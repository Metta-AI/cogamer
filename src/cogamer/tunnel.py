"""Cloudflare Tunnel management for cogamer dashboards.

Provides named tunnels (<name>.softmax-cogamers.com) when Cloudflare credentials
are available, with fallback to quick tunnels (random trycloudflare.com URLs).
"""

from __future__ import annotations

import os
import re
import subprocess
import time

CF_DOMAIN = "softmax-cogamers.com"
CF_ZONE_ID = "44e6c4bd5c8a5983918db813f123324c"


def _cf_headers() -> dict[str, str]:
    return {
        "X-Auth-Email": os.environ["CLOUDFLARE_EMAIL"],
        "X-Auth-Key": os.environ["CLOUDFLARE_API_KEY"],
        "Content-Type": "application/json",
    }


def _cf_api(method: str, path: str, **kwargs: object) -> dict:
    """Make an authenticated Cloudflare API request."""
    import requests

    resp = requests.request(
        method,
        f"https://api.cloudflare.com/client/v4{path}",
        headers=_cf_headers(),
        **kwargs,  # type: ignore[arg-type]
    )
    resp.raise_for_status()
    return resp.json()


def _get_account_id() -> str:
    """Get the Cloudflare account ID."""
    result = _cf_api("GET", "/accounts", params={"per_page": 1})
    return result["result"][0]["id"]


def has_cloudflare_creds() -> bool:
    """Check if Cloudflare API credentials are available."""
    return bool(os.environ.get("CLOUDFLARE_API_KEY") and os.environ.get("CLOUDFLARE_EMAIL"))


def dashboard_url(name: str) -> str:
    """Return the deterministic dashboard URL for a cogamer."""
    return f"https://{name}.{CF_DOMAIN}"


def create_tunnel(name: str) -> str:
    """Create a named Cloudflare tunnel and DNS record for <name>.softmax-cogamers.com.

    Returns the tunnel token for use with `cloudflared tunnel run --token`.
    """
    import base64
    import secrets as _secrets

    hostname = f"{name}.{CF_DOMAIN}"
    tunnel_name = f"cogamer-{name}"
    account_id = _get_account_id()

    # Find or create tunnel
    result = _cf_api(
        "GET",
        f"/accounts/{account_id}/cfd_tunnel",
        params={"name": tunnel_name, "is_deleted": "false"},
    )
    tunnels = result.get("result", [])

    if tunnels:
        tunnel_id = tunnels[0]["id"]
    else:
        tunnel_secret = base64.b64encode(_secrets.token_bytes(32)).decode()
        result = _cf_api(
            "POST",
            f"/accounts/{account_id}/cfd_tunnel",
            json={"name": tunnel_name, "tunnel_secret": tunnel_secret, "config_src": "cloudflare"},
        )
        tunnel_id = result["result"]["id"]

    # Get tunnel token
    token_result = _cf_api("GET", f"/accounts/{account_id}/cfd_tunnel/{tunnel_id}/token")
    tunnel_token = token_result["result"]

    # Create or update DNS CNAME
    cname_target = f"{tunnel_id}.cfargotunnel.com"
    dns_result = _cf_api(
        "GET",
        f"/zones/{CF_ZONE_ID}/dns_records",
        params={"name": hostname, "type": "CNAME"},
    )
    existing = dns_result.get("result", [])

    if existing:
        if existing[0]["content"] != cname_target:
            _cf_api(
                "PATCH",
                f"/zones/{CF_ZONE_ID}/dns_records/{existing[0]['id']}",
                json={"content": cname_target, "proxied": True},
            )
    else:
        _cf_api(
            "POST",
            f"/zones/{CF_ZONE_ID}/dns_records",
            json={"type": "CNAME", "name": hostname, "content": cname_target, "proxied": True},
        )

    # Update tunnel ingress config
    _cf_api(
        "PUT",
        f"/accounts/{account_id}/cfd_tunnel/{tunnel_id}/configurations",
        json={
            "config": {
                "ingress": [
                    {"hostname": hostname, "service": "http://localhost:8080"},
                    {"service": "http_status:404"},
                ]
            }
        },
    )

    return tunnel_token


def delete_tunnel(name: str) -> None:
    """Delete the Cloudflare tunnel and DNS record for a cogamer."""
    hostname = f"{name}.{CF_DOMAIN}"
    tunnel_name = f"cogamer-{name}"
    account_id = _get_account_id()

    # Delete DNS record
    dns_result = _cf_api(
        "GET",
        f"/zones/{CF_ZONE_ID}/dns_records",
        params={"name": hostname, "type": "CNAME"},
    )
    for record in dns_result.get("result", []):
        if "cfargotunnel.com" in record.get("content", ""):
            _cf_api("DELETE", f"/zones/{CF_ZONE_ID}/dns_records/{record['id']}")

    # Delete tunnel
    result = _cf_api(
        "GET",
        f"/accounts/{account_id}/cfd_tunnel",
        params={"name": tunnel_name, "is_deleted": "false"},
    )
    for tunnel in result.get("result", []):
        # Clean up connections first
        _cf_api("DELETE", f"/accounts/{account_id}/cfd_tunnel/{tunnel['id']}/connections")
        _cf_api("DELETE", f"/accounts/{account_id}/cfd_tunnel/{tunnel['id']}")


def run_tunnel_named(token: str) -> subprocess.Popen:
    """Start cloudflared with a named tunnel token."""
    log = os.path.expanduser("~/.cloudflared-tunnel.log")
    return subprocess.Popen(
        ["cloudflared", "tunnel", "--no-autoupdate", "run", "--token", token],
        stdout=open(log, "w"),
        stderr=subprocess.STDOUT,
    )


def run_tunnel_quick() -> str | None:
    """Start a quick (anonymous) Cloudflare tunnel. Returns the URL or None."""
    log = os.path.expanduser("~/.cloudflared-tunnel.log")
    subprocess.Popen(
        ["cloudflared", "tunnel", "--url", "http://localhost:8080", "--no-autoupdate"],
        stdout=open(log, "w"),
        stderr=subprocess.STDOUT,
    )
    for _ in range(30):
        time.sleep(1)
        if os.path.exists(log):
            with open(log) as f:
                for line in f:
                    if "trycloudflare.com" in line:
                        match = re.search(r"(https://[a-z0-9-]+\.trycloudflare\.com)", line)
                        if match:
                            return match.group(1)
    return None
