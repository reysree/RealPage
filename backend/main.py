"""
File: main.py
Purpose: FastAPI application entry point with CORS and health checks.
Author: Sreeram
"""

import logging
from functools import lru_cache
from time import perf_counter

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic_settings import BaseSettings, SettingsConfigDict

from backend.agent import run_agent
from backend.schemas import AgentOutput, HealthResponse, RunRequest, RunResponse

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    """
    Runtime configuration for the backend application.
    """

    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    model_config = SettingsConfigDict(env_prefix="REALPAGE_", env_file=".env")


@lru_cache
def get_settings() -> Settings:
    """
    Load and cache runtime settings for application startup.

    Returns:
        Settings: Environment-backed backend settings.
    """

    return Settings()


def create_app() -> FastAPI:
    """
    Create the FastAPI app and configure cross-origin browser access.

    Returns:
        FastAPI: Configured API application.
    """

    settings = get_settings()
    allowed_origins = [
        origin.strip() for origin in settings.cors_origins.split(",") if origin.strip()
    ]

    app = FastAPI(title="RealPage Lumina API")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        """
        Return validation errors without echoing submitted input values.

        Args:
            request: Incoming request that failed validation.
            exc: FastAPI request validation exception.
        Returns:
            JSONResponse: Sanitized validation details.
        """

        sanitized_errors = [
            {
                "loc": error.get("loc", []),
                "msg": error.get("msg", "Invalid input"),
                "type": error.get("type", "validation_error"),
            }
            for error in exc.errors()
        ]
        return JSONResponse(status_code=422, content={"detail": sanitized_errors})

    @app.get("/health", response_model=HealthResponse)
    async def health_check() -> HealthResponse:
        """
        Report whether the backend API is available.

        Returns:
            HealthResponse: Current API health state.
        """

        return HealthResponse(status="ok")

    @app.post("/run", response_model=RunResponse)
    async def run_case(request: RunRequest) -> RunResponse:
        """
        Run one outreach case through the agent and return generated output.

        Args:
            request: Validated outreach run request.
        Returns:
            RunResponse: Generated agent output and runtime metadata.
        """

        started_at = perf_counter()
        try:
            output = AgentOutput.model_validate(run_agent(request.model_dump()))
        except Exception as exc:
            logger.error("Agent run failed: %s", exc, exc_info=True)
            raise HTTPException(status_code=500, detail="Agent run failed") from exc

        latency_ms = int((perf_counter() - started_at) * 1000)
        return RunResponse(output=output, latency_ms=latency_ms)

    return app


app = create_app()
