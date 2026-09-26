"""Page fetching, SSRF protection and HTML -> readable text conversion."""
from __future__ import annotations

import asyncio
import ipaddress
import json
import socket
from dataclasses import dataclass, field
from urllib.parse import urljoin, urldefrag, urlparse
from urllib.robotparser import RobotFileParser

import httpx
from bs4 import BeautifulSoup

from . import config

MAX_BYTES = 5 * 1024 * 1024
MAX_REDIRECTS = 5


class FetchError(Exception):
    pass


@dataclass
class Link:
    url: str
    text: str


@dataclass
class Page:
    url: str
    status: int
    title: str = ""
    text: str = ""
    links: list[Link] = field(default_factory=list)
    truncated: bool = False
    content_type: str = ""


def normalize_url(url: str) -> str:
    url = url.strip()
    if url and "://" not in url:
        url = "https://" + url
    url, _ = urldefrag(url)
    return url


async def assert_public_host(url: str) -> None:
    """Refuse URLs that resolve to private / loopback / link-local addresses."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise FetchError(f"不支持的协议: {parsed.scheme or '(空)'}")
    host = parsed.hostname
    if not host:
        raise FetchError("URL 缺少主机名")
    if config.ALLOW_PRIVATE_NETWORKS:
        return
    loop = asyncio.get_running_loop()
    try:
        infos = await loop.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80),
                                       type=socket.SOCK_STREAM)
    except socket.gaierror as e:
        raise FetchError(f"无法解析域名 {host}: {e}") from e
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if not ip.is_global:
            raise FetchError(f"拒绝访问内网地址 {host} ({ip})")


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        headers={
            "User-Agent": config.USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        },
        timeout=httpx.Timeout(20.0, connect=10.0),
        follow_redirects=False,
    )


async def _get(client: httpx.AsyncClient, url: str) -> tuple[str, httpx.Response, bytes]:
    """GET with manual redirects so every hop passes the SSRF check."""
    for _ in range(MAX_REDIRECTS + 1):
        await assert_public_host(url)
        async with client.stream("GET", url) as resp:
            if resp.is_redirect and "location" in resp.headers:
                url = normalize_url(urljoin(url, resp.headers["location"]))
                continue
            chunks, size = [], 0
            async for chunk in resp.aiter_bytes():
                size += len(chunk)
                if size > MAX_BYTES:
                    break
                chunks.append(chunk)
            return url, resp, b"".join(chunks)
    raise FetchError("重定向次数过多")


class RobotsCache:
    def __init__(self) -> None:
        self._cache: dict[str, RobotFileParser | None] = {}

    async def allowed(self, client: httpx.AsyncClient, url: str) -> bool:
        p = urlparse(url)
        origin = f"{p.scheme}://{p.netloc}"
        if origin not in self._cache:
            parser: RobotFileParser | None = None
            try:
                _, resp, body = await _get(client, origin + "/robots.txt")
                if resp.status_code == 200:
                    parser = RobotFileParser()
                    parser.parse(body.decode("utf-8", "replace").splitlines())
            except Exception:
                parser = None
            self._cache[origin] = parser
        parser = self._cache[origin]
        return True if parser is None else parser.can_fetch(config.USER_AGENT, url)


def html_to_page(url: str, status: int, html: str) -> Page:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "noscript", "svg", "iframe", "template"]):
        tag.decompose()

    title = soup.title.get_text(strip=True) if soup.title else ""
    if soup.head:
        soup.head.decompose()

    links: list[Link] = []
    seen: dict[str, int] = {}
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if href.startswith(("javascript:", "mailto:", "tel:", "#")):
            continue
        absolute = normalize_url(urljoin(url, href))
        if urlparse(absolute).scheme not in ("http", "https"):
            continue
        text = " ".join(a.get_text(" ", strip=True).split())[:120]
        if absolute not in seen:
            seen[absolute] = len(links)
            links.append(Link(absolute, text))
        a.replace_with(f"{text} [L{seen[absolute]}]" if text else f"[L{seen[absolute]}]")

    for img in soup.find_all("img"):
        src = img.get("src") or img.get("data-src") or ""
        if src:
            img.replace_with(f"![{img.get('alt', '').strip()}]({urljoin(url, src)})")
        else:
            img.decompose()

    for br in soup.find_all("br"):
        br.replace_with("\n")

    raw = soup.get_text("\n")
    lines = [" ".join(line.split()) for line in raw.splitlines()]
    text = "\n".join(line for line in lines if line)

    truncated = len(text) > config.MAX_PAGE_CHARS
    if truncated:
        text = text[: config.MAX_PAGE_CHARS]
    return Page(url=url, status=status, title=title, text=text, links=links,
                truncated=truncated, content_type="text/html")


async def fetch_http(client: httpx.AsyncClient, url: str) -> Page:
    final_url, resp, body = await _get(client, url)
    ctype = resp.headers.get("content-type", "").lower()
    if resp.status_code >= 400:
        raise FetchError(f"HTTP {resp.status_code}")
    encoding = resp.encoding or "utf-8"
    content = body.decode(encoding, "replace")
    if "html" in ctype or content.lstrip()[:15].lower().startswith(("<!doctype", "<html")):
        return html_to_page(final_url, resp.status_code, content)
    if "json" in ctype:
        try:
            content = json.dumps(json.loads(content), ensure_ascii=False, indent=1)
        except ValueError:
            pass
    if ctype.startswith(("text/", "application/json", "application/xml")) or not ctype:
        truncated = len(content) > config.MAX_PAGE_CHARS
        return Page(url=final_url, status=resp.status_code, text=content[: config.MAX_PAGE_CHARS],
                    truncated=truncated, content_type=ctype)
    raise FetchError(f"不支持的内容类型: {ctype}")


async def fetch_browser(url: str) -> Page:
    """Render the page with headless Chromium (only when Playwright is installed)."""
    from playwright.async_api import async_playwright

    await assert_public_host(url)
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(args=["--no-sandbox"])
        try:
            page = await browser.new_page(user_agent=config.USER_AGENT)

            async def guard(route):
                try:
                    await assert_public_host(route.request.url)
                except FetchError:
                    return await route.abort()
                await route.continue_()

            await page.route("**/*", guard)
            resp = await page.goto(url, wait_until="networkidle", timeout=45_000)
            html = await page.content()
            status = resp.status if resp else 200
            return html_to_page(page.url, status, html)
        finally:
            await browser.close()


def new_client() -> httpx.AsyncClient:
    return _client()
