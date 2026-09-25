# Ranking, exclusions and run-to-run memory

Extract the single Python block below into a scratch module and use it unchanged. You decide the
evidence for each venue (its call, deadline, requirements, route and fit); this code decides what
is excluded and why, the order, the verdict, and which venues later runs must not pitch again.
Never rank or exclude by hand.

## Venue records

One record per candidate you verified or rejected, with these fields:

- `name`: the venue's own name, without the year (`PyCon US`, not `PyCon US 2027`).
- `url`: the venue's own CFP, apply or guest page (`https://...`).
- `format`: `conference_talk`, `meetup_talk` or `podcast_guest`.
- `deadline`: the closing date as `YYYY-MM-DD` from the venue's own page, or `null` for a
  rolling venue.
- `edition`: the year of the event the call is for, or `null`. A dated call without one uses its
  deadline's year. Next year's call of the same conference is a new edition and may be pitched.
- `open_verified`: true only when the venue's own page shows the call is open now (or, for a
  rolling venue, recent activity shows it still takes pitches).
- `requirements_confirmed`: true only when the length limits, bio, sample and submission
  mechanism were read on the venue's own page.
- `route`: `form` (a CFP, apply or guest form), `published_address` (the venue's own page asks
  for pitches at a stated address), or `direct_message` (no stated intake: writing to a host or
  organiser unprompted, which is cold outreach).
- `fit`: 3 when the venue's stated theme or recent talks/episodes match the pitch closely, 2 when
  they overlap, 1 when the link is loose.

## Memory between runs

Every report ends with a `tin-speaking-state` block. Read the block of every earlier report in
the output folder, pass each parsed value to `read_state()`, and merge the trusted ones with
`merge_states()`. A block that fails `read_state()` is ignored, and the report says so.

```python
import re
import unicodedata
from datetime import date

FORMATS = ("conference_talk", "meetup_talk", "podcast_guest")
PREFERENCES = ("no_preference",) + FORMATS
ROUTES = ("form", "published_address", "direct_message")
HARD_NOS = (
    "no_cold_email",
    "no_paid_ads",
    "no_founder_posting",
    "no_discounting",
    "no_unbacked_claims",
)
FIT_MIN_SHORTLIST = 3
MAX_STATE_VENUES = 500
REQUIRED = (
    "name",
    "url",
    "format",
    "deadline",
    "open_verified",
    "requirements_confirmed",
    "route",
    "fit",
)


def _day(value, field):
    if not isinstance(value, str):
        raise ValueError(f"{field} must be YYYY-MM-DD")
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f"{field} must be YYYY-MM-DD") from error


def slug(name):
    """Normalise a venue name for matching: case, accents, punctuation and a trailing year."""
    if not isinstance(name, str) or not name.strip():
        raise ValueError("name must be non-empty text")
    text = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    text = re.sub(r"[^a-z0-9]+", " ", text).strip()
    text = re.sub(r"\s+(19|20)\d{2}$", "", text)
    if not text:
        raise ValueError("name must contain letters or digits")
    return text


def venue_key(venue):
    """A rolling venue is one target; a dated call is one target per edition."""
    if venue["deadline"] is None and venue.get("edition") is None:
        return slug(venue["name"])
    edition = venue.get("edition") or _day(venue["deadline"], "deadline").year
    return f"{slug(venue['name'])}@{edition}"


def check(venue):
    missing = [field for field in REQUIRED if field not in venue]
    if missing:
        raise ValueError(f"venue record is missing {', '.join(missing)}")
    slug(venue["name"])
    if not isinstance(venue["url"], str) or not venue["url"].startswith(("https://", "http://")):
        raise ValueError("url must be the venue's own page")
    if venue["format"] not in FORMATS:
        raise ValueError(f"format must be one of {', '.join(FORMATS)}")
    if venue["deadline"] is not None:
        _day(venue["deadline"], "deadline")
    edition = venue.get("edition")
    if edition is not None and (
        not isinstance(edition, int) or isinstance(edition, bool) or edition < 2000
    ):
        raise ValueError("edition must be a year or null")
    for field in ("open_verified", "requirements_confirmed"):
        if not isinstance(venue[field], bool):
            raise ValueError(f"{field} must be true or false")
    if venue["route"] not in ROUTES:
        raise ValueError(f"route must be one of {', '.join(ROUTES)}")
    fit = venue["fit"]
    if isinstance(fit, bool) or not isinstance(fit, int) or not 1 <= fit <= 3:
        raise ValueError("fit must be 1, 2 or 3")


def read_state(value):
    """Validate one earlier report's state block. Returns None when it cannot be trusted."""
    try:
        if not isinstance(value, dict) or value.get("version") != 1:
            return None
        venues = value.get("venues")
        if not isinstance(venues, dict) or len(venues) > MAX_STATE_VENUES:
            return None
        clean = {}
        for key, item in venues.items():
            if not isinstance(key, str) or not key.strip() or not isinstance(item, dict):
                return None
            name = item.get("name")
            slug(name)
            if item.get("format") not in FORMATS:
                return None
            _day(item.get("first_drafted"), "first_drafted")
            report = item.get("report")
            if not isinstance(report, str) or not report.strip():
                return None
            clean[key] = {
                "name": name,
                "format": item["format"],
                "first_drafted": item["first_drafted"],
                "report": report,
            }
        return {"version": 1, "venues": clean}
    except (AttributeError, TypeError, ValueError):
        return None


def merge_states(states):
    """Union trusted earlier states; a venue keeps the report that first drafted it."""
    merged = {}
    for state in states:
        if state is None:
            continue
        for key, item in state["venues"].items():
            known = merged.get(key)
            if known is None or item["first_drafted"] < known["first_drafted"]:
                merged[key] = dict(item)
    return {"version": 1, "venues": merged}


def plan(
    venues,
    as_of,
    max_venues=10,
    format_preference="no_preference",
    already_pitched=(),
    previous=None,
    hard_nos=(),
    report_path="",
):
    """Exclude, rank and cap verified venues; return the shortlist, exclusions and next state."""
    today = _day(as_of, "as_of")
    if isinstance(max_venues, bool) or not isinstance(max_venues, int) or not 3 <= max_venues <= 20:
        raise ValueError("max_venues must be 3-20")
    if format_preference not in PREFERENCES:
        raise ValueError(f"format_preference must be one of {', '.join(PREFERENCES)}")
    for item in hard_nos:
        if item not in HARD_NOS:
            raise ValueError(f"hard no must be one of {', '.join(HARD_NOS)}")
    skipped = {slug(name) for name in already_pitched if isinstance(name, str) and name.strip()}
    earlier = (previous or {}).get("venues", {})
    seen, eligible, excluded, duplicates = set(), [], [], 0
    for venue in venues:
        check(venue)
        key = venue_key(venue)
        if key in seen:
            duplicates += 1
            continue
        seen.add(key)
        row = dict(venue, key=key)
        reason = ""
        if format_preference != "no_preference" and venue["format"] != format_preference:
            reason = f"format: {venue['format']} was not requested"
        elif not venue["open_verified"]:
            reason = "open call not verified on the venue's own page"
        elif not venue["requirements_confirmed"]:
            reason = "submission requirements not confirmed on the venue's own page"
        elif venue["deadline"] is not None and _day(venue["deadline"], "deadline") < today:
            reason = "deadline has passed"
        elif slug(venue["name"]) in skipped:
            reason = "named in already_pitched"
        elif key in earlier:
            prior = earlier[key]
            reason = f"pitch drafted on {prior['first_drafted']} in {prior['report']}"
        elif venue["route"] == "direct_message" and "no_cold_email" in hard_nos:
            reason = "hard no: no cold email (no stated intake for pitches)"
        if reason:
            excluded.append(dict(row, reason=reason))
        else:
            eligible.append(row)

    def rank(row):
        rolling = row["deadline"] is None
        return (rolling, row["deadline"] or "", -row["fit"], slug(row["name"]))

    eligible.sort(key=rank)
    shortlist = eligible[:max_venues]
    for row in eligible[max_venues:]:
        excluded.append(dict(row, reason="over max_venues; eligible next run"))
    count = len(shortlist)
    verdict = "fit" if count >= FIT_MIN_SHORTLIST else "thin" if count else "not a fit"
    state = {key: dict(item) for key, item in earlier.items()}
    for row in shortlist:
        state[row["key"]] = {
            "name": row["name"],
            "format": row["format"],
            "first_drafted": as_of,
            "report": report_path,
        }
    if len(state) > MAX_STATE_VENUES:
        newest = sorted(state.items(), key=lambda kv: kv[1]["first_drafted"], reverse=True)
        state = dict(newest[:MAX_STATE_VENUES])
    return {
        "status": "complete" if count else "no venues verified",
        "verdict": verdict,
        "shortlist": shortlist,
        "excluded": excluded,
        "duplicates_dropped": duplicates,
        "state": {"version": 1, "venues": state},
    }
```

Pass `already_pitched` as a list of the names in the input (split on commas and new lines),
`hard_nos` as the ids of the hard no's the growth plan records (`no cold email` is
`no_cold_email`), and `report_path` as the declared output path of this run.
