"""Connection requests end to end (#450): proposed after an engagers run, decided in
Decisions or over MCP, then sent one at a time from a synthetic LinkedIn sandbox.

The engagers run uses the collection fixture's synthetic sandbox and model; the sending
activities use a fake sandbox that answers each request as told.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI
from mcp.server.mcpserver.exceptions import ToolError
from test_connection_collection import USER
from test_connection_collection import collection_db as collection_db
from test_linkedin_engagers import (
    Cloud,
    engagers_run,
    fixture,
    member,
    person,
    post,
    run_through,
    work,
)
from test_linkedin_per_member import TEAMMATE, add_teammate
from test_people_view import mcp, structured

from tin_lite import linkedin_requests as requests
from tin_lite import linkedin_requests_activities
from tin_lite import people_records as records
from tin_lite.auth import AuthContext, require_user
from tin_lite.connection_collection import CollectionError
from tin_lite.linkedin_requests_activities import LinkedInRequestsActivities
from tin_lite.linkedin_requests_api import router
from tin_lite.linkedin_requests_service import ConnectionRequests
from tin_lite.people_api import router as people_router

# Monday 19 October 2026, 10:00 in the project's time zone (UTC).
MONDAY = datetime(2026, 10, 19, 10, tzinfo=UTC)
STARTED = []


def client(f, user=USER):
    app = FastAPI()
    app.include_router(router)
    app.include_router(people_router)
    app.state.runtime = SimpleNamespace(database=f.db, storage=f.storage)
    app.state.settings = f.store.settings
    app.dependency_overrides[require_user] = lambda: AuthContext(
        clerk_user_id=user,
        token_type="session_token",  # noqa: S106
    )
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://tin.test")


@pytest.fixture(autouse=True)
def no_temporal(monkeypatch):
    """Approving starts the sending run; here it is recorded instead."""

    STARTED.clear()

    async def start(self, project_id, batch_id, member, trigger_client, oauth_client_id):
        STARTED.append((project_id, batch_id, member, trigger_client))
        return uuid4()

    monkeypatch.setattr(ConnectionRequests, "_start", start)


async def ran(f, people, *, by=None, n=1):
    item = post(n, 3)
    await run_through(
        work(f, Cloud([item], {item["thread_urn"]: people})), await engagers_run(f, by=by)
    )
    return item


async def ids(f) -> dict[str, UUID]:
    """Each person's record ID by their LinkedIn member ID."""

    rows = await f.db.pool.fetch(
        "SELECT record_id, value FROM record_identifiers WHERE kind = 'linkedin_member'"
    )
    return {row["value"]: row["record_id"] for row in rows}


async def turn_on(http, f):
    path = f"/api/projects/{f.project.id}/linkedin-requests/sending"
    refused = await http.put(path, json={"enabled": True})
    assert refused.status_code == 422
    answer = await http.put(path, json={"enabled": True, "consent_version": 1})
    assert answer.status_code == 200, answer.text
    assert answer.json()["sending"]["on"] is True


async def test_sending_needs_cloud_reading(collection_db):
    """Sending uses the session cloud reading saves: browser-only reading can't turn it on."""

    f = await fixture(collection_db)
    await f.db.pool.execute(
        """UPDATE integration_connections
           SET configuration = jsonb_set(configuration, '{collection_permission,mode}',
                                         '"local_only"')
           WHERE project_id = $1 AND provider_key = 'network.linkedin'""",
        f.project.id,
    )
    base = f"/api/projects/{f.project.id}/linkedin-requests"
    async with client(f) as http:
        state = (await http.get(base)).json()
        refused = await http.put(f"{base}/sending", json={"enabled": True, "consent_version": 1})
    assert state["reading"] is False and state["browser_only"] is True
    assert refused.status_code == 409 and "cloud reading" in refused.text


async def test_people_who_fit_and_engaged_with_your_posts_are_proposed_once(collection_db):
    f = await fixture(collection_db)
    await add_teammate(f)
    # 1 and 4 fit and aren't connected; 2 is connected; 3 doesn't fit.
    await ran(f, [person(1), person(2, degree="1st"), person(3, headline="Designer"), person(4)])
    summary = await f.db.pool.fetchval(
        "SELECT result_summary FROM workflow_runs ORDER BY created_at DESC LIMIT 1"
    )
    assert "2 people who fit and aren't connected wait in Decisions" in summary
    base = f"/api/projects/{f.project.id}/linkedin-requests"
    async with client(f) as http:
        state = (await http.get(base)).json()
    assert state["offered"] is True and state["reading"] is True
    assert state["sending"]["on"] is False
    assert state["consent"]["version"] == 1 and "one at a time" in state["consent"]["text"]
    [batch] = state["batches"]
    assert sorted(p["name"] for p in batch["people"]) == ["Person 1", "Person 4"]
    assert batch["people"][0]["fit"] == 0.9 and batch["people"][0]["engaged"]["kind"] == "reacted"
    assert batch["first_send"] and batch["last_send"] >= batch["first_send"]

    # Someone who reacted to a teammate's post is proposed to the teammate, not to you.
    await ran(f, [person(8)], by=TEAMMATE, n=2)
    async with client(f) as http:
        mine = (await http.get(base)).json()["batches"][0]
    async with client(f, TEAMMATE) as http:
        theirs = (await http.get(base)).json()["batches"][0]
    assert "Person 8" not in {p["name"] for p in mine["people"]}
    assert [p["name"] for p in theirs["people"]] == ["Person 8"]

    # A customer is never proposed.
    known = await ids(f)
    async with f.db.pool.acquire() as conn:
        await conn.execute("DELETE FROM linkedin_requests WHERE member = $1", USER)
        await records.set_by_member(
            conn, f.project.id, known[member(4)], [records.Value("customer", "yes")], member=USER
        )
        assert await requests.propose(conn, f.project.id, USER) == 1


async def test_only_you_approve_and_only_with_sending_on(collection_db):
    f = await fixture(collection_db)
    await add_teammate(f)
    await ran(f, [person(1), person(4)])
    known = await ids(f)
    base = f"/api/projects/{f.project.id}/linkedin-requests"
    async with client(f) as http:
        batch = (await http.get(base)).json()["batches"][0]
        approve = f"{base}/batches/{batch['id']}/approve"
        decision = {"request_id": str(uuid4()), "people": [str(known[member(1)])]}
        off = await http.post(approve, json=decision)
        assert off.status_code == 409 and "Turn on sending" in off.json()["detail"]
    async with client(f, TEAMMATE) as http:
        # A teammate's LinkedIn wouldn't send these, so they can't decide them.
        assert (await http.post(approve, json=decision)).status_code == 404
    async with client(f, "user_outsider") as http:
        assert (await http.get(base)).status_code == 404
    async with client(f) as http:
        await turn_on(http, f)
        assert (await http.post(approve, json={"request_id": str(uuid4())})).status_code == 422
        answer = await http.post(approve, json=decision)
        assert answer.status_code == 200, answer.text
        assert answer.json()["queued"] == 1 and answer.json()["run_id"]
        # The same request repeats the same approval; another one is refused.
        assert (await http.post(approve, json=decision)).json()["repeated"] is True
        assert (
            await http.post(approve, json={**decision, "request_id": str(uuid4())})
        ).status_code == 409
        assert (await http.get(base)).json()["batches"] == []
    statuses = dict(
        await f.db.pool.fetch(
            "SELECT record_id, status FROM linkedin_requests WHERE member = $1", USER
        )
    )
    assert statuses == {known[member(1)]: "queued", known[member(4)]: "declined"}
    # A repeated approval asks to start the same run again; its start key makes it one run.
    assert {(m, client_) for _p, _b, m, client_ in STARTED} == {(USER, "dashboard")}
    assert len({b for _p, b, _m, _c in STARTED}) == 1
    # Nobody decided is proposed again.
    await ran(f, [person(1), person(4)], n=3)
    async with client(f) as http:
        assert (await http.get(base)).json()["batches"] == []


class InviteCloud:
    """The LinkedIn sandbox for sending: answers each request and relationship read as told."""

    def __init__(self, db, *, outcomes=None, states=None):
        self.db = db
        self.outcomes, self.states = outcomes or {}, states or {}
        self.calls, self.cleaned = [], []

    async def engagement(self, conn, *, execution_key, run_id, session, packet, seconds=270):
        assert session["cookies"] and packet["actor"]["key"]
        self.calls.append(packet)
        await self.db.save_effect_progress(
            conn, execution_key=execution_key, result={"sandbox_id": f"sandbox-{len(self.calls)}"}
        )
        if packet["kind"] == "linkedin_relationships":
            return {
                "people": [
                    {"member": m, "state": self.states.get(m, "invited")} for m in packet["members"]
                ]
            }
        answer = self.outcomes.get(packet["member"], "sent")
        if isinstance(answer, Exception):
            raise answer
        return {
            "member": packet["member"],
            "outcome": answer,
            "invitation": "urn:li:fsd_invitation:9" if answer == "sent" else None,
        }

    async def cleanup(self, sandbox_id):
        self.cleaned.append(sandbox_id)


class Clock:
    def __init__(self, now):
        self.now = now

    def __call__(self):
        clock = self

        class Fixed(datetime):
            @classmethod
            def now(cls, tz=None):
                return clock.now if tz else clock.now.replace(tzinfo=None)

        return Fixed


async def approved(f, *people_indexes, run_people=(1, 4)):
    await ran(f, [person(i) for i in run_people])
    known = await ids(f)
    async with client(f) as http:
        await turn_on(http, f)
        batch = (await http.get(f"/api/projects/{f.project.id}/linkedin-requests")).json()[
            "batches"
        ][0]
        answer = await http.post(
            f"/api/projects/{f.project.id}/linkedin-requests/batches/{batch['id']}/approve",
            json={
                "request_id": str(uuid4()),
                "people": [str(known[member(i)]) for i in people_indexes],
            },
        )
        assert answer.status_code == 200, answer.text
    return UUID(batch["id"]), known


async def requests_run(f, batch_id: UUID, *, by=USER) -> str:
    workflow_id = await f.db.pool.fetchval("SELECT id FROM workflows WHERE key=$1", requests.KEY)
    if workflow_id is None:
        workflow_id = uuid4()
        await f.db.pool.execute(
            """INSERT INTO workflows (id,key,title,executor,definition_repo_id,
                    definition_path,current_commit_sha,version_label,definition)
               VALUES ($1,$2,$2,$2,'registry/workflows','r.json',$3,'1','{}')""",
            workflow_id,
            requests.KEY,
            "e" * 40,
        )
    run_id = uuid4()
    await f.db.pool.execute(
        """INSERT INTO workflow_runs
           (id,project_id,workflow_id,executor,definition_commit_sha,temporal_workflow_id,
            thread_id,generation,fencing_token,status,lease_active,started_by_clerk_user_id,input)
           VALUES ($1,$2,$3,$4,$5,$6,$7,1,1,'pending',false,$8,$9::jsonb)""",
        run_id,
        f.project.id,
        workflow_id,
        requests.KEY,
        "e" * 40,
        f"{requests.KEY}:{run_id}",
        str(run_id),
        by,
        json.dumps({"project_id": str(f.project.id), "batch_id": str(batch_id)}),
    )
    return str(run_id)


def sender(f, cloud):
    return LinkedInRequestsActivities(
        database=f.db, storage=f.storage, settings=f.store.settings, cipher=f.cipher, cloud=cloud
    )


async def status(f, record_id):
    return await f.db.pool.fetchval(
        "SELECT status FROM linkedin_requests WHERE record_id = $1", record_id
    )


async def test_approved_requests_go_one_at_a_time_and_acceptances_are_read(
    collection_db, monkeypatch
):
    f = await fixture(collection_db)
    batch, known = await approved(f, 1, 4)
    clock = Clock(MONDAY)
    monkeypatch.setattr(linkedin_requests_activities, "datetime", clock())
    cloud = InviteCloud(f.db)
    acts = sender(f, cloud)
    run_id = await requests_run(f, batch)
    await acts.prepare(run_id)

    step = await acts.next(run_id)
    assert step["action"] == "send"
    first = await acts.send({"run_id": run_id, "request_id": step["request_id"]})
    assert first["outcome"] == "sent"
    assert [c["kind"] for c in cloud.calls] == ["linkedin_invite"]
    # The next waits its turn: never two together.
    after = await acts.next(run_id)
    assert after["action"] == "wait" and after["seconds"] >= 15 * 60
    target = cloud.calls[0]["member"]
    sent_to = known[target]
    assert await status(f, sent_to) == "sent"
    # A retried send for the same request asks LinkedIn nothing more.
    again = await acts.send({"run_id": run_id, "request_id": step["request_id"]})
    assert again["outcome"] == "sent" and len(cloud.calls) == 1

    # The person reads as invited in People, with the request on their timeline.
    async with client(f) as http:
        person_view = (await http.get(f"/api/projects/{f.project.id}/people/{sent_to}")).json()
    assert person_view["fields"]["linkedin_relationship"]["value"] == "pending"
    assert person_view["fields"]["linkedin_relationship"]["by"] == "requests"
    assert person_view["events"][0]["kind"] == "invited"

    clock.now = MONDAY + timedelta(hours=1)
    monkeypatch.setattr(linkedin_requests_activities, "datetime", clock())
    step = await acts.next(run_id)
    assert step["action"] == "send"
    await acts.send({"run_id": run_id, "request_id": step["request_id"]})
    assert len(cloud.calls) == 2

    # A day later Tin reads who accepted.
    clock.now = MONDAY + timedelta(days=1, hours=1)
    monkeypatch.setattr(linkedin_requests_activities, "datetime", clock())
    cloud.states = {target: "connected"}
    assert (await acts.next(run_id))["action"] == "check"
    checked = await acts.check(run_id)
    assert checked == {"outcome": "read", "accepted": 1, "pending": 1, "ended": 0}
    assert await status(f, sent_to) == "accepted"
    async with client(f) as http:
        person_view = (await http.get(f"/api/projects/{f.project.id}/people/{sent_to}")).json()
        week = (await http.get(f"/api/projects/{f.project.id}/linkedin-requests")).json()["week"]
    assert person_view["fields"]["linkedin_relationship"]["value"] == "connected"
    assert [e["kind"] for e in person_view["events"][:2]] == ["accepted", "invited"]
    assert week["accepted"] == 1 and week["queued"] == 0

    # When every request is settled or past three weeks, the run finishes with a report.
    await f.db.pool.execute(
        "UPDATE linkedin_requests SET attempted_at = attempted_at - interval '22 days' "
        "WHERE status = 'sent'"
    )
    clock.now = MONDAY + timedelta(days=2)
    monkeypatch.setattr(linkedin_requests_activities, "datetime", clock())
    assert (await acts.next(run_id))["action"] in {"check", "done"}
    await acts.check(run_id)
    assert (await acts.next(run_id))["action"] == "done"
    await acts.finish(run_id)
    run = await f.db.get_run(UUID(run_id))
    assert run.status.value == "succeeded"
    assert run.result_summary == "2 connection requests sent, 1 accepted."
    repo = f.storage.repo
    report = repo.trees[repo.head]["people/connection-requests.md"][1].decode()
    assert "| Person 1 |" in report and "accepted" in report


async def test_linkedin_s_warning_pauses_sending_until_you_resume(collection_db, monkeypatch):
    f = await fixture(collection_db)
    batch, known = await approved(f, 1, 4)
    monkeypatch.setattr(linkedin_requests_activities, "datetime", Clock(MONDAY)())
    cloud = InviteCloud(
        f.db,
        outcomes={member(1): CollectionError("challenge"), member(4): CollectionError("challenge")},
    )
    acts = sender(f, cloud)
    run_id = await requests_run(f, batch)
    await acts.prepare(run_id)
    step = await acts.next(run_id)
    paused = await acts.send({"run_id": run_id, "request_id": step["request_id"]})
    assert paused["outcome"] == "challenge"
    # Nothing went out, so the request waits its turn again; nothing more is sent.
    assert sorted([await status(f, known[member(1)]), await status(f, known[member(4)])]) == [
        "queued",
        "queued",
    ]
    assert await acts.next(run_id) == {"action": "wait", "seconds": 6 * 3600}
    base = f"/api/projects/{f.project.id}/linkedin-requests"
    async with client(f) as http:
        state = (await http.get(base)).json()
        assert state["sending"]["paused"] is True and state["sending"]["held"] is True
        assert state["pause_text"] == "LinkedIn asked to verify your account"
        assert (await http.post(f"{base}/sending/resume")).json()["sending"]["paused"] is False
    cloud.outcomes = {}
    assert (await acts.next(run_id))["action"] == "send"


async def test_linkedin_s_weekly_limit_holds_sending_until_next_week(collection_db, monkeypatch):
    f = await fixture(collection_db)
    batch, known = await approved(f, 1)
    monkeypatch.setattr(linkedin_requests_activities, "datetime", Clock(MONDAY)())
    acts = sender(f, InviteCloud(f.db, outcomes={member(1): "limit"}))
    run_id = await requests_run(f, batch)
    await acts.prepare(run_id)
    step = await acts.next(run_id)
    assert (await acts.send({"run_id": run_id, "request_id": step["request_id"]}))[
        "outcome"
    ] == "limit"
    assert await status(f, known[member(1)]) == "queued"
    held = await f.db.pool.fetchval(
        "SELECT paused_until FROM linkedin_sending WHERE member = $1", USER
    )
    assert held == MONDAY + timedelta(days=7) - timedelta(hours=1)


async def test_a_send_that_may_have_gone_out_is_never_sent_again(collection_db, monkeypatch):
    f = await fixture(collection_db)
    batch, known = await approved(f, 1)
    clock = Clock(MONDAY)
    monkeypatch.setattr(linkedin_requests_activities, "datetime", clock())
    cloud = InviteCloud(f.db, outcomes={member(1): CollectionError("cloud_failed")})
    acts = sender(f, cloud)
    run_id = await requests_run(f, batch)
    await acts.prepare(run_id)
    step = await acts.next(run_id)
    await acts.send({"run_id": run_id, "request_id": step["request_id"]})
    assert await status(f, known[member(1)]) == "uncertain"
    # The next relationship read settles it: never sent, so it is left, not retried.
    clock.now = MONDAY + timedelta(days=1)
    monkeypatch.setattr(linkedin_requests_activities, "datetime", clock())
    cloud.states = {member(1): "none"}
    assert (await acts.next(run_id))["action"] == "check"
    await acts.check(run_id)
    assert await status(f, known[member(1)]) == "not_sent"
    assert (await acts.next(run_id))["action"] == "done"
    assert [c["kind"] for c in cloud.calls].count("linkedin_invite") == 1


async def test_approvals_not_sent_within_two_weeks_lapse(collection_db, monkeypatch):
    f = await fixture(collection_db)
    batch, known = await approved(f, 1)
    await f.db.pool.execute(
        "UPDATE linkedin_requests SET queued_at = now() - interval '15 days' WHERE status='queued'"
    )
    acts = sender(f, InviteCloud(f.db))
    run_id = await requests_run(f, batch)
    await acts.prepare(run_id)
    assert (await acts.next(run_id))["action"] == "done"
    assert await status(f, known[member(1)]) == "lapsed"


async def test_mcp_lists_and_approves_your_requests(collection_db, monkeypatch):
    f = await fixture(collection_db)
    await ran(f, [person(1), person(4)])
    known = await ids(f)
    async with client(f) as http:
        await turn_on(http, f)
    server = mcp(f, monkeypatch)
    project = str(f.project.id)
    listed = structured(await server.call_tool("list_open_decisions", {"project_id": project}))
    [batch] = listed["connection_requests"]
    assert batch["sending_on"] is True
    assert sorted(p["name"] for p in batch["people"]) == ["Person 1", "Person 4"]
    with pytest.raises(ToolError, match="invalid"):
        await server.call_tool(
            "approve_connection_requests",
            {
                "project_id": project,
                "batch_id": batch["batch_id"],
                "person_ids": [str(uuid4())],
                "request_id": str(uuid4()),
            },
        )
    approved_ = structured(
        await server.call_tool(
            "approve_connection_requests",
            {
                "project_id": project,
                "batch_id": batch["batch_id"],
                "person_ids": [str(known[member(4)])],
                "request_id": str(uuid4()),
            },
        )
    )
    assert approved_["status"] == "approved" and approved_["queued"] == 1
    assert STARTED[-1][3] == "mcp"
    listed = structured(await server.call_tool("list_open_decisions", {"project_id": project}))
    assert listed["connection_requests"] == []


async def test_the_workflow_follows_each_step_and_keeps_only_ids_in_history():
    from temporalio import activity
    from temporalio.testing import WorkflowEnvironment
    from temporalio.worker import Replayer, Worker

    from tin_lite.workflows import LinkedInRequestsWorkflow

    steps = [
        {"action": "send", "request_id": str(uuid4())},
        {"action": "wait", "seconds": 3600},
        {"action": "send", "request_id": str(uuid4())},
        {"action": "check"},
        {"action": "done"},
    ]
    calls = []

    @activity.defn(name="linkedin_requests_prepare")
    async def prepare(run_id):
        calls.append("prepare")

    @activity.defn(name="linkedin_requests_next")
    async def next_(run_id):
        calls.append(("next", activity.info().scheduled_time))
        return steps.pop(0)

    @activity.defn(name="linkedin_requests_send")
    async def send(control):
        calls.append(("send", control["request_id"]))
        return {"outcome": "sent", "status": "sent"}

    @activity.defn(name="linkedin_requests_check")
    async def check(run_id):
        calls.append("check")
        return {"outcome": "read", "accepted": 0, "pending": 2, "ended": 0}

    @activity.defn(name="linkedin_requests_finish")
    async def finish(run_id):
        calls.append("finish")

    @activity.defn(name="linkedin_requests_failure")
    async def failure(argument):
        raise AssertionError("Sending must not fail")

    run_id = str(uuid4())
    async with await WorkflowEnvironment.start_time_skipping() as env:
        queue = f"requests-{uuid4()}"
        async with Worker(
            env.client,
            task_queue=queue,
            workflows=[LinkedInRequestsWorkflow],
            activities=[prepare, next_, send, check, finish, failure],
        ):
            handle = await env.client.start_workflow(
                LinkedInRequestsWorkflow.run,
                run_id,
                id=f"{requests.KEY}:{run_id}",
                task_queue=queue,
            )
            await handle.result()
            history = await handle.fetch_history()
    await Replayer(workflows=[LinkedInRequestsWorkflow]).replay_workflow(history)
    kinds = [c if isinstance(c, str) else c[0] for c in calls]
    assert kinds == [
        "prepare",
        "next",
        "send",
        "next",
        "next",
        "send",
        "next",
        "check",
        "next",
        "finish",
    ]
    nexts = [c[1] for c in calls if isinstance(c, tuple) and c[0] == "next"]
    # The hour's wait was slept in the workflow before asking again.
    assert nexts[2] - nexts[1] >= timedelta(hours=1)
    for event in history.events:
        if event.HasField("activity_task_scheduled_event_attributes"):
            for payload in event.activity_task_scheduled_event_attributes.input.payloads:
                value = json.loads(payload.data)
                assert value == run_id or set(value) == {"run_id", "request_id"}
