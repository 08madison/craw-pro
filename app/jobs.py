"""Crawl jobs: persistence, progress events and the crawl loop."""
from __future__ import annotations

import asyncio
import ipaddress
import json
import sqlite3
import time
import uuid
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

from pydantic import BaseModel, Field

from . import config
from .fetcher import FetchError, Page, RobotsCache, fetch_browser, fetch_http, new_client, normalize_url
from .dedupe import dedupe
from .llm import CrawlPlan, Extractor, LLMError, basic_extract, fallback_plan


class JobRequest(BaseModel):
    urls: list[str] = Field(min_length=1, max_length=20)
    description: str = Field(default="", max_length=4000)
    max_pages: int = Field(default=10, ge=1)
    max_depth: int = Field(default=1, ge=0)
    same_domain: bool = True
    render_js: bool = False
    respect_robots: bool = True


@dataclass
class Job:
    id: str
    request: JobRequest
    created_at: float = field(default_factory=time.time)
    status: str = "queued"  # queued | running | done | failed | cancelled
    plan: dict | None = None
    records: list[dict] = field(default_factory=list)
    pages: list[dict] = field(default_factory=list)
    events: list[dict] = field(default_factory=list)
    error: str = ""
    finished_at: float | None = None
    usage: dict = field(default_factory=lambda: {"input_tokens": 0, "output_tokens": 0})
    queued_pages: int = 0
    cancel_requested: bool = False

    def summary(self) -> dict:
        return {
            "id": self.id,
            "created_at": self.created_at,
            "finished_at": self.finished_at,
            "status": self.status,
            "urls": self.request.urls,
            "description": self.request.description,
            "record_count": len(self.records),
            "pages_done": len(self.pages),
            "max_pages": self.request.max_pages,
            "queued_pages": self.queued_pages,
            "error": self.error,
        }

    def detail(self) -> dict:
        return {
            **self.summary(),
            "request": self.request.model_dump(),
            "plan": self.plan,
            "records": self.records,
            "pages": self.pages,
            "usage": self.usage,
        }


class JobStore:
    def __init__(self) -> None:
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(config.DATA_DIR / "jobs.db", check_same_thread=False)
        self.db.execute("CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, created_at REAL, data TEXT)")
        self.db.commit()
        self.jobs: dict[str, Job] = {}
        self._tasks: dict[str, asyncio.Task] = {}
        self._slots = asyncio.Semaphore(config.MAX_CONCURRENT_JOBS)
        self._load()

    def _load(self) -> None:
        for (data,) in self.db.execute("SELECT data FROM jobs ORDER BY created_at DESC LIMIT 200"):
            d = json.loads(data)
            job = Job(
                id=d["id"], request=JobRequest(**d["request"]), created_at=d["created_at"],
                status=d["status"], plan=d.get("plan"), records=d.get("records", []),
                pages=d.get("pages", []), events=d.get("events", []), error=d.get("error", ""),
                finished_at=d.get("finished_at"), usage=d.get("usage") or {},
            )
            if job.status in ("queued", "running"):
                job.status, job.error = "failed", "服务重启，任务中断"
            self.jobs[job.id] = job

    def save(self, job: Job) -> None:
        if job.id not in self.jobs:  # deleted while running
            return
        data = {**job.detail(), "events": job.events[-500:]}
        self.db.execute("INSERT OR REPLACE INTO jobs (id, created_at, data) VALUES (?, ?, ?)",
                        (job.id, job.created_at, json.dumps(data, ensure_ascii=False)))
        self.db.commit()

    def list(self) -> list[Job]:
        return sorted(self.jobs.values(), key=lambda j: j.created_at, reverse=True)

    def delete(self, job_id: str) -> bool:
        job = self.jobs.pop(job_id, None)
        if job is None:
            return False
        job.cancel_requested = True
        self.db.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
        self.db.commit()
        return True

    def create(self, req: JobRequest) -> Job:
        req.max_pages = min(req.max_pages, config.MAX_PAGES_LIMIT)
        req.max_depth = min(req.max_depth, config.MAX_DEPTH_LIMIT)
        req.urls = [normalize_url(u) for u in req.urls if u.strip()]
        job = Job(id=uuid.uuid4().hex[:12], request=req)
        self.jobs[job.id] = job
        emit(job, "info", "任务已创建，排队中")
        self.save(job)
        self._tasks[job.id] = asyncio.create_task(self._run(job))
        return job

    async def _run(self, job: Job) -> None:
        async with self._slots:
            try:
                await Crawler(job, self).run()
            except Exception as e:  # noqa: BLE001
                job.status, job.error = "failed", str(e) or e.__class__.__name__
                emit(job, "error", f"任务失败: {job.error}")
            finally:
                job.finished_at = time.time()
                self.save(job)
                self._tasks.pop(job.id, None)


# Second-level labels under which registrations happen, e.g. cuhk.edu.hk, sina.com.cn, ox.ac.uk
_SLD = {"ac", "co", "com", "edu", "gov", "net", "org", "gob", "mil", "or", "ne", "go"}


def site_of(host: str) -> str:
    """Registrable domain, so subdomains of one site match (www.cuhk.edu.hk ~ cse.cuhk.edu.hk)."""
    host = host.lower().rstrip(".")
    try:
        ipaddress.ip_address(host.strip("[]"))
        return host
    except ValueError:
        pass
    parts = host.split(".")
    if len(parts) >= 3 and len(parts[-1]) == 2 and parts[-2] in _SLD:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def emit(job: Job, level: str, message: str, **extra: Any) -> None:
    job.events.append({"id": len(job.events), "ts": time.time(), "level": level,
                       "message": message, **extra})


class Crawler:
    def __init__(self, job: Job, store: JobStore) -> None:
        self.job = job
        self.store = store
        self.req = job.request
        self.use_llm = bool(config.LLM_PROVIDER)
        self.extractor = Extractor() if self.use_llm else None
        self.robots = RobotsCache()
        self.seen: set[str] = set()
        self.queue: asyncio.Queue[tuple[str, int]] = asyncio.Queue()
        self.started = 0
        self.sites = {site_of(urlparse(u).hostname or "") for u in self.req.urls}
        self.render_js = self.req.render_js and config.browser_available()

    def _enqueue(self, url: str, depth: int) -> bool:
        url = normalize_url(url)
        if url in self.seen:
            return False
        if self.req.same_domain and site_of(urlparse(url).hostname or "") not in self.sites:
            return False
        if len(self.seen) >= self.req.max_pages:
            return False
        self.seen.add(url)
        self.queue.put_nowait((url, depth))
        self.job.queued_pages = len(self.seen)
        return True

    async def run(self) -> None:
        job = self.job
        job.status = "running"
        if self.req.render_js and not self.render_js:
            emit(job, "warn", "服务器未安装浏览器组件，改用普通 HTTP 抓取")

        # 1. Understand the request
        if self.extractor:
            emit(job, "info", f"正在用 AI 模型 ({config.LLM_MODEL}) 理解抓取需求…")
            try:
                plan, usage = await self.extractor.plan(self.req.description, self.req.urls)
            except LLMError as e:
                raise RuntimeError(f"需求解析失败: {e}") from e
            self._add_usage(usage)
        else:
            emit(job, "warn", "未配置大模型 API Key，使用基础模式（仅抓取标题和正文）")
            plan = fallback_plan(self.req.description)
        job.plan = plan.model_dump()
        emit(job, "plan", "抓取计划: " + plan.summary + "；字段: " + "、".join(f.label for f in plan.fields))
        self.store.save(job)
        model = self.extractor.extraction_model(plan) if self.extractor else None

        # 2. Crawl
        for u in self.req.urls:
            self._enqueue(u, 0)
        async with new_client() as client:
            self.client = client
            workers = [asyncio.create_task(self._worker(plan, model)) for _ in range(config.CRAWL_CONCURRENCY)]
            await self.queue.join()
            for w in workers:
                w.cancel()
            await asyncio.gather(*workers, return_exceptions=True)

        records, removed, shared = dedupe(job.records, [f.key for f in plan.fields])
        job.records = records
        if removed or shared:
            parts = [f"合并了 {removed} 条重复记录"] if removed else []
            if shared:
                parts.append(f"{shared} 条记录的邮箱为多人共用，已标记为「公共邮箱」")
            emit(job, "info", "整理结果：" + "；".join(parts))

        if job.cancel_requested:
            job.status = "cancelled"
            emit(job, "warn", "任务已取消")
        else:
            job.status = "done"
            emit(job, "done", f"完成：抓取 {len(job.pages)} 个页面，得到 {len(job.records)} 条记录")

    async def _worker(self, plan: CrawlPlan, model: Any) -> None:
        while True:
            url, depth = await self.queue.get()
            try:
                if not self.job.cancel_requested:
                    await self._process(url, depth, plan, model)
            except Exception as e:  # noqa: BLE001
                emit(self.job, "error", f"处理 {url} 出错: {e}", url=url)
            finally:
                self.queue.task_done()

    async def _process(self, url: str, depth: int, plan: CrawlPlan, model: Any) -> None:
        job = self.job
        self.started += 1
        n = self.started
        page_info: dict[str, Any] = {"url": url, "depth": depth, "status": "ok", "records": 0}

        if self.req.respect_robots and not await self.robots.allowed(self.client, url):
            emit(job, "warn", f"[{n}] robots.txt 禁止抓取，跳过 {url}", url=url)
            job.pages.append({**page_info, "status": "blocked"})
            return

        emit(job, "fetch", f"[{n}] 正在抓取 {url}", url=url)
        try:
            page: Page = await (fetch_browser(url) if self.render_js else fetch_http(self.client, url))
        except (FetchError, Exception) as e:  # noqa: BLE001
            emit(job, "error", f"[{n}] 抓取失败 {url}: {e}", url=url)
            job.pages.append({**page_info, "status": "error", "error": str(e)})
            return
        finally:
            await asyncio.sleep(config.REQUEST_DELAY_MS / 1000)

        page_info["title"] = page.title
        if page.truncated:
            emit(job, "warn", f"[{n}] 页面过长，仅分析前 {config.MAX_PAGE_CHARS} 个字符", url=url)

        # Pagination stays at the same depth; only other links go one level deeper.
        go_deeper = depth < self.req.max_depth
        want_links = len(self.seen) < self.req.max_pages
        if self.extractor:
            emit(job, "extract", f"[{n}] AI 正在分析「{page.title or url}」", url=url)
            try:
                records, paging, follow, note, usage = await self.extractor.extract(plan, model, page, want_links)
                self._add_usage(usage)
            except LLMError as e:
                emit(job, "error", f"[{n}] 分析失败: {e}", url=url)
                job.pages.append({**page_info, "status": "error", "error": str(e)})
                return
            pick = lambda idx: [page.links[i].url for i in idx if 0 <= i < len(page.links)]  # noqa: E731
            next_links = [(u, depth) for u in pick(paging)]
            if go_deeper:
                next_links += [(u, depth + 1) for u in pick(follow)]
        else:
            records, note = basic_extract(page), ""
            next_links = [(l.url, depth + 1) for l in page.links] if go_deeper else []

        for r in records:
            r["_source"] = page.url
        job.records.extend(records)
        page_info["records"] = len(records)
        job.pages.append(page_info)

        added = 0
        if want_links and not job.cancel_requested:
            for u, d in next_links:
                if self._enqueue(u, d):
                    added += 1
        msg = f"[{n}] 提取到 {len(records)} 条记录"
        if added:
            msg += f"，新增 {added} 个待抓取链接"
        if note:
            msg += f"（{note}）"
        emit(job, "page", msg, url=url, records=len(records))
        self.store.save(job)

    def _add_usage(self, usage: dict) -> None:
        for k, v in usage.items():
            self.job.usage[k] = self.job.usage.get(k, 0) + v
