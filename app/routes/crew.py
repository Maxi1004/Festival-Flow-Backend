from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile

from app.core.security import get_current_user, require_role
from app.schemas.auth_schema import CurrentUser, UserRole
from app.schemas.crew_schema import (
    CrewDirectMessageResponse,
    CrewConversationResponse,
    CrewMemberResponse,
    CrewMemberUpdateRequest,
    CrewMessageCreateRequest,
    CrewMessageResponse,
    CrewProjectCrmResponse,
    MessageConversationFeedResponse,
    MessageConversationInfoResponse,
    ProjectChatMessageResponse,
    ProjectCrewMemberResponse,
    ProjectCrewMembersResponse,
    ProjectMessageCreateRequest,
    TalentCrewFeedResponse,
    TalentCrewFeedSummary,
    TeamChatPhotoResponse,
    TeamChatSettingsUpdateRequest,
    UnifiedConversationMessageResponse,
)
from app.services.crew_service import (
    create_direct_message,
    create_crew_message,
    create_project_chat_message,
    create_unified_conversation_message,
    get_unified_conversation_info,
    get_talent_crew_summary,
    list_crew_messages,
    list_direct_messages,
    list_message_conversations,
    list_my_message_conversations,
    list_producer_crew,
    list_producer_crew_crm,
    list_project_chat_messages,
    list_project_members,
    list_talent_crew_feed,
    list_talent_crew,
    list_unified_conversation_messages,
    remove_project_crew_member,
    update_team_conversation_settings,
    update_team_conversation_photo,
    update_crew_member,
    update_project_crew_member,
    validate_team_conversation_photo_access,
)
from app.services.cloudinary_service import CloudinaryUploadError, upload_project_team_chat_photo

router = APIRouter(tags=["Crew"])

ALLOWED_TEAM_PHOTO_TYPES = {"image/jpeg", "image/png", "image/webp"}
MAX_TEAM_PHOTO_SIZE = 5 * 1024 * 1024


@router.get("/producer/crew", response_model=list[CrewMemberResponse])
async def get_producer_crew(
    current_user: CurrentUser = Depends(require_role(UserRole.PRODUCER)),
):
    return list_producer_crew(current_user)


@router.get("/crew/me/crm", response_model=list[CrewProjectCrmResponse])
async def get_producer_crew_crm(
    summary: bool = Query(default=True),
    current_user: CurrentUser = Depends(require_role(UserRole.PRODUCER)),
):
    return list_producer_crew_crm(current_user, summary=summary)


@router.get("/talent/crew", response_model=list[CrewMemberResponse])
async def get_talent_crew(
    current_user: CurrentUser = Depends(require_role(UserRole.TALENT)),
):
    return list_talent_crew(current_user)


@router.get("/crew/me/feed", response_model=TalentCrewFeedResponse)
async def get_talent_crew_feed(
    limit: int = Query(default=10, ge=1, le=50),
    cursor: str | None = Query(default=None),
    summary: bool = Query(default=True),
    current_user: CurrentUser = Depends(require_role(UserRole.TALENT)),
):
    return list_talent_crew_feed(current_user, limit=limit, cursor=cursor, include_summary=summary)


@router.get("/crew/me/summary", response_model=TalentCrewFeedSummary)
async def get_talent_crew_feed_summary(
    current_user: CurrentUser = Depends(require_role(UserRole.TALENT)),
):
    return get_talent_crew_summary(current_user)


@router.get("/crew/projects/{project_id}/members", response_model=ProjectCrewMembersResponse)
async def get_project_members(
    project_id: str,
    current_user: CurrentUser = Depends(get_current_user),
):
    return list_project_members(project_id, current_user)


@router.patch("/crew/projects/{project_id}/members/{member_id}", response_model=ProjectCrewMemberResponse)
async def patch_project_member(
    project_id: str,
    member_id: str,
    payload: CrewMemberUpdateRequest,
    current_user: CurrentUser = Depends(require_role(UserRole.PRODUCER)),
):
    return update_project_crew_member(project_id, member_id, payload, current_user)


@router.delete("/crew/projects/{project_id}/members/{member_id}", response_model=ProjectCrewMemberResponse)
async def delete_project_member(
    project_id: str,
    member_id: str,
    current_user: CurrentUser = Depends(require_role(UserRole.PRODUCER)),
):
    return remove_project_crew_member(project_id, member_id, current_user)


@router.get("/crew/projects/{project_id}/team-chat/messages", response_model=list[ProjectChatMessageResponse])
async def get_project_team_chat_messages(
    project_id: str,
    current_user: CurrentUser = Depends(get_current_user),
):
    return list_project_chat_messages(project_id, current_user)


@router.post("/crew/projects/{project_id}/team-chat/messages", response_model=ProjectChatMessageResponse)
async def post_project_team_chat_message(
    project_id: str,
    payload: ProjectMessageCreateRequest,
    current_user: CurrentUser = Depends(get_current_user),
):
    return create_project_chat_message(project_id, payload, current_user)


@router.get("/crew/projects/{project_id}/direct-messages/{other_user_uid}", response_model=list[CrewDirectMessageResponse])
async def get_project_direct_messages(
    project_id: str,
    other_user_uid: str,
    current_user: CurrentUser = Depends(get_current_user),
):
    return list_direct_messages(project_id, other_user_uid, current_user)


@router.post("/crew/projects/{project_id}/direct-messages/{other_user_uid}", response_model=CrewDirectMessageResponse)
async def post_project_direct_message(
    project_id: str,
    other_user_uid: str,
    payload: ProjectMessageCreateRequest,
    current_user: CurrentUser = Depends(get_current_user),
):
    return create_direct_message(project_id, other_user_uid, payload, current_user)


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


@router.get("/messages/me/conversations", response_model=MessageConversationFeedResponse)
async def get_my_message_conversations(
    limit: int = Query(default=20, ge=1, le=50),
    cursor: str | None = Query(default=None),
    current_user: CurrentUser = Depends(get_current_user),
):
    return list_my_message_conversations(current_user, limit=limit, cursor=cursor)


@router.get(
    "/messages/me/conversations/{conversation_id}/messages",
    response_model=list[UnifiedConversationMessageResponse],
)
async def get_unified_conversation_messages(
    conversation_id: str,
    limit: int = Query(default=50, ge=1, le=50),
    current_user: CurrentUser = Depends(get_current_user),
):
    return list_unified_conversation_messages(conversation_id, current_user, limit=limit)


@router.post(
    "/messages/me/conversations/{conversation_id}/messages",
    response_model=UnifiedConversationMessageResponse,
)
async def post_unified_conversation_message(
    conversation_id: str,
    payload: ProjectMessageCreateRequest,
    current_user: CurrentUser = Depends(get_current_user),
):
    return create_unified_conversation_message(conversation_id, payload, current_user)


@router.get(
    "/messages/me/conversations/{conversation_id}/info",
    response_model=MessageConversationInfoResponse,
)
async def get_unified_conversation_info_route(
    conversation_id: str,
    current_user: CurrentUser = Depends(get_current_user),
):
    return get_unified_conversation_info(conversation_id, current_user)


@router.patch(
    "/messages/me/conversations/{conversation_id}/team-settings",
    response_model=MessageConversationInfoResponse,
)
async def patch_team_conversation_settings(
    conversation_id: str,
    payload: TeamChatSettingsUpdateRequest,
    current_user: CurrentUser = Depends(get_current_user),
):
    return update_team_conversation_settings(conversation_id, payload, current_user)


@router.post(
    "/messages/me/conversations/{conversation_id}/team-photo",
    response_model=TeamChatPhotoResponse,
)
async def post_team_conversation_photo(
    conversation_id: str,
    file: UploadFile = File(...),
    current_user: CurrentUser = Depends(get_current_user),
):
    project_id = validate_team_conversation_photo_access(conversation_id, current_user)

    if file.content_type not in ALLOWED_TEAM_PHOTO_TYPES:
        raise HTTPException(
            status_code=415,
            detail="La foto debe ser una imagen JPEG, PNG o WebP.",
        )

    try:
        image_data = await file.read(MAX_TEAM_PHOTO_SIZE + 1)
    finally:
        await file.close()

    if not image_data:
        raise HTTPException(status_code=400, detail="La foto esta vacia.")

    if len(image_data) > MAX_TEAM_PHOTO_SIZE:
        raise HTTPException(
            status_code=413,
            detail="La foto supera el tamano maximo permitido de 5 MB.",
        )

    try:
        photo_url = upload_project_team_chat_photo(project_id, image_data)
    except CloudinaryUploadError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error

    return update_team_conversation_photo(conversation_id, photo_url, current_user)
