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

- integración real con Strava
- lógica de negocio completa
- pruebas end-to-end contra BD real

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

Endpoints iniciales:

- `GET /health`
- `POST /api/v1/auth/login`
- `GET /api/v1/auth/me`
- `GET /api/v1/athletes/me`

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
