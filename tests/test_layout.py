from types import SimpleNamespace

from jinja2 import Environment, FileSystemLoader

from app import BASE_DIR


def render_base(page_type_template: str = "base.html") -> str:
    env = Environment(loader=FileSystemLoader(str(BASE_DIR / "templates")), autoescape=True)
    env.globals["url_for"] = lambda name, **kwargs: f"/static/{kwargs['path']}"
    template = env.get_template(page_type_template)
    return template.render(
        version="test",
        request=SimpleNamespace(url=SimpleNamespace(path="/")),
        site_name="Blog OSAP",
        site_description="Descripción",
        canonical="https://blog.example/",
        feed_url="https://blog.example/feed",
        osap_url="https://app.example",
        login_url="https://auth.example/login",
        can_edit=False,
        user=None,
        user_name="",
        session_error=False,
        q="",
    )


def test_menu_is_rendered_in_a_single_top_header() -> None:
    html = render_base()
    assert '<header class="site-header">' in html
    assert '<nav class="main-nav"' in html
    assert 'class="sidebar"' not in html
    assert html.index('class="site-header"') < html.index('class="layout"')


def test_vertical_ad_rail_is_on_the_right_and_targets_sidebar_placement() -> None:
    html = render_base()
    layout = html[html.index('class="layout"') :]
    assert '<aside class="ad-rail"' in layout
    assert 'data-ad-placement="sidebar"' in layout
    assert 'data-page-type="blog_index"' in layout
    assert 'class="ad-slot ad-tall"' in layout
    assert html.index('class="main"') < html.index('class="ad-rail"')


def test_templates_can_override_the_ad_page_type() -> None:
    env = Environment(loader=FileSystemLoader(str(BASE_DIR / "templates")), autoescape=True)
    env.globals["url_for"] = lambda name, **kwargs: f"/static/{kwargs['path']}"
    child = env.from_string(
        '{% extends "base.html" %}{% block page_type %}blog_article{% endblock %}'
    )
    html = child.render(
        version="test",
        request=SimpleNamespace(url=SimpleNamespace(path="/blog/ejemplo")),
        site_name="Blog OSAP",
        site_description="Descripción",
        canonical="https://blog.example/blog/ejemplo",
        feed_url="https://blog.example/feed",
        osap_url="https://app.example",
        login_url="https://auth.example/login",
        can_edit=False,
        user=None,
        user_name="",
        session_error=False,
        q="",
    )
    assert 'data-page-type="blog_article"' in html


def test_vertical_ad_rail_is_skipped_on_narrow_screens() -> None:
    css = (BASE_DIR / "static" / "blog.css").read_text(encoding="utf-8")
    assert "@media (max-width: 1000px)" in css
    assert ".ad-rail { display: none; }" in css
    assert "grid-template-columns: minmax(0,1fr) 300px" in css


def test_ads_proxy_route_is_registered() -> None:
    from app import app

    assert any(route.path == "/ads/compose" for route in app.routes)
