# Changelog — OSAP Blog

## 1.0.3 — 2026-10-29

- Sesión firmada del blog de 7 días, independiente de la caducidad del access token.
- Los guardados usan la sesión del blog cuando existe.

## 1.0.2 — 2026-10-29

- Imágenes pegadas desde el portapapeles se convierten en ficheros `/media/`.
- Conversión de imágenes `data:` al guardar para no perderlas.

## 1.0.1 — 2026-10-29

- Autoguardado local del editor y restauración de borradores.
- Renovación de sesión de OSAP para evitar guardados con token caducado.
- El cuerpo del artículo se conserva aunque falle el JavaScript del editor.
- Subida de portada, biblioteca de imágenes y URLs externas.

## 1.0.0 — 2026-10-29

Primera versión estable en producción.

- Blog público con portada de últimos artículos, destacado, búsqueda, paginación y archivo.
- Artículos con editor de página completa, imágenes alineables, borradores, publicación y revisiones.
- Comentarios con moderación.
- RSS, sitemap y metadatos sociales.
- Autenticación delegada en OSAP con entrada directa desde la SPA y retorno a la administración.
- Migración prod→prod de los artículos generales de `amigos_articles`, incluidas portadas.
- Licencia GPL-3.0.


