"""生成与 PRD 第 5 节描述一致的 Google Ads CSV 样例（用于测试与演示）。

结构：第 1-2 行为报表名称/日期范围（元数据），第 3 行为 60 列字段表头。
数据：78 条广告行，10 个不同 Final URL，14 个 Campaign，9 个 Ad group；
汇总：点击 296、展示 3844、费用 CNY 3,440.36、转化 8。
另含 1 行汇总行（Campaign=Total）用于验证汇总行不被重复计入。
"""
import csv
import os

OUT = os.path.join(os.path.dirname(__file__), "fixtures", "sample_google_ads.csv")
os.makedirs(os.path.dirname(OUT), exist_ok=True)

# 60 列字段表头（含 Headline 1-15、Description 1-4 等）
headers = [
    "Campaign", "Ad group", "Ad type", "Ad status", "Final URL", "Mobile final URL",
]
headers += [f"Headline {i}" for i in range(1, 16)]      # 15
headers += [f"Description {i}" for i in range(1, 5)]    # 4
headers += [
    "Status reasons", "Clicks", "Impr.", "CTR", "Currency code", "Avg. CPC",
    "Cost", "Conv. rate", "Conversions", "Cost / conv.",
]
# 补足到 60 列（填充其它常见 Google Ads 列）
extra = [
    "Search keyword", "Search impression share", "Search top IS", "Search abs. top IS",
    "Campaign ID", "Ad group ID", "Ad ID", "Device", "Country", "Language",
    "Network", "Conversion value", "View-through conv.", "All conv.", "Cost / all conv.",
    "Impr. (abs. top) %", "Impr. (top) %", "Engagement rate", "Interactions",
    "Interaction rate", "Avg. position", "Quality Score", "Landing page experience",
    "Expected CTR", "Ad relevance",
]
headers += extra
assert len(headers) == 60, len(headers)

URLS = [
    "https://www.oimchemical.com/product/category/molecular-sieve",
    "https://www.oimchemical.com/product/air-seperation-plant-molecular-sieve13x",
    "https://www.oimchemical.com/product/3a-molecular-sieve",
    "https://www.oimchemical.com/product/4a-molecular-sieve",
    "https://www.oimchemical.com/product/5a-molecular-sieve",
    "https://www.oimchemical.com/product/13x-molecular-sieve",
    "https://www.oimchemical.com/product/activated-alumina",
    "https://www.oimchemical.com/product/silica-gel",
    "https://www.oimchemical.com/product/carbon-molecular-sieve",
    "https://www.oimchemical.com/contact-us",
]
HEADLINES = [
    "High Quality Molecular Sieve", "Factory Price 13X Zeolite", "Molecular Sieve 3A 4A 5A",
    "OIM Chemical Supplier", "CMS For PSA Nitrogen", "Best Molecular Sieve Manufacturer",
]
DESCRIPTIONS = [
    "Supply molecular sieve with competitive price and fast delivery.",
    "ISO certified molecular sieve for air separation and PSA.",
]

# 行级指标分布（保证合计精确）
n = 78
clicks = [4] * 62 + [3] * 16                      # sum 296
impr = [50] * 22 + [49] * 56                      # sum 3844
cents = [4411] * 56 + [4410] * 22                 # sum 344036 -> 3440.36
conv_assign = set([0, 10, 20, 30, 40, 50, 60, 70])  # 8 行各 1 转化

rows = []
for i in range(n):
    url = URLS[i % 10]
    camp = f"Campaign {(i % 14) + 1}"
    ag = f"Ad Group {(i % 9) + 1}"
    c = clicks[i]
    im = impr[i]
    cost = cents[i] / 100.0
    conv = 1 if i in conv_assign else 0
    ctr = round(c / im * 100, 2)
    avg_cpc = round(cost / c, 2) if c else 0.0
    cvr = round(conv / c * 100, 2) if c else 0.0
    cpa = round(cost / conv, 2) if conv else 0.0
    row = {h: "" for h in headers}
    row["Campaign"] = camp
    row["Ad group"] = ag
    row["Ad type"] = "Responsive search ad"
    row["Ad status"] = "Enabled"
    row["Final URL"] = url
    row["Mobile final URL"] = url
    for j in range(15):
        row[f"Headline {j+1}"] = HEADLINES[(i + j) % len(HEADLINES)]
    for j in range(4):
        row[f"Description {j+1}"] = DESCRIPTIONS[(i + j) % len(DESCRIPTIONS)]
    row["Status reasons"] = ""
    row["Clicks"] = c
    row["Impr."] = im
    row["CTR"] = f"{ctr}%"
    row["Currency code"] = "CNY"
    row["Avg. CPC"] = f"CNY {avg_cpc:.2f}"
    row["Cost"] = f"CNY {cost:.2f}"
    row["Conv. rate"] = f"{cvr}%"
    row["Conversions"] = conv
    row["Cost / conv."] = f"CNY {cpa:.2f}" if conv else "-"
    rows.append(row)

# 汇总行
summary = {h: "" for h in headers}
summary["Campaign"] = "Total"
summary["Clicks"] = 296
summary["Impr."] = 3844
summary["CTR"] = "7.70%"
summary["Cost"] = "CNY 3440.36"
summary["Conversions"] = 8

with open(OUT, "w", newline="", encoding="utf-8-sig") as f:
    w = csv.writer(f)
    w.writerow(["Google Ads Report (Search)"])            # 元数据行 1
    w.writerow(["Date range: 2026-09-10 to 2026-09-16"])  # 元数据行 2
    w.writerow(headers)                                   # 第 3 行：字段表头
    for r in rows:
        w.writerow([r[h] for h in headers])
    w.writerow([summary[h] for h in headers])              # 汇总行

print("written:", OUT, "data_rows:", len(rows))
