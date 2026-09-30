"""FastAPI entry point: REST API, SSE progress stream and the static web UI."""
from __future__ import annotations

import asyncio
import csv
import io
import json
import secrets
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import config, exporters
from .jobs import BatchRequest, Job, JobRequest, JobStore
from .llm import LLMError

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
store: JobStore
OFFICE_TYPES = {
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}


@asynccontextmanager
async def lifespan(_: FastAPI):
    global store
    store = JobStore()
    yield


app = FastAPI(title="Craw Pro", lifespan=lifespan)


def check_password(request: Request) -> None:
    if not config.APP_PASSWORD:
        return
    supplied = request.headers.get("x-app-password") or request.query_params.get("pw") or ""
    if not secrets.compare_digest(supplied.encode(), config.APP_PASSWORD.encode()):
        raise HTTPException(status_code=401, detail="需要访问密码")


def get_job(job_id: str):
    job = store.jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    return job


@app.get("/healthz")
async def healthz():
    return {"ok": True}


@app.get("/api/config")
async def get_config():
    return {
        "password_required": bool(config.APP_PASSWORD),
        "llm_enabled": bool(config.LLM_PROVIDER),
        "provider": config.LLM_PROVIDER,
        "model": config.LLM_MODEL,
        "browser_available": config.browser_available(),
        "max_pages_limit": config.MAX_PAGES_LIMIT,
        "max_depth_limit": config.MAX_DEPTH_LIMIT,
    }


@app.post("/api/auth/check", dependencies=[Depends(check_password)])
async def auth_check():
    return {"ok": True}


@app.post("/api/jobs", dependencies=[Depends(check_password)])
async def create_job(req: JobRequest):
    if not any(u.strip() for u in req.urls):
        raise HTTPException(status_code=422, detail="请至少输入一个网址")
    job = store.create(req)
    return job.summary()


@app.get("/api/jobs", dependencies=[Depends(check_password)])
async def list_jobs():
    return [j.summary() for j in store.list()]


@app.get("/api/jobs/{job_id}", dependencies=[Depends(check_password)])
async def job_detail(job_id: str):
    return get_job(job_id).detail()


@app.post("/api/jobs/{job_id}/cancel", dependencies=[Depends(check_password)])
async def cancel_job(job_id: str):
    job = get_job(job_id)
    job.cancel_requested = True
    return {"ok": True}


@app.delete("/api/jobs/{job_id}", dependencies=[Depends(check_password)])
async def delete_job(job_id: str):
    if not store.delete(job_id):
        raise HTTPException(status_code=404, detail="任务不存在")
    return {"ok": True}


@app.get("/api/jobs/{job_id}/events", dependencies=[Depends(check_password)])
async def job_events(job_id: str, request: Request):
    job = get_job(job_id)
    start = int(request.headers.get("last-event-id", "-1")) + 1

    async def stream():
        idx = start
        idle = 0
        while True:
            if await request.is_disconnected():
                return
            sent = False
            while idx < len(job.events):
                ev = job.events[idx]
                payload = {**ev, "job": job.summary()}
                yield f"id: {ev['id']}\nevent: progress\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
                idx += 1
                sent = True
            if job.status in ("done", "failed", "cancelled") and idx >= len(job.events):
                yield f"event: end\ndata: {json.dumps(job.summary(), ensure_ascii=False)}\n\n"
                return
            idle = 0 if sent else idle + 1
            if idle >= 30:  # keep-alive comment every ~15s
                idle = 0
                yield ": ping\n\n"
            await asyncio.sleep(0.5)

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def export_response(job: Job, format: str, filename: str) -> Response:
    if format == "csv":
        cols = exporters.columns(job)
        buf = io.StringIO()
        buf.write("\ufeff")  # BOM so Excel opens UTF-8 correctly
        w = csv.writer(buf)
        w.writerow([label for _, label in cols])
        for r in job.records:
            w.writerow([r.get(k, "") for k, _ in cols])
        return Response(buf.getvalue(), media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="{filename}.csv"'})
    if format in ("docx", "pptx"):
        build = exporters.to_docx if format == "docx" else exporters.to_pptx
        return Response(build(job), media_type=OFFICE_TYPES[format],
                        headers={"Content-Disposition": f'attachment; filename="{filename}.{format}"'})
    return JSONResponse(
        {"job": job.summary(), "plan": job.plan, "records": job.records},
        headers={"Content-Disposition": f'attachment; filename="{filename}.json"'},
    )


@app.get("/api/jobs/{job_id}/export", dependencies=[Depends(check_password)])
async def export_job(job_id: str, format: str = "json"):
    job = get_job(job_id)
    return await asyncio.to_thread(export_response, job, format, f"crawl-{job.id}")


@app.post("/api/batches", dependencies=[Depends(check_password)])
async def create_batch(breq: BatchRequest):
    try:
        group = await store.create_batch(breq)
    except LLMError as e:
        raise HTTPException(status_code=502, detail=f"生成抓取计划失败: {e}") from e
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    return store.group_summary(group)


@app.get("/api/batches/{group}", dependencies=[Depends(check_password)])
async def batch_detail(group: str):
    summary = store.group_summary(group)
    if not summary["total"]:
        raise HTTPException(status_code=404, detail="批次不存在")
    return summary


@app.post("/api/batches/{group}/cancel", dependencies=[Depends(check_password)])
async def cancel_batch(group: str):
    for job in store.group_jobs(group):
        job.cancel_requested = True
    return {"ok": True}


@app.get("/api/batches/{group}/export", dependencies=[Depends(check_password)])
async def export_batch(group: str, format: str = "json"):
    job = store.combined_job(group)
    if job is None:
        raise HTTPException(status_code=404, detail="批次不存在")
    return await asyncio.to_thread(export_response, job, format, f"batch-{group}")


@app.get("/")
async def index():
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
