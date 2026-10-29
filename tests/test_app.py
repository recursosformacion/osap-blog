from app import sanitize_html, slugify


def test_sanitize_keeps_formatting_and_drops_scripts() -> None:
    raw = '<p>Hola <strong>mundo</strong><script>alert(1)</script></p>'
    assert sanitize_html(raw) == '<p>Hola <strong>mundo</strong></p>'


def test_sanitize_allows_editor_images_and_alignment() -> None:
    raw = '<figure class="align-right"><img src="/media/abc" alt="Retrato"><figcaption>Pie</figcaption></figure>'
    clean = sanitize_html(raw)
    assert 'class="align-right"' in clean
    assert 'src="/media/abc"' in clean
    assert "figcaption" in clean


def test_sanitize_allows_http_images_but_rejects_active_sources() -> None:
    assert "<img" in sanitize_html('<img src="https://example.org/x.png" alt="x">')
    assert "<img" not in sanitize_html('<img src="javascript:alert(1)" alt="x">')
    assert "<img" not in sanitize_html('<img src="//example.org/x.png" alt="x">')


def test_slugify() -> None:
    assert slugify("Canción de prueba, número 1") == "cancion-de-prueba-numero-1"
