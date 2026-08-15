from __future__ import annotations

from typing import TypeGuard, cast

from .errors import MitraResponseError
from .models import CurrentUser, FunctionExecution, ProxyResult, QueryResult


def expect_object(payload: object | None, context: str) -> dict[str, object]:
    if not _is_object(payload):
        raise MitraResponseError(f"{context} must be a JSON object")
    return payload


def expect_object_list(payload: object | None, context: str) -> list[dict[str, object]]:
    if not isinstance(payload, list) or not all(_is_object(item) for item in payload):
        raise MitraResponseError(f"{context} must be a JSON array of objects")
    return cast(list[dict[str, object]], payload)


def expect_current_user(payload: object | None, context: str) -> CurrentUser:
    user = expect_object(payload, context)

    _expect_string(user, "id", context)
    tenant = _expect_object(user, "tenant", context)
    _expect_string(tenant, "id", f"{context} tenant")
    _expect_string(tenant, "shortId", f"{context} tenant")
    _expect_nullable_integer(tenant, "legacyId", f"{context} tenant")
    _expect_string(tenant, "slug", f"{context} tenant")
    plan = _expect_object(tenant, "plan", f"{context} tenant")
    _expect_string(plan, "id", f"{context} tenant plan")
    _expect_string(plan, "name", f"{context} tenant plan")
    _expect_string(tenant, "name", f"{context} tenant")
    _expect_nullable_string(tenant, "description", f"{context} tenant")
    _expect_nullable_string(tenant, "hexColor", f"{context} tenant")
    _expect_nullable_string(tenant, "icon", f"{context} tenant")
    _expect_string(tenant, "infraStatus", f"{context} tenant")
    _expect_boolean(tenant, "active", f"{context} tenant")
    _expect_string(user, "name", context)
    _expect_string(user, "email", context)
    _expect_nullable_string(user, "imageUrl", context)
    _expect_boolean(user, "onboardingCompleted", context)

    return cast(CurrentUser, user)


def expect_query_result(payload: object | None, context: str) -> QueryResult:
    result = expect_object(payload, context)

    expect_object_list(_required_field(result, "rows", context), f"{context} rows")
    if "affectedRows" in result:
        _expect_nullable_integer(result, "affectedRows", context)
    _expect_integer(result, "durationMs", context)

    return cast(QueryResult, result)


def expect_function_execution(payload: object | None, context: str) -> FunctionExecution:
    execution = expect_object(payload, context)

    for field in ("id", "functionId", "functionVersionId", "status"):
        _expect_string(execution, field, context)
    _expect_nullable_object(execution, "input", context)
    _expect_nullable_object(execution, "output", context)
    for field in ("errorMessage", "logs", "startedAt", "finishedAt"):
        _expect_nullable_string(execution, field, context)
    _expect_nullable_integer(execution, "durationMs", context)
    _expect_string(execution, "createdAt", context)

    return cast(FunctionExecution, execution)


def expect_proxy_result(payload: object | None, context: str) -> ProxyResult:
    result = expect_object(payload, context)

    _expect_integer(result, "status", context)
    headers = _required_field(result, "headers", context)
    if not _is_object(headers) or not all(isinstance(value, str) for value in headers.values()):
        _invalid_field(context, "headers")
    _required_field(result, "body", context)
    _expect_integer(result, "durationMs", context)
    _expect_string(result, "executionId", context)

    return cast(ProxyResult, result)


def _is_object(value: object) -> TypeGuard[dict[str, object]]:
    return isinstance(value, dict) and all(isinstance(key, str) for key in value)


def _is_integer(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _required_field(value: dict[str, object], field: str, context: str) -> object:
    if field not in value:
        _invalid_field(context, field)
    return value[field]


def _expect_string(value: dict[str, object], field: str, context: str) -> None:
    if not isinstance(_required_field(value, field, context), str):
        _invalid_field(context, field)


def _expect_nullable_string(value: dict[str, object], field: str, context: str) -> None:
    field_value = _required_field(value, field, context)
    if field_value is not None and not isinstance(field_value, str):
        _invalid_field(context, field)


def _expect_integer(value: dict[str, object], field: str, context: str) -> None:
    if not _is_integer(_required_field(value, field, context)):
        _invalid_field(context, field)


def _expect_nullable_integer(value: dict[str, object], field: str, context: str) -> None:
    field_value = _required_field(value, field, context)
    if field_value is not None and not _is_integer(field_value):
        _invalid_field(context, field)


def _expect_boolean(value: dict[str, object], field: str, context: str) -> None:
    if not isinstance(_required_field(value, field, context), bool):
        _invalid_field(context, field)


def _expect_object(
    value: dict[str, object],
    field: str,
    context: str,
) -> dict[str, object]:
    field_value = _required_field(value, field, context)
    if not _is_object(field_value):
        _invalid_field(context, field)
    return cast(dict[str, object], field_value)


def _expect_nullable_object(value: dict[str, object], field: str, context: str) -> None:
    field_value = _required_field(value, field, context)
    if field_value is not None and not _is_object(field_value):
        _invalid_field(context, field)


def _invalid_field(context: str, field: str) -> None:
    raise MitraResponseError(f"{context} has an invalid {field} field")
