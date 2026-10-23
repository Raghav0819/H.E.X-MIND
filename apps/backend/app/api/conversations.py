import uuid

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import select

from app.api.deps import SessionDep
from app.api.schemas import (
    ConversationCreate,
    ConversationOut,
    MessageCreate,
    MessageExchangeOut,
    MessageOut,
)
from app.chat.service import DEFAULT_TITLE, ChatService
from app.db.models import Conversation, Message, Project

router = APIRouter(tags=["conversations"])


async def _get_conversation(session: SessionDep, conversation_id: uuid.UUID) -> Conversation:
    conversation = await session.get(Conversation, conversation_id)
    if conversation is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "conversation not found")
    return conversation


@router.get("/projects/{project_id}/conversations", response_model=list[ConversationOut])
async def list_conversations(project_id: uuid.UUID, session: SessionDep) -> list[Conversation]:
    result = await session.scalars(
        select(Conversation)
        .where(Conversation.project_id == project_id)
        .order_by(Conversation.updated_at.desc())
        .limit(50)
    )
    return list(result)


@router.post(
    "/projects/{project_id}/conversations",
    response_model=ConversationOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_conversation(
    project_id: uuid.UUID, body: ConversationCreate, session: SessionDep
) -> Conversation:
    if await session.get(Project, project_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "project not found")
    conversation = Conversation(project_id=project_id, title=body.title or DEFAULT_TITLE)
    session.add(conversation)
    await session.flush()
    await session.refresh(conversation)
    return conversation


@router.get("/conversations/{conversation_id}", response_model=ConversationOut)
async def get_conversation(conversation_id: uuid.UUID, session: SessionDep) -> Conversation:
    return await _get_conversation(session, conversation_id)


@router.get("/conversations/{conversation_id}/messages", response_model=list[MessageOut])
async def list_messages(conversation_id: uuid.UUID, session: SessionDep) -> list[Message]:
    await _get_conversation(session, conversation_id)
    result = await session.scalars(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at)
    )
    return list(result)


@router.post("/conversations/{conversation_id}/messages", response_model=MessageExchangeOut)
async def send_message(
    conversation_id: uuid.UUID, body: MessageCreate, request: Request
) -> MessageExchangeOut:
    """Route the message and reply. Answers are synchronous; runs continue in the background."""
    chat: ChatService = request.app.state.chat
    try:
        exchange = await chat.handle_message(conversation_id, body.content, body.mode)
    except LookupError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "conversation not found") from None
    return MessageExchangeOut(
        user_message=MessageOut.model_validate(exchange.user_message),
        assistant_message=MessageOut.model_validate(exchange.assistant_message),
        run_id=exchange.run_id,
    )
