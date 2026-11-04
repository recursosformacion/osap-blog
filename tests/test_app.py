from io import BytesIO

from PIL import Image

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
