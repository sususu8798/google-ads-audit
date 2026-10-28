"""robots.txt 抓取与规则匹配。

设计原则：
- 只回答「这个路径是否被禁止抓取」这一件可确定的事，不冒充 Google 实际抓取结论。
- 复用 SSRF 安全抓取器，不另开网络通道。
- 按 host 缓存，避免报表模式下每个 URL 都重抓一次。
"""
import re
from typing import Dict, List, Optional, Tuple

# host -> robots.txt 文本（None 表示抓取失败/不存在）
# 说明：Web 服务下这是进程内缓存，最坏情况是重复抓取一次，不影响正确性。
_CACHE: Dict[str, Optional[str]] = {}


def _split_group(lines: List[str]) -> List[Tuple[List[str], List[Tuple[str, str]]]]:
    """把 robots.txt 解析成 [(user-agents, [(allow|disallow, value)])]。"""
    groups: List[Tuple[List[str], List[Tuple[str, str]]]] = []
    agents: List[str] = []
    rules: List[Tuple[str, str]] = []
    for raw in lines:
        line = raw.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        key, val = line.split(":", 1)
        key = key.strip().lower()
        val = val.strip()
        if key == "user-agent":
            if rules:
                groups.append((agents, rules))
                agents, rules = [], []
            agents.append(val.lower())
        elif key in ("disallow", "allow"):
            if not agents:
                agents = ["*"]
            rules.append((key, val))
    if agents or rules:
        groups.append((agents, rules))
    return groups


def _glob_match(pattern: str, path: str) -> bool:
    """robots.txt 通配符匹配：* 任意多字符，$ 结尾锚定。"""
    anchored_end = pattern.endswith("$")
    if anchored_end:
        pattern = pattern[:-1]
    parts = pattern.split("*")
    # 每段必须按顺序出现
    idx = 0
    for i, part in enumerate(parts):
        if part == "":
            continue
        found = path.find(part, idx)
        if found < 0:
            return False
        idx = found + len(part)
    if anchored_end:
        return idx == len(path)
    return True


def disallows(robots_txt: Optional[str], path: str, agent: str = "*") -> Optional[bool]:
    """判断路径是否被禁止抓取。

    返回 None 表示无法判断（没有 robots.txt 或没有可用规则）。
    """
    if robots_txt is None:
        return None
    agent = (agent or "*").lower()
    groups = _split_group(robots_txt.splitlines())
    if not groups:
        return None

    # 选组：优先指定 agent（如 AdsBot），否则回退 *
    chosen: Optional[List[Tuple[str, str]]] = None
    for ags, rules in groups:
        if agent in ags:
            chosen = rules
            break
    if chosen is None:
        for ags, rules in groups:
            if "*" in ags:
                chosen = rules
                break
    if not chosen:
        return None

    # 最长匹配优先；空 Disallow 视为允许全部
    best: Optional[Tuple[str, str]] = None
    for kind, val in chosen:
        if val == "":
            continue
        if path.startswith(val) or _glob_match(val, path):
            if best is None or len(val) > len(best[1]):
                best = (kind, val)
    if best is None:
        return None
    return best[0] == "disallow"


async def get_robots(client, host: str) -> Optional[str]:
    """抓取并缓存指定 host 的 robots.txt（失败返回 None）。"""
    if host in _CACHE:
        return _CACHE[host]
    from .fetcher import fetch_url

    fr = await fetch_url(f"https://{host}/robots.txt", client)
    text: Optional[str] = None
    if fr.ok and fr.content:
        try:
            text = fr.content.decode("utf-8", "ignore")
        except Exception:  # noqa: BLE001
            text = None
    _CACHE[host] = text
    return text


def reset_cache() -> None:
    _CACHE.clear()


def path_of(url: str) -> str:
    from urllib.parse import urlparse

    u = urlparse(url)
    path = u.path or "/"
    if u.query:
        path += "?" + u.query
    return path
