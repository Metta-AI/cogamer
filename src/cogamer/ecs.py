"""ECS Fargate operations for cogamer containers."""

from __future__ import annotations

from typing import Any

import boto3


class CogamerECS:
    def __init__(
        self,
        cluster: str = "cogamer",
        task_definition: str = "cogamer-task",
        subnets: list[str] | None = None,
        security_groups: list[str] | None = None,
        session: boto3.Session | None = None,
    ):
        _session = session or boto3
        self._client = _session.client("ecs")
        self._ec2 = _session.client("ec2")
        self._cluster = cluster
        self._task_definition = task_definition
        self._subnets = subnets or []
        self._security_groups = security_groups or []

    def run_task(self, cogamer_name: str, env: dict[str, str] | None = None) -> str:
        overrides: dict[str, Any] = {}
        if env:
            overrides["containerOverrides"] = [
                {
                    "name": "cogamer",
                    "environment": [{"name": k, "value": v} for k, v in env.items()],
                }
            ]

        resp = self._client.run_task(
            cluster=self._cluster,
            taskDefinition=self._task_definition,
            launchType="FARGATE",
            enableExecuteCommand=True,
            networkConfiguration={
                "awsvpcConfiguration": {
                    "subnets": self._subnets,
                    "securityGroups": self._security_groups,
                    "assignPublicIp": "ENABLED",
                }
            },
            overrides=overrides,
            tags=[{"key": "cogamer-name", "value": cogamer_name}],
        )
        return resp["tasks"][0]["taskArn"]

    def stop_task(self, task_arn: str) -> None:
        try:
            self._client.stop_task(cluster=self._cluster, task=task_arn, reason="cogamer stop")
        except self._client.exceptions.InvalidParameterException:
            pass  # Task already stopped

    def describe_task(self, task_arn: str) -> dict[str, Any]:
        resp = self._client.describe_tasks(cluster=self._cluster, tasks=[task_arn])
        task = resp["tasks"][0]
        private_ip = None
        public_ip = None

        # Get private IP from container network interfaces
        for container in task.get("containers", []):
            for ni in container.get("networkInterfaces", []):
                private_ip = ni.get("privateIpv4Address")
                break

        # Get public IP from the ENI attachment
        for attachment in task.get("attachments", []):
            if attachment.get("type") == "ElasticNetworkInterface":
                eni_id = None
                for detail in attachment.get("details", []):
                    if detail.get("name") == "networkInterfaceId":
                        eni_id = detail["value"]
                        break
                if eni_id:
                    try:
                        eni_resp = self._ec2.describe_network_interfaces(NetworkInterfaceIds=[eni_id])
                        for ni in eni_resp.get("NetworkInterfaces", []):
                            assoc = ni.get("Association", {})
                            public_ip = assoc.get("PublicIp")
                    except self._ec2.exceptions.ClientError:
                        pass  # ENI gone (task stopped)
                break

        return {
            "task_arn": task["taskArn"],
            "status": task["lastStatus"],
            "ip": private_ip,
            "public_ip": public_ip,
        }
