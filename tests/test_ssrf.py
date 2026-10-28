"""SSRF 防护测试。"""
import pytest

from src.fetcher import _validate_url, SSRFError


def test_blocks_localhost():
    with pytest.raises(SSRFError):
        _validate_url("http://localhost/admin")


def test_blocks_127():
    with pytest.raises(SSRFError):
        _validate_url("http://127.0.0.1/")

def test_blocks_cloud_metadata():
    with pytest.raises(SSRFError):
        _validate_url("http://169.254.169.254/latest/meta-data/")


def test_blocks_private_10():
    with pytest.raises(SSRFError):
        _validate_url("http://10.0.0.5/")


def test_blocks_non_http():
    with pytest.raises(SSRFError):
        _validate_url("file:///etc/passwd")
    with pytest.raises(SSRFError):
        _validate_url("ftp://example.com/")


def test_allows_public_https():
    # 不应抛异常（仅做格式与地址校验，不实际请求）
    _validate_url("https://www.example.com/product/p1")
