"""Find the customer segment that pays and stays, from bounded Stripe subscription reads.

Everything after the reads is ordinary arithmetic: no model, no guesses. The report names one
segment to aim acquisition at (or says the evidence is not there yet) and hands that decision
as exact inputs for the outreach shortlist, keyword plan and paid-ads assessment. A code flow
cannot start other workflows; the calling agent starts them from that labelled section.
"""

import json
import math
import re
from collections import Counter
from datetime import UTC, datetime, timedelta

OUTPUT = "reports/outreach/PAYING_SEGMENT.md"
SERVICE = "stripe"
MAX_CALLS = 8
MAX_RESPONSE_BYTES = 64_000
# Stripe's page size. Tin keeps the leading records that fit MAX_RESPONSE_BYTES and says where
# to continue, so the package never sizes pages itself.
PAGE_LIMIT = 100
# How Tin's own refusals start: a Stripe answer (permission, key, rate limit) or an uncertain read.
REFUSALS = ("Stripe", "Service response unavailable")
DAY = 86_400
ALPHA = 0.05
MIN_JUDGED = 20
INVOLUNTARY_SHARE = 0.3
MAX_SEEDS = 10
MAX_PRICE_GROUPS = 5
MAX_METADATA_DIMENSIONS = 3
OFFER_FAMILIES = frozenset({"Billing interval", "Entry price", "Trial", "Discount"})

FREE_MAIL = frozenset(
    """
    gmail.com googlemail.com outlook.com hotmail.com live.com msn.com yahoo.com ymail.com
    icloud.com me.com mac.com aol.com proton.me protonmail.com pm.me gmx.com gmx.de gmx.net
    web.de mail.com yandex.com yandex.ru mail.ru qq.com 163.com 126.com naver.com zoho.com
    hey.com fastmail.com tutanota.com rediffmail.com hotmail.co.uk yahoo.co.uk yahoo.co.in
    outlook.in live.co.uk btinternet.com orange.fr free.fr libero.it t-online.de comcast.net
    att.net verizon.net
    """.split()
)
EDUCATION = re.compile(r"(\.edu|\.edu\.[a-z]{2}|\.ac\.[a-z]{2})$")
DOMAIN = re.compile(
    r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+"
)
SAFE_LABEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9 _.\-/+&]{0,39}")
IDENTIFIER = re.compile(r"(@|https?:|www\.|\d{6,}|^[a-z]+_[A-Za-z0-9]{8,}$)")
ALIVE_PAYING = {"active", "past_due"}
NEVER_PAID = {"incomplete", "incomplete_expired"}
# Open but not collecting money, since an unknown date: neither stayed nor left can be claimed.
NOT_COLLECTING = {"unpaid", "paused"}
# A new subscription this soon after the last one ended is a plan switch, not a departure.
CONTINUATION_DAYS = 14
# Markets organic.keyword_plan and ads.assessment accept (tin_lite.organic_audit.MARKETS).
KEYWORD_MARKETS = ("US", "GB", "CA", "AU")
ADS_BILLING = {"month": "monthly", "year": "annual"}
# Months in one billing interval; a price divided by this is its monthly value.
INTERVAL_MONTHS = {"day": 12 / 365, "week": 12 / 52, "month": 1, "year": 12}
REASONS = {
    "cancellation_requested": "they cancelled",
    "payment_failed": "a payment failed",
    "payment_disputed": "a payment was disputed",
}
FEEDBACK = {
    "too_expensive": "too expensive",
    "missing_features": "missing features",
    "switched_service": "switched to another service",
    "unused": "not using it",
    "customer_service": "customer service",
    "too_complex": "too complex",
    "low_quality": "quality",
    "other": "other",
}


class ConnectionProblem(Exception):
    """Stripe answered, but not with data: the founder has to fix the connection."""


async def run(ctx, inputs):
    now = datetime.fromisoformat(ctx["created_at"])
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    settings = validate(inputs)
    try:
        subscriptions, requests, truncated = await fetch(ctx, now, settings)
    except ConnectionProblem as problem:
        return {"path": OUTPUT, "content": diagnostic(now, settings, str(problem))}
    records = [normalize(item) for item in subscriptions]
    if len({r["id"] for r in records}) != len(records):
        raise ValueError("Stripe returned the same subscription twice")
    analysis = analyse(records, now, settings)
    analysis.update(requests=requests, truncated=truncated, fetched=len(records))
    return {"path": OUTPUT, "content": render(now, settings, analysis)}


def validate(inputs):
    settings = {
        "lookback_days": inputs.get("lookback_days", 365),
        "retention_days": inputs.get("retention_days", 60),
        "min_segment_size": inputs.get("min_segment_size", 5),
        "exclude_domains": inputs.get("exclude_domains", []),
        "product_summary": inputs.get("product_summary", ""),
    }
    for key, low, high in (
        ("lookback_days", 90, 1095),
        ("retention_days", 14, 180),
        ("min_segment_size", 3, 50),
    ):
        if type(settings[key]) is not int or not low <= settings[key] <= high:
            raise ValueError(f"{key} must be an integer from {low} to {high}")
    if settings["lookback_days"] < settings["retention_days"] + 30:
        raise ValueError("lookback_days must be at least retention_days + 30")
    domains = settings["exclude_domains"]
    if not isinstance(domains, list) or len(domains) > 20:
        raise ValueError("exclude_domains must be a list of at most 20 domains")
    cleaned = set()
    for domain in domains:
        value = domain.strip().lower().lstrip("@") if isinstance(domain, str) else ""
        if not DOMAIN.fullmatch(value):
            raise ValueError("exclude_domains must contain plain domains like example.com")
        cleaned.add(value)
    settings["exclude_domains"] = sorted(cleaned)
    summary = settings["product_summary"]
    if not isinstance(summary, str) or len(summary) > 500:
        raise ValueError("product_summary must be at most 500 characters")
    settings["product_summary"] = " ".join(summary.split())
    return settings


async def fetch(ctx, now, settings):
    """Read the newest judgeable subscriptions, page by page, through Tin's Stripe reads.

    Tin expands each customer and returns small projected records, fitting as many as the
    binding's byte bound allows; `next_cursor` continues exactly after the last one returned.
    """
    window = {
        "status": "all",
        "created_gte": int((now - timedelta(days=settings["lookback_days"])).timestamp()),
        # Younger subscriptions cannot show whether a customer stayed; do not spend reads on them.
        "created_lte": int((now - timedelta(days=settings["retention_days"])).timestamp()),
        "limit": PAGE_LIMIT,
    }
    records, requests, cursor = [], [], None
    for index in range(MAX_CALLS):
        arguments = window if cursor is None else {**window, "cursor": cursor}
        step = f"page_{index + 1}"
        try:
            response = await ctx.services.call(
                service=SERVICE, step=step, operation="subscriptions.list", arguments=arguments
            )
        except ValueError as error:
            # Tin's own refusals (missing permission, revoked key, rate limit, an uncertain
            # read) need the founder; anything else is a bug in this package and must fail.
            if str(error).startswith(REFUSALS):
                raise ConnectionProblem(str(error)) from None
            raise
        page = subscription_page(response)
        requests.append(
            {"step": step, "records": len(page["records"]), "fitted": page["truncated"]}
        )
        records.extend(page["records"])
        if not page["has_more"]:
            return records, requests, False
        cursor = page["next_cursor"]
    return records, requests, True


def subscription_page(response):
    if (
        not isinstance(response, dict)
        or not isinstance(response.get("records"), list)
        or type(response.get("has_more")) is not bool
        or type(response.get("truncated")) is not bool
    ):
        raise ValueError("Stripe did not return a subscription page")
    if response["has_more"] and (
        not response["records"] or not isinstance(response.get("next_cursor"), str)
    ):
        raise ValueError("Stripe returned a page without a cursor to continue from")
    return response


def timestamp(value, *, required=False):
    if value is None and not required:
        return None
    if type(value) is not int or value <= 0:
        raise ValueError("Invalid Stripe subscription record")
    return value


def normalize(sub):
    """One projected subscription (see docs/stripe-and-posthog-connections.md) to a record."""
    if (
        not isinstance(sub, dict)
        or not isinstance(sub.get("id"), str)
        or not isinstance(sub.get("status"), str)
        or not isinstance(sub.get("customer"), dict)
        or not isinstance(sub["customer"].get("id"), str)
        or not isinstance(sub.get("items"), list)
    ):
        raise ValueError("Invalid Stripe subscription record")
    customer = sub["customer"]
    start = timestamp(sub.get("start_date") or sub.get("created"), required=True)
    trial_end = timestamp(sub.get("trial_end"))
    ended = timestamp(sub.get("ended_at"))
    domain, email_type = classify_email(None if customer.get("deleted") else customer)
    country = customer.get("country")
    details = sub.get("cancellation_details")
    details = details if isinstance(details, dict) else {}
    monthly, currency, label, interval = price(sub["items"])
    return {
        "id": sub["id"],
        "customer": customer["id"],
        "status": sub["status"],
        "start": start,
        "paid_start": trial_end if trial_end and trial_end > start else start,
        "trial": bool(trial_end and trial_end > start),
        "ended": ended,
        "domain": domain,
        "email_type": email_type,
        "country": country.upper() if isinstance(country, str) and len(country) == 2 else None,
        "discounted": bool(sub.get("discount_ids")) or bool(sub.get("coupon_id")),
        "monthly": monthly,
        "currency": currency,
        "price": label,
        "interval": interval,
        "reason": details.get("reason") if details.get("reason") in REASONS else None,
        "feedback": details.get("feedback") if details.get("feedback") in FEEDBACK else None,
        "livemode": sub.get("livemode") is True,
        "metadata": {
            **safe_metadata(customer.get("metadata")),
            **safe_metadata(sub.get("metadata")),
        },
    }


def classify_email(customer):
    """Email type from the projected customer's email domain; the address itself is not kept."""
    domain = customer.get("email_domain") if isinstance(customer, dict) else None
    if not isinstance(domain, str) or not DOMAIN.fullmatch(domain.lower()):
        return None, "no email"
    domain = domain.lower()
    if domain in FREE_MAIL:
        return domain, "personal email"
    if EDUCATION.search(domain):
        return domain, "education email"
    return domain, "work email"


def price(items):
    """List-price monthly value in minor units; None when a price is tiered or metered."""
    total, currency, labels, intervals = 0, None, [], set()
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("price_id"), str):
            raise ValueError("Invalid Stripe subscription record")
        interval = item.get("interval")
        count = item.get("interval_count") or 1
        amount = item.get("unit_amount")
        quantity = item.get("quantity")
        quantity = 1 if quantity is None else quantity
        currency = item.get("currency") if isinstance(item.get("currency"), str) else currency
        if (
            interval not in INTERVAL_MONTHS
            or type(count) is not int
            or count < 1
            or type(amount) is not int
            or type(quantity) is not int
            or total is None
        ):
            total = None
        else:
            total += amount * quantity / (INTERVAL_MONTHS[interval] * count)
        intervals.add(interval if interval in INTERVAL_MONTHS else "other")
        if type(amount) is int and interval in INTERVAL_MONTHS:
            every = interval if count == 1 else f"{count} {interval}s"
            labels.append(f"{(currency or '').upper()} {amount / 100:,.2f}/{every}".strip())
        else:
            labels.append("usage-based price")
    currency = (currency or "").lower() or None
    if not items:
        return None, currency, "no price", "other"
    interval = intervals.pop() if len(intervals) == 1 else "mixed"
    return (round(total) if total is not None else None), currency, " + ".join(labels), interval


def safe_metadata(value):
    """Keep only short categorical labels; anything that looks like an identity is dropped."""
    if not isinstance(value, dict):
        return {}
    kept = {}
    for key, text in value.items():
        if not isinstance(key, str) or not isinstance(text, str):
            continue
        text = text.strip()
        if all(SAFE_LABEL.fullmatch(s) and not IDENTIFIER.search(s) for s in (key, text)):
            kept[key] = text
    return kept


def outcome(record, now_ts, days):
    """Stayed: still paying `days` after the first paid day. Trial time does not count."""
    if record["status"] in NEVER_PAID:
        return "never paid"
    if record["ended"] is None and record["status"] in NOT_COLLECTING:
        return "unclear"
    if record["ended"] is not None and record["ended"] <= record["paid_start"]:
        return "never paid"
    if record["ended"] is not None and record["ended"] - record["paid_start"] < days * DAY:
        return "left"
    if now_ts - record["paid_start"] < days * DAY:
        return "too young"
    return "stayed"


def analyse(records, now, settings):
    now_ts = int(now.timestamp())
    excluded = set(settings["exclude_domains"])
    kept = [r for r in records if r["domain"] not in excluded]
    by_customer = {}
    for record in sorted(kept, key=lambda r: (r["start"], r["id"])):
        by_customer.setdefault(record["customer"], []).append(record)
    customers = []
    for subs in by_customer.values():
        first = continued(subs)
        first["outcome"] = outcome(first, now_ts, settings["retention_days"])
        first["returned"] = len(subs) > 1
        first["tenure_days"] = ((first["ended"] or now_ts) - first["paid_start"]) // DAY
        customers.append(first)
    currencies = Counter(c["currency"] for c in customers if c["monthly"] is not None)
    primary = currencies.most_common(1)[0][0] if currencies else None
    for customer in customers:
        paying = customer["status"] in ALIVE_PAYING and customer["ended"] is None
        customer["value"] = (
            (customer["monthly"] if paying else 0)
            if customer["currency"] == primary and customer["monthly"] is not None
            else None
        )
    judged = [c for c in customers if c["outcome"] not in ("too young", "unclear")]
    groups = price_groups(judged)
    for customer in judged:
        customer["price_group"] = groups.get(customer["price"], "other prices")
    families = dimensions(judged)
    tests = segment_tests(judged, families, settings["min_segment_size"])
    departures = [c for c in judged if c["outcome"] in ("left", "never paid")]
    overall = rate(judged)
    decision = decide(judged, tests, departures, settings)
    return {
        "records_excluded": len(records) - len(kept),
        "customers": len(customers),
        "judged": judged,
        "too_young": sum(c["outcome"] == "too young" for c in customers),
        "unclear": sum(c["outcome"] == "unclear" for c in customers),
        "returned": sum(c["returned"] for c in customers),
        "switched": sum(c["switched"] for c in customers),
        "primary_currency": primary,
        "other_currency": sum(1 for c in judged if c["value"] is None),
        "livemode": {r["livemode"] for r in records},
        "families": families,
        "tests": tests,
        "overall": overall,
        "departures": departures,
        "decision": decision,
    }


def continued(subs):
    """The customer's first subscription, carried through any that continue it.

    Some checkouts record a plan change as a new subscription. One that starts within
    CONTINUATION_DAYS of the previous ending is the same customer still paying, so the entry
    segment stays the first subscription's and the outcome follows the chain.
    """
    first = dict(subs[0], switched=False)
    for later in subs[1:]:
        if first["ended"] is None or later["start"] - first["ended"] > CONTINUATION_DAYS * DAY:
            break
        if first["ended"] <= first["paid_start"]:
            # Left a trial straight into a paid plan: paid time starts with the new plan.
            first["paid_start"] = later["paid_start"]
        for key in ("status", "ended", "reason", "feedback", "monthly", "currency"):
            first[key] = later[key]
        first["switched"] = True
    return first


def price_groups(customers):
    ranked = Counter(c["price"] for c in customers).most_common()
    return {label: label for label, _ in ranked[:MAX_PRICE_GROUPS]}


def dimensions(customers):
    """Every family is chosen from the data's shape, before looking at who stayed."""
    families = {
        "Email type": lambda c: c["email_type"],
        "Work email ending": lambda c: (
            "." + c["domain"].rsplit(".", 1)[1] if c["email_type"] == "work email" else None
        ),
        "Billing interval": lambda c: c["interval"],
        "Entry price": lambda c: c["price_group"],
        "Trial": lambda c: "started with a trial" if c["trial"] else "no trial",
        "Discount": lambda c: "discounted" if c["discounted"] else "full price",
    }
    if customers and sum(c["country"] is not None for c in customers) >= len(customers) / 2:
        families["Country"] = lambda c: c["country"] or "unknown"
    coverage = Counter(key for c in customers for key in c["metadata"])
    candidates = []
    for key, present in coverage.items():
        values = {c["metadata"][key] for c in customers if key in c["metadata"]}
        if present >= len(customers) / 2 and 2 <= len(values) <= 8:
            candidates.append((-present, key))
    for _, key in sorted(candidates)[:MAX_METADATA_DIMENSIONS]:
        families[f"Metadata {key}"] = lambda c, key=key: c["metadata"].get(key, "not set")
    return families


def rate(customers):
    stayed = sum(c["outcome"] == "stayed" for c in customers)
    return {
        "n": len(customers),
        "stayed": stayed,
        "rate": stayed / len(customers) if customers else None,
    }


def segment_tests(customers, families, minimum):
    tests, partitions = [], set()
    for family, key in families.items():
        members = [(key(c), c) for c in customers]
        members = [(value, c) for value, c in members if value is not None]
        values = sorted({value for value, _ in members})
        # A family that splits customers exactly like an earlier one (one price per interval,
        # say) is the same comparison under another name; show and count it once.
        partition = frozenset(
            frozenset(c["customer"] for v, c in members if v == value) for value in values
        )
        if partition in partitions:
            continue
        partitions.add(partition)
        everyone = frozenset(c["customer"] for _, c in members)
        for value in values:
            inside = [c for v, c in members if v == value]
            outside = [c for v, c in members if v != value]
            if len(inside) < minimum or len(outside) < minimum:
                continue
            a, c = rate(inside)["stayed"], rate(outside)["stayed"]
            valued = [x["value"] for x in inside if x["value"] is not None]
            ids = frozenset(x["customer"] for x in inside)
            tests.append(
                {
                    # With two values, "A against the rest" and "B against the rest" are one
                    # test; the split identifies it so Holm counts it once.
                    "split": frozenset({ids, everyone - ids}),
                    "family": family,
                    "value": value,
                    "n": len(inside),
                    "stayed": a,
                    "left": sum(x["outcome"] == "left" for x in inside),
                    "never_paid": sum(x["outcome"] == "never paid" for x in inside),
                    "rate": a / len(inside),
                    "rest_n": len(outside),
                    "rest_rate": c / len(outside),
                    "interval": wilson(a, len(inside)),
                    "value_per_customer": sum(valued) / len(valued) if valued else None,
                    "p": fisher(a, len(inside) - a, c, len(outside) - c),
                }
            )
    distinct = holm(tests)
    for test in tests:
        test["comparisons"] = distinct
    return tests


def fisher(a, b, c, d):
    """Two-sided Fisher exact test on [[a, b], [c, d]]."""
    row, col, total = a + b, a + c, a + b + c + d

    def log_p(x):
        return (
            math.lgamma(row + 1)
            + math.lgamma(total - row + 1)
            + math.lgamma(col + 1)
            + math.lgamma(total - col + 1)
            - math.lgamma(total + 1)
            - math.lgamma(x + 1)
            - math.lgamma(row - x + 1)
            - math.lgamma(col - x + 1)
            - math.lgamma(total - row - col + x + 1)
        )

    observed = log_p(a)
    low, high = max(0, row + col - total), min(row, col)
    p = sum(math.exp(log_p(x)) for x in range(low, high + 1) if log_p(x) <= observed + 1e-7)
    return min(1.0, p)


def holm(tests):
    """Holm step-down over distinct splits; rows sharing a split share the adjusted p."""
    unique = {}
    for test in tests:
        unique.setdefault(test.get("split", id(test)), test["p"])
    ordered = sorted(unique, key=lambda split: unique[split])
    adjusted, running = {}, 0.0
    for rank, split in enumerate(ordered):
        running = max(running, min(1.0, (len(ordered) - rank) * unique[split]))
        adjusted[split] = running
    for test in tests:
        test["p_holm"] = adjusted[test.get("split", id(test))]
    return len(ordered)


def wilson(successes, n, z=1.96):
    if not n:
        return (None, None)
    phat = successes / n
    centre = phat + z * z / (2 * n)
    margin = z * math.sqrt(phat * (1 - phat) / n + z * z / (4 * n * n))
    return (
        max(0.0, (centre - margin) / (1 + z * z / n)),
        min(1.0, (centre + margin) / (1 + z * z / n)),
    )


def decide(judged, tests, departures, settings):
    floor = max(MIN_JUDGED, 2 * settings["min_segment_size"])
    involuntary = sum(c["reason"] == "payment_failed" for c in departures)
    base = {"floor": floor, "involuntary": involuntary}
    if len(judged) < floor:
        return {**base, "status": "insufficient evidence"}
    # Only a "who" segment can be targeted before someone becomes a customer. What they bought
    # (interval, price, trial, discount) is a lever on the offer, reported separately.
    who = [t for t in tests if t["family"] not in OFFER_FAMILIES]
    offer = [t for t in tests if t["family"] in OFFER_FAMILIES]
    better = [t for t in who if t["p_holm"] < ALPHA and t["rate"] > t["rest_rate"]]
    worse = [t for t in who if t["p_holm"] < ALPHA and t["rate"] < t["rest_rate"]]
    target = max(
        better,
        key=lambda t: (t["value_per_customer"] or 0, t["rate"], t["n"]),
        default=None,
    )
    avoid = min(worse, key=lambda t: (t["rate"], -t["n"]), default=None)
    lever = max(
        (t for t in offer if t["p_holm"] < ALPHA and t["rate"] > t["rest_rate"]),
        key=lambda t: (t["rate"] - t["rest_rate"], t["n"]),
        default=None,
    )
    leading = None
    if target is None:
        leading = max(
            (t for t in who if t["rate"] > t["rest_rate"]),
            key=lambda t: (t["interval"][0], t["n"]),
            default=None,
        )
    return {
        **base,
        "status": "complete" if target or avoid else "provisional",
        "target": target,
        "avoid": avoid,
        "lever": lever,
        "leading": leading,
        "dunning_first": len(departures) >= 3
        and involuntary / len(departures) >= INVOLUNTARY_SHARE,
    }


def phrase(test):
    family, value = test["family"], test["value"]
    if family == "Email type":
        return {
            "work email": "people who sign up with a work email",
            "personal email": "people who sign up with a personal email",
            "education email": "people who sign up with a school or university email",
            "no email": "customers with no email on file",
        }[value]
    if family == "Work email ending":
        return f"companies whose work email ends in {value}"
    if family == "Billing interval":
        return {
            "month": "customers who pick monthly billing",
            "year": "customers who pick annual billing",
            "mixed": "customers with mixed billing intervals",
        }.get(value, f"customers billed per {value}")
    if family == "Entry price":
        return f"customers who start on {value}"
    if family == "Trial":
        return (
            "customers who start with a trial"
            if value.startswith("started")
            else "customers who start without a trial"
        )
    if family == "Discount":
        return (
            "customers on a discount" if value == "discounted" else "customers who pay full price"
        )
    if family == "Country":
        return f"customers in {value}"
    return f"customers whose {family.removeprefix('Metadata ')} is {value}"


def percent(value):
    return "n/a" if value is None else f"{value * 100:.0f}%"


def money(minor, currency):
    if minor is None or currency is None:
        return "n/a"
    return f"{currency.upper()} {minor / 100:,.2f}"


def seeds(judged, target, families, excluded):
    key = families.get(target["family"]) if target else None
    pool = [
        c
        for c in judged
        if c["outcome"] == "stayed"
        and c["email_type"] == "work email"
        and c["domain"] not in excluded
        and (key is None or key(c) == target["value"])
    ]
    ordered = sorted(pool, key=lambda c: (-c["tenure_days"], c["domain"]))
    return list(dict.fromkeys(c["domain"] for c in ordered))[:MAX_SEEDS]


def render(now, settings, analysis):
    decision, judged, tests = analysis["decision"], analysis["judged"], analysis["tests"]
    target, avoid, leading = decision.get("target"), decision.get("avoid"), decision.get("leading")
    currency, days = analysis["primary_currency"], settings["retention_days"]
    overall = analysis["overall"]
    header = [
        f"Status: {decision['status']}",
        f"Generated: {now.astimezone(UTC).strftime('%Y-%m-%d %H:%M')} UTC",
        f"Stayed means: still paying {days} days after the first paid day; trial days do not "
        "count.",
        f"Window: subscriptions created {settings['lookback_days']} to {days} days before this "
        "run.",
    ]
    if analysis["livemode"] == {False}:
        header.append("Data: Stripe TEST MODE. These are not real customers.")
    elif analysis["livemode"] == {True, False}:
        header.append("Data: a mix of live and test-mode subscriptions. Check the connected key.")
    excluded = analysis["records_excluded"]
    calls = len(analysis["requests"])
    coverage = (
        f"Read {analysis['fetched']} subscriptions in {calls} request{'s' * (calls != 1)} "
        f"({analysis['customers']} customers, {len(judged)} old enough to judge"
        + (f", {excluded} excluded by domain" if excluded else "")
        + ")."
    )
    if analysis["truncated"]:
        coverage += (
            " Older subscriptions exist that this run could not read; the sample is the newest."
        )
    # One item per line in Markdown; single newlines would merge them into one paragraph.
    lines = ["# Who pays and stays", "", *[f"- {item}" for item in [*header, coverage]]]
    lines += ["", "## The answer", ""]
    lines += paragraphs(
        answer(decision, analysis, settings, target, avoid, leading, overall, currency)
    )
    lines += ["", f"## Keep rate by segment ({days}-day)", ""]
    lines += segment_table(tests, currency, overall)
    lines += ["", "## Why customers left", ""]
    lines += paragraphs(departures(analysis["departures"]))
    if decision["status"] != "insufficient evidence":
        lines += ["", "## Hand-off: inputs for the next workflows", ""]
        lines += handoff(decision, analysis, settings, target, avoid, leading)
    lines += ["", "## Method and limits", ""]
    lines += limits(analysis, settings)
    lines += [
        "",
        "<!-- tin-paying-segment-evidence-v1 -->",
        "```json",
        evidence(analysis, settings),
        "```",
        "",
    ]
    return "\n".join(lines)


def paragraphs(items):
    return [line for item in items for line in (item, "")][:-1]


def answer(decision, analysis, settings, target, avoid, leading, overall, currency):
    judged = analysis["judged"]
    if decision["status"] == "insufficient evidence":
        need = decision["floor"] - len(judged)
        return [
            f"Not enough customers to judge yet: {len(judged)} of the {decision['floor']} needed.",
            f"Next action: keep this workflow on its weekly schedule. It needs about {need} more "
            f"customers who started at least {settings['retention_days']} days ago. "
            "Newer subscriptions are not read until they are old enough to judge.",
        ]
    lines = [f"Across {overall['n']} judged customers, {percent(overall['rate'])} paid and stayed."]
    if target:
        lines.append(
            f"Aim at: {phrase(target)}. {percent(target['rate'])} of them stayed, against "
            f"{percent(target['rest_rate'])} of everyone else (n={target['n']}, Holm-adjusted "
            f"p={target['p_holm']:.3f}); each one started is worth "
            f"{money(target['value_per_customer'], currency)} a month today."
        )
    if avoid:
        lines.append(
            f"Stop paying to acquire: {phrase(avoid)}. Only {percent(avoid['rate'])} stayed, "
            "against "
            f"{percent(avoid['rest_rate'])} of everyone else (n={avoid['n']}, Holm-adjusted "
            f"p={avoid['p_holm']:.3f})."
        )
    lever = decision.get("lever")
    if lever:
        lines.append(
            f"Offer lever: {phrase(lever)} kept paying at {percent(lever['rate'])}, against "
            f"{percent(lever['rest_rate'])} (n={lever['n']}, Holm-adjusted "
            f"p={lever['p_holm']:.3f}). Lead with that offer in outreach and on the pricing page."
        )
    if not target and not avoid:
        if leading:
            lines.append(
                f"No segment is reliably different yet. The strongest lead is {phrase(leading)}: "
                f"{percent(leading['rate'])} stayed against {percent(leading['rest_rate'])} "
                f"(n={leading['n']}, p={leading['p_holm']:.2f} after Holm). Treat it as a "
                "hypothesis."
            )
        else:
            lines.append("No segment keeps customers better than the rest in this sample.")
    departures_count = len(analysis["departures"])
    if decision["dunning_first"]:
        action = (
            f"Next action: fix failed payments before changing who you target. "
            f"{decision['involuntary']} of {departures_count} departures were a failed payment, "
            "not a decision to leave. Turn on Stripe's Smart Retries and failed-payment emails."
        )
    elif target:
        action = (
            "Next action: start Build an email outreach shortlist with the inputs in the "
            f"hand-off below, so the next list is made of {phrase(target)}."
        )
    elif avoid:
        action = (
            f"Next action: stop spending acquisition effort on {phrase(avoid)}; "
            "start the next outreach shortlist with the inputs in the hand-off below."
        )
    elif leading:
        action = (
            f"Next action: aim one small outreach batch at {phrase(leading)} as a test, "
            "then let the weekly run confirm or drop it."
        )
    else:
        action = (
            "Next action: keep the weekly run; acquisition channel metadata would sharpen it "
            "(see limits)."
        )
    return [*lines, action]


def segment_table(tests, currency, overall):
    if not tests:
        return ["No segment reached the minimum size on both sides; nothing was compared."]
    rows = [
        f"Everyone: {overall['stayed']} of {overall['n']} stayed ({percent(overall['rate'])}).",
        "",
        "| Segment | Started | Stayed | Left | Never paid | Keep rate (95% CI) | Rest | "
        f"Monthly value per customer ({(currency or 'n/a').upper()}) | Holm p |",
        "| --- | ---: | ---: | ---: | ---: | --- | ---: | ---: | ---: |",
    ]
    for t in sorted(tests, key=lambda t: (t["family"], -t["n"], t["value"])):
        low, high = t["interval"]
        value = t["value_per_customer"]
        value = "n/a" if value is None else f"{value / 100:,.2f}"
        rows.append(
            f"| {t['family']}: {t['value']} | {t['n']} | {t['stayed']} | {t['left']} | "
            f"{t['never_paid']} | {percent(t['rate'])} ({percent(low)}-{percent(high)}) | "
            f"{percent(t['rest_rate'])} | {value} | {t['p_holm']:.3f} |"
        )
    return rows


def departures(departed):
    if not departed:
        return ["No judged customer left or failed to pay."]
    reasons = Counter(REASONS.get(c["reason"], "reason not recorded") for c in departed)
    feedback = Counter(FEEDBACK[c["feedback"]] for c in departed if c["feedback"])
    lines = [
        f"{len(departed)} judged customers left or never paid. Stripe's reason: "
        + ", ".join(f"{label} {count}" for label, count in reasons.most_common())
        + "."
    ]
    if feedback:
        lines.append(
            "What they chose when cancelling: "
            + ", ".join(f"{label} {count}" for label, count in feedback.most_common())
            + "."
        )
    else:
        lines.append(
            "No cancellation feedback was recorded. Turning on the cancellation reason survey in "
            "Stripe's customer portal would say why, not only who."
        )
    return lines


def handoff(decision, analysis, settings, target, avoid, leading):
    """Exact start inputs for sibling workflows. This flow cannot start them itself."""
    chosen = target or leading
    if chosen is None and avoid is None:
        return [
            "Nothing to hand off yet: no segment stands out from the rest. The weekly run "
            "will write inputs here once one does."
        ]
    lines = [
        "This run starts nothing. The calling agent can start each workflow below with "
        "`project_id` plus the JSON shown. First check the hard no's in "
        "`reports/GROWTH_ONBOARDING_PLAN.md`: skip the shortlist under no cold email and the "
        "ads assessment under no paid ads.",
    ]
    if analysis["livemode"] == {False}:
        lines += [
            "",
            "Stripe TEST MODE data: these inputs describe test customers. Do not start "
            "outreach from them.",
        ]
    elif analysis["livemode"] == {True, False}:
        lines += ["", "Mixed live and test-mode data: check the connected key before using these."]
    who = phrase(chosen) if chosen else None
    lines += ["", "### Build an email outreach shortlist (`outreach.email_shortlist`)", ""]
    lines += [
        "It searches the founder's own Gmail and Calendar, so it finds people the founder already "
        "knows who match this segment.",
        "",
        "```json",
        json.dumps(shortlist_inputs(analysis, settings, chosen, avoid, target is None), indent=1),
        "```",
    ]
    buyer = " ".join(
        part
        for part in [
            settings["product_summary"],
            f"The buyers who pay and stay are {who}." if who else "",
            f"Buyers who churn early are {phrase(avoid)}." if avoid else "",
        ]
        if part
    )
    keyword = {"buyer_context": buyer[:2000]}
    market = dominant_market(analysis["judged"])
    if market:
        keyword["market"] = market
    lines += ["", "### Plan keyword opportunities (`organic.keyword_plan`)", ""]
    needs = ["`site_url` (the product's public HTTPS origin)"]
    if not market:
        needs.append("`market` (US, GB, CA or AU)")
    note = "Add " + " and ".join(needs) + " from the onboarding plan."
    if not settings["product_summary"]:
        note += (
            " `product_summary` was empty, so `buyer_context` does not say what the product "
            "does: put one sentence from the onboarding plan's The business section in front "
            "of it, or rerun this workflow with `product_summary` filled."
        )
    lines += [note, "", "```json", json.dumps(keyword, indent=1), "```"]
    ads = ads_inputs(analysis, who, avoid)
    lines += ["", "### Assess paid ads for this business (`ads.assessment`)", ""]
    lines += [
        "Stripe's figures for the assessment's economics; its other inputs come from the "
        "onboarding plan (`onboarding_run_id`).",
        "",
        "```json",
        json.dumps(ads, indent=1),
        "```",
    ]
    return lines


def shortlist_inputs(analysis, settings, chosen, avoid, provisional):
    prefix = "Provisional, test on a small batch: " if provisional else ""
    who = phrase(chosen) if chosen else f"anyone except {phrase(avoid)}"
    objective = (
        f"{prefix}From the founder's contacts, shortlist people who look like the customers "
        f"who paid and stayed for {settings['retention_days']}+ days: {who}."
    )
    notes = []
    if chosen:
        notes.append(
            f"Prioritise {who} ({percent(chosen['rate'])} kept paying against "
            f"{percent(chosen['rest_rate'])} for everyone else)."
        )
    if avoid:
        notes.append(f"Deprioritise {phrase(avoid)} ({percent(avoid['rate'])} kept paying).")
    lever = analysis["decision"].get("lever")
    if lever:
        notes.append(
            f"Lead the pitch with what retained customers chose: {phrase(lever)} kept paying at "
            f"{percent(lever['rate'])} against {percent(lever['rest_rate'])}."
        )
    target = None if provisional else chosen
    seed_domains = seeds(
        analysis["judged"], target, analysis["families"], set(settings["exclude_domains"])
    )
    if seed_domains:
        notes.append(
            "Already retained customers, not prospects (look for organisations like them; "
            "contact them only to ask for a referral): " + ", ".join(seed_domains) + "."
        )
    return {"objective": objective[:2000], "selection_notes": " ".join(notes)[:2000]}


def dominant_market(judged):
    """A keyword market only when most retained customers with a country share a supported one."""
    countries = Counter(c["country"] for c in judged if c["outcome"] == "stayed" and c["country"])
    if not countries:
        return None
    country, count = countries.most_common(1)[0]
    return (
        country if country in KEYWORD_MARKETS and count >= 0.6 * sum(countries.values()) else None
    )


def ads_inputs(analysis, who, avoid):
    """Typical price and billing from retained customers, in USD only (the assessment's unit)."""
    stayed = [
        c
        for c in analysis["judged"]
        if c["outcome"] == "stayed" and c["currency"] == "usd" and c["monthly"] is not None
    ]
    inputs = {}
    intervals = Counter(c["interval"] for c in stayed if c["interval"] in ADS_BILLING)
    if intervals:
        interval = intervals.most_common(1)[0][0]
        months = 12 if interval == "year" else 1
        prices = sorted(c["monthly"] * months for c in stayed if c["interval"] == interval)
        middle = len(prices) // 2
        median = prices[middle] if len(prices) % 2 else (prices[middle - 1] + prices[middle]) / 2
        inputs = {"price_point": round(median / 100, 2), "billing": ADS_BILLING[interval]}
    notes = [f"Customers who pay and stay: {who}." if who else ""]
    notes.append(f"Customers who leave early: {phrase(avoid)}." if avoid else "")
    notes.append(f"From {OUTPUT}.")
    inputs["notes"] = " ".join(n for n in notes if n)[:1000]
    return inputs


def limits(analysis, settings):
    distinct = analysis["tests"][0]["comparisons"] if analysis["tests"] else 0
    lines = [
        "- One customer counts once, by their earliest subscription in the window. "
        f"{analysis['returned']} customers had more than one subscription.",
        "- Segments come from Stripe fields only: email domain, billing interval, entry price, "
        "trial, discount, country when at least half of customers have one, and up to three "
        "customer or subscription metadata keys with 2-8 short values. Emails, names and IDs are "
        "never written to this report; only company domains of retained customers are.",
        "- Discount is what the subscription carries now, not necessarily at signup.",
        "- Monthly value is today's list price of subscriptions still paying, before discounts "
        f"and tax, in {(analysis['primary_currency'] or '').upper() or 'the main currency'}; "
        f"{analysis['other_currency']} customers in other currencies or on usage-based prices "
        "count for keep rate but not for value.",
        "- Each segment is compared with everyone else by a two-sided Fisher exact test"
        + (
            f"; Holm's correction covers all {distinct} distinct comparisons."
            if distinct
            else ". No segment was large enough to compare in this run."
        )
        + f" A segment needs {settings['min_segment_size']} customers on both sides.",
        f"- Subscriptions created in the last {settings['retention_days']} days are not read. "
        f"{analysis['too_young']} of those read were still in a trial too recent to judge.",
        f"- A new subscription within {CONTINUATION_DAYS} days of the previous one ending counts "
        f"as the same customer staying on ({analysis['switched']} customers renewed this way).",
        "- Past-due subscriptions still count as paying; cancelled-at-period-end ones count "
        "until they end.",
    ]
    if analysis["unclear"]:
        lines.append(
            f"- {analysis['unclear']} customers are unpaid or paused with no end date. Stripe does "
            "not say when they stopped paying, so they are left out of the comparison."
        )
    if analysis["truncated"]:
        lines.append(
            "- The eight-request limit was reached before the window was exhausted. A shorter "
            "lookback_days reads a more complete, more recent sample."
        )
    if not any(name.startswith("Metadata ") for name in analysis["families"]):
        lines.append(
            "- No acquisition metadata was found. Writing a `source` or `utm_source` key to the "
            "Stripe customer at checkout would let this compare channels, which is the "
            "segment that matters most."
        )
    return lines


def evidence(analysis, settings):
    data = {
        "settings": {k: v for k, v in settings.items() if k != "product_summary"},
        "requests": analysis["requests"],
        "truncated": analysis["truncated"],
        "fetched": analysis["fetched"],
        "customers": analysis["customers"],
        "judged": len(analysis["judged"]),
        "too_young": analysis["too_young"],
        "unclear": analysis["unclear"],
        "switched": analysis["switched"],
        "overall": analysis["overall"],
        "tests": [
            {
                k: (round(v, 6) if isinstance(v, float) else v)
                for k, v in t.items()
                if k not in ("interval", "split")
            }
            for t in analysis["tests"]
        ],
        "status": analysis["decision"]["status"],
    }
    return json.dumps(data, separators=(",", ":"), sort_keys=True)


def diagnostic(now, settings, problem):
    return "\n".join(
        [
            "# Who pays and stays",
            "",
            "Status: connection needs attention",
            f"Generated: {now.astimezone(UTC).strftime('%Y-%m-%d %H:%M')} UTC",
            "",
            problem,
            "",
            "Connect Stripe in Integrations with a restricted key (rk_live_ or rk_test_) made "
            "from Tin's link, which selects read permissions only. This workflow needs a "
            "restricted key with Read access to Subscriptions and Customers. After changing the "
            "key in Stripe, press Check again on the Stripe card. No figures were computed from "
            "this run.",
            "",
        ]
    )
