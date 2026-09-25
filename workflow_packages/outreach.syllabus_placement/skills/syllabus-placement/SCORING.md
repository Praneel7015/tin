# Scoring and sequencing

Run this block exactly as written. Save the verified course records from Station 3 as a JSON
list, then call `plan(courses, as_of, max_courses, searches, opened)` and use its result for
the report. The ranking lives here so that two runs on the same evidence give the same plan.

The timing window is an assumption, kept in two constants: instructors settle next term's
tools between about four months and three weeks before it starts (bookstore adoption and
syllabus deadlines usually fall in that span). Courses are assumed to run once a year unless
the page gives a later start date; for courses that run every term, enter the next start.
A document dated more than two years before `as_of` is not evidence of a current course,
and a course only seen in a search snippet is not evidence of anything yet, including that
it already uses the product. The verdict is `fit` only when at least three courses make the
shortlist; one or two hands-on courses are `thin`. Courses already listed to contact in an
earlier run count toward the verdict: the channel is the same size on a rerun.

Run-to-run memory lives in the `tin-syllabus-state` block at the end of every report. Read the
block of every earlier report in the output folder, pass each parsed value to `read_state()`,
merge the trusted ones with `merge_states()` and pass the result to `plan()` as `previous`.
A course listed under `contact_now` is not listed there again until `REPEAT_AFTER_DAYS` have
passed (one yearly cycle); earlier `schedule` and `next_cycle` courses this run did not find
again are carried forward with their dates until the date passes.

```python
import json
from datetime import date, timedelta

WINDOW_OPENS_DAYS = 120
WINDOW_CLOSES_DAYS = 21
SOON_DAYS = 180
STALE_YEARS = 2
FIT_MIN_SHORTLIST = 3
REPEAT_AFTER_DAYS = 300
MAX_STATE_COURSES = 500

SLOT_POINTS = {
    "open": 40,
    "manual": 35,
    "incumbent_suggested": 25,
    "incumbent_required": 12,
    "own": 0,
    "none": 0,
}
TIMING_POINTS = {"open": 30, "soon": 20, "later": 10, "missed": 5, "unknown": 0}
CONTACT_POINTS = {"public_page": 10, "none": 0}
DECISION_ORDER = ["contact_now", "schedule", "next_cycle"]
HARD_NOS = (
    "no_cold_email",
    "no_paid_ads",
    "no_founder_posting",
    "no_discounting",
    "no_unbacked_claims",
)
REQUIRED = ("course", "institution", "url", "quote", "quote_source", "hands_on", "slot")


def _day(value, field):
    if not isinstance(value, str):
        raise ValueError(f"{field} must be YYYY-MM-DD")
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f"{field} must be YYYY-MM-DD") from error


def window(next_start, as_of):
    """Where today falls against the instructor's tool choice for the next offering."""
    today = _day(as_of, "as_of")
    if next_start is None:
        return {"status": "unknown", "send_on": None}
    start = _day(next_start, "next_start")
    opens = start - timedelta(days=WINDOW_OPENS_DAYS)
    closes = start - timedelta(days=WINDOW_CLOSES_DAYS)
    if today < opens:
        status = "soon" if (opens - today).days <= SOON_DAYS else "later"
        return {"status": status, "send_on": opens.isoformat()}
    if today <= closes:
        return {"status": "open", "send_on": today.isoformat()}
    following = start + timedelta(days=365) - timedelta(days=WINDOW_OPENS_DAYS)
    return {"status": "missed", "send_on": following.isoformat()}


def enrollment_points(enrollment):
    if enrollment is None:
        return 0
    if not isinstance(enrollment, int) or isinstance(enrollment, bool) or enrollment < 0:
        raise ValueError("enrollment must be a non-negative integer or null")
    if enrollment < 20:
        return 5
    if enrollment < 60:
        return 10
    if enrollment < 150:
        return 15
    return 20


def check(course):
    missing = [field for field in REQUIRED if field not in course]
    if missing:
        raise ValueError(f"course record is missing {', '.join(missing)}")
    for field in ("course", "institution", "quote"):
        if not isinstance(course[field], str) or not course[field].strip():
            raise ValueError(f"{field} must be non-empty text")
    if not isinstance(course["url"], str) or not course["url"].startswith(("https://", "http://")):
        raise ValueError("url must be the course document's web address")
    if course["quote_source"] not in {"document", "snippet"}:
        raise ValueError("quote_source must be document or snippet")
    if not isinstance(course["hands_on"], bool):
        raise ValueError("hands_on must be true or false")
    if course["slot"] not in SLOT_POINTS:
        raise ValueError(f"slot must be one of {', '.join(SLOT_POINTS)}")
    if course.get("contact", "none") not in CONTACT_POINTS:
        raise ValueError("contact must be public_page or none")
    year = course.get("document_year")
    if year is not None and (not isinstance(year, int) or isinstance(year, bool) or year < 1990):
        raise ValueError("document_year must be a year or null")


def score_course(course, as_of):
    check(course)
    timing = window(course.get("next_start"), as_of)
    contact = course.get("contact", "none")
    score = (
        SLOT_POINTS[course["slot"]]
        + TIMING_POINTS[timing["status"]]
        + enrollment_points(course.get("enrollment"))
        + CONTACT_POINTS[contact]
    )
    year = course.get("document_year")
    reason = ""
    if course["slot"] == "none" or not course["hands_on"]:
        decision, score, reason = "discard", 0, "students do not do the job in this course"
    elif course["quote_source"] != "document":
        decision, reason = "check_by_hand", "not verified from the course document"
    elif year is not None and year < _day(as_of, "as_of").year - STALE_YEARS:
        decision, reason = "check_by_hand", f"document is from {year}; find a current offering"
    elif course["slot"] == "own":
        decision, score = "already_teaching", 0
    elif timing["status"] == "unknown":
        decision, reason = "check_by_hand", "next start date not found"
    elif timing["status"] == "open" and contact != "public_page":
        decision, reason = "check_by_hand", "window is open but no public instructor page"
    elif timing["status"] == "open":
        decision = "contact_now"
    elif timing["status"] == "missed":
        decision = "next_cycle"
    else:
        decision = "schedule"
    return {
        **course,
        "window": timing["status"],
        "send_on": timing["send_on"],
        "score": score,
        "decision": decision,
        "reason": reason,
    }


def verdict(funnel):
    """Fit needs several courses to act on; one good course is a lead, not a channel."""
    if funnel["shortlisted"] + funnel.get("already_listed", 0) >= FIT_MIN_SHORTLIST:
        return "fit"
    if funnel["hands_on"] > 0:
        return "thin"
    return "not a fit"


def course_key(course):
    return f"{course['institution'].strip().lower()}|{course['course'].strip().lower()}"


def read_state(value):
    """Validate one earlier report's state block. Returns None when it cannot be trusted."""
    try:
        if not isinstance(value, dict) or value.get("version") != 1:
            return None
        rows = value.get("courses")
        if not isinstance(rows, dict) or len(rows) > MAX_STATE_COURSES:
            return None
        clean = {}
        for key, item in rows.items():
            if not isinstance(key, str) or not isinstance(item, dict):
                return None
            for field in ("course", "institution", "report"):
                if not isinstance(item.get(field), str) or not item[field].strip():
                    return None
            if item.get("decision") not in DECISION_ORDER:
                return None
            _day(item.get("listed_on"), "listed_on")
            if item.get("send_on") is not None:
                _day(item["send_on"], "send_on")
            clean[key] = {
                field: item.get(field)
                for field in ("course", "institution", "decision", "send_on", "listed_on", "report")
            }
        return {"version": 1, "courses": clean}
    except (AttributeError, TypeError, ValueError):
        return None


def merge_states(states):
    """Union trusted earlier states; the most recent listing of a course wins."""
    merged = {}
    for state in states:
        if state is None:
            continue
        for key, item in state["courses"].items():
            known = merged.get(key)
            if known is None or item["listed_on"] > known["listed_on"]:
                merged[key] = dict(item)
    return {"version": 1, "courses": merged}


def plan(
    courses,
    as_of,
    max_courses=15,
    searches=0,
    opened=0,
    previous=None,
    report_path="",
    hard_nos=(),
):
    if not isinstance(max_courses, int) or isinstance(max_courses, bool):
        raise ValueError("max_courses must be an integer")
    if not 5 <= max_courses <= 30:
        raise ValueError("max_courses must be 5-30")
    for item in hard_nos:
        if item not in HARD_NOS:
            raise ValueError(f"hard no must be one of {', '.join(HARD_NOS)}")
    today = _day(as_of, "as_of")
    earlier = (previous or {}).get("courses", {})
    seen, unique, duplicates, already_listed = set(), [], 0, []
    for course in courses:
        check(course)
        identity = course_key(course)
        if identity in seen:
            duplicates += 1
            continue
        seen.add(identity)
        row = score_course(course, as_of)
        prior = earlier.get(identity)
        if (
            row["decision"] == "contact_now"
            and prior is not None
            and prior["decision"] == "contact_now"
            and (today - _day(prior["listed_on"], "listed_on")).days < REPEAT_AFTER_DAYS
        ):
            row["reason"] = f"listed to contact on {prior['listed_on']} in {prior['report']}"
            already_listed.append(row)
            continue
        unique.append(row)

    def rank(row):
        return (DECISION_ORDER.index(row["decision"]), -row["score"], row["send_on"] or "")

    def by(decision):
        return [row for row in unique if row["decision"] == decision]

    eligible = sorted((row for row in unique if row["decision"] in DECISION_ORDER), key=rank)
    shortlist = eligible[:max_courses]
    recorded = unique + already_listed
    verified = [row for row in recorded if row["quote_source"] == "document"]
    funnel = {
        "searches": searches,
        "documents_opened": opened,
        "courses_recorded": len(recorded),
        "duplicates_dropped": duplicates,
        "verified_from_document": len(verified),
        "hands_on": sum(1 for row in verified if row["hands_on"] and row["slot"] != "none"),
        "shortlisted": len(shortlist),
        "contact_now": sum(1 for row in shortlist if row["decision"] == "contact_now"),
        "already_listed": len(already_listed),
    }
    carried = [
        dict(item, key=key)
        for key, item in sorted(earlier.items())
        if key not in seen
        and item["decision"] in ("schedule", "next_cycle")
        and item["send_on"] is not None
        and _day(item["send_on"], "send_on") >= today
    ]
    state = {key: dict(item) for key, item in earlier.items()}
    for row in shortlist:
        key = course_key(row)
        prior = state.get(key)
        kept = prior is not None and prior["decision"] == row["decision"] != "contact_now"
        state[key] = {
            "course": row["course"],
            "institution": row["institution"],
            "decision": row["decision"],
            "send_on": row["send_on"],
            "listed_on": prior["listed_on"] if kept else as_of,
            "report": prior["report"] if kept else report_path,
        }
    if len(state) > MAX_STATE_COURSES:
        newest = sorted(state.items(), key=lambda kv: kv[1]["listed_on"], reverse=True)
        state = dict(newest[:MAX_STATE_COURSES])
    return {
        "verdict": verdict(funnel),
        "shortlist": shortlist,
        "over_limit": eligible[max_courses:],
        "check_by_hand": by("check_by_hand"),
        "already_teaching": by("already_teaching"),
        "discarded": by("discard"),
        "already_listed": already_listed,
        "carried_forward": carried,
        "notes_allowed": "no_cold_email" not in hard_nos,
        "funnel": funnel,
        "state": {"version": 1, "courses": state},
    }


if __name__ == "__main__":
    import sys

    records = json.loads(open(sys.argv[1], encoding="utf-8").read())
    print(json.dumps(plan(records, sys.argv[2], *map(int, sys.argv[3:6])), indent=2))
```

Copy the block to a scratch file and import `plan`, `read_state` and `merge_states` from it.
Pass `previous` (the merged state), `report_path` (the declared output path of this run) and
`hard_nos` (the growth plan's hard no ids; `no cold email` is `no_cold_email`). The command line
`python3 score.py courses.json YYYY-MM-DD <max_courses> <searches> <opened>` has no memory and
is only for checking records by hand.
