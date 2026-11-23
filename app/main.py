from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, RedirectResponse

from .config import get_settings
from .errors import ProspectDiscoveryError
from .logging_config import configure_logging
from .schemas import DiscoveryRequest, DiscoveryResponse
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
