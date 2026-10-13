"""Zernio, the provider behind LinkedIn posting: fixed, bounded operations on Tin's account.

Tin holds one Zernio key (`TIN_LITE_ZERNIO_API_KEY`) on the switchboard. It never reaches a
sandbox, package, project file, log or Temporal history. Every operation names a fixed path,
and callers pass the profile and account IDs held by the project's connection, never IDs
taken from a request: one key acts on every project's LinkedIn, so that mapping is the
boundary. See docs/linkedin-posting.md.
"""

from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

import httpx

from tin_lite.connection_records import read_bounded_json
from tin_lite.integrations import (
    IntegrationAuthorizationError,
    IntegrationDeliveryUnknownError,
    IntegrationNotConfiguredError,
    IntegrationRateLimitedError,
    IntegrationUpstreamError,
    ServiceCallRefused,
)

logger = logging.getLogger(__name__)

API = "https://zernio.com/api/v1"
MAX_RESPONSE_BYTES = 256_000
TIMEOUT_SECONDS = 20.0
# Zernio's media host refuses Python's default user agent.
USER_AGENT = "Tin (+https://tin.computer)"
# Posting now; comments and analytics are asked for once so later reads need no second consent.
SCOPES = "posting,analytics,comments"
ID = re.compile(r"^[0-9a-f]{24}$")
ORGANIZATION_URN = re.compile(r"^urn:li:organization:[0-9]{1,20}$")
PERSON_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
CONNECT_HOSTS = {"www.linkedin.com", "linkedin.com", "zernio.com"}
UNAVAILABLE = "LinkedIn posting is temporarily unavailable"


def ready(settings: Any) -> bool:
    return getattr(settings, "zernio_api_key", None) is not None


def profile_name(project_id: UUID) -> str:
    return f"tin:{project_id}"


def zernio_id(value: Any) -> str:
    if not isinstance(value, str) or not ID.fullmatch(value):
        raise IntegrationUpstreamError("Zernio returned an invalid identifier")
    return value


def linkedin_account(value: Any) -> dict[str, Any] | None:
    """What Tin keeps of one Zernio account, or None when it is not a usable LinkedIn one."""

    if not isinstance(value, dict) or value.get("platform") != "linkedin":
        return None
    account_id = value.get("_id")
    metadata = value.get("metadata")
    if not isinstance(account_id, str) or not ID.fullmatch(account_id):
        return None
    if not isinstance(metadata, dict):
        return None
    kind = metadata.get("accountType")
    if kind == "organization":
        organization = metadata.get("organizationInfo")
        if not isinstance(organization, dict):
            return None
        urn = organization.get("urn")
        if not isinstance(urn, str) or not ORGANIZATION_URN.fullmatch(urn):
            return None
        name = organization.get("name") or value.get("displayName")
    elif kind == "personal":
        profile = metadata.get("profileData")
        person = profile.get("id") if isinstance(profile, dict) else None
        if not isinstance(person, str) or not PERSON_ID.fullmatch(person):
            return None
        urn = f"urn:li:person:{person}"
        name = value.get("displayName")
    else:
        return None
    if not isinstance(name, str) or not name.strip():
        name = "LinkedIn page" if kind == "organization" else "LinkedIn profile"
    return {
        "id": account_id,
        "urn": urn,
        "kind": kind,
        "name": " ".join(name.split())[:100],
        "active": value.get("isActive") is True and value.get("enabled", True) is not False,
    }


class Zernio:
    def __init__(self, client: httpx.AsyncClient, settings: Any) -> None:
        key = getattr(settings, "zernio_api_key", None)
        if key is None:
            raise IntegrationNotConfiguredError(
                "LinkedIn posting is not configured on this Tin deployment"
            )
        self._client = client
        self._key = key.get_secret_value()

    async def _call(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
        body: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
        write: bool = False,
    ) -> tuple[int, Any]:
        """One request; returns status and parsed body for 2xx and 4xx answers.

        A write whose answer is lost raises IntegrationDeliveryUnknownError, so callers holding
        a receipt never send it again on their own. Reads fail as ordinary upstream errors.
        """

        headers = {
            "Authorization": f"Bearer {self._key}",
            "Accept": "application/json",
            "Accept-Encoding": "identity",
            "User-Agent": USER_AGENT,
        }
        if idempotency_key is not None:
            headers["Idempotency-Key"] = idempotency_key
        lost = IntegrationDeliveryUnknownError if write else IntegrationUpstreamError
        try:
            async with self._client.stream(
                method,
                f"{API}{path}",
                params=params,
                json=body,
                headers=headers,
                follow_redirects=False,
                timeout=TIMEOUT_SECONDS,
            ) as response:
                status = response.status_code
                if status >= 500:
                    raise lost(UNAVAILABLE)
                try:
                    payload = await read_bounded_json(
                        response, maximum=MAX_RESPONSE_BYTES, provider="Zernio"
                    )
                except (IntegrationUpstreamError, ServiceCallRefused):
                    if 200 <= status < 300:
                        raise lost(UNAVAILABLE) from None
                    payload = None
        except httpx.HTTPError:
            raise lost(UNAVAILABLE) from None
        if status == 429:
            raw = response.headers.get("retry-after", "")
            raise IntegrationRateLimitedError(
                "Zernio is rate limiting LinkedIn posting; try again shortly",
                retry_after=min(int(raw), 3600) if raw.isdigit() else None,
            )
        if status == 401:
            # Tin's own key was refused; nothing a founder can fix.
            logger.warning("Zernio refused Tin's API key (%s %s)", method, path)
            raise IntegrationUpstreamError(UNAVAILABLE)
        if not (200 <= status < 300 or 400 <= status < 500):
            raise lost(UNAVAILABLE)
        return status, payload

    async def ensure_profile(self, project_id: UUID) -> str:
        """The project's one profile: created once, then found again by its unique name."""

        name = profile_name(project_id)
        status, payload = await self._call(
            "POST",
            "/profiles",
            body={"name": name, "externalId": str(project_id), "description": "Tin project"},
            idempotency_key=f"tin-profile-{project_id}",
        )
        if status in {200, 201} and isinstance(payload, dict):
            profile = payload.get("profile")
            if isinstance(profile, dict):
                return zernio_id(profile.get("_id"))
        if status == 409:
            details = payload.get("details") if isinstance(payload, dict) else None
            existing = details.get("existingProfileId") if isinstance(details, dict) else None
            if isinstance(existing, str) and ID.fullmatch(existing):
                return existing
            found = await self.find_profile(project_id)
            if found is not None:
                return found
        logger.warning("Zernio did not create the project profile (status %s)", status)
        raise IntegrationUpstreamError(UNAVAILABLE)

    async def find_profile(self, project_id: UUID) -> str | None:
        status, payload = await self._call(
            "GET", "/profiles", params={"name": profile_name(project_id), "limit": "2"}
        )
        if status != 200 or not isinstance(payload, dict):
            raise IntegrationUpstreamError(UNAVAILABLE)
        profiles = payload.get("profiles")
        if not isinstance(profiles, list):
            raise IntegrationUpstreamError(UNAVAILABLE)
        for profile in profiles:
            if (
                isinstance(profile, dict)
                and profile.get("name") == profile_name(project_id)
                and profile.get("externalId", str(project_id)) == str(project_id)
            ):
                return zernio_id(profile.get("_id"))
        return None

    async def connect_url(self, profile_id: str, *, redirect: str) -> str:
        status, payload = await self._call(
            "GET",
            "/connect/linkedin",
            params={"profileId": zernio_id(profile_id), "scopes": SCOPES, "redirect_url": redirect},
        )
        url = payload.get("authUrl") if status == 200 and isinstance(payload, dict) else None
        if not isinstance(url, str) or len(url) > 4096:
            raise IntegrationUpstreamError(UNAVAILABLE)
        parts = urlsplit(url)
        if parts.scheme != "https" or parts.hostname not in CONNECT_HOSTS:
            raise IntegrationUpstreamError(UNAVAILABLE)
        return url

    async def accounts(self, profile_id: str) -> list[dict[str, Any]]:
        """The LinkedIn accounts in this profile, and only those."""

        profile_id = zernio_id(profile_id)
        status, payload = await self._call(
            "GET", "/accounts", params={"profileId": profile_id, "platform": "linkedin"}
        )
        if status != 200 or not isinstance(payload, dict):
            raise IntegrationUpstreamError(UNAVAILABLE)
        values = payload.get("accounts")
        if not isinstance(values, list):
            raise IntegrationUpstreamError(UNAVAILABLE)
        accounts = []
        for value in values[:100]:
            owner = value.get("profileId") if isinstance(value, dict) else None
            owner_id = owner.get("_id") if isinstance(owner, dict) else owner
            if owner_id is not None and owner_id != profile_id:
                continue
            account = linkedin_account(value)
            if account is not None:
                accounts.append(account)
        return accounts

    async def disconnect_account(self, account_id: str) -> None:
        status, _ = await self._call("DELETE", f"/accounts/{zernio_id(account_id)}", write=True)
        if status not in {200, 204, 404}:
            raise IntegrationUpstreamError(UNAVAILABLE)

    async def delete_profile(self, profile_id: str) -> None:
        status, _ = await self._call("DELETE", f"/profiles/{zernio_id(profile_id)}", write=True)
        if status not in {200, 204, 404}:
            raise IntegrationAuthorizationError(
                "Zernio kept the profile; disconnect its accounts first"
            )
