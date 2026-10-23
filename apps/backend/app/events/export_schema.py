"""Export the event contract as JSON Schema for the renderer's generated TypeScript types.

Usage: python -m app.events.export_schema <output.json>
"""

import json
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, create_model

from app.events.schema import PAYLOADS, SCHEMA_VERSION


class _Envelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1]
    event_id: uuid.UUID
    run_id: uuid.UUID
    seq: int
    ts: datetime
    agent_id: str | None
    task_id: uuid.UUID | None


def _event_models() -> list[type[BaseModel]]:
    models = []
    for event_type, payload in PAYLOADS.items():
        name = "".join(part.title() for part in event_type.value.split("_")) + "Event"
        models.append(
            create_model(
                name,
                __base__=_Envelope,
                type=(Literal[event_type.value], ...),  # type: ignore[valid-type]
                payload=(payload, ...),
            )
        )
    return models


def _strip_property_titles(node: Any) -> None:
    """Pydantic titles every property; json2ts would turn each into a named alias type."""
    if isinstance(node, dict):
        for prop in node.get("properties", {}).values():
            prop.pop("title", None)
        for value in node.values():
            _strip_property_titles(value)
    elif isinstance(node, list):
        for item in node:
            _strip_property_titles(item)


def build_schema() -> dict[str, Any]:
    union = Annotated[Union[tuple(_event_models())], Field(discriminator="type")]  # noqa: UP007
    # Serialization mode: fields with defaults are always present in events we send.
    schema = TypeAdapter(union).json_schema(ref_template="#/$defs/{model}", mode="serialization")
    _strip_property_titles(schema)
    schema["title"] = "AgentEvent"
    schema["description"] = f"H.E.X Mind agent event, schema version {SCHEMA_VERSION}."
    return schema


def render() -> str:
    return json.dumps(build_schema(), indent=2, sort_keys=True) + "\n"


if __name__ == "__main__":
    Path(sys.argv[1]).write_text(render(), encoding="utf-8", newline="\n")
