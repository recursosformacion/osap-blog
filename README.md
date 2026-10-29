# OSAP Blog

Blog independiente de OSAP.

## Estado

Primera versión funcional en local. Tiene:

- Aplicación FastAPI y plantillas Jinja.
- Base de datos propia `osap_blog`.
- Almacén de imágenes propio (`data/media`).
- Autenticación delegada en OSAP (`/auth/me`); no duplica usuarios.
- Editor de página completa con negritas, cursivas, títulos, listas, citas, enlaces e imágenes.
- Imágenes alineadas izquierda, centro o derecha; en móvil se desalinean para no romper el texto.
- Artículos en borrador o publicados, revisiones y comentarios con moderación.
- Sanitización del HTML en servidor; las imágenes del editor solo aceptan `/media/`.

## Arranque local

```powershell
Copy-Item config.example.yaml config.yaml
# ajustar password y rutas
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python -m uvicorn app:app --host 127.0.0.1 --port 8500
```

La base de datos se crea a mano y las tablas al arrancar:

```sql
CREATE DATABASE osap_blog CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```

En desarrollo se puede usar el venv de `osap-api`; el aplicativo no importa su código.

## Acceso y autenticación

El blog solo usa OSAP como proveedor de identidad. Para abrir el panel:

```text
http://localhost:8500/auth/session?token=<access_token_de_OSAP>&next=/admin
```

Eso deja una cookie `HttpOnly` de una hora. Los comentarios usan la misma sesión. El handoff OIDC completo queda pendiente: ahora el token se pasa en la URL de entrada.

`config.yaml`:

- `editor.roles: []` permite editar a cualquier usuario autenticado, útil en desarrollo.
- En producción debe listar roles como `admin`, `editor` o `blog_admin`.
- `editor.moderation: true` deja los comentarios pendientes de aprobación.

## Rutas

- `GET /` — artículos publicados.
- `GET /blog/{slug}` — artículo y comentarios aprobados.
- `POST /comments` — comentario autenticado.
- `GET /admin` — panel, artículos y moderación.
- `GET /admin/new`, `GET /admin/{id}/edit` — editor.
- `POST /admin/upload` — subida de imagen.
- `GET /media/{id}` — imagen.
- `GET /health`.

## Pendiente antes de producción

- Migrar los artículos actuales de `osap-api` conservando ids, slugs y fechas; redirigir las URLs antiguas con 301.
- Cerrar el handoff OIDC (no aceptar tokens de acceso en la URL).
- Copias de seguridad propias de `osap_blog` y del almacén de imágenes.
- Moderación completa, rate limit, antispam y notificaciones.
- Despliegue systemd/nginx y TLS para el subdominio.
