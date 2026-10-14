"""Read who engaged with a member's own LinkedIn posts, with their saved session (#435).

Two reads, both GET-only JSON on www.linkedin.com, each starting with the same /me check the
collection reader makes:
- the member's own posts, newest first, from their share feed; plain reposts of other
  people's posts are left out;
- one post's reactions, a page of ten at a time, with each person's name, headline, LinkedIn
  profile ID and connection degree.

Reads wait a random few seconds between pages, like a person reading. This module runs in the
LinkedIn sandbox image, so it imports only the standard library, httpx and the collection and
session modules copied beside it.
"""

from __future__ import annotations

import asyncio
import base64
import re
import secrets
import unicodedata
from datetime import UTC, datetime, timedelta
from urllib.parse import quote

from tin_lite.connection_collection import CollectionError
from tin_lite.linkedin_session import _get, headers, identity_matches, identity_profile

WINDOW_DAYS = 90
MAX_POSTS = 60
FEED_PAGE = 20
MAX_FEED_PAGES = 6
REACTIONS_PAGE = 10
# Pages one read may take before handing back where it stopped; the caller continues there.
REACTION_PAGES_PER_READ = 10
# A runaway guard far above a founder's post: the rest of a larger post is left unread.
MAX_REACTIONS = 1000
GAP_SECONDS = (3.0, 9.0)
MEMBER_ID = re.compile(r"ACo[A-Za-z0-9_-]{20,80}")
ACTIVITY = re.compile(r"urn:li:activity:(\d{15,22})")
THREAD = re.compile(r"urn:li:(?:ugcPost|share):\d{15,22}")
DEGREE = re.compile(r"(1st|2nd|3rd)\+?")
REACTION = re.compile(r"[A-Z][A-Z_]{1,30}")
ORIGIN = "https://www.linkedin.com"
_RANDOM = secrets.SystemRandom()


def clean(value) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(unicodedata.normalize("NFC", value).split())


def posted_at(activity_urn: str) -> datetime:
    """When a post was made: LinkedIn activity IDs carry their creation time."""

    match = ACTIVITY.fullmatch(activity_urn)
    if not match:
        raise CollectionError("unsupported_contract")
    return datetime.fromtimestamp((int(match[1]) >> 22) / 1000, UTC)


def _headers(session, *, page: str, referer: str) -> dict:
    result = headers(session)
    result["referer"] = referer
    result["x-li-page-instance"] = (
        f"urn:li:page:{page};" + base64.b64encode(secrets.token_bytes(16)).decode()
    )
    return result


def own_profile_id(me_payload) -> str:
    """The signed-in member's LinkedIn profile ID, from the same /me answer the check reads."""

    urn = identity_profile(me_payload).get("entityUrn", "")
    member = urn.rsplit(":", 1)[-1] if isinstance(urn, str) else ""
    if not urn.startswith("urn:li:fs_miniProfile:") or not MEMBER_ID.fullmatch(member):
        raise CollectionError("unsupported_identity")
    return member


def _index(payload) -> tuple[dict, dict]:
    if not isinstance(payload, dict):
        raise CollectionError("unsupported_contract")
    data, included = payload.get("data"), payload.get("included")
    if not isinstance(data, dict) or not isinstance(included, list):
        raise CollectionError("unsupported_contract")
    by_urn = {
        item["entityUrn"]: item
        for item in included
        if isinstance(item, dict) and isinstance(item.get("entityUrn"), str)
    }
    return data, by_urn


def own_posts(payload, profile_id: str) -> tuple[list[dict], str | None, int]:
    """One share-feed page: the member's own posts, the next page's token, and how many
    updates the page held (plain reposts count, so only an empty page ends the feed).
    """

    data, by_urn = _index(payload)
    # The page after the last one comes back with paging and no elements at all.
    refs = data.get("*elements", [] if isinstance(data.get("paging"), dict) else None)
    if not isinstance(refs, list):
        raise CollectionError("unsupported_contract")
    metadata = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
    token = metadata.get("paginationToken")
    posts = []
    for ref in refs:
        update = by_urn.get(ref)
        if not isinstance(update, dict):
            continue
        meta = update.get("updateMetadata") or {}
        activity = meta.get("urn") if isinstance(meta, dict) else None
        if not isinstance(activity, str) or not ACTIVITY.fullmatch(activity):
            continue
        # A plain repost names the original author as its actor, so it fails this check; a
        # repost with the member's own words is their post, with its own reactions.
        actor = update.get("actor") if isinstance(update.get("actor"), dict) else {}
        name = actor.get("name") if isinstance(actor.get("name"), dict) else {}
        minis = {
            attribute.get("*miniProfile")
            for attribute in name.get("attributes") or []
            if isinstance(attribute, dict)
        }
        if f"urn:li:fs_miniProfile:{profile_id}" not in minis:
            continue
        detail = by_urn.get(update.get("*socialDetail")) or {}
        thread = detail.get("urn")
        if not isinstance(thread, str) or not THREAD.fullmatch(thread):
            continue
        counts = by_urn.get(detail.get("*totalSocialActivityCounts")) or {}
        commentary = update.get("commentary") if isinstance(update.get("commentary"), dict) else {}
        text = commentary.get("text") if isinstance(commentary.get("text"), dict) else {}
        posts.append(
            {
                "activity_urn": activity,
                "thread_urn": thread,
                "published_at": posted_at(activity).isoformat(),
                "excerpt": clean(text.get("text"))[:280],
                "reactions": counts.get("numLikes")
                if type(counts.get("numLikes")) is int
                else None,
                "comments": (
                    counts.get("numComments") if type(counts.get("numComments")) is int else None
                ),
            }
        )
    return posts, token if isinstance(token, str) and len(token) <= 500 else None, len(refs)


def reactions_page(payload, *, start: int, profile_id: str) -> tuple[list[dict], int]:
    """One page of a post's reactions: the people who reacted, and the post's total."""

    data, by_urn = _index(payload)
    paging, refs = data.get("paging"), data.get("*elements")
    if (
        not isinstance(paging, dict)
        or paging.get("start") != start
        or type(paging.get("total")) is not int
        or not isinstance(refs, list)
        or len(refs) > REACTIONS_PAGE
    ):
        raise CollectionError("unsupported_contract")
    people = []
    for ref in refs:
        reaction = by_urn.get(ref)
        if not isinstance(reaction, dict):
            continue
        union = reaction.get("actorUnion") if isinstance(reaction.get("actorUnion"), dict) else {}
        actor = reaction.get("actorUrn") or union.get("profileUrn")
        # Pages and companies react too; only people become records.
        if not isinstance(actor, str) or not actor.startswith("urn:li:fsd_profile:"):
            continue
        member = actor.rsplit(":", 1)[1]
        if not MEMBER_ID.fullmatch(member) or member == profile_id:
            continue
        lockup = reaction.get("reactorLockup")
        lockup = lockup if isinstance(lockup, dict) else {}

        def text(key, limit, lockup=lockup):
            value = lockup.get(key)
            return clean(value.get("text"))[:limit] if isinstance(value, dict) else ""

        degree = DEGREE.fullmatch(text("label", 20).lstrip("·• "))
        kind = reaction.get("reactionType")
        people.append(
            {
                "member": member,
                "name": text("title", 200),
                "headline": text("subtitle", 1000),
                "degree": degree[1] if degree else None,
                "reaction": kind if isinstance(kind, str) and REACTION.fullmatch(kind) else None,
            }
        )
    return people, paging["total"]


async def _sleep(gap, sleep):
    await sleep(_RANDOM.uniform(*gap))


async def _me(client, session, actor) -> str:
    me = await _get(client, session, "/voyager/api/me")
    if not identity_matches(me, actor):
        raise CollectionError("account_changed")
    return own_profile_id(me)


async def read_posts(
    session,
    actor,
    *,
    client,
    now: datetime,
    window_days: int = WINDOW_DAYS,
    limit: int = MAX_POSTS,
    gap=GAP_SECONDS,
    sleep=asyncio.sleep,
) -> dict:
    """The member's own posts from the last window_days, newest first, at most limit."""

    profile_id = await _me(client, session, actor)
    cutoff = now - timedelta(days=window_days)
    found, token, complete = {}, None, False
    for page in range(MAX_FEED_PAGES):
        await _sleep(gap, sleep)
        params = {
            "count": str(FEED_PAGE),
            "includeLongTermHistory": "true",
            "moduleKey": "member-shares:phone",
            "numComments": "0",
            "numLikes": "0",
            "profileUrn": f"urn:li:fsd_profile:{profile_id}",
            "q": "memberShareFeed",
            "start": str(page * FEED_PAGE),
        }
        if token:
            params["paginationToken"] = token
        payload = await _get(
            client,
            session,
            "/voyager/api/identity/profileUpdatesV2",
            params,
            request_headers=_headers(
                session,
                page="d_flagship3_profile_view_base",
                referer=f"{ORIGIN}/in/{quote(profile_id)}/recent-activity/all/",
            ),
        )
        posts, token, seen = own_posts(payload, profile_id)
        recent = [p for p in posts if datetime.fromisoformat(p["published_at"]) >= cutoff]
        for post in recent:
            found.setdefault(post["activity_urn"], post)
        # A pinned post can sit above older ones, so only a page with nothing recent ends it.
        if not seen or not token or (posts and not recent) or len(found) >= limit:
            complete = True
            break
    posts = sorted(found.values(), key=lambda p: p["published_at"], reverse=True)[:limit]
    return {"posts": posts, "complete": complete}


async def read_reactions(
    session,
    actor,
    *,
    client,
    activity_urn: str,
    thread_urn: str,
    start: int = 0,
    pages: int = REACTION_PAGES_PER_READ,
    gap=GAP_SECONDS,
    sleep=asyncio.sleep,
) -> dict:
    """Up to pages pages of one post's reactions from start; next_start says where to go on."""

    if not THREAD.fullmatch(thread_urn) or not ACTIVITY.fullmatch(activity_urn):
        raise CollectionError("unsupported_contract")
    if not isinstance(start, int) or start < 0 or start % REACTIONS_PAGE:
        raise CollectionError("unsupported_contract")
    profile_id = await _me(client, session, actor)
    people, total, position = [], None, start
    for _ in range(max(1, min(pages, REACTION_PAGES_PER_READ))):
        if position >= MAX_REACTIONS:
            break
        await _sleep(gap, sleep)
        payload = await _get(
            client,
            session,
            "/voyager/api/voyagerSocialDashReactions",
            {
                "count": str(REACTIONS_PAGE),
                "q": "reactionType",
                "start": str(position),
                "threadUrn": thread_urn,
            },
            request_headers=_headers(
                session,
                page="d_flagship3_detail_base",
                referer=f"{ORIGIN}/feed/update/{activity_urn}/",
            ),
        )
        found, total = reactions_page(payload, start=position, profile_id=profile_id)
        people.extend(found)
        position += REACTIONS_PAGE
        if position >= total:
            break
    more = total is not None and position < min(total, MAX_REACTIONS)
    return {
        "people": people,
        "total": total,
        "next_start": position if more else None,
        "capped": total is not None and total > MAX_REACTIONS,
    }
