"""code.storage ref-update rejections reach members and agents as invalid or conflict."""

from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from pierre_storage.errors import RefUpdateError

from tin_lite.code_storage import CodeStorage
from tin_lite.mcp_errors import tool_error
from tin_lite.project_files import ProjectFileService, StaleProjectRevisionError

HEAD = "a" * 40
CHANGES = [{"operation": "upsert", "path": "notes.md", "content": "same as before"}]


class RejectingRepo:
    def __init__(self, error: RefUpdateError) -> None:
        self.error = error

    async def list_files(self, **values) -> dict:
        return {"paths": ["notes.md"]}

    async def list_commits(self, **values) -> dict:
        return {"commits": [{"sha": HEAD, "message": "an earlier commit"}]}

    def create_commit(self, **values):
        error = self.error

        class Builder:
            def add_file_from_string(self, path: str, content: str):
                return self

            async def send(self) -> dict:
                raise error

        return Builder()


def storage_rejecting(monkeypatch: pytest.MonkeyPatch, error: RefUpdateError) -> CodeStorage:
    pem = (
        ec.generate_private_key(ec.SECP256R1())
        .private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        .decode()
    )
    storage = CodeStorage(organization="tin", private_key=pem)
    repo = RejectingRepo(error)

    async def get_repo(repo_id: str):
        return repo

    async def head_sha(repo, branch: str):
        return HEAD

    monkeypatch.setattr(storage, "get_repo", get_repo)
    monkeypatch.setattr(storage, "head_sha", head_sha)
    return storage


def file_service(storage: CodeStorage):
    @asynccontextmanager
    async def lock(**values):
        yield

    database = SimpleNamespace(
        project_file_change_lock=lock,
        get_project_file_change=AsyncMock(return_value=None),
        start_project_file_change=AsyncMock(),
        fail_project_file_change=AsyncMock(),
        complete_project_file_change=AsyncMock(),
    )
    return ProjectFileService(database=database, storage=storage), database  # type: ignore[arg-type]


async def commit(service):
    project = SimpleNamespace(id=uuid4(), state_repo_id="projects/p", canonical_branch="main")
    return await service.commit(
        project=project,
        actor_clerk_user_id="user_member",
        client_id=None,
        request_id=uuid4(),
        expected_revision=HEAD,
        message="tick the plan",
        changes=CHANGES,
    )


@pytest.mark.asyncio
async def test_no_changes_is_invalid_and_the_request_is_not_left_started(monkeypatch):
    storage = storage_rejecting(monkeypatch, RefUpdateError("no changes to commit"))
    service, database = file_service(storage)
    with pytest.raises(ValueError, match="no changes") as caught:
        await commit(service)
    assert str(tool_error(caught.value)) == (
        "invalid: no changes: files already match expected_revision"
    )
    assert database.fail_project_file_change.await_args.kwargs["error_code"] == "invalid"
    database.complete_project_file_change.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error",
    [
        RefUpdateError("expected head moved", status="409", reason="conflict"),
        RefUpdateError("precondition failed", status="precondition_failed"),
    ],
)
async def test_ref_conflict_is_a_stale_revision(monkeypatch, error):
    service, database = file_service(storage_rejecting(monkeypatch, error))
    with pytest.raises(StaleProjectRevisionError) as caught:
        await commit(service)
    assert str(tool_error(caught.value)).startswith("conflict: canonical project state changed")
    assert database.fail_project_file_change.await_args.kwargs["error_code"] == "stale_revision"


@pytest.mark.asyncio
async def test_other_ref_rejection_is_recorded_as_a_storage_failure(monkeypatch):
    error = RefUpdateError("upstream unavailable", status="503", reason="unavailable")
    service, database = file_service(storage_rejecting(monkeypatch, error))
    with pytest.raises(RuntimeError, match=r"rejected the project file commit \(unavailable\)"):
        await commit(service)
    assert database.fail_project_file_change.await_args.kwargs["error_code"] == "storage_failed"
