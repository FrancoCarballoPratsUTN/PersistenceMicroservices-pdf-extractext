from collections.abc import Mapping

from starlette.requests import Request
from starlette.responses import JSONResponse

from app.errors import ServiceError

PROBLEM_MEDIA_TYPE = "application/problem+json"
REDACTED = "<redacted>"


def instance_of(request: Request) -> str:
    parameters = "&".join(f"{name}={REDACTED}" for name in request.query_params)
    return f"{request.url.path}?{parameters}" if parameters else request.url.path


def build_problem(
    *,
    status: int,
    type_uri: str,
    title: str,
    detail: str,
    instance: str,
    code: str,
) -> dict[str, str | int]:
    return {
        "type": type_uri,
        "title": title,
        "status": status,
        "detail": detail,
        "instance": instance,
        "code": code,
    }


def problem_from_error(error: ServiceError, instance: str) -> dict[str, str | int]:
    return build_problem(
        status=error.status,
        type_uri=error.type_uri,
        title=error.title,
        detail=error.detail,
        instance=instance,
        code=error.code,
    )


def problem_response(
    error: ServiceError, instance: str, headers: Mapping[str, str] | None = None
) -> JSONResponse:
    return JSONResponse(
        status_code=error.status,
        content=problem_from_error(error, instance),
        media_type=PROBLEM_MEDIA_TYPE,
        headers=headers,
    )
