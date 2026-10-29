"""Aplicativo de blog independiente de OSAP.

Usa su propia base de datos (`osap_blog`), su propio almacén de imágenes y solo delega la
autenticación en OSAP Auth. No comparte tablas con osap-api.
"""

from __future__ import annotations

import logging
import math
import os
import re
import threading
import time
import unicodedata
import uuid
from collections.abc import Iterator
from contextlib import asynccontextmanager, contextmanager
from datetime import UTC, datetime
from email.utils import format_datetime
from html import escape
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

import httpx
import pymysql
import yaml
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    PlainTextResponse,
    RedirectResponse,
    Response,
)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pymysql.cursors import DictCursor

BASE_DIR = Path(__file__).resolve().parent
APP_VERSION = "1.0.1"


def _load_config() -> dict[str, Any]:
    path = Path(os.environ.get("OSAP_BLOG_CONFIG", BASE_DIR / "config.yaml"))
    if not path.exists():
        path = BASE_DIR / "config.example.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    data.setdefault("db", {})
    data.setdefault("server", {})
    data.setdefault("auth", {})
    data.setdefault("osap", {})
    data.setdefault("media", {})
    data.setdefault("editor", {})
    data["server"].setdefault("site_name", "Blog OSAP")
    data["server"].setdefault(
        "site_description",
        "Historias, análisis y novedades sobre el repertorio y la comunidad de OSAP.",
    )
    data["server"].setdefault("page_size", 9)
    data["db"]["password"] = os.environ.get(
        "OSAP_BLOG_DB_PASSWORD", data["db"].get("password", "")
    )
    data["server"]["public_url"] = os.environ.get(
        "OSAP_BLOG_PUBLIC_URL", data["server"].get("public_url", "http://localhost:8500")
    ).rstrip("/")
    data["auth"]["base_url"] = os.environ.get(
        "OSAP_BLOG_AUTH_URL", data["auth"].get("base_url", "http://127.0.0.1:8200")
    ).rstrip("/")
    data["osap"]["public_url"] = os.environ.get(
        "OSAP_PUBLIC_URL", data["osap"].get("public_url", "http://osap-app")
    ).rstrip("/")
    data["media"]["root"] = os.environ.get(
        "OSAP_BLOG_MEDIA_ROOT", data["media"].get("root", "data/media")
    )
    return data


CONFIG = _load_config()
DB = CONFIG["db"]
AUTH_BASE = CONFIG["auth"]["base_url"]
PUBLIC_URL = CONFIG["server"]["public_url"]
OSAP_URL = CONFIG["osap"]["public_url"]
SITE_NAME = str(CONFIG["server"]["site_name"])
SITE_DESCRIPTION = str(CONFIG["server"]["site_description"])
try:
    PAGE_SIZE = max(1, min(50, int(CONFIG["server"]["page_size"])))
except (TypeError, ValueError):
    PAGE_SIZE = 9
MEDIA_ROOT = Path(CONFIG["media"]["root"])
if not MEDIA_ROOT.is_absolute():
    MEDIA_ROOT = BASE_DIR / MEDIA_ROOT
MEDIA_ROOT.mkdir(parents=True, exist_ok=True)
COOKIE = "osap_blog_token"
REFRESH_COOKIE = "osap_blog_refresh"
LOGGER = logging.getLogger("osap-blog")
MAX_UPLOAD = int(CONFIG["media"].get("max_bytes", 5 * 1024 * 1024))
EDITOR_ROLES = list(CONFIG["editor"].get("roles", []))
COMMENT_MODERATION = bool(CONFIG["editor"].get("moderation", True))

ALLOWED_TAGS = {
    "p", "br", "strong", "b", "em", "i", "u", "s", "ul", "ol", "li",
    "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "a", "hr",
    "figure", "figcaption", "img", "div", "span",
}
VOID_TAGS = {"br", "hr", "img"}
CLASSES = {"align-left", "align-right", "align-center", "media-wide"}


class BlogSanitizer(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.stack: list[str] = []
        self.skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in {"script", "style", "iframe", "object", "embed"}:
            self.skip += 1
            return
        if self.skip or tag not in ALLOWED_TAGS:
            return
        values = dict(attrs)
        safe: list[tuple[str, str]] = []
        cls = " ".join(
            token for token in str(values.get("class") or "").split() if token in CLASSES
        )
        if cls:
            safe.append(("class", cls))
        if tag == "a":
            href = str(values.get("href") or "")
            parsed = urlparse(href)
            if href.startswith("/") or parsed.scheme in {"http", "https", "mailto"}:
                safe.extend([("href", href), ("rel", "nofollow noopener")])
        elif tag == "img":
            src = str(values.get("src") or "")
            parsed_src = urlparse(src)
            if not (src.startswith("/media/") or parsed_src.scheme in {"http", "https"}):
                return
            safe.extend([("src", src), ("alt", str(values.get("alt") or "")), ("loading", "lazy")])
            for key in ("width", "height"):
                value = str(values.get(key) or "")
                if value.isdigit():
                    safe.append((key, value))
        suffix = "".join(f' {key}="{escape(value, quote=True)}"' for key, value in safe)
        if tag in VOID_TAGS:
            self.parts.append(f"<{tag}{suffix}>")
        else:
            self.parts.append(f"<{tag}{suffix}>")
            self.stack.append(tag)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"script", "style", "iframe", "object", "embed"}:
            self.skip = max(0, self.skip - 1)
            return
        if self.skip or tag not in ALLOWED_TAGS or tag in VOID_TAGS:
            return
        if tag in self.stack:
            while self.stack and self.stack.pop() != tag:
                pass
            self.parts.append(f"</{tag}>")

    def handle_data(self, data: str) -> None:
        if not self.skip:
            self.parts.append(escape(data, quote=False))


def sanitize_html(value: str | None) -> str:
    parser = BlogSanitizer()
    parser.feed(value or "")
    parser.close()
    return "".join(parser.parts).strip()


def slugify(value: str) -> str:
    text = unicodedata.normalize("NFKD", value)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^a-z0-9]+", "-", text.casefold()).strip("-")
    return text[:160] or "articulo"


def unique_slug(title: str) -> str:
    base = slugify(title)
    candidate = base
    with db() as conn, conn.cursor() as cur:
        for index in range(2, 100):
            cur.execute("SELECT id FROM articles WHERE slug=%s", (candidate,))
            if cur.fetchone() is None:
                return candidate
            candidate = f"{base}-{index}"
    return f"{base}-{uuid.uuid4().hex[:8]}"


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def public_user(token: str) -> dict[str, Any] | None:
    if not token:
        return None
    try:
        response = httpx.get(
            f"{AUTH_BASE}/auth/me",
            headers={"Authorization": f"Bearer {token}"},
            timeout=5.0,
        )
    except httpx.HTTPError:
        return None
    if response.status_code != 200:
        return None
    try:
        data = response.json()
    except ValueError:
        return None
    return data if data.get("user_id") else None


_REFRESH_LOCK = threading.Lock()
_REFRESH_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}


def refresh_tokens(refresh_token: str) -> dict[str, Any] | None:
    """Renueva la sesión en OSAP y reutiliza el resultado durante unos segundos."""
    if not refresh_token:
        return None
    now = time.monotonic()
    with _REFRESH_LOCK:
        cached = _REFRESH_CACHE.get(refresh_token)
        if cached and cached[0] > now:
            return cached[1]
        try:
            response = httpx.post(
                f"{AUTH_BASE}/auth/refresh",
                json={"refresh_token": refresh_token},
                timeout=8.0,
            )
        except httpx.HTTPError as exc:
            LOGGER.warning("No se pudo renovar la sesión del blog: %s", type(exc).__name__)
            return None
        if response.status_code != 200:
            LOGGER.warning("OSAP rechazó la renovación: HTTP %s", response.status_code)
            return None
        try:
            data = response.json()
        except ValueError:
            return None
        if not data.get("access_token") or not data.get("refresh_token"):
            return None
        _REFRESH_CACHE[refresh_token] = (now + 60.0, data)
        return data


def can_edit(user: dict[str, Any] | None) -> bool:
    if not user:
        return False
    if not EDITOR_ROLES:
        return True
    roles = {str(role) for role in (user.get("roles") or [])}
    return bool(roles & set(EDITOR_ROLES))


def token_for(request: Request) -> str:
    return getattr(request.state, "blog_token", "") or request.cookies.get(COOKIE, "")


def set_cookie(
    response: Response,
    request: Request,
    token: str,
    refresh_token: str = "",
) -> None:
    response.set_cookie(
        COOKIE,
        token,
        max_age=3600,
        httponly=True,
        secure=PUBLIC_URL.startswith("https://"),
        samesite="lax",
        path="/",
    )
    if refresh_token:
        response.set_cookie(
            REFRESH_COOKIE,
            refresh_token,
            max_age=30 * 24 * 3600,
            httponly=True,
            secure=PUBLIC_URL.startswith("https://"),
            samesite="lax",
            path="/",
        )


@contextmanager
def db() -> Iterator[pymysql.Connection]:
    conn = pymysql.connect(
        host=DB.get("host", "127.0.0.1"),
        port=int(DB.get("port", 3306)),
        user=DB.get("user"),
        password=DB.get("password", ""),
        database=DB.get("name", "osap_blog"),
        charset="utf8mb4",
        cursorclass=DictCursor,
        autocommit=False,
    )
    try:
        yield conn
    finally:
        conn.close()


def init_schema() -> None:
    schema = (BASE_DIR / "schema.sql").read_text(encoding="utf-8")
    with db() as conn, conn.cursor() as cur:
        for statement in schema.split(";"):
            if statement.strip():
                cur.execute(statement)
        conn.commit()


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_schema()
    yield


app = FastAPI(title="OSAP Blog", docs_url=None, redoc_url=None, lifespan=lifespan)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


@app.middleware("http")
async def renew_blog_session(request: Request, call_next):
    path = request.url.path
    if not (path == "/admin" or path.startswith(("/admin/", "/comments", "/auth/"))):
        return await call_next(request)
    access = request.cookies.get(COOKIE, "")
    refresh = request.cookies.get(REFRESH_COOKIE, "")
    renewed: dict[str, Any] | None = None
    if refresh and (not access or not public_user(access)):
        candidate = refresh_tokens(refresh)
        if candidate and public_user(str(candidate["access_token"])):
            renewed = candidate
            request.state.blog_token = candidate["access_token"]
            request.state.blog_refresh = candidate["refresh_token"]
    response = await call_next(request)
    if renewed:
        set_cookie(
            response,
            request,
            str(renewed["access_token"]),
            str(renewed["refresh_token"]),
        )
    return response


def render(
    request: Request,
    template: str,
    *,
    status_code: int = 200,
    **context: Any,
) -> HTMLResponse:
    token = token_for(request)
    user = public_user(token)
    base = {
        "request": request,
        "version": APP_VERSION,
        "user": user,
        "user_name": str((user or {}).get("name") or (user or {}).get("email") or ""),
        "can_edit": can_edit(user),
        "osap_url": OSAP_URL,
        "public_url": PUBLIC_URL,
        "site_name": SITE_NAME,
        "site_description": SITE_DESCRIPTION,
        "canonical": f"{PUBLIC_URL}{request.url.path}",
        "feed_url": f"{PUBLIC_URL}/feed",
        "login_url": f"{OSAP_URL}/?auth=login&return_to=blog",
        "session_error": request.query_params.get("session") == "error",
    }
    base.update(context)
    return templates.TemplateResponse(request, template, base, status_code=status_code)


def rss_date(value: datetime | None) -> str:
    stamp = value or datetime.now(UTC).replace(tzinfo=None)
    return format_datetime(stamp.replace(tzinfo=UTC))


def reading_minutes(body_html: str) -> int:
    words = len(re.sub(r"<[^>]+>", " ", body_html).split())
    return max(1, round(words / 220))


@app.get("/health")
def health() -> dict[str, str]:
    with db() as conn, conn.cursor() as cur:
        cur.execute("SELECT 1")
        cur.fetchone()
    return {"status": "ok", "version": APP_VERSION}


@app.get("/", response_class=HTMLResponse)
def home(request: Request, page: int = 1, q: str = "", month: str = "") -> HTMLResponse:
    query = q.strip()[:120]
    page = max(1, page)
    where = "status='published'"
    params: list[Any] = []
    if query:
        where += " AND (title LIKE %s OR summary LIKE %s OR body_html LIKE %s)"
        params.extend([f"%{query}%"] * 3)
    month_label = ""
    if re.fullmatch(r"\d{4}-\d{2}", month):
        year, month_number = month.split("-")
        where += " AND YEAR(published_at)=%s AND MONTH(published_at)=%s"
        params.extend([int(year), int(month_number)])
        month_label = f"{month_number}/{year}"
    with db() as conn, conn.cursor() as cur:
        cur.execute(f"SELECT COUNT(*) AS total FROM articles WHERE {where}", params)
        total = int(cur.fetchone()["total"])
        total_pages = max(1, math.ceil(total / PAGE_SIZE))
        page = min(page, total_pages)
        offset = (page - 1) * PAGE_SIZE
        cur.execute(
            "SELECT id, slug, title, summary, cover_url, author_name, published_at "
            f"FROM articles WHERE {where} "
            "ORDER BY published_at DESC, created_at DESC LIMIT %s OFFSET %s",
            [*params, PAGE_SIZE, offset],
        )
        articles = cur.fetchall()
        cur.execute(
            "SELECT id, slug, title, published_at FROM articles WHERE status='published' "
            "ORDER BY published_at DESC, created_at DESC LIMIT 5"
        )
        recent = cur.fetchall()
    featured = articles[0] if page == 1 and not query and not month_label and articles else None
    listed = articles[1:] if featured else articles
    return render(
        request,
        "index.html",
        articles=listed,
        featured=featured,
        recent=recent,
        q=query,
        month=month,
        month_label=month_label,
        page=page,
        total=total,
        total_pages=total_pages,
        has_previous=page > 1,
        has_next=page < total_pages,
    )


@app.get("/buscar")
def search(q: str = "") -> RedirectResponse:
    target = f"/?q={quote(q.strip()[:120])}" if q.strip() else "/"
    return RedirectResponse(target, status_code=303)


@app.get("/archivo", response_class=HTMLResponse)
def archive(request: Request) -> HTMLResponse:
    with db() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT YEAR(published_at) AS year, MONTH(published_at) AS month, "
            "COUNT(*) AS total FROM articles WHERE status='published' "
            "GROUP BY year, month ORDER BY year DESC, month DESC"
        )
        months = cur.fetchall()
    return render(request, "archive.html", months=months, canonical=f"{PUBLIC_URL}/archivo")


@app.get("/feed")
def feed() -> Response:
    with db() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT slug, title, summary, body_html, published_at FROM articles "
            "WHERE status='published' ORDER BY published_at DESC, created_at DESC LIMIT 20"
        )
        articles = cur.fetchall()
    items = []
    for article in articles:
        link = f"{PUBLIC_URL}/blog/{quote(article['slug'])}"
        summary = article["summary"] or ""
        body = re.sub(r"<[^>]+>", " ", article["body_html"] or "")
        body = re.sub(r"\s+", " ", body).strip()[:800]
        items.append(
            "    <item>\n"
            f"      <title>{escape(article['title'])}</title>\n"
            f"      <link>{escape(link)}</link>\n"
            f"      <guid isPermaLink=\"true\">{escape(link)}</guid>\n"
            f"      <pubDate>{rss_date(article['published_at'])}</pubDate>\n"
            f"      <description>{escape(summary or body)}</description>\n"
            "    </item>"
        )
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<rss version="2.0"><channel>\n'
        f"  <title>{escape(SITE_NAME)}</title>\n"
        f"  <link>{escape(PUBLIC_URL)}/</link>\n"
        f"  <description>{escape(SITE_DESCRIPTION)}</description>\n"
        "  <language>es</language>\n"
        f"  <lastBuildDate>{rss_date(datetime.now(UTC).replace(tzinfo=None))}</lastBuildDate>\n"
        + "\n".join(items)
        + "\n</channel></rss>\n"
    )
    return Response(xml, media_type="application/rss+xml; charset=utf-8")


@app.get("/sitemap.xml")
def sitemap() -> Response:
    with db() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT slug, published_at FROM articles WHERE status='published' "
            "ORDER BY published_at DESC"
        )
        articles = cur.fetchall()
    urls = [
        f"  <url><loc>{escape(PUBLIC_URL)}/</loc></url>",
        f"  <url><loc>{escape(PUBLIC_URL)}/archivo</loc></url>",
    ]
    for article in articles:
        loc = f"{PUBLIC_URL}/blog/{quote(article['slug'])}"
        lastmod = (
            article["published_at"].strftime("%Y-%m-%d")
            if article["published_at"]
            else ""
        )
        suffix = f"<lastmod>{lastmod}</lastmod>" if lastmod else ""
        urls.append(f"  <url><loc>{escape(loc)}</loc>{suffix}</url>")
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + "\n".join(urls)
        + "\n</urlset>\n"
    )
    return Response(xml, media_type="application/xml; charset=utf-8")


@app.get("/robots.txt")
def robots() -> PlainTextResponse:
    body = (
        "User-agent: *\n"
        "Allow: /\n"
        "Disallow: /admin\n"
        "Disallow: /auth/\n"
        f"Sitemap: {PUBLIC_URL}/sitemap.xml\n"
    )
    return PlainTextResponse(body)


@app.get("/blog/{slug}", response_class=HTMLResponse)
def article_page(request: Request, slug: str, comment_status: str = "") -> HTMLResponse:
    with db() as conn, conn.cursor() as cur:
        cur.execute("SELECT * FROM articles WHERE slug=%s AND status='published'", (slug,))
        article = cur.fetchone()
        if article is None:
            return render(request, "not_found.html", status_code=404)
        cur.execute(
            "SELECT user_name, body, created_at FROM comments "
            "WHERE article_id=%s AND status='approved' ORDER BY created_at",
            (article["id"],),
        )
        comments = cur.fetchall()
        cur.execute(
            "SELECT id, slug, title, cover_url, published_at FROM articles "
            "WHERE status='published' AND id<>%s "
            "ORDER BY published_at DESC, created_at DESC LIMIT 3",
            (article["id"],),
        )
        related = cur.fetchall()
    notice = {
        "pending": "Comentario recibido; quedará visible tras moderación.",
        "ok": "Comentario publicado.",
    }.get(comment_status, "")
    return render(
        request,
        "article.html",
        article=article,
        body_html=sanitize_html(article["body_html"]),
        comments=comments,
        related=related,
        notice=notice,
        canonical=f"{PUBLIC_URL}/blog/{quote(article['slug'])}",
        reading_minutes=reading_minutes(article["body_html"]),
        published_rfc822=rss_date(article["published_at"]),
        description=article["summary"] or SITE_DESCRIPTION,
        og_type="article",
        og_image=(
            f"{PUBLIC_URL}{article['cover_url']}"
            if str(article["cover_url"] or "").startswith("/")
            else article["cover_url"]
        ),
    )


@app.get("/auth/session")
def auth_session(
    request: Request,
    token: str = "",
    refresh_token: str = "",
    next: str = "/admin",
) -> RedirectResponse:
    target = next if next.startswith("/") and not next.startswith("//") else "/admin"
    if token and public_user(token):
        response = RedirectResponse(target, status_code=303)
        set_cookie(
            response,
            request,
            token,
            refresh_token or request.cookies.get(REFRESH_COOKIE, ""),
        )
        return response
    candidate = refresh_tokens(
        refresh_token
        or request.cookies.get(REFRESH_COOKIE, "")
        or getattr(request.state, "blog_refresh", "")
    )
    if candidate and public_user(str(candidate["access_token"])):
        response = RedirectResponse(target, status_code=303)
        set_cookie(
            response,
            request,
            str(candidate["access_token"]),
            str(candidate["refresh_token"]),
        )
        return response
    if token:
        return RedirectResponse("/?session=error", status_code=303)
    return RedirectResponse("/login", status_code=303)


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request, error: str = "") -> HTMLResponse:
    return render(
        request,
        "login.html",
        error=error,
        canonical=f"{PUBLIC_URL}/login",
    )


@app.get("/logout")
def logout() -> RedirectResponse:
    response = RedirectResponse("/", status_code=303)
    response.delete_cookie(COOKIE, path="/")
    response.delete_cookie(REFRESH_COOKIE, path="/")
    return response


@app.post("/comments")
def create_comment(
    request: Request,
    article_id: str = Form(...),
    body: str = Form(...),
    slug: str = Form(""),
) -> RedirectResponse:
    user = public_user(token_for(request))
    if not user:
        return RedirectResponse("/", status_code=303)
    body = re.sub(r"\s+", " ", body).strip()[:4000]
    if body:
        status = "pending" if COMMENT_MODERATION else "approved"
        with db() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO comments (id, article_id, user_id, user_name, body, status, created_at) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s)",
                (
                    str(uuid.uuid4()),
                    article_id,
                    str(user["user_id"]),
                    str(user.get("name") or user.get("email") or "OSAP"),
                    body,
                    status,
                    utcnow(),
                ),
            )
            conn.commit()
    return RedirectResponse(
        f"/blog/{quote(slug)}?comment_status={'pending' if COMMENT_MODERATION else 'ok'}",
        status_code=303,
    )


@app.get("/admin", response_class=HTMLResponse)
def admin(request: Request) -> HTMLResponse:
    user = public_user(token_for(request))
    if not can_edit(user):
        return render(request, "forbidden.html", status_code=403)
    with db() as conn, conn.cursor() as cur:
        cur.execute("SELECT * FROM articles ORDER BY updated_at DESC")
        articles = cur.fetchall()
        cur.execute(
            "SELECT c.*, a.title, a.slug FROM comments c JOIN articles a ON a.id=c.article_id "
            "WHERE c.status='pending' ORDER BY c.created_at"
        )
        comments = cur.fetchall()
    return render(request, "admin.html", articles=articles, comments=comments)


@app.get("/admin/new", response_class=HTMLResponse)
def new_article(request: Request) -> HTMLResponse:
    if not can_edit(public_user(token_for(request))):
        return render(request, "forbidden.html", status_code=403)
    return render(request, "edit.html", article=None, body_html="", editing=False)


@app.get("/admin/{article_id}/edit", response_class=HTMLResponse)
def edit_article(request: Request, article_id: str) -> HTMLResponse:
    if not can_edit(public_user(token_for(request))):
        return render(request, "forbidden.html", status_code=403)
    with db() as conn, conn.cursor() as cur:
        cur.execute("SELECT * FROM articles WHERE id=%s", (article_id,))
        article = cur.fetchone()
    if article is None:
        return render(request, "not_found.html", status_code=404)
    return render(
        request,
        "edit.html",
        article=article,
        body_html=sanitize_html(article["body_html"]),
        editing=True,
    )


def save_article(
    request: Request,
    article_id: str | None,
    title: str,
    summary: str,
    body: str,
    cover_url: str,
    publish: bool,
) -> RedirectResponse:
    user = public_user(token_for(request))
    if not can_edit(user):
        return RedirectResponse("/login?error=session", status_code=303)
    title = title.strip()
    if not title:
        return RedirectResponse("/admin", status_code=303)
    clean_body = sanitize_html(body)
    LOGGER.info(
        "save article id=%s title_len=%d body_len=%d clean_len=%d",
        article_id or "new",
        len(title),
        len(body),
        len(clean_body),
    )
    now = utcnow()
    with db() as conn, conn.cursor() as cur:
        if article_id:
            cur.execute("SELECT id, body_html, published_at FROM articles WHERE id=%s", (article_id,))
            current = cur.fetchone()
            if current is None:
                return RedirectResponse("/admin", status_code=303)
            cur.execute(
                "INSERT INTO article_revisions (id, article_id, body_html, author_id, created_at) "
                "VALUES (%s,%s,%s,%s,%s)",
                (str(uuid.uuid4()), article_id, current["body_html"], str(user["user_id"]), now),
            )
            published_at = current["published_at"] or (now if publish else None)
            cur.execute(
                "UPDATE articles SET title=%s, summary=%s, body_html=%s, cover_url=%s, "
                "status=%s, published_at=%s, updated_at=%s WHERE id=%s",
                (
                    title,
                    summary.strip() or None,
                    clean_body,
                    cover_url.strip() or None,
                    "published" if publish else "draft",
                    published_at,
                    now,
                    article_id,
                ),
            )
        else:
            article_id = str(uuid.uuid4())
            cur.execute(
                "INSERT INTO articles (id, slug, title, summary, body_html, cover_url, status, "
                "author_id, author_name, published_at, created_at, updated_at) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    article_id,
                    unique_slug(title),
                    title,
                    summary.strip() or None,
                    clean_body,
                    cover_url.strip() or None,
                    "published" if publish else "draft",
                    str(user["user_id"]),
                    str(user.get("name") or user.get("email") or "OSAP"),
                    now if publish else None,
                    now,
                    now,
                ),
            )
        conn.commit()
    return RedirectResponse(f"/admin/{article_id}/edit", status_code=303)


@app.post("/admin/new")
def create_article(
    request: Request,
    title: str = Form(...),
    summary: str = Form(""),
    body: str = Form(""),
    cover_url: str = Form(""),
    publish: str = Form("0"),
) -> RedirectResponse:
    return save_article(request, None, title, summary, body, cover_url, publish == "1")


@app.post("/admin/{article_id}/edit")
def update_article(
    request: Request,
    article_id: str,
    title: str = Form(...),
    summary: str = Form(""),
    body: str = Form(""),
    cover_url: str = Form(""),
    publish: str = Form("0"),
) -> RedirectResponse:
    return save_article(request, article_id, title, summary, body, cover_url, publish == "1")


@app.get("/admin/media")
def list_media(request: Request) -> JSONResponse:
    user = public_user(token_for(request))
    if not can_edit(user):
        return JSONResponse({"error": "No autorizado"}, status_code=403)
    with db() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT id, filename, content_type, created_at FROM media "
            "WHERE content_type LIKE 'image/%' "
            "AND (uploaded_by=%s OR uploaded_by='legacy') "
            "ORDER BY created_at DESC LIMIT 100",
            (str(user["user_id"]),),
        )
        rows = cur.fetchall()
    return JSONResponse(
        {
            "items": [
                {
                    "id": row["id"],
                    "name": row["filename"],
                    "url": f"/media/{row['id']}",
                    "created_at": row["created_at"].isoformat() if row["created_at"] else None,
                }
                for row in rows
            ]
        }
    )


@app.post("/admin/upload")
def upload_media(
    request: Request, image: UploadFile = File(...)  # noqa: B008
) -> JSONResponse:
    user = public_user(token_for(request))
    if not can_edit(user):
        return JSONResponse({"error": "No autorizado"}, status_code=403)
    content_type = image.content_type or ""
    if not content_type.startswith("image/"):
        return JSONResponse({"error": "El archivo no es una imagen"}, status_code=400)
    data = image.file.read(MAX_UPLOAD + 1)
    if len(data) > MAX_UPLOAD:
        return JSONResponse({"error": "Imagen demasiado grande"}, status_code=413)
    extension = {
        "image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp",
        "image/gif": ".gif",
    }.get(content_type, ".bin")
    media_id = str(uuid.uuid4())
    path = MEDIA_ROOT / f"{media_id}{extension}"
    path.write_bytes(data)
    with db() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO media (id, filename, content_type, path, uploaded_by, created_at) "
            "VALUES (%s,%s,%s,%s,%s,%s)",
            (media_id, image.filename or path.name, content_type, path.name, str(user["user_id"]), utcnow()),
        )
        conn.commit()
    return JSONResponse({"url": f"/media/{media_id}", "id": media_id})


@app.get("/media/{media_id}")
def media(media_id: str) -> FileResponse:
    with db() as conn, conn.cursor() as cur:
        cur.execute("SELECT path, content_type FROM media WHERE id=%s", (media_id,))
        row = cur.fetchone()
    if row is None:
        raise HTTPException(status_code=404)
    path = MEDIA_ROOT / row["path"]
    if not path.exists():
        raise HTTPException(status_code=404)
    return FileResponse(path, media_type=row["content_type"])


@app.post("/admin/comments/{comment_id}/{decision}")
def moderate_comment(request: Request, comment_id: str, decision: str) -> RedirectResponse:
    if not can_edit(public_user(token_for(request))) or decision not in {"approved", "rejected"}:
        return RedirectResponse("/admin", status_code=303)
    with db() as conn, conn.cursor() as cur:
        cur.execute("UPDATE comments SET status=%s WHERE id=%s", (decision, comment_id))
        conn.commit()
    return RedirectResponse("/admin", status_code=303)





