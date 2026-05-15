"""
File: main.py
Purpose: FastAPI application entry point with CORS and health checks.
Author: Sreeram
"""

from pathlib import Path
from typing import Any, Mapping

_BACKEND_ROOT = Path(__file__).resolve().parent


def _load_backend_dotenv() -> None:
    """
    Populate ``os.environ`` from ``.env`` files before tools call ``os.getenv``.

    Uvicorn is typically started from the repo root, so a bare ``env_file=".env"``
    resolves to the wrong directory. Loads ``backend/.env`` first, then repo-root
    ``.env``, without overriding variables already set in the shell.
    """

    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    repo_root = _BACKEND_ROOT.parent
    for path in (_BACKEND_ROOT / ".env", repo_root / ".env"):
        if path.is_file():
            load_dotenv(path, override=False)


_load_backend_dotenv()

import json
import logging
from functools import lru_cache
from time import perf_counter

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic_settings import BaseSettings, SettingsConfigDict

from backend.agent import run_agent
from backend.evals.runner import run_all_cases
from backend.schemas import (
    AgentOutput,
    EvalBatchRunRequest,
    EvalBatchRunResponse,
    HealthResponse,
    RunRequest,
    RunResponse,
)

logger = logging.getLogger(__name__)


def _validation_errors_for_log(errors: list[Any]) -> list[dict[str, Any]]:
    """
    Drop submitted values from validation errors before logging.

    Args:
        errors: Raw Pydantic/FastAPI validation error dicts.
    Returns:
        Same structures without ``input`` payloads (may contain PII).
    """

    cleaned: list[dict[str, Any]] = []
    for item in errors:
        if isinstance(item, Mapping):
            cleaned.append({k: v for k, v in dict(item).items() if k != "input"})
    return cleaned


def _field_display_path(loc: tuple[Any, ...] | list[Any]) -> str:
    """
    Build a dotted path for client-facing messages (omit HTTP ``body`` wrapper).

    Args:
        loc: Error location tuple from validation metadata.
    Returns:
        Dot-separated field path such as ``input.property_name``.
    """

    skip_roots = {"body", "query", "path", "header"}
    parts: list[str] = []
    for segment in loc:
        if segment in skip_roots and not parts:
            continue
        parts.append(str(segment))
    return ".".join(parts) if parts else "request"


def _humanize_validation_errors(errors: list[Any]) -> str:
    """
    Turn validation metadata into short user-facing sentences (no error codes).

    Args:
        errors: Raw validation error list from ``RequestValidationError``.
    Returns:
        Single human-readable summary suitable for API JSON responses.
    """

    messages: list[str] = []
    for item in errors:
        if not isinstance(item, Mapping):
            continue
        loc = item.get("loc") or ()
        field = _field_display_path(tuple(loc))
        typ = str(item.get("type") or "")
        if typ == "missing":
            messages.append(f"Required field missing: {field}.")
            continue
        if typ == "extra_forbidden":
            messages.append(f"Unexpected field: {field}.")
            continue
        if typ.endswith("_type") or typ in {"bool_parsing", "int_parsing", "float_parsing"}:
            messages.append(f"Invalid type for {field}.")
            continue
        if typ.startswith("value_error"):
            messages.append(f"Invalid value for {field}.")
            continue
        messages.append(f"Invalid input for {field}.")
    joined = " ".join(messages).strip()
    return joined if joined else "Invalid request."


def _http_detail_message(detail: Any) -> str:
    """
    Normalize HTTPException detail to a single string for responses.

    Args:
        detail: Starlette/FastAPI ``HTTPException.detail`` payload.
    Returns:
        Plain-language message without structured error codes.
    """

    if isinstance(detail, str):
        return detail
    return "Request could not be processed."


class Settings(BaseSettings):
    """
    Runtime configuration for the backend application.
    """

    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    model_config = SettingsConfigDict(
        env_prefix="REALPAGE_",
        env_file=_BACKEND_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


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

    app = FastAPI(title="Context-Aware Message Sending Bot API")
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
        Log structured validation failures; return only plain-language messages.

        Args:
            request: Incoming request that failed validation.
            exc: FastAPI request validation exception.
        Returns:
            JSONResponse with generic ``error`` and human ``message`` only.
        """

        logger.warning(
            "request_validation_failed path=%s errors=%s",
            request.url.path,
            _validation_errors_for_log(exc.errors()),
        )
        message = _humanize_validation_errors(exc.errors())
        return JSONResponse(
            status_code=422,
            content={
                "error": "Run failed",
                "message": message,
            },
        )

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
        """
        Normalize HTTP errors to the same minimal JSON shape as validation failures.

        Args:
            request: Incoming request (unused; signature required by FastAPI).
            exc: Raised HTTP exception.
        Returns:
            JSONResponse with ``error`` and ``message`` only.
        """

        if exc.status_code >= 500:
            logger.error(
                "http_server_error path=%s status=%s detail=%s",
                request.url.path,
                exc.status_code,
                exc.detail,
            )
            client_message = "Run failed."
        else:
            client_message = _http_detail_message(exc.detail)

        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": "Run failed",
                "message": client_message,
            },
        )

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

    @app.post("/eval/run", response_model=EvalBatchRunResponse)
    async def eval_run_batch(request: EvalBatchRunRequest) -> EvalBatchRunResponse:
        """
        Run multiple eval cases (same records as JSONL / sample.json) and return an aggregate report.
        """

        try:
            raw = run_all_cases(
                request.cases,
                latency_sample_count=request.latency_sample_count,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except Exception as exc:
            logger.error("Eval batch failed: %s", exc, exc_info=True)
            raise HTTPException(status_code=500, detail="Eval run failed") from exc

        return EvalBatchRunResponse(
            total=raw["total"],
            passed=raw["passed"],
            failed=raw["failed"],
            results=raw["results"],
            source="request_body",
        )

    @app.post("/eval/run-sample", response_model=EvalBatchRunResponse)
    async def eval_run_sample(
        latency_sample_count: int | None = Query(
            default=None,
            ge=1,
            le=64,
            description=(
                "Timed repetitions of POST /run per case for P95; omit to use REALPAGE_EVAL_LATENCY_RUNS / default."
            ),
        ),
    ) -> EvalBatchRunResponse:
        """
        Run eval cases from ``sample.json`` at the repository root (JSON array).
        """

        path = _BACKEND_ROOT.parent / "sample.json"
        if not path.is_file():
            raise HTTPException(
                status_code=404,
                detail="sample.json not found at repository root.",
            )
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise HTTPException(
                status_code=422,
                detail="sample.json is not valid JSON.",
            ) from exc
        if not isinstance(data, list):
            raise HTTPException(
                status_code=422,
                detail="sample.json must be a JSON array of case objects.",
            )
        cases: list[dict[str, Any]] = []
        for item in data:
            if not isinstance(item, dict):
                raise HTTPException(
                    status_code=422,
                    detail="sample.json array must contain only JSON objects.",
                )
            cases.append(item)

        try:
            raw = run_all_cases(cases, latency_sample_count=latency_sample_count)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except Exception as exc:
            logger.error("Eval sample run failed: %s", exc, exc_info=True)
            raise HTTPException(status_code=500, detail="Eval run failed") from exc

        return EvalBatchRunResponse(
            total=raw["total"],
            passed=raw["passed"],
            failed=raw["failed"],
            results=raw["results"],
            source="sample_json",
        )

    return app


app = create_app()
