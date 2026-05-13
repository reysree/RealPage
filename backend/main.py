"""
File: main.py
Purpose: FastAPI application entry point with CORS and health checks.
Author: Sreeram
"""

from functools import lru_cache

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Runtime configuration for the backend application.
    """

    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    model_config = SettingsConfigDict(env_prefix="REALPAGE_", env_file=".env")


class HealthResponse(BaseModel):
    """
    Response model for the backend health check.
    """

    status: str
    service: str


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

    @app.get("/health", response_model=HealthResponse)
    def health_check() -> HealthResponse:
        """
        Report whether the backend API is available.

        Returns:
            HealthResponse: Current API health state.
        """

        return HealthResponse(status="ok", service="realpage-backend")

    return app


app = create_app()
