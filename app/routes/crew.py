from fastapi import APIRouter, Depends

from app.core.security import get_current_user, require_role
from app.schemas.auth_schema import CurrentUser, UserRole
from app.schemas.crew_schema import (
    CrewConversationResponse,
    CrewMemberResponse,
    CrewMemberUpdateRequest,
    CrewMessageCreateRequest,
    CrewMessageResponse,
)
from app.services.crew_service import (
    create_crew_message,
    list_crew_messages,
    list_message_conversations,
    list_producer_crew,
    list_talent_crew,
    update_crew_member,
)

router = APIRouter(tags=["Crew"])


@router.get("/producer/crew", response_model=list[CrewMemberResponse])
async def get_producer_crew(
    current_user: CurrentUser = Depends(require_role(UserRole.PRODUCER)),
):
    return list_producer_crew(current_user)


@router.get("/talent/crew", response_model=list[CrewMemberResponse])
async def get_talent_crew(
    current_user: CurrentUser = Depends(require_role(UserRole.TALENT)),
):
    return list_talent_crew(current_user)


@router.patch("/crew/{crew_member_id}", response_model=CrewMemberResponse)
async def patch_crew_member(
    crew_member_id: str,
    payload: CrewMemberUpdateRequest,
    current_user: CurrentUser = Depends(require_role(UserRole.PRODUCER)),
):
    return update_crew_member(crew_member_id, payload, current_user)


@router.post("/crew/{crew_member_id}/messages", response_model=CrewMessageResponse)
async def post_crew_message(
    crew_member_id: str,
    payload: CrewMessageCreateRequest,
    current_user: CurrentUser = Depends(get_current_user),
):
    return create_crew_message(crew_member_id, payload, current_user)


@router.get("/crew/{crew_member_id}/messages", response_model=list[CrewMessageResponse])
async def get_crew_messages(
    crew_member_id: str,
    current_user: CurrentUser = Depends(get_current_user),
):
    return list_crew_messages(crew_member_id, current_user)


@router.get("/messages/conversations", response_model=list[CrewConversationResponse])
async def get_message_conversations(
    current_user: CurrentUser = Depends(get_current_user),
):
    return list_message_conversations(current_user)
