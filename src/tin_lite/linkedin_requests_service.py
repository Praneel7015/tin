"""What a member reads and decides about connection requests, for HTTP and MCP alike (#450).

A member sees and decides only requests their own LinkedIn would send; turning sending on takes
their own tick of the consent box, so it happens on the LinkedIn card, never over MCP.
Approving starts the `social.linkedin_requests` run for that batch.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from tin_lite import linkedin_requests as requests
from tin_lite.connection_collection import PROVIDER, enabled

CONSENT_TEXT = (
    "Send the connection requests I approve from Tin's servers, with my LinkedIn session: one "
    "at a time, a few each weekday. This works while my computer is off. Tin stops at the "
    "first warning from LinkedIn, and I can turn it off here anytime."
)
RISK_TEXT = (
    "LinkedIn's terms don't allow automated requests. Few, paced requests that stop at the "
    "first warning lower the risk to your account; they don't remove it."
)


class RequestsRefused(Exception):
    """A request Tin refuses, with its status and the sentence the member reads."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status, self.message = status, message


STATUS = {
    "not_found": 404,
    "conflict": 409,
    "sending_off": 409,
    "consent_required": 422,
    "invalid": 422,
}


def _refused(error: requests.RequestError) -> RequestsRefused:
    return RequestsRefused(STATUS.get(error.code, 422), error.message)


class ConnectionRequests:
    def __init__(self, runtime, settings):
        self.runtime, self.settings = runtime, settings
        self.db = runtime.database

    async def _project(self, project_id: UUID, member: str):
        if not await self.db.has_project_access(project_id=project_id, clerk_user_id=member):
            raise RequestsRefused(404, "project not found")
        project = await self.db.get_project(project_id)
        if project is None:
            raise RequestsRefused(404, "project not found")
        return project

    async def _reading(self, project_id: UUID, member: str) -> bool:
        return bool(
            await self.db.pool.fetchval(
                """SELECT EXISTS (SELECT 1 FROM integration_connections
                   WHERE project_id = $1 AND provider_key = $2 AND status = 'connected'
                     AND connected_by_clerk_user_id = $3)""",
                project_id,
                PROVIDER,
                member,
            )
        )

    async def state(self, project_id: UUID, member: str) -> dict[str, Any]:
        """The member's sending, this week's numbers, and the batch waiting for them."""

        await self._project(project_id, member)
        now = datetime.now(UTC)
        async with self.db.pool.acquire() as conn:
            sending = await requests.sending(conn, project_id, member)
            week = await requests.week(conn, project_id, member, now)
            batches = await requests.open_batches(conn, project_id, member, now)
        offered = enabled(self.settings, project_id)
        return {
            "offered": offered,
            "reading": await self._reading(project_id, member) if offered else False,
            "sending": {
                key: sending[key]
                for key in (
                    "on",
                    "paused",
                    "held",
                    "paused_reason",
                    "paused_until",
                    "daily_cap",
                    "weekly_cap",
                    "start_minute",
                    "end_minute",
                    "timezone",
                )
            },
            "pause_text": requests.PAUSES.get(sending["paused_reason"] or "")
            if sending["paused_reason"] != "limit"
            else "LinkedIn's weekly limit for invitations",
            "consent": {
                "version": requests.CONSENT_VERSION,
                "text": CONSENT_TEXT,
                "risk": RISK_TEXT,
            },
            "week": week,
            "batches": batches,
        }

    async def set_sending(
        self,
        project_id: UUID,
        member: str,
        *,
        enabled_: bool,
        consent_version: int | None = None,
        limits: dict[str, int] | None = None,
    ) -> dict[str, Any]:
        await self._project(project_id, member)
        if enabled_ and not await self._reading(project_id, member):
            raise RequestsRefused(409, "Connect your own LinkedIn reading first.")
        try:
            async with self.db.pool.acquire() as conn:
                await requests.set_sending(
                    conn,
                    project_id,
                    member,
                    enabled=enabled_,
                    consent_version=consent_version,
                    limits=limits,
                )
        except requests.RequestError as error:
            raise _refused(error) from None
        return await self.state(project_id, member)

    async def resume(self, project_id: UUID, member: str) -> dict[str, Any]:
        await self._project(project_id, member)
        async with self.db.pool.acquire() as conn:
            await requests.resume(conn, project_id, member)
        return await self.state(project_id, member)

    async def decide(
        self,
        project_id: UUID,
        batch_id: UUID,
        member: str,
        *,
        request_id: UUID,
        approve: bool,
        people: list[UUID] | None = None,
        trigger_client: str = "dashboard",
        oauth_client_id: str | None = None,
    ) -> dict[str, Any]:
        """Approve the chosen people, which starts the sending run, or discard the batch."""

        await self._project(project_id, member)
        try:
            async with self.db.pool.acquire() as conn:
                decided = await requests.decide(
                    conn,
                    project_id,
                    batch_id,
                    member,
                    request_id=request_id,
                    approve=approve,
                    people=people,
                )
        except requests.RequestError as error:
            raise _refused(error) from None
        if decided["status"] == "approved":
            decided["run_id"] = str(
                await self._start(project_id, batch_id, member, trigger_client, oauth_client_id)
            )
        return decided

    async def _start(self, project_id, batch_id, member, trigger_client, oauth_client_id):
        from tin_lite.run_service import start_workflow_run

        workflow = await self.db.get_workflow(requests.WORKFLOW_ID)
        if workflow is None:
            raise RequestsRefused(503, "Sending isn't available right now. Try again later.")
        from tin_lite.billing_contracts import BillingError
        from tin_lite.failures import public_error_text
        from tin_lite.integrations import IntegrationError
        from tin_lite.run_service import WorkflowExecutorUnavailableError
        from tin_lite.workflow_inputs import WorkflowInputError

        try:
            run = await start_workflow_run(
                runtime=self.runtime,
                settings=self.settings,
                workflow=workflow,
                project_id=project_id,
                started_by_clerk_user_id=member,
                start_idempotency_key=f"linkedin-requests:{batch_id}",
                input_payload={"batch_id": str(batch_id)},
                trigger_client=trigger_client,
                started_by_oauth_client_id=oauth_client_id,
                _linkedin_requests=True,
            )
        except (
            BillingError,
            IntegrationError,
            WorkflowExecutorUnavailableError,
            WorkflowInputError,
        ) as exc:
            # Approved and queued: approving again with the same request starts it.
            raise RequestsRefused(
                409, public_error_text(exc, "Tin couldn't start sending. Approve again shortly.")
            ) from None
        return run.id
