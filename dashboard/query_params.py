"""Shared parsing for list filter query parameters."""

from rest_framework.exceptions import ValidationError


# Primary keys are BigAutoField (PostgreSQL bigint); larger values would
# overflow in the database and fail with a 500 instead of a 400.
MAX_FILTER_ID = 9223372036854775807


def parse_id_param(params, name, message):
    """Return the positive integer ID in `params[name]`, or None when absent/empty.

    Malformed, non-positive and out-of-range values raise ValidationError({name: message}).
    """
    value = params.get(name)
    if value in (None, ""):
        return None
    try:
        object_id = int(value)
    except (TypeError, ValueError):
        raise ValidationError({name: message})
    if not 1 <= object_id <= MAX_FILTER_ID:
        raise ValidationError({name: message})
    return object_id
