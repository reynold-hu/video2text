"""本地服务：粘贴链接 → 提取文字 → 下载 txt。

没有数据库也没有队列 —— 任务就是内存里一个 dict，跑完把结果留着供下载。
本地单人使用，够用且好排查。
"""

import threading
import traceback
import urllib.parse
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, Response

from core import asr, audio, cookies, pipeline, router, writer
from core.schemas import Transcript

ROOT = Path(__file__).resolve().parent
PORT = 8756

app = FastAPI(title="video2text")


@dataclass
class Job:
    id: str
    status: str = "running"  # running | done | error
    stage: str = "准备中…"
    logs: list[str] = field(default_factory=list)
    transcript: Transcript | None = None
    error: str = ""

    def log(self, message: str) -> None:
        self.stage = message
        self.logs.append(message)


_jobs: dict[str, Job] = {}
_lock = threading.Lock()


@app.on_event("startup")
def _startup() -> None:
    # 清掉上次异常退出留下的临时音频
    audio.sweep()
    # 提前在后台探测 cookie，别让第一次点"提取"卡在解密浏览器数据库上
    threading.Thread(target=cookies.probe, daemon=True).start()


@app.get("/")
def index() -> FileResponse:
    return FileResponse(ROOT / "static" / "index.html")


@app.get("/api/cookies")
def api_cookies(refresh: bool = False) -> dict:
    """登录态探测。B站没登录的话必须让前端显式提示，否则用户会以为工具坏了。"""
    return {
        "sites": cookies.summary(),
        "browsers": {
            b: {"available": i["available"], "total": i["total"], "sites": i["sites"]}
            for b, i in cookies.probe(refresh=refresh).items()
        },
    }


@app.get("/api/engines")
def api_engines() -> dict:
    return {"engines": asr.available()}


@app.post("/api/parse")
def api_parse(payload: dict) -> dict:
    text = (payload or {}).get("url", "")
    engine = (payload or {}).get("engine", "mlx")
    # 空字符串表示"自动检测"
    language = (payload or {}).get("language", "zh") or None

    if not (text or "").strip():
        raise HTTPException(status_code=400, detail="请先粘贴链接")

    job = Job(id=uuid.uuid4().hex[:12])
    with _lock:
        # 只保留最近 20 个任务，避免长时间运行内存里堆着结果
        if len(_jobs) > 20:
            for k in list(_jobs)[:-20]:
                _jobs.pop(k, None)
        _jobs[job.id] = job

    threading.Thread(target=_run_job, args=(job, text, engine, language), daemon=True).start()
    return {"job_id": job.id}


@app.get("/api/job/{job_id}")
def api_job(job_id: str) -> dict:
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在或已过期")

    out = {"id": job.id, "status": job.status, "stage": job.stage, "logs": job.logs[-8:]}
    if job.status == "error":
        out["error"] = job.error
    if job.status == "done" and job.transcript:
        t = job.transcript.to_dict()
        out["result"] = {
            "platform": t["platform"],
            "platform_name": router.PLATFORM_NAMES.get(t["platform"], t["platform"]),
            "title": t["title"],
            "author": t["author"],
            "created": t["created"],
            "url": t["url"],
            "source": t["source"],
            "engine": t["engine"],
            "extra": t["extra"],
            "count": len(t["segments"]),
            "duration": t["duration"],
            "text": t["text"],
            "formats": [
                {"key": k, "label": v[0], "suffix": v[1]} for k, v in writer.FORMATS.items()
            ],
        }
    return out


@app.get("/api/download/{job_id}/{fmt}")
def api_download(job_id: str, fmt: str) -> Response:
    job = _jobs.get(job_id)
    if not job or job.status != "done" or not job.transcript:
        raise HTTPException(status_code=404, detail="结果不存在或已过期")

    try:
        filename, content = writer.render(job.transcript, fmt)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    # 文件名可能含中文，用 RFC 5987 编码，否则浏览器会存成乱码
    quoted = urllib.parse.quote(filename)
    return Response(
        content=content,
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quoted}"},
    )


def _run_job(job: Job, text: str, engine: str, language: str | None) -> None:
    try:
        job.transcript = pipeline.run(
            text, engine=engine, language=language, on_progress=job.log
        )
        job.status = "done"
    except pipeline.PipelineError as e:
        job.status = "error"
        job.error = str(e)
    except Exception as e:  # 兜底，别让后台线程静默死掉
        job.status = "error"
        job.error = f"内部错误：{e}"
        traceback.print_exc()


def main() -> None:
    import argparse

    import uvicorn

    parser = argparse.ArgumentParser(description="video2text 本地服务")
    parser.add_argument("--port", type=int, default=PORT, help=f"监听端口（默认 {PORT}）")
    args = parser.parse_args()

    print(f"\n  video2text 已启动 →  http://127.0.0.1:{args.port}\n")
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
