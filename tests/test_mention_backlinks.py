"""Reviewed ledger resource for organic.mention_backlinks; no web, provider or model calls in CI."""

import json
import re
from pathlib import Path

import pytest

from tin_lite.workflow_inputs import normalize_workflow_inputs
from tin_lite.workflow_prerequisites import parse_workflow_prerequisites
from tin_lite.workflow_qualification import CASE_PROJECT, Qualification, assess_output

ROOT = Path(__file__).parents[1]
PACKAGE = ROOT / "workflow_packages/organic.mention_backlinks"
RESOURCES = PACKAGE / "skills/mention-to-backlink"
FIXTURES = ROOT / "tests/fixtures/mention_backlinks"
CASES = ROOT / "workflow_evals/organic.mention_backlinks/qualification.json"
DOMAIN = "shipyard.dev"


def resource(name):
    path = RESOURCES / name
    blocks = re.findall(r"```python\n(.*?)\n```", path.read_text(encoding="utf-8"), re.S)
    assert len(blocks) == 1
    namespace = {}
    # Only the fixed repository resource executes here, never fetched page text.
    exec(compile(blocks[0], str(path), "exec"), namespace)  # noqa: S102
    return namespace


@pytest.fixture
def ledger():
    return resource("LEDGER.md")


def definition():
    return json.loads((PACKAGE / "workflow.json").read_text(encoding="utf-8"))["definition"]


def fixture_text(name):
    # Normalise line endings so a Windows checkout reads the same as CI.
    return (FIXTURES / name).read_bytes().decode("utf-8").replace("\r\n", "\n")


def fence(text):
    return json.loads(re.search(r"```tin-backlink-state\n(.*?)\n```", text, re.S).group(1))


def case(case_id):
    contract = Qualification.model_validate(json.loads(CASES.read_text(encoding="utf-8")))
    return next(item for item in contract.cases if item.id == case_id)


def first_week(ledger):
    return ledger["next_state"](
        None,
        [
            {"url": "https://devtoolsweekly.com/issues/212", "status": "drafted"},
            {
                "url": "https://www.stackradar.dev/tools/shipyard/?utm_source=x",
                "status": "no_contact",
            },
            {
                "url": "https://shipyardbrewing.com/beers",
                "status": "discarded",
                "reason": "name_collision",
            },
        ],
        DOMAIN,
    )


@pytest.mark.parametrize(
    "value",
    [
        "shipyard.dev",
        "https://www.Shipyard.dev/pricing",
        "SHIPYARD.DEV.",
        "http://shipyard.dev:8080",
    ],
)
def test_bare_host_normalizes_what_a_founder_types(ledger, value):
    assert ledger["bare_host"](value) == "shipyard.dev"


@pytest.mark.parametrize("value", ["", "   ", "localhost", "shipyard", "https://", None, 42])
def test_bare_host_rejects_what_is_not_a_public_host(ledger, value):
    with pytest.raises(ValueError):
        ledger["bare_host"](value)


def test_one_page_has_one_key_however_it_was_linked(ledger):
    key = ledger["page_key"]
    same = {
        key("https://www.stackradar.dev/tools/shipyard/"),
        key("http://stackradar.dev/tools/shipyard?utm_source=news&ref=x"),
        key("https://StackRadar.dev/tools/shipyard#reviews"),
    }
    assert same == {"stackradar.dev/tools/shipyard"}
    assert key("https://news.ycombinator.com/item?id=4") != key("https://news.ycombinator.com/item")
    with pytest.raises(ValueError):
        key("ftp://stackradar.dev/tools")


def test_own_hosts_cover_subdomains_but_not_lookalikes(ledger):
    own = ["shipyard.dev"]
    assert ledger["is_own"]("https://docs.shipyard.dev/deploy", own)
    assert ledger["is_own"]("https://www.shipyard.dev/", own)
    assert not ledger["is_own"]("https://shipyard.devtools.io/", own)
    assert not ledger["is_own"]("https://notshipyard.dev/", own)


def test_first_run_triage_screens_own_pages_before_any_fetch(ledger):
    triage = ledger["triage"]
    assert triage(None, "https://blog.shipyard.dev/launch", [DOMAIN]) == "own_property"
    assert triage(None, "https://devtoolsweekly.com/issues/212", [DOMAIN]) == "investigate"


def test_an_asked_page_is_rechecked_and_never_redrafted(ledger):
    state, changes = first_week(ledger)
    assert changes["new_asks"] == ["devtoolsweekly.com/issues/212"]
    previous = ledger["read_state"](json.loads(json.dumps(state)), DOMAIN)
    triage = ledger["triage"]
    assert triage(previous, "https://devtoolsweekly.com/issues/212/", [DOMAIN]) == "recheck"
    assert triage(previous, "https://stackradar.dev/tools/shipyard", [DOMAIN]) == "investigate"
    assert triage(previous, "https://shipyardbrewing.com/beers", [DOMAIN]) == "skip"
    with pytest.raises(ValueError, match="already asked"):
        ledger["next_state"](
            previous,
            [{"url": "https://devtoolsweekly.com/issues/212", "status": "drafted"}],
            DOMAIN,
        )
    with pytest.raises(ValueError, match="already asked"):
        ledger["next_state"](
            previous,
            [{"url": "https://devtoolsweekly.com/issues/212", "status": "no_contact"}],
            DOMAIN,
        )


def test_settled_pages_are_not_reinvestigated(ledger):
    state, _ = first_week(ledger)
    with pytest.raises(ValueError, match="settled"):
        ledger["next_state"](
            state, [{"url": "https://shipyardbrewing.com/beers", "status": "drafted"}], DOMAIN
        )


def test_recheck_outcomes_need_an_earlier_ask(ledger):
    state, _ = first_week(ledger)
    for status in ("linked", "still_unlinked"):
        with pytest.raises(ValueError, match="never asked"):
            ledger["next_state"](
                state, [{"url": "https://stackradar.dev/tools/shipyard", "status": status}], DOMAIN
            )


def test_an_ask_is_rechecked_weekly_until_it_goes_live_or_closes(ledger):
    state, _ = first_week(ledger)
    url = "https://devtoolsweekly.com/issues/212"
    for week in range(1, ledger["MAX_RECHECKS"] + 1):
        assert ledger["triage"](state, url, [DOMAIN]) == "recheck"
        state, changes = ledger["next_state"](
            state, [{"url": url, "status": "still_unlinked"}], DOMAIN
        )
        assert changes["still_unlinked"] == [["devtoolsweekly.com/issues/212", week]]
        assert state["pages"]["devtoolsweekly.com/issues/212"]["status"] == "drafted"
    assert ledger["triage"](state, url, [DOMAIN]) == "closed"

    fresh, _ = first_week(ledger)
    live, changes = ledger["next_state"](fresh, [{"url": url, "status": "linked"}], DOMAIN)
    assert changes["went_live"] == ["devtoolsweekly.com/issues/212"]
    assert ledger["triage"](live, url, [DOMAIN]) == "skip"


def test_a_failed_recheck_keeps_the_ask_open(ledger):
    state, _ = first_week(ledger)
    url = "https://devtoolsweekly.com/issues/212"
    after, changes = ledger["next_state"](state, [{"url": url, "status": "unreachable"}], DOMAIN)
    assert (
        after["pages"]["devtoolsweekly.com/issues/212"]
        == state["pages"]["devtoolsweekly.com/issues/212"]
    )
    assert changes["unreachable"] == ["devtoolsweekly.com/issues/212"]


def test_the_brand_can_never_ask_itself_for_a_link(ledger):
    for status in ("drafted", "no_contact", "withheld"):
        with pytest.raises(ValueError, match="own page"):
            ledger["next_state"](
                None, [{"url": "https://docs.shipyard.dev/deploy", "status": status}], DOMAIN
            )
    with pytest.raises(ValueError, match="own page"):
        ledger["next_state"](
            None,
            [{"url": "https://github.com/shipyard-dev", "status": "drafted"}],
            DOMAIN,
            ["github.com"],
        )


def test_own_property_discards_are_counted_not_stored(ledger):
    state, changes = ledger["next_state"](
        None,
        [
            {
                "url": "https://docs.shipyard.dev/deploy",
                "status": "discarded",
                "reason": "own_property",
            }
        ],
        DOMAIN,
    )
    assert state["pages"] == {}
    assert changes["discarded"] == {"own_property": 1}


@pytest.mark.parametrize(
    "outcome",
    [
        {"url": "https://a.example.com/x", "status": "discarded"},
        {"url": "https://a.example.com/x", "status": "discarded", "reason": "unlikely to reply"},
        {"url": "https://a.example.com/x", "status": "drafted", "reason": "name_collision"},
        {"url": "https://a.example.com/x", "status": "sent"},
        {"url": "https://a.example.com/x"},
        {"url": "https://a.example.com/x", "status": "drafted", "note": "x"},
        "https://a.example.com/x",
    ],
)
def test_outcomes_outside_the_vocabulary_are_rejected(ledger, outcome):
    with pytest.raises(ValueError):
        ledger["next_state"](None, [outcome], DOMAIN)


def test_two_outcomes_for_one_page_are_rejected(ledger):
    with pytest.raises(ValueError, match="two outcomes"):
        ledger["next_state"](
            None,
            [
                {"url": "https://a.example.com/x/", "status": "drafted"},
                {"url": "https://www.a.example.com/x", "status": "no_contact"},
            ],
            DOMAIN,
        )


def test_the_ledger_forgets_old_discards_before_it_forgets_an_ask(ledger):
    discards = [
        {"url": f"https://site{index}.example.com/p", "status": "discarded", "reason": "gated"}
        for index in range(ledger["MAX_PAGES"])
    ]
    state, _ = ledger["next_state"](None, discards, DOMAIN)
    assert len(state["pages"]) == ledger["MAX_PAGES"]
    state, _ = ledger["next_state"](
        state, [{"url": "https://new.example.org/review", "status": "drafted"}], DOMAIN
    )
    assert len(state["pages"]) == ledger["MAX_PAGES"]
    assert "new.example.org/review" in state["pages"]
    assert "site0.example.com/p" not in state["pages"]


@pytest.mark.parametrize(
    "value",
    [
        None,
        [],
        {"version": 2, "domain": DOMAIN, "pages": {}},
        {"version": 1, "domain": "other.dev", "pages": {}},
        {"version": 1, "domain": DOMAIN, "pages": []},
        {"version": 1, "domain": DOMAIN, "pages": {"a.com/x": {"status": "drafted"}}},
        {
            "version": 1,
            "domain": DOMAIN,
            "pages": {"a.com/x": {"status": "drafted", "reason": "", "asked": False, "runs": 1}},
        },
        {
            "version": 1,
            "domain": DOMAIN,
            "pages": {"a.com/x": {"status": "discarded", "reason": "", "asked": False, "runs": 1}},
        },
        {
            "version": 1,
            "domain": DOMAIN,
            "pages": {"a.com/x": {"status": "sent", "reason": "", "asked": True, "runs": 1}},
        },
        {
            "version": 1,
            "domain": DOMAIN,
            "pages": {"a.com/x": {"status": "drafted", "reason": "", "asked": True, "runs": 0}},
        },
    ],
)
def test_untrusted_or_foreign_history_is_discarded(ledger, value):
    assert ledger["read_state"](value, DOMAIN) is None


def test_manifest_declares_resources_prerequisites_and_optional_brand_inputs():
    spec = definition()
    procedure = spec["procedure"]
    on_disk = sorted(
        path.relative_to(PACKAGE).as_posix() for path in (PACKAGE / "skills").rglob("*.md")
    )
    assert sorted(procedure["skill_files"]) == on_disk
    assert spec["key"] == PACKAGE.name
    assert spec["system"] == "organic-traffic"
    assert procedure["output"]["path_template"] == "reports/backlink-asks/{run_id}.md"
    assert procedure["sandbox"] == {
        "profile": "isolated",
        "egress": "fenced",
        "timeout_seconds": 900,
    }
    schema = spec["input_schema"]
    assert schema["required"] == ["project_id"]
    for name, field in schema["properties"].items():
        if field.get("type") == "string" and name != "project_id":
            assert "maxLength" in field, name
    prerequisites = parse_workflow_prerequisites(spec["prerequisites"], input_schema=schema)
    assert {(p.kind, p.level) for p in prerequisites} == {
        ("artifact", "recommended"),
        ("run", "recommended"),
    }
    assert {p.producer for p in prerequisites if p.kind == "artifact"} == {
        "growth.onboarding_plan",
        "style.capture",
    }
    assert [p.workflow for p in prerequisites if p.kind == "run"] == ["organic.audit"]


def test_qualification_inputs_satisfy_the_manifest():
    schema = definition()["input_schema"]
    contract = Qualification.model_validate(json.loads(CASES.read_text(encoding="utf-8")))
    for item in contract.cases:
        normalize_workflow_inputs(schema=schema, project_id=CASE_PROJECT, inputs=item.inputs)


def test_skill_report_layout_and_ledger_agree():
    skill = (RESOURCES / "SKILL.md").read_text(encoding="utf-8")
    ledger_text = (RESOURCES / "LEDGER.md").read_text(encoding="utf-8")
    assert "```tin-backlink-state" in skill and "tin-backlink-state" in ledger_text
    for heading in (
        "## Ready to send",
        "## No contact found",
        "## Since last run",
        "## Discarded",
        "## Sources and budget",
    ):
        assert heading in skill
    for source in (
        "reports/GROWTH_ONBOARDING_PLAN.md",
        "reports/organic-audit/",
        "reports/visibility/",
        ".agents/skills/writing-style/SKILL.md",
        "reports/backlink-asks/",
    ):
        assert source in skill + ledger_text, source


def test_the_ordinary_fixture_passes_and_its_fence_reads_back(ledger):
    text = fixture_text("ordinary_report.md")
    result = assess_output(case("ordinary"), status="succeeded", content=text.encode("utf-8"))
    assert result["status"] == "passed", result["checks"]
    state = ledger["read_state"](fence(text), DOMAIN)
    assert state is not None
    # Next week the two new asks and last week's ask are rechecks, never new drafts.
    for url in (
        "https://devtoolsweekly.com/issues/212",
        "https://stackradar.dev/tools/shipyard",
        "https://jamiewrites.net/2026/08/leaving-heroku",
    ):
        assert ledger["triage"](state, url, [DOMAIN]) == "recheck"
    drafted = re.findall(r"(?m)^- Page: (\S+)$", text)
    assert drafted and not any(ledger["is_own"](url, [DOMAIN]) for url in drafted)


def test_a_plausible_but_unusable_report_fails_the_ordinary_case(ledger):
    # Drafts to the brand's own docs, to a brewery that shares the name, and a repeat ask.
    report = (FIXTURES / "unusable_report.md").read_bytes()
    result = assess_output(case("ordinary"), status="succeeded", content=report)
    assert result["status"] == "failed"
    failed = {check["check"] for check in result["checks"] if not check["passed"]}
    assert {"contains:6", "contains:8", "contains:9", "excludes:2", "excludes:4"} <= failed
    # The ledger refuses the same mistakes before any report is written.
    with pytest.raises(ValueError, match="own page"):
        ledger["next_state"](
            None, [{"url": "https://docs.shipyard.dev/deploy", "status": "drafted"}], DOMAIN
        )
    previous, _ = first_week(ledger)
    assert ledger["triage"](previous, "https://shipyardbrewing.com/beers", [DOMAIN]) == "skip"
    with pytest.raises(ValueError, match="already asked"):
        ledger["next_state"](
            previous,
            [{"url": "https://devtoolsweekly.com/issues/212", "status": "drafted"}],
            DOMAIN,
        )


def test_the_unusable_fixture_also_fails_the_own_and_collision_case():
    report = (FIXTURES / "unusable_report.md").read_bytes()
    result = assess_output(case("only_own_and_collisions"), status="succeeded", content=report)
    assert result["status"] == "failed"
