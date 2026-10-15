"""The People view: the list a run wrote, one person with their timeline, and forgetting them.

Reads and scores come from the engagers workflow with a synthetic sandbox and model; the HTTP
API is called as a project member.
"""

from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID, uuid4

import httpx
from fastapi import FastAPI
from test_connection_collection import USER
from test_connection_collection import collection_db as collection_db
from test_linkedin_engagers import (
    ICP,
    Cloud,
    Router,
    engagers_run,
    fixture,
    member,
    person,
    post,
    run_through,
    work,
)
from test_linkedin_per_member import TEAMMATE, add_teammate

from tin_lite import people_records as records
from tin_lite.auth import AuthContext, require_user
from tin_lite.people_api import router
from tin_lite.people_records import Value


def client(f, user=USER):
    app = FastAPI()
    app.include_router(router)
    app.state.runtime = SimpleNamespace(database=f.db, storage=f.storage)
    app.dependency_overrides[require_user] = lambda: AuthContext(
        clerk_user_id=user,
        token_type="session_token",  # noqa: S106
    )
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://tin.test")


async def ran(f, people, *, days=3, by=None):
    item = post(1, days)
    await run_through(
        work(f, Cloud([item], {item["thread_urn"]: people})), await engagers_run(f, by=by)
    )
    return item


def by_name(listed):
    return {p["name"]: p for p in listed["people"]}


async def test_the_list_shows_each_value_with_who_set_it_and_the_last_touch(collection_db):
    f = await fixture(collection_db)
    item = await ran(f, [person(1, degree="1st"), person(2, headline="Designer")])
    async with client(f) as http:
        listed = (await http.get(f"/api/projects/{f.project.id}/people")).json()
    assert listed["truncated"] is False and listed["fit_shown"] == 0.6
    people = by_name(listed)
    assert set(people) == {"Person 1", "Person 2"}
    one = people["Person 1"]
    assert one["headline"] == "Founder at Startup 1"
    assert one["profile_url"] == f"https://www.linkedin.com/in/{member(1)}"
    fields = one["fields"]
    assert fields["icp"]["value"] == "Software founders"
    assert fields["icp_fit"]["value"] == 0.9
    assert fields["icp_fit"]["reason"].startswith("Headline says")
    assert fields["icp_fit"]["by"] == "engagers" and fields["icp_fit"]["stale"] is False
    assert fields["icp_fit"]["definition"] == "strategy/ICP.md"
    assert fields["linkedin_relationship"]["value"] == "connected"
    assert people["Person 2"]["fields"]["linkedin_relationship"]["value"] == "none"
    assert people["Person 2"]["fields"]["icp"]["value"] == "none"
    # LinkedIn gives no reaction time: the last touch is the post's date.
    assert one["last_touch"]["kind"] == "reacted"
    assert one["last_touch"]["at"][:10] == item["published_at"][:10]
    assert one["added"]["by"] == "engagers"

    # A changed ICP file marks every score old until the next run rescores it.
    changed = ICP + "\n## 3. Agencies\n\nBuyer: a CTO.\n"
    f.storage.repo.edit({"strategy/ICP.md": changed.encode()}, message="ICP")
    async with client(f) as http:
        people = by_name((await http.get(f"/api/projects/{f.project.id}/people")).json())
    assert people["Person 1"]["fields"]["icp_fit"]["stale"] is True
    assert people["Person 1"]["fields"]["icp"]["stale"] is True
    assert people["Person 1"]["fields"]["linkedin_relationship"]["stale"] is False


async def test_a_person_shows_their_timeline_and_whose_post_it_was(collection_db):
    f = await fixture(collection_db)
    await add_teammate(f)
    mine = await ran(f, [person(1)], days=3)
    theirs = await ran(f, [person(1)], days=9, by=TEAMMATE)
    async with client(f) as http:
        listed = (await http.get(f"/api/projects/{f.project.id}/people")).json()
        found = listed["people"][0]
        one = (await http.get(f"/api/projects/{f.project.id}/people/{found['id']}")).json()
        as_teammate = await http.get(f"/api/projects/{f.project.id}/people/{found['id']}")
    assert [e["at"][:10] for e in one["events"]] == [
        mine["published_at"][:10],
        theirs["published_at"][:10],
    ]
    newest = one["events"][0]
    assert newest["kind"] == "reacted" and newest["reaction"] == "LIKE"
    assert newest["post_url"] == f"https://www.linkedin.com/feed/update/{mine['activity_urn']}/"
    assert [e["yours"] for e in one["events"]] == [True, False]
    assert as_teammate.status_code == 200

    # A value a member set says who: you, or a teammate.
    async with f.db.pool.acquire() as conn:
        await records.set_values(
            conn,
            f.project.id,
            UUID(found["id"]),
            [Value("icp", "Service agencies", "Runs an agency")],
            set_by_kind="member",
            set_by=TEAMMATE,
        )
    async with client(f) as http:
        me = (await http.get(f"/api/projects/{f.project.id}/people/{found['id']}")).json()
    async with client(f, TEAMMATE) as http:
        them = (await http.get(f"/api/projects/{f.project.id}/people/{found['id']}")).json()
    assert me["fields"]["icp"]["by"] == "a teammate" and them["fields"]["icp"]["by"] == "you"
    assert [e["yours"] for e in them["events"]] == [False, True]


async def test_forgetting_a_person_removes_them_and_keeps_them_out(collection_db):
    f = await fixture(collection_db)
    await ran(f, [person(1), person(2)])
    path = f"/api/projects/{f.project.id}/people"
    async with client(f) as http:
        gone = by_name((await http.get(path)).json())["Person 2"]["id"]
        assert (await http.delete(f"{path}/{gone}")).status_code == 204
        assert (await http.get(f"{path}/{gone}")).status_code == 404
        assert (await http.delete(f"{path}/{gone}")).status_code == 404
        assert set(by_name((await http.get(path)).json())) == {"Person 1"}
    await ran(f, [person(1), person(2)])
    async with client(f) as http:
        assert set(by_name((await http.get(path)).json())) == {"Person 1"}


async def test_only_project_members_see_or_forget_people(collection_db):
    f = await fixture(collection_db)
    await ran(f, [person(1)])
    path = f"/api/projects/{f.project.id}/people"
    async with client(f) as http:
        someone = (await http.get(path)).json()["people"][0]["id"]
    async with client(f, "user_outsider") as http:
        assert (await http.get(path)).status_code == 404
        assert (await http.get(f"{path}/{someone}")).status_code == 404
        assert (await http.delete(f"{path}/{someone}")).status_code == 404
        assert (await http.get(f"/api/projects/{uuid4()}/people")).status_code == 404
    async with client(f) as http:
        assert len((await http.get(path)).json()["people"]) == 1


async def test_without_people_or_an_icp_the_list_is_empty(collection_db):
    f = await fixture(collection_db, icp=None)
    async with client(f) as http:
        listed = (await http.get(f"/api/projects/{f.project.id}/people")).json()
    assert listed["people"] == []


async def test_a_person_forgotten_while_scored_is_skipped(collection_db):
    f = await fixture(collection_db)
    item = post(1, 2)

    class Forgetting(Router):
        async def generate(self, route, request, *, timeout_seconds):
            async with f.db.pool.acquire() as conn:
                for found in await records.people(conn, f.project.id):
                    if found["identifiers"]["linkedin_member"] == member(2):
                        await records.forget(conn, f.project.id, found["id"])
            return await super().generate(route, request, timeout_seconds=timeout_seconds)

    run_id = await engagers_run(f)
    await run_through(
        work(f, Cloud([item], {item["thread_urn"]: [person(1), person(2)]}), Forgetting()),
        run_id,
    )
    left = await records.people(f.db.pool, f.project.id)
    assert [p["fields"]["name"]["text"] for p in left] == ["Person 1"]
    assert left[0]["fields"]["icp_fit"]["number"] == 0.9
    status = await f.db.pool.fetchval("SELECT status FROM workflow_runs WHERE id=$1", UUID(run_id))
    assert status == "succeeded"
