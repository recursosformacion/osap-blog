# OSAP Blog

Blog independiente de OSAP.

## Estado

Versión **1.0.6**, desplegada en producción. Incluye:

- Aplicación FastAPI y plantillas Jinja.
- Base de datos propia `osap_blog`.
- Almacén de imágenes propio (`data/media`).
- Autenticación delegada en OSAP (`/auth/me`); no duplica usuarios.
- Editor de página completa con negritas, cursivas, títulos, listas, citas, enlaces e imágenes.
- Imágenes alineadas izquierda, centro o derecha; en móvil se desalinean para no romper el texto.
- Artículos en borrador o publicados, revisiones y comentarios con moderación.
- Portada pública con últimos artículos, destacado, buscador, paginación, archivo por mes,
  RSS (`/feed`) y sitemap (`/sitemap.xml`), sin exigir identificación.
- Sanitización del HTML en servidor; las imágenes del editor solo aceptan `/media/`.

## Dominios

| Entorno | URL | Servicio |
|---|---|---|
| Desarrollo | `http://osap-blog` | Apache XAMPP → uvicorn `127.0.0.1:8500` |
| Producción | `https://blog.openmusicrepository.com` | nginx → uvicorn `127.0.0.1:8500` |

La entrada desde la SPA de OSAP es el ítem «Blog» del menú lateral. Si hay sesión, el enlace
pasa por `/auth/session` para dejar la cookie del blog; si no, abre la portada pública
directamente.

## Producción

| Elemento | Valor |
|---|---|
| URL | `https://blog.openmusicrepository.com` |
| Servicio | `osap-blog.service` (uvicorn `127.0.0.1:8500`) |
| Directorio | `/home/ocw/openmusicrepository.com/osap-blog` |
| BD | `osap_blog` (usuario dedicado) |
| Config | `config.yaml` sin contraseña; secreto en `/etc/openmusicrepository/osap-blog.env` (600) |
| Nginx | `/etc/nginx/sites-enabled/blog.openmusicrepository.com.conf` |
| TLS | Let's Encrypt por DNS Cloudflare, renovación automática |
| Migración | prod→prod desde `osap_api.amigos_articles` (`scope='general'`); 2 artículos |

El 29/10/2026 se migraron los dos artículos generales publicados de producción y sus
portadas. El origen no se modificó. La copia previa de las tablas de artículos está en
`/root/backups/osap-blog-source-20261029-162128.sql` en el servidor.

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
http://osap-blog/auth/session?token=<access_token_de_OSAP>&next=/admin
```

Eso deja una cookie `HttpOnly` de una hora. Los comentarios usan la misma sesión. La entrada
desde OSAP usa `?auth=login&return_to=blog`: tras autenticarse, OSAP transfiere el token al
blog y abre `/admin`. El handoff OIDC completo queda pendiente: ahora el token se pasa en la
URL de entrada.

`config.yaml`:

- `editor.roles: []` permite editar a cualquier usuario autenticado, útil en desarrollo.
- En producción debe listar roles como `admin`, `editor` o `blog_admin`.
- `editor.moderation: true` deja los comentarios pendientes de aprobación.

## Rutas

- `GET /` — portada pública: últimos artículos, destacado y paginación (`?page=`, `?q=`, `?month=YYYY-MM`).
- `GET /buscar?q=` — buscador (redirige a la portada con `q`).
- `GET /archivo` — archivo agrupado por mes.
- `GET /feed` — RSS 2.0 de los últimos 20 artículos.
- `GET /sitemap.xml`, `GET /robots.txt` — SEO.
- `GET /blog/{slug}` — artículo y comentarios aprobados.
- `POST /comments` — comentario autenticado.
- `GET /admin` — panel, artículos y moderación.
- `GET /admin/new`, `GET /admin/{id}/edit` — editor.
- `POST /admin/upload` — subida de imagen.
- `GET /media/{id}` — imagen.
- `GET /health`.

## Migración del blog antiguo

El blog general antiguo está en `osap_api.amigos_articles` (`scope='general'`). El script
`scripts/migrate_legacy_articles.py` es idempotente, conserva id/slug/fechas, sanea el HTML y
descarga las portadas al almacén local:

```powershell
python scripts/migrate_legacy_articles.py --dry-run
python scripts/migrate_legacy_articles.py --apply
```

Para otros orígenes con las mismas columnas:

```powershell
python scripts/migrate_legacy_articles.py --source-db blog_api --source-table articles --apply
```

Opciones: `--scope all` (incluye artículos de grupos), `--include-unpublished`,
`--skip-covers` y `--limit`. Los artículos generales antiguos
`/amigos/articulo/<id>/<slug>` redirigen con 301 al artículo del blog; los de grupo siguen
en OSAP hasta que se migren expresamente.

## Pendiente

- Migrar artículos de otros orígenes (`blog-api`) si no están en `amigos_articles`, conservando ids, slugs y fechas.
- Cerrar el handoff OIDC (no aceptar tokens de acceso en la URL).
- Programar copias de seguridad propias de `osap_blog` y del almacén de imágenes.
- Moderación completa, rate limit, antispam y notificaciones.
- Añadir el blog al script de despliegue general para que la próxima release sea reproducible.






