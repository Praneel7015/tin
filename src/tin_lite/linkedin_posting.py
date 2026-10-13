"""The project's LinkedIn posting connection, through Tin's own Zernio account.

Each project gets one Zernio profile. The founder signs in to LinkedIn through Zernio's hosted
connect and picks where Tin may post: themselves, the pages they administer, or both. Each pick
is one Zernio account in the project's profile. Tin stores no LinkedIn credential; the
connection row keeps the profile and its accounts, and the server reads them from Zernio by the
project's profile, never from the callback's query.

The posting card is shown only to the projects in `TIN_LITE_LINKEDIN_POSTING_PROJECTS`, because
Zernio bills Tin for every connected account. `TIN_LITE_ZERNIO_PROFILE_MAP` points a project at
an existing profile instead: staging uses it so it never creates profiles or accounts of its
own, and connecting or disconnecting a mapped profile never changes it in Zernio.
"""

from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode
from uuid import UUID, uuid4

from tin_lite.integrations import (
    LINKEDIN_POSTING_CAPABILITIES,
    LINKEDIN_POSTING_PROVIDER,
    ConnectStart,
    IntegrationAuthorizationError,
    IntegrationError,
    IntegrationNotConfiguredError,
)
from tin_lite.zernio import Zernio

logger = logging.getLogger(__name__)

CALLBACK = "linkedin"
# Zernio keeps its OAuth state for 30 minutes; Tin's attempt lasts as long.
ATTEMPT_MINUTES = 30
EXPIRED = "LinkedIn connection attempt has expired; connect again"


def enabled(settings: Any, project_id: UUID | None) -> bool:
    if project_id is None:
        return False
    values = getattr(settings, "linkedin_posting_projects", ())
    return str(project_id) in {str(value) for value in values}


def mapped_profile(settings: Any, project_id: UUID) -> str | None:
    return dict(getattr(settings, "zernio_profile_map", {}) or {}).get(str(project_id))


def _hash(state: str) -> str:
    return hashlib.sha256(state.encode()).hexdigest()


def _label(accounts: list[dict[str, Any]]) -> str:
    names = [account["name"] for account in accounts if account["active"]]
    return ", ".join(names)[:200] or "No account connected"


class LinkedInPosting:
    def __init__(self, integrations: Any) -> None:
        self.integrations = integrations
        self.db = integrations._database
        self.settings = integrations._settings

    @property
    def zernio(self) -> Zernio:
        return Zernio(self.integrations._client, self.settings)

    def _require_enabled(self, project_id: UUID) -> None:
        self.integrations._require_configured(LINKEDIN_POSTING_PROVIDER)
        if not enabled(self.settings, project_id):
            raise IntegrationNotConfiguredError(
                "LinkedIn posting is not available for this project yet"
            )

    async def _profile(self, project_id: UUID) -> tuple[str, bool]:
        mapped = mapped_profile(self.settings, project_id)
        if mapped is not None:
            return mapped, True
        if getattr(self.settings, "deployment_environment", "production") == "staging":
            raise IntegrationNotConfiguredError(
                "Staging posts to LinkedIn only through a mapped Zernio profile"
            )
        return await self.zernio.ensure_profile(project_id), False

    async def start(self, *, project_id: UUID, clerk_user_id: str) -> ConnectStart:
        self._require_enabled(project_id)
        profile_id, mapped = await self._profile(project_id)
        state = secrets.token_urlsafe(32)
        await self.db.create_integration_auth_attempt(
            token_hash=_hash(state),
            project_id=project_id,
            provider_key=LINKEDIN_POSTING_PROVIDER,
            clerk_user_id=clerk_user_id,
            pkce_verifier_ciphertext=None,
            requested_capabilities=LINKEDIN_POSTING_CAPABILITIES,
            expires_at=datetime.now(UTC) + timedelta(minutes=ATTEMPT_MINUTES),
        )
        # Zernio keeps an existing query string and appends its own parameters to it.
        callback = f"{self.integrations._callback_url(CALLBACK)}?{urlencode({'state': state})}"
        if mapped:
            # The profile and its accounts already exist; attach them without a new sign-in.
            return ConnectStart(authorization_url=callback)
        return ConnectStart(
            authorization_url=await self.zernio.connect_url(profile_id, redirect=callback)
        )

    async def _attempt(self, state: str, clerk_user_id: str, *, include_used: bool):
        if not isinstance(state, str) or not 1 <= len(state) <= 256:
            raise IntegrationAuthorizationError(EXPIRED)
        attempt = await self.db.get_integration_auth_attempt(
            token_hash=_hash(state),
            provider_key=LINKEDIN_POSTING_PROVIDER,
            clerk_user_id=clerk_user_id,
            include_used=include_used,
        )
        if attempt is None:
            raise IntegrationAuthorizationError(EXPIRED)
        return attempt

    async def pending_project(self, *, state: str, clerk_user_id: str) -> UUID:
        return (await self._attempt(state, clerk_user_id, include_used=True)).project_id

    async def complete(self, *, state: str, clerk_user_id: str):
        """Record the accounts now in the project's profile; a repeated callback returns them."""

        state_hash = _hash(state if isinstance(state, str) else "")
        attempt = await self.db.consume_integration_auth_attempt(
            token_hash=state_hash,
            provider_key=LINKEDIN_POSTING_PROVIDER,
            clerk_user_id=clerk_user_id,
        )
        if attempt is None:
            used = await self._attempt(state, clerk_user_id, include_used=True)
            existing = await self.db.get_integration_connection(
                project_id=used.project_id, provider_key=LINKEDIN_POSTING_PROVIDER
            )
            if existing is not None and existing.configuration.get("auth_attempt") == state_hash:
                return existing
            raise IntegrationAuthorizationError(EXPIRED)
        self._require_enabled(attempt.project_id)
        profile_id, mapped = await self._profile(attempt.project_id)
        accounts = await self.zernio.accounts(profile_id)
        if not any(account["active"] for account in accounts):
            raise IntegrationAuthorizationError(
                "No LinkedIn account was connected. Connect again and pick yourself or a page."
            )
        async with self.db.integration_refresh_lock(
            project_id=attempt.project_id, provider_key=LINKEDIN_POSTING_PROVIDER
        ):
            connection = await self.db.upsert_integration_connection(
                project_id=attempt.project_id,
                provider_key=LINKEDIN_POSTING_PROVIDER,
                external_account_id=profile_id,
                external_account_label=_label(accounts),
                configuration={
                    "zernio_profile_id": profile_id,
                    "profile_mapped": mapped,
                    "accounts": accounts,
                    "granted_capabilities": list(LINKEDIN_POSTING_CAPABILITIES),
                    "auth_attempt": state_hash,
                },
                credential_ciphertext=None,
                credential_key_version=None,
                connected_by_clerk_user_id=clerk_user_id,
            )
        await self.integrations._record_activity(
            connection,
            "integration_connected",
            f"LinkedIn posting connected for {_label(accounts)}.",
            suffix=str(uuid4()),
        )
        return connection

    async def connection(self, project_id: UUID):
        self._require_enabled(project_id)
        connection = await self.db.get_integration_connection(
            project_id=project_id, provider_key=LINKEDIN_POSTING_PROVIDER
        )
        if connection is None or connection.status != "connected":
            raise IntegrationAuthorizationError("Connect or reconnect LinkedIn posting")
        return connection

    async def check(self, project_id: UUID):
        """Read the profile's accounts again, so the card shows what Tin may post as now."""

        connection = await self.db.get_integration_connection(
            project_id=project_id, provider_key=LINKEDIN_POSTING_PROVIDER
        )
        if connection is None:
            raise IntegrationAuthorizationError("Connect LinkedIn posting first")
        self._require_enabled(project_id)
        accounts = await self.zernio.accounts(connection.external_account_id)
        configuration = {**connection.configuration, "accounts": accounts}
        updated = await self.db.update_integration_configuration(
            project_id=project_id,
            provider_key=LINKEDIN_POSTING_PROVIDER,
            configuration=configuration,
            external_account_label=_label(accounts),
        )
        if not any(account["active"] for account in accounts):
            await self.db.mark_integration_attention(
                project_id=project_id,
                provider_key=LINKEDIN_POSTING_PROVIDER,
                error_code="no_active_account",
            )
            updated = await self.db.get_integration_connection(
                project_id=project_id, provider_key=LINKEDIN_POSTING_PROVIDER
            )
        return updated

    async def revoke(self, connection: Any) -> None:
        """Remove the project's accounts and profile from Zernio, so Tin stops paying for them.

        Best effort, like the other providers: deleting the local connection is authoritative.
        A mapped profile belongs to another deployment or project and is never changed.
        """

        if connection.configuration.get("profile_mapped") or mapped_profile(
            self.settings, connection.project_id
        ):
            return
        profile_id = connection.configuration.get("zernio_profile_id")
        if not isinstance(profile_id, str):
            return
        try:
            for account in await self.zernio.accounts(profile_id):
                await self.zernio.disconnect_account(account["id"])
            await self.zernio.delete_profile(profile_id)
        except IntegrationError:
            logger.warning("Zernio cleanup for project %s did not finish", connection.project_id)
