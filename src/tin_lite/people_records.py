"""People records: one lasting record per person a project knows (#435).

A record is recognized by its identifiers (a LinkedIn member ID or profile slug), holds typed
field values that each say who set them, when and why, and keeps an append-only timeline.
Only Tin's own services write here. When one read supplies identifiers of two records, they
merge: the older record survives, the newer points at it, and events stay where they were
written. Forgetting a person deletes the record and keeps a hash of each identifier, so no
later read adds them back.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.parse import quote, unquote, urlsplit
from uuid import UUID, uuid4

PERSON = "person"
IDENTIFIER_KINDS = ("linkedin_member", "linkedin_slug")
EVENT_KINDS = ("reacted", "commented", "invited", "accepted", "withdrawn")
RELATIONSHIPS = ("connected", "pending", "none")
# Built-in fields: key → (type, label, choices).
FIELDS: dict[str, tuple[str, str, tuple[str, ...] | None]] = {
    "name": ("text", "Name", None),
    "headline": ("text", "Headline", None),
    "linkedin_relationship": ("choice", "On LinkedIn", RELATIONSHIPS),
    "icp": ("text", "ICP", None),
    "icp_fit": ("number", "ICP fit", None),
}
SET_BY = ("run", "member")
TEXT_LIMIT = 2000
REASON_LIMIT = 500
# LinkedIn's own profile ID, as in /in/ACoAA… and urn:li:fsd_profile:ACoAA….
MEMBER_ID = re.compile(r"ACo[A-Za-z0-9_-]{20,80}")


class RecordError(ValueError):
    """A write Tin refuses: an unknown field, a value of the wrong type, a bad identifier."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class Value:
    field: str
    value: str | float | None
    reason: str = ""


def linkedin_identifiers(value: str) -> dict[str, str]:
    """The identifiers in a LinkedIn profile URL or profile URN.

    /in/ACo… and urn:li:fsd_profile:ACo… name the member; any other /in/<slug> is the profile's
    public slug, which LinkedIn matches without regard to case.
    """

    value = (value or "").strip()
    if value.startswith(("urn:li:fsd_profile:", "urn:li:fs_miniProfile:")):
        member = value.rsplit(":", 1)[1]
        if MEMBER_ID.fullmatch(member):
            return {"linkedin_member": member}
        raise RecordError("invalid_identifier")
    parsed = urlsplit(value)
    match = re.fullmatch(r"/in/([^/]+)/?", parsed.path)
    if (
        parsed.scheme != "https"
        or parsed.hostname not in {"www.linkedin.com", "linkedin.com"}
        or parsed.port is not None
        or parsed.username
        or not match
    ):
        raise RecordError("invalid_identifier")
    identifier = unquote(match[1])
    if MEMBER_ID.fullmatch(identifier):
        return {"linkedin_member": identifier}
    if (
        not identifier
        or len(identifier) > 300
        or any(c in identifier for c in "/\\?#")
        or any(ord(c) < 32 for c in identifier)
    ):
        raise RecordError("invalid_identifier")
    return {"linkedin_slug": identifier.casefold()}


def profile_link(identifiers: dict[str, str]) -> str:
    """The person's LinkedIn profile URL: the public slug when Tin knows it."""

    value = identifiers.get("linkedin_slug") or identifiers.get("linkedin_member")
    return "https://www.linkedin.com/in/" + quote(value, safe="-._~") if value else ""


def suppression_hash(project_id: UUID, kind: str, value: str) -> str:
    return hashlib.sha256(f"{project_id}:{kind}:{value}".encode()).hexdigest()


def _pairs(identifiers: dict[str, str]) -> list[tuple[str, str]]:
    pairs = []
    for kind, value in identifiers.items():
        if kind not in IDENTIFIER_KINDS or not isinstance(value, str):
            raise RecordError("invalid_identifier")
        value = value.strip()
        if kind == "linkedin_slug":
            value = value.casefold()
        if not value or len(value) > 300:
            raise RecordError("invalid_identifier")
        pairs.append((kind, value))
    if not pairs:
        raise RecordError("invalid_identifier")
    return pairs


async def _lock(conn, project_id: UUID) -> None:
    # Recognizing a person reads, then writes identifiers: one writer per project at a time.
    await conn.execute(
        "SELECT pg_advisory_xact_lock(hashtextextended($1, 0))", f"records:{project_id}"
    )


async def ensure_fields(conn, project_id: UUID) -> None:
    await conn.executemany(
        """INSERT INTO record_fields (project_id, key, type, label, options, built_in)
           VALUES ($1, $2, $3, $4, $5::jsonb, true)
           ON CONFLICT (project_id, key) DO NOTHING""",
        [
            (project_id, key, kind, label, json.dumps(list(choices)) if choices else None)
            for key, (kind, label, choices) in FIELDS.items()
        ],
    )


async def current(conn, project_id: UUID, record_id: UUID) -> UUID | None:
    """The record a possibly merged record now lives in, or None once it is gone."""

    row = await conn.fetchrow(
        "SELECT id, merged_into FROM records WHERE project_id = $1 AND id = $2",
        project_id,
        record_id,
    )
    if row is None:
        return None
    return row["merged_into"] or row["id"]


async def upsert_person(
    conn,
    project_id: UUID,
    identifiers: dict[str, str],
    *,
    source: str,
    run_id: UUID | None = None,
) -> UUID | None:
    """The person's record, created when no identifier matches; None for a forgotten person."""

    pairs = _pairs(identifiers)
    kinds, values = [k for k, _ in pairs], [v for _, v in pairs]
    async with conn.transaction():
        await _lock(conn, project_id)
        if await conn.fetchval(
            """SELECT EXISTS (SELECT 1 FROM record_suppressions
               WHERE project_id = $1 AND identifier_hash = ANY($2::text[]))""",
            project_id,
            [suppression_hash(project_id, k, v) for k, v in pairs],
        ):
            return None
        rows = await conn.fetch(
            """SELECT DISTINCT r.id, r.created_at FROM record_identifiers i
               JOIN records r ON r.id = i.record_id
               WHERE i.project_id = $1
                 AND (i.kind, i.value) IN (SELECT * FROM unnest($2::text[], $3::text[]))
               ORDER BY r.created_at, r.id""",
            project_id,
            kinds,
            values,
        )
        if rows:
            record_id = rows[0]["id"]
            if len(rows) > 1:
                await _merge(conn, record_id, [row["id"] for row in rows[1:]])
            await conn.execute("UPDATE records SET updated_at = now() WHERE id = $1", record_id)
        else:
            record_id = uuid4()
            await conn.execute(
                """INSERT INTO records (id, project_id, type, source, source_run_id)
                   VALUES ($1, $2, $3, $4, $5)""",
                record_id,
                project_id,
                PERSON,
                source[:100],
                run_id,
            )
        await conn.execute(
            """INSERT INTO record_identifiers (project_id, kind, value, record_id)
               SELECT $1, kind, value, $4 FROM unnest($2::text[], $3::text[]) AS t(kind, value)
               ON CONFLICT (project_id, kind, value) DO NOTHING""",
            project_id,
            kinds,
            values,
            record_id,
        )
        return record_id


async def _merge(conn, survivor: UUID, others: list[UUID]) -> None:
    await conn.execute(
        """UPDATE records SET merged_into = $2, updated_at = now()
           WHERE id = ANY($1::uuid[]) OR merged_into = ANY($1::uuid[])""",
        others,
        survivor,
    )
    await conn.execute(
        "UPDATE record_identifiers SET record_id = $2 WHERE record_id = ANY($1::uuid[])",
        others,
        survivor,
    )
    # The survivor keeps its own values. A field only the others had moves over: a member's
    # value first, then the newest.
    await conn.execute(
        """WITH moving AS (
               SELECT DISTINCT ON (field) record_id, field FROM record_values
               WHERE record_id = ANY($1::uuid[])
                 AND field NOT IN (SELECT field FROM record_values WHERE record_id = $2)
               ORDER BY field, set_by_kind = 'member' DESC, set_at DESC)
           UPDATE record_values v SET record_id = $2 FROM moving m
           WHERE v.record_id = m.record_id AND v.field = m.field""",
        others,
        survivor,
    )
    await conn.execute("DELETE FROM record_values WHERE record_id = ANY($1::uuid[])", others)


def _typed(spec: tuple[str, tuple[str, ...] | None], value) -> tuple[str | None, float | None]:
    kind, choices = spec
    if value is None:
        return None, None
    if kind == "number":
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise RecordError("invalid_value")
        if not math.isfinite(value):
            raise RecordError("invalid_value")
        return None, float(value)
    if not isinstance(value, str):
        raise RecordError("invalid_value")
    text = " ".join(value.split())[:TEXT_LIMIT]
    if kind == "choice" and text not in (choices or ()):
        raise RecordError("invalid_value")
    return text or None, None


async def set_values(
    conn,
    project_id: UUID,
    record_id: UUID,
    values: list[Value],
    *,
    set_by_kind: str,
    set_by: str,
    definition: str = "",
) -> int:
    """Write current values with their lineage; returns how many changed.

    A value a member set is never replaced by a run, and a write that changes nothing (same
    value, reason and definition) leaves the earlier one, with its time, in place.
    """

    if set_by_kind not in SET_BY or not set_by:
        raise RecordError("invalid_author")
    rows = await conn.fetch(
        "SELECT key, type, options FROM record_fields WHERE project_id = $1", project_id
    )
    fields = {
        row["key"]: (row["type"], tuple(json.loads(row["options"])) if row["options"] else None)
        for row in rows
    }
    target = await current(conn, project_id, record_id)
    if target is None:
        raise RecordError("record_gone")
    changed = 0
    for item in values:
        if item.field not in fields:
            raise RecordError("unknown_field")
        text, number = _typed(fields[item.field], item.value)
        written = await conn.fetchval(
            """INSERT INTO record_values (project_id, record_id, field, value_text, value_number,
                   reason, set_by_kind, set_by, definition)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
               ON CONFLICT (record_id, field) DO UPDATE SET
                   value_text = EXCLUDED.value_text, value_number = EXCLUDED.value_number,
                   reason = EXCLUDED.reason, set_by_kind = EXCLUDED.set_by_kind,
                   set_by = EXCLUDED.set_by, definition = EXCLUDED.definition, set_at = now()
               WHERE NOT (record_values.set_by_kind = 'member' AND EXCLUDED.set_by_kind = 'run')
                 AND (record_values.value_text, record_values.value_number, record_values.reason,
                      record_values.definition)
                     IS DISTINCT FROM (EXCLUDED.value_text, EXCLUDED.value_number,
                      EXCLUDED.reason, EXCLUDED.definition)
               RETURNING true""",
            project_id,
            target,
            item.field,
            text,
            number,
            " ".join((item.reason or "").split())[:REASON_LIMIT],
            set_by_kind,
            set_by[:200],
            definition[:200],
        )
        changed += bool(written)
    return changed


async def add_event(
    conn,
    project_id: UUID,
    record_id: UUID,
    *,
    kind: str,
    event_key: str,
    occurred_at: datetime | None = None,
    detail: dict[str, Any] | None = None,
    run_id: UUID | None = None,
) -> bool:
    """Add one timeline entry; a key already recorded adds nothing and returns False."""

    if kind not in EVENT_KINDS:
        raise RecordError("unknown_event")
    if not event_key or len(event_key) > 300:
        raise RecordError("invalid_event_key")
    target = await current(conn, project_id, record_id)
    if target is None:
        raise RecordError("record_gone")
    inserted = await conn.fetchval(
        """INSERT INTO record_events (id, project_id, record_id, kind, event_key, occurred_at,
               detail, run_id)
           VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, $8)
           ON CONFLICT (project_id, event_key) DO NOTHING
           RETURNING true""",
        uuid4(),
        project_id,
        target,
        kind,
        event_key,
        occurred_at,
        json.dumps(detail or {}),
        run_id,
    )
    return bool(inserted)


async def forget(conn, project_id: UUID, record_id: UUID) -> bool:
    """Delete a person and everything merged into them, and keep their identifiers' hashes."""

    async with conn.transaction():
        await _lock(conn, project_id)
        target = await current(conn, project_id, record_id)
        if target is None:
            return False
        ids = [
            row["id"]
            for row in await conn.fetch(
                "SELECT id FROM records WHERE project_id = $1 AND (id = $2 OR merged_into = $2)",
                project_id,
                target,
            )
        ]
        identifiers = await conn.fetch(
            "SELECT kind, value FROM record_identifiers WHERE record_id = ANY($1::uuid[])", ids
        )
        await conn.executemany(
            """INSERT INTO record_suppressions (project_id, identifier_hash) VALUES ($1, $2)
               ON CONFLICT DO NOTHING""",
            [
                (project_id, suppression_hash(project_id, row["kind"], row["value"]))
                for row in identifiers
            ],
        )
        await conn.execute("DELETE FROM record_events WHERE record_id = ANY($1::uuid[])", ids)
        await conn.execute("DELETE FROM record_values WHERE record_id = ANY($1::uuid[])", ids)
        await conn.execute("DELETE FROM record_identifiers WHERE record_id = ANY($1::uuid[])", ids)
        await conn.execute("DELETE FROM records WHERE id = ANY($1::uuid[])", ids)
        return True


async def people(conn, project_id: UUID, *, limit: int = 5000) -> list[dict[str, Any]]:
    """Current people with identifiers, values and event counts, newest first."""

    rows = await conn.fetch(
        """SELECT r.id, r.created_at, r.updated_at,
               (SELECT jsonb_object_agg(i.kind, i.value) FROM record_identifiers i
                WHERE i.record_id = r.id) AS identifiers,
               (SELECT jsonb_object_agg(v.field, jsonb_build_object(
                    'text', v.value_text, 'number', v.value_number, 'reason', v.reason,
                    'definition', v.definition, 'set_by_kind', v.set_by_kind))
                FROM record_values v WHERE v.record_id = r.id) AS fields,
               (SELECT jsonb_object_agg(kind, n) FROM (
                    SELECT e.kind, count(*) AS n FROM record_events e
                    WHERE e.record_id = r.id
                       OR e.record_id IN (SELECT m.id FROM records m WHERE m.merged_into = r.id)
                    GROUP BY e.kind) counted) AS events
           FROM records r
           WHERE r.project_id = $1 AND r.type = $2 AND r.merged_into IS NULL
           ORDER BY r.created_at DESC, r.id
           LIMIT $3""",
        project_id,
        PERSON,
        limit,
    )
    result = []
    for row in rows:
        identifiers = json.loads(row["identifiers"]) if row["identifiers"] else {}
        fields = json.loads(row["fields"]) if row["fields"] else {}
        result.append(
            {
                "id": row["id"],
                "identifiers": identifiers,
                "profile_url": profile_link(identifiers),
                "fields": fields,
                "events": json.loads(row["events"]) if row["events"] else {},
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
        )
    return result
