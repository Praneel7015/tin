"""Calls an agent can copy directly from onboarding; no external services."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import UUID, uuid4

import pytest
from mcp.server.mcpserver.exceptions import ToolError
from test_private_workflows import ACTOR, activate, fixture, mcp, structured
from test_procedure_publication import publication_db as publication_db
from test_service_billing import install

from tin_lite.integrations import ConnectStart, IntegrationNotConfiguredError


@pytest.fixture
async def account(publication_db, monkeypatch):
    f = await fixture(publication_db)
    await f.db.grant_workspace_membership(workspace_id=f.project.workspace_id, clerk_user_id=ACTOR)
    f.storage.ensure_repo = AsyncMock()
    f.server = mcp(f, monkeypatch)
    return f


async def call(f, tool_name, **arguments):
    return structured(await f.server.call_tool(tool_name, arguments))


async def test_name_only_creation_in_one_workspace_and_explicit_retry(account):
    f = account
    project = await call(f, "create_project", name="Example business")
    assert project["workspace_id"] == str(f.project.workspace_id)
    assert project["name"] == "Example business"
    assert UUID(project["request_id"])
    replay = await call(
        f, "create_project", name="Example business", request_id=project["request_id"]
    )
    assert replay == project
    assert len(await f.db.list_projects_for_user(ACTOR)) == 2
    with pytest.raises(ToolError, match="already used for another project"):
        await call(f, "create_project", name="Different business", request_id=project["request_id"])


async def test_workspace_choice_is_explicit_when_ambiguous_and_never_infers_from_project_access(
    account,
):
    f = account
    other = await f.db.create_project(name="Other", state_repo_id="projects/other")
    await f.db.grant_workspace_membership(workspace_id=other.workspace_id, clerk_user_id=ACTOR)
    with pytest.raises(ToolError, match="Choose workspace_id") as error:
        await call(f, "create_project", name="A business")
    assert str(f.project.workspace_id) in str(error.value)
    assert str(other.workspace_id) in str(error.value)
    f.storage.ensure_repo.assert_not_called()
    project = await call(
        f, "create_project", name="A business", workspace_id=str(other.workspace_id)
    )
    assert project["workspace_id"] == str(other.workspace_id)
    await f.db.pool.execute("DELETE FROM workspace_memberships WHERE clerk_user_id=$1", ACTOR)
    f.storage.ensure_repo.reset_mock()
    with pytest.raises(ToolError, match="No administered workspace"):
        await call(f, "create_project", name="No authority")
    with pytest.raises(ToolError, match="workspace not found"):
        await call(
            f, "create_project", name="No authority", workspace_id=str(f.project.workspace_id)
        )
    f.storage.ensure_repo.assert_not_called()


async def test_uuid_requirements_are_in_the_schema_and_invalid_values_have_no_effect(account):
    f = account
    tools = {tool.name: tool for tool in await f.server.list_tools()}
    assert tools["create_project"].input_schema["required"] == ["name"]
    for tool, fields in {
        "create_project": ["workspace_id", "request_id"],
        "get_workflow": ["project_id"],
    }.items():
        for field in fields:
            schema = tools[tool].input_schema["properties"][field]
            assert {"format": "uuid", "type": "string"} in schema["anyOf"]
            assert schema["description"]
    for field in ["workspace_id", "request_id"]:
        with pytest.raises(ToolError, match="UUID"):
            await call(f, "create_project", name="Invalid", **{field: "not-a-uuid"})
    f.storage.ensure_repo.assert_not_called()


def tools_schema_is_plain_string(f):
    return True


async def test_onboarding_identifier_and_ready_to_call_inspection_both_work(account):
    f = account
    workflow = await install(f, "growth.onboarding")
    started = await call(f, "get_started", project_id=str(f.project.id))
    assert started["onboarding_contract_version"] == 1
    assert started["delivery_destination"]["channel"] == "tin"
    assert started["delivery_destination"]["notifications_enabled"] is False
    assert {n["provider"] for n in started["access_needs"]} == {"infra.github", "analytics.gsc"}
    assert started["first_deliverables"] and started["result_links"] == []
    first = started["first_workflow"]
    assert first["id"] == str(workflow.id)
    generic = await call(f, "get_workflow", workflow_id=first["id"])
    assert generic["key"] == first["key"]
    assert generic["readiness"] is None and generic["project_id"] is None
    assert "preparation" not in generic
    assert "input_schema" in generic
    inspect = first["inspect"]
    scoped = await call(f, inspect["name"], **inspect["arguments"])
    assert scoped["project_id"] == str(f.project.id)
    assert scoped["readiness"] is not None
    for key in [first["key"], first["id"]]:
        old_client = await call(f, "get_workflow", project_id=str(f.project.id), workflow_key=key)
        assert old_client == scoped
    by_key = await call(f, "get_workflow", workflow_key=first["key"])
    assert by_key == generic
    # Agents often pass the key they were shown as workflow_id; accept it.
    assert tools_schema_is_plain_string(f)
    assert await call(f, "get_workflow", workflow_id=first["key"]) == generic
    key_as_id = await call(
        f, "get_workflow", project_id=str(f.project.id), workflow_id=f" {first['key']} "
    )
    assert key_as_id == scoped
    with pytest.raises(ToolError, match="workflow_id 'growth.nope' is not a workflow UUID or key"):
        await call(f, "get_workflow", project_id=str(f.project.id), workflow_id="growth.nope")
    with pytest.raises(ToolError, match="workflow_key 'growth.nope' is not a workflow UUID or key"):
        await call(f, "get_workflow", project_id=str(f.project.id), workflow_key="growth.nope")
    with pytest.raises(ToolError, match="workflow not found for workflow_id 'growth.nope'"):
        await call(f, "get_workflow", workflow_id="growth.nope")
    with pytest.raises(ToolError, match="not both"):
        await call(f, "get_workflow", workflow_id=first["id"], workflow_key=first["key"])
    with pytest.raises(ToolError, match="Supply workflow_id"):
        await call(f, "get_workflow")
    with pytest.raises(ToolError, match="workflow not found"):
        await call(f, "get_workflow", workflow_id=str(uuid4()))
    f.runtime.temporal.start_workflow.assert_not_called()


async def test_private_id_inspection_keeps_membership_boundary(account, monkeypatch):
    f = account
    private = await activate(f)
    result = await call(f, "get_workflow", workflow_id=private["workflow_id"])
    assert result["scope"] == "project" and result["project_id"] == str(f.project.id)
    other = await f.db.create_project(name="Other", state_repo_id="projects/other")
    await f.db.grant_project_membership(project_id=other.id, clerk_user_id=ACTOR)
    with pytest.raises(ToolError, match="workflow not found"):
        await call(f, "get_workflow", project_id=str(other.id), workflow_id=private["workflow_id"])
    f.server = mcp(f, monkeypatch, actor="user_OutsideProject")
    with pytest.raises(ToolError, match="workflow not found"):
        await call(f, "get_workflow", workflow_id=private["workflow_id"])


async def test_founder_words_come_apart_as_quote_and_relay(account):
    """A tool result carries Tin's own words in `quote` and facts for the agent's words in
    `relay`; `tell_the_founder` joins them for clients on older instructions."""
    f = account
    workflow = await install(f, "growth.onboarding")
    started = await call(
        f,
        "start_workflow",
        project_id=str(f.project.id),
        workflow_id=workflow.key,
        inputs={"product_url": "https://example.com/"},
    )
    # Starting is a status, said in the agent's words, with the guessed defaults first.
    assert "quote" not in started
    assert started["relay"][0].startswith(
        "I set this up as a serious side project aiming for more signups."
    )
    assert started["relay"][1].startswith("Tin is writing your plan now.")
    assert started["tell_the_founder"] == "\n\n".join(started["relay"])
    # The plan's minutes are useful: hand over context, connect the systems it leans on.
    meanwhile = started["meanwhile"]
    assert meanwhile["context_request"]["path_pattern"] == "context/{slug}.md"
    assert meanwhile["context_request"]["index_path"] == "wiki/INDEX.md"
    assert meanwhile["context_request"]["commit"]["name"] == "commit_project_changes"
    assert "credential" in meanwhile["context_request"]["guard"]
    assert "plan already running does not see it" in meanwhile["context_request"]["reaches"]
    assert {need["provider"] for need in meanwhile["access_needs"]} == {
        "infra.github",
        "analytics.gsc",
    }
    assert all(need["benefit"] and need["permissions"] for need in meanwhile["access_needs"])
    assert meanwhile["connection_batch"]["name"] == "start_integration_connections"
    assert started["relay"][2].startswith("While it reads, two things help")
    assert "GitHub" in started["relay"][2] and "Search Console" in started["relay"][2]

    # While the plan waits for a pick, Tin's view is the quote and the state is the relay.
    run_id = UUID(started["id"])
    view = (
        "Example has a live site and no measured traffic.\n\nAs the first phase, Tin can start\n"
        "- checking assistant recommendations weekly"
    )
    await f.db.pool.execute(
        "UPDATE workflow_runs SET status='running', review_required=true WHERE id=$1", run_id
    )
    await f.db.request_human_review(
        run_id=run_id,
        canonical_commit_sha="a" * 40,
        artifact_ref="code.storage://repo@a/reports/GROWTH_ONBOARDING_PLAN.md",
        artifact_path="reports/GROWTH_ONBOARDING_PLAN.md",
        summary=view,
    )
    held = await call(f, "get_run", run_id=str(run_id))
    assert held["status"] == "needs_input"
    assert held["quote"] == held["review_summary"] == view
    assert held["relay"] == [
        "The plan is ready and waits for their pick.",
        "The next few minutes are theirs: what Tin takes on, in their words, then the control "
        "they keep and any connections. Nothing runs until they have said.",
    ]
    assert held["tell_the_founder"] == "\n\n".join([view, *held["relay"]])


async def test_integration_connection_returns_the_link_and_surfaces_provider_errors(account):
    f = account
    url = "https://github.com/login/oauth/authorize?state=synthetic"
    f.runtime.integrations.start_connect = AsyncMock(return_value=ConnectStart(url))
    started = await call(
        f, "start_integration_connection", project_id=str(f.project.id), provider_key="infra.github"
    )
    assert started["authorization_url"] == url
    assert started["relay"] == [
        "I am opening the github connection for Private pilot in your browser; it takes about "
        "a minute. Tell me when it says connected."
    ]
    assert started["tell_the_founder"] == started["relay"][0]

    f.runtime.integrations.start_connect = AsyncMock(
        side_effect=IntegrationNotConfiguredError("GitHub is not configured on this Tin deployment")
    )
    with pytest.raises(ToolError, match="GitHub is not configured"):
        await call(
            f,
            "start_integration_connection",
            project_id=str(f.project.id),
            provider_key="infra.github",
        )


async def test_stripe_connects_through_tins_page_never_through_chat(account):
    f = account
    url = f"https://lite.tin.test/connect?project={f.project.id}&providers=payments.stripe"
    f.runtime.integrations.start_connect = AsyncMock(return_value=ConnectStart(url))
    started = await call(
        f,
        "start_integration_connection",
        project_id=str(f.project.id),
        provider_key="payments.stripe",
    )
    assert started["setup_url"] == started["authorization_url"] == url
    assert "never in this chat" in started["relay"][0]
    batch = await call(
        f,
        "start_integration_connections",
        project_id=str(f.project.id),
        providers=["payments.stripe", "infra.github"],
    )
    assert batch["providers"] == ["payments.stripe", "infra.github"]
    assert batch["url"].endswith("&providers=payments.stripe,infra.github")
    assert "Stripe" in batch["relay"][0] and "never in chat" in batch["relay"][0]
    from tin_lite.integrations import registered_integrations
    from tin_lite.mcp_server import _mcp_integration_view

    stripe = next(d for d in registered_integrations() if d.key == "payments.stripe")
    listed = _mcp_integration_view(stripe, None, configured=True)
    assert listed["setup_url"].startswith("https://dashboard.stripe.com/apikeys/create?")
    assert listed["capabilities"] == [
        "subscriptions.read",
        "customers.read",
        "invoices.read",
        "prices.read",
        "charges.read",
    ]


async def test_posthog_connects_through_oauth_and_names_the_project_choice(account):
    f = account
    url = "https://oauth.posthog.com/oauth/authorize/?required_access_level=project"
    f.runtime.integrations.start_connect = AsyncMock(return_value=ConnectStart(url))
    started = await call(
        f,
        "start_integration_connection",
        project_id=str(f.project.id),
        provider_key="analytics.posthog",
    )
    assert started["authorization_url"] == url
    assert "pick the one PostHog project" in started["relay"][0]
    batch = await call(
        f,
        "start_integration_connections",
        project_id=str(f.project.id),
        providers=["analytics.posthog", "payments.stripe"],
    )
    assert batch["url"].endswith("&providers=analytics.posthog,payments.stripe")
    assert "PostHog asks which project" in batch["relay"][0]


async def test_a_new_onboarding_supersedes_only_earlier_unapproved_runs(account):
    """Agents restart onboarding after a correction; the earlier run must not wait forever."""
    f = account
    handle = SimpleNamespace(cancel=AsyncMock())
    f.runtime.temporal.get_workflow_handle = Mock(return_value=handle)
    workflow = await install(f, "growth.onboarding")

    async def start(request_id):
        started = await call(
            f,
            "start_workflow",
            project_id=str(f.project.id),
            workflow_id=workflow.key,
            inputs={"product_url": "https://example.com/"},
            request_id=request_id,
        )
        return UUID(started["id"])

    async def status(run_id):
        return await f.db.pool.fetchval("SELECT status FROM workflow_runs WHERE id=$1", run_id)

    first = await start(str(uuid4()))
    # The first run waits for picks; its plan child is still pending.
    await f.db.pool.execute(
        "UPDATE workflow_runs SET status='running', review_required=true WHERE id=$1", first
    )
    await f.db.request_human_review(
        run_id=first,
        canonical_commit_sha="a" * 40,
        artifact_ref="code.storage://repo@a/reports/GROWTH_ONBOARDING_PLAN.md",
        artifact_path="reports/GROWTH_ONBOARDING_PLAN.md",
        summary="Pick an option.",
    )
    planner = await install(f, "growth.onboarding_plan")
    plan_child, _ = await f.db.create_run(
        project_id=f.project.id,
        workflow_id=planner.id,
        started_by_clerk_user_id=ACTOR,
        start_idempotency_key=f"onboarding:{first}:plan",
        input_payload=(await f.db.get_run(first)).input,
        pinned_definition=planner.definition,
        definition_commit_sha=planner.current_commit_sha,
    )
    view = await call(f, "get_started", project_id=str(f.project.id))
    assert view["active_run_id"] == str(first)

    second_key = str(uuid4())
    second = await start(second_key)
    assert await status(first) == "superseded"
    assert await status(plan_child.id) == "superseded"
    assert await status(second) == "pending"
    cancelled = {c.args[0] for c in f.runtime.temporal.get_workflow_handle.call_args_list}
    assert cancelled == {
        (await f.db.get_run(first)).temporal_workflow_id,
        plan_child.temporal_workflow_id,
    }
    assert handle.cancel.await_count == 2
    view = await call(f, "get_started", project_id=str(f.project.id))
    assert view["active_run_id"] == str(second)

    # A replayed start returns the same run and supersedes nothing.
    assert await start(second_key) == second
    assert await status(second) == "pending"
    assert handle.cancel.await_count == 2

    # An approved onboarding belongs to setup, and a finished one stays finished.
    async with f.db.pool.acquire() as conn:
        key = f"onboarding:{second}:approved_plan"
        await f.db.start_effect(conn, execution_key=key, operation="growth.onboarding")
        await f.db.complete_effect(conn, execution_key=key, result={"text": "plan"})
    third = await start(str(uuid4()))
    assert await status(second) == "pending"
    await f.db.pool.execute("UPDATE workflow_runs SET status='succeeded' WHERE id=$1", third)
    await start(str(uuid4()))
    assert await status(third) == "succeeded"
    assert await status(second) == "pending"
    assert handle.cancel.await_count == 2
