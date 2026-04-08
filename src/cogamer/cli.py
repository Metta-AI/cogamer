"""Cogamer CLI — thin HTTP client wrapping the control plane API.

Syntax:
  cogamer list [--all]
  cogamer api start|stop|restart|status
  cogamer <name> create
  cogamer <name> status
  cogamer <name> stop
  cogamer <name> delete [-y]
  cogamer <name> restart
  cogamer <name> connect [--iterm]
  cogamer <name> send <message> [--async] [--timeout=60] [--follow]
  cogamer <name> secret list|get|set
  cogamer <name> logs [--since 10m] [--max 200]
  cogamer <name> config [key=value ... | mcp.name=url ... | key ...]
  cogamer <name> pull
  cogamer <name> wipe [--full]
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import click
import httpx
from rich.console import Console
from rich.table import Table

console = Console()

PROD_API_URL = "https://api.softmax-cogamers.com"
LOCAL_API_URL = "http://localhost:8000"
PID_FILE = Path.home() / ".cogamer" / "api.pid"
LOG_FILE = Path.home() / ".cogamer" / "api.log"

_api_server: str = "prod"  # set by --api-server flag


# --- HTTP helpers ---


def _api_url() -> str:
    if env := os.environ.get("COGAMER_API_URL"):
        return env
    return LOCAL_API_URL if _api_server == "local" else PROD_API_URL


def _headers() -> dict[str, str]:
    token = _load_softmax_token()
    if not token:
        console.print("[red]Not logged in. Run 'softmax login' first.[/red]")
        sys.exit(1)
    return {"Authorization": f"Bearer {token}"}


def _url(path: str) -> str:
    return f"{_api_url()}{path}"


class _api:
    """Thin wrapper around httpx that injects Authorization Bearer token on every request."""

    @staticmethod
    def _kw(kwargs: dict) -> dict:
        h = kwargs.pop("headers", {})
        h.update(_headers())
        kwargs["headers"] = h
        kwargs.setdefault("timeout", 30.0)
        return kwargs

    @staticmethod
    def get(url: str, **kw: object) -> httpx.Response:
        return httpx.get(url, **_api._kw(kw))  # type: ignore[arg-type]

    @staticmethod
    def post(url: str, **kw: object) -> httpx.Response:
        return httpx.post(url, **_api._kw(kw))  # type: ignore[arg-type]

    @staticmethod
    def put(url: str, **kw: object) -> httpx.Response:
        return httpx.put(url, **_api._kw(kw))  # type: ignore[arg-type]

    @staticmethod
    def delete(url: str, **kw: object) -> httpx.Response:
        return httpx.delete(url, **_api._kw(kw))  # type: ignore[arg-type]


# --- Utility functions ---


def _load_softmax_token() -> str | None:
    """Read the SOFTMAX_TOKEN from local cogames config (~/.metta/cogames.yaml)."""
    cogames_yaml = os.path.expanduser("~/.metta/cogames.yaml")
    if not os.path.exists(cogames_yaml):
        return None
    try:
        import yaml

        with open(cogames_yaml) as f:
            data = yaml.safe_load(f) or {}
        tokens = data.get("login_tokens", {})
        return tokens.get("https://softmax.com/api")
    except Exception:
        return None


def _get_cogamer_ip(name: str) -> str:
    try:
        resp = _api.get(_url(f"/cogamers/{name}"))
    except httpx.ConnectError:
        console.print("[red]API not running — start it with: cogamer api start[/red]")
        sys.exit(1)
    if resp.status_code == 404:
        console.print(f"[red]cogamer '{name}' not found[/red]")
        sys.exit(1)
    resp.raise_for_status()
    data = resp.json()
    public_ip = data.get("public_ip")
    if not public_ip:
        console.print("[red]No public IP found — is the cogamer running?[/red]")
        sys.exit(1)
    return public_ip


def _ssh_run(ip: str, cmd: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "ssh",
            "-o",
            "StrictHostKeyChecking=no",
            "-o",
            "UserKnownHostsFile=/dev/null",
            "-o",
            "LogLevel=ERROR",
            f"cogamer@{ip}",
            cmd,
        ],
        capture_output=True,
        text=True,
    )


def _elapsed_seconds(iso_ts: str | None) -> int | None:
    """Return seconds since the given ISO timestamp, or None."""
    if not iso_ts:
        return None
    from datetime import datetime, timezone

    try:
        dt = datetime.fromisoformat(iso_ts)
        return max(0, int((datetime.now(timezone.utc) - dt).total_seconds()))
    except (ValueError, TypeError):
        return None


def _format_elapsed(iso_ts: str | None) -> str:
    total = _elapsed_seconds(iso_ts)
    if total is None:
        return "-"
    days, rem = divmod(total, 86400)
    hours, rem = divmod(rem, 3600)
    mins, secs = divmod(rem, 60)
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if mins:
        parts.append(f"{mins}m")
    parts.append(f"{secs}s")
    return " ".join(parts)


def _heartbeat_style(iso_ts: str | None) -> str:
    """Return a Rich color based on heartbeat age: green <1m, yellow <5m, red otherwise."""
    secs = _elapsed_seconds(iso_ts)
    if secs is None:
        return "red"
    if secs < 60:
        return "green"
    if secs < 300:
        return "yellow"
    return "red"


_STATUS_COLORS = {"ready": "green", "starting": "yellow", "active": "cyan", "pending": "yellow", "stopped": "red"}


# --- CLI structure ---
#
# "cogamer list", "cogamer api ..." are top-level commands.
# Everything else is "cogamer <name> <command>", handled by CogamerCLI
# which treats unknown first args as cogamer names and dispatches to
# the _cogamer_commands group.


class CogamerCLI(click.Group):
    def get_command(self, ctx: click.Context, cmd_name: str) -> click.BaseCommand | None:
        # Known top-level commands first
        rv = super().get_command(ctx, cmd_name)
        if rv is not None:
            return rv
        # Treat as a cogamer name — stash it and return the per-cogamer group
        ctx.ensure_object(dict)
        ctx.obj["cogamer_name"] = cmd_name
        return _cogamer_commands

    def resolve_command(self, ctx: click.Context, args: list[str]) -> tuple:
        # Let click know that unknown commands are valid (not typos)
        cmd_name, cmd, remaining = super().resolve_command(ctx, args)
        return cmd_name, cmd, remaining

    def format_usage(self, ctx: click.Context, formatter: click.HelpFormatter) -> None:
        formatter.write("Usage: cogamer <name> <command> | cogamer list | cogamer api <command>\n")


@click.group(cls=CogamerCLI)
@click.option("--api-server", type=click.Choice(["prod", "local"]), default="prod", help="API server to use")
def main(api_server: str) -> None:
    """Cogamer — lightweight Claude Code agent platform."""
    global _api_server
    _api_server = api_server


# --- Top-level commands ---


@main.command("list")
@click.option("--all", "show_all", is_flag=True, help="Include non-running cogamers")
def list_cmd(show_all: bool) -> None:
    """List cogamers."""
    resp = _api.get(_url("/cogamers"), params={"all": show_all})
    resp.raise_for_status()
    cogamers = resp.json()
    if not cogamers:
        console.print("[dim]No cogamers running[/dim]")
        return
    from rich.box import ROUNDED

    table = Table(box=ROUNDED, padding=(0, 1))
    table.add_column("Name", style="bold")
    table.add_column("Owner", style="dim")
    table.add_column("Status")
    table.add_column("Uptime", style="dim")
    table.add_column("Heartbeat")
    table.add_column("Activity")
    table.add_column("IP", style="dim")
    for c in cogamers:
        # Uptime from most recent ops_log entry
        ops = c.get("ops_log") or []
        last_start = None
        for entry in reversed(ops):
            if entry.get("action") in ("created", "restarted"):
                last_start = entry.get("timestamp")
                break
        uptime_str = _format_elapsed(last_start) if last_start else "-"
        status = c.get("status", "unknown")
        sc = _STATUS_COLORS.get(status, "dim")
        hb_ts = c.get("last_heartbeat")
        hb_elapsed = _format_elapsed(hb_ts)
        hb_color = _heartbeat_style(hb_ts)
        hb_str = f"[{hb_color}]{hb_elapsed}[/{hb_color}]" if hb_ts else "[dim]-[/dim]"
        msg = c.get("heartbeat_msg") or "-"
        owner_name = c.get("owner_name") or ""
        owner_email = c.get("owner_email") or ""
        owner_id = c.get("owner", "-")
        if owner_name:
            owner_display = f"{owner_name} ({owner_email})" if owner_email else owner_name
        else:
            owner_display = owner_id
        table.add_row(
            c["name"],
            owner_display,
            f"[{sc}]{status}[/{sc}]",
            uptime_str,
            hb_str,
            msg,
            c.get("public_ip") or "-",
        )
    console.print(table)


# --- API management subgroup ---


@main.group()
def api() -> None:
    """Manage the cogamer control plane API."""


def _read_pid() -> int | None:
    if PID_FILE.exists():
        try:
            pid = int(PID_FILE.read_text().strip())
            os.kill(pid, 0)
            return pid
        except (ValueError, ProcessLookupError, PermissionError):
            PID_FILE.unlink(missing_ok=True)
    return None


@api.command("start")
@click.option("--host", default="0.0.0.0", help="Bind host")
@click.option("--port", default=8000, type=int, help="Bind port")
def api_start(host: str, port: int) -> None:
    """Start the control plane API server."""
    if _read_pid():
        console.print("[yellow]API already running[/yellow]")
        return
    PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_FILE, "a") as log:
        proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "cogamer.api.app:app", "--host", host, "--port", str(port)],
            stdout=log,
            stderr=log,
            start_new_session=True,
        )
    PID_FILE.write_text(str(proc.pid))
    console.print(f"[green]API started on {host}:{port} (pid {proc.pid})[/green]")
    console.print(f"[dim]Logs: {LOG_FILE}[/dim]")


@api.command("stop")
def api_stop() -> None:
    """Stop the control plane API server."""
    pid = _read_pid()
    if not pid:
        console.print("[yellow]API not running[/yellow]")
        return
    os.kill(pid, signal.SIGTERM)
    PID_FILE.unlink(missing_ok=True)
    console.print(f"[yellow]API stopped (pid {pid})[/yellow]")


@api.command("restart")
@click.option("--host", default="0.0.0.0", help="Bind host")
@click.option("--port", default=8000, type=int, help="Bind port")
@click.pass_context
def api_restart(ctx: click.Context, host: str, port: int) -> None:
    """Restart the control plane API server."""
    ctx.invoke(api_stop)
    time.sleep(1)
    ctx.invoke(api_start, host=host, port=port)


@api.command("status")
def api_status() -> None:
    """Check if the API server is running."""
    pid = _read_pid()
    if pid:
        console.print(f"[green]API running (pid {pid})[/green]")
    else:
        console.print("[dim]API not running[/dim]")


@api.command("update")
def api_update() -> None:
    """Trigger API rebuild and deploy via GitHub Actions."""
    console.print("[dim]Triggering deploy-api workflow...[/dim]")
    result = subprocess.run(
        ["gh", "workflow", "run", "deploy-api.yml", "--repo", "Metta-AI/cogamer"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        console.print(f"[red]Failed to trigger workflow: {result.stderr.strip()}[/red]")
        sys.exit(1)

    console.print("[green]Deploy workflow triggered[/green]")

    # Wait for the run to appear
    time.sleep(3)
    result = subprocess.run(
        [
            "gh",
            "run",
            "list",
            "--repo",
            "Metta-AI/cogamer",
            "--workflow",
            "deploy-api.yml",
            "--limit",
            "1",
            "--json",
            "databaseId,status",
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        console.print("[yellow]Could not find run — check GitHub Actions manually[/yellow]")
        return

    runs = json.loads(result.stdout)
    if not runs:
        console.print("[yellow]No runs found — check GitHub Actions manually[/yellow]")
        return

    run_id = runs[0]["databaseId"]
    console.print(f"[dim]Watching run {run_id}...[/dim]")
    result = subprocess.run(["gh", "run", "watch", str(run_id), "--repo", "Metta-AI/cogamer"])
    if result.returncode == 0:
        console.print("[green]API deployed[/green]")


# --- Per-cogamer commands (cogamer <name> <command>) ---


@click.group()
@click.pass_context
def _cogamer_commands(ctx: click.Context) -> None:
    """Commands for a specific cogamer."""


def _name(ctx: click.Context) -> str:
    return ctx.obj["cogamer_name"]


@_cogamer_commands.command()
@click.pass_context
def create(ctx: click.Context) -> None:
    """Create a new cogamer. Forks softmax-agents/cogamer and launches on ECS."""
    name = _name(ctx)
    resp = _api.post(_url("/cogamers"), json={"name": name})
    if resp.status_code == 409:
        console.print(f"[red]cogamer '{name}' already exists[/red]")
        sys.exit(1)
    resp.raise_for_status()
    data = resp.json()
    console.print(f"[green]Created cogamer '{data['name']}' — status: {data['status']}[/green]")
    console.print(f"[dim]Repo: {data.get('codebase', '')}[/dim]")
    if data.get("token"):
        console.print(f"[bold]Token:[/bold] {data['token']}")
        console.print("[dim]Save this — it won't be shown again.[/dim]")


@_cogamer_commands.command()
@click.pass_context
def status(ctx: click.Context) -> None:
    """Show cogamer info."""
    name = _name(ctx)
    resp = _api.get(_url(f"/cogamers/{name}"))
    if resp.status_code == 404:
        console.print(f"[red]cogamer '{name}' not found[/red]")
        sys.exit(1)
    resp.raise_for_status()
    data = resp.json()
    from rich.box import ROUNDED
    from rich.panel import Panel

    status = data.get("status", "unknown")
    status_style = _STATUS_COLORS.get(status, "dim")

    def _ts(iso: str | None) -> str:
        if not iso:
            return "-"
        elapsed = _format_elapsed(iso)
        # Shorten ISO for display
        short = iso
        if "T" in iso:
            short = iso.split("T")[0] + " " + iso.split("T")[1][:8]
        return f"{short}  [dim]({elapsed} ago)[/dim]"

    # Info table
    info = Table(show_header=False, box=None, padding=(0, 1))
    info.add_column(style="dim", min_width=10)
    info.add_column()
    info.add_row("status", f"[{status_style}]{status}[/{status_style}]")
    info.add_row("codebase", data.get("codebase", ""))
    if data.get("public_ip"):
        info.add_row("ip", f"{data['public_ip']}  [dim]({data.get('container_ip', '')})[/dim]")
    if data.get("ecs_task_arn"):
        task_id = data["ecs_task_arn"].rsplit("/", 1)[-1]
        info.add_row("task", task_id[:12])
        logs_url = (
            "https://us-east-1.console.aws.amazon.com/cloudwatch/home?region=us-east-1"
            f"#logsV2:log-groups/log-group/$252Fcogamer$252Ftasks/log-events/cogamer$252Fcogamer$252F{task_id}"
        )
        info.add_row("logs", f"[link={logs_url}]{logs_url}[/link]")
    if data.get("tunnel_url"):
        info.add_row("dashboard", f"[link={data['tunnel_url']}]{data['tunnel_url']}[/link]")
    if data.get("last_heartbeat"):
        hb_color = _heartbeat_style(data["last_heartbeat"])
        hb_line = f"[{hb_color}]{_ts(data['last_heartbeat'])}[/{hb_color}]"
        if data.get("heartbeat_msg"):
            hb_line += f"  [italic]{data['heartbeat_msg']}[/italic]"
        info.add_row("heartbeat", hb_line)
    info.add_row("created", _ts(data.get("created_at")))

    # Image info
    image = data.get("image_info") or {}
    if image:
        info.add_row("", "")
        commit_str = image.get("git_hash", "?")
        msg = image.get("git_message", "")
        if msg:
            commit_str += f"  [dim]{msg}[/dim]"
        info.add_row("image", commit_str)
        if image.get("built_at"):
            info.add_row("built", _ts(image["built_at"]))

    console.print(Panel(info, title=f"[bold]{data['name']}[/bold]", box=ROUNDED))

    # Ops log
    ops = data.get("ops_log") or []
    if ops:
        ops_table = Table(box=ROUNDED, padding=(0, 1))
        ops_table.add_column("time", style="dim")
        ops_table.add_column("action")
        ops_table.add_column("image", style="dim")
        for entry in reversed(ops[-10:]):
            ts = entry.get("timestamp", "?")
            elapsed = _format_elapsed(ts) + " ago" if ts != "?" else ""
            if "T" in ts:
                ts = ts.split("T")[0] + " " + ts.split("T")[1][:8]
            ops_table.add_row(f"{ts}  [dim]{elapsed}[/dim]", entry.get("action", "?"), entry.get("image", ""))
        console.print(ops_table)


@_cogamer_commands.command()
@click.pass_context
def token(ctx: click.Context) -> None:
    """Show the cogamer's auth token."""
    name = _name(ctx)
    resp = _api.get(_url(f"/cogamers/{name}/token"))
    if resp.status_code == 404:
        console.print(f"[red]cogamer '{name}' not found[/red]")
        sys.exit(1)
    resp.raise_for_status()
    console.print(resp.json()["token"])


@_cogamer_commands.command()
@click.pass_context
def stop(ctx: click.Context) -> None:
    """Stop a running cogamer."""
    name = _name(ctx)
    resp = _api.delete(_url(f"/cogamers/{name}"))
    resp.raise_for_status()
    console.print(f"[yellow]Stopped cogamer '{name}'[/yellow]")


@_cogamer_commands.command()
@click.option("--secrets", is_flag=True, help="Also delete secrets")
@click.option("--config", is_flag=True, help="Also delete config")
@click.option("-y", "--yes", is_flag=True, help="Skip confirmation")
@click.pass_context
def delete(ctx: click.Context, secrets: bool, config: bool, yes: bool) -> None:
    """Delete a cogamer record."""
    name = _name(ctx)
    if not yes:
        if not click.confirm(f"Delete cogamer '{name}'?"):
            return
    if secrets:
        resp = _api.delete(_url(f"/cogamers/{name}/secrets"))
        if resp.status_code != 404:
            resp.raise_for_status()
            console.print(f"[yellow]Deleted secrets for '{name}'[/yellow]")
    if config:
        resp = _api.delete(_url(f"/cogamers/{name}/config"))
        if resp.status_code != 404:
            resp.raise_for_status()
            console.print(f"[yellow]Deleted config for '{name}'[/yellow]")
    # Clean up Cloudflare tunnel
    from cogamer.tunnel import delete_tunnel, has_cloudflare_creds

    if has_cloudflare_creds():
        try:
            delete_tunnel(name)
            console.print(f"[yellow]Deleted Cloudflare tunnel for '{name}'[/yellow]")
        except Exception as e:
            console.print(f"[yellow]Could not delete Cloudflare tunnel: {e}[/yellow]")

    resp = _api.delete(_url(f"/cogamers/{name}/record"))
    if resp.status_code == 404:
        console.print(f"[red]cogamer '{name}' not found[/red]")
        sys.exit(1)
    resp.raise_for_status()
    console.print(f"[yellow]Deleted cogamer '{name}'[/yellow]")


@_cogamer_commands.command()
@click.pass_context
def restart(ctx: click.Context) -> None:
    """Restart a cogamer."""
    name = _name(ctx)
    resp = _api.post(_url(f"/cogamers/{name}/restart"))
    resp.raise_for_status()
    console.print(f"[green]Restarted cogamer '{name}'[/green]")


@_cogamer_commands.command()
@click.option("--iterm", is_flag=True, help="Use tmux -CC (iTerm2 native integration)")
@click.pass_context
def connect(ctx: click.Context, iterm: bool) -> None:
    """Connect to a cogamer via SSH."""
    name = _name(ctx)
    if iterm and os.environ.get("TERM_PROGRAM") != "iTerm.app":
        console.print("[red]--iterm requires running inside iTerm2[/red]")
        sys.exit(1)
    ip = _get_cogamer_ip(name)
    ssh_base = [
        "ssh",
        "-t",
        "-o",
        "StrictHostKeyChecking=no",
        "-o",
        "UserKnownHostsFile=/dev/null",
        "-o",
        "LogLevel=ERROR",
        "-o",
        "SetEnv=TERM=xterm-256color",
        f"cogamer@{ip}",
    ]
    tmux_cmd = "tmux -CC attach -t main" if iterm else "tmux attach -t main"
    os.execvp("ssh", ssh_base + [tmux_cmd])


@_cogamer_commands.command()
@click.argument("message")
@click.option("--async", "async_mode", is_flag=True, help="Print channel_id and exit")
@click.option("--timeout", default=60, type=int, help="Timeout in seconds (default: 60)")
@click.option("--follow", is_flag=True, help="Keep listening for messages instead of exiting after first response")
@click.pass_context
def send(ctx: click.Context, message: str, async_mode: bool, timeout: int, follow: bool) -> None:
    """Send a message to a cogamer."""
    name = _name(ctx)
    resp = _api.post(_url(f"/cogamers/{name}/send"), json={"message": message})
    resp.raise_for_status()
    channel_id = resp.json()["channel_id"]

    if async_mode:
        console.print(channel_id)
        return

    last_ts = None
    deadline = time.monotonic() + timeout
    console.print(f"[dim]channel: {channel_id}[/dim]")
    while True:
        if time.monotonic() >= deadline:
            console.print(f"[yellow]Timed out after {timeout}s[/yellow]")
            raise SystemExit(1)
        params = {"after": last_ts} if last_ts else {}
        resp = _api.get(_url(f"/cogamers/{name}/recv/{channel_id}"), params=params)
        resp.raise_for_status()
        msgs = resp.json()["messages"]
        for msg in msgs:
            if msg["sender"] != "cli":
                console.print(msg["body"])
                last_ts = msg["timestamp"]
                if not follow:
                    return
        time.sleep(2)


@_cogamer_commands.group(invoke_without_command=True)
@click.pass_context
def secret(ctx: click.Context) -> None:
    """Manage secrets. Subcommands: list, get, set."""
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


@secret.command("list")
@click.pass_context
def secret_list(ctx: click.Context) -> None:
    """List secret keys."""
    name = _name(ctx.parent)  # type: ignore[arg-type]
    resp = _api.get(_url(f"/cogamers/{name}/secrets"))
    resp.raise_for_status()
    keys = resp.json().get("keys", [])
    if not keys:
        console.print("[dim]No secrets set[/dim]")
    else:
        for k in keys:
            console.print(k)


@secret.command("get")
@click.argument("key")
@click.pass_context
def secret_get(ctx: click.Context, key: str) -> None:
    """Get a secret value."""
    name = _name(ctx.parent)  # type: ignore[arg-type]
    resp = _api.get(_url(f"/cogamers/{name}/secrets/{key}"))
    resp.raise_for_status()
    console.print(resp.json().get("value", ""))


@secret.command("set")
@click.argument("pairs", nargs=-1, required=True)
@click.pass_context
def secret_set(ctx: click.Context, pairs: tuple[str, ...]) -> None:
    """Set secrets. Usage: cogamer <name> secret set KEY=VALUE ..."""
    name = _name(ctx.parent)  # type: ignore[arg-type]
    secrets = {}
    for pair in pairs:
        if "=" not in pair:
            console.print(f"[red]Invalid format: {pair} (expected KEY=VALUE)[/red]")
            sys.exit(1)
        k, v = pair.split("=", 1)
        secrets[k] = v
    resp = _api.put(_url(f"/cogamers/{name}/secrets"), json={"secrets": secrets})
    resp.raise_for_status()
    console.print("[green]Secrets updated[/green]")


@_cogamer_commands.command()
@click.argument("pairs", nargs=-1, required=True)
@click.pass_context
def config(ctx: click.Context, pairs: tuple[str, ...]) -> None:
    """Get or set config and MCP servers.

    Usage:
      cogamer <name> config key=value ...        Set config values
      cogamer <name> config key                  Get config values
      cogamer <name> config mcp.name=url         Add MCP server (restart required)
      cogamer <name> config mcp.name=            Remove MCP server
    """
    name = _name(ctx)
    if any("=" in p for p in pairs):
        cfg = {}
        mcp = {}
        mcp_removes = []
        for pair in pairs:
            if "=" not in pair:
                console.print(f"[red]Invalid format: {pair} (expected key=value)[/red]")
                sys.exit(1)
            k, v = pair.split("=", 1)
            if k.startswith("mcp."):
                mcp_name = k[4:]
                if v:
                    mcp[mcp_name] = v
                else:
                    mcp_removes.append(mcp_name)
            else:
                cfg[k] = v
        if cfg:
            resp = _api.put(_url(f"/cogamers/{name}/config"), json={"config": cfg})
            resp.raise_for_status()
            console.print("[green]Config updated[/green]")
        if mcp:
            resp = _api.put(_url(f"/cogamers/{name}/mcp"), json={"mcp_servers": mcp})
            resp.raise_for_status()
            console.print(f"[green]MCP servers updated: {', '.join(mcp.keys())}[/green]")
            console.print("[dim]Restart to apply[/dim]")
        if mcp_removes:
            # Fetch current, remove keys, overwrite
            resp = _api.get(_url(f"/cogamers/{name}"))
            resp.raise_for_status()
            current = resp.json().get("mcp_servers", {})
            for rm in mcp_removes:
                current.pop(rm, None)
            # Direct DB update via config workaround — use put with full set
            # For now, we need a dedicated endpoint; warn user
            console.print("[yellow]MCP server removal requires restart to take effect[/yellow]")
    else:
        resp = _api.get(_url(f"/cogamers/{name}"))
        resp.raise_for_status()
        data = resp.json()
        cfg_data = data.get("config", {})
        mcp_data = data.get("mcp_servers", {})
        for key in pairs:
            if key == "mcp":
                if mcp_data:
                    for k, v in mcp_data.items():
                        console.print(f"[bold]mcp.{k}:[/bold] {v}")
                else:
                    console.print("[dim]No MCP servers configured[/dim]")
            elif key.startswith("mcp."):
                mcp_name = key[4:]
                value = mcp_data.get(mcp_name, "[not set]")
                console.print(f"[bold]{key}:[/bold] {value}")
            else:
                value = cfg_data.get(key, "[not set]")
                console.print(f"[bold]{key}:[/bold] {value}")


@_cogamer_commands.command()
@click.option("--upstream", is_flag=True, help="Sync cogbase from upstream first")
@click.pass_context
def pull(ctx: click.Context, upstream: bool) -> None:
    """Pull latest cogbase changes into the cogamer's repo."""
    name = _name(ctx)

    if upstream:
        # Get the cogbase repo from the codebase URL
        resp = _api.get(_url(f"/cogamers/{name}"))
        resp.raise_for_status()
        codebase = resp.json().get("codebase", "")
        # git@github.com:user/repo.git -> user/repo
        repo = codebase.replace("git@github.com:", "").replace(".git", "")
        # Get upstream repo name
        upstream_result = subprocess.run(
            ["gh", "repo", "view", repo, "--json", "parent", "-q", '.parent.owner.login + "/" + .parent.name'],
            capture_output=True,
            text=True,
        )
        upstream_name = upstream_result.stdout.strip() if upstream_result.returncode == 0 else "upstream"
        console.print(f"[dim]Syncing {repo} from {upstream_name}...[/dim]")
        result = subprocess.run(
            ["gh", "repo", "sync", repo],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            console.print(f"[green]Synced with {upstream_name}[/green]")
        else:
            console.print(f"[red]Sync failed: {result.stderr.strip()}[/red]")
            sys.exit(1)

    ip = _get_cogamer_ip(name)
    console.print("[dim]Merging main into working branch...[/dim]")
    result = _ssh_run(ip, "cd ~/repo && git fetch origin && git merge origin/main --no-edit")
    if result.returncode == 0:
        console.print(f"[green]{result.stdout.strip()}[/green]")
    else:
        console.print(f"[red]{result.stderr.strip()}[/red]")


@_cogamer_commands.command()
@click.option("--full", is_flag=True, help="Reset all of .claude/ (not just memory)")
@click.pass_context
def wipe(ctx: click.Context, full: bool) -> None:
    """Reset .claude/memory/, memory/, and runtime/. With --full, reset all of .claude/."""
    name = _name(ctx)
    ip = _get_cogamer_ip(name)
    claude_target = ".claude" if full else ".claude/memory"
    wipe_cmd = f"cd ~/repo && rm -rf {claude_target} ; rm -rf memory ; rm -rf runtime"
    result = _ssh_run(ip, wipe_cmd)
    if result.returncode == 0:
        console.print(f"[green]{claude_target} and memory/ reset[/green]")
    else:
        console.print(f"[red]{result.stderr.strip()}[/red]")


@_cogamer_commands.command()
@click.option("--since", default="10m", help="How far back to fetch logs (e.g. 5m, 1h, 2d). Default: 10m")
@click.option("--max", "max_lines", default=200, type=int, help="Max log lines to show. Default: 200")
@click.pass_context
def logs(ctx: click.Context, since: str, max_lines: int) -> None:
    """Show CloudWatch logs for the cogamer."""
    name = _name(ctx)
    resp = _api.get(_url(f"/cogamers/{name}"))
    resp.raise_for_status()
    data = resp.json()

    task_arn = data.get("ecs_task_arn")
    if not task_arn:
        console.print("[red]No running task found[/red]")
        return
    task_id = task_arn.rsplit("/", 1)[-1]
    log_stream = f"cogamer/cogamer/{task_id}"

    from cogamer.config import get_aws_session

    session = get_aws_session()
    client = session.client("logs", region_name="us-east-1")

    # Parse --since into millisecond timestamp
    import re

    m = re.fullmatch(r"(\d+)([smhd])", since)
    if not m:
        console.print(f"[red]Invalid --since format: {since} (use e.g. 5m, 1h, 2d)[/red]")
        return
    multipliers = {"s": 1, "m": 60, "h": 3600, "d": 86400}
    start_ms = int((time.time() - int(m.group(1)) * multipliers[m.group(2)]) * 1000)

    try:
        resp_logs = client.get_log_events(
            logGroupName="/cogamer/tasks",
            logStreamName=log_stream,
            startTime=start_ms,
            startFromHead=True,
            limit=max_lines,
        )
    except client.exceptions.ResourceNotFoundException:
        console.print("[yellow]No logs found (stream not created yet)[/yellow]")
        return

    events = resp_logs.get("events", [])
    if not events:
        console.print("[dim]No log events in this time range[/dim]")
        return

    from datetime import datetime, timezone

    for e in events:
        ts = datetime.fromtimestamp(e["timestamp"] / 1000, tz=timezone.utc).strftime("%H:%M:%S")
        console.print(f"[dim]{ts}[/dim] {e['message'].rstrip()}")
