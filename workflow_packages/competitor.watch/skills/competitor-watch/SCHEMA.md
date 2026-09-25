# Evidence schema and diff

Every report ends with one fenced `tin-competitor-watch` JSON block. It is the only history this
workflow has: the next run finds the newest valid block under `reports/competitor-watch/` and
diffs against it. Nothing else persists between runs.

Extract the single Python block below into a scratch module and use it unchanged. You decide the
evidence (what a page says, which page is pricing, whether a page actually rendered). This code
decides what counts as a change, which changes are material, what carries forward from an
earlier run, and the report status. Never diff by hand.

## What each field means

- `id`: the competitor's host without `www.` (`linear.app`). Pages on other hosts belong to
  whichever competitor links to them; do not create a second competitor for a docs subdomain.
- `source`: where the competitor came from, one of `SOURCES`. `input` is the founder's own list.
- `pages[]`: every page you tried, with `kind` (`pricing`, `changelog`, `product`) and `status`:
  `read` (you saw the actual content), `empty` (the page loaded but held no pricing or entries,
  typically a JavaScript-rendered shell), `blocked` (bot wall, login, paywall), `not_found`, or
  `error`. Only a `read` page supplies data.
- `pricing`: the normalized extraction from a `read` pricing page, or `None` when no pricing page
  was read this run. `has_public_pricing: false` means the page was read and shows only "contact
  us". `price_monthly` is the list price per billing unit per month; `None` means no price is
  shown for that tier. `price_annual_monthly_equivalent` is the annual price divided by twelve.
  `seat_minimum`, `usage_limits`, `cta_text` and `highlighted_features` are what the page says.
  A read pricing page always names at least one plan, even a sales-only "Enterprise"; a page
  with no plan at all is `empty`, never "pricing removed".
- `changelog`: up to ten newest visible entries (`date` as `YYYY-MM-DD` or `None`, `title`) from a
  `read` changelog, or `None` when none was read this run.
- `pricing_checked_at` / `changelog_checked_at`: when that data was actually read. When a page
  could not be read this run, `next_evidence` carries the earlier data forward with its original
  date, so an unreadable page never looks like a removed plan.

Material changes (these can make a week non-quiet): public pricing appearing or disappearing, a
tier added or removed, a price change, a seat minimum change, a usage limit whose numbers
changed, a free-trial change, a feature moved between tiers, and a call to action switching
between self-serve and sales. Everything else is listed under "Also seen" and never produces a
suggested response: reworded limits with the same numbers, a feature added to or dropped from a
tier's highlights, cosmetic call-to-action copy, and new changelog entries. `promote` may raise a
changelog entry or a newly highlighted feature to material, only with a stated reason: it matches
`watch_for`, or the Feature map shows the project lacks that capability.

A tier rename shows up as one tier removed and one added. Say so in the report when the prices
and limits match; do not hide it.

```python
import json
import re
from datetime import datetime

VERSION = 1
FENCE = "tin-competitor-watch"
SOURCES = (
    "input",
    "previous_watch",
    "onboarding_plan",
    "wiki",
    "keyword_plan",
    "ads_assessment",
)
PAGE_KINDS = ("pricing", "changelog", "product")
PAGE_STATUSES = ("read", "empty", "blocked", "not_found", "error")
LIMITS = {"competitors": 5, "pages": 4, "tiers": 8, "features": 6, "changelog": 10, "text": 200}
PRICE_EPSILON = 0.005
MATERIAL_KINDS = (
    "public_pricing",
    "tier_added",
    "tier_removed",
    "price",
    "seat_minimum",
    "usage_limits",
    "free_trial",
    "feature_moved",
    "sales_motion",
)
PROMOTABLE_KINDS = ("changelog_new", "feature_added")
SALES_WORDS = ("contact", "demo", "sales", "talk to", "call", "quote")
_FENCE = re.compile(r"^```" + FENCE + r"[ \t]*\n(.*?)\n```[ \t]*$", re.S | re.M)
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _text(value, name, *, optional=False, limit=None):
    if value is None and optional:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be non-empty text")
    value = " ".join(value.split())
    if len(value) > (limit or LIMITS["text"]):
        raise ValueError(f"{name} is too long")
    return value


def _choice(value, allowed, name):
    if value not in allowed:
        raise ValueError(f"{name} must be one of {', '.join(allowed)}")
    return value


def _flag(value, name):
    if value is not None and not isinstance(value, bool):
        raise ValueError(f"{name} must be true, false or null")
    return value


def _whole(value, name, low, high):
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise ValueError(f"{name} must be a whole number from {low} to {high}")
    return value


def _money(value, name):
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value < 1e6:
        raise ValueError(f"{name} must be a non-negative number or null")
    return round(float(value), 2)


def _timestamp(value, name):
    text = _text(value, name, limit=40)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError(f"{name} must be an ISO-8601 timestamp") from None
    if parsed.tzinfo is None:
        raise ValueError(f"{name} must carry a timezone")
    return text


def _key(value):
    return " ".join(value.casefold().split())


def _tier(value):
    if not isinstance(value, dict):
        raise ValueError("tier must be an object")
    features = value.get("highlighted_features") or []
    if not isinstance(features, list) or len(features) > LIMITS["features"]:
        raise ValueError("highlighted_features must be a short list")
    return {
        "name": _text(value.get("name"), "tier name", limit=80),
        "price_monthly": _money(value.get("price_monthly"), "price_monthly"),
        "price_annual_monthly_equivalent": _money(
            value.get("price_annual_monthly_equivalent"), "price_annual_monthly_equivalent"
        ),
        "billing_unit": _text(value.get("billing_unit"), "billing_unit", optional=True, limit=40),
        "seat_minimum": _whole(value.get("seat_minimum"), "seat_minimum", 1, 100_000),
        "cta_text": _text(value.get("cta_text"), "cta_text", optional=True, limit=60),
        "highlighted_features": [_text(f, "feature", limit=80) for f in features],
        "usage_limits": _text(value.get("usage_limits"), "usage_limits", optional=True),
    }


def _pricing(value):
    if value is None:
        return None
    if not isinstance(value, dict) or not isinstance(value.get("has_public_pricing"), bool):
        raise ValueError("pricing needs has_public_pricing")
    trial = value.get("free_trial") or {}
    if not isinstance(trial, dict):
        raise ValueError("free_trial must be an object")
    tiers = value.get("tiers")
    if not isinstance(tiers, list) or not 1 <= len(tiers) <= LIMITS["tiers"]:
        raise ValueError("a read pricing page names 1 to 8 plans; otherwise its status is empty")
    tiers = [_tier(t) for t in tiers]
    if len({_key(t["name"]) for t in tiers}) != len(tiers):
        raise ValueError("tier names must be distinct")
    if value["has_public_pricing"] and not any(t["price_monthly"] is not None for t in tiers):
        raise ValueError("public pricing needs at least one priced tier")
    return {
        "has_public_pricing": value["has_public_pricing"],
        "currency": _text(value.get("currency"), "currency", optional=True, limit=10),
        "free_trial": {
            "available": _flag(trial.get("available"), "free_trial.available"),
            "days": _whole(trial.get("days"), "free_trial.days", 1, 366),
            "credit_card_required": _flag(
                trial.get("credit_card_required"), "free_trial.credit_card_required"
            ),
        },
        "tiers": tiers,
    }


def _changelog(value):
    if value is None:
        return None
    if not isinstance(value, list) or len(value) > LIMITS["changelog"]:
        raise ValueError("changelog must be a bounded list")
    entries = []
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("changelog entry must be an object")
        date = item.get("date")
        if date is not None and not (isinstance(date, str) and _DATE.fullmatch(date)):
            raise ValueError("changelog date must be YYYY-MM-DD or null")
        entries.append({"date": date, "title": _text(item.get("title"), "changelog title")})
    return entries


def _competitor(value):
    if not isinstance(value, dict):
        raise ValueError("competitor must be an object")
    ident = _text(value.get("id"), "competitor id", limit=253).casefold().removeprefix("www.")
    if "/" in ident or " " in ident or "." not in ident:
        raise ValueError("competitor id must be a bare host")
    pages = value.get("pages")
    if not isinstance(pages, list) or not 1 <= len(pages) <= LIMITS["pages"]:
        raise ValueError("pages must list 1 to 4 attempted pages")
    clean_pages = []
    for page in pages:
        if not isinstance(page, dict):
            raise ValueError("page must be an object")
        url = _text(page.get("url"), "page url", limit=500)
        if not url.startswith(("https://", "http://")):
            raise ValueError("page url must be http(s)")
        clean_pages.append(
            {
                "url": url,
                "kind": _choice(page.get("kind"), PAGE_KINDS, "page kind"),
                "status": _choice(page.get("status"), PAGE_STATUSES, "page status"),
            }
        )
    pricing = _pricing(value.get("pricing"))
    changelog = _changelog(value.get("changelog"))
    return {
        "id": ident,
        "name": _text(value.get("name"), "competitor name", limit=120),
        "source": _choice(value.get("source"), SOURCES, "source"),
        "pages": clean_pages,
        "pricing": pricing,
        "pricing_checked_at": (
            _timestamp(value.get("pricing_checked_at"), "pricing_checked_at")
            if pricing is not None
            else None
        ),
        "changelog": changelog,
        "changelog_checked_at": (
            _timestamp(value.get("changelog_checked_at"), "changelog_checked_at")
            if changelog is not None
            else None
        ),
    }


def validate(evidence):
    """Normalize one evidence object. Raises ValueError when it breaks the contract."""
    if not isinstance(evidence, dict) or evidence.get("version") != VERSION:
        raise ValueError("evidence must be a version 1 object")
    competitors = evidence.get("competitors")
    if not isinstance(competitors, list) or not 1 <= len(competitors) <= LIMITS["competitors"]:
        raise ValueError("evidence must hold 1 to 5 competitors")
    clean = [_competitor(c) for c in competitors]
    if len({c["id"] for c in clean}) != len(clean):
        raise ValueError("competitor ids must be distinct")
    return {
        "version": VERSION,
        "checked_at": _timestamp(evidence.get("checked_at"), "checked_at"),
        "competitors": clean,
    }


def read_evidence(report_text):
    """The validated evidence of one earlier report, or None when it cannot be trusted."""
    if not isinstance(report_text, str):
        return None
    blocks = _FENCE.findall(report_text)
    if len(blocks) != 1:
        return None
    try:
        return validate(json.loads(blocks[0]))
    except (ValueError, TypeError, AttributeError):
        return None


def latest(reports):
    """Pick the newest trustworthy evidence from {path: text}. Returns (path, evidence, skipped).

    Report paths carry run ids, not dates, so order comes from `checked_at` in the block.
    `skipped` lists paths whose evidence block was missing or malformed.
    """
    best, skipped = (None, None), []
    for path in sorted(reports):
        evidence = read_evidence(reports[path])
        if evidence is None:
            skipped.append(path)
            continue
        when = datetime.fromisoformat(evidence["checked_at"].replace("Z", "+00:00"))
        if best[1] is None or when > best[2]:
            best = (path, evidence, when)
    return (best[0], best[1], skipped) if best[1] is not None else (None, None, skipped)


def _numbers(text):
    return sorted(re.findall(r"\d+(?:[.,]\d+)?", text or ""))


def _sales(cta):
    return any(word in (cta or "").casefold() for word in SALES_WORDS)


def _change(competitor, kind, subject, before, after):
    return {
        "competitor": competitor,
        "kind": kind,
        "subject": subject,
        "before": before,
        "after": after,
        "material": kind in MATERIAL_KINDS,
        "reason": None,
    }


def _pricing_changes(ident, old, new):
    changes = []
    if old["has_public_pricing"] != new["has_public_pricing"]:
        changes.append(
            _change(
                ident,
                "public_pricing",
                "pricing page",
                old["has_public_pricing"],
                new["has_public_pricing"],
            )
        )
    same_currency = old["currency"] == new["currency"] or None in (old["currency"], new["currency"])
    if not same_currency:
        changes.append(_change(ident, "currency", "pricing page", old["currency"], new["currency"]))
    for field in ("available", "days", "credit_card_required"):
        a, b = old["free_trial"][field], new["free_trial"][field]
        if a is not None and b is not None and a != b:
            changes.append(_change(ident, "free_trial", field, a, b))
    before = {_key(t["name"]): t for t in old["tiers"]}
    after = {_key(t["name"]): t for t in new["tiers"]}
    for key in before.keys() - after.keys():
        changes.append(
            _change(ident, "tier_removed", before[key]["name"], before[key]["price_monthly"], None)
        )
    for key in after.keys() - before.keys():
        changes.append(
            _change(ident, "tier_added", after[key]["name"], None, after[key]["price_monthly"])
        )
    added, removed = {}, {}
    for key in sorted(before.keys() & after.keys()):
        a, b, name = before[key], after[key], after[key]["name"]
        if same_currency:
            for field in ("price_monthly", "price_annual_monthly_equivalent"):
                x, y = a[field], b[field]
                if (x is None) != (y is None) or (x is not None and abs(x - y) > PRICE_EPSILON):
                    changes.append(_change(ident, "price", f"{name} {field}", x, y))
        if a["seat_minimum"] != b["seat_minimum"]:
            changes.append(
                _change(ident, "seat_minimum", name, a["seat_minimum"], b["seat_minimum"])
            )
        if _key(a["usage_limits"] or "") != _key(b["usage_limits"] or ""):
            kind = (
                "usage_limits"
                if _numbers(a["usage_limits"]) != _numbers(b["usage_limits"])
                else "copy"
            )
            changes.append(
                _change(ident, kind, f"{name} limits", a["usage_limits"], b["usage_limits"])
            )
        if _key(a["cta_text"] or "") != _key(b["cta_text"] or ""):
            kind = "sales_motion" if _sales(a["cta_text"]) != _sales(b["cta_text"]) else "copy"
            changes.append(
                _change(ident, kind, f"{name} call to action", a["cta_text"], b["cta_text"])
            )
        old_features = {_key(f): f for f in a["highlighted_features"]}
        new_features = {_key(f): f for f in b["highlighted_features"]}
        for f in new_features.keys() - old_features.keys():
            added[f] = (name, new_features[f])
        for f in old_features.keys() - new_features.keys():
            removed[f] = (name, old_features[f])
    for f in sorted(added.keys() & removed.keys()):
        changes.append(_change(ident, "feature_moved", added[f][1], removed[f][0], added[f][0]))
    for f in sorted(added.keys() - removed.keys()):
        changes.append(_change(ident, "feature_added", added[f][1], None, added[f][0]))
    for f in sorted(removed.keys() - added.keys()):
        changes.append(_change(ident, "feature_removed", removed[f][1], removed[f][0], None))
    return changes


def diff(previous, current):
    """Changes for one competitor. `previous` may be None (first check: no changes).

    Sections that were not read this run (`None`) are never compared, so an unreadable page
    cannot report a removed plan. Returns (changes, not_compared).
    """
    if previous is None:
        return [], []
    changes, not_compared = [], []
    ident = current["id"]
    if current["pricing"] is None:
        not_compared.append("pricing")
    elif previous["pricing"] is not None:
        changes += _pricing_changes(ident, previous["pricing"], current["pricing"])
    if current["changelog"] is None:
        not_compared.append("changelog")
    elif previous["changelog"] is not None:
        seen = {(e["date"], _key(e["title"])) for e in previous["changelog"]}
        newest = max((e["date"] for e in previous["changelog"] if e["date"]), default=None)
        for entry in current["changelog"]:
            if (entry["date"], _key(entry["title"])) in seen:
                continue
            if entry["date"] and newest and entry["date"] <= newest:
                continue  # older entry that scrolled into view, not news
            changes.append(_change(ident, "changelog_new", entry["title"], None, entry["date"]))
    return changes, not_compared


def promote(change, reason):
    """Raise a changelog entry or newly highlighted feature to material, with a stated reason."""
    if change["kind"] not in PROMOTABLE_KINDS:
        raise ValueError("only changelog entries and newly highlighted features can be promoted")
    return {**change, "material": True, "reason": _text(reason, "reason")}


def next_evidence(previous, current, checked_at):
    """This run's evidence block. Unread sections carry forward with their original date."""
    checked_at = _timestamp(checked_at, "checked_at")
    before = {c["id"]: c for c in (previous or {}).get("competitors", [])}
    competitors = []
    for item in current:
        item = dict(item)
        old = before.get(str(item.get("id", "")).casefold().removeprefix("www."))
        for section in ("pricing", "changelog"):
            stamp = f"{section}_checked_at"
            if item.get(section) is not None:
                item[stamp] = checked_at
            elif old is not None and old[section] is not None:
                item[section], item[stamp] = old[section], old[stamp]
            else:
                item[stamp] = None
        competitors.append(item)
    return validate({"version": VERSION, "checked_at": checked_at, "competitors": competitors})


def status(previous, changes, competitors_known):
    """`diagnostic`, `baseline`, `changes` or `no-change` for the report's Status line."""
    if not competitors_known:
        return "diagnostic"
    if previous is None:
        return "baseline"
    return "changes" if any(c["material"] for c in changes) else "no-change"


def fence(evidence):
    """The exact block to paste at the end of the report."""
    body = json.dumps(validate(evidence), ensure_ascii=False, separators=(",", ":"))
    return f"```{FENCE}\n{body}\n```"
```
