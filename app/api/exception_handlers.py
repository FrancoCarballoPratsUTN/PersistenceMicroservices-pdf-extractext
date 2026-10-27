import logging

from starlette.applications import Starlette
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.api.problem import (
    PROBLEM_MEDIA_TYPE,
    build_problem,
    instance_of,
    problem_response,
)
from app.errors import (
    InternalError,
    MethodNotAllowedError,
    ResourceNotFoundError,
    ServiceError,
)

logger = logging.getLogger(__name__)

_ROUTING_ERRORS: dict[int, type[ServiceError]] = {
    404: ResourceNotFoundError,
    405: MethodNotAllowedError,
}


async def service_error_handler(request: Request, exc: ServiceError) -> JSONResponse:
    return problem_response(exc, instance_of(request))


async def http_exception_handler(
    request: Request, exc: StarletteHTTPException
) -> JSONResponse:
    error_cls = _ROUTING_ERRORS.get(exc.status_code)
    if error_cls is not None:
        return problem_response(error_cls(), instance_of(request))
    return JSONResponse(
        status_code=exc.status_code,
        media_type=PROBLEM_MEDIA_TYPE,
        content=build_problem(
            status=exc.status_code,
            type_uri="/problems/http_error",
            title="HTTP error",
            detail="The request could not be completed.",
            instance=instance_of(request),
            code="HTTP_ERROR",
        ),
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.error("Unhandled error while handling %s", request.url.path, exc_info=exc)
    return problem_response(InternalError(), instance_of(request))


def register_exception_handlers(app: Starlette) -> None:
    app.add_exception_handler(ServiceError, service_error_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
