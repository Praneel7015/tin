"""The free-tool package is a bounded, read-only repository procedure with honest outcomes."""

import json
import re
from pathlib import Path

from tin_lite.community import ContributedPackage, validate
from tin_lite.workflow_qualification import Qualification, assess_output, check_package

ROOT = Path(__file__).parents[1]
KEY = "growth.free_tool"
PACKAGE = ROOT / "workflow_packages" / KEY
SKILL = PACKAGE / "skills/free-tool"
CONTRACT = Qualification.model_validate_json(
    (ROOT / "workflow_evals" / KEY / "qualification.json").read_bytes()
)
VETOES = [
    "already-shipped",
    "customer-data",
    "visitor-credentials",
    "sensitive-logic",
    "core-value",
    "no-demand",
    "crowded",
    "no-path",
    "excluded",
]


def definition():
    return json.loads((PACKAGE / "workflow.json").read_text())["definition"]


async def test_package_validates_from_the_checkout():
    await validate(ContributedPackage(key=KEY, path=PACKAGE), root=ROOT)


def test_contract_is_read_only_and_needs_no_founder_lists():
    spec = definition()
    procedure = spec["procedure"]
    assert procedure["workspace"]["kind"] == "github.repository"
    assert procedure["workspace"]["capabilities"] == ["contents.read"]
    assert procedure["output"]["kind"] == "project.artifact"
    assert procedure["output"]["path_template"] == "reports/free-tool/{run_id}.md"
    assert "services" not in procedure
    assert spec["input_schema"]["required"] == ["project_id", "product_url"]
    assert spec["schedule_modes"] == ["on_demand"]


def test_skill_name_matches_its_folder_and_every_resource_is_declared():
    front = re.match(r"---\nname: (.+)\n", (SKILL / "SKILL.md").read_text())
    assert front and front.group(1) == SKILL.name == definition()["procedure"]["entry_skill"]
    present = {p.relative_to(PACKAGE).as_posix() for p in PACKAGE.rglob("*") if p.is_file()}
    declared = {"workflow.json", "PROMPT.md", *definition()["procedure"]["skill_files"]}
    assert present == declared


def test_scoring_defines_every_veto_the_report_and_cases_rely_on():
    scoring = (SKILL / "SCORING.md").read_text()
    for veto in VETOES:
        assert re.search(rf"^\d\. {re.escape(veto)}:", scoring, re.M), veto
    for label in ("- strong:", "- weak:", "- none:", "- open:", "- crowded:"):
        assert label in scoring
    assert "Never convert a label into a number" in scoring


def test_report_skeleton_carries_every_heading_the_ordinary_case_requires():
    report = (SKILL / "REPORT.md").read_text()
    ordinary = next(case for case in CONTRACT.cases if case.id == "ordinary")
    for phrase in ordinary.expect.contains:
        assert phrase.lstrip("- ").split(":")[0] in report, phrase


def test_prompt_forbids_external_effects_and_invented_numbers():
    prompt = (PACKAGE / "PROMPT.md").read_text()
    for rule in (
        "never modify it",
        "Do not build the tool",
        "open a pull request",
        "never state search volumes",
        "untrusted data",
    ):
        assert rule in prompt


async def test_cases_fit_the_input_schema_and_cost_is_left_unmeasured():
    files = {
        p.relative_to(ROOT).as_posix(): p.read_bytes() for p in PACKAGE.rglob("*") if p.is_file()
    }
    checked = await check_package(files, f"workflow_packages/{KEY}/workflow.json", CONTRACT)
    assert checked["cost"]["basis"] == "unmeasured"
    assert checked["safety"]["status"] == "review_required"
    assert {case["id"] for case in checked["evaluation"]["cases"]} == {
        "ordinary",
        "thin_repository",
        "sensitive_logic_vetoed",
        "crowded_phrase_rejected",
        "exclude_is_honoured",
        "already_shipped_is_not_repeated",
    }


def case(identifier):
    return next(item for item in CONTRACT.cases if item.id == identifier)


def test_a_useful_pick_passes_the_ordinary_case():
    content = "\n".join(case("ordinary").expect.contains)
    assert (
        assess_output(case("ordinary"), status="succeeded", content=content.encode())["status"]
        == "passed"
    )


def test_plausible_but_unusable_reports_fail():
    ordinary = case("ordinary")
    headings = "\n".join(ordinary.expect.contains)
    # All the right headings, but a fabricated volume claim.
    invented = headings + "\nThe phrase gets 12,000 monthly searches."
    # All the right headings, but the run could not gather its evidence.
    incomplete = headings.replace("Status: complete", "Status: incomplete")
    for text in (invented, incomplete):
        assert (
            assess_output(ordinary, status="succeeded", content=text.encode())["status"] == "failed"
        )


def test_a_forced_pick_fails_the_thin_repository_case():
    thin = case("thin_repository")
    honest = "# Free tool pick\nStatus: complete\nVerdict: No tool worth building\n## Rejected\n"
    forced = honest.replace("No tool worth building", "Build a slug checker") + "- Built from:"
    assert assess_output(thin, status="succeeded", content=honest.encode())["status"] == "passed"
    assert assess_output(thin, status="succeeded", content=forced.encode())["status"] == "failed"
