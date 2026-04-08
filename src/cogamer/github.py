"""GitHub App authentication and repo operations for the cogamer platform."""

import time

import httpx
import jwt
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)

GITHUB_API = "https://api.github.com"


class GitHubApp:
    """Authenticate as a GitHub App and perform repo operations."""

    def __init__(self, app_id: str, pem: str):
        """Initialize with GitHub App ID and PEM private key."""
        self.app_id = app_id
        self.pem = pem

    def _generate_jwt(self) -> str:
        """Generate a JWT signed with the App's PEM. Valid for 10 minutes."""
        now = int(time.time())
        payload = {
            "iat": now - 60,
            "exp": now + 600,
            "iss": self.app_id,
        }
        return jwt.encode(payload, self.pem, algorithm="RS256")

    def _get_installation_id(self) -> int:
        """GET /app/installations, return the first installation's ID."""
        token = self._generate_jwt()
        resp = httpx.get(
            f"{GITHUB_API}/app/installations",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
            },
        )
        resp.raise_for_status()
        return resp.json()[0]["id"]

    def _get_installation_token(self) -> str:
        """POST /app/installations/{id}/access_tokens. Returns the token string."""
        installation_id = self._get_installation_id()
        token = self._generate_jwt()
        resp = httpx.post(
            f"{GITHUB_API}/app/installations/{installation_id}/access_tokens",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
            },
        )
        resp.raise_for_status()
        return resp.json()["token"]

    def fork_repo(self, source_repo: str, new_name: str, org: str = "softmax-agents") -> str:
        """Fork source_repo into org with the given name.

        Returns the full repo name (org/new_name).
        GitHub forks are async -- poll until the repo exists (max 30s, 2s intervals).
        """
        token = self._get_installation_token()
        headers = {
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github+json",
        }

        resp = httpx.post(
            f"{GITHUB_API}/repos/{source_repo}/forks",
            headers=headers,
            json={"organization": org, "name": new_name},
        )
        resp.raise_for_status()

        full_name = f"{org}/{new_name}"
        deadline = time.time() + 30
        while time.time() < deadline:
            check = httpx.get(
                f"{GITHUB_API}/repos/{full_name}",
                headers=headers,
            )
            if check.status_code == 200:
                print(f"Fork ready: {full_name}")
                return full_name
            time.sleep(2)

        raise TimeoutError(f"Fork {full_name} not ready after 30s")

    def add_deploy_key(
        self,
        repo: str,
        title: str,
        public_key: str,
        read_only: bool = False,
    ) -> None:
        """POST /repos/{owner}/{repo}/keys. Adds an SSH deploy key."""
        token = self._get_installation_token()
        resp = httpx.post(
            f"{GITHUB_API}/repos/{repo}/keys",
            headers={
                "Authorization": f"token {token}",
                "Accept": "application/vnd.github+json",
            },
            json={
                "title": title,
                "key": public_key,
                "read_only": read_only,
            },
        )
        resp.raise_for_status()


def create_repo_with_deploy_key(
    app_id: str,
    pem: str,
    name: str,
    source_repo: str = "softmax-agents/cogamer",
    org: str = "softmax-agents",
) -> tuple[str, str]:
    """High-level: fork repo and set up deploy key.

    1. Create GitHubApp with app_id and pem
    2. Fork source_repo -> org/name
    3. Generate ed25519 SSH key pair
    4. Add public key as deploy key (write access)
    5. Return (repo_full_name, private_key_pem_string)
    """
    app = GitHubApp(app_id, pem)
    repo_full_name = app.fork_repo(source_repo, name, org=org)

    # Generate ed25519 key pair
    private_key = Ed25519PrivateKey.generate()
    private_key_pem = private_key.private_bytes(Encoding.PEM, PrivateFormat.OpenSSH, NoEncryption()).decode()
    public_key_ssh = private_key.public_key().public_bytes(Encoding.OpenSSH, PublicFormat.OpenSSH).decode()

    app.add_deploy_key(repo_full_name, f"cogamer-{name}", public_key_ssh, read_only=False)

    return repo_full_name, private_key_pem
