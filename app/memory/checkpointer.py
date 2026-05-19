"""Cosmos DB checkpointer for LangGraph state persistence.

Enables paused approvals to resume hours later with full graph state restored.
"""
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

        checkpoint = self.serde.loads_typed((item["type"], item["checkpoint"]))
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

        container = await self._get_container()
        item = {
            "id": f"{thread_id}:{checkpoint_id}",
            "thread_id": thread_id,
            "checkpoint_id": checkpoint_id,
            "parent_checkpoint_id": parent_checkpoint_id,
            "type": type_,
            "checkpoint": serialized,
            "metadata": json.dumps(dict(metadata)),
            "ts": datetime.utcnow().isoformat(),
        }
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
