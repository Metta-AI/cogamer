"""MCP channel server for cogamer — bridges the control plane API into Claude Code.

Polls for new messages and pushes them as channel notifications.
Exposes tools that map 1:1 to control plane API routes.

Environment variables:
  COGAMER_NAME          – This cogamer's name
  COGAMER_API_URL       – Control plane API base URL (default: http://localhost:8000)
  COGAMER_POLL_INTERVAL – Poll interval in seconds (default: 5)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess

import httpx

logging.basicConfig(level=logging.WARNING, format="[cogamer-mcp] %(levelname)s: %(message)s")
logger = logging.getLogger("cogamer.mcp")
from datetime import datetime, timezone

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool

_name = os.environ.get("COGAMER_NAME", "unknown")
_api_url = os.environ.get("COGAMER_API_URL", "http://localhost:8000")
_poll_interval = int(os.environ.get("COGAMER_POLL_INTERVAL", "5"))
_cogamer_token = os.environ.get("COGAMER_TOKEN", "")
_headers = {"Authorization": f"Bearer {_cogamer_token}"} if _cogamer_token else {}
_conversation_log = os.path.expanduser("~/repo/memory/conversation.jsonl")

# -- Tool definitions (match API routes) --

TOOLS: list[Tool] = [
    Tool(
        name="reply",
        description="Reply on a message channel.",
        inputSchema={
            "type": "object",
            "properties": {
                "channel_id": {"type": "string"},
                "message": {"type": "string"},
            },
            "required": ["channel_id", "message"],
        },
    ),
    Tool(
        name="send_message",
        description="Send a message to another cogamer. Returns the channel_id.",
        inputSchema={
            "type": "object",
            "properties": {
                "cogamer_name": {"type": "string"},
                "message": {"type": "string"},
            },
            "required": ["cogamer_name", "message"],
        },
    ),
    Tool(
        name="heartbeat",
        description="Report current status to the control plane. Include a short message about what you're working on.",
        inputSchema={
            "type": "object",
            "properties": {
                "status": {"type": "string", "default": "idle"},
                "message": {"type": "string", "description": "Short description of current activity"},
            },
        },
    ),
    Tool(
        name="get_secrets",
        description="List secret key names for this cogamer.",
        inputSchema={"type": "object", "properties": {}},
    ),
    Tool(
        name="set_secrets",
        description="Store secrets (merges with existing). Values are encrypted at rest.",
        inputSchema={
            "type": "object",
            "properties": {
                "secrets": {"type": "object", "additionalProperties": {"type": "string"}},
            },
            "required": ["secrets"],
        },
    ),
    Tool(
        name="get_config",
        description="Get config key-value pairs for this cogamer.",
        inputSchema={"type": "object", "properties": {}},
    ),
    Tool(
        name="set_config",
        description="Set config values (merges with existing).",
        inputSchema={
            "type": "object",
            "properties": {
                "config": {"type": "object", "additionalProperties": {"type": "string"}},
            },
            "required": ["config"],
        },
    ),
]

# -- Server setup --

server = Server(
    name="cogamer-channel",
    version="0.1.0",
    instructions=(
        f"You are cogamer '{_name}'. Messages from your operator and other cogamers "
        f"arrive as <channel> tags. Use reply to respond on the same channel_id."
    ),
)


def _url(path: str) -> str:
    return f"{_api_url}{path}"


# -- Tool dispatch --


async def _call(client: httpx.AsyncClient, name: str, args: dict) -> str:
    me = _name
    match name:
        case "reply":
            await client.post(_url(f"/cogamers/{me}/reply"), json=args)
            _log_conversation("outgoing", args.get("channel_id", ""), me, args.get("message", ""))
            return "sent"
        case "send_message":
            resp = await client.post(
                _url(f"/cogamers/{args['cogamer_name']}/send"),
                json={"message": args["message"]},
            )
            ch_id = resp.json()["channel_id"]
            _log_conversation("outgoing", ch_id, me, f"[to:{args['cogamer_name']}] {args['message']}")
            return f"sent on {ch_id}"
        case "heartbeat":
            payload: dict = {"status": args.get("status", "idle")}
            if "message" in args:
                payload["message"] = args["message"]
            await client.post(
                _url(f"/cogamers/{me}/heartbeat"),
                json=payload,
            )
            # Save heartbeat to file for dashboard
            try:
                hb_path = os.path.expanduser("~/repo/runtime/heartbeat.json")
                os.makedirs(os.path.dirname(hb_path), exist_ok=True)
                with open(hb_path, "w") as f:
                    json.dump(
                        {
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                            "status": payload.get("status", "idle"),
                            "message": payload.get("message", ""),
                        },
                        f,
                    )
            except Exception:
                pass
            return "ok"
        case "get_secrets":
            resp = await client.get(_url(f"/cogamers/{me}/secrets"))
            return json.dumps(resp.json())
        case "set_secrets":
            await client.put(_url(f"/cogamers/{me}/secrets"), json={"secrets": args["secrets"]})
            return "ok"
        case "get_config":
            resp = await client.get(_url(f"/cogamers/{me}/config"))
            return json.dumps(resp.json())
        case "set_config":
            await client.put(_url(f"/cogamers/{me}/config"), json={"config": args["config"]})
            return "ok"
        case _:
            return f"unknown tool: {name}"


@server.list_tools()
async def list_tools() -> list[Tool]:
    return TOOLS


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[dict]:
    async with httpx.AsyncClient(headers=_headers) as client:
        text = await _call(client, name, arguments)
    return [{"type": "text", "text": text}]


# -- Message polling --


async def _seed_seen(seen: set[str]) -> None:
    try:
        async with httpx.AsyncClient(headers=_headers) as client:
            resp = await client.get(_url(f"/cogamers/{_name}/messages"))
            resp.raise_for_status()
            for msg in resp.json().get("messages", []):
                seen.add(msg.get("timestamp", ""))
    except Exception:
        logger.exception("seed_seen failed")


async def _heartbeat_loop() -> None:
    async with httpx.AsyncClient(headers=_headers) as client:
        while True:
            try:
                resp = await client.post(
                    _url(f"/cogamers/{_name}/heartbeat"),
                    json={"status": "active"},
                )
                resp.raise_for_status()
            except Exception:
                logger.exception("heartbeat failed")
            await asyncio.sleep(30)


def _log_conversation(direction: str, channel_id: str, sender: str, body: str) -> None:
    """Append a message to the conversation JSONL log."""
    try:
        os.makedirs(os.path.dirname(_conversation_log), exist_ok=True)
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "direction": direction,
            "channel_id": channel_id,
            "sender": sender,
            "body": body,
        }
        with open(_conversation_log, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        logger.exception("conversation log write failed")


def _inject_message(sender: str, channel_id: str, body: str) -> None:
    """Inject a message into the Claude tmux session as user input."""
    _log_conversation("incoming", channel_id, sender, body)
    text = f"[channel:{channel_id} from:{sender}] {body}"
    # Escape special tmux characters
    escaped = text.replace("\\", "\\\\").replace(";", "\\;").replace("'", "'\\''")
    subprocess.run(
        ["tmux", "send-keys", "-t", "main", escaped, "Enter"],
        capture_output=True,
        timeout=5,
    )


async def _poll_and_notify(seen: set[str]) -> None:
    async with httpx.AsyncClient(headers=_headers) as client:
        while True:
            try:
                resp = await client.get(_url(f"/cogamers/{_name}/messages"))
                if resp.status_code == 200:
                    for msg in resp.json().get("messages", []):
                        ts = msg.get("timestamp", "")
                        if ts in seen or msg.get("sender") == _name:
                            seen.add(ts)
                            continue
                        seen.add(ts)
                        _inject_message(
                            sender=msg.get("sender", "unknown"),
                            channel_id=msg.get("channel_id", ""),
                            body=msg["body"],
                        )
            except Exception:
                logger.exception("poll failed")
            if len(seen) > 10000:
                for item in list(seen)[: len(seen) - 5000]:
                    seen.discard(item)
            await asyncio.sleep(_poll_interval)


async def main() -> None:
    seen: set[str] = set()
    await _seed_seen(seen)
    async with stdio_server() as (read, write):
        poll_task = asyncio.create_task(_poll_and_notify(seen))
        heartbeat_task = asyncio.create_task(_heartbeat_loop())
        try:
            await server.run(read, write, server.create_initialization_options())
        finally:
            poll_task.cancel()
            heartbeat_task.cancel()


if __name__ == "__main__":
    asyncio.run(main())
