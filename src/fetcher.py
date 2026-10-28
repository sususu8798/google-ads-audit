"""SSRF 防护的网页抓取。

安全原则（对应 PRD 第 10 节）：
- 仅允许 http/https
- 解析 DNS 后校验目标 IP，拦截私网 / 链路本地 / 云元数据地址
- 每次跳转重新校验目标主机
- 超时、最大响应体、最大跳转次数限制
"""
import ipaddress
import socket
from dataclasses import dataclass, field
from typing import List, Optional
from urllib.parse import urlparse

import httpx

from . import config

# 受保护的地址范围（私网 / 回环 / 链路本地 / 云元数据 / 唯一本地地址）
_BLOCKED_NETWORKS = [
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("100.64.0.0/10"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),   # 含 169.254.169.254 云元数据
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.0.0.0/24"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("198.18.0.0/15"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
    ipaddress.ip_network("::/128"),
]


class SSRFError(Exception):
    pass


def _is_blocked_ip(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        # 非 IP 字面量（如主机名），交给 DNS 解析路径处理，不在此拦截
        return False
    for net in _BLOCKED_NETWORKS:
        if addr.version == net.version and addr in net:
            return True
    return False


def _validate_host(host: str) -> None:
    """解析主机名并校验所有解析到的 IP。"""
    if not host:
        raise SSRFError("缺少主机名")
    # 直接是 IP 的情况
    try:
        if _is_blocked_ip(host):
            raise SSRFError(f"目标地址被禁止：{host}")
    except ValueError:
        pass
    # 解析域名
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as e:
        raise SSRFError(f"无法解析主机 {host}：{e}")
    ips = {info[4][0] for info in infos}
    if not ips:
        raise SSRFError(f"主机 {host} 未解析到可用地址")
    for ip in ips:
        if _is_blocked_ip(ip):
            raise SSRFError(f"目标主机解析到受保护地址 {ip}（{host}）")


def _validate_url(url: str) -> str:
    """校验协议与主机的合法性，返回规范化后的 URL。"""
    if not url or not isinstance(url, str):
        raise SSRFError("URL 为空")
    u = url.strip()
    parsed = urlparse(u)
    if parsed.scheme not in ("http", "https"):
        raise SSRFError(f"仅支持 http/https 协议，收到：{parsed.scheme or '(无)'}")
    if not parsed.hostname:
        raise SSRFError("URL 缺少主机名")
    _validate_host(parsed.hostname)
    return u


@dataclass
class FetchResult:
    ok: bool
    status_code: Optional[int] = None
    final_url: Optional[str] = None
    error: Optional[str] = None
    error_type: Optional[str] = None  # ssrf | timeout | http | dns | too_large | redirect
    redirect_chain: List[str] = field(default_factory=list)
    headers: dict = field(default_factory=dict)
    content: bytes = b""
    elapsed_ms: int = 0


async def fetch_url(url: str, client: Optional[httpx.AsyncClient] = None) -> FetchResult:
    """安全抓取单个 URL（不自动跟随跳转，便于逐步校验与记录跳转链）。"""
    own_client = client is None
    try:
        _validate_url(url)
    except SSRFError as e:
        return FetchResult(ok=False, error=str(e), error_type="ssrf")

    if own_client:
        client = httpx.AsyncClient(
            timeout=httpx.Timeout(config.settings.fetch_timeout),
            follow_redirects=False,
            headers={"User-Agent": config.settings.user_agent},
            verify=True,
        )
    chain: List[str] = []
    current = url
    try:
        for _ in range(config.settings.max_redirects + 1):
            _validate_url(current)  # 每次跳转重新校验
            resp = await client.get(current)
            chain.append(current)
            if resp.is_redirect and resp.headers.get("location"):
                loc = resp.headers["location"]
                # 相对跳转补全
                from urllib.parse import urljoin
                current = urljoin(current, loc)
                continue
            # 读取响应体（带大小上限）
            try:
                content = await resp.aread()
            except httpx.ReadError:
                content = b""
            if len(content) > config.settings.max_response_bytes:
                return FetchResult(
                    ok=False, status_code=resp.status_code, final_url=current,
                    error=f"响应体超过上限 {config.settings.max_response_bytes} 字节",
                    error_type="too_large", redirect_chain=chain,
                    headers=dict(resp.headers), content=b"",
                )
            return FetchResult(
                ok=(200 <= resp.status_code < 300), status_code=resp.status_code, final_url=current,
                redirect_chain=chain, headers=dict(resp.headers), content=content,
                elapsed_ms=int(resp.elapsed.total_seconds() * 1000),
            )
        return FetchResult(
            ok=False, final_url=current, status_code=None,
            error=f"跳转次数超过上限 {config.settings.max_redirects}",
            error_type="redirect", redirect_chain=chain,
        )
    except httpx.TimeoutException:
        return FetchResult(ok=False, final_url=current, error="请求超时", error_type="timeout", redirect_chain=chain)
    except httpx.ConnectError as e:
        return FetchResult(ok=False, final_url=current, error=f"连接失败：{e}", error_type="http", redirect_chain=chain)
    except (httpx.HTTPError, Exception) as e:  # noqa: BLE001
        return FetchResult(ok=False, final_url=current, error=f"请求异常：{e}", error_type="http", redirect_chain=chain)
    finally:
        if own_client:
            await client.aclose()
