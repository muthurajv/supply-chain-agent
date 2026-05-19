"""Cosmos DB checkpointer for LangGraph state persistence.

Enables paused approvals to resume hours later with full graph state restored.
"""
import base64
import json
from typing import Any, Iterator, AsyncIterator, Optional, Tuple
from datetime import datetime
from azure.cosmos.aio import CosmosClient
from azure.cosmos import exceptions as cosmos_exceptions
from langgraph.checkpoint.base import (
    BaseCheckpointSaver,
    Checkpoint,
    CheckpointMetadata,
    CheckpointTuple,
    get_checkpoint_id,
)
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from app.config import get_settings


def _sanitize(obj: Any) -> Any:
    """Recursively convert bytes values to base64 strings for Cosmos JSON storage."""
    if isinstance(obj, bytes):
        return {"__b64__": base64.b64encode(obj).decode()}
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize(v) for v in obj]
    return obj


def _restore(obj: Any) -> Any:
    """Reverse _sanitize — convert base64 markers back to bytes."""
    if isinstance(obj, dict):
        if set(obj.keys()) == {"__b64__"}:
            return base64.b64decode(obj["__b64__"])
        return {k: _restore(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_restore(v) for v in obj]
    return obj


class CosmosDBCheckpointer(BaseCheckpointSaver):
    """LangGraph checkpoint saver backed by Azure Cosmos DB."""

    serde = JsonPlusSerializer()

    def __init__(self):
        super().__init__()
        self._client: CosmosClient | None = None

    def _get_client(self) -> CosmosClient:
        if self._client is None:
            self._client = CosmosClient.from_connection_string(get_settings().cosmos_connection_string)
        return self._client

    async def _get_container(self):
        settings = get_settings()
        db = self._get_client().get_database_client(settings.cosmos_database)
        return db.get_container_client(settings.cosmos_container_checkpoints)

    async def aget_tuple(self, config: dict) -> Optional[CheckpointTuple]:
        thread_id = config["configurable"]["thread_id"]
        checkpoint_id = config["configurable"].get("checkpoint_id")
        container = await self._get_container()

        try:
            if checkpoint_id:
                item_id = f"{thread_id}:{checkpoint_id}"
                item = await container.read_item(item=item_id, partition_key=thread_id)
            else:
                query = (
                    "SELECT TOP 1 * FROM c WHERE c.thread_id = @thread_id ORDER BY c.ts DESC"
                )
                items = []
                async for i in container.query_items(
                    query=query,
                    parameters=[{"name": "@thread_id", "value": thread_id}],
                    partition_key=thread_id,
                ):
                    items.append(i)
                if not items:
                    return None
                item = items[0]
        except cosmos_exceptions.CosmosResourceNotFoundError:
            return None

        raw = _restore(item["checkpoint"])
        checkpoint = self.serde.loads_typed((item["type"], raw))
        metadata = CheckpointMetadata(**json.loads(item.get("metadata", "{}")))
        config_out = {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_id": item["checkpoint_id"],
            }
        }
        parent_config = None
        if item.get("parent_checkpoint_id"):
            parent_config = {
                "configurable": {
                    "thread_id": thread_id,
                    "checkpoint_id": item["parent_checkpoint_id"],
                }
            }
        return CheckpointTuple(config=config_out, checkpoint=checkpoint, metadata=metadata, parent_config=parent_config)

    async def aput(
        self,
        config: dict,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: Any,
    ) -> dict:
        thread_id = config["configurable"]["thread_id"]
        checkpoint_id = checkpoint["id"]
        parent_checkpoint_id = config["configurable"].get("checkpoint_id")
        type_, serialized = self.serde.dumps_typed(checkpoint)
        # Cosmos DB cannot store raw bytes — encode all bytes recursively.
        checkpoint_stored = _sanitize(serialized)

        container = await self._get_container()
        item = _sanitize({
            "id": f"{thread_id}:{checkpoint_id}",
            "thread_id": thread_id,
            "checkpoint_id": checkpoint_id,
            "parent_checkpoint_id": parent_checkpoint_id,
            "type": type_,
            "checkpoint": checkpoint_stored,
            "metadata": json.dumps(dict(metadata)),
            "ts": datetime.utcnow().isoformat(),
        })
        await container.upsert_item(item)
        return {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_id": checkpoint_id,
            }
        }

    async def aput_writes(self, config: dict, writes: list, task_id: str) -> None:
        pass

    def get_tuple(self, config: dict) -> Optional[CheckpointTuple]:
        raise NotImplementedError("Use aget_tuple for async access")

    def list(self, config: dict, **kwargs) -> Iterator[CheckpointTuple]:
        raise NotImplementedError("Use alist for async access")

    def put(self, config: dict, checkpoint: Checkpoint, metadata: CheckpointMetadata, new_versions: Any) -> dict:
        raise NotImplementedError("Use aput for async access")
