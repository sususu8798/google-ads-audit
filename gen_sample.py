"""生成自包含演示报告 sample_report.html（内嵌一次真实抓取结果，无需后端即可打开）。

用法：
  python gen_sample.py [URL]
默认抓取 https://example.com/ 作为演示样本。
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from src import audit

BASE = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(BASE, "static")


def main():
    url = sys.argv[1] if len(sys.argv) > 1 else "https://example.com/"
    print("正在抓取并分析：", url)
    report = audit.analyze_page_with_input(url, {
        "url": url, "industry": "演示", "country": "全球", "language": "英语",
        "goal": "询盘", "product": "示例产品",
        "keywords": ["example", "demo"],
        "ad_headlines": ["Example Product", "Quality Service"],
        "ad_descriptions": ["We provide example product with good service."],
    })
    js = json.dumps(report, ensure_ascii=False).replace("<", "\\u003c")

    with open(os.path.join(STATIC, "index.html"), encoding="utf-8") as f:
        html = f.read()
    with open(os.path.join(STATIC, "styles.css"), encoding="utf-8") as f:
        css = f.read()
    with open(os.path.join(STATIC, "app.js"), encoding="utf-8") as f:
        appjs = f.read()

    # 用内联样式替换外链样式；用内联脚本 + 演示数据替换外链脚本
    html = html.replace('<link rel="stylesheet" href="/static/styles.css">', f"<style>\n{css}\n</style>")
    html = html.replace('<script src="/static/app.js"></script>',
                        f"<script>window.__DEMO__ = {js};</script>\n<script>\n{appjs}\n</script>")

    out = os.path.join(BASE, "sample_report.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)
    print("已生成演示报告：", out)


if __name__ == "__main__":
    main()
