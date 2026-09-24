import asyncio
import time
from contextlib import asynccontextmanager, suppress
from collections import defaultdict, deque
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from app.config import get_settings
from app.routes import admin, auth, candidate, operations, public
from app.security import csrf_is_valid
from app.services.interview_reminders import reminder_loop
from app.services.supabase import SupabaseClient

settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI):
    reminder_task = asyncio.create_task(reminder_loop(settings))
    try:
        yield
    finally:
        reminder_task.cancel()
        with suppress(asyncio.CancelledError):
            await reminder_task
        await SupabaseClient.close_shared_http()


app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    docs_url="/api/docs" if settings.app_env != "production" else None,
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Requested-With", "X-CSRF-Token"],
)

request_log: dict[str, deque[float]] = defaultdict(deque)


@app.middleware("http")
async def security_and_rate_limit(request: Request, call_next):
    if request.method in {"POST", "PUT", "PATCH", "DELETE"} and request.cookies.get(settings.csrf_cookie_name):
        if not csrf_is_valid(request, settings):
            return JSONResponse(status_code=403, content={"detail": "CSRF validation failed"})
    ip = request.client.host if request.client else "unknown"
    bucket = f"{ip}:{request.url.path}"
    now = time.time()
    events = request_log[bucket]
    while events and events[0] < now - 60:
        events.popleft()
    limit = 10 if any(part in request.url.path for part in ("/auth/", "/applications")) else 120
    if len(events) >= limit:
        return JSONResponse(status_code=429, content={"detail": "Too many requests. Please try again shortly."})
    events.append(now)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    if settings.cookie_secure:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


@app.get("/health")
async def health():
    return {"status": "healthy", "service": settings.app_name, "environment": settings.app_env}


app.include_router(public.router, prefix=settings.api_prefix)
app.include_router(auth.router, prefix=settings.api_prefix)
app.include_router(admin.router, prefix=settings.api_prefix)
app.include_router(candidate.router, prefix=settings.api_prefix)
app.include_router(operations.router, prefix=settings.api_prefix)
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host="127.0.0.1",
        port=8000,
        reload=True,
    )
