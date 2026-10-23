"""Rolling conversation summary (plan §3.4): older turns are folded into `conversations.summary`
so the context bundle stays bounded while long conversations keep their decisions."""

import asyncio
import uuid
from collections import defaultdict

from sqlalchemy import func, select

from app.context.manager import RECENT_MESSAGES, SUMMARY_BATCH
from app.context.redact import redact
from app.db.models import Conversation, Message
from app.graph.services import Services
from app.providers.base import ChatMessage, LLMRequest

# Summarize once at least this many messages have aged out of the recent window.
MIN_BATCH = SUMMARY_BATCH

_locks: defaultdict[uuid.UUID, asyncio.Lock] = defaultdict(asyncio.Lock)

PROMPT = """Update the running summary of a coding conversation between a developer and the
H.E.X Mind IDE agents. Keep decisions, requirements, constraints, file names and open questions.
Drop pleasantries. At most 200 words. Reply with the summary text only."""


async def maybe_update_summary(services: Services, conversation_id: uuid.UUID) -> bool:
    """Returns True if the summary was updated."""
    async with _locks[conversation_id]:
        async with services.sessionmaker() as session:
            conversation = await session.get(Conversation, conversation_id)
            if conversation is None:
                return False
            total = await session.scalar(
                select(func.count()).where(Message.conversation_id == conversation_id)
            )
            pending = (total or 0) - RECENT_MESSAGES - conversation.summary_message_count
            if pending < MIN_BATCH:
                return False
            batch = list(
                await session.scalars(
                    select(Message)
                    .where(Message.conversation_id == conversation_id)
                    .order_by(Message.created_at)
                    .offset(conversation.summary_message_count)
                    .limit(pending)
                )
            )
            previous = conversation.summary

        transcript = "\n".join(f"{m.role}: {redact(m.content)}" for m in batch)
        result = await services.providers.complete(
            LLMRequest(
                purpose="summary",
                messages=[
                    ChatMessage(role="system", content=PROMPT),
                    ChatMessage(
                        role="user",
                        content=(
                            f"Current summary:\n{previous or '(none)'}\n\nNew turns:\n{transcript}"
                        ),
                    ),
                ],
                max_tokens=400,
            )
        )
        if not result.ok or not result.content:
            return False

        async with services.sessionmaker.begin() as session:
            conversation = await session.get(Conversation, conversation_id)
            assert conversation is not None
            conversation.summary = result.content.strip()
            conversation.summary_message_count += len(batch)
        return True
