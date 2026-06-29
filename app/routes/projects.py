from fastapi import APIRouter, Depends

from app.core.security import require_role
from app.schemas.auth_schema import CurrentUser, UserRole
from app.schemas.project_schema import ProjectCreateRequest, ProjectResponse, ProjectStatusUpdateRequest, ProjectUpdateRequest
from app.services.project_service import (
    create_project,
    get_my_project_by_id,
    list_my_projects,
    update_my_project,
    update_project_status,
)

router = APIRouter(tags=["Projects"])


@router.post("/projects", response_model=ProjectResponse)
async def post_project(
    payload: ProjectCreateRequest,
    current_user: CurrentUser = Depends(require_role(UserRole.PRODUCER)),
):
    return create_project(payload, current_user)


@router.get("/projects/me", response_model=list[ProjectResponse])
async def get_projects_me(
    current_user: CurrentUser = Depends(require_role(UserRole.PRODUCER)),
):
    return list_my_projects(current_user)


@router.get("/projects/{project_id}", response_model=ProjectResponse)
async def get_project_detail(
    project_id: str,
    current_user: CurrentUser = Depends(require_role(UserRole.PRODUCER)),
):
    return get_my_project_by_id(project_id, current_user)


@router.put("/projects/{project_id}", response_model=ProjectResponse)
async def put_project(
    project_id: str,
    payload: ProjectUpdateRequest,
    current_user: CurrentUser = Depends(require_role(UserRole.PRODUCER)),
):
    return update_my_project(project_id, payload, current_user)


@router.patch("/projects/{project_id}/status", response_model=ProjectResponse)
async def patch_project_status(
    project_id: str,
    payload: ProjectStatusUpdateRequest,
    current_user: CurrentUser = Depends(require_role(UserRole.PRODUCER)),
):
    return update_project_status(project_id, payload, current_user)
