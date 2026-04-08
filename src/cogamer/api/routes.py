"""Control plane API routes."""

from __future__ import annotations

import httpx as _httpx
from fastapi import APIRouter, HTTPException, Request

from cogamer.auth import AuthenticatedCogamer, AuthenticatedUser, Caller
from cogamer.config import get_aws_session, get_softmax_auth_secret, load_config
from cogamer.db import CogamerDB
from cogamer.ecs import CogamerECS
from cogamer.github import create_repo_with_deploy_key
from cogamer.models import (
    Channel,
    CogamerCreateRequest,
    CogamerState,
    ConfigSetRequest,
    HeartbeatRequest,
    McpSetRequest,
    Message,
    RecvResponse,
    ReplyRequest,
    SecretListResponse,
    SecretSetRequest,
    SendRequest,
    SendResponse,
)
from cogamer.secrets import CogamerSecrets

router = APIRouter()

_db: CogamerDB | None = None
_ecs: CogamerECS | None = None
_secrets: CogamerSecrets | None = None


def get_db() -> CogamerDB:
    global _db
    if _db is None:
        cfg = load_config()
        session = get_aws_session()
        _db = CogamerDB(table_name=cfg.dynamodb_table, session=session)
    return _db


def get_ecs() -> CogamerECS:
    global _ecs
    if _ecs is None:
        cfg = load_config()
        session = get_aws_session()
        _ecs = CogamerECS(
            cluster=cfg.ecs_cluster,
            task_definition=cfg.ecs_task_definition,
            subnets=cfg.ecs_subnets,
            security_groups=cfg.ecs_security_groups,
            session=session,
        )
    return _ecs


def get_secrets() -> CogamerSecrets:
    global _secrets
    if _secrets is None:
        cfg = load_config()
        session = get_aws_session()
        _secrets = CogamerSecrets(prefix=cfg.secrets_prefix, session=session)
    return _secrets


def _require_cogamer(name: str) -> CogamerState:
    state = get_db().get_cogamer(name)
    if not state:
        raise HTTPException(404, f"cogamer '{name}' not found")
    return state


def _get_caller(request: Request) -> Caller:
    return request.state.caller


def _get_user(request: Request) -> AuthenticatedUser:
    """Get caller as a user, or 403 if it's a cogamer token."""
    caller = _get_caller(request)
    if not isinstance(caller, AuthenticatedUser):
        raise HTTPException(403, "this endpoint requires user authentication")
    return caller


def _require_access(caller: Caller, state: CogamerState) -> None:
    """Raise 403 if caller cannot access this cogamer."""
    if isinstance(caller, AuthenticatedCogamer):
        if caller.cogamer_name != state.name:
            raise HTTPException(403, "access denied")
        return
    # AuthenticatedUser
    if caller.is_team_member:
        return
    if state.owner != caller.id:
        raise HTTPException(403, "access denied")


def _log_op(name: str, action: str, **extra: str) -> None:
    """Append an operations log entry."""
    from cogamer.models import _now

    state = get_db().get_cogamer(name)
    if not state:
        return
    log = list(state.ops_log)
    entry: dict[str, str] = {"action": action, "timestamp": _now()}
    entry.update(extra)
    log.append(entry)
    # Keep last 50 entries
    get_db().update_cogamer(name, ops_log=log[-50:])


def _get_image_info() -> dict[str, str]:
    """Read container image build metadata from DynamoDB."""
    try:
        db = get_db()
        resp = db._table.get_item(Key={"pk": "SYSTEM", "sk": "IMAGE#latest"})
        item = resp.get("Item")
        if not item:
            return {}
        return {
            "built_at": item.get("built_at", "unknown"),
            "git_hash": item.get("git_hash", "unknown"),
            "git_message": item.get("git_message", "unknown"),
        }
    except Exception:
        return {}


_owner_cache: dict[str, dict[str, str | None]] = {}


def _resolve_owners(owner_ids: list[str]) -> dict[str, dict[str, str | None]]:
    """Resolve owner IDs to {id: {name, email}} via softmax.com login service."""
    cfg = load_config()
    auth_secret = get_softmax_auth_secret()
    if not auth_secret:
        return {}

    uncached = [uid for uid in set(owner_ids) if uid not in _owner_cache]
    if uncached:
        try:
            resp = _httpx.post(
                f"{cfg.login_service_url}/api/users/resolve",
                json={"userIds": uncached},
                headers={"X-Auth-Secret": auth_secret},
                timeout=5.0,
            )
            if resp.status_code == 200:
                users = resp.json().get("users", {})
                for uid in uncached:
                    info = users.get(uid)
                    if info:
                        _owner_cache[uid] = {
                            "name": info.get("name"),
                            "email": info.get("email"),
                        }
                    else:
                        _owner_cache[uid] = {"name": None, "email": None}
        except Exception:
            pass

    return {uid: _owner_cache.get(uid, {"name": None, "email": None}) for uid in owner_ids}


def _sanitize_state(state: CogamerState, owner_info: dict | None = None) -> dict:
    """Return state dict with token excluded and optional owner info."""
    d = state.model_dump()
    d.pop("token", None)
    if owner_info:
        d["owner_name"] = owner_info.get("name")
        d["owner_email"] = owner_info.get("email")
    return d


def _get_github_app_creds() -> tuple[str, str]:
    """Fetch GitHub App ID and PEM from Secrets Manager."""
    cfg = load_config()
    session = get_aws_session()
    sm = session.client("secretsmanager")
    app_id = sm.get_secret_value(SecretId=cfg.github_app_id_secret_name)["SecretString"].strip()
    pem = sm.get_secret_value(SecretId=cfg.github_app_pem_secret_name)["SecretString"]
    return app_id, pem


@router.post("/cogamers", status_code=201)
def create_cogamer(req: CogamerCreateRequest, request: Request) -> dict:
    user = _get_user(request)
    db = get_db()
    name = req.name
    if db.get_cogamer(name):
        raise HTTPException(409, f"cogamer '{name}' already exists")

    cfg = load_config()

    # Fork repo and create deploy key via GitHub App
    app_id, pem = _get_github_app_creds()
    repo_full_name, private_key_pem = create_repo_with_deploy_key(
        app_id=app_id,
        pem=pem,
        name=name,
        source_repo=cfg.github_template_repo,
        org=cfg.github_org,
    )

    # Store deploy key in Secrets Manager
    codebase = f"git@github.com:{repo_full_name}.git"
    get_secrets().set_secrets(name, {"GIT_SSH_KEY": private_key_pem})

    # Create state and launch
    state = CogamerState(
        name=name,
        codebase=codebase,
        owner=user.id,
        status="starting",
    )
    state.image_info = _get_image_info()
    arn = get_ecs().run_task(
        name,
        env={"COGAMER_NAME": name, "COGAMER_CODEBASE": codebase},
    )
    state.ecs_task_arn = arn
    state.ops_log = [
        {
            "action": "created",
            "timestamp": state.created_at,
            "image": state.image_info.get("git_hash", ""),
        },
    ]
    db.put_cogamer(state)
    return state.model_dump()


def _refresh_ecs_status(state: CogamerState) -> None:
    """Update state with live ECS task info."""
    if not state.ecs_task_arn:
        return
    try:
        task_info = get_ecs().describe_task(state.ecs_task_arn)
    except Exception:
        return
    ecs_status = task_info["status"].lower()
    state.container_ip = task_info.get("ip")
    state.public_ip = task_info.get("public_ip")
    if ecs_status != "running":
        state.status = ecs_status


@router.get("/cogamers")
def list_cogamers(all: bool = False, request: Request = None) -> list[dict]:
    user = _get_user(request)
    cogamers = get_db().list_cogamers()
    for c in cogamers:
        _refresh_ecs_status(c)
    if not all:
        cogamers = [c for c in cogamers if c.status not in ("stopped", "deleted")]
    # Non-team members only see their own cogamers
    # Team members see all when --all, otherwise just their own
    if not user.is_team_member or not all:
        cogamers = [c for c in cogamers if c.owner == user.id]
    owner_ids = list({c.owner for c in cogamers})
    owner_map = _resolve_owners(owner_ids)
    return [_sanitize_state(c, owner_map.get(c.owner)) for c in cogamers]


@router.get("/cogamers/{name}")
def get_cogamer(name: str, request: Request) -> dict:
    state = _require_cogamer(name)
    _require_access(_get_caller(request), state)
    _refresh_ecs_status(state)
    owner_map = _resolve_owners([state.owner])
    return _sanitize_state(state, owner_map.get(state.owner))


@router.get("/cogamers/{name}/token")
def get_cogamer_token(name: str, request: Request) -> dict[str, str]:
    """Retrieve the cogamer's auth token. Owner or team member only."""
    state = _require_cogamer(name)
    user = _get_user(request)
    if not user.is_team_member and state.owner != user.id:
        raise HTTPException(403, "access denied")
    return {"token": state.token}


@router.delete("/cogamers/{name}")
def stop_cogamer(name: str, request: Request) -> dict[str, str]:
    state = _require_cogamer(name)
    _require_access(_get_caller(request), state)
    if state.ecs_task_arn:
        get_ecs().stop_task(state.ecs_task_arn)
    get_db().update_cogamer(name, status="stopped")
    _log_op(name, "stopped")
    return {"status": "stopped"}


@router.delete("/cogamers/{name}/record")
def delete_cogamer(name: str, request: Request) -> dict[str, str]:
    state = _require_cogamer(name)
    user = _get_user(request)
    if not user.is_team_member and state.owner != user.id:
        raise HTTPException(403, "access denied")
    if state.ecs_task_arn:
        get_ecs().stop_task(state.ecs_task_arn)
    _log_op(name, "deleted")
    get_db().delete_cogamer(name)
    return {"status": "deleted"}


@router.post("/cogamers/{name}/restart")
def restart_cogamer(name: str, request: Request) -> dict:
    state = _require_cogamer(name)
    user = _get_user(request)
    if not user.is_team_member and state.owner != user.id:
        raise HTTPException(403, "access denied")
    if state.ecs_task_arn:
        get_ecs().stop_task(state.ecs_task_arn)
    image_info = _get_image_info()
    arn = get_ecs().run_task(name, env={"COGAMER_NAME": name, "COGAMER_CODEBASE": state.codebase})
    get_db().update_cogamer(name, status="starting", ecs_task_arn=arn, image_info=image_info)
    _log_op(name, "restarted", image=image_info.get("git_hash", ""))
    state.ecs_task_arn = arn
    state.status = "starting"
    state.image_info = image_info
    return _sanitize_state(state)


@router.post("/cogamers/{name}/send")
def send_message(name: str, req: SendRequest, request: Request) -> SendResponse:
    state = _require_cogamer(name)
    _require_access(_get_caller(request), state)
    channel = Channel(cogamer_name=name)
    msg = Message(channel_id=channel.channel_id, sender="cli", body=req.message)
    get_db().put_message(name, msg)
    return SendResponse(channel_id=channel.channel_id)


@router.get("/cogamers/{name}/recv/{channel_id}")
def recv_messages(name: str, channel_id: str, request: Request, after: str | None = None) -> RecvResponse:
    state = _require_cogamer(name)
    _require_access(_get_caller(request), state)
    msgs = get_db().get_messages(name, channel_id, after=after)
    return RecvResponse(messages=msgs)


@router.put("/cogamers/{name}/config")
def set_config(name: str, req: ConfigSetRequest, request: Request) -> dict[str, str]:
    state = _require_cogamer(name)
    _require_access(_get_caller(request), state)
    state = get_db().get_cogamer(name)
    assert state is not None
    merged = {**state.config, **req.config}
    get_db().update_cogamer(name, config=merged)
    return {"status": "ok"}


@router.get("/cogamers/{name}/config")
def get_config(name: str, request: Request) -> dict[str, str]:
    state = _require_cogamer(name)
    _require_access(_get_caller(request), state)
    return state.config


@router.put("/cogamers/{name}/secrets")
def set_secrets(name: str, req: SecretSetRequest, request: Request) -> dict[str, str]:
    state = _require_cogamer(name)
    _require_access(_get_caller(request), state)
    existing = get_secrets().get_secrets(name)
    merged = {**existing, **req.secrets}
    get_secrets().set_secrets(name, merged)
    return {"status": "ok"}


@router.get("/cogamers/{name}/secrets")
def list_secrets(name: str, request: Request) -> SecretListResponse:
    state = _require_cogamer(name)
    _require_access(_get_caller(request), state)
    return SecretListResponse(keys=get_secrets().list_secret_keys(name))


@router.get("/cogamers/{name}/secrets/{key}")
def get_secret(name: str, key: str, request: Request) -> dict[str, str]:
    state = _require_cogamer(name)
    _require_access(_get_caller(request), state)
    secrets = get_secrets().get_secrets(name)
    if key not in secrets:
        raise HTTPException(status_code=404, detail=f"Secret '{key}' not found")
    return {"value": secrets[key]}


@router.delete("/cogamers/{name}/secrets")
def delete_secrets(name: str, request: Request) -> dict[str, str]:
    state = _require_cogamer(name)
    _require_access(_get_caller(request), state)
    get_secrets().delete_secrets(name)
    return {"status": "ok"}


@router.delete("/cogamers/{name}/config")
def delete_config(name: str, request: Request) -> dict[str, str]:
    state = _require_cogamer(name)
    _require_access(_get_caller(request), state)
    get_db().update_cogamer(name, config={})
    return {"status": "ok"}


@router.post("/cogamers/{name}/reply")
def reply_message(name: str, req: ReplyRequest, request: Request) -> dict[str, str]:
    state = _require_cogamer(name)
    _require_access(_get_caller(request), state)
    msg = Message(channel_id=req.channel_id, sender=name, body=req.message)
    get_db().put_message(name, msg)
    return {"status": "ok"}


@router.get("/cogamers/{name}/messages")
def get_messages(name: str, request: Request, after: str | None = None) -> RecvResponse:
    """Get all messages across all channels for a cogamer."""
    state = _require_cogamer(name)
    _require_access(_get_caller(request), state)
    msgs = get_db().get_all_messages(name, after=after)
    return RecvResponse(messages=msgs)


@router.post("/cogamers/{name}/heartbeat")
def heartbeat(name: str, req: HeartbeatRequest, request: Request) -> dict[str, str]:
    from cogamer.models import _now

    state = _require_cogamer(name)
    _require_access(_get_caller(request), state)
    updates: dict = {"status": req.status, "last_heartbeat": _now()}
    if req.message is not None:
        updates["heartbeat_msg"] = req.message
    get_db().update_cogamer(name, **updates)
    return {"status": "ok"}


@router.put("/cogamers/{name}/mcp")
def set_mcp(name: str, req: McpSetRequest, request: Request) -> dict[str, str]:
    state = _require_cogamer(name)
    _require_access(_get_caller(request), state)
    state = get_db().get_cogamer(name)
    assert state is not None
    merged = {**state.mcp_servers, **req.mcp_servers}
    get_db().update_cogamer(name, mcp_servers=merged)
    return {"status": "ok"}
