"""DynamoDB operations for cogamer state and messaging."""

from __future__ import annotations

from typing import Any

import boto3
from boto3.dynamodb.conditions import Key

from cogamer.models import CogamerState, Message


class CogamerDB:
    def __init__(self, table_name: str = "cogamer", session: boto3.Session | None = None):
        resource = (session or boto3).resource("dynamodb")  # pyright: ignore[reportAttributeAccessIssue]
        self._table: Any = resource.Table(table_name)

    def put_cogamer(self, state: CogamerState) -> None:
        item = state.model_dump()
        item["pk"] = f"COGAMER#{state.name}"
        item["sk"] = "META"
        self._table.put_item(Item=item)

    def get_cogamer(self, name: str) -> CogamerState | None:
        resp = self._table.get_item(Key={"pk": f"COGAMER#{name}", "sk": "META"})
        item = resp.get("Item")
        if not item:
            return None
        fields = {k: v for k, v in item.items() if k not in ("pk", "sk")}
        if "name" not in fields or "codebase" not in fields:
            return None
        return CogamerState(**fields)

    def update_cogamer(self, name: str, **fields: object) -> None:
        expr_parts = []
        names = {}
        values = {}
        for i, (k, v) in enumerate(fields.items()):
            expr_parts.append(f"#{k} = :v{i}")
            names[f"#{k}"] = k
            values[f":v{i}"] = v
        self._table.update_item(
            Key={"pk": f"COGAMER#{name}", "sk": "META"},
            UpdateExpression="SET " + ", ".join(expr_parts),
            ExpressionAttributeNames=names,
            ExpressionAttributeValues=values,
        )

    def delete_cogamer(self, name: str) -> None:
        resp = self._table.query(KeyConditionExpression=Key("pk").eq(f"COGAMER#{name}"))
        for item in resp.get("Items", []):
            self._table.delete_item(Key={"pk": item["pk"], "sk": item["sk"]})

    def list_cogamers(self) -> list[CogamerState]:
        resp = self._table.query(
            IndexName="gsi-sk",
            KeyConditionExpression=Key("sk").eq("META"),
        )
        results = []
        for item in resp.get("Items", []):
            fields = {k: v for k, v in item.items() if k not in ("pk", "sk")}
            if "name" not in fields or "codebase" not in fields:
                continue
            results.append(CogamerState(**fields))
        return results

    def put_message(self, cogamer_name: str, msg: Message) -> None:
        item = msg.model_dump()
        item["pk"] = f"COGAMER#{cogamer_name}"
        item["sk"] = f"MSG#{msg.channel_id}#{msg.timestamp}"
        self._table.put_item(Item=item)

    def get_all_messages(self, cogamer_name: str, after: str | None = None) -> list[Message]:
        """Get all messages across all channels for a cogamer."""
        condition = Key("pk").eq(f"COGAMER#{cogamer_name}") & Key("sk").begins_with("MSG#")
        resp = self._table.query(KeyConditionExpression=condition)
        msgs = [Message(**{k: v for k, v in item.items() if k not in ("pk", "sk")}) for item in resp.get("Items", [])]
        if after:
            msgs = [m for m in msgs if m.timestamp > after]
        return sorted(msgs, key=lambda m: m.timestamp)

    def get_messages(self, cogamer_name: str, channel_id: str, after: str | None = None) -> list[Message]:
        sk_prefix = f"MSG#{channel_id}#"
        if after:
            condition = Key("pk").eq(f"COGAMER#{cogamer_name}") & Key("sk").gt(f"MSG#{channel_id}#{after}")
        else:
            condition = Key("pk").eq(f"COGAMER#{cogamer_name}") & Key("sk").begins_with(sk_prefix)
        resp = self._table.query(KeyConditionExpression=condition)
        return [Message(**{k: v for k, v in item.items() if k not in ("pk", "sk")}) for item in resp.get("Items", [])]
