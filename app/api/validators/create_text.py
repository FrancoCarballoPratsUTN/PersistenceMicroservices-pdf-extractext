from __future__ import annotations

from app.api.models import CreateTextBody
from app.api.validators.common import checked
from app.use_cases.ports import CreateTextCommand


def validate(raw: object) -> CreateTextCommand:
    body = checked(CreateTextBody, raw)
    return CreateTextCommand(
        checksum=body.checksum,
        text=body.text,
        name=body.name,
        metadata=body.metadata,
    )
