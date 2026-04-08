"""Pydantic models for cogamer state, config, and messaging."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from pydantic import BaseModel, Field


def _new_cogamer_token() -> str:
    return f"cgm_{uuid.uuid4().hex}"


def _new_channel_id() -> str:
    return f"ch-{uuid.uuid4().hex[:12]}"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class CogamerCreateRequest(BaseModel):
    """Parameters for creating a cogamer."""

    name: str


class CogamerState(BaseModel):
    """Runtime state of a cogamer stored in DynamoDB."""

    name: str
    codebase: str
    owner: str
    token: str = Field(default_factory=_new_cogamer_token)
    status: str = "creating"
    config: dict[str, str] = Field(default_factory=dict)
    mcp_servers: dict[str, str] = Field(default_factory=dict)
    ecs_task_arn: str | None = None
    container_ip: str | None = None
    public_ip: str | None = None
    last_heartbeat: str | None = None
    heartbeat_msg: str | None = None
    tunnel_url: str | None = None
    image_info: dict[str, str] = Field(default_factory=dict)
    ops_log: list[dict[str, str]] = Field(default_factory=list)
    created_at: str = Field(default_factory=_now)


class Message(BaseModel):
    """A single message on a channel."""

    channel_id: str
    sender: str
    body: str
    timestamp: str = Field(default_factory=_now)


class Channel(BaseModel):
    """A message channel between a caller and a cogamer."""

    channel_id: str = Field(default_factory=_new_channel_id)
    cogamer_name: str
    messages: list[Message] = Field(default_factory=list)
    created_at: str = Field(default_factory=_now)


class SendRequest(BaseModel):
    message: str


class SendResponse(BaseModel):
    channel_id: str


class ReplyRequest(BaseModel):
    channel_id: str
    message: str


class RecvResponse(BaseModel):
    messages: list[Message]


class SecretSetRequest(BaseModel):
    secrets: dict[str, str]


class SecretListResponse(BaseModel):
    keys: list[str]


class ConfigSetRequest(BaseModel):
    config: dict[str, str]


class HeartbeatRequest(BaseModel):
    status: str = "idle"
    message: str | None = None


class McpSetRequest(BaseModel):
    mcp_servers: dict[str, str]
