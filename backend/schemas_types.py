"""
File: schemas_types.py
Purpose: Wire validators and annotated primitive types shared across outreach schema modules.
Author: Sreeram
"""

from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BeforeValidator, StringConstraints

# Pipeline states required in every eval case assertion record.
REQUIRED_ASSERTION_STATES: tuple[str, ...] = (
    "consent_verified",
    "fair_housing_check_passed",
    "brand_style_applied",
)

PersonaKind = Literal["prospect"]
LifecycleKind = Literal["new", "open"]
Channel = Literal["sms", "email", "voice"]
LanguageCode = Literal["en"]

ShortText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=80),
]
MediumText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=160),
]
LongText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=2000),
]
ComposerReasonText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=500),
]


def _wire_bool(value: object) -> bool:
    """
    Accept only JSON-native booleans — reject 0/1 and \"true\"/\"false\" strings.
    """

    if isinstance(value, bool):
        return value
    raise ValueError("Must be JSON true or false, not a string or number.")


def _wire_optional_bool(value: object) -> bool | None:
    """
    Accept null or JSON booleans only for optional constraint flags.
    """

    if value is None:
        return None
    return _wire_bool(value)


def _wire_int(value: object) -> int:
    """
    Accept JSON integers only — reject booleans and floats.
    """

    if isinstance(value, bool):
        raise ValueError("Integer threshold cannot be a boolean.")
    if isinstance(value, int):
        return value
    raise ValueError("Must be a JSON integer, not a float or string.")


def _wire_optional_int(value: object) -> int | None:
    """
    Accept null or JSON integers for optional integer thresholds.
    """

    if value is None:
        return None
    return _wire_int(value)


def _wire_optional_float(value: object) -> float | None:
    """
    Accept null or JSON numbers for float thresholds — not strings or booleans.
    """

    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError("Float threshold cannot be a boolean.")
    if isinstance(value, float):
        return value
    if isinstance(value, int):
        return float(value)
    raise ValueError("Must be a JSON number.")


def _wire_required_float(value: object) -> float:
    """
    Accept JSON numbers for required float thresholds — reject null, strings, booleans.
    """

    if value is None:
        raise ValueError("Required float threshold cannot be null.")
    if isinstance(value, bool):
        raise ValueError("Float threshold cannot be a boolean.")
    if isinstance(value, float):
        return value
    if isinstance(value, int):
        return float(value)
    raise ValueError("Must be a JSON number.")


def _iso_date_wire(value: object) -> date:
    """
    Parse move date from JSON string YYYY-MM-DD or an existing date object.
    """

    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        return date.fromisoformat(value)
    raise ValueError("Date must be an ISO 8601 date string (YYYY-MM-DD).")


def _iso_datetime_wire(value: object) -> datetime:
    """
    Parse last interaction from ISO 8601 JSON string or an existing datetime.
    """

    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        normalized = value.replace("Z", "+00:00") if value.endswith("Z") else value
        return datetime.fromisoformat(normalized)
    raise ValueError("Datetime must be an ISO 8601 string or datetime.")


JsonBoolean = Annotated[bool, BeforeValidator(_wire_bool)]
OptionalJsonBoolean = Annotated[bool | None, BeforeValidator(_wire_optional_bool)]
JsonInt = Annotated[int, BeforeValidator(_wire_int)]
OptionalJsonInt = Annotated[int | None, BeforeValidator(_wire_optional_int)]
OptionalJsonFloat = Annotated[float | None, BeforeValidator(_wire_optional_float)]
JsonFloat = Annotated[float, BeforeValidator(_wire_required_float)]
IsoDate = Annotated[date, BeforeValidator(_iso_date_wire)]
IsoDateTime = Annotated[datetime, BeforeValidator(_iso_datetime_wire)]
