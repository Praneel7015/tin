"""Reading a member's own posts and who reacted to them, from synthetic LinkedIn answers."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from test_connection_collection import ACTOR, session_envelope

from tin_lite import linkedin_engagement as engagement
from tin_lite.connection_collection import CollectionError
from tin_lite.linkedin_session import validate_session

OWNER = "ACoAAOwner" + "0" * 26
OTHER = "ACoAAOther" + "1" * 26
NOW = datetime(2026, 10, 14, 12, tzinfo=UTC)


def member(index: int) -> str:
    return f"ACoAAPerson{index:04d}" + "x" * 21


def activity(when: datetime, n: int = 0) -> str:
    return f"urn:li:activity:{(int(when.timestamp() * 1000) << 22) + n}"


def me() -> dict:
    mini = f"urn:li:fs_miniProfile:{OWNER}"
    return {
        "data": {"*miniProfile": mini, "plainId": 1, "$type": "com.linkedin.voyager.common.Me"},
        "included": [{"entityUrn": mini, "publicIdentifier": "owner", "firstName": "Owner"}],
    }


def update(when, n=0, *, author=OWNER, reshare=False, thread="ugcPost", text="A post about A"):
    act = activity(when, n)
    number = act.rsplit(":", 1)[1]
    detail, counts = f"urn:li:fs_socialDetail:{number}", f"urn:li:fs_socialActivityCounts:{number}"
    ref = f"urn:li:fs_updateV2:({act},MEMBER_SHARES,EMPTY,DEFAULT,false)"
    return ref, [
        {
            "entityUrn": ref,
            "$type": "com.linkedin.voyager.feed.render.UpdateV2",
            "updateMetadata": {"urn": act, "shareUrn": f"urn:li:share:{number}"},
            "*resharedUpdate": "urn:li:fs_updateV2:(urn:li:activity:1,X)" if reshare else None,
            "actor": {
                "urn": "urn:li:member:1",
                "name": {
                    "text": "Owner Name",
                    "attributes": [
                        {
                            "type": "PROFILE_FULLNAME",
                            "*miniProfile": f"urn:li:fs_miniProfile:{author}",
                        }
                    ],
                },
            },
            "*socialDetail": detail,
            "commentary": {"text": {"text": f"  {text}\n\nwith   spacing  "}},
        },
        {
            "entityUrn": detail,
            "$type": "com.linkedin.voyager.feed.SocialDetail",
            "urn": f"urn:li:{thread}:{number}",
            "*totalSocialActivityCounts": counts,
        },
        {"entityUrn": counts, "numLikes": 12, "numComments": 3},
    ]


def feed(updates, cursor="next-page"):
    refs, included = [], []
    for ref, rows in updates:
        refs.append(ref)
        included.extend(rows)
    return {
        "data": {
            "*elements": refs,
            "paging": {"count": 20, "start": 0},
            "metadata": {"paginationToken": cursor} if cursor else {},
        },
        "included": included,
    }


def reaction(index, *, thread="urn:li:ugcPost:1", actor=None, label="2nd", kind="LIKE"):
    actor = actor or f"urn:li:fsd_profile:{member(index)}"
    ref = f"urn:li:fsd_reaction:({actor},{thread},0)"
    return ref, {
        "entityUrn": ref,
        "$type": "com.linkedin.voyager.dash.social.Reaction",
        "actorUrn": actor,
        "reactionType": kind,
        "reactorLockup": {
            "title": {"text": f"Person {index}"},
            "subtitle": {"text": f"Founder at Company {index}"},
            "label": {"text": f"· {label}"},
            "navigationUrl": f"https://www.linkedin.com/in/{member(index)}",
        },
    }


def reactions(start, total, rows):
    return {
        "data": {
            "paging": {"count": 10, "start": start, "total": total},
            "*elements": [ref for ref, _ in rows],
        },
        "included": [row for _, row in rows],
    }


async def no_wait(_seconds):
    return None


def test_own_posts_leave_out_plain_reposts():
    pinned = NOW - timedelta(days=200)
    page = feed(
        [
            update(NOW - timedelta(days=2), 1),
            update(NOW - timedelta(days=3), 2, reshare=True),
            update(NOW - timedelta(days=4), 3, author=OTHER),
            update(NOW - timedelta(days=5), 4, thread="share"),
            update(pinned, 5),
        ]
    )
    posts, cursor, seen = engagement.own_posts(page, OWNER)
    assert cursor == "next-page" and seen == 5
    # A repost with the owner's words is theirs; a plain repost names its original author.
    assert [p["thread_urn"].split(":")[2] for p in posts] == [
        "ugcPost",
        "ugcPost",
        "share",
        "ugcPost",
    ]
    first = posts[0]
    assert first["excerpt"] == "A post about A with spacing"
    assert first["reactions"] == 12 and first["comments"] == 3
    assert datetime.fromisoformat(first["published_at"]).date() == (NOW - timedelta(days=2)).date()
    # Past the last page LinkedIn answers with paging and no elements.
    end = {"data": {"paging": {"count": 20, "start": 40}, "metadata": {}}, "included": []}
    assert engagement.own_posts(end, OWNER) == ([], None, 0)
    with pytest.raises(CollectionError, match="unsupported_contract"):
        engagement.own_posts({"data": {}, "included": []}, OWNER)


async def test_reads_posts_in_the_window_through_pages():
    seen = []
    pages = {
        "0": feed(
            [update(NOW - timedelta(days=400), 9)]  # pinned, older than the window
            + [update(NOW - timedelta(days=d), d) for d in (1, 10, 20)]
        ),
        "20": feed([update(NOW - timedelta(days=d), d) for d in (30, 80, 95)], cursor="t2"),
        "40": feed([update(NOW - timedelta(days=d), d) for d in (120, 130)], cursor="t3"),
    }

    def respond(request):
        seen.append(request)
        assert request.method == "GET" and request.url.host == "www.linkedin.com"
        if request.url.path == "/voyager/api/me":
            return httpx.Response(200, json=me())
        assert request.url.path == "/voyager/api/identity/profileUpdatesV2"
        params = request.url.params
        assert params["q"] == "memberShareFeed"
        assert params["profileUrn"] == f"urn:li:fsd_profile:{OWNER}"
        assert request.headers["referer"].endswith(f"/in/{OWNER}/recent-activity/all/")
        if params["start"] != "0":
            assert params["paginationToken"] == {"20": "next-page", "40": "t2"}[params["start"]]
        return httpx.Response(200, json=pages[params["start"]])

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        result = await engagement.read_posts(
            validate_session(session_envelope()), ACTOR, client=client, now=NOW, sleep=no_wait
        )
    days = [(NOW - datetime.fromisoformat(p["published_at"])).days for p in result["posts"]]
    assert days == [1, 10, 20, 30, 80]
    assert result["complete"]
    assert [r.url.params.get("start") for r in seen[1:]] == ["0", "20", "40"]


async def test_post_reads_stop_at_the_limit_and_check_the_account():
    def respond(request):
        if request.url.path == "/voyager/api/me":
            return httpx.Response(200, json=me())
        return httpx.Response(
            200, json=feed([update(NOW - timedelta(days=d), d) for d in (1, 2, 3)])
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        result = await engagement.read_posts(
            validate_session(session_envelope()),
            ACTOR,
            client=client,
            now=NOW,
            limit=2,
            sleep=no_wait,
        )
        assert len(result["posts"]) == 2 and result["complete"]
        with pytest.raises(CollectionError, match="account_changed"):
            await engagement.read_posts(
                validate_session(session_envelope()),
                {
                    **ACTOR,
                    "key": "https://www.linkedin.com/in/someone",
                    "profile_url": "https://www.linkedin.com/in/someone",
                },
                client=client,
                now=NOW,
                sleep=no_wait,
            )


def test_a_reactions_page_names_people_only():
    rows = [
        reaction(1, label="1st"),
        reaction(2, label="3rd+", kind="EMPATHY"),
        reaction(3, actor="urn:li:fsd_company:12345"),
        reaction(4, actor=f"urn:li:fsd_profile:{OWNER}"),
        reaction(5, label="Following", kind="<script>"),
    ]
    people, total = engagement.reactions_page(reactions(0, 5, rows), start=0, profile_id=OWNER)
    assert total == 5
    assert people == [
        {
            "member": member(1),
            "name": "Person 1",
            "headline": "Founder at Company 1",
            "degree": "1st",
            "reaction": "LIKE",
        },
        {
            "member": member(2),
            "name": "Person 2",
            "headline": "Founder at Company 2",
            "degree": "3rd",
            "reaction": "EMPATHY",
        },
        {
            "member": member(5),
            "name": "Person 5",
            "headline": "Founder at Company 5",
            "degree": None,
            "reaction": None,
        },
    ]
    with pytest.raises(CollectionError, match="unsupported_contract"):
        engagement.reactions_page(reactions(10, 5, rows), start=0, profile_id=OWNER)


async def test_reads_reactions_page_by_page_and_says_where_it_stopped():
    seen = []
    thread, act = "urn:li:ugcPost:7508955117447147520", activity(NOW, 1)

    def respond(request):
        seen.append(request)
        if request.url.path == "/voyager/api/me":
            return httpx.Response(200, json=me())
        assert request.url.path == "/voyager/api/voyagerSocialDashReactions"
        assert request.url.params["threadUrn"] == thread
        assert request.headers["referer"] == f"https://www.linkedin.com/feed/update/{act}/"
        start = int(request.url.params["start"])
        rows = [reaction(i, thread=thread) for i in range(start, min(start + 10, 23))]
        return httpx.Response(200, json=reactions(start, 23, rows))

    session = validate_session(session_envelope())
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        everything = await engagement.read_reactions(
            session, ACTOR, client=client, activity_urn=act, thread_urn=thread, sleep=no_wait
        )
        assert len(everything["people"]) == 23 and everything["next_start"] is None
        part = await engagement.read_reactions(
            session,
            ACTOR,
            client=client,
            activity_urn=act,
            thread_urn=thread,
            pages=2,
            sleep=no_wait,
        )
        assert len(part["people"]) == 20 and part["next_start"] == 20
        rest = await engagement.read_reactions(
            session,
            ACTOR,
            client=client,
            activity_urn=act,
            thread_urn=thread,
            start=20,
            sleep=no_wait,
        )
        assert [p["name"] for p in rest["people"]] == ["Person 20", "Person 21", "Person 22"]
        assert rest["next_start"] is None
        for bad in ({"start": 5}, {"thread_urn": "urn:li:activity:1"}):
            with pytest.raises(CollectionError, match="unsupported_contract"):
                await engagement.read_reactions(
                    session,
                    ACTOR,
                    client=client,
                    activity_urn=act,
                    sleep=no_wait,
                    **{"thread_urn": thread, **bad},
                )
    assert all(r.method == "GET" for r in seen)


async def test_a_very_large_post_is_capped(monkeypatch):
    monkeypatch.setattr(engagement, "MAX_REACTIONS", 20)
    thread, act = "urn:li:ugcPost:7508955117447147520", activity(NOW, 1)

    def respond(request):
        if request.url.path == "/voyager/api/me":
            return httpx.Response(200, json=me())
        start = int(request.url.params["start"])
        return httpx.Response(
            200,
            json=reactions(
                start, 500, [reaction(i, thread=thread) for i in range(start, start + 10)]
            ),
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        result = await engagement.read_reactions(
            validate_session(session_envelope()),
            ACTOR,
            client=client,
            activity_urn=act,
            thread_urn=thread,
            sleep=no_wait,
        )
    assert len(result["people"]) == 20
    assert result["next_start"] is None and result["capped"]


@pytest.mark.parametrize(
    ("status", "location", "code"),
    [
        (302, "https://www.linkedin.com/checkpoint/challenge/x", "challenge"),
        (302, "https://www.linkedin.com/login", "session_expired"),
        (429, "", "rate_limited"),
        (999, "", "access_denied"),
    ],
)
async def test_linkedin_refusals_stop_the_read(status, location, code):
    def respond(request):
        if request.url.path == "/voyager/api/me":
            return httpx.Response(200, json=me())
        return httpx.Response(status, headers={"location": location} if location else {})

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        with pytest.raises(CollectionError, match=code):
            await engagement.read_posts(
                validate_session(session_envelope()), ACTOR, client=client, now=NOW, sleep=no_wait
            )


def test_the_sandbox_runner_refuses_an_unknown_or_overlong_read(tmp_path):
    """The image's fixed program: a packet it doesn't know, or one asking for too long, fails
    closed with an error file and no network."""

    source = Path(__file__).parents[1] / "sandbox/linkedin/runner.py"
    text = source.read_text()
    assert '"linkedin_posts": 300' in text and '"linkedin_reactions": 300' in text
    work = tmp_path / "run"
    work.mkdir()
    program = text.replace("/run/tin-collection", str(work)).replace(
        'sys.path.insert(0, "/opt/tin-collection")',
        f"sys.path.insert(0, {str(Path(__file__).parents[1] / 'src')!r})",
    )
    script = tmp_path / "runner.py"
    script.write_text(program)
    import time

    for packet in (
        {"kind": "linkedin_comments", "expires_at": time.time() + 60},
        {"kind": "linkedin_posts", "expires_at": time.time() + 900},
    ):
        (work / "request.json").write_text(json.dumps(packet))
        # The repository's own runner, with this test's paths.
        subprocess.run([sys.executable, str(script)], check=True, timeout=30)  # noqa: S603
        assert json.loads((work / "result.json").read_text()) == {"error": "cloud_failed"}
        assert not (work / "request.json").exists()
