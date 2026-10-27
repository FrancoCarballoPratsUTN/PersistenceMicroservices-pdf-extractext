from __future__ import annotations

from typing import Any

from pydantic import BaseModel
from pydantic import ValidationError as PydanticValidationError

from app.errors import ValidationError


def checked[ModelT: BaseModel](model: type[ModelT], raw: Any) -> ModelT:
    try:
        return model.model_validate(raw)
    except PydanticValidationError as error:
        raise ValidationError(_detail(error)) from error


def _detail(error: PydanticValidationError) -> str:
    location = error.errors()[0]["loc"]
    return f"invalid {location[0]}" if location else "invalid body"


def require_str(value: Any) -> str:
    if not isinstance(value, str) or not value:
        raise ValidationError("invalid string")
    return value
