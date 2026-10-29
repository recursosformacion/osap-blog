"""Migra artículos del blog antiguo (`amigos_articles`) a la base propia del blog.

Lee en modo solo lectura la tabla de origen y escribe en `osap_blog.articles`.
No toca la base de origen.

Uso:
    .venv\\Scripts\\python.exe scripts/migrate_legacy_articles.py --dry-run
    .venv\\Scripts\\python.exe scripts/migrate_legacy_articles.py --apply

Por defecto migra solo `scope='general'` publicados. Para el blog general antiguo:
    --scope general
Para incluir los artículos de grupos:
    --scope all
Para traer borradores/pendientes:
    --include-unpublished
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx
import pymysql
import yaml
from pymysql.cursors import DictCursor

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import MEDIA_ROOT, sanitize_html, slugify


def load_config() -> dict[str, Any]:
    with (ROOT / "config.yaml").open(encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def as_datetime(value: Any) -> datetime | None:
    if value is None or isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def truncate(value: Any, size: int) -> str:
    return str(value or "").strip()[:size]


def import_cover(
    cur: Any,
    source_url: str | None,
    article_id: str,
    author_id: str,
    created: datetime,
) -> str | None:
    """Descarga una portada externa y la registra en el almacén local del blog."""
    url = (source_url or "").strip()
    if not url:
        return None
    if url.startswith("/media/"):
        return url
    if not url.startswith(("http://", "https://")):
        return url
    try:
        with httpx.Client(follow_redirects=True, timeout=25) as client:
            response = client.get(url)
            response.raise_for_status()
    except httpx.HTTPError as exc:
        print(f"  portada no descargada ({article_id}): {exc}")
        return url
    content_type = response.headers.get("content-type", "").split(";")[0].strip().lower()
    if not content_type.startswith("image/"):
        print(f"  portada ignorada ({article_id}): {content_type or 'sin tipo'}")
        return url
    suffix = {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
        "image/gif": ".gif",
        "image/avif": ".avif",
    }.get(content_type, ".img")
    media_id = str(uuid.uuid4())
    path = MEDIA_ROOT / f"{media_id}{suffix}"
    path.write_bytes(response.content)
    try:
        cur.execute(
            "INSERT INTO media (id, filename, content_type, path, uploaded_by, created_at) "
            "VALUES (%s,%s,%s,%s,%s,%s)",
            (media_id, f"legacy-{article_id}{suffix}", content_type, path.name, author_id, created),
        )
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return f"/media/{media_id}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-db", default="osap_api")
    parser.add_argument("--source-table", default="amigos_articles")
    parser.add_argument("--source-host", default="127.0.0.1")
    parser.add_argument("--source-port", type=int, default=3306)
    parser.add_argument("--source-user", default="osap2027")
    parser.add_argument(
        "--source-password-env",
        default="OSAP_SOURCE_DB_PASSWORD",
        help="Variable de entorno con la contraseña de origen.",
    )
    parser.add_argument("--scope", choices=("general", "all"), default="general")
    parser.add_argument("--include-unpublished", action="store_true")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument(
        "--cover-base",
        default="",
        help="Sustituye el origen de las portadas (p. ej. http://127.0.0.1:8001).",
    )
    parser.add_argument(
        "--skip-covers",
        action="store_true",
        help="No descargar portadas externas al almacén local.",
    )
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if args.apply and args.dry_run:
        raise SystemExit("Usa --apply o --dry-run, no ambos.")

    if not re.fullmatch(r"[A-Za-z0-9_]+", args.source_table):
        raise SystemExit("nombre de tabla de origen inválido")

    config = load_config()
    target_db = config["db"]
    source_password = os.environ.get(args.source_password_env) or str(target_db.get("password", ""))
    source = pymysql.connect(
        host=args.source_host,
        port=args.source_port,
        user=args.source_user,
        password=source_password,
        database=args.source_db,
        charset="utf8mb4",
        cursorclass=DictCursor,
        autocommit=True,
        read_timeout=30,
    )
    target = pymysql.connect(
        host=target_db.get("host", "127.0.0.1"),
        port=int(target_db.get("port", 3306)),
        user=target_db["user"],
        password=os.environ.get("OSAP_BLOG_DB_PASSWORD") or target_db["password"],
        database=target_db["name"],
        charset="utf8mb4",
        cursorclass=DictCursor,
        autocommit=False,
    )

    try:
        with source.cursor() as cur:
            cur.execute(f"DESCRIBE `{args.source_table}`")
            columns = {str(row["Field"]) for row in cur.fetchall()}
            required = {"id", "title", "body", "status"}
            missing = required - columns
            if missing:
                raise SystemExit(f"la tabla de origen no tiene columnas: {', '.join(sorted(missing))}")

            where: list[str] = []
            params: list[Any] = []
            if args.scope == "general" and "scope" in columns:
                where.append("scope=%s")
                params.append("general")
            if not args.include_unpublished:
                where.append("status=%s")
                params.append("published")
            sql = f"SELECT * FROM `{args.source_table}`"
            if where:
                sql += " WHERE " + " AND ".join(where)
            sql += " ORDER BY created_at ASC, id ASC"
            if args.limit > 0:
                sql += " LIMIT %s"
                params.append(args.limit)
            cur.execute(sql, params)
            rows = cur.fetchall()

        if not rows:
            print("No hay artículos que migrar con los filtros indicados.")
            return

        print(f"Artículos de origen: {len(rows)}")
        print("Muestra:", ", ".join(str(row["id"]) for row in rows[:5]))
        if args.dry_run or not args.apply:
            print("Dry-run: no se ha escrito nada. Usa --apply para migrar.")
            return

        inserted = updated = skipped = 0
        with target.cursor() as cur:
            for row in rows:
                source_id = truncate(row["id"], 36)
                title = truncate(row["title"], 300)
                body = sanitize_html(str(row.get("body") or ""))
                if not body.strip():
                    body = "<p></p>"
                base_slug = slugify(str(row.get("slug") or title)) or f"articulo-{source_id[:8]}"
                base_slug = base_slug[:170]
                slug = base_slug
                suffix = 1
                while True:
                    cur.execute("SELECT id FROM articles WHERE slug=%s", (slug,))
                    owner = cur.fetchone()
                    if owner is None or str(owner["id"]) == source_id:
                        break
                    suffix += 1
                    slug = f"{base_slug[:160]}-{suffix}"

                status = "published" if str(row.get("status")) == "published" else "draft"
                created = as_datetime(row.get("created_at")) or datetime.now(UTC).replace(tzinfo=None)
                updated_at = as_datetime(row.get("updated_at")) or created
                published = as_datetime(row.get("published_at"))
                if status == "published" and published is None:
                    published = created
                author_id = truncate(row.get("author_user_id") or row.get("author_id") or "legacy", 64)
                author_name = truncate(row.get("author_name"), 200) or None
                summary = truncate(row.get("summary"), 600) or None
                cover_source = truncate(row.get("cover_url"), 800) or None
                if cover_source and args.cover_base:
                    parts = urlsplit(cover_source)
                    base = urlsplit(args.cover_base)
                    cover_source = urlunsplit((base.scheme, base.netloc, parts.path, parts.query, parts.fragment))
                cover_url = cover_source
                if cover_source and not args.skip_covers and not cover_source.startswith("/media/"):
                    cover_url = import_cover(cur, cover_source, source_id, author_id, created)

                cur.execute(
                    """
                    INSERT INTO articles
                      (id, slug, title, summary, body_html, cover_url, status,
                       author_id, author_name, published_at, created_at, updated_at)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON DUPLICATE KEY UPDATE
                      slug=VALUES(slug), title=VALUES(title), summary=VALUES(summary),
                      body_html=VALUES(body_html), cover_url=VALUES(cover_url),
                      status=VALUES(status), author_name=VALUES(author_name),
                      published_at=VALUES(published_at), updated_at=VALUES(updated_at)
                    """,
                    (
                        source_id, slug, title, summary, body, cover_url, status,
                        author_id, author_name, published, created, updated_at,
                    ),
                )
                if cur.rowcount == 1:
                    inserted += 1
                elif cur.rowcount == 2:
                    updated += 1
                else:
                    skipped += 1
            target.commit()

        print(f"Insertados: {inserted}; actualizados: {updated}; sin cambios: {skipped}")
    finally:
        source.close()
        target.close()


if __name__ == "__main__":
    main()
