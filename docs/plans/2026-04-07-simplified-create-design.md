# Simplified Cogamer Create Flow

**Date:** 2026-04-07

## Goal

Move cogamer creation entirely to the API. CLI becomes a one-liner. Uses a GitHub App installed in the `softmax-agents` org to fork repos and manage deploy keys.

## Current Flow (to be replaced)

CLI does: fork repo, clone, write IDENTITY.md, push, call API, generate deploy key, upload secrets (SOFTMAX_TOKEN, COGAMER_TOKEN, SSH keys), set up Cloudflare tunnel, run on-create hook.

## New Flow

### CLI

```
cogamer <name> create
```

Calls `POST /cogamers {"name": "<name>"}`. Prints status + token. Done.

### API (`POST /cogamers`)

1. Fetch GitHub App PEM from Secrets Manager (`cogamer/github-app-pem`)
2. Generate GitHub App installation token for `softmax-agents` org
3. Fork `softmax-agents/cogamer` → `softmax-agents/<name>` via GitHub API
4. Wait for fork to be ready
5. Generate ed25519 SSH key pair
6. Add public key as deploy key on `softmax-agents/<name>` (write access)
7. Store private key in Secrets Manager (`cogamer/<name>/GIT_SSH_KEY`)
8. Create CogamerState in DynamoDB (codebase = `git@github.com:softmax-agents/<name>.git`)
9. Launch ECS task
10. Return state + token

### Container Boot

No changes to core boot sequence. Container:
- Fetches `GIT_SSH_KEY` from Secrets Manager (as before)
- Clones via SSH (as before)
- SOFTMAX_TOKEN is no longer guaranteed at boot — skip cogames.yaml setup if missing

## GitHub App Details

- **Org:** `softmax-agents`
- **App PEM:** stored in Secrets Manager at `cogamer/github-app-pem`
- **App ID:** stored in Secrets Manager at `cogamer/github-app-id` (or hardcoded/env var)
- **Permissions needed:** repo creation, deploy key management, contents read/write
- **Installation token:** scoped to org, short-lived (1hr), only used during create

## What's Removed

- CLI-side: fork logic, `gh` CLI calls, deploy key generation, secret uploads, SOFTMAX_TOKEN handling, Cloudflare tunnel setup, on-create hook, cogbase validation, IDENTITY.md initialization
- Entrypoint: SOFTMAX_TOKEN/cogames.yaml setup made optional

## Files Changed

- **New:** `src/cogamer/github.py` — GitHub App auth, fork, deploy key
- **Modify:** `src/cogamer/api/routes.py` — create endpoint does everything
- **Simplify:** `src/cogamer/cli.py` — create becomes thin API call
- **Modify:** `src/cogamer/entrypoint.py` — SOFTMAX_TOKEN setup optional
