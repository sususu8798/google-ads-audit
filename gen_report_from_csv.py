"""把真实的 Google Ads 报表 CSV/XLSX 跑成自包含报告 HTML（无需后端即可打开）。

用法：
  python gen_report_from_csv.py <报表文件路径> [输出文件名]

示例：
  python gen_report_from_csv.py ~/Desktop/"Ad report.csv"
"""
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from src import csv_parser, audit

BASE = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(BASE, "static")


def main():
    if len(sys.argv) < 2:
        print("用法: python gen_report_from_csv.py <报表文件>")
        sys.exit(1)
    path = sys.argv[1]
    out_name = sys.argv[2] if len(sys.argv) > 2 else "report_" + os.path.splitext(os.path.basename(path))[0] + ".html"

    with open(path, "rb") as f:
        content = f.read()
    print("解析报表：", path)
    parsed = csv_parser.parse_report_file(os.path.basename(path), content)
    p = parsed["preview"]
    print(f"  => {p['data_rows']} 行数据 / {p['url_count']} 个唯一 URL / {p['column_count']} 列")

    print("正在对每个 URL 执行安全抓取与诊断…")
    data = asyncio.run(audit.analyze_report(parsed))
    s = data["summary"]
    print(f"  => 总花费 {s['total_cost']} / 总点击 {s['total_clicks']} / 总转化 {s['total_conversions']} / 优先级 {s['priority_counts']}")

    js = json.dumps(data, ensure_ascii=False).replace("<", "\\u003c")
    with open(os.path.join(STATIC, "index.html"), encoding="utf-8") as f:
        html = f.read()
    with open(os.path.join(STATIC, "styles.css"), encoding="utf-8") as f:
        css = f.read()
    with open(os.path.join(STATIC, "app.js"), encoding="utf-8") as f:
        appjs = f.read()

    html = html.replace('<link rel="stylesheet" href="/static/styles.css">', f"<style>\n{css}\n</style>")
    html = html.replace('<script src="/static/app.js"></script>',
                        f"<script>window.__DEMO_REPORT__ = {js};</script>\n<script>\n{appjs}\n</script>")

    out = os.path.join(BASE, out_name)
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)
    print("已生成报告：", out)


if __name__ == "__main__":
    main()
