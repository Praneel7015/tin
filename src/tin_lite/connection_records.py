"""Shared helpers for first-party read connections that return projected records.

Stripe and PostHog use these. A provider module owns its HTTP client and projections. This
module owns what every such adapter must do the same way: open the stored credential, read a
bounded response body, fit the leading projected records to the binding's byte bound with a
resumable cursor, and write the provider receipt.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

import httpx

from tin_lite.integrations import (
    IntegrationAuthorizationError,
    IntegrationNotConfiguredError,
    IntegrationUpstreamError,
    ServiceCallRefused,
    ServiceResponseTooLarge,
)

METADATA_MAX_KEYS = 20
METADATA_MAX_VALUE = 200


class ServiceArgumentError(ValueError):
    """An operation argument is outside its closed contract; the message is Tin's own."""


def json_size(value: Any) -> int:
    """Bytes as the service gateway measures a response: compact-ish json.dumps defaults."""
    return len(json.dumps(value, ensure_ascii=False, allow_nan=False).encode())


def credential_context(connection: Any) -> str:
    return f"credential:{connection.project_id}:{connection.provider_key}"


def open_credential(integrations: Any, connection: Any) -> str:
    """Decrypt a connection's stored credential; fail closed without key or ciphertext."""
    cipher = integrations._cipher
    if cipher is None:
        raise IntegrationNotConfiguredError("integration credential key is not configured")
    if connection.credential_ciphertext is None:
        raise IntegrationAuthorizationError("The connection has no stored credential.")
    return cipher.decrypt(connection.credential_ciphertext, context=credential_context(connection))


def seal_credential(integrations: Any, *, project_id: UUID, provider_key: str, value: str):
    cipher = integrations._cipher
    if cipher is None:
        raise IntegrationNotConfiguredError("integration credential key is not configured")
    return (
        cipher.encrypt(value, context=f"credential:{project_id}:{provider_key}"),
        cipher.version,
    )


async def read_bounded_json(response: httpx.Response, *, maximum: int, provider: str) -> Any:
    """Read a streamed body up to `maximum` bytes and parse it; never decompress unbounded.

    Requests send `Accept-Encoding: identity`; an encoded body is refused before allocation.
    """
    if response.headers.get("content-encoding", "identity") != "identity":
        raise IntegrationUpstreamError(f"{provider} returned a compressed response")
    raw = bytearray()
    async for chunk in response.aiter_raw():
        raw.extend(chunk)
        if len(raw) > maximum:
            raise ServiceCallRefused(
                f"{provider} returned more data than Tin reads in one call; "
                "request a smaller limit.",
                code="upstream_too_large",
            )
    try:
        return json.loads(raw)
    except (ValueError, UnicodeError, RecursionError):
        raise IntegrationUpstreamError(f"{provider} returned an invalid response") from None


def fit_records(
    records: list[dict[str, Any]],
    *,
    max_response_bytes: int | None,
    has_more: bool,
    envelope: dict[str, Any] | None = None,
    cursor_field: str = "id",
    offset: int | None = None,
) -> dict[str, Any]:
    """Keep the leading records that fit the bound and say where the next page starts.

    Returns `{**envelope, records, has_more, truncated, next_cursor}`: `truncated` is true when
    Tin left records out to fit the bound; `has_more` is true when more records follow the last
    one returned (left out here or not yet read upstream); `next_cursor` is then the last
    returned record's cursor, to pass back as `cursor`. With `offset` (position-paged APIs)
    the cursor is instead the position after the last returned record, as a string. Only a
    single record too large for the bound on its own raises `ServiceResponseTooLarge`.
    """
    base = dict(envelope or {})
    page = {"cursor_field": cursor_field, "offset": offset}
    if max_response_bytes is None:
        return _page(base, records, has_more=has_more, truncated=False, **page)
    whole = _page(base, records, has_more=has_more, truncated=False, **page)
    if json_size(whole) <= max_response_bytes:
        return whole
    # Budget the widest envelope this page can carry, then add records in order.
    widest = (
        len(json.dumps(str(offset + len(records))))
        if offset is not None
        else max((len(json.dumps(str(r.get(cursor_field)))) for r in records), default=2)
    )
    skeleton = {
        **base,
        "records": [],
        "has_more": True,
        "truncated": True,
        "next_cursor": "x" * widest,
    }
    used = json_size(skeleton)
    kept = 0
    for index, record in enumerate(records):
        used += json_size(record) + (2 if index else 0)  # ", " between records
        if used > max_response_bytes:
            break
        kept += 1
    if records and not kept:
        raise ServiceResponseTooLarge("A single record exceeds the response bound.")
    return _page(
        base,
        records[:kept],
        has_more=has_more or kept < len(records),
        truncated=kept < len(records),
        **page,
    )


def _page(base, records, *, has_more, truncated, cursor_field, offset=None):
    if not has_more:
        cursor = None
    elif offset is not None:
        cursor = str(offset + len(records))
    else:
        cursor = records[-1].get(cursor_field) if records else None
    return {
        **base,
        "records": records,
        "has_more": has_more,
        "truncated": truncated,
        "next_cursor": cursor,
    }


def text(value: Any, limit: int = 200) -> str | None:
    """A provider string cut to `limit` characters; anything else becomes None."""
    if not isinstance(value, str):
        return None
    return value.replace("\x00", "")[:limit]


def integer(value: Any) -> int | None:
    return value if type(value) is int else None


def boolean(value: Any) -> bool | None:
    return value if type(value) is bool else None


def bounded_metadata(value: Any) -> dict[str, str]:
    """At most twenty string entries, keys sorted, values cut to two hundred characters."""
    if not isinstance(value, dict):
        return {}
    items = sorted((k, v) for k, v in value.items() if isinstance(k, str) and isinstance(v, str))
    return {k[:40]: v[:METADATA_MAX_VALUE] for k, v in items[:METADATA_MAX_KEYS]}


def email_domain(email: Any) -> str | None:
    if not isinstance(email, str) or email.count("@") != 1:
        return None
    domain = email.rsplit("@", 1)[1].strip().lower()
    return domain[:253] if "." in domain and " " not in domain else None


async def record_call(
    database: Any,
    *,
    connection: Any,
    capability: str,
    fingerprint: str,
    execution_key: str,
    run_id: UUID | None,
    status: str,
    response_summary: dict[str, Any] | None = None,
    provider_request_id: str | None = None,
    error_code: str | None = None,
) -> None:
    await database.record_integration_call(
        execution_key=execution_key,
        project_id=connection.project_id,
        run_id=run_id,
        connection_id=connection.id,
        provider_key=connection.provider_key,
        capability=capability,
        request_fingerprint=fingerprint,
        status=status,
        response_summary=response_summary,
        provider_request_id=(provider_request_id or "")[:200] or None,
        error_code=error_code,
    )
