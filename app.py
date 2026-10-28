"""FastAPI 应用：提供单 URL 检测、报表解析与联合诊断 API，并托管前端。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi import FastAPI, File, UploadFile, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from typing import List, Optional

from src import audit, config, csv_parser

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")

app = FastAPI(title="Google Ads 落地页质量诊断工具", version="1.0")

# 允许任意来源跨源访问：页面可能通过 file:// 或预览代理打开，
# 前端会强制回连 127.0.0.1:8000，需要 CORS 放行
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def no_cache_static(request: Request, call_next):
    """前端资源禁止浏览器缓存。

    本地工具会频繁迭代 index.html / app.js / styles.css，浏览器一旦缓存旧版，
    用户就会一直看到旧文案（已多次踩坑）。no-cache 让浏览器每次带回源校验，
    文件没变时仍可用 304，几乎没有额外开销。
    """
    resp = await call_next(request)
    path = request.url.path
    if path.startswith("/static/") or path == "/" or path.endswith((".js", ".css", ".html")):
        resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        resp.headers["Pragma"] = "no-cache"
        resp.headers["Expires"] = "0"
    return resp


class CheckRequest(BaseModel):
    url: str
    industry: Optional[str] = None
    country: Optional[str] = None
    language: Optional[str] = None
    goal: Optional[str] = None
    product: Optional[str] = None
    keywords: Optional[List[str]] = None
    ad_headlines: Optional[List[str]] = None
    ad_descriptions: Optional[List[str]] = None


class BatchRequest(BaseModel):
    urls: List[str]
    industry: Optional[str] = None
    country: Optional[str] = None
    language: Optional[str] = None
    goal: Optional[str] = None
    product: Optional[str] = None
    keywords: Optional[List[str]] = None
    ad_headlines: Optional[List[str]] = None
    ad_descriptions: Optional[List[str]] = None


@app.get("/api/health")
async def health():
    return {"status": "ok", "weights": {k: w for k, _, w in config.settings.dimensions}}


@app.post("/api/check-url")
async def check_url(req: CheckRequest):
    if not req.url:
        raise HTTPException(status_code=400, detail="URL 不能为空")
    try:
        report = audit.analyze_page_with_input(req.url, req.model_dump())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return JSONResponse(content=report)


@app.post("/api/check-urls")
async def check_urls(req: BatchRequest):
    raw = [u.strip() for u in (req.urls or []) if u and u.strip()]
    if not raw:
        raise HTTPException(status_code=400, detail="至少提供 1 个 URL")
    # 去重（保留首次出现顺序，忽略大小写）
    seen, dedup = set(), []
    for u in raw:
        ku = u.lower()
        if ku in seen:
            continue
        seen.add(ku)
        dedup.append(u)
    MAX = 200
    if len(dedup) > MAX:
        raise HTTPException(status_code=400, detail=f"URL 数量超出上限（{MAX}），请改用「广告报表分析」上传")
    try:
        data = await audit.analyze_url_list(dedup, req.model_dump())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return JSONResponse(content=data)


@app.post("/api/analyze-report")
async def analyze_report(file: UploadFile = File(...)):
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="文件为空")
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in (".csv", ".xlsx", ".xls"):
        raise HTTPException(status_code=400, detail="仅支持 CSV / XLSX 文件")
    try:
        parsed = csv_parser.parse_report_file(file.filename or "report.csv", content)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=422, detail=f"解析失败：{e}")
    if parsed.get("error"):
        raise HTTPException(status_code=422, detail=parsed["error"])
    # 完整联合诊断（抓取每个 URL）
    try:
        full = await audit.analyze_report(parsed)
    except Exception as e:  # noqa: BLE001
        # 解析成功但抓取失败，退回仅展示解析结果
        return JSONResponse(content={
            "type": "report", "preview": parsed["preview"], "warnings": parsed["warnings"],
            "summary": None, "urls": [], "parse_only": True,
            "error": f"页面抓取阶段异常：{e}",
        })
    return JSONResponse(content=full)


@app.get("/")
async def index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


if not os.path.isdir(STATIC_DIR):
    os.makedirs(STATIC_DIR, exist_ok=True)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=config.settings.host, port=config.settings.port)
