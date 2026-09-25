# Scoring and checks

Extract the single Python block below into a scratch module and use it unchanged. The model
decides the evidence (shape, presence, gate results, audience fit); this code decides the order,
the picks, whether copy fits a field, and what changed since the last run. Never rank by hand.

## What each input means

- `shape`: how the product touches the partner. Only `user_authorized` (the partner's users grant
  the product access, or install it) and `distributed_artifact` (the product ships something the
  store distributes, such as an extension or an MCP server) are storefronts. `vendor_side`
  (the product is the partner's customer: billing, email delivery, hosting, models),
  `outbound_only` (posts to a URL or key the customer pastes) and `declared_only` (in the
  manifest, no call site) are reported and never picked.
- `presence`: `listed` (a listing URL was opened), `absent` (the marketplace search and a domain
  search both ran and neither found it), `unknown` (a lookup failed or was ambiguous). Only
  `absent` can be picked; `unknown` is rechecked next run.
- `audience`: 3 when the Code map or Feature map shows the product's buyers work inside this
  partner every day, 2 when some do, 1 when the link is incidental. Cite the memory line.
- `competitors_listed`: named competitors or same-category products found listed in this
  marketplace, capped at 3. It is evidence that buyers shop for this kind of product there.
- `gates`: one entry per hard gate in MARKETPLACES.md, with `status` `pass`, `fail` or `unknown`
  and the gate's `size`. Cite the page or file behind each pass or fail.
- `effort` and `review_days`: from MARKETPLACES.md. Unknown review time is `None`.

Readiness: any large gate that fails is `blocked`; all gates pass is `ready`; a large gate that
is unknown (install counts, for example) is `confirm`, meaning the founder must confirm it before
submitting; anything else is `fix_first`, meaning small fixes stand between the product and a
listing.

Score = audience x (1 + competitors listed) x readiness weight / effort, with weights ready 3,
fix_first 2, confirm 1. Ties go to the shorter review, then the marketplace id.

Memory: every report ends with a `tin-listings-state` block. Read the block of every earlier
report in the output folder, pass each to `read_state()`, fold them with `merge_states()` and
pass the result to `pick()` and `next_state()` as `previous`. A marketplace an earlier run
recommended that is still not listed is not recommended again; it is reported as waiting on the
founder, with the date and report that hold its packet.

```python
from datetime import date

MARKETPLACES = (
    "slack",
    "github",
    "google_workspace",
    "zapier",
    "hubspot",
    "shopify",
    "notion",
    "stripe",
    "vercel",
    "chrome",
    "mcp_registry",
)
SHAPES = (
    "user_authorized",
    "distributed_artifact",
    "vendor_side",
    "outbound_only",
    "declared_only",
)
STOREFRONT_SHAPES = ("user_authorized", "distributed_artifact")
PRESENCE = ("listed", "absent", "unknown")
GATE_STATUS = ("pass", "fail", "unknown")
GATE_SIZE = ("small", "large")
READINESS_WEIGHT = {"ready": 3, "fix_first": 2, "confirm": 1, "blocked": 0}
MAX_COMPETITORS = 3
NO_REVIEW_TIME = 10_000


def _choice(value, allowed, name):
    if value not in allowed:
        raise ValueError(f"{name} must be one of {', '.join(allowed)}")
    return value


def _whole(value, name, low, high):
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise ValueError(f"{name} must be a whole number from {low} to {high}")
    return value


def readiness(gates):
    """Classify one marketplace from its hard gates."""
    if not isinstance(gates, list) or not gates:
        raise ValueError("gates must be a non-empty list")
    for gate in gates:
        if not isinstance(gate, dict) or not str(gate.get("rule", "")).strip():
            raise ValueError("every gate needs a rule")
        _choice(gate.get("status"), GATE_STATUS, "gate status")
        _choice(gate.get("size"), GATE_SIZE, "gate size")
    if any(g["status"] == "fail" and g["size"] == "large" for g in gates):
        return "blocked"
    if all(g["status"] == "pass" for g in gates):
        return "ready"
    if any(g["status"] == "unknown" and g["size"] == "large" for g in gates):
        return "confirm"
    return "fix_first"


def score(row):
    """Return the row with readiness, score and a one-line reason. Score None means not picked."""
    marketplace = _choice(row.get("marketplace"), MARKETPLACES, "marketplace")
    shape = _choice(row.get("shape"), SHAPES, "shape")
    presence = _choice(row.get("presence"), PRESENCE, "presence")
    audience = _whole(row.get("audience"), "audience", 1, 3)
    competitors = _whole(row.get("competitors_listed"), "competitors_listed", 0, 1000)
    effort = _whole(row.get("effort"), "effort", 1, 3)
    review_days = row.get("review_days")
    if review_days is not None:
        _whole(review_days, "review_days", 0, 1000)
    state = readiness(row.get("gates"))
    result = dict(row, marketplace=marketplace, readiness=state, score=None)
    if shape not in STOREFRONT_SHAPES:
        result["reason"] = f"not a storefront: {shape.replace('_', ' ')}"
    elif presence == "listed":
        result["reason"] = "already listed"
    elif presence == "unknown":
        result["reason"] = "presence unknown; recheck next run"
    elif state == "blocked":
        result["reason"] = "blocked by a large gate"
    else:
        value = audience * (1 + min(competitors, MAX_COMPETITORS)) * READINESS_WEIGHT[state]
        result["score"] = round(value / effort, 2)
        result["reason"] = state.replace("_", " ")
    return result


def pick(rows, max_picks, skip=(), previous=None):
    """Rank scored rows and return (picks, ranked). Skipped marketplaces are never picked.

    A marketplace an earlier run already recommended, and that is still not listed, is not
    recommended again: its packet is in the earlier report and it waits on the founder.
    """
    _whole(max_picks, "max_picks", 1, 3)
    skipped = {_choice(item, MARKETPLACES, "skip") for item in skip}
    before = (previous or {}).get("rows", {})
    scored = []
    for row in rows:
        result = score(row)
        prior = before.get(result["marketplace"])
        if result["score"] is not None and prior and prior["picked_runs"] > 0:
            where = prior.get("picked_in") or "an earlier report"
            when = prior.get("picked_on") or "an earlier run"
            result["waiting"] = True
            result["reason"] = f"recommended on {when} in {where}; waiting on you"
        scored.append(result)
    seen = set()
    for row in scored:
        if row["marketplace"] in seen:
            raise ValueError(f"marketplace {row['marketplace']} appears twice")
        seen.add(row["marketplace"])
    ranked = sorted(
        scored,
        key=lambda r: (
            r["score"] is None,
            -(r["score"] or 0),
            NO_REVIEW_TIME if r.get("review_days") is None else r["review_days"],
            r["marketplace"],
        ),
    )
    picks = [
        r
        for r in ranked
        if r["score"] is not None and r["marketplace"] not in skipped and not r.get("waiting")
    ]
    return picks[:max_picks], ranked


def fit(text, limit):
    """Check copy against a field limit. Never truncates: rewrite the copy when ok is False."""
    if not isinstance(text, str) or not text.strip():
        raise ValueError("copy must be non-empty text")
    if limit is not None:
        _whole(limit, "limit", 1, 100_000)
    chars = len(text)
    return {"chars": chars, "limit": limit, "ok": limit is None or chars <= limit}


def _day(value, name):
    if not isinstance(value, str) or len(value) != 10:
        raise ValueError(f"{name} must be YYYY-MM-DD")
    date.fromisoformat(value)
    return value


def read_state(value):
    """Validate an earlier run's state block. Returns None when it cannot be trusted."""
    try:
        if not isinstance(value, dict) or value.get("version") != 1:
            return None
        rows = value.get("rows")
        if not isinstance(rows, dict) or len(rows) > len(MARKETPLACES):
            return None
        clean = {}
        for marketplace, item in rows.items():
            _choice(marketplace, MARKETPLACES, "marketplace")
            _choice(item.get("presence"), PRESENCE, "presence")
            clean[marketplace] = {
                "presence": item["presence"],
                "picked_runs": _whole(item.get("picked_runs", 0), "picked_runs", 0, 1000),
            }
            if item.get("picked_on") is not None:
                clean[marketplace]["picked_on"] = _day(item["picked_on"], "picked_on")
            if item.get("picked_in") is not None:
                if not isinstance(item["picked_in"], str) or not item["picked_in"].strip():
                    raise ValueError("picked_in must be a report path")
                clean[marketplace]["picked_in"] = item["picked_in"]
        state = {"version": 1, "rows": clean}
        if value.get("checked") is not None:
            state["checked"] = _day(value["checked"], "checked")
        return state
    except (AttributeError, TypeError, ValueError):
        return None


def merge_states(states):
    """Fold every trusted earlier state into one, oldest first.

    Presence comes from the latest check; a marketplace keeps the earliest report that
    recommended it and the highest recommendation count.
    """
    trusted = sorted((s for s in states if s), key=lambda s: s.get("checked", ""))
    if not trusted:
        return None
    rows = {}
    for state in trusted:
        for marketplace, item in state["rows"].items():
            known = rows.get(marketplace)
            if known is None:
                rows[marketplace] = dict(item)
                continue
            known["presence"] = item["presence"]
            known["picked_runs"] = max(known["picked_runs"], item["picked_runs"])
            for field in ("picked_on", "picked_in"):
                if field not in known and field in item:
                    known[field] = item[field]
    merged = {"version": 1, "rows": rows}
    if trusted[-1].get("checked"):
        merged["checked"] = trusted[-1]["checked"]
    return merged


def next_state(previous, ranked, picks, checked=None, report=None):
    """Build this run's state block and the changes since the previous run."""
    before = (previous or {}).get("rows", {})
    picked = {r["marketplace"] for r in picks}
    rows, went_live, still_waiting, new = {}, [], [], []
    for row in ranked:
        marketplace = row["marketplace"]
        prior = before.get(marketplace)
        runs = (prior["picked_runs"] if prior else 0) + (1 if marketplace in picked else 0)
        rows[marketplace] = {"presence": row["presence"], "picked_runs": runs}
        for field in ("picked_on", "picked_in"):
            if prior and field in prior:
                rows[marketplace][field] = prior[field]
        if marketplace in picked and "picked_on" not in rows[marketplace]:
            if checked is not None:
                rows[marketplace]["picked_on"] = _day(checked, "checked")
            if report is not None:
                rows[marketplace]["picked_in"] = report
        if prior is None:
            new.append(marketplace)
        elif prior["presence"] != "listed" and row["presence"] == "listed":
            went_live.append(marketplace)
        elif prior["picked_runs"] > 0 and row["presence"] != "listed":
            still_waiting.append((marketplace, runs))
    dropped = sorted(set(before) - set(rows))
    changes = {
        "went_live": went_live,
        "still_waiting": still_waiting,
        "new": new,
        "dropped": dropped,
    }
    state = {"version": 1, "rows": rows}
    if checked is not None:
        state["checked"] = checked
    return state, changes
```
