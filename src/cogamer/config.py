"""Configuration for the cogamer control plane."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import boto3


@dataclass
class Config:
    """Control plane configuration."""

    aws_region: str = "us-east-1"
    aws_role_arn: str = "arn:aws:iam::815935788409:role/OrganizationAccountAccessRole"
    aws_source_profile: str = "softmax-org"
    ecs_cluster: str = "cogamer"
    ecs_task_definition: str = "cogamer-task"
    ecs_subnets: list[str] = field(default_factory=list)
    ecs_security_groups: list[str] = field(default_factory=list)
    dynamodb_table: str = "cogamer"
    secrets_prefix: str = "cogamer/"
    api_url: str = "https://api.softmax-cogamers.com"
    login_service_url: str = "https://softmax.com"
    softmax_auth_secret_name: str = "cogamer/softmax-auth-secret"
    github_app_id_secret_name: str = "cogamer/github-app-id"
    github_app_pem_secret_name: str = "cogamer/github-app-pem"
    github_org: str = "softmax-agents"
    github_template_repo: str = "softmax-agents/cogamer"


_config: Config | None = None


def load_config() -> Config:
    """Load config from ~/.cogamer/config.yaml, with env var overrides."""
    global _config
    if _config is not None:
        return _config

    cfg = Config()

    config_path = Path.home() / ".cogamer" / "config.yaml"
    if config_path.exists():
        import yaml

        with open(config_path) as f:
            data = yaml.safe_load(f) or {}
        for k, v in data.items():
            if hasattr(cfg, k):
                setattr(cfg, k, v)

    # Env var overrides
    if v := os.environ.get("AWS_REGION"):
        cfg.aws_region = v
    if v := os.environ.get("COGAMER_ROLE_ARN"):
        cfg.aws_role_arn = v
    if v := os.environ.get("COGAMER_SOURCE_PROFILE"):
        cfg.aws_source_profile = v
    if v := os.environ.get("COGAMER_ECS_CLUSTER"):
        cfg.ecs_cluster = v
    if v := os.environ.get("COGAMER_ECS_TASK_DEF"):
        cfg.ecs_task_definition = v
    if v := os.environ.get("COGAMER_ECS_SUBNETS"):
        cfg.ecs_subnets = [s.strip() for s in v.split(",") if s.strip()]
    if v := os.environ.get("COGAMER_ECS_SECURITY_GROUPS"):
        cfg.ecs_security_groups = [s.strip() for s in v.split(",") if s.strip()]
    if v := os.environ.get("COGAMER_TABLE"):
        cfg.dynamodb_table = v
    if v := os.environ.get("COGAMER_API_URL"):
        cfg.api_url = v
    if v := os.environ.get("COGAMER_LOGIN_SERVICE_URL"):
        cfg.login_service_url = v
    if v := os.environ.get("COGAMER_SOFTMAX_AUTH_SECRET_NAME"):
        cfg.softmax_auth_secret_name = v

    _config = cfg
    return cfg


_softmax_auth_secret: str | None = None


def get_softmax_auth_secret() -> str | None:
    """Load the softmax auth secret from AWS Secrets Manager (cached)."""
    global _softmax_auth_secret
    if _softmax_auth_secret is not None:
        return _softmax_auth_secret

    # Allow direct env var override for local dev
    if v := os.environ.get("SOFTMAX_AUTH_SECRET"):
        _softmax_auth_secret = v
        return v

    cfg = load_config()
    try:
        session = get_aws_session()
        client = session.client("secretsmanager")
        resp = client.get_secret_value(SecretId=cfg.softmax_auth_secret_name)
        _softmax_auth_secret = resp["SecretString"].strip()
        return _softmax_auth_secret
    except Exception:
        return None


def get_aws_session() -> boto3.Session:
    """Get a boto3 session with auto-refreshing credentials.

    Uses STS role assumption locally via botocore's RefreshableCredentials,
    so tokens are re-assumed transparently before they expire.
    In containers (ECS task role), uses default credentials which auto-refresh
    via the metadata endpoint.
    """
    from botocore.credentials import DeferredRefreshableCredentials
    from botocore.session import get_session as get_botocore_session

    cfg = load_config()

    # Inside AWS (ECS task role / Lambda execution role), default credentials auto-refresh
    if (
        os.environ.get("ECS_CONTAINER_METADATA_URI_V4")
        or os.environ.get("ECS_CONTAINER_METADATA_URI")
        or os.environ.get("AWS_LAMBDA_FUNCTION_NAME")
    ):
        return boto3.Session(region_name=cfg.aws_region)

    def _refresh():
        source_session = boto3.Session(profile_name=cfg.aws_source_profile)
        sts = source_session.client("sts")
        creds = sts.assume_role(
            RoleArn=cfg.aws_role_arn,
            RoleSessionName="cogamer-api",
        )["Credentials"]
        return {
            "access_key": creds["AccessKeyId"],
            "secret_key": creds["SecretAccessKey"],
            "token": creds["SessionToken"],
            "expiry_time": creds["Expiration"].isoformat(),
        }

    botocore_session = get_botocore_session()
    botocore_session._credentials = DeferredRefreshableCredentials(
        method="sts-assume-role",
        refresh_using=_refresh,
    )
    return boto3.Session(botocore_session=botocore_session, region_name=cfg.aws_region)
