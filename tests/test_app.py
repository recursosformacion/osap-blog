from io import BytesIO

from PIL import Image
from starlette.requests import Request

import app as blog_app
from app import faq_schema_json, optimize_image, sanitize_html, slugify


def test_sanitize_keeps_formatting_and_drops_scripts() -> None:
    raw = '<p>Hola <strong>mundo</strong><script>alert(1)</script></p>'
    assert sanitize_html(raw) == '<p>Hola <strong>mundo</strong></p>'


def test_sanitize_allows_editor_images_and_alignment() -> None:
    raw = '<figure class="align-right"><img src="/media/abc" alt="Retrato"><figcaption>Pie</figcaption></figure>'
    clean = sanitize_html(raw)
    assert 'class="align-right"' in clean
    assert 'src="/media/abc"' in clean
    assert "figcaption" in clean


def test_sanitize_allows_image_size_classes() -> None:
    raw = '<figure class="align-left media-50"><img src="/media/abc" alt="Retrato"></figure>'
    clean = sanitize_html(raw)
    assert 'class="align-left media-50"' in clean


def test_sanitize_allows_http_images_but_rejects_active_sources() -> None:
    assert "<img" in sanitize_html('<img src="https://example.org/x.png" alt="x">')
    assert "<img" not in sanitize_html('<img src="javascript:alert(1)" alt="x">')
    assert "<img" not in sanitize_html('<img src="//example.org/x.png" alt="x">')


def test_faq_details_are_kept_and_rendered_as_faq_schema() -> None:
    raw = (
        "<details><summary>¿Qué es OSAP?</summary>"
        "<p>Una plataforma de obras musicales.</p></details>"
    )
    clean = sanitize_html(raw)
    assert clean == raw
    schema = faq_schema_json(clean)
    assert '"@type": "FAQPage"' in schema
    assert '"name": "¿Qué es OSAP?"' in schema
    assert '"text": "Una plataforma de obras musicales."' in schema


def test_faq_schema_is_empty_without_details() -> None:
    assert faq_schema_json("<p>Sin preguntas</p>") == ""


def test_image_optimizer_converts_jpeg_to_webp() -> None:
    source = BytesIO()
    Image.new("RGB", (320, 200), "white").save(source, format="JPEG", quality=95)
    optimized, content_type = optimize_image(source.getvalue())
    assert content_type == "image/webp"
    with Image.open(BytesIO(optimized)) as result:
        assert result.format == "WEBP"
        assert result.size == (320, 200)


def test_slugify() -> None:
    assert slugify("Canción de prueba, número 1") == "cancion-de-prueba-numero-1"


def _request_with_cookies(cookie: str) -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/admin",
            "headers": [(b"cookie", cookie.encode("latin-1"))],
            "query_string": b"",
            "scheme": "https",
            "server": ("testserver", 443),
            "client": ("testclient", 1234),
        }
    )


def test_editor_access_fails_closed_when_role_allowlist_is_empty(monkeypatch) -> None:
    monkeypatch.setattr(blog_app, "EDITOR_ROLES", [])
    assert not blog_app.can_edit({"user_id": "user-1", "roles": ["admin"]})


def test_editor_access_requires_an_allowed_role(monkeypatch) -> None:
    monkeypatch.setattr(blog_app, "EDITOR_ROLES", ["editor", "blog_admin"])
    assert blog_app.can_edit({"user_id": "user-1", "roles": ["editor"]})
    assert not blog_app.can_edit({"user_id": "user-1", "roles": ["member"]})


def test_session_user_uses_fresh_auth_roles_not_cached_cookie_roles(monkeypatch) -> None:
    cached_user = {"user_id": "user-1", "roles": ["admin"]}
    signed_session = blog_app._session_payload(cached_user)
    request = _request_with_cookies(
        f"{blog_app.SESSION_COOKIE}={signed_session}; "
        f"{blog_app.COOKIE}=valid-access-token"
    )
    monkeypatch.setattr(
        blog_app,
        "public_user",
        lambda token: (
            {"user_id": "user-1", "roles": ["member"]}
            if token == "valid-access-token"
            else None
        ),
    )

    user = blog_app.session_user(request)

    assert user is not None
    assert user["roles"] == ["member"]


def test_session_user_rejects_revoked_or_invalid_access_token(monkeypatch) -> None:
    signed_session = blog_app._session_payload(
        {"user_id": "user-1", "roles": ["admin"]}
    )
    request = _request_with_cookies(
        f"{blog_app.SESSION_COOKIE}={signed_session}; "
        f"{blog_app.COOKIE}=revoked-access-token"
    )
    monkeypatch.setattr(blog_app, "public_user", lambda _token: None)

    assert blog_app.session_user(request) is None


def test_blog_session_handoff_is_post_only() -> None:
    routes = [route for route in blog_app.app.routes if getattr(route, "path", None) == "/auth/session"]
    assert len(routes) == 1
    assert routes[0].methods == {"POST"}

def test_refresh_cache_reuses_rotated_pair_without_second_auth_call(monkeypatch) -> None:
    blog_app._REFRESH_CACHE.clear()
    calls = []

    class FakeResponse:
        status_code = 200

        @staticmethod
        def json():
            return {"access_token": "new-access", "refresh_token": "new-refresh"}

    def fake_post(*args, **kwargs):
        calls.append((args, kwargs))
        return FakeResponse()

    monkeypatch.setattr(blog_app.httpx, "post", fake_post)
    first = blog_app.refresh_tokens("old-refresh")
    second = blog_app.refresh_tokens("old-refresh")

    assert first == second
    assert first == {"access_token": "new-access", "refresh_token": "new-refresh"}
    assert len(calls) == 1


def test_auth_session_rejects_backslash_open_redirect(monkeypatch) -> None:
    monkeypatch.setattr(
        blog_app,
        "public_user",
        lambda _token: {"user_id": "user-1", "roles": ["admin"]},
    )

    response = blog_app.auth_session(
        _request_with_cookies(""),
        access_token="valid-access-token",
        refresh_token="",
        next="/\\evil.example",
    )

    assert response.headers["location"] == "/admin"


def test_logout_rejects_backslash_open_redirect() -> None:
    response = blog_app.logout(
        _request_with_cookies(""),
        next="/\\evil.example",
    )

    assert response.headers["location"] == "/"


def test_logout_allows_only_configured_osap_home(monkeypatch) -> None:
    monkeypatch.setattr(blog_app, "OSAP_URL", "https://osap.example")
    monkeypatch.setattr(blog_app, "PUBLIC_URL", "https://blog.example")

    response = blog_app.logout(
        _request_with_cookies(""),
        next="https://osap.example/",
    )

    assert response.headers["location"] == "https://osap.example/"


def test_logout_rejects_non_root_path_on_configured_origin(monkeypatch) -> None:
    monkeypatch.setattr(blog_app, "OSAP_URL", "https://osap.example")
    monkeypatch.setattr(blog_app, "PUBLIC_URL", "https://blog.example")

    response = blog_app.logout(
        _request_with_cookies(""),
        next="https://osap.example/account?continue=/admin",
    )

    assert response.headers["location"] == "/"


def test_logout_rejects_unconfigured_absolute_origin(monkeypatch) -> None:
    monkeypatch.setattr(blog_app, "OSAP_URL", "https://osap.example")
    monkeypatch.setattr(blog_app, "PUBLIC_URL", "https://blog.example")

    response = blog_app.logout(
        _request_with_cookies(""),
        next="https://attacker.example/",
    )

    assert response.headers["location"] == "/"


def test_refresh_cache_does_not_reuse_expired_entry(monkeypatch) -> None:
    blog_app._REFRESH_CACHE.clear()
    blog_app._REFRESH_CACHE["old-refresh"] = (
        10.0,
        {"access_token": "expired-access", "refresh_token": "expired-refresh"},
    )
    calls = []

    class FakeResponse:
        status_code = 200

        @staticmethod
        def json():
            return {"access_token": "new-access", "refresh_token": "new-refresh"}

    def fake_post(*args, **kwargs):
        calls.append((args, kwargs))
        return FakeResponse()

    monkeypatch.setattr(blog_app.time, "monotonic", lambda: 20.0)
    monkeypatch.setattr(blog_app.httpx, "post", fake_post)

    result = blog_app.refresh_tokens("old-refresh")

    assert result == {"access_token": "new-access", "refresh_token": "new-refresh"}
    assert len(calls) == 1
    blog_app._REFRESH_CACHE.clear()


def test_refresh_cache_expires_entries_and_is_bounded(monkeypatch) -> None:
    blog_app._REFRESH_CACHE.clear()
    blog_app._REFRESH_CACHE["expired"] = (10.0, {"access_token": "a", "refresh_token": "b"})
    blog_app._REFRESH_CACHE["oldest"] = (1000.0, {"access_token": "a", "refresh_token": "b"})
    monkeypatch.setattr(blog_app, "_REFRESH_CACHE_MAX_ENTRIES", 2)

    blog_app._prune_refresh_cache(10.0)
    assert "expired" not in blog_app._REFRESH_CACHE

    blog_app._REFRESH_CACHE["newer"] = (1000.0, {"access_token": "a", "refresh_token": "b"})
    blog_app._REFRESH_CACHE["newest"] = (1000.0, {"access_token": "a", "refresh_token": "b"})
    blog_app._prune_refresh_cache(20.0)

    assert len(blog_app._REFRESH_CACHE) == 2
    assert "oldest" not in blog_app._REFRESH_CACHE
    blog_app._REFRESH_CACHE.clear()
