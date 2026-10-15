"""The People view's HTTP reads, and forgetting a person (#435).

Project members read and forget a project's people; Tin's own workflows write them. A score
computed under an older ICP file comes back marked stale.
"""

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from tin_lite import linkedin_engagers as engagers
from tin_lite import people_records as records
from tin_lite.auth import AuthContext, require_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/projects/{project_id}/people")
USER = Depends(require_user)
LIMIT = 5000


async def _project(request: Request, project_id: UUID, user: AuthContext):
    database = request.app.state.runtime.database
    if not await database.has_project_access(
        project_id=project_id, clerk_user_id=user.clerk_user_id
    ):
        raise HTTPException(404, "project not found")
    project = await database.get_project(project_id)
    if project is None:
        raise HTTPException(404, "project not found")
    return project


async def _icp(request: Request, project) -> dict:
    try:
        return await engagers.read_icp(request.app.state.runtime.storage, project)
    except Exception as error:  # noqa: BLE001
        # Without the ICP file nothing is marked stale; the people and scores still show.
        logger.warning("People view couldn't read the ICP of %s: %s", project.id, type(error))
        return {}


@router.get("")
async def list_people(project_id: UUID, request: Request, user: AuthContext = USER):
    project = await _project(request, project_id, user)
    icp = await _icp(request, project)
    async with request.app.state.runtime.database.pool.acquire() as conn:
        people = await records.directory(
            conn,
            project.id,
            viewer=user.clerk_user_id,
            definition=icp.get("definition", ""),
            limit=LIMIT + 1,
        )
    return {
        "people": people[:LIMIT],
        "truncated": len(people) > LIMIT,
        "fit_shown": engagers.FIT_SHOWN,
    }


@router.get("/{person_id}")
async def get_person(project_id: UUID, person_id: UUID, request: Request, user: AuthContext = USER):
    project = await _project(request, project_id, user)
    icp = await _icp(request, project)
    async with request.app.state.runtime.database.pool.acquire() as conn:
        found = await records.person(
            conn,
            project.id,
            person_id,
            viewer=user.clerk_user_id,
            definition=icp.get("definition", ""),
        )
    if found is None:
        raise HTTPException(404, "This person is no longer in this project.")
    return found


@router.delete("/{person_id}", status_code=204)
async def forget_person(
    project_id: UUID, person_id: UUID, request: Request, user: AuthContext = USER
):
    project = await _project(request, project_id, user)
    async with request.app.state.runtime.database.pool.acquire() as conn:
        if not await records.forget(conn, project.id, person_id):
            raise HTTPException(404, "This person is no longer in this project.")
    return Response(status_code=204)
