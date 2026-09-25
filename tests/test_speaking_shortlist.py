"""Reviewed ranking resource for outreach.speaking_shortlist; no web or model calls in CI."""

import json
import re
from pathlib import Path

import pytest

from tin_lite.workflow_prerequisites import parse_workflow_prerequisites
from tin_lite.workflow_qualification import Qualification, assess_output

ROOT = Path(__file__).parents[1]
PACKAGE = ROOT / "workflow_packages/outreach.speaking_shortlist"
SKILL = PACKAGE / "skills/speaking-shortlist"
FIXTURES = ROOT / "tests/fixtures/speaking_shortlist"
CASES = ROOT / "workflow_evals/outreach.speaking_shortlist/qualification.json"
AS_OF = "2026-09-24"
REPORT = "reports/outreach/speaking/0f4e5c1a-2b3c-4d5e-8f90-a1b2c3d4e5f6.md"


@pytest.fixture(scope="module")
def scoring():
    text = (SKILL / "SCORING.md").read_text(encoding="utf-8")
    blocks = re.findall(r"```python\n(.*?)\n```", text, re.S)
    assert len(blocks) == 1
    namespace = {}
    # Only the fixed repository resource executes here, never venue text from a run.
    exec(compile(blocks[0], str(SKILL / "SCORING.md"), "exec"), namespace)  # noqa: S102
    return namespace


def venue(name="Example Postgres Day", **overrides):
    return {
        "name": name,
        "url": "https://pgday.example.org/cfp",
        "format": "conference_talk",
        "deadline": "2026-10-15",
        "open_verified": True,
        "requirements_confirmed": True,
        "route": "form",
        "fit": 3,
        **overrides,
    }


def podcast(name="The Example Data Podcast", **overrides):
    return venue(name, format="podcast_guest", deadline=None, **overrides)


def fixture_text(name):
    # Normalise line endings so a Windows checkout (core.autocrlf) reads the same as CI.
    return (FIXTURES / name).read_bytes().decode("utf-8").replace("\r\n", "\n")


def case(case_id):
    contract = Qualification.model_validate(json.loads(CASES.read_text(encoding="utf-8")))
    return next(item for item in contract.cases if item.id == case_id)


def test_manifest_declares_resources_context_and_a_run_owned_report():
    definition = json.loads((PACKAGE / "workflow.json").read_text(encoding="utf-8"))["definition"]
    assert definition["key"] == PACKAGE.name
    assert definition["system"] == "cold-outreach"
    procedure = definition["procedure"]
    on_disk = sorted(path.relative_to(PACKAGE).as_posix() for path in SKILL.rglob("*.md"))
    assert sorted(procedure["skill_files"]) == on_disk
    assert procedure["output"]["path_template"] == "reports/outreach/speaking/{run_id}.md"
    assert procedure["sandbox"] == {
        "profile": "isolated",
        "egress": "fenced",
        "timeout_seconds": 900,
    }
    schema = definition["input_schema"]
    assert schema["required"] == ["project_id"]
    for name, spec in schema["properties"].items():
        if spec.get("type") == "string" and name != "project_id" and "enum" not in spec:
            assert spec["maxLength"] <= 2000, name
            assert spec["default"] == "", name
    prerequisites = parse_workflow_prerequisites(definition["prerequisites"], input_schema=schema)
    assert {(p.path, p.producer, p.level) for p in prerequisites} == {
        ("wiki/INDEX.md", "product.deep_dive", "recommended"),
        ("reports/GROWTH_ONBOARDING_PLAN.md", "growth.onboarding_plan", "recommended"),
        (".agents/skills/writing-style/SKILL.md", "style.capture", "recommended"),
    }


def test_skill_report_and_state_block_agree():
    skill = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    for label in ("Pitching:", "Context:", "Submit via:", "## Pitched in earlier runs"):
        assert label in skill, label
    assert "tin-speaking-state" in skill
    assert "tin-speaking-state" in (SKILL / "SCORING.md").read_text(encoding="utf-8")
    # The email campaign contract does not fit tailored pitches; the skill says so.
    assert "outreach/email/SHORTLIST.csv" in skill


def test_dated_calls_lead_by_deadline_then_rolling_venues_by_fit(scoring):
    venues = [
        podcast("Loose Podcast", fit=1),
        venue("Late Conf", deadline="2026-12-01", fit=3),
        podcast("Close Podcast", fit=3),
        venue("Soon Meetup", format="meetup_talk", deadline="2026-10-01", fit=1),
    ]
    result = scoring["plan"](venues, AS_OF)
    assert [row["name"] for row in result["shortlist"]] == [
        "Soon Meetup",
        "Late Conf",
        "Close Podcast",
        "Loose Podcast",
    ]
    assert result["status"] == "complete"
    assert result["verdict"] == "fit"


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"open_verified": False}, "open call not verified"),
        ({"requirements_confirmed": False}, "requirements not confirmed"),
        ({"deadline": "2026-09-23"}, "deadline has passed"),
    ],
)
def test_unverified_or_closed_calls_are_excluded_with_a_reason(scoring, overrides, reason):
    result = scoring["plan"]([venue(**overrides)], AS_OF)
    assert result["shortlist"] == []
    assert reason in result["excluded"][0]["reason"]
    assert result["status"] == "no venues verified"
    assert result["verdict"] == "not a fit"


def test_a_rolling_podcast_is_not_dropped_for_lacking_a_deadline(scoring):
    result = scoring["plan"]([podcast()], AS_OF)
    assert [row["key"] for row in result["shortlist"]] == ["the example data podcast"]
    assert result["verdict"] == "thin"


def test_format_preference_narrows_the_list(scoring):
    result = scoring["plan"]([venue(), podcast()], AS_OF, format_preference="podcast_guest")
    assert [row["format"] for row in result["shortlist"]] == ["podcast_guest"]
    assert "conference_talk was not requested" in result["excluded"][0]["reason"]


def test_already_pitched_matches_names_loosely(scoring):
    result = scoring["plan"]([venue("PGConf.EU 2026")], AS_OF, already_pitched=["pgconf eu"])
    assert result["shortlist"] == []
    assert result["excluded"][0]["reason"] == "named in already_pitched"


def test_a_venue_drafted_in_an_earlier_run_is_never_pitched_again(scoring):
    first = scoring["plan"]([venue(), podcast()], "2026-09-10", report_path="reports/a.md")
    earlier = scoring["merge_states"](
        [scoring["read_state"](json.loads(json.dumps(first["state"])))]
    )
    second = scoring["plan"](
        [venue(), podcast(), venue("New Conf", deadline="2026-11-20")],
        AS_OF,
        previous=earlier,
        report_path="reports/b.md",
    )
    assert [row["name"] for row in second["shortlist"]] == ["New Conf"]
    reasons = {row["name"]: row["reason"] for row in second["excluded"]}
    assert reasons["Example Postgres Day"] == "pitch drafted on 2026-09-10 in reports/a.md"
    assert reasons["The Example Data Podcast"] == "pitch drafted on 2026-09-10 in reports/a.md"
    # Memory is cumulative, so the next run only needs the newest block to remember all three.
    assert set(second["state"]["venues"]) == {
        "example postgres day@2026",
        "the example data podcast",
        "new conf@2026",
    }
    assert second["state"]["venues"]["new conf@2026"]["report"] == "reports/b.md"


def test_next_years_call_of_the_same_conference_is_a_new_target(scoring):
    first = scoring["plan"]([venue()], "2026-09-10", report_path="reports/a.md")
    next_edition = venue(deadline="2027-10-15")
    result = scoring["plan"]([next_edition], "2027-09-01", previous=first["state"])
    assert [row["key"] for row in result["shortlist"]] == ["example postgres day@2027"]


def test_merge_keeps_the_first_report_that_drafted_a_venue(scoring):
    item = {"name": "Example Postgres Day", "format": "conference_talk"}
    older = {"version": 1, "venues": {"k": {**item, "first_drafted": "2026-01-01", "report": "a"}}}
    newer = {"version": 1, "venues": {"k": {**item, "first_drafted": "2026-05-01", "report": "b"}}}
    merged = scoring["merge_states"]([newer, None, older])
    assert merged["venues"]["k"]["report"] == "a"


def test_hard_no_on_cold_email_drops_venues_without_a_stated_intake(scoring):
    venues = [
        podcast("Form Podcast"),
        podcast("Published Address Podcast", route="published_address"),
        podcast("Host Inbox Podcast", route="direct_message"),
    ]
    allowed = scoring["plan"](venues, AS_OF)
    assert len(allowed["shortlist"]) == 3
    ruled = scoring["plan"](venues, AS_OF, hard_nos=["no_cold_email"])
    assert [row["name"] for row in ruled["shortlist"]] == [
        "Form Podcast",
        "Published Address Podcast",
    ]
    assert ruled["excluded"][0]["reason"].startswith("hard no: no cold email")


def test_the_cap_is_respected_and_overflow_stays_eligible_next_run(scoring):
    venues = [podcast(f"Podcast {n}") for n in range(5)]
    result = scoring["plan"](venues, AS_OF, max_venues=3, report_path="r.md")
    assert len(result["shortlist"]) == 3
    overflow = [row for row in result["excluded"] if "over max_venues" in row["reason"]]
    assert len(overflow) == 2
    assert len(result["state"]["venues"]) == 3


def test_duplicates_are_counted_once(scoring):
    result = scoring["plan"]([venue(), venue("Example  Postgres-Day")], AS_OF)
    assert len(result["shortlist"]) == 1
    assert result["duplicates_dropped"] == 1


@pytest.mark.parametrize(
    "overrides",
    [
        {"name": "  "},
        {"url": "pgday.example.org/cfp"},
        {"format": "webinar"},
        {"deadline": "mid October"},
        {"open_verified": "yes"},
        {"route": "guessed_email"},
        {"fit": 4},
        {"fit": True},
        {"edition": "2026"},
    ],
)
def test_plausible_but_unusable_records_are_rejected(scoring, overrides):
    with pytest.raises(ValueError):
        scoring["plan"]([venue(**overrides)], AS_OF)


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"max_venues": 2}, "max_venues"),
        ({"max_venues": 21}, "max_venues"),
        ({"format_preference": "keynote"}, "format_preference"),
        ({"hard_nos": ["no_podcasts"]}, "hard no"),
    ],
)
def test_run_inputs_outside_the_contract_are_rejected(scoring, kwargs, message):
    with pytest.raises(ValueError, match=message):
        scoring["plan"]([venue()], AS_OF, **kwargs)


@pytest.mark.parametrize(
    "state",
    [
        None,
        [],
        {"version": 2, "venues": {}},
        {"version": 1, "venues": []},
        {"version": 1, "venues": {"k": "drafted"}},
        {"version": 1, "venues": {"k": {"name": "X", "format": "webinar"}}},
        {
            "version": 1,
            "venues": {
                "k": {
                    "name": "X",
                    "format": "podcast_guest",
                    "first_drafted": "soon",
                    "report": "r",
                }
            },
        },
        {
            "version": 1,
            "venues": {
                "k": {"name": "X", "format": "podcast_guest", "first_drafted": "2026-01-01"}
            },
        },
    ],
)
def test_untrusted_earlier_state_is_discarded(scoring, state):
    assert scoring["read_state"](state) is None


def test_a_plausible_report_passes_the_ordinary_case(scoring):
    text = fixture_text("synthetic_report.md")
    result = assess_output(case("ordinary"), status="succeeded", content=text.encode("utf-8"))
    assert result["status"] == "passed", result["checks"]
    state = re.search(r"```tin-speaking-state\n(.*?)\n```", text, re.S).group(1)
    parsed = scoring["read_state"](json.loads(state))
    assert parsed is not None
    headings = re.findall(r"(?m)^## (.+)$", text)
    venues = [h for h in headings if h not in {"Pitched in earlier runs", "Excluded candidates"}]
    drafted_here = [v for v in parsed["venues"].values() if v["report"] == REPORT]
    assert sorted(venues) == sorted(v["name"] for v in drafted_here)
    assert "Verdict: fit\n" in text and len(venues) >= 3


def test_a_plausible_but_unusable_report_fails_the_ordinary_case():
    # Invented deadline, guessed address, fabricated history, no memory block.
    report = (FIXTURES / "unusable_report.md").read_bytes()
    result = assess_output(case("ordinary"), status="succeeded", content=report)
    assert result["status"] == "failed"
    failed = {check["check"] for check in result["checks"] if not check["passed"]}
    contains = case("ordinary").expect.contains
    for label in ("## Excluded candidates", "Submit via:", "```tin-speaking-state"):
        assert f"contains:{contains.index(label)}" in failed, label
