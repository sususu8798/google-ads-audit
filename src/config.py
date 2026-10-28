"""运行时配置：从环境变量读取，提供默认值。所有阈值/权重均可配置。"""
import os
from dataclasses import dataclass, field


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def _float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


@dataclass
class Settings:
    host: str = field(default_factory=lambda: os.getenv("HOST", "0.0.0.0"))
    port: int = field(default_factory=lambda: _int("PORT", 8000))

    # 抓取限制
    fetch_timeout: int = field(default_factory=lambda: _int("FETCH_TIMEOUT", 15))
    max_redirects: int = field(default_factory=lambda: _int("MAX_REDIRECTS", 5))
    max_response_bytes: int = field(default_factory=lambda: _int("MAX_RESPONSE_BYTES", 5 * 1024 * 1024))
    user_agent: str = "GoogleAdsLandingPageAuditor/1.0 (+internal-tool)"

    # 评分维度权重（默认，管理员可调整；总和应为 100）
    # 以落地页质量为主，兼顾广告相关性：内容 25 / 信任 25 / 转化 10 / 可访问 15 / 广告相关性 15 / 移动 10（质量合计 85%）
    w_accessibility: float = field(default_factory=lambda: _float("W_ACCESSIBILITY", 15))
    w_ad_relevance: float = field(default_factory=lambda: _float("W_AD_RELEVANCE", 15))
    w_content: float = field(default_factory=lambda: _float("W_CONTENT", 25))
    w_conversion: float = field(default_factory=lambda: _float("W_CONVERSION", 10))
    w_mobile_perf: float = field(default_factory=lambda: _float("W_MOBILE_PERF", 10))
    w_trust: float = field(default_factory=lambda: _float("W_TRUST", 25))

    # 优先级阈值
    p1_min_cost: float = field(default_factory=lambda: _float("P1_MIN_COST", 200))
    small_sample_clicks: int = field(default_factory=lambda: _int("SMALL_SAMPLE_CLICKS", 30))
    high_cpa_factor: float = field(default_factory=lambda: _float("HIGH_CPA_FACTOR", 2.0))

    @property
    def dimensions(self):
        return [
            ("accessibility", "可访问性与技术稳定性", self.w_accessibility),
            ("ad_relevance", "广告—页面相关性", self.w_ad_relevance),
            ("content", "内容与产品信息", self.w_content),
            ("conversion", "询盘转化体验", self.w_conversion),
            ("mobile_perf", "移动端与性能", self.w_mobile_perf),
            ("trust", "信任与透明度", self.w_trust),
        ]


settings = Settings()
