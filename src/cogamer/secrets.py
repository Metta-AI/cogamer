"""Secrets Manager operations for cogamer secrets."""

from __future__ import annotations

import json

import boto3


class CogamerSecrets:
    def __init__(self, prefix: str = "cogamer/", session: boto3.Session | None = None):
        self._client = (session or boto3).client("secretsmanager")
        self._prefix = prefix

    def _secret_id(self, cogamer_name: str) -> str:
        return f"{self._prefix}{cogamer_name}"

    def set_secrets(self, cogamer_name: str, secrets: dict[str, str]) -> None:
        secret_id = self._secret_id(cogamer_name)
        value = json.dumps(secrets)
        try:
            self._client.put_secret_value(SecretId=secret_id, SecretString=value)
        except self._client.exceptions.ResourceNotFoundException:
            self._client.create_secret(Name=secret_id, SecretString=value)

    def get_secrets(self, cogamer_name: str) -> dict[str, str]:
        try:
            resp = self._client.get_secret_value(SecretId=self._secret_id(cogamer_name))
            return json.loads(resp["SecretString"])
        except self._client.exceptions.ResourceNotFoundException:
            return {}

    def list_secret_keys(self, cogamer_name: str) -> list[str]:
        return sorted(self.get_secrets(cogamer_name).keys())

    def delete_secrets(self, cogamer_name: str) -> None:
        try:
            self._client.delete_secret(
                SecretId=self._secret_id(cogamer_name),
                ForceDeleteWithoutRecovery=True,
            )
        except self._client.exceptions.ResourceNotFoundException:
            pass
