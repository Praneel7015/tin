"""Reviewed decision resources for growth.signup_source; no provider or model calls in CI."""

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
PACKAGE = ROOT / "workflow_packages/growth.signup_source"
RESOURCES = PACKAGE / "skills/signup-source"


def resource(name):
    path = RESOURCES / name
    blocks = re.findall(r"```python\n(.*?)\n```", path.read_text(encoding="utf-8"), re.S)
    assert len(blocks) == 1
    namespace = {}
    # Only the fixed repository resource executes here, never repository or model text.
    exec(compile(blocks[0], str(path), "exec"), namespace)  # noqa: S102
    return namespace


@pytest.fixture
def placement():
    return resource("PLACEMENT.md")["choose_placement"]


@pytest.fixture
def options():
    return resource("QUESTION.md")["answer_options"]


def facts(**overrides):
    return {
        "signup_in_repo": True,
        "already_asks": False,
        "form": "custom",
        "first_screen": False,
        "sinks": ["auth_metadata"],
        **overrides,
    }


def test_a_custom_form_with_auth_metadata_keeps_the_answer_with_the_account(placement):
    assert placement(facts()) == {
        "outcome": "patch",
        "surface": "signup_form",
        "sink": "auth_metadata",
        "reason": "",
    }


def test_the_account_beats_analytics_whatever_order_sinks_are_found_in(placement):
    found = facts(sinks=["analytics_identify", "migration", "profile_json"])
    assert placement(found)["sink"] == "profile_json"
    assert placement(facts(sinks=["analytics_identify", "migration"]))["sink"] == "migration"
    assert placement(facts(sinks=["analytics_identify"]))["sink"] == "analytics_identify"


def test_a_hosted_widget_moves_the_question_to_the_first_screen(placement):
    decided = placement(facts(form="hosted", first_screen=True))
    assert (decided["outcome"], decided["surface"]) == ("patch", "first_screen")


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"signup_in_repo": False}, "signup is not in this repository"),
        ({"already_asks": True}, "already asked"),
        ({"form": "hosted"}, "hosted signup"),
        ({"form": "none"}, "hosted signup"),
        ({"sinks": []}, "without new infrastructure"),
    ],
)
def test_blockers_return_no_change_with_the_next_step(placement, overrides, reason):
    decided = placement(facts(**overrides))
    assert decided["outcome"] == "no_change"
    assert decided["surface"] is None and decided["sink"] is None
    assert reason in decided["reason"]


def test_a_migration_that_does_not_fit_the_file_budget_is_not_attempted(placement):
    assert placement(facts(sinks=["migration"]), max_files=3)["sink"] == "migration"
    assert placement(facts(sinks=["migration"]), max_files=2)["outcome"] == "no_change"
    assert placement(facts(sinks=["migration", "auth_metadata"]), max_files=2)["sink"] == (
        "auth_metadata"
    )


@pytest.mark.parametrize(
    "broken",
    [
        None,
        facts(form="widget"),
        facts(sinks=["cookie"]),
        facts(sinks="auth_metadata"),
        facts(first_screen="yes"),
        {k: v for k, v in facts().items() if k != "already_asks"},
    ],
)
def test_unusable_facts_are_rejected_rather_than_guessed(placement, broken):
    with pytest.raises(ValueError):
        placement(broken)


@pytest.mark.parametrize("budget", [0, 4, "3", True])
def test_the_file_budget_is_validated(placement, budget):
    with pytest.raises(ValueError):
        placement(facts(), max_files=budget)


def test_with_no_evidence_the_core_answers_and_other_are_offered(options):
    offered = options([])
    assert [o["value"] for o in offered] == ["ai_assistant", "search", "friend", "other"]
    assert offered[-1]["label"] == "Somewhere else"


def test_evidenced_channels_follow_the_core_in_a_fixed_order(options):
    offered = options(
        [
            {"signal": "reddit", "evidence": "src/components/Footer.tsx:41"},
            {"signal": "ads", "evidence": "app/layout.tsx:12 gtag AW-123"},
            {"signal": "reddit", "evidence": "second sighting is ignored"},
        ]
    )
    assert [o["value"] for o in offered] == [
        "ai_assistant",
        "search",
        "friend",
        "ad",
        "reddit",
        "other",
    ]
    assert offered[4]["evidence"] == "src/components/Footer.tsx:41"


def test_the_list_never_grows_past_eight_and_other_stays_last(options):
    every = [
        {"signal": key, "evidence": f"proof/{key}"} for key in resource("QUESTION.md")["CHANNELS"]
    ]
    offered = options(every)
    assert len(offered) == 8
    assert offered[-1]["value"] == "other"
    assert len({o["value"] for o in offered}) == 8


@pytest.mark.parametrize(
    "signals",
    [
        None,
        [{"signal": "tiktok", "evidence": "footer"}],
        [{"signal": "youtube", "evidence": ""}],
        [{"signal": "youtube", "evidence": "   "}],
        [{"signal": "youtube"}],
        [{"signal": "youtube", "evidence": "x", "label": "Our channel"}],
        [{"signal": "youtube", "evidence": "x" * 301}],
        [{"signal": "youtube", "evidence": "x"}] * 65,
    ],
)
def test_a_channel_without_evidence_or_outside_the_list_is_rejected(options, signals):
    with pytest.raises(ValueError):
        options(signals)


def test_stored_values_are_stable_identifiers_not_labels():
    question = resource("QUESTION.md")
    values = [value for value, _ in question["CORE"]]
    values += [value for value, _ in question["CHANNELS"].values()] + [question["OTHER"][0]]
    assert len(values) == len(set(values))
    assert all(re.fullmatch(r"[a-z][a-z_]*", value) for value in values)


def test_manifest_declares_every_shipped_resource():
    definition = json.loads((PACKAGE / "workflow.json").read_text())["definition"]
    procedure = definition["procedure"]
    shipped = sorted(
        str(path.relative_to(PACKAGE)) for path in (PACKAGE / "skills").rglob("*") if path.is_file()
    )
    assert sorted(procedure["skill_files"]) == shipped
    assert definition["key"] == PACKAGE.name
    assert procedure["output"]["kind"] == "github.pull_request"
    assert procedure["output"]["allow_no_change"] is True
    assert procedure["output"]["max_files"] == 3


def test_the_skill_uses_the_resources_unchanged_and_never_ships_to_production():
    skill = " ".join((RESOURCES / "SKILL.md").read_text().split())
    prompt = " ".join((PACKAGE / "PROMPT.md").read_text().split())
    assert "run `choose_placement` unchanged" in skill
    assert "Run `answer_options` unchanged" in skill
    for promise in ("Never make the question required", "block a signup", "merge, deploy"):
        assert promise in prompt


def test_the_result_headings_are_the_ones_the_skill_promises():
    headings = re.findall(r"^## (.+)$", (RESOURCES / "RESULT.md").read_text(), re.M)
    assert headings == [
        "Outcome",
        "Where it appears",
        "Answers offered",
        "Where answers are kept",
        "How to read them",
        "Verification",
        "Not changed",
    ]
    assert "reports/signup-source/{run_id}/RESULT.md" in (RESOURCES / "RESULT.md").read_text()
