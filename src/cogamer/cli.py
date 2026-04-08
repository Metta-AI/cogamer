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

PROD_API_URL = "https://api.softmax-cogents.com"
LOCAL_API_URL = "http://localhost:8000"
PID_FILE = Path.home() / ".cogamer" / "api.pid"
LOG_FILE = Path.home() / ".cogamer" / "api.log"

_api_server: str = "prod"  # set by --api-server flag
_verbose: bool = "--verbose" in sys.argv
if _verbose:
    sys.argv = [a for a in sys.argv if a != "--verbose"]


# --- HTTP helpers ---


def _api_url() -> str:
    if env := os.environ.get("COGAMER_API_URL"):
        return env
    if _api_server == "prod":
        return PROD_API_URL
    # Custom server (e.g. localhost:8000)
    server = _api_server
    if not server.startswith("http"):
        server = f"http://{server}"
    return server


def _headers() -> dict[str, str]:
    token = _load_softmax_token()
    if not token:
        console.print("[red]Not logged in. Run 'softmax login' first.[/red]")
        sys.exit(1)
    return {"Authorization": f"Bearer {token}"}


def _url(path: str) -> str:
    return f"{_api_url()}{path}"


def _request(method: str, url: str, **kw: object) -> httpx.Response:
    """Send an HTTP request with auth headers and friendly error handling."""
    from urllib.parse import urlparse

    h = dict(kw.pop("headers", {}))  # type: ignore[arg-type]
    h.update(_headers())
    kw["headers"] = h  # type: ignore[assignment]
    kw.setdefault("timeout", 30.0)  # type: ignore[arg-type]

    try:
        return getattr(httpx, method)(url, **kw)
    except httpx.ConnectError as exc:
        host = urlparse(url).hostname or url
        console.print(f"[red]Could not reach {host} — use --verbose for details[/red]")
        if _verbose:
            console.print(f"[dim]{exc}[/dim]")
        raise SystemExit(1) from None


def _check(resp: httpx.Response) -> None:
    """Call instead of _check(resp) for friendly error output."""
    if resp.is_error:
        from urllib.parse import urlparse

        url = str(resp.request.url)
        host = urlparse(url).hostname or url
        console.print(f"[red]{resp.status_code} from {host}{urlparse(url).path} — use --verbose for details[/red]")
        if _verbose:
            console.print(f"[dim]{resp.text}[/dim]")
        raise SystemExit(1)


class _api:
    """Thin wrapper around httpx that injects Authorization Bearer token on every request."""

    @staticmethod
    def get(url: str, **kw: object) -> httpx.Response:
        return _request("get", url, **kw)

    @staticmethod
    def post(url: str, **kw: object) -> httpx.Response:
        return _request("post", url, **kw)

    @staticmethod
    def put(url: str, **kw: object) -> httpx.Response:
        return _request("put", url, **kw)

    @staticmethod
    def delete(url: str, **kw: object) -> httpx.Response:
        return _request("delete", url, **kw)


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
        resp = _api.get(_url(f"/cogamer/{name}"))
    except httpx.ConnectError:
        console.print("[red]API not running — start it with: cogamer api start[/red]")
        sys.exit(1)
    if resp.status_code == 404:
        console.print(f"[red]cogamer '{name}' not found[/red]")
        sys.exit(1)
    _check(resp)
    data = resp.json()
    public_ip = data.get("public_ip")
    if not public_ip:
        console.print("[red]No public IP found — is the cogamer running?[/red]")
        sys.exit(1)
    return public_ip


def _get_ssh_key_path(name: str) -> str:
    """Fetch the cogamer's SSH key via API and cache it locally."""
    key_dir = Path.home() / ".cogamer" / "keys"
    key_dir.mkdir(parents=True, exist_ok=True)
    key_path = key_dir / f"{name}.pem"
    if not key_path.exists():
        resp = _api.get(_url(f"/cogamer/{name}/config/GIT_SSH_KEY?secret=true"))
        _check(resp)
        ssh_key = resp.json().get("value", "")
        if not ssh_key:
            console.print(f"[red]No SSH key found for '{name}'[/red]")
            sys.exit(1)
        key_path.write_text(ssh_key)
        key_path.chmod(0o600)
    return str(key_path)


def _ssh_args(ip: str, name: str) -> list[str]:
    """Common SSH arguments for connecting to a cogamer."""
    key_path = _get_ssh_key_path(name)
    return [
        "ssh",
        "-i", key_path,
        "-o", "StrictHostKeyChecking=no",
        "-o", "UserKnownHostsFile=/dev/null",
        "-o", "LogLevel=ERROR",
        f"cogamer@{ip}",
    ]


def _ssh_run(ip: str, cmd: str, name: str | None = None) -> subprocess.CompletedProcess[str]:
    if name:
        base = _ssh_args(ip, name)
    else:
        base = [
            "ssh",
            "-o", "StrictHostKeyChecking=no",
            "-o", "UserKnownHostsFile=/dev/null",
            "-o", "LogLevel=ERROR",
            f"cogamer@{ip}",
        ]
    return subprocess.run(base + [cmd], capture_output=True, text=True)


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


def _format_elapsed_seconds(total: int) -> str:
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
@click.option("--api-server", default="prod", help="API server: 'prod' or host:port (e.g. localhost:8000)")
def main(api_server: str) -> None:
    """Cogamer — lightweight Claude Code agent platform."""
    global _api_server
    _api_server = api_server


# --- Top-level commands ---


@main.command("list")
@click.option("--all", "show_all", is_flag=True, help="Include non-running cogamers")
def list_cmd(show_all: bool) -> None:
    """List cogamers."""
    resp = _api.get(_url("/cogamer"), params={"all": show_all})
    _check(resp)
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
            [sys.executable, "-m", "uvicorn", "cogamer_api.api.app:app", "--host", host, "--port", str(port)],
            stdout=log,
            stderr=log,
            start_new_session=True,
        )
    # Wait briefly to detect immediate crashes (e.g. port already in use)
    import time

    time.sleep(0.5)
    if proc.poll() is not None:
        PID_FILE.unlink(missing_ok=True)
        console.print(f"[red]API failed to start (exit code {proc.returncode})[/red]")
        console.print(f"[dim]Check logs: {LOG_FILE}[/dim]")
        raise SystemExit(1)
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
    """Check API server health."""
    # Check local dev server if one is running
    pid = _read_pid()
    if pid:
        console.print(f"[green]Local dev server running (pid {pid})[/green]")

    # Check the configured API endpoint
    url = _api_url()
    try:
        resp = httpx.get(f"{url}/status", timeout=30.0)
        if resp.status_code == 200:
            data = resp.json()
            commit = data.get("git_commit", "unknown")
            uptime = data.get("uptime_seconds", 0)
            console.print(f"[green]{url} reachable[/green]")
            console.print(f"  commit: {commit[:12]}")
            console.print(f"  uptime: {_format_elapsed_seconds(uptime)}")
        else:
            console.print(f"[green]{url} reachable ({resp.status_code})[/green]")
    except (httpx.ConnectError, httpx.ReadTimeout) as exc:
        from urllib.parse import urlparse

        host = urlparse(url).hostname or url
        msg = "timed out" if isinstance(exc, httpx.ReadTimeout) else "not reachable"
        console.print(f"[red]{host} {msg}[/red]")


@api.command("update")
@click.option("--branch", default=None, help="Branch to deploy from (default: main)")
def api_update(branch: str | None) -> None:
    """Trigger API rebuild and deploy via GitHub Actions."""
    ref = branch or "main"
    # Show what's being deployed
    result = subprocess.run(
        [
            "gh", "api", f"repos/Metta-AI/metta/commits/{ref}",
            "--jq", '.sha[:12] + " " + (.commit.message | split("\\n")[0])',
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0 and result.stdout.strip():
        console.print(f"[bold]Deploying ({ref}):[/bold] {result.stdout.strip()}")
    console.print("[dim]Triggering deploy-api workflow...[/dim]")
    cmd = ["gh", "workflow", "run", "cogamer-api-build-image.yml", "--repo", "Metta-AI/metta"]
    if branch:
        cmd += ["--ref", branch]
    result = subprocess.run(cmd, capture_output=True, text=True)
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
            "Metta-AI/metta",
            "--workflow",
            "cogamer-api-build-image.yml",
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
    result = subprocess.run(["gh", "run", "watch", str(run_id), "--repo", "Metta-AI/metta"])
    if result.returncode == 0:
        console.print("[green]API deployed[/green]")


# --- Per-cogamer commands (cogamer <name> <command>) ---


@click.group()
@click.pass_context
def _cogamer_commands(ctx: click.Context) -> None:
    """Commands for a specific cogamer."""


def _name(ctx: click.Context) -> str:
    return ctx.obj["cogamer_name"]


# ---------------------------------------------------------------------------
# Lifecycle (top-level) — create, status, stop, restart, delete
# ---------------------------------------------------------------------------


@_cogamer_commands.command()
@click.pass_context
def create(ctx: click.Context) -> None:
    """Create a new cogamer."""
    name = _name(ctx)
    resp = _api.post(_url("/cogamer"), json={"name": name})
    if resp.status_code == 409:
        console.print(f"[red]cogamer '{name}' already exists[/red]")
        sys.exit(1)
    _check(resp)
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
    resp = _api.get(_url(f"/cogamer/{name}"))
    if resp.status_code == 404:
        console.print(f"[red]cogamer '{name}' not found[/red]")
        sys.exit(1)
    _check(resp)
    data = resp.json()
    from rich.box import ROUNDED
    from rich.panel import Panel

    st = data.get("status", "unknown")
    status_style = _STATUS_COLORS.get(st, "dim")

    def _ts(iso: str | None) -> str:
        if not iso:
            return "-"
        elapsed = _format_elapsed(iso)
        short = iso
        if "T" in iso:
            short = iso.split("T")[0] + " " + iso.split("T")[1][:8]
        return f"{short}  [dim]({elapsed} ago)[/dim]"

    info = Table(show_header=False, box=None, padding=(0, 1))
    info.add_column(style="dim", min_width=10)
    info.add_column()
    info.add_row("status", f"[{status_style}]{st}[/{status_style}]")
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
def stop(ctx: click.Context) -> None:
    """Stop a running cogamer."""
    name = _name(ctx)
    resp = _api.delete(_url(f"/cogamer/{name}"))
    _check(resp)
    console.print(f"[yellow]Stopped cogamer '{name}'[/yellow]")


@_cogamer_commands.command()
@click.pass_context
def restart(ctx: click.Context) -> None:
    """Restart a cogamer."""
    name = _name(ctx)
    resp = _api.post(_url(f"/cogamer/{name}/restart"))
    _check(resp)
    console.print(f"[green]Restarted cogamer '{name}'[/green]")


@_cogamer_commands.command()
@click.option("--secrets", is_flag=True, help="Also delete secrets")
@click.option("-y", "--yes", is_flag=True, help="Skip confirmation")
@click.pass_context
def delete(ctx: click.Context, secrets: bool, yes: bool) -> None:
    """Delete a cogamer record."""
    name = _name(ctx)
    if not yes:
        if not click.confirm(f"Delete cogamer '{name}'?"):
            return
    if secrets:
        resp = _api.delete(_url(f"/cogamer/{name}/config?secret=true"))
        if resp.status_code != 404:
            _check(resp)
            console.print(f"[yellow]Deleted secrets for '{name}'[/yellow]")
    from cogamer.tunnel import delete_tunnel, has_cloudflare_creds

    if has_cloudflare_creds():
        try:
            delete_tunnel(name)
            console.print(f"[yellow]Deleted Cloudflare tunnel for '{name}'[/yellow]")
        except Exception as e:
            console.print(f"[yellow]Could not delete Cloudflare tunnel: {e}[/yellow]")

    resp = _api.delete(_url(f"/cogamer/{name}/record"))
    if resp.status_code == 404:
        console.print(f"[red]cogamer '{name}' not found[/red]")
        sys.exit(1)
    _check(resp)
    console.print(f"[yellow]Deleted cogamer '{name}'[/yellow]")


# ---------------------------------------------------------------------------
# config — get/put/delete config and secrets
# ---------------------------------------------------------------------------


@_cogamer_commands.group(invoke_without_command=True)
@click.pass_context
def config(ctx: click.Context) -> None:
    """Manage config and secrets."""
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


@config.command("get")
@click.argument("key", required=False)
@click.option("--secret", is_flag=True, help="Read from secrets instead of config")
@click.pass_context
def config_get(ctx: click.Context, key: str | None, secret: bool) -> None:
    """Get config or secret values."""
    name = _name(ctx.parent.parent)  # type: ignore[arg-type]
    flag = "?secret=true" if secret else ""
    if key:
        resp = _api.get(_url(f"/cogamer/{name}/config/{key}{flag}"))
        _check(resp)
        console.print(resp.json().get("value", ""))
    else:
        resp = _api.get(_url(f"/cogamer/{name}/config{flag}"))
        _check(resp)
        data = resp.json()
        if secret:
            keys = data.get("keys", [])
            if not keys:
                console.print("[dim]No secrets set[/dim]")
            else:
                for k in keys:
                    console.print(k)
        elif not data:
            console.print("[dim]No config set[/dim]")
        else:
            for k, v in data.items():
                console.print(f"[bold]{k}:[/bold] {v}")


@config.command("put")
@click.argument("pairs", nargs=-1, required=True)
@click.option("--secret", is_flag=True, help="Write to secrets instead of config")
@click.pass_context
def config_put(ctx: click.Context, pairs: tuple[str, ...], secret: bool) -> None:
    """Set config or secret values. Usage: config put KEY=VALUE ..."""
    name = _name(ctx.parent.parent)  # type: ignore[arg-type]
    kv = {}
    for pair in pairs:
        if "=" not in pair:
            console.print(f"[red]Invalid format: {pair} (expected KEY=VALUE)[/red]")
            sys.exit(1)
        k, v = pair.split("=", 1)
        kv[k] = v
    flag = "?secret=true" if secret else ""
    body_key = "secrets" if secret else "config"
    resp = _api.put(_url(f"/cogamer/{name}/config{flag}"), json={body_key: kv})
    _check(resp)
    label = "Secrets" if secret else "Config"
    console.print(f"[green]{label} updated[/green]")


@config.command("delete")
@click.argument("key", required=False)
@click.option("--secret", is_flag=True, help="Delete secrets instead of config")
@click.pass_context
def config_delete(ctx: click.Context, key: str | None, secret: bool) -> None:
    """Delete config or secrets."""
    name = _name(ctx.parent.parent)  # type: ignore[arg-type]
    flag = "?secret=true" if secret else ""
    resp = _api.delete(_url(f"/cogamer/{name}/config{flag}"))
    _check(resp)
    label = "Secrets" if secret else "Config"
    console.print(f"[yellow]{label} deleted[/yellow]")


@config.command("mcp")
@click.argument("pairs", nargs=-1)
@click.pass_context
def config_mcp(ctx: click.Context, pairs: tuple[str, ...]) -> None:
    """Get or set MCP servers. Usage: config mcp name=url ..."""
    name = _name(ctx.parent.parent)  # type: ignore[arg-type]
    if not pairs:
        resp = _api.get(_url(f"/cogamer/{name}"))
        _check(resp)
        mcp_data = resp.json().get("mcp_servers", {})
        if not mcp_data:
            console.print("[dim]No MCP servers configured[/dim]")
        else:
            for k, v in mcp_data.items():
                console.print(f"[bold]{k}:[/bold] {v}")
        return
    mcp = {}
    for pair in pairs:
        if "=" not in pair:
            console.print(f"[red]Invalid format: {pair} (expected name=url)[/red]")
            sys.exit(1)
        k, v = pair.split("=", 1)
        mcp[k] = v
    resp = _api.put(_url(f"/cogamer/{name}/mcp"), json={"mcp_servers": mcp})
    _check(resp)
    console.print(f"[green]MCP servers updated: {', '.join(mcp.keys())}[/green]")
    console.print("[dim]Restart to apply[/dim]")


# ---------------------------------------------------------------------------
# io — channel-based messaging
# ---------------------------------------------------------------------------


@_cogamer_commands.group(invoke_without_command=True)
@click.argument("channel", required=False, default="default")
@click.pass_context
def io(ctx: click.Context, channel: str) -> None:
    """Channel-based messaging. Usage: io [channel] create|list|delete|read|write"""
    ctx.ensure_object(dict)
    ctx.obj["io_channel"] = channel
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


@io.command("create")
@click.pass_context
def io_create(ctx: click.Context) -> None:
    """Create a channel."""
    name = _name(ctx.parent.parent)  # type: ignore[arg-type]
    channel = ctx.parent.obj["io_channel"]  # type: ignore[union-attr]
    resp = _api.post(_url(f"/cogamer/{name}/io/{channel}"))
    _check(resp)
    console.print(f"[green]Channel '{channel}' created[/green]")


@io.command("list")
@click.pass_context
def io_list(ctx: click.Context) -> None:
    """List channels."""
    name = _name(ctx.parent.parent)  # type: ignore[arg-type]
    resp = _api.get(_url(f"/cogamer/{name}/io"))
    _check(resp)
    channels = resp.json()
    if not channels:
        console.print("[dim]No channels[/dim]")
    else:
        for ch in channels:
            console.print(f"{ch['channel_id']}  [dim]{ch.get('created_at', '')}[/dim]")


@io.command("delete")
@click.pass_context
def io_delete(ctx: click.Context) -> None:
    """Delete a channel and all its messages."""
    name = _name(ctx.parent.parent)  # type: ignore[arg-type]
    channel = ctx.parent.obj["io_channel"]  # type: ignore[union-attr]
    resp = _api.delete(_url(f"/cogamer/{name}/io/{channel}"))
    _check(resp)
    console.print(f"[yellow]Channel '{channel}' deleted[/yellow]")


@io.command("write")
@click.argument("message")
@click.pass_context
def io_write(ctx: click.Context, message: str) -> None:
    """Write a message to a channel."""
    name = _name(ctx.parent.parent)  # type: ignore[arg-type]
    channel = ctx.parent.obj["io_channel"]  # type: ignore[union-attr]
    resp = _api.put(_url(f"/cogamer/{name}/io/{channel}"), json={"message": message})
    _check(resp)
    console.print("[dim]sent[/dim]")


@io.command("read")
@click.option("--since", default=None, help="Only messages after this timestamp")
@click.option("--follow", is_flag=True, help="Keep listening for new messages")
@click.option("--timeout", default=60, type=int, help="Timeout in seconds (default: 60)")
@click.pass_context
def io_read(ctx: click.Context, since: str | None, follow: bool, timeout: int) -> None:
    """Read messages from a channel."""
    name = _name(ctx.parent.parent)  # type: ignore[arg-type]
    channel = ctx.parent.obj["io_channel"]  # type: ignore[union-attr]

    last_ts = since
    deadline = time.monotonic() + timeout
    while True:
        params = {"since": last_ts} if last_ts else {}
        resp = _api.get(_url(f"/cogamer/{name}/io/{channel}"), params=params)
        _check(resp)
        msgs = resp.json().get("messages", [])
        for msg in msgs:
            console.print(f"[dim]{msg.get('sender', '?')}:[/dim] {msg['body']}")
            last_ts = msg.get("timestamp")
        if not follow:
            return
        if time.monotonic() >= deadline:
            console.print(f"[yellow]Timed out after {timeout}s[/yellow]")
            raise SystemExit(1)
        time.sleep(2)


# ---------------------------------------------------------------------------
# ctl — ssh, exec, clone, pull, wipe, logs
# ---------------------------------------------------------------------------


@_cogamer_commands.group(invoke_without_command=True)
@click.pass_context
def ctl(ctx: click.Context) -> None:
    """Control commands: ssh, exec, clone, pull, wipe, logs."""
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


@ctl.command("ssh")
@click.option("--iterm", is_flag=True, help="Use tmux -CC (iTerm2 native integration)")
@click.pass_context
def ctl_ssh(ctx: click.Context, iterm: bool) -> None:
    """Connect via SSH."""
    name = _name(ctx.parent.parent)  # type: ignore[arg-type]
    if iterm and os.environ.get("TERM_PROGRAM") != "iTerm.app":
        console.print("[red]--iterm requires running inside iTerm2[/red]")
        sys.exit(1)
    ip = _get_cogamer_ip(name)
    ssh_base = _ssh_args(ip, name) + ["-t", "-o", "SetEnv=TERM=xterm-256color"]
    tmux_cmd = "tmux -CC attach -t main" if iterm else "tmux attach -t main"
    os.execvp("ssh", ssh_base + [tmux_cmd])


@ctl.command("exec")
@click.argument("command")
@click.pass_context
def ctl_exec(ctx: click.Context, command: str) -> None:
    """Run a command on the cogamer via SSH."""
    name = _name(ctx.parent.parent)  # type: ignore[arg-type]
    ip = _get_cogamer_ip(name)
    result = _ssh_run(ip, command, name=name)
    if result.stdout:
        console.print(result.stdout.rstrip())
    if result.returncode != 0 and result.stderr:
        console.print(f"[red]{result.stderr.rstrip()}[/red]")
    raise SystemExit(result.returncode)


@ctl.command("clone")
@click.argument("path", required=False)
@click.pass_context
def ctl_clone(ctx: click.Context, path: str | None) -> None:
    """Clone this cogamer's repo locally."""
    name = _name(ctx.parent.parent)  # type: ignore[arg-type]
    resp = _api.get(_url(f"/cogamer/{name}"))
    if resp.status_code == 404:
        console.print(f"[red]cogamer '{name}' not found[/red]")
        sys.exit(1)
    _check(resp)
    codebase = resp.json().get("codebase", "")
    if not codebase:
        console.print(f"[red]cogamer '{name}' has no codebase URL[/red]")
        sys.exit(1)
    dest = path or name
    console.print(f"[dim]Cloning {codebase} → {dest}[/dim]")
    subprocess.run(["git", "clone", codebase, dest], check=True)
    console.print(f"[green]Cloned to {dest}[/green]")


@ctl.command("pull")
@click.option("--upstream", is_flag=True, help="Sync cogbase from upstream first")
@click.pass_context
def ctl_pull(ctx: click.Context, upstream: bool) -> None:
    """Pull latest changes into the cogamer's repo."""
    name = _name(ctx.parent.parent)  # type: ignore[arg-type]

    if upstream:
        resp = _api.get(_url(f"/cogamer/{name}"))
        _check(resp)
        codebase = resp.json().get("codebase", "")
        repo = codebase.replace("git@github.com:", "").replace(".git", "")
        upstream_result = subprocess.run(
            ["gh", "repo", "view", repo, "--json", "parent", "-q", '.parent.owner.login + "/" + .parent.name'],
            capture_output=True,
            text=True,
        )
        upstream_name = upstream_result.stdout.strip() if upstream_result.returncode == 0 else "upstream"
        console.print(f"[dim]Syncing {repo} from {upstream_name}...[/dim]")
        result = subprocess.run(["gh", "repo", "sync", repo], capture_output=True, text=True)
        if result.returncode == 0:
            console.print(f"[green]Synced with {upstream_name}[/green]")
        else:
            console.print(f"[red]Sync failed: {result.stderr.strip()}[/red]")
            sys.exit(1)

    ip = _get_cogamer_ip(name)
    console.print("[dim]Merging main into working branch...[/dim]")
    result = _ssh_run(ip, "cd ~/repo && git fetch origin && git merge origin/main --no-edit", name=name)
    if result.returncode == 0:
        console.print(f"[green]{result.stdout.strip()}[/green]")
    else:
        console.print(f"[red]{result.stderr.strip()}[/red]")


@ctl.command("wipe")
@click.option("--full", is_flag=True, help="Reset all of .claude/ (not just memory)")
@click.pass_context
def ctl_wipe(ctx: click.Context, full: bool) -> None:
    """Reset .claude/memory/, memory/, and runtime/."""
    name = _name(ctx.parent.parent)  # type: ignore[arg-type]
    ip = _get_cogamer_ip(name)
    claude_target = ".claude" if full else ".claude/memory"
    wipe_cmd = f"cd ~/repo && rm -rf {claude_target} ; rm -rf memory ; rm -rf runtime"
    result = _ssh_run(ip, wipe_cmd, name=name)
    if result.returncode == 0:
        console.print(f"[green]{claude_target} and memory/ reset[/green]")
    else:
        console.print(f"[red]{result.stderr.strip()}[/red]")


@ctl.command("logs")
@click.option("--since", default="10m", help="How far back (e.g. 5m, 1h, 2d). Default: 10m")
@click.option("--max", "max_lines", default=200, type=int, help="Max lines. Default: 200")
@click.pass_context
def ctl_logs(ctx: click.Context, since: str, max_lines: int) -> None:
    """Show CloudWatch logs."""
    name = _name(ctx.parent.parent)  # type: ignore[arg-type]
    resp = _api.get(_url(f"/cogamer/{name}"))
    _check(resp)
    data = resp.json()

    task_arn = data.get("ecs_task_arn")
    if not task_arn:
        console.print("[red]No running task found[/red]")
        return
    task_id = task_arn.rsplit("/", 1)[-1]
    log_stream = f"cogamer/cogamer/{task_id}"

    from cogamer_api.config import get_aws_session

    session = get_aws_session()
    client = session.client("logs", region_name="us-east-1")

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
