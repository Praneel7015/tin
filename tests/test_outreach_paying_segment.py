"""Offline checks for outreach.paying_segment through Tin's offline Stripe binding."""

import json
import runpy
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from connection_fakes import FakeStripeConnection

from tin_lite.community import REPOSITORY_ROOT
from tin_lite.workflow_code import validate_code_definition, validate_code_result
from tin_lite.workflow_qualification import Qualification, assess_output

ROOT = REPOSITORY_ROOT / "workflow_packages" / "outreach.paying_segment"
NOW = datetime(2026, 9, 1, 12, tzinfo=UTC)
DAY = 86_400
LIMIT = 64_000


def package():
    definition = json.loads((ROOT / "workflow.json").read_text())["definition"]
    return SimpleNamespace(**runpy.run_path(str(ROOT / "main.py"))), definition


MODULE, DEFINITION = package()


def subscription(
    index,
    *,
    email,
    started_days_ago,
    paid_days=None,
    interval="month",
    amount=2900,
    trial_days=0,
    discount=False,
    reason=None,
    feedback=None,
    items=1,
    metadata=None,
    country="US",
    livemode=False,
):
    """A subscription with its customer expanded, in the shape and size Stripe returns."""
    start = int(NOW.timestamp()) - started_days_ago * DAY
    trial_end = start + trial_days * DAY if trial_days else None
    paid_start = trial_end or start
    ended = None if paid_days is None else paid_start + paid_days * DAY
    price = {
        "id": f"price_{interval}{amount}",
        "object": "price",
        "active": True,
        "billing_scheme": "per_unit",
        "created": start,
        "currency": "usd",
        "custom_unit_amount": None,
        "livemode": livemode,
        "lookup_key": None,
        "metadata": {},
        "nickname": None,
        "product": "prod_Synthetic01",
        "recurring": {
            "aggregate_usage": None,
            "interval": interval,
            "interval_count": 1,
            "meter": None,
            "trial_period_days": None,
            "usage_type": "licensed",
        },
        "tax_behavior": "unspecified",
        "tiers_mode": None,
        "transform_quantity": None,
        "type": "recurring",
        "unit_amount": amount,
        "unit_amount_decimal": str(amount),
    }
    plan = {
        "id": price["id"],
        "object": "plan",
        "active": True,
        "aggregate_usage": None,
        "amount": amount,
        "amount_decimal": str(amount),
        "billing_scheme": "per_unit",
        "created": start,
        "currency": "usd",
        "interval": interval,
        "interval_count": 1,
        "livemode": livemode,
        "metadata": {},
        "meter": None,
        "nickname": None,
        "product": "prod_Synthetic01",
        "tiers_mode": None,
        "transform_usage": None,
        "trial_period_days": None,
        "usage_type": "licensed",
    }
    sub_id = f"sub_{index:06d}"
    return {
        "id": sub_id,
        "object": "subscription",
        "application": None,
        "application_fee_percent": None,
        "automatic_tax": {"disabled_reason": None, "enabled": False, "liability": None},
        "billing_cycle_anchor": paid_start,
        "billing_cycle_anchor_config": None,
        "billing_thresholds": None,
        "cancel_at": ended,
        "cancel_at_period_end": False,
        "canceled_at": ended,
        "cancellation_details": {"comment": None, "feedback": feedback, "reason": reason},
        "collection_method": "charge_automatically",
        "created": start,
        "currency": "usd",
        "current_period_end": paid_start + 30 * DAY,
        "current_period_start": paid_start,
        "customer": {
            "id": f"cus_{index:06d}",
            "object": "customer",
            "address": {
                "city": None,
                "country": country,
                "line1": None,
                "line2": None,
                "postal_code": None,
                "state": None,
            },
            "balance": 0,
            "created": start,
            "currency": "usd",
            "default_source": None,
            "delinquent": False,
            "description": None,
            "discount": None,
            "email": email,
            "invoice_prefix": f"INV{index:05d}",
            "invoice_settings": {
                "custom_fields": None,
                "default_payment_method": "pm_synthetic",
                "footer": None,
                "rendering_options": None,
            },
            "livemode": livemode,
            "metadata": metadata or {},
            "name": f"Synthetic Customer {index}",
            "next_invoice_sequence": 2,
            "phone": None,
            "preferred_locales": [],
            "shipping": None,
            "tax_exempt": "none",
            "test_clock": None,
        },
        "days_until_due": None,
        "default_payment_method": "pm_synthetic",
        "default_source": None,
        "default_tax_rates": [],
        "description": None,
        "discount": None,
        "discounts": ["di_synthetic"] if discount else [],
        "ended_at": ended,
        "invoice_settings": {"account_tax_ids": None, "issuer": {"type": "self"}},
        "items": {
            "object": "list",
            "data": [
                {
                    "id": f"si_{index:06d}_{n}",
                    "object": "subscription_item",
                    "billing_thresholds": None,
                    "created": start,
                    "discounts": [],
                    "metadata": {},
                    "plan": plan,
                    "price": price,
                    "quantity": 1,
                    "subscription": sub_id,
                    "tax_rates": [],
                }
                for n in range(items)
            ],
            "has_more": False,
            "total_count": items,
            "url": f"/v1/subscription_items?subscription={sub_id}",
        },
        "latest_invoice": f"in_{index:06d}",
        "livemode": livemode,
        "metadata": {},
        "next_pending_invoice_item_invoice": None,
        "on_behalf_of": None,
        "pause_collection": None,
        "payment_settings": {
            "payment_method_options": None,
            "payment_method_types": None,
            "save_default_payment_method": "off",
        },
        "pending_invoice_item_interval": None,
        "pending_setup_intent": None,
        "pending_update": None,
        "schedule": None,
        "start_date": start,
        "status": "active" if ended is None else "canceled",
        "test_clock": None,
        "transfer_data": None,
        "trial_end": trial_end,
        "trial_settings": {"end_behavior": {"missing_payment_method": "create_invoice"}},
        "trial_start": start if trial_days else None,
    }


def stripe(subscriptions, **options):
    """Tin's offline `payments.stripe` binding over Stripe-shaped subscriptions."""
    return FakeStripeConnection(
        {"subscriptions": subscriptions, "customers": []},
        service="stripe",
        max_response_bytes=LIMIT,
        **options,
    )


class Context(dict):
    def __init__(self, stripe):
        super().__init__(run_id="00000000-0000-4000-8000-000000000099", created_at=NOW.isoformat())
        self.services = stripe


async def run(subscriptions, **inputs):
    binding = stripe(subscriptions)
    result = await MODULE.run(Context(binding), inputs)
    validate_code_result(json.dumps(result).encode(), validate_code_definition(DEFINITION))
    return result["content"], binding


def evidence(content):
    return json.loads(content.split("<!-- tin-paying-segment-evidence-v1 -->\n```json\n")[1][:-5])


def ordinary():
    """25 work-email customers (20 stay, 12 of them annual) against 25 personal-email ones."""
    subs, index = [], 0
    for n in range(25):
        index += 1
        annual = n < 12
        subs.append(
            subscription(
                index,
                email=f"founder@studio{n}.io",
                started_days_ago=90 + n * 7,
                interval="year" if annual else "month",
                amount=29000 if annual else 2900,
                paid_days=None if n < 20 else 20,
                reason=None if n < 20 else "cancellation_requested",
                feedback=None if n < 20 else "missing_features",
                metadata={"source": "podcast" if n % 2 else "search"},
            )
        )
    for n in range(25):
        index += 1
        if n < 6:
            outcome = {}
        elif n < 18:
            outcome = {"paid_days": 25, "reason": "cancellation_requested"}
            outcome["feedback"] = "too_expensive"
        elif n < 22:
            outcome = {"trial_days": 14, "paid_days": -1, "reason": "cancellation_requested"}
        else:
            outcome = {"paid_days": 35, "reason": "payment_failed"}
        subs.append(
            subscription(
                index,
                email=f"person{n}@gmail.com",
                started_days_ago=91 + n * 7,
                metadata={"source": "podcast" if n % 2 else "search"},
                **outcome,
            )
        )
    return subs


def test_manifest_declares_a_read_only_stripe_binding_and_the_rendered_path():
    spec = validate_code_definition(DEFINITION)
    assert DEFINITION["integration_requirements"] == [
        {
            "provider_key": "payments.stripe",
            "capabilities": ["subscriptions.read"],
            "required": True,
        }
    ]
    assert DEFINITION["code"]["services"]["stripe"]["provider_key"] == "payments.stripe"
    assert DEFINITION["code"]["services"]["stripe"]["max_calls"] == MODULE.MAX_CALLS
    assert DEFINITION["code"]["services"]["stripe"]["max_response_bytes"] == LIMIT
    assert DEFINITION["code"]["output"]["path"] == MODULE.OUTPUT
    assert "model_routes" not in DEFINITION["code"]
    assert spec is not None


async def test_ordinary_account_names_who_to_aim_at_and_hands_it_off():
    content, stripe = await run(
        ordinary(), exclude_domains=[], product_summary="An API for podcast clipping."
    )
    assert "Status: complete" in content
    assert "Data: Stripe TEST MODE" in content
    # Markdown merges single-newline lines; each finding must stay its own block.
    assert "\n- Status: complete\n- Generated:" in content
    assert "\n\nAim at:" in content and "\n\nStop paying to acquire:" in content
    assert "Aim at: people who sign up with a work email. 80% of them stayed" in content
    assert "Stop paying to acquire: people who sign up with a personal email" in content
    # Annual billing is a lever on the offer, never the acquisition target.
    assert "Offer lever: customers who pick annual billing kept paying at 100%" in content
    # The hand-off is exact start inputs for sibling workflows, never a start of its own.
    handoff = content.split("## Hand-off: inputs for the next workflows")[1].split("## Method")[0]
    blocks = [json.loads(b.split("```")[0]) for b in handoff.split("```json\n")[1:]]
    shortlist, keyword, ads = blocks
    assert set(shortlist) == {"objective", "selection_notes"}
    assert shortlist["objective"].startswith(
        "From the founder's contacts, shortlist people who look like the customers who paid"
    )
    assert "not prospects" in shortlist["selection_notes"]
    assert keyword == {
        "buyer_context": "An API for podcast clipping. The buyers who pay and stay are people "
        "who sign up with a work email. Buyers who churn early are people who sign up with a "
        "personal email.",
        "market": "US",
    }
    assert len(keyword["buyer_context"]) >= 20, "organic.keyword_plan requires 20 characters"
    # 14 retained monthly customers outnumber 12 annual ones; the median monthly price is 29.
    assert ads["price_point"] == 29.0 and ads["billing"] == "monthly"
    assert "Do not start outreach from them" in handoff, "test-mode data is flagged"
    assert "`outreach.email_shortlist`" in handoff and "`ads.assessment`" in handoff
    assert "studio19.io" in content and "gmail.com" not in content
    assert "@" not in content.split("<!--")[0], "no email addresses in the human report"
    assert "switched to another service" not in content and "too expensive 12" in content
    # Metadata "source" was discovered as a dimension but shows no real difference.
    assert "Metadata source: podcast" in content
    data = evidence(content)
    assert data["fetched"] == 50 and data["judged"] == 50 and not data["truncated"]
    # Projected records are small: fifty subscriptions with their customers fit one read.
    assert [call["step"] for call in stripe.calls] == ["page_1"]
    assert stripe.calls[0]["operation"] == "subscriptions.list"
    assert stripe.calls[0]["arguments"] == {
        "status": "all",
        "created_gte": int(NOW.timestamp()) - 365 * DAY,
        "created_lte": int(NOW.timestamp()) - 60 * DAY,
        "limit": 100,
    }
    tests = {(t["family"], t["value"]): t for t in data["tests"]}
    # One price per interval: "Entry price" repeats "Billing interval" and is shown once.
    assert not any(family == "Entry price" for family, _ in tests)
    assert tests[("Email type", "work email")]["comparisons"] == 3
    assert tests[("Email type", "work email")]["p_holm"] < 0.05
    assert tests[("Metadata source", "podcast")]["p_holm"] > 0.05


def too_few():
    return ordinary()[:8] + ordinary()[25:33]


def no_difference():
    """Half of every segment stays: any named segment here would be a false finding."""
    return [
        subscription(
            n,
            email=f"a@team{n}.com" if n % 2 else f"p{n}@gmail.com",
            started_days_ago=100 + n * 5,
            paid_days=None if n % 4 < 2 else 20,
        )
        for n in range(40)
    ]


async def test_small_accounts_are_told_to_wait_instead_of_getting_a_segment():
    content, _ = await run(too_few())
    assert "Status: insufficient evidence" in content
    assert "Not enough customers to judge yet: 16 of the 20 needed." in content
    assert "## Hand-off" not in content and "Aim at:" not in content


async def test_no_real_difference_stays_provisional():
    content, _ = await run(no_difference())
    assert "Status: provisional" in content
    assert "Aim at:" not in content and "Stop paying to acquire:" not in content
    assert '"objective": "Provisional, test on a small batch:' in content or (
        "Nothing to hand off yet" in content
    )


async def test_failed_payments_come_before_retargeting():
    subs = [
        subscription(
            n,
            email=f"a@team{n}.com" if n < 20 else f"p{n}@gmail.com",
            started_days_ago=100 + n * 5,
            paid_days=None if n % 3 else 30,
            reason=None if n % 3 else "payment_failed",
        )
        for n in range(40)
    ]
    content, _ = await run(subs)
    assert "Next action: fix failed payments before changing who you target." in content
    assert "a payment failed 14" in content


async def test_fitted_pages_continue_from_the_cursor_and_disclose_truncation():
    subs = [
        subscription(n, email=f"a@team{n}.com", started_days_ago=100 + n % 250, items=6)
        for n in range(1000)
    ]
    content, binding = await run(subs)
    assert len(binding.calls) == 8
    # Tin fits the leading records of each 100-record page; the next read starts right after.
    pages = [call["response"] for call in binding.calls]
    assert all(page["truncated"] and page["has_more"] for page in pages)
    for page, after in zip(pages, binding.calls[1:], strict=False):
        assert after["arguments"]["cursor"] == page["next_cursor"] == page["records"][-1]["id"]
    read = [record["id"] for page in pages for record in page["records"]]
    newest = sorted(subs, key=lambda s: (-s["created"], s["id"]))[: len(read)]
    assert read == [s["id"] for s in newest], "no subscription is skipped or read twice"
    assert evidence(content)["fetched"] == len(read)
    assert "Older subscriptions exist that this run could not read" in content
    assert "eight-request limit was reached" in content


@pytest.mark.parametrize(
    ("refusal", "shown"),
    [
        ("permission_denied", "cannot read Subscriptions"),
        ("authentication_failed", "rejected the stored restricted key"),
        ("rate_limited", "rate-limited this read"),
    ],
)
async def test_refused_read_writes_a_setup_diagnostic_after_one_call(refusal, shown):
    binding = stripe(ordinary(), refuse={"page_1": refusal})
    result = await MODULE.run(Context(binding), {})
    assert len(binding.calls) == 1
    assert "Status: connection needs attention" in result["content"]
    assert shown in result["content"]
    assert "restricted key with Read access to Subscriptions and Customers" in result["content"]


async def test_a_binding_without_the_declared_capability_is_a_package_error_not_a_diagnostic():
    binding = stripe(ordinary(), capabilities=("customers.read",))
    with pytest.raises(ValueError, match="declared contract"):
        await MODULE.run(Context(binding), {})


def mutate(change):
    subs = ordinary()
    change(subs)
    return subs


class Altered(FakeStripeConnection):
    """Serves a plausible projected page, then changes it the way a bad response would."""

    def __init__(self, change):
        super().__init__({"subscriptions": ordinary(), "customers": []}, service="stripe")
        self.change = change

    async def call(self, **kwargs):
        page = await super().call(**kwargs)
        self.change(page)
        return page


@pytest.mark.parametrize(
    "change",
    [
        lambda p: p["records"][0].pop("id"),
        lambda p: p["records"][0].update(start_date=None, created=None),
        lambda p: p["records"][0].update(start_date="yesterday"),
        lambda p: p["records"][0].update(items=None),
        lambda p: p["records"][0]["items"][0].update(price_id=None),
        lambda p: p["records"][0].update(customer=None),
        lambda p: p["records"][1].update(id=p["records"][0]["id"]),
        lambda p: p.update(has_more=True, next_cursor=None),
        lambda p: p.pop("records"),
    ],
    ids=[
        "no-id",
        "no-start",
        "bad-timestamp",
        "no-items",
        "no-price",
        "no-customer",
        "duplicate",
        "more-without-cursor",
        "not-a-page",
    ],
)
async def test_plausible_but_malformed_stripe_data_fails_instead_of_reporting(change):
    with pytest.raises(ValueError):
        await MODULE.run(Context(Altered(change)), {})


@pytest.mark.parametrize(
    "inputs",
    [
        {"lookback_days": 80},
        {"retention_days": 90, "lookback_days": 100},
        {"min_segment_size": 2},
        {"exclude_domains": ["not a domain"]},
        {"exclude_domains": [f"d{n}.com" for n in range(21)]},
        {"product_summary": "x" * 501},
    ],
)
async def test_invalid_inputs_are_rejected_before_any_request(inputs):
    binding = stripe(ordinary())
    with pytest.raises(ValueError):
        await MODULE.run(Context(binding), inputs)
    assert binding.calls == []


async def test_excluded_domains_and_identifying_metadata_never_become_segments():
    subs = ordinary()
    for sub in subs:
        sub["customer"]["metadata"]["referrer"] = sub["customer"]["email"]
        sub["customer"]["metadata"]["signup_id"] = "123456789"
    content, _ = await run(subs, exclude_domains=["studio0.io", "studio1.io"])
    assert "2 excluded by domain" in content
    human = content.split("<!--")[0]
    assert "studio0.io" not in human and "studio1.io" not in human
    assert "Metadata referrer" not in content and "Metadata signup_id" not in content


def test_outcome_rules_ignore_trial_days_and_wait_for_young_customers():
    now = int(NOW.timestamp())
    base = {"status": "active", "paid_start": now - 90 * DAY, "ended": None}
    assert MODULE.outcome(base, now, 60) == "stayed"
    assert MODULE.outcome({**base, "paid_start": now - 30 * DAY}, now, 60) == "too young"
    assert MODULE.outcome({**base, "ended": now - 70 * DAY}, now, 60) == "left"
    assert MODULE.outcome({**base, "ended": now - 20 * DAY}, now, 60) == "stayed"
    assert MODULE.outcome({**base, "ended": base["paid_start"]}, now, 60) == "never paid"
    assert MODULE.outcome({**base, "status": "incomplete_expired"}, now, 60) == "never paid"


def test_statistics_match_reference_values():
    # Fisher's tea-tasting style table; reference two-sided p from R's fisher.test.
    assert MODULE.fisher(1, 9, 11, 3) == pytest.approx(0.002759, abs=1e-6)
    assert MODULE.fisher(3, 1, 1, 3) == pytest.approx(0.485714, abs=1e-6)
    tests = [{"p": 0.01}, {"p": 0.04}, {"p": 0.03}]
    assert MODULE.holm(tests) == 3
    assert [t["p_holm"] for t in tests] == pytest.approx([0.03, 0.06, 0.06])
    # Two rows of one two-valued split are a single comparison.
    mirrored = [{"p": 0.01, "split": "a"}, {"p": 0.01, "split": "a"}, {"p": 0.04, "split": "b"}]
    assert MODULE.holm(mirrored) == 2
    assert [t["p_holm"] for t in mirrored] == pytest.approx([0.02, 0.02, 0.04])
    low, high = MODULE.wilson(8, 10)
    assert low == pytest.approx(0.4902, abs=1e-4) and high == pytest.approx(0.9433, abs=1e-4)


def test_price_reads_projected_items_and_usage_prices():
    item = {
        "price_id": "price_1",
        "product_id": "prod_1",
        "unit_amount": 12000,
        "currency": "eur",
        "interval": "year",
        "interval_count": 1,
        "quantity": 1,
    }
    assert MODULE.price([item]) == (1000, "eur", "EUR 120.00/year", "year")
    quarterly = {**item, "unit_amount": 3000, "interval": "month", "interval_count": 3}
    assert MODULE.price([quarterly]) == (1000, "eur", "EUR 30.00/3 months", "month")
    metered = {**item, "unit_amount": None, "currency": "usd", "interval": "month"}
    assert MODULE.price([metered])[0] is None


CASE_FIXTURES = {
    "ordinary": (ordinary, {}),
    "too_few_customers": (too_few, {}),
    "no_real_difference": (no_difference, {}),
    "refused_key": (ordinary, {"page_1": "permission_denied"}),
}


async def test_qualification_cases_pass_on_their_fixtures():
    raw = REPOSITORY_ROOT / "workflow_evals" / "outreach.paying_segment" / "qualification.json"
    qualification = Qualification.model_validate_json(raw.read_text())
    assert {case.id for case in qualification.cases} == set(CASE_FIXTURES)
    for case in qualification.cases:
        build, refuse = CASE_FIXTURES[case.id]
        result = await MODULE.run(Context(stripe(build(), refuse=refuse)), case.inputs)
        report = assess_output(case, status="succeeded", content=result["content"].encode())
        assert report["status"] == "passed", (case.id, report["checks"])


async def test_plan_switch_to_a_new_subscription_is_not_counted_as_leaving():
    subs = ordinary()
    # Customer 1 cancels after 20 days and starts a new plan three days later, still paying.
    first = subs[0]
    first.update(ended_at=first["start_date"] + 20 * DAY, status="canceled")
    again = subscription(900, email="founder@studio0.io", started_days_ago=80 - 23)
    again["customer"] = first["customer"]
    again["created"] = again["start_date"] = first["start_date"] + 23 * DAY
    content, _ = await run([*subs, again])
    data = evidence(content)
    assert data["switched"] == 1 and data["customers"] == 50
    stayed = {(t["family"], t["value"]): t for t in data["tests"]}
    assert stayed[("Email type", "work email")]["stayed"] == 20
    assert "(1 customers renewed this way)" in content


async def test_unpaid_without_an_end_date_is_left_out_not_counted_as_stayed():
    subs = ordinary()
    for sub in subs[:3]:
        sub["status"] = "unpaid"
    content, _ = await run(subs)
    data = evidence(content)
    assert data["unclear"] == 3 and data["judged"] == 47
    assert "3 customers are unpaid or paused with no end date" in content


async def test_empty_product_summary_and_foreign_currency_are_flagged_in_the_handoff():
    subs = ordinary()
    for sub in subs:
        sub["customer"]["address"]["country"] = "DE"
        sub["currency"] = "eur"
        for item in sub["items"]["data"]:
            item["price"]["currency"] = item["plan"]["currency"] = "eur"
        sub["livemode"] = True
    content, _ = await run(subs)
    handoff = content.split("## Hand-off: inputs for the next workflows")[1].split("## Method")[0]
    blocks = [json.loads(b.split("```")[0]) for b in handoff.split("```json\n")[1:]]
    _, keyword, ads = blocks
    assert "market" not in keyword and "`market` (US, GB, CA or AU)" in handoff
    assert "`product_summary` was empty" in handoff
    assert "price_point" not in ads and "billing" not in ads
    assert "TEST MODE" not in content


async def test_empty_account_is_insufficient_evidence_without_a_handoff():
    content, stripe = await run([])
    assert len(stripe.calls) == 1
    assert "Status: insufficient evidence" in content and "## Hand-off" not in content
