"""Offline checks of the checked-in recipe; no PostHog requests or model calls."""

import json
import re
from copy import deepcopy
from pathlib import Path

import pytest
from connection_fakes import FakePostHogConnection

from tin_lite.posthog_connection import check_hogql, project_query

RESOURCE = (
    Path(__file__).parents[1]
    / "workflow_packages/example.posthog_funnel/skills/posthog-funnel/HOGQL.md"
)


@pytest.fixture
def recipe():
    # This exact reviewed repository resource is executable inside the procedure sandbox.
    # Never use this loader for packages submitted to the qualification service.
    blocks = re.findall(r"```python\n(.*?)\n```", RESOURCE.read_text(), re.S)
    assert len(blocks) == 1
    namespace = {}
    exec(compile(blocks[0], str(RESOURCE), "exec"), namespace)  # noqa: S102 - fixed, reviewed fixture
    return namespace


def response():
    # Synthetic three-stage fixture, as Tin's query.hogql returns it: raw marginals differ
    # from ordered unique actors.
    columns = [name for i in (1, 2, 3) for name in (f"raw{i}", f"eligible{i}", f"actors{i}")]
    columns += ["n1", "n2", "n3", "median_d12", "median_d13", "median_d23"]
    columns += ["order_violations", "duplicate_choices"]
    return {
        "columns": columns,
        "types": ["UInt64"] * 12 + ["Float64"] * 3 + ["UInt64"] * 2,
        "rows": [[10, 10, 8, 11, 11, 8, 10, 10, 8, 8, 6, 5, 1.5, 5.0, 3.0, 0, 0]],
        "has_more": False,
        "truncated": False,
    }


def test_exact_aggregate_validation_and_rates(recipe):
    rows = recipe["read_funnel"](response(), 3)
    assert [r["chain_actors"] for r in rows] == [8, 6, 5]
    assert [r["raw_actors"] for r in rows] == [8, 8, 8]
    assert [r["median_from_first"] for r in rows] == [0.0, 1.5, 5.0]
    assert rows[2]["median_from_previous"] == 3.0
    assert rows[2]["of_previous_pct"] == pytest.approx(100 * 5 / 6)
    assert rows[2]["of_first_pct"] == 62.5


def test_generator_preserves_the_provider_qualified_synthetic_query(recipe):
    # A versioned SQL/response pair records the actual dialect check. This is a regression
    # guard, not a live query in CI; SQL changes require separately authorized requalification.
    fixtures = Path(__file__).parent / "fixtures/posthog_funnel"
    query = (fixtures / "ordered.sql").read_text().rstrip()
    events_cte = query.split(",\nb AS", 1)[0]
    steps = ["onboarding_plan_written", "onboarding_approved", "onboarding_set_up"]
    assert events_cte + recipe["funnel_tail"](steps) == query
    # The recorded PostHog response, projected the way Tin's gateway returns it.
    observed = project_query(
        json.loads((fixtures / "ordered.json").read_text()), max_response_bytes=32_000
    )
    assert recipe["read_funnel"](observed, 3) == recipe["read_funnel"](response(), 3)


def guarded_events_cte():
    """A synthetic e CTE that Tin's guard accepts: rows come from arrayJoin, not UNION ALL."""
    rows = [
        ("p1", "a", "signed_up", 1),
        ("p1", "a", "onboarding_completed", 2),
        ("p2", "b", "signed_up", 1),
    ]
    literal = ",".join(f"('{a}','{b}','{e}',{t})" for a, b, e, t in rows)
    columns = "r.1 AS actor,r.2 AS attempt,r.3 AS event,toDateTime64(r.4,6,'UTC') AS t"
    rows_sql = f"SELECT arrayJoin([{literal}]) AS r"
    return f"WITH e AS (SELECT {columns},true AS eligible FROM ({rows_sql}))"  # noqa: S608


async def test_generated_query_passes_tins_guard_through_the_binding(recipe):
    query = guarded_events_cte() + recipe["funnel_tail"](["signed_up", "onboarding_completed"])
    assert check_hogql(query) == query and len(query.encode()) <= 8000
    fixtures = Path(__file__).parent / "fixtures/posthog_funnel"
    recorded = json.loads((fixtures / "ordered.json").read_text())
    posthog = FakePostHogConnection(
        {}, service="analytics", max_response_bytes=32_000, queries={"funnel": recorded}
    )
    result = await posthog.call(
        service="analytics",
        step="funnel",
        operation="query.hogql",
        arguments={"query": query, "name": "funnel"},
    )
    assert set(result) == {"columns", "types", "rows", "has_more", "truncated"}
    assert recipe["read_funnel"](result, 3)[2]["chain_actors"] == 5
    # The old request shape (project path, OFFSET paging, UNION) never reaches PostHog.
    for bad in [
        query.removesuffix(" LIMIT 2"),
        query + " OFFSET 10",
        query + " UNION ALL " + query,
    ]:
        with pytest.raises(ValueError):
            check_hogql(bad)


@pytest.mark.parametrize("raw_first", [0, 1])
def test_no_events_and_no_eligible_actor_have_undefined_rates(recipe, raw_first):
    data = response()
    data["rows"] = [[raw_first, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, None, None, None, 0, 0]]
    rows = recipe["read_funnel"](data, 3)
    assert all(r["chain_actors"] == 0 for r in rows)
    assert all(r["of_first_pct"] is None and r["of_previous_pct"] is None for r in rows)
    assert all(r["median_from_first"] is None for r in rows)
    assert rows[0]["raw_events"] == raw_first  # Missing identity is distinguishable from no events.


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("n2", 9),  # Unmatched joins must not inflate completion past the event/actor counts.
        ("n3", 7),  # A later prefix cannot exceed its predecessor.
        ("order_violations", 1),
        ("duplicate_choices", 1),
        ("eligible2", 5),
        ("n2", True),
        ("n2", -1),
        ("median_d12", None),
        ("median_d12", 0),
        ("median_d12", -1),
        ("median_d13", float("nan")),
        ("median_d23", float("inf")),
    ],
)
def test_rejects_inconsistent_provider_aggregates(recipe, column, value):
    data = response()
    data["rows"][0][data["columns"].index(column)] = value
    with pytest.raises(ValueError):
        recipe["read_funnel"](data, 3)


@pytest.mark.parametrize(
    "change",
    [
        {"has_more": True},
        {"truncated": True},
        {"has_more": None},
        {"rows": []},
        {"rows": [[1]]},
        {"columns": ["unexpected"]},
    ],
)
def test_rejects_unavailable_or_malformed_results(recipe, change):
    data = response() | deepcopy(change)
    with pytest.raises(ValueError):
        recipe["read_funnel"](data, 3)


def test_two_stage_results(recipe):
    data = {
        "columns": [
            "raw1",
            "eligible1",
            "actors1",
            "raw2",
            "eligible2",
            "actors2",
            "n1",
            "n2",
            "median_d12",
            "order_violations",
            "duplicate_choices",
        ],
        "rows": [[10, 10, 8, 11, 11, 8, 8, 6, 1.0, 0, 0]],
        "has_more": False,
        "truncated": False,
    }
    rows = recipe["read_funnel"](data, 2)
    assert len(rows) == 2 and rows[1]["of_first_pct"] == 75
    assert rows[1]["median_from_first"] == rows[1]["median_from_previous"] == 1.0


@pytest.mark.parametrize("steps", [["one"], ["same", "same"], ["one", "x'); DROP TABLE events"]])
def test_query_builder_rejects_invalid_stage_literals(recipe, steps):
    with pytest.raises(ValueError):
        recipe["funnel_tail"](steps)
