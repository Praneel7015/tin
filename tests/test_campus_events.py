"""Offline checks for outreach.campus_events: manifest bounds, context wiring and cases."""

import calendar
import json
import re
from datetime import date
from pathlib import Path

from tin_lite.workflow_prerequisites import parse_workflow_prerequisites
from tin_lite.workflow_qualification import Qualification, assess_output

ROOT = Path(__file__).parents[1]
PACKAGE = ROOT / "workflow_packages/outreach.campus_events"
DEFINITION = json.loads((PACKAGE / "workflow.json").read_text())["definition"]
PROMPT = (PACKAGE / "PROMPT.md").read_text()
SKILL = (PACKAGE / "skills/campus-event-fit/SKILL.md").read_text()
CASES = Qualification.model_validate_json(
    (ROOT / "workflow_evals/outreach.campus_events/qualification.json").read_text()
)
# The day the cases were written; the past-events case must stay past after it.
WRITTEN = date(2026, 9, 24)
MONTHS = {name: number for number, name in enumerate(calendar.month_name) if name}


def case(case_id):
    return next(c for c in CASES.cases if c.id == case_id)


def test_only_project_id_is_required_and_every_text_input_is_bounded():
    schema = DEFINITION["input_schema"]
    assert schema["required"] == ["project_id"]
    assert schema["additionalProperties"] is False
    for name, spec in schema["properties"].items():
        if name != "project_id" and spec["type"] == "string":
            assert spec["maxLength"] <= 12000 and spec["default"] == ""


def test_procedure_stays_isolated_fenced_and_writes_one_outreach_report():
    procedure = DEFINITION["procedure"]
    assert procedure["sandbox"] == {
        "profile": "isolated",
        "egress": "fenced",
        "timeout_seconds": 900,
    }
    assert procedure["output"]["path_template"] == "reports/outreach/campus-events/{run_id}.md"
    assert DEFINITION["system"] == "cold-outreach"
    assert "student" in DEFINITION["title"].lower() and "students" in DEFINITION["description"]


def test_context_is_declared_as_recommended_prerequisites_and_read_by_the_skill():
    parsed = parse_workflow_prerequisites(
        DEFINITION["prerequisites"], input_schema=DEFINITION["input_schema"]
    )
    assert {p.level for p in parsed} == {"recommended"}
    paths = {p["path"] for p in DEFINITION["prerequisites"]}
    assert paths == {
        "reports/GROWTH_ONBOARDING_PLAN.md",
        "wiki/INDEX.md",
        ".agents/skills/writing-style/SKILL.md",
    }
    for path in paths | {"### Feature map", "tin-campus-events-state"}:
        assert path in SKILL
    for hard_no in ("no discounting", "no unbacked claims", "no founder posting", "no cold email"):
        assert hard_no in SKILL


def test_research_is_bounded_and_nothing_is_sent():
    assert "at most 12 searches and open at most 20 pages" in SKILL
    assert "next 120 days" in SKILL
    assert "Do not search for replacements" in SKILL
    for forbidden in ("contact organizers", "register", "buy", "guess email"):
        assert forbidden in PROMPT
    assert "Only write the\ndeclared report." in PROMPT


def test_past_events_case_is_plausible_but_unusable():
    past = case("all_supplied_events_past")
    dates = [
        date(int(y), MONTHS[m], int(d))
        for m, d, y in re.findall(r"(\w+) (\d{1,2}), (\d{4})", past.inputs["event_briefs"])
    ]
    assert len(dates) == 2 and all(d < WRITTEN for d in dates)
    assert "Status: recommended" in past.expect.excludes
    ids = {c.id for c in CASES.cases}
    assert {"ordinary", "missing_evidence", "research_when_no_briefs"} <= ids


def report(status, source, events):
    return (
        f"# Campus events for Flashcards\n\nStatus: {status}\nDate: 2026-09-24\n"
        f"Event source: {source}\nBusiness from: input\nStudents from: input\n"
        f"Limits: GBP 150\nContext: none\n\n{events}\n\n"
        '```tin-campus-events-state\n{"recommended": [], "checked": []}\n```\n'
    ).encode()


def test_past_events_case_rejects_a_report_that_recommends_or_researches_anyway():
    past = case("all_supplied_events_past")
    events = "Both are past: MedSoc Freshers Fair, Anatomy Revision Night."
    good = report("no current fit", "supplied briefs", events)
    assert assess_output(past, status="succeeded", content=good)["status"] == "passed"
    for bad in (
        report("recommended", "supplied briefs", events),
        report("no current fit", "web research", events),
    ):
        assert assess_output(past, status="succeeded", content=bad)["status"] == "failed"
