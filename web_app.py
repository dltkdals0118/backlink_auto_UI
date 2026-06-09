"""로컬 웹 UI 서버 — 브라우저에서 자동 등록을 실행하고 실시간 로그를 확인.

실행:
    python web_app.py
    # 또는: uvicorn web_app:app --reload
브라우저에서 http://127.0.0.1:8000 접속.
"""
from __future__ import annotations

import json
import queue
import threading
import uuid
from dataclasses import asdict
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel

from config import settings
from src import ip_rotator
from src.humanize import HumanSettings
from src.runner import RunOptions, run_batch

app = FastAPI(title="서울컴퓨터자수 자동 등록 UI")

BASE_DIR = Path(__file__).parent
INDEX_HTML = BASE_DIR / "web" / "index.html"

_DONE = object()


class Job:
    def __init__(self) -> None:
        self.queue: "queue.Queue" = queue.Queue()
        self.result: dict | None = None
        self.running = True


# 한 번에 하나의 작업만 허용 (Playwright 브라우저 1개 가정)
_jobs: dict[str, Job] = {}
_lock = threading.Lock()


class HumanRequest(BaseModel):
    enabled: bool = False
    device: str = "desktop"
    referer_mode: str = "search"
    min_delay_ms: int = 400
    max_delay_ms: int = 1500
    scroll_min: int = 2
    scroll_max: int = 6
    mouse_min: int = 3
    mouse_max: int = 8
    typing: bool = True
    use_ai: bool = True


class RunRequest(BaseModel):
    url: str | None = None
    topic: str | None = None
    show_browser: bool = False
    dry_run: bool = False
    backlink_url: str | None = None
    backlink_text: str | None = None
    repeat: int = 1
    rotate_ip: bool = False
    rotate_every: int = 1
    mobile: bool = False
    human: HumanRequest = HumanRequest()


def _worker(job: Job, options: RunOptions) -> None:
    def log(line: str) -> None:
        job.queue.put(str(line))

    try:
        result = run_batch(options, log=log)
        job.result = asdict(result)
    except Exception as exc:  # noqa: BLE001
        log(f"오류: {exc}")
        job.result = {
            "code": 1,
            "success": False,
            "message": str(exc),
            "subject": None,
            "result_url": None,
        }
    finally:
        job.running = False
        job.queue.put(_DONE)


@app.get("/")
def index() -> FileResponse:
    return FileResponse(INDEX_HTML)


@app.get("/api/status")
def status() -> JSONResponse:
    key = settings.openai_api_key.strip()
    key_ok = bool(key) and not key.startswith("sk-...") and len(key) >= 20
    busy = any(j.running for j in _jobs.values())
    adb_ok, adb_msg = ip_rotator.adb_available(settings.adb_cmd)
    return JSONResponse(
        {
            "key_ok": key_ok,
            "model": settings.openai_model,
            "target_url": settings.target_url,
            "busy": busy,
            "adb_ok": adb_ok,
            "adb_msg": adb_msg,
        }
    )


@app.get("/api/current-ip")
def current_ip() -> JSONResponse:
    return JSONResponse({"ip": ip_rotator.get_public_ip()})


@app.post("/api/run")
def run(req: RunRequest) -> JSONResponse:
    with _lock:
        if any(j.running for j in _jobs.values()):
            return JSONResponse(
                {"error": "이미 실행 중인 작업이 있습니다."}, status_code=409
            )
        job = Job()
        job_id = uuid.uuid4().hex
        _jobs[job_id] = job

    options = RunOptions(
        url=req.url or settings.target_url,
        topic=req.topic or None,
        manual=False,  # 웹에서는 수동 캡차 입력 미지원 (AI 비전 + 재시도)
        headless=not req.show_browser,
        dry_run=req.dry_run,
        backlink_url=(req.backlink_url or "").strip() or None,
        backlink_text=(req.backlink_text or "").strip() or None,
        repeat=max(1, int(req.repeat or 1)),
        rotate_ip=bool(req.rotate_ip),
        rotate_every=max(1, int(req.rotate_every or 1)),
        mobile=bool(req.mobile),
        human=HumanSettings(**req.human.model_dump()),
    )
    threading.Thread(target=_worker, args=(job, options), daemon=True).start()
    return JSONResponse({"job_id": job_id})


@app.get("/api/stream/{job_id}")
def stream(job_id: str) -> StreamingResponse:
    job = _jobs.get(job_id)
    if job is None:
        return StreamingResponse(
            iter([f"event: error\ndata: {json.dumps('알 수 없는 작업')}\n\n"]),
            media_type="text/event-stream",
        )

    def event_gen():
        while True:
            item = job.queue.get()
            if item is _DONE:
                payload = json.dumps(job.result, ensure_ascii=False)
                yield f"event: done\ndata: {payload}\n\n"
                break
            data = json.dumps(item, ensure_ascii=False)
            yield f"event: log\ndata: {data}\n\n"

    return StreamingResponse(event_gen(), media_type="text/event-stream")


if __name__ == "__main__":
    import os

    import uvicorn

    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run(app, host=host, port=port)
