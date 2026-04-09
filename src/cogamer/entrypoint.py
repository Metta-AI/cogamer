"""Container entrypoint — boots a cogamer."""

from __future__ import annotations

import importlib.resources
import json
import os
import shlex
import subprocess
import sys
import time

try:
    from cogamer_api.db import CogamerDB
    from cogamer_api.secrets import CogamerSecrets
except ImportError:
    CogamerDB = None  # type: ignore[assignment,misc]
    CogamerSecrets = None  # type: ignore[assignment,misc]


def _render_template(template_name: str, variables: dict[str, str], repo_dir: str | None = None) -> str:
    """Load and render a prompt template.

    If repo_dir is given, check for an override file there first (e.g. COGAMER.md in the repo root).
    Otherwise, load from the package defaults.
    """
    template = None
    if repo_dir:
        repo_override = os.path.join(repo_dir, template_name.upper())
        if os.path.exists(repo_override):
            with open(repo_override) as f:
                template = f.read()
    if template is None:
        ref = importlib.resources.files("cogamer").joinpath(template_name.lower())
        template = ref.read_text()

    for key, value in variables.items():
        template = template.replace(f"{{{{{key}}}}}", value)
    return template


def _run(cmd: list[str], **kwargs: object) -> None:
    subprocess.run(cmd, check=True, **kwargs)  # type: ignore[arg-type]


def main() -> None:
    name = os.environ["COGAMER_NAME"]
    codebase = os.environ["COGAMER_CODEBASE"]
    os.environ.get("COGAMER_API_URL", "http://localhost:8000")
    table_name = os.environ.get("COGAMER_TABLE", "cogamer")

    print(f"[cogamer] Booting cogamer '{name}'...")

    db = CogamerDB(table_name=table_name)
    secrets = CogamerSecrets()

    # 1. Fetch and export secrets
    print("[cogamer] Fetching secrets...")
    secret_values = secrets.get_secrets(name)
    for k, v in secret_values.items():
        os.environ[k] = v

    # 1a. Pre-configure cogames auth from SOFTMAX_TOKEN secret
    softmax_token = os.environ.get("SOFTMAX_TOKEN")
    if softmax_token:
        print("[cogamer] Configuring cogames auth...")
        metta_dir = os.path.expanduser("~/.metta")
        os.makedirs(metta_dir, exist_ok=True)
        import yaml

        cogames_yaml = os.path.join(metta_dir, "cogames.yaml")
        with open(cogames_yaml, "w") as f:
            yaml.safe_dump(
                {"login_tokens": {"https://softmax.com/api": softmax_token}},
                f,
                default_flow_style=False,
            )
        os.chmod(cogames_yaml, 0o600)

    # 2. Fetch config
    print("[cogamer] Fetching config...")
    state = db.get_cogamer(name)
    mcp_servers = state.mcp_servers if state else {}

    # 3. Setup SSH access
    ssh_pubkey = os.environ.get("SSH_PUBLIC_KEY")
    if ssh_pubkey:
        print("[cogamer] Configuring SSH access...")
        ssh_dir = os.path.expanduser("~/.ssh")
        os.makedirs(ssh_dir, exist_ok=True)
        os.chmod(ssh_dir, 0o700)
        auth_keys_path = os.path.join(ssh_dir, "authorized_keys")
        with open(auth_keys_path, "w") as f:
            f.write(ssh_pubkey + "\n")
        os.chmod(auth_keys_path, 0o600)
        # Start sshd as a daemon
        _run(["sudo", "/usr/sbin/sshd"])
    else:
        print("[cogamer] No SSH_PUBLIC_KEY set, skipping SSH setup")

    # 4. Update Claude Code to latest
    print("[cogamer] Updating Claude Code...")
    subprocess.run(["claude", "update"], capture_output=True)

    # 5. Clone codebase
    print(f"[cogamer] Cloning {codebase}...")
    repo_dir = os.path.expanduser("~/repo")
    clone_env = os.environ.copy()
    git_ssh_key = os.environ.get("GIT_SSH_KEY")
    ssh_cmd = "ssh -o StrictHostKeyChecking=no"
    if git_ssh_key:
        ssh_key_path = os.path.expanduser("~/.ssh/cogamer_deploy_key")
        os.makedirs(os.path.dirname(ssh_key_path), exist_ok=True)
        with open(ssh_key_path, "w") as f:
            f.write(git_ssh_key)
            if not git_ssh_key.endswith("\n"):
                f.write("\n")
        os.chmod(ssh_key_path, 0o600)
        ssh_cmd += f" -i {ssh_key_path}"
    clone_env["GIT_SSH_COMMAND"] = ssh_cmd
    # Persist GIT_SSH_COMMAND globally so git pull/push also work
    _run(["git", "config", "--global", "core.sshCommand", ssh_cmd])
    _run(["git", "config", "--global", "user.name", name])
    _run(["git", "config", "--global", "user.email", f"{name}@cogamer.local"])
    _run(["git", "clone", codebase, repo_dir], env=clone_env)

    # Create a working branch: cogamer/<name>/<start-time>, based off the latest one
    from datetime import datetime, timezone

    start_ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    branch_name = f"cogamer/{name}/{start_ts}"
    print(f"[cogamer] Creating branch {branch_name}...")

    # Fetch all remote branches and find the latest cogamer/<name>/* branch
    _run(["git", "-C", repo_dir, "fetch", "origin"])
    result = subprocess.run(
        ["git", "-C", repo_dir, "branch", "-r", "--sort=-committerdate", "--list", f"origin/cogamer/{name}/*"],
        capture_output=True,
        text=True,
    )
    latest_branch = result.stdout.strip().split("\n")[0].strip() if result.stdout.strip() else ""
    if latest_branch:
        print(f"[cogamer] Basing off previous branch: {latest_branch}")
        _run(["git", "-C", repo_dir, "checkout", "-b", branch_name, latest_branch])
        # Merge main to pick up any upstream changes
        subprocess.run(["git", "-C", repo_dir, "merge", "origin/main", "--no-edit"])
    else:
        _run(["git", "-C", repo_dir, "checkout", "-b", branch_name])

    # 4. Configure Claude Code settings
    print("[cogamer] Configuring Claude Code...")
    claude_dir = os.path.expanduser("~/.claude")
    os.makedirs(claude_dir, exist_ok=True)

    # User-level settings
    settings = {
        "skipDangerousModePermissionPrompt": True,
    }
    with open(os.path.join(claude_dir, "settings.json"), "w") as f:
        json.dump(settings, f, indent=2)

    # Add cogamer-channel as a Claude Code channel (pushes messages via notifications)
    print("[cogamer] Adding channel server...")
    mcp_env = [
        "-e",
        f"COGAMER_NAME={name}",
        "-e",
        "COGAMER_API_URL=http://localhost:8000",
    ]
    cogamer_token = os.environ.get("COGAMER_TOKEN", "")
    if cogamer_token:
        mcp_env += ["-e", f"COGAMER_TOKEN={cogamer_token}"]
    _run(
        [
            "claude",
            "mcp",
            "add",
            "cogamer-channel",
            "-s",
            "user",
            *mcp_env,
            "--",
            "python",
            "-m",
            "cogamer.channel.mcp_server",
        ]
    )
    # Add MCP servers from DynamoDB config
    for mcp_name, mcp_uri in mcp_servers.items():
        _run(["claude", "mcp", "add", "--transport", "http", mcp_name, "-s", "user", mcp_uri])
    # Add MCP servers from cogbase cogamer/mcp.yaml
    mcp_yaml_path = os.path.join(repo_dir, "cogamer", "mcp.yaml")
    if os.path.exists(mcp_yaml_path):
        import yaml

        with open(mcp_yaml_path) as f:
            repo_mcps = yaml.safe_load(f) or {}
        for mcp_name, mcp_uri in repo_mcps.items():
            if mcp_name not in mcp_servers:
                print(f"[cogamer] Adding MCP server from cogbase: {mcp_name}")
                _run(["claude", "mcp", "add", "--transport", "http", mcp_name, "-s", "user", mcp_uri])

    # Pre-seed first-run config with project trust
    config_path = os.path.expanduser("~/.claude.json")
    config: dict = {}
    if os.path.exists(config_path):
        with open(config_path) as f:
            config = json.load(f)
    config.update(
        {
            "hasCompletedOnboarding": True,
            "hasAcknowledgedDisclaimer": True,
            "bypassPermissions": True,
        }
    )
    # Pre-trust the repo directory
    projects = config.setdefault("projects", {})
    # Claude Code encodes the project path by replacing / with -
    project_key = repo_dir.replace("/", "-")
    projects[repo_dir] = {
        "allowedTools": [],
        "hasTrustDialogAccepted": True,
    }
    with open(config_path, "w") as f:
        json.dump(config, f, indent=2)

    # Pre-create Claude Code's project memory directory so it doesn't prompt for .claude/ writes
    project_memory_dir = os.path.join(claude_dir, "projects", project_key, "memory")
    os.makedirs(project_memory_dir, exist_ok=True)

    # 5. Set up ~/repo/runtime/ (gitignored) for auto-generated files
    runtime_dir = os.path.join(repo_dir, "runtime")
    os.makedirs(runtime_dir, exist_ok=True)

    # Ensure runtime/ is gitignored
    gitignore_path = os.path.join(repo_dir, ".gitignore")
    gitignore_lines = []
    if os.path.exists(gitignore_path):
        with open(gitignore_path) as f:
            gitignore_lines = f.read().splitlines()
    if "runtime/" not in gitignore_lines:
        with open(gitignore_path, "a") as f:
            f.write("\nruntime/\n")

    _HOOK_SUFFIX = (
        "\n\n---\n\n"
        "**IMPORTANT:** After completing the steps above, check if "
        "`~/repo/cogamer/hooks/on-{name}.md` exists. "
        "If it does, read it and follow those instructions now.\n"
    )

    def _install_skills(label, package_subdir, dest_dir):
        print(f"[cogamer] Installing {label}...")
        os.makedirs(dest_dir, exist_ok=True)
        src = importlib.resources.files("cogamer").joinpath(package_subdir)
        for item in src.iterdir():
            if item.name.endswith(".md"):
                content = item.read_text()
                skill_name = item.name.removesuffix(".md")
                content += _HOOK_SUFFIX.format(name=skill_name)
                with open(os.path.join(dest_dir, item.name), "w") as f:
                    f.write(content)

    _install_skills("lifecycle skills", "lifecycle", os.path.join(runtime_dir, "lifecycle"))
    _install_skills("memory skills", "memory", os.path.join(runtime_dir, "memory"))
    _install_skills("skills", "skills", os.path.join(runtime_dir, "skills"))

    # Symlink repo cogamer/ files (IDENTITY.md, hooks/, etc.) into runtime/
    repo_cogamer_dir = os.path.join(repo_dir, "cogamer")
    if os.path.isdir(repo_cogamer_dir):
        for item in os.listdir(repo_cogamer_dir):
            src = os.path.join(repo_cogamer_dir, item)
            dst = os.path.join(runtime_dir, item)
            if not os.path.exists(dst):
                os.symlink(src, dst)

    # Write AGENTS.md in runtime/ warning not to save there
    with open(os.path.join(runtime_dir, "AGENTS.md"), "w") as f:
        f.write(
            "# Runtime Directory\n\n"
            "**Do not save anything in this directory.** "
            "All contents are auto-generated by the cogamer runtime and will be "
            "overwritten on every restart.\n"
        )

    # 7. Build prompts and inline into AGENTS.md
    print("[cogamer] Writing prompts...")
    mcp_names = ["cogamer-channel"] + list(mcp_servers.keys())
    mcp_list = "\n".join(f"- `{n}`" for n in mcp_names)
    variables = {"name": name, "codebase": codebase, "mcp_list": mcp_list}

    cogamer_md = _render_template("cogamer.md", variables, repo_dir=repo_dir)
    capabilities_md = _render_template("capabilities.md", variables)

    with open(os.path.join(runtime_dir, "COGAMER.md"), "w") as f:
        f.write(cogamer_md)
    with open(os.path.join(runtime_dir, "CAPABILITIES.md"), "w") as f:
        f.write(capabilities_md)

    all_md = f"{cogamer_md}\n\n{capabilities_md}"

    # Inline ALL.md into AGENTS.md, preserving any existing repo instructions
    agents_md_path = os.path.join(repo_dir, "AGENTS.md")
    if os.path.exists(agents_md_path):
        with open(agents_md_path) as f:
            existing = f.read()
        all_md += f"\n\n## Repository Instructions\n\n{existing}\n"

    with open(agents_md_path, "w") as f:
        f.write(all_md)

    # Symlink CLAUDE.md -> AGENTS.md so tools that look for CLAUDE.md find it
    claude_md_path = os.path.join(repo_dir, "CLAUDE.md")
    if os.path.islink(claude_md_path) or os.path.exists(claude_md_path):
        os.remove(claude_md_path)
    os.symlink("AGENTS.md", claude_md_path)

    # 6. Start local API server (so MCP plugin can reach it at localhost:8000)
    print("[cogamer] Starting local API server...")
    subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "cogamer_api.api.app:app", "--host", "127.0.0.1", "--port", "8000"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    # 6a. Start dashboard webserver and Cloudflare tunnel
    dashboard_dir = os.path.join(repo_dir, "cogamer", "dashboard")
    os.makedirs(dashboard_dir, exist_ok=True)
    # Write a placeholder index.html if none exists
    index_path = os.path.join(dashboard_dir, "index.html")
    if not os.path.exists(index_path):
        with open(index_path, "w") as f:
            f.write(f"<html><body><h1>{name}</h1><p>Dashboard not yet generated.</p></body></html>\n")

    print("[cogamer] Starting dashboard server...")
    subprocess.Popen(
        [sys.executable, "-m", "cogamer.dashboard_server", dashboard_dir],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    # Start Cloudflare tunnel for dashboard
    cf_tunnel_token = os.environ.get("CF_TUNNEL_TOKEN")
    if cf_tunnel_token:
        from cogamer.tunnel import dashboard_url, run_tunnel_named

        print(f"[cogamer] Starting named tunnel for {name}.softmax-cogamers.com...")
        run_tunnel_named(cf_tunnel_token)
        time.sleep(5)
        tunnel_url = dashboard_url(name)
        print(f"[cogamer] Dashboard: {tunnel_url}")
        db.update_cogamer(name, tunnel_url=tunnel_url)
    else:
        from cogamer.tunnel import run_tunnel_quick

        print("[cogamer] Starting quick tunnel (no CF_TUNNEL_TOKEN)...")
        tunnel_url = run_tunnel_quick()
        if tunnel_url:
            print(f"[cogamer] Dashboard: {tunnel_url}")
            db.update_cogamer(name, tunnel_url=tunnel_url)
        else:
            print("[cogamer] WARNING: Could not get tunnel URL")

    # 7. Persist env vars for all shells (SSH, tmux, etc.)
    print("[cogamer] Persisting environment...")
    aws_region = os.environ.get("AWS_REGION", os.environ.get("AWS_DEFAULT_REGION", "us-east-1"))
    persistent_env = {
        "CLAUDE_CODE_USE_BEDROCK": "1",
        "CLAUDE_CODE_ACCEPT_TOS": "1",
        "AWS_REGION": aws_region,
        "AWS_DEFAULT_REGION": aws_region,
        # Make uv commands use the system environment directly so `uv sync` /
        # `uv run` don't create a venv and re-download 7 GB of pre-installed deps.
        "UV_PROJECT_ENVIRONMENT": "/usr/local",
        "UV_NO_CACHE": "1",
    }
    for k, v in persistent_env.items():
        os.environ[k] = v

    # Write to .bashrc so SSH sessions and tmux panes also get them
    # Skip multiline values (e.g. SSH keys) — they break shell export syntax
    env_lines = []
    for k, v in os.environ.items():
        if not k.startswith(("AWS_", "CLAUDE_", "COGAMER_", "UV_")):
            continue
        if "\n" in v:
            continue
        env_lines.append(f"export {k}={shlex.quote(v)}")
    bashrc_path = os.path.expanduser("~/.bashrc")
    with open(bashrc_path, "a") as f:
        f.write("\n# cogamer env\n" + "\n".join(env_lines) + "\n")

    # 8. Start tmux and launch Claude Code (mngr-style: interactive shell + send-keys)
    print("[cogamer] Launching claude-code...")
    claude_cmd = "claude --dangerously-skip-permissions"
    start_prompt = "Read and follow ~/repo/runtime/lifecycle/start.md"

    def _launch_claude() -> None:
        # Create tmux session with explicit dimensions (prevents 0x0 PTY bug)
        _run(["tmux", "new-session", "-d", "-s", "main", "-x", "200", "-y", "50", "-c", repo_dir, "bash -i"])
        time.sleep(1)
        # Type claude command into the interactive shell (env vars loaded from .bashrc)
        _run(["tmux", "send-keys", "-t", "main:0", claude_cmd, "Enter"])
        # Wait for Claude to initialize, then send the start lifecycle prompt
        time.sleep(5)
        _run(["tmux", "send-keys", "-t", "main:0", start_prompt, "Enter"])

    _launch_claude()

    # 9. Update status
    db.update_cogamer(name, status="ready")
    print(f"[cogamer] Cogamer '{name}' is ready.")

    # 10. Health check loop
    while True:
        time.sleep(30)
        result = subprocess.run(["tmux", "has-session", "-t", "main"], capture_output=True)
        if result.returncode != 0:
            print("[cogamer] tmux session died, restarting claude-code...")
            _launch_claude()
        db.update_cogamer(name, status="ready")


if __name__ == "__main__":
    main()
