import uuid
from dataclasses import dataclass

from sqlalchemy import func

from app.context.summary import maybe_update_summary
from app.db.models import Conversation, Message
from app.graph.conversation import build_conversation_graph
from app.graph.services import Services
from app.router.schemas import Mode

DEFAULT_TITLE = "New conversation"


@dataclass
class Exchange:
    user_message: Message
    assistant_message: Message
    run_id: uuid.UUID | None


class ChatService:
    def __init__(self, services: Services) -> None:
        self._services = services
        self._graph = build_conversation_graph(services)

    async def handle_message(
        self, conversation_id: uuid.UUID, content: str, mode: Mode
    ) -> Exchange:
        sessionmaker = self._services.sessionmaker

        # Persist the user's message first so it survives any later failure.
        async with sessionmaker.begin() as session:
            conversation = await session.get(Conversation, conversation_id)
            if conversation is None:
                raise LookupError("conversation not found")
            user_message = Message(
                conversation_id=conversation_id, role="user", mode=mode, content=content
            )
            session.add(user_message)
            if conversation.title == DEFAULT_TITLE:
                conversation.title = _title(content)
            conversation.updated_at = func.clock_timestamp()
            await session.flush()
            project_id = conversation.project_id

        state = await self._graph.ainvoke(
            {
                "conversation_id": conversation_id,
                "project_id": project_id,
                "message_id": user_message.id,
                "content": content,
                "mode": mode,
            }
        )

        plan = state["plan"]
        async with sessionmaker.begin() as session:
            assistant_message = Message(
                conversation_id=conversation_id,
                role="assistant",
                content=state["reply"],
                meta={
                    "kind": state["reply_kind"],
                    "route": {
                        "route": plan.route,
                        "request_type": plan.request_type,
                        "complexity": plan.complexity,
                        "confidence": plan.confidence,
                        "strategy": plan.strategy,
                        "fallback_used": plan.fallback_used,
                        "policy_note": plan.policy_note,
                        "reason": plan.reason,
                        "decision_id": str(state["decision_id"]),
                    },
                    "context": state["context_sources"],
                    "llm": state.get("llm"),
                    "run_id": str(state["run_id"]) if state.get("run_id") else None,
                },
            )
            session.add(assistant_message)
            await session.flush()

        self._services.background.spawn(
            maybe_update_summary(self._services, conversation_id),
            name=f"summary-{conversation_id}",
        )
        return Exchange(user_message, assistant_message, state.get("run_id"))


def _title(content: str) -> str:
    line = content.strip().splitlines()[0] if content.strip() else DEFAULT_TITLE
    return line if len(line) <= 60 else line[:57] + "…"
