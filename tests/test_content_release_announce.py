"""Offline unit tests for the content.release_announce contributed workflow package.

Validates the manifest contract, two-step model sequence, grounding constraints,
and output rendering without making paid supplier API calls.
"""

from __future__ import annotations

import json
import runpy
from types import SimpleNamespace

import jsonschema
import pytest

from tin_lite.code_models import CodeModelError, model_terms, request_contract
from tin_lite.community import REPOSITORY_ROOT
from tin_lite.workflow_code import validate_code_definition, validate_code_result

PACKAGE_KEY = "content.release_announce"
PROJECT_ID = "a0000000-0000-0000-0000-000000000001"

CHANGELOG = (
    "# Release 2.4.0\n"
    "---\n"
    "- Added CSV export for customer analytics\n"
    "- Fixed bug causing session timeout on Safari 17\n"
    "- Refactored database connection pool internals\n"
)

EXTRACTED = {
    "changes": [
        {
            "id": 1,
            "summary": "CSV export for customer analytics",
            "category": "feature",
            "user_facing": True,
        },
        {
            "id": 2,
            "summary": "Resolved session timeout bug on Safari 17",
            "category": "fix",
            "user_facing": True,
        },
        {
            "id": 3,
            "summary": "Internal refactor of database pool",
            "category": "internal",
            "user_facing": False,
        },
    ]
}

ANNOUNCED = {
    "covered_ids": [1, 2],
    "x_post": "v2.4 is out: export customer analytics to CSV, and no more Safari 17 timeouts.",
    "linkedin": (
        "Version 2.4.0 adds CSV export for customer analytics.\n\n"
        "We also fixed a Safari 17 session timeout."
    ),
    "email_subject": "New in 2.4.0: CSV export for analytics",
    "email_body": (
        "Hi there,\n\nYou can now export customer analytics to CSV.\n\n"
        "We also fixed the Safari 17 timeout.\n\nTry the export today."
    ),
}


def load_package():
    root = REPOSITORY_ROOT / "workflow_packages" / PACKAGE_KEY
    definition = json.loads((root / "workflow.json").read_text())["definition"]
    module = SimpleNamespace(**runpy.run_path(str(root / "main.py")))
    return module, definition


def fake_models(spec, *, extracted=EXTRACTED, announced=ANNOUNCED, calls=None):
    calls = [] if calls is None else calls

    async def generate(**payload):
        request_contract(spec, payload)
        calls.append(payload)
        output = extracted if payload["step"] == "extract_changes" else announced
        jsonschema.validate(output, payload["output_schema"])
        return {"parsed": output, "text": json.dumps(output)}

    return SimpleNamespace(models=SimpleNamespace(generate=generate))


def inputs(**overrides):
    return {
        "project_id": PROJECT_ID,
        "changelog": CHANGELOG,
        "product_name": "Tin Computer",
        **overrides,
    }


def test_package_contract_and_estimate():
    _, definition = load_package()
    spec = validate_code_definition(definition)
    assert spec.entrypoint == "main.py"
    assert spec.output_path == "reports/RELEASE_ANNOUNCE.md"
    assert spec.media_type == "text/markdown"
    assert spec.max_bytes == 32000
    assert {r.name for r in spec.model_routes} == {"extract", "announce"}
    assert {r.model for r in spec.model_routes} == {"gpt-6-luna"}
    assert model_terms(definition)["maximum_nanos"] > 0
    properties = definition["input_schema"]["properties"]
    for name, schema in properties.items():
        if schema.get("type") == "string" and name != "project_id" and "enum" not in schema:
            assert schema["maxLength"] <= 12000
    assert {p["producer"] for p in definition["prerequisites"]} == {
        "style.capture",
        "growth.onboarding_plan",
    }
    assert all(p["level"] == "recommended" for p in definition["prerequisites"])


@pytest.mark.parametrize("tone", ["professional", "enthusiastic"])
async def test_happy_path_two_model_steps_and_report_rendering(tone):
    module, definition = load_package()
    spec = validate_code_definition(definition)
    calls = []
    ctx = fake_models(spec, calls=calls)

    result = await module.run(
        ctx,
        inputs(
            audience="Founders and growth engineers",
            tone=tone,
            voice_notes="Short sentences. No exclamation marks.",
            release_url="https://tin.example/changelog/2-4-0",
        ),
    )
    assert [c["step"] for c in calls] == ["extract_changes", "write_announcements"]
    brief = calls[1]["data"]
    # Only announceable changes reach the copywriter, and user text stays data.
    assert [c["id"] for c in brief["changes"]] == [1, 2]
    assert brief["voice_notes"] == "Short sentences. No exclamation marks."
    assert "Tin Computer" not in calls[1]["instructions"]

    content = result["content"]
    assert result["path"] == "reports/RELEASE_ANNOUNCE.md"
    assert "# Release announcements for Tin Computer" in content
    assert "## X post" in content
    assert "## LinkedIn post" in content
    assert "## Newsletter email" in content
    assert "It is not a cold outreach email, and Tin does not send it." in content
    assert "1 internal change(s) left out of the announcements." in content
    assert "Not mentioned in the drafts below" not in content
    assert content.count("https://tin.example/changelog/2-4-0") == 3
    assert f"Tone: {tone}" in content
    validate_code_result(json.dumps(result).encode(), spec)


async def test_internal_category_is_never_announced_even_if_marked_user_facing():
    module, definition = load_package()
    spec = validate_code_definition(definition)
    extracted = {
        "changes": [
            {**EXTRACTED["changes"][0]},
            {**EXTRACTED["changes"][2], "user_facing": True},
        ]
    }
    announced = {**ANNOUNCED, "covered_ids": [1]}
    announced["x_post"] = "Export customer analytics to CSV."
    announced["linkedin"] = "You can now export customer analytics to CSV."
    announced["email_body"] = "You can now export customer analytics to CSV."
    calls = []
    ctx = fake_models(spec, extracted=extracted, announced=announced, calls=calls)
    await module.run(ctx, inputs())
    assert [c["id"] for c in calls[1]["data"]["changes"]] == [1]


async def test_uncovered_change_is_flagged_for_the_reviewer():
    module, definition = load_package()
    spec = validate_code_definition(definition)
    announced = {
        **ANNOUNCED,
        "covered_ids": [1],
        "x_post": "Export customer analytics to CSV.",
        "linkedin": "You can now export customer analytics to CSV.",
        "email_body": "You can now export customer analytics to CSV.",
    }
    result = await module.run(fake_models(spec, announced=announced), inputs())
    assert (
        "Not mentioned in the drafts below:\n- Resolved session timeout bug on Safari 17"
        in (result["content"])
    )


@pytest.mark.parametrize(
    "bad_changes,error_match",
    [
        (
            [{"id": 99, "summary": "Hallucinated", "category": "feature", "user_facing": True}],
            "out of range",
        ),
        (
            [
                {"id": 0, "summary": "Duplicate 1", "category": "feature", "user_facing": True},
                {"id": 0, "summary": "Duplicate 2", "category": "feature", "user_facing": True},
            ],
            "duplicate",
        ),
        (
            [{"id": 0, "summary": "Refactor", "category": "internal", "user_facing": False}],
            "No user-facing changes found",
        ),
        (
            [{"id": 0, "summary": "   ", "category": "feature", "user_facing": True}],
            "blank",
        ),
        (
            [{"id": 0, "summary": "x" * 200, "category": "feature", "user_facing": True}],
            "cut off",
        ),
    ],
)
async def test_extraction_validation_rejects_unusable_results(bad_changes, error_match):
    module, definition = load_package()
    spec = validate_code_definition(definition)
    calls = []
    ctx = fake_models(spec, extracted={"changes": bad_changes}, calls=calls)
    with pytest.raises(ValueError, match=error_match):
        await module.run(ctx, inputs(changelog="- Line zero change"))
    assert len(calls) == 1  # Never proceeds to the announce step on a bad extraction.


@pytest.mark.parametrize(
    "override,error_match",
    [
        # Plausible, well-formed copy that invents a performance claim.
        (
            {"x_post": "Version 2.4.0: CSV export, and pages now load 3x faster."},
            "numbers not in the changelog: 3",
        ),
        ({"linkedin": "Read more at https://evil.example"}, "must not invent links"),
        ({"covered_ids": [1, 3]}, r"not supplied: \[3\]"),
        ({"covered_ids": [1, 1]}, "must not repeat"),
        ({"email_body": "y" * 4000}, "cut off"),
        ({"email_subject": "   "}, "blank"),
    ],
)
async def test_announcement_validation_rejects_unusable_copy(override, error_match):
    module, definition = load_package()
    spec = validate_code_definition(definition)
    ctx = fake_models(spec, announced={**ANNOUNCED, **override})
    with pytest.raises(ValueError, match=error_match):
        await module.run(ctx, inputs())


async def test_x_post_must_fit_with_the_appended_link():
    module, definition = load_package()
    spec = validate_code_definition(definition)
    ctx = fake_models(spec, announced={**ANNOUNCED, "x_post": "CSV export " * 25})
    with pytest.raises(ValueError, match="max 280"):
        await module.run(ctx, inputs(release_url="https://tin.example/r"))


@pytest.mark.parametrize(
    "url", ["http://tin.example/r", 'https://tin.example/r" onclick="x', "javascript:alert(1)"]
)
async def test_release_url_must_be_a_plain_https_link(url):
    module, _ = load_package()
    with pytest.raises(ValueError, match="plain https"):
        await module.run(SimpleNamespace(), inputs(release_url=url))


async def test_oversized_changelog_fails_clearly_before_any_model_call():
    module, definition = load_package()
    spec = validate_code_definition(definition)
    changelog = "\n".join(f"- Changed ünïcödé thing number {i}" for i in range(400))
    calls = []
    with pytest.raises(ValueError, match="too long for one run"):
        await module.run(fake_models(spec, calls=calls), inputs(changelog=changelog[:12000]))
    assert calls == []


async def test_size_precheck_admits_what_the_runtime_admits():
    module, definition = load_package()
    spec = validate_code_definition(definition)
    # A long but admissible changelog must pass both the precheck and the runtime contract.
    changelog = "\n".join(f"- Improved export option {i} for analytics" for i in range(150))
    numbered = [{"id": i, "text": line} for i, line in enumerate(changelog.splitlines())]
    module._check_request_size(module.EXTRACT_INSTRUCTIONS, numbered, module.EXTRACTION, "x")
    request_contract(
        spec,
        {
            "route": "extract",
            "step": "extract_changes",
            "instructions": module.EXTRACT_INSTRUCTIONS,
            "data": numbered,
            "output_schema": module.EXTRACTION,
        },
    )
    too_big = numbered * 4
    with pytest.raises(ValueError):
        module._check_request_size(module.EXTRACT_INSTRUCTIONS, too_big, module.EXTRACTION, "x")
    with pytest.raises(CodeModelError):
        request_contract(
            spec,
            {
                "route": "extract",
                "step": "extract_changes",
                "instructions": module.EXTRACT_INSTRUCTIONS,
                "data": too_big,
                "output_schema": module.EXTRACTION,
            },
        )


@pytest.mark.parametrize("empty_input", ["", "   ", "\n---\n===\n***", "--- \n === \n ~~~"])
async def test_split_changelog_rejects_empty_or_decorative_content(empty_input):
    module, _ = load_package()
    with pytest.raises(ValueError, match="Changelog contains no meaningful content"):
        await module.run(SimpleNamespace(), inputs(changelog=empty_input))
