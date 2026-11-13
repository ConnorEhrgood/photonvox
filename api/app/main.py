from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import DataError

from app.config import settings
from app.db import engine, system_engine
from app.routes import directory_notify, me, phone_system, platform, tenants

problem = settings.production_safe()
if problem:
    raise RuntimeError(f"Unsafe production configuration: {problem}")

_prod = settings.environment == "production"
app = FastAPI(title="PhotonVox API", docs_url=None if _prod else "/docs", redoc_url=None, openapi_url=None if _prod else "/openapi.json")
app.include_router(me.router)
app.include_router(tenants.router)
app.include_router(phone_system.router)
app.include_router(platform.router)
app.include_router(directory_notify.router)

# Every verb the web app uses; a verb missing here fails in the browser only, as a preflight the API never answers.
CORS_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]

if settings.cors_list:
    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_list, allow_methods=CORS_METHODS,
                       allow_headers=["Authorization", "Content-Type"], max_age=600)


@app.on_event("startup")
def refuse_a_database_role_that_bypasses_row_level_security() -> None:
    """In production neither login may be an owner or superuser: either would skip every policy, which would make them decoration."""
    if not _prod:
        return
    for name, eng in (("DATABASE_URL", engine), ("SYSTEM_DATABASE_URL", system_engine)):
        with eng.connect() as c:
            bypass = c.execute(text("SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname = current_user")).scalar()
        if bypass:
            raise RuntimeError(f"{name} connects as a role that bypasses row-level security. Use vox_app / vox_system")


@app.middleware("http")
async def security_headers(request: Request, call_next):
    resp = await call_next(request)
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("Referrer-Policy", "no-referrer")
    return resp


@app.exception_handler(DataError)
async def unstorable_value(request: Request, exc: DataError):
    """The database refused a value as malformed (a NUL character in text, a number that does not fit): the request's fault, a 422, not a 500."""
    return JSONResponse({"detail": "The request holds a value that can't be stored"}, status_code=422)


@app.get("/healthz")
def healthz():
    """Liveness: the process answers. No dependencies, so a database blip never restarts the API (suite OPERATIONS §2.5)."""
    return {"ok": True}


@app.get("/readyz")
def readyz():
    """Readiness: the database answers and the schema is at the migration this build expects."""
    with system_engine.connect() as c:
        c.execute(text("SELECT 1"))
    return {"ok": True}
