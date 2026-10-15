"""Connection requests (#450): what LinkedIn's answers mean, and when each request may go.

Synthetic LinkedIn only: an httpx mock transport stands in for www.linkedin.com.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest
from test_connection_collection import ACTOR, session_envelope
from test_linkedin_engagement import OWNER, me
from test_linkedin_engagement import member as engagement_member

from tin_lite import linkedin_invitations as invitations
from tin_lite import linkedin_requests as requests
from tin_lite.connection_collection import CollectionError
from tin_lite.linkedin_session import validate_session

CONNECTED = {"*connection": "urn:li:fsd_connection:ACoAAx"}
NOBODY = {"noConnection": {"invitationUnion": {"noInvitation": {}}, "memberDistance": "DISTANCE_2"}}
INVITED = {"noConnection": {"invitationUnion": {"*invitation": "urn:li:fsd_invitation:42"}}}


def top_card(target: str, union) -> dict:
    return {
        "data": {"*elements": [f"urn:li:fsd_profile:{target}"]},
        "included": [
            {"entityUrn": f"urn:li:fsd_profile:{target}", "firstName": "Someone"},
            {
                "entityUrn": f"urn:li:fsd_memberRelationship:{target}",
                "memberRelationshipUnion": union,
                "$type": "com.linkedin.voyager.dash.relationships.MemberRelationship",
            },
        ],
    }


async def no_wait(_seconds):
    return None


def linkedin(relationships: dict, invite=None):
    """A mock LinkedIn: /me, each person's top card, and the one invitation POST."""

    posts = []

    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/voyager/api/me":
            return httpx.Response(200, json=me())
        if request.url.path == "/voyager/api/identity/dash/profiles":
            target = request.url.params["memberIdentity"]
            assert request.url.params["decorationId"] == invitations.TOP_CARD
            union = relationships.get(target)
            return httpx.Response(200, json=top_card(target, union) if union else {})
        if request.method == "POST":
            assert request.url.path == "/voyager/api/voyagerRelationshipsDashMemberRelationships"
            assert request.url.params["action"] == "verifyQuotaAndCreateV2"
            assert request.headers["content-type"].startswith("application/json")
            assert request.headers["csrf-token"]
            posts.append(json.loads(request.content))
            return invite(request) if invite else httpx.Response(201)
        raise AssertionError(f"unexpected {request.method} {request.url}")

    return respond, posts


def test_a_top_card_says_connected_invited_neither_or_unknown():
    target = engagement_member(1)
    assert invitations.relationship_state(top_card(target, CONNECTED), target) == "connected"
    assert invitations.relationship_state(top_card(target, INVITED), target) == "invited"
    assert invitations.relationship_state(top_card(target, NOBODY), target) == "none"
    # Someone else's relationship, an unknown union or no relationship at all: unknown.
    assert invitations.relationship_state(top_card(engagement_member(2), NOBODY), target) == (
        "unknown"
    )
    assert invitations.relationship_state(top_card(target, {"other": {}}), target) == "unknown"
    assert invitations.relationship_state({}, target) == "unknown"
    assert invitations.relationship_state(None, target) == "unknown"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("union", "invite", "outcome", "posted"),
    [
        (CONNECTED, None, "connected", 0),
        (INVITED, None, "invited", 0),
        (None, None, "unknown_person", 0),
        (
            NOBODY,
            lambda r: httpx.Response(
                201, headers={"x-restli-id": "urn:li:fsd_invitation:7"}, json={}
            ),
            "sent",
            1,
        ),
        (NOBODY, lambda r: httpx.Response(429), "limit", 1),
        (
            NOBODY,
            lambda r: httpx.Response(400, text='{"code":"CANT_RESEND_YET fuse limit"}'),
            "limit",
            1,
        ),
        (NOBODY, lambda r: httpx.Response(422, text="{}"), "refused", 1),
        (NOBODY, lambda r: httpx.Response(500), "uncertain", 1),
    ],
)
async def test_a_request_goes_only_to_someone_neither_connected_nor_invited(
    union, invite, outcome, posted
):
    target = engagement_member(3)
    respond, posts = linkedin({target: union} if union else {}, invite)
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        result = await invitations.send_invitation(
            validate_session(session_envelope()), ACTOR, client=client, member=target, sleep=no_wait
        )
    assert result["outcome"] == outcome
    assert len(posts) == posted
    if posted:
        # No note: the request names the person and nothing else.
        assert posts[0] == {
            "invitee": {"inviteeUnion": {"memberProfile": f"urn:li:fsd_profile:{target}"}}
        }
    if outcome == "sent":
        assert result["invitation"] == "urn:li:fsd_invitation:7"
    invitations.InviteResult.model_validate(result)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("answer", "code"),
    [
        (httpx.Response(302, headers={"location": "/checkpoint/challenge"}), "challenge"),
        (httpx.Response(401), "session_expired"),
        (httpx.Response(403), "access_denied"),
    ],
)
async def test_a_warning_on_the_request_stops_sending(answer, code):
    target = engagement_member(4)
    respond, _posts = linkedin({target: NOBODY}, lambda r: answer)
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        with pytest.raises(CollectionError, match=code):
            await invitations.send_invitation(
                validate_session(session_envelope()),
                ACTOR,
                client=client,
                member=target,
                sleep=no_wait,
            )


@pytest.mark.asyncio
async def test_never_to_yourself_and_never_to_a_malformed_id():
    respond, posts = linkedin({})
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        own = await invitations.send_invitation(
            validate_session(session_envelope()), ACTOR, client=client, member=OWNER, sleep=no_wait
        )
        with pytest.raises(CollectionError):
            await invitations.send_invitation(
                validate_session(session_envelope()),
                ACTOR,
                client=client,
                member="not-an-id",
                sleep=no_wait,
            )
    assert own["outcome"] == "refused" and posts == []


@pytest.mark.asyncio
async def test_a_relationship_read_covers_a_few_people_at_a_time():
    first, second = engagement_member(5), engagement_member(6)
    respond, posts = linkedin({first: CONNECTED, second: INVITED})
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        result = await invitations.read_relationships(
            validate_session(session_envelope()),
            ACTOR,
            client=client,
            members=[first, second],
            sleep=no_wait,
        )
        with pytest.raises(CollectionError):
            await invitations.read_relationships(
                validate_session(session_envelope()),
                ACTOR,
                client=client,
                members=[engagement_member(i) for i in range(21)],
                sleep=no_wait,
            )
    assert invitations.RelationshipsResult.model_validate(result).model_dump() == {
        "people": [{"member": first, "state": "connected"}, {"member": second, "state": "invited"}]
    }
    assert posts == []


# Pacing: weekdays inside the window, a gap after every request, and the caps.

LA = {
    **{k: v for k, v in requests.DEFAULTS.items()},
    "timezone": "America/Los_Angeles",
}
# Monday 19 October 2026, 10:00 in Los Angeles (UTC-7).
MONDAY_10 = datetime(2026, 10, 19, 17, tzinfo=UTC)


def la(day: int, hour: int, minute: int = 0) -> datetime:
    """A time in Los Angeles in the week of Monday 19 October (day 0 is Monday)."""

    return datetime(2026, 10, 19, 17, tzinfo=UTC) + timedelta(
        days=day, hours=hour - 10, minutes=minute
    )


def test_a_request_waits_for_a_weekday_inside_the_window():
    request = uuid4()
    first = MONDAY_10 - timedelta(days=30)
    assert requests.next_slot(MONDAY_10, LA, [], request, first=first) == MONDAY_10
    assert requests.next_slot(la(0, 7), LA, [], request, first=first) == la(0, 9)
    assert requests.next_slot(la(0, 17, 1), LA, [], request, first=first) == la(1, 9)
    assert requests.next_slot(la(4, 18), LA, [], request, first=first) == la(7, 9)
    assert requests.next_slot(la(5, 12), LA, [], request, first=first) == la(7, 9)


def test_requests_are_never_together():
    request = uuid4()
    first = MONDAY_10 - timedelta(days=30)
    last = MONDAY_10 - timedelta(minutes=5)
    slot = requests.next_slot(MONDAY_10, LA, [last], request, first=first)
    assert slot == last + requests.GAP + requests.jitter(request)
    assert timedelta(minutes=15) <= slot - last <= timedelta(minutes=40)
    # The same request always draws the same wait.
    assert requests.jitter(request) == requests.jitter(str(request))


def test_the_caps_hold_and_the_first_week_is_half():
    request = uuid4()
    long_ago = MONDAY_10 - timedelta(days=30)
    today = [la(0, 9) + timedelta(minutes=16 * i) for i in range(8)]
    # In the first week, 8 a day (half of 15): the ninth waits for tomorrow.
    assert requests.next_slot(la(0, 12), LA, today, request, first=today[0]) == la(1, 9)
    # After it, 15 a day.
    assert requests.next_slot(la(0, 12), LA, today, request, first=long_ago) == la(0, 12)
    week = [la(day, 9) + timedelta(minutes=16 * i) for day in range(4) for i in range(15)]
    assert requests.next_slot(la(4, 10), LA, week, request, first=long_ago) == la(7, 9)
    held = {**LA, "paused_until": la(2, 11)}
    assert requests.next_slot(la(0, 10), held, [], request, first=long_ago) == la(2, 11)


def test_a_batch_is_spread_one_at_a_time_inside_the_window():
    ids = [uuid4() for _ in range(12)]
    plan = requests.projection(la(0, 16), LA, [], ids)
    assert len(plan) == 12
    for earlier, later in zip(plan, plan[1:], strict=False):
        assert later - earlier >= timedelta(minutes=15)
    for moment in plan:
        local = moment.astimezone(requests.ZoneInfo("America/Los_Angeles"))
        assert local.weekday() < 5 and 9 <= local.hour < 17
    # A first week: 8 a day.
    days = {m.astimezone(requests.ZoneInfo("America/Los_Angeles")).date() for m in plan}
    assert len(days) >= 2


class Answers:
    """A connection whose queries answer in order: Start here, saved schedule, project."""

    def __init__(self, *values):
        self.values = list(values)

    async def fetchval(self, _query, _project_id):
        return self.values.pop(0)


@pytest.mark.asyncio
async def test_the_window_is_in_the_founder_s_time_zone_as_start_here_recorded_it():
    project = uuid4()
    zone = requests.founder_timezone
    assert await zone(Answers("America/Los_Angeles", "Europe/Berlin", "UTC"), project) == (
        "America/Los_Angeles"
    )
    assert await zone(Answers(None, "Europe/Berlin", "UTC"), project) == "Europe/Berlin"
    # Free text Start here couldn't resolve falls through; the project's default is UTC.
    assert await zone(Answers("Pacific time", None, "Asia/Tokyo"), project) == "Asia/Tokyo"
    assert await zone(Answers(None, None, None), project) == "UTC"
