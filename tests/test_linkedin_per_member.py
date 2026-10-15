"""Each member of a project keeps their own LinkedIn reading connection (Tin for Chrome).

A teammate pairing their browser never replaces another member's connection, session or
browser; a run reads with the LinkedIn of the member who started it; each member sees,
changes and disconnects their own.
"""

from __future__ import annotations

import base64
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import SecretStr
from test_connection_collection import USER, session_envelope
from test_connection_collection import collection_db as collection_db
from test_connection_collection_lifecycle import QUERY, prepared

from tin_lite.connection_collection import POLICY_V2, CollectionError
from tin_lite.connection_collection_connection import default_inputs
from tin_lite.connection_collection_store import token_hash
from tin_lite.integrations import IntegrationService

TEAMMATE = "user_collectionteammate"
TEAMMATE_TOKEN = "synthetic-teammate-device-token-for-tests-12345678"  # noqa: S105
TEAMMATE_ACTOR = {
    "key": "https://www.linkedin.com/in/teammate",
    "name": "Teammate",
    "profile_url": "https://www.linkedin.com/in/teammate",
}


async def add_teammate(f, *, mode="cloud_only"):
    await f.db.grant_project_membership(project_id=f.project.id, clerk_user_id=TEAMMATE)
    grant = await f.store.grant(f.project.id, TEAMMATE)
    await f.store.pair(grant["grant"], token_hash(TEAMMATE_TOKEN), TEAMMATE_ACTOR)
    await f.connection.preferences(
        f.project.id, TEAMMATE, {"actor": TEAMMATE_ACTOR, "mode": mode, "consent_version": 1}
    )
    envelope = session_envelope()
    envelope["cookies"][0]["expiration_date"] = (datetime.now(UTC) + timedelta(days=3)).timestamp()
    await f.connection.save_session(
        f.project.id,
        TEAMMATE_TOKEN,
        {
            "actor_key": TEAMMATE_ACTOR["key"],
            "session": envelope,
            "query_id": QUERY,
            "expected_generation": None,
        },
    )


async def connections(f):
    rows = await f.db.pool.fetch(
        "SELECT * FROM integration_connections WHERE project_id=$1 "
        "AND provider_key='network.linkedin'",
        f.project.id,
    )
    return {row["connected_by_clerk_user_id"]: row for row in rows}


async def run_by(f, member):
    run_id = uuid4()
    await f.db.pool.execute(
        """INSERT INTO workflow_runs
        (id,project_id,workflow_id,executor,definition_commit_sha,temporal_workflow_id,thread_id,
         generation,fencing_token,status,started_by_clerk_user_id,input)
        SELECT $2,project_id,workflow_id,executor,definition_commit_sha,$3,$3,
          1,1,'running',$4,$5::jsonb FROM workflow_runs WHERE id=$1""",
        f.run.id,
        run_id,
        "collection-" + str(run_id),
        member,
        json.dumps(
            {
                "friends": ["https://www.linkedin.com/in/friend"],
                "keywords": "",
                "execution": "cloud_preferred",
            }
        ),
    )
    await f.db.pool.execute(
        "UPDATE connection_collection_jobs SET state='completed' WHERE project_id=$1",
        f.project.id,
    )
    await f.db.pool.execute("DELETE FROM connection_collection_account_leases")
    return await f.db.get_run(run_id)


async def test_a_teammate_pairing_keeps_the_first_members_linkedin(collection_db):
    f = await prepared(collection_db)
    before = (await connections(f))[USER]
    await add_teammate(f)
    after = await connections(f)
    assert set(after) == {USER, TEAMMATE}
    mine, theirs = after[USER], after[TEAMMATE]
    # The first member's connection, saved session and browser are untouched.
    assert mine["id"] == before["id"]
    assert mine["credential_ciphertext"] == before["credential_ciphertext"]
    assert json.loads(mine["configuration"])["session_state"] == "available"
    devices = await f.db.pool.fetch(
        "SELECT clerk_user_id, revoked_at FROM connection_extension_devices "
        "WHERE project_id=$1 AND revoked_at IS NULL",
        f.project.id,
    )
    assert {d["clerk_user_id"] for d in devices} == {USER, TEAMMATE}
    assert theirs["external_account_id"] == TEAMMATE_ACTOR["key"]
    assert json.loads(theirs["configuration"])["session_state"] == "available"

    # Pairing again replaces only that member's own browser.
    grant = await f.store.grant(f.project.id, TEAMMATE)
    await f.store.pair(grant["grant"], token_hash(TEAMMATE_TOKEN + "x"), TEAMMATE_ACTOR)
    active = await f.db.pool.fetch(
        "SELECT clerk_user_id FROM connection_extension_devices "
        "WHERE project_id=$1 AND revoked_at IS NULL",
        f.project.id,
    )
    assert sorted(d["clerk_user_id"] for d in active) == sorted([USER, TEAMMATE])
    assert (await connections(f))[USER]["credential_ciphertext"] == before["credential_ciphertext"]


async def test_each_member_lists_and_sets_their_own(collection_db):
    f = await prepared(collection_db)
    await add_teammate(f)
    mine = await f.db.list_integration_connections(f.project.id, member=USER)
    theirs = await f.db.list_integration_connections(f.project.id, member=TEAMMATE)
    everyone = await f.db.list_integration_connections(f.project.id)
    linkedin = [c for c in mine if c.provider_key == "network.linkedin"]
    assert [c.connected_by_clerk_user_id for c in linkedin] == [USER]
    assert [
        c.connected_by_clerk_user_id for c in theirs if c.provider_key == "network.linkedin"
    ] == [TEAMMATE]
    assert len([c for c in everyone if c.provider_key == "network.linkedin"]) == 2
    # A member who never connected sees no LinkedIn of their own.
    assert not [
        c
        for c in await f.db.list_integration_connections(f.project.id, member="user_nobody")
        if c.provider_key == "network.linkedin"
    ]

    # Turning cloud reading off clears only the teammate's session.
    await f.connection.preferences(
        f.project.id,
        TEAMMATE,
        {"actor": TEAMMATE_ACTOR, "mode": "local_only", "consent_version": 1},
    )
    rows = await connections(f)
    assert rows[TEAMMATE]["credential_ciphertext"] is None
    assert rows[USER]["credential_ciphertext"] is not None
    # A saved choice fills each member's own new collection.
    assert (await default_inputs(f.db, f.project.id, {}, member=TEAMMATE))["execution"] == (
        "local_only"
    )
    assert (await default_inputs(f.db, f.project.id, {}, member=USER))["execution"] == (
        "cloud_preferred"
    )
    assert await default_inputs(f.db, f.project.id, {}, member="user_nobody") == {}


async def test_a_run_reads_with_the_linkedin_of_whoever_started_it(collection_db):
    f = await prepared(collection_db)
    await add_teammate(f)
    rows = await connections(f)
    job = await f.store.prepare(await run_by(f, TEAMMATE), POLICY_V2)
    assert job["connection_id"] == rows[TEAMMATE]["id"]
    assert job["actor"]["key"] == TEAMMATE_ACTOR["key"]
    job = await f.store.prepare(await run_by(f, USER), POLICY_V2)
    assert job["connection_id"] == rows[USER]["id"]
    # A member without a LinkedIn of their own is told to connect it.
    await f.db.grant_project_membership(project_id=f.project.id, clerk_user_id="user_nobody")
    with pytest.raises(CollectionError, match="account_owner_required"):
        await f.store.prepare(await run_by(f, "user_nobody"), POLICY_V2)


async def test_disconnecting_removes_only_your_own_linkedin(collection_db):
    f = await prepared(collection_db)
    await add_teammate(f)
    settings = SimpleNamespace(
        **{
            **vars(f.store.settings),
            "integration_credential_key": SecretStr(base64.urlsafe_b64encode(b"k" * 32).decode()),
        }
    )
    service = IntegrationService(database=f.db, settings=settings)
    assert await service.disconnect(
        project_id=f.project.id, provider_key="network.linkedin", member=TEAMMATE
    )
    assert set(await connections(f)) == {USER}
    assert not await service.disconnect(
        project_id=f.project.id, provider_key="network.linkedin", member=TEAMMATE
    )
    # Without a member, as project deletion does, every one goes, even when a finished job
    # still names the browser that last held its lease.
    assert await f.db.pool.fetchval(
        "SELECT count(*) FROM connection_collection_jobs WHERE project_id=$1 "
        "AND lease_device_id IS NOT NULL",
        f.project.id,
    )
    await add_teammate(f)
    assert await service.disconnect(project_id=f.project.id, provider_key="network.linkedin")
    assert await connections(f) == {}


async def test_other_integrations_stay_one_per_project(collection_db):
    f = await prepared(collection_db)
    for member in (USER, "user_other"):
        await f.db.upsert_integration_connection(
            project_id=f.project.id,
            provider_key="infra.github",
            external_account_id=member,
            external_account_label=member,
            configuration={},
            credential_ciphertext=None,
            credential_key_version=None,
            connected_by_clerk_user_id=member,
        )
    rows = await f.db.pool.fetch(
        "SELECT connected_by_clerk_user_id FROM integration_connections "
        "WHERE project_id=$1 AND provider_key='infra.github'",
        f.project.id,
    )
    assert [r["connected_by_clerk_user_id"] for r in rows] == ["user_other"]
    with pytest.raises(ValueError, match="pairing"):
        await f.db.upsert_integration_connection(
            project_id=f.project.id,
            provider_key="network.linkedin",
            external_account_id="x",
            external_account_label="x",
            configuration={},
            credential_ciphertext=None,
            credential_key_version=None,
            connected_by_clerk_user_id=USER,
        )
