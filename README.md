# cycling-coach-api

Base inicial del backend para una plataforma de análisis y planificación de entrenamiento de ciclismo, pensada para integrarse con Strava y servir clientes mobile/web mediante una API limpia y mantenible.

## Objetivo de esta base

Esta primera iteración prioriza foundation:

- FastAPI runnable
- configuración por entorno
- capa de acceso a base de datos con SQLAlchemy 2.x
- modelos iniciales y contratos base
- estructura modular para crecer hacia auth, atletas, actividades, planificación y sincronización con Strava
- tests mínimos para validar que la app arranca

No incluye todavía:

- pruebas end-to-end reales contra Strava con credenciales de dev válidas
- lógica de negocio completa aguas abajo del catálogo de actividades
- workers/colas para sync asíncrono en background

## Stack

- Python 3.11+
- FastAPI
- SQLAlchemy 2.x
- PostgreSQL (orientado a Neon)
- Pydantic Settings
- Pytest
- Ruff / MyPy

## Estructura

```text
cycling-coach-api/
├── pyproject.toml
├── README.md
├── .env.example
├── src/
│   └── app/
│       ├── main.py
│       ├── api/
│       │   └── v1/
│       │       ├── router.py
│       │       └── endpoints/
│       │           ├── auth.py
│       │           ├── health.py
│       │           └── athletes.py
│       ├── core/
│       │   ├── config.py
│       │   ├── logging.py
│       │   └── security.py
│       ├── db/
│       │   ├── base.py
│       │   └── session.py
│       ├── models/
│       │   ├── athlete.py
│       │   ├── session.py
│       │   ├── user.py
│       │   └── workout.py
│       ├── repositories/
│       │   ├── athlete.py
│       │   ├── session.py
│       │   └── user.py
│       ├── schemas/
│       │   ├── athlete.py
│       │   ├── auth.py
│       │   └── common.py
│       └── services/
│           ├── athlete.py
│           └── auth.py
├── alembic/
│   ├── env.py
│   └── versions/
└── tests/
    └── test_health.py
```

## Variables de entorno

Copiar el archivo de ejemplo:

```bash
cp .env.example .env
```

Variables clave:

- `APP_ENV`: `local`, `staging`, `production`, `test`
- `APP_NAME`: nombre visible de la API
- `APP_DEBUG`: habilita modo debug
- `API_V1_PREFIX`: prefijo de rutas versionadas
- `DATABASE_URL`: URL async/sync compatible con PostgreSQL/Neon
- `CORS_ORIGINS`: lista separada por comas
- `JWT_SECRET`: secreto para firmar access tokens
- `ACCESS_TOKEN_TTL_MINUTES`: duración del access token
- `REFRESH_TOKEN_TTL_DAYS`: duración de sesiones refresh
- `BOOTSTRAP_ADMIN_EMAIL`: admin inicial opcional
- `BOOTSTRAP_ADMIN_PASSWORD`: password del admin inicial opcional
- `STRAVA_CLIENT_ID`: client id de la app Strava de dev
- `STRAVA_CLIENT_SECRET`: client secret de la app Strava de dev
- `STRAVA_REDIRECT_URI`: callback backend registrado en Strava, por ejemplo `https://cycling-coach-api.onrender.com/api/v1/strava/callback`
- `STRAVA_FRONTEND_REDIRECT_URI`: URL de frontend a la que el backend redirige tras completar el callback, por ejemplo `https://cycling-coach-web.vercel.app/integrations/strava/callback`
- `STRAVA_OAUTH_STATE_TTL_MINUTES`: TTL del state firmado OAuth
- `STRAVA_DEFAULT_ACTIVITY_LIMIT`: tamaño de sync incremental
- `STRAVA_FULL_SYNC_MAX_PAGES`: máximo de páginas para import histórico en dev
- `STRAVA_TOKEN_REFRESH_SKEW_SECONDS`: margen para refrescar token antes del vencimiento real
- `STRAVA_WEBHOOK_VERIFY_TOKEN`: token compartido que Strava usa para verificar la suscripción webhook
- `STRAVA_WEBHOOK_CALLBACK_URL`: URL pública dev del endpoint `GET/POST /api/v1/strava/webhook`
- `STRAVA_WEBHOOK_SUBSCRIPTION_ID`: id dev de la subscription creada en Strava (informativo por ahora)
- `TOKEN_ENCRYPTION_SECRET`: secreto para cifrar access/refresh tokens persistidos

## Instalación

Con `uv`:

```bash
uv sync --all-extras
```

O con `pip`:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
```

## Ejecutar en local

```bash
uvicorn app.main:app --app-dir src --reload
```

Endpoints principales:

- `GET /health`
- `POST /api/v1/auth/login`
- `GET /api/v1/auth/me`
- `GET /api/v1/athletes/me`
- `GET /api/v1/strava/webhook`
- `POST /api/v1/strava/webhook`
- `GET /api/v1/strava/connect-url`
- `GET /api/v1/strava/callback`
- `GET /api/v1/strava/status`
- `POST /api/v1/strava/sync`

### Flujo Strava en dev

1. El frontend autenticado pide `GET /api/v1/strava/connect-url`.
2. Redirige al usuario a `authorize_url` en Strava.
3. Strava vuelve a `STRAVA_REDIRECT_URI` (`/api/v1/strava/callback`).
4. El backend intercambia el `code`, persiste tokens cifrados y dispara un import histórico inicial para dejar poblada la base propia desde la primera conexión.
5. El callback responde/redirige con el estado de conexión y del import inicial (`state`, `status`, `connected`, `athlete_id`, `scopes`, `token_expires_at`, `last_sync_at`, `initial_sync_completed`, `initial_sync_error`, `imported_count`, `updated_count`). Si falla el callback y la petición no pide JSON, también redirige al frontend con `error` y `message`.
6. A partir de ahí el frontend lee desde la DB vía `GET /api/v1/strava/status`, `GET /api/v1/strava/activities`, `GET /api/v1/strava/activities/overview` y sólo usa `POST /api/v1/strava/sync` para refrescar ingestión.

Notas de implementación actuales:

- Los tokens se persisten cifrados en `oauth_connections`.
- El refresh token se rota si Strava devuelve uno nuevo; si no, se conserva el anterior.
- El backend refresca el access token antes de expirar usando `STRAVA_TOKEN_REFRESH_SKEW_SECONDS`.
- El sync incremental usa `last_sync_at` como cursor (`after`).
- El full sync pagina hasta `STRAVA_FULL_SYNC_MAX_PAGES` para no descontrolarse en dev.
- El webhook MVP soporta verificación de suscripción (`hub.challenge`) y eventos `activity` con `aspect_type=create|update`.
- Cuando llega un webhook válido, el backend busca la conexión Strava activa por `owner_id` (athlete id), refresca token si hace falta, pide el detalle actual de la actividad a Strava y hace upsert en `strava_activities`.
- Los eventos ignorados por ahora: `delete` y objetos no `activity`. Quedan registrados de forma implícita por la respuesta del endpoint, pero no borran datos locales.

### Webhook Strava en dev

Endpoint listo en backend:

- Verify: `GET /api/v1/strava/webhook`
- Receive: `POST /api/v1/strava/webhook`

Qué falta para activarlo contra Strava dev:

1. Exponer una URL pública HTTPS que apunte al backend local/dev.
2. Configurar `STRAVA_WEBHOOK_VERIFY_TOKEN` con un secreto compartido.
3. Configurar `STRAVA_WEBHOOK_CALLBACK_URL` con esa URL pública final.
4. Crear la subscription en Strava Developer API apuntando a esa callback URL y guardarse el `id` dev resultante en `STRAVA_WEBHOOK_SUBSCRIPTION_ID`.

Ejemplo conceptual de alta de subscription (fuera de esta API, contra Strava):

```bash
curl -X POST https://www.strava.com/api/v3/push_subscriptions \
  -F client_id="$STRAVA_CLIENT_ID" \
  -F client_secret="$STRAVA_CLIENT_SECRET" \
  -F callback_url="$STRAVA_WEBHOOK_CALLBACK_URL" \
  -F verify_token="$STRAVA_WEBHOOK_VERIFY_TOKEN"
```

Notas:

- Esto debe hacerse solo con credenciales/dev callback de desarrollo, no prod.
- El backend ya valida el verify token y procesa el POST.
- `STRAVA_WEBHOOK_SUBSCRIPTION_ID` hoy es documental/operativo; no bloquea el procesamiento.

## Testing

```bash
pytest
```

## Próximos pasos sugeridos

1. Instalar dependencias y probar auth contra una BD real de dev.
2. Ejecutar Alembic y materializar `users` + `sessions`.
3. Conectar el frontend al contrato real de `auth/login` y `auth/me`.
4. Modelar ingestión de actividades y sincronización incremental con Strava.
5. Diseñar contratos API-first para métricas, workouts y planes.
