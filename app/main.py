from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, RedirectResponse

from .config import get_settings
from .errors import ProspectDiscoveryError
from .logging_config import configure_logging
from .platforms.registry import get_adapters
from .schemas import DiscoveryRequest, DiscoveryResponse, ValidationResponse
from .services.prospect_service import ProspectService

logger = logging.getLogger(__name__)
_service: ProspectService | None = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    global _service
    settings = get_settings()
    configure_logging(settings)
    _service = ProspectService(settings)
    logger.info("%s started", settings.app_name)
    try:
        yield
    finally:
        if _service is not None:
            await _service.aclose()
        _service = None


app = FastAPI(
    title="AI-Powered Multi-Platform Prospect Discovery API",
    version="1.0.0",
    description="Discover and consolidate public prospect profiles from a natural-language query.",
    lifespan=lifespan,
)


@app.middleware("http")
async def request_id_middleware(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response


async def get_prospect_service() -> ProspectService:
    if _service is None:
        raise ProspectDiscoveryError("Service is not ready.")
    return _service


@app.exception_handler(ProspectDiscoveryError)
async def discovery_error_handler(request: Request, exc: ProspectDiscoveryError) -> JSONResponse:
    logger.info("Discovery error %s", exc.code)
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "success": False,
            "error": {"code": exc.code, "message": exc.client_message},
        },
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    errors = [
        {
            "field": ".".join(str(part) for part in error.get("loc", [])[1:]),
            "message": error.get("msg", "invalid"),
        }
        for error in exc.errors()
    ]
    return JSONResponse(
        status_code=422,
        content={
            "success": False,
            "error": {
                "code": "INVALID_REQUEST",
                "message": "Request validation failed.",
                "details": errors,
            },
        },
    )


@app.exception_handler(Exception)
async def unexpected_error_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled error")
    return JSONResponse(
        status_code=500,
        content={
            "success": False,
            "error": {"code": "INTERNAL_ERROR", "message": "An unexpected error occurred."},
        },
    )


@app.get("/", include_in_schema=False)
async def root() -> RedirectResponse:
    return RedirectResponse(url="/docs")


@app.get("/health", tags=["health"])
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/platforms", tags=["health"])
async def platforms() -> dict[str, object]:
    """Readiness report. It never exposes secret values."""
    settings = get_settings()
    return {
        "llm_provider": settings.llm_provider,
        "llm_model": settings.llm_model,
        "llm_configured": settings.active_llm_key() is not None,
        "tavily_configured": settings.tavily_api_key is not None,
        "platforms": [adapter.name for adapter in get_adapters()],
    }


@app.post("/validate", response_model=ValidationResponse, tags=["validation"])
async def validate_query(
    payload: DiscoveryRequest,
    service: ProspectService = Depends(get_prospect_service),
) -> ValidationResponse:
    """Parse intent and show planned queries without searching the web."""
    intent = await service.query.understand(payload.query)
    return ValidationResponse(
        query=payload.query,
        intent=intent,
        queries=service.extractor.build_queries(intent),
    )


@app.post(
    "/prospect-discovery",
    response_model=DiscoveryResponse,
    tags=["prospect-discovery"],
    summary="Discover public prospect profiles from a natural-language query",
)
async def prospect_discovery(
    payload: DiscoveryRequest,
    service: ProspectService = Depends(get_prospect_service),
) -> DiscoveryResponse:
    return await service.discover(payload.query)
