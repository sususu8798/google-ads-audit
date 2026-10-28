"""报表解析与聚合测试。"""
import os
from src import csv_parser

FIX = os.path.join(os.path.dirname(__file__), "fixtures", "sample_google_ads.csv")


def test_header_detection_skips_metadata():
    with open(FIX, "rb") as f:
        content = f.read()
    r = csv_parser.parse_report_file("sample_google_ads.csv", content)
    # 前两行为元数据，第 3 行（索引 2）才是表头
    assert r["preview"]["header_row_index"] == 2
    assert r["preview"]["column_count"] == 60


def test_counts_match_prd_example():
    with open(FIX, "rb") as f:
        content = f.read()
    r = csv_parser.parse_report_file("sample_google_ads.csv", content)
    p = r["preview"]
    assert p["data_rows"] == 78
    assert p["url_count"] == 10
    assert p["campaign_count"] == 14
    assert p["ad_group_count"] == 9
    assert p["duplicate_count"] == 0


def test_aggregated_totals():
    with open(FIX, "rb") as f:
        content = f.read()
    r = csv_parser.parse_report_file("sample_google_ads.csv", content)
    tc = sum(a["clicks"] for a in r["aggregated"])
    ti = sum(a["impressions"] for a in r["aggregated"])
    tco = round(sum(a["cost"] for a in r["aggregated"]), 2)
    tconv = sum(a["conversions"] for a in r["aggregated"])
    assert tc == 296
    assert ti == 3844
    assert tco == 3440.36
    assert tconv == 8
    # 汇总结论不与数据行重复计入
    assert len(r["aggregated"]) == 10


def test_zero_conversions_cpa_is_none():
    csv_text = (
        "Campaign,Final URL,Clicks,Impr.,Cost,Conversions,Currency code\n"
        "C1,https://example.com/p1,10,100,20.00,0,CNY\n"
    )
    r = csv_parser.parse_report_file("t.csv", csv_text.encode("utf-8"))
    a = r["aggregated"][0]
    assert a["conversions"] == 0
    assert a["cpa"] is None  # 零转化 -> CPA 不显示为 0


def test_no_impressions_ctr_is_none():
    csv_text = (
        "Campaign,Final URL,Clicks,Impr.,Cost,Conversions,Currency code\n"
        "C1,https://example.com/p1,0,0,0.00,0,CNY\n"
    )
    r = csv_parser.parse_report_file("t.csv", csv_text.encode("utf-8"))
    a = r["aggregated"][0]
    assert a["ctr"] is None  # 零展示 -> 不计算 CTR


def test_multicurrency_not_merged():
    csv_text = (
        "Campaign,Final URL,Clicks,Impr.,Cost,Conversions,Currency code\n"
        "C1,https://example.com/p1,10,100,20.00,1,USD\n"
        "C1,https://example.com/p1,10,100,150.00,1,CNY\n"
    )
    r = csv_parser.parse_report_file("t.csv", csv_text.encode("utf-8"))
    assert len(r["aggregated"]) == 2  # 不同币种分别聚合，不合并
    curs = {a["currency"] for a in r["aggregated"]}
    assert curs == {"USD", "CNY"}


def test_duplicate_rows_deduplicated():
    csv_text = (
        "Campaign,Final URL,Clicks,Impr.,Cost,Conversions,Currency code\n"
        "C1,https://example.com/p1,10,100,20.00,1,CNY\n"
        "C1,https://example.com/p1,10,100,20.00,1,CNY\n"
    )
    r = csv_parser.parse_report_file("t.csv", csv_text.encode("utf-8"))
    assert r["preview"]["duplicate_count"] == 1
    assert len(r["aggregated"]) == 1


def test_chinese_headline_description_headers():
    csv_content = (
        "最终到达 URL,广告系列,广告组,点击,展示,花费,转化,标题 1,标题 2,说明 1\n"
        "https:// example.com/a,系列1,组1,10,100,50.00,2,50公斤实验台,精准称重,支持定制规格\n"
        "https:// example.com/a,系列1,组2,5,60,30.00,1,台面防静电,稳定耐用\n"
    ).replace(" ", "")
    r = csv_parser.parse_report_file("cn.csv", csv_content.encode("utf-8"))
    agg = r["aggregated"][0]
    assert "50公斤实验台" in agg["headlines_sample"]
    assert "台面防静电" in agg["headlines_sample"]
    assert "支持定制规格" in agg["descriptions_sample"]


def test_chinese_headline_description_headers():
    csv_content = (
        "Final URL,Campaign,Ad group,Clicks, Impressions, Cost, Conversions,标题 1,标题 2,说明 1\n"
        "https://example.com/a,系列1,组1,10,100,50.00,2,50公斤实验台,精准称重,支持定制规格\n"
        "https://example.com/a,系列1,组2,5,60,30.00,1,台面防静电,稳定耐用,\n"
    )
    r = csv_parser.parse_report_file("cn.csv", csv_content.encode("utf-8"))
    assert r["aggregated"], "应能聚合出 URL"
    agg = r["aggregated"][0]
    assert "50公斤实验台" in agg["headlines_sample"]
    assert "台面防静电" in agg["headlines_sample"]
    assert "支持定制规格" in agg["descriptions_sample"]


def test_duplicate_warning_only_for_effective_rows():
    # 有 URL 的数据行重复 → 提示
    csv_content = (
        "Final URL,Campaign,Ad group,Clicks,Impr.,Cost,Conversions\n"
        "https://example.com/a,系列1,组1,10,100,50.00,2\n"
        "https://example.com/a,系列1,组1,10,100,50.00,2\n"
    )
    r = csv_parser.parse_report_file("dup_url.csv", csv_content.encode("utf-8"))
    assert any("重复" in w for w in r["warnings"])
    # 无 URL 的总计行重复 → 静默
    csv_content2 = (
        "Final URL,Campaign,Ad group,Clicks,Impr.,Cost,Conversions\n"
        "https://example.com/a,系列1,组1,10,100,50.00,2\n"
        ",总计,,74,961,860.09,2.00\n"
        ",总计,,74,961,860.09,2.00\n"
    )
    r2 = csv_parser.parse_report_file("dup_total.csv", csv_content2.encode("utf-8"))
    assert not any("重复" in w for w in r2["warnings"])
    assert r2["preview"]["duplicate_count"] == 1  # 计数保留，只是不提示
