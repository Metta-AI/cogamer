"""CDK stack for cogamer infrastructure."""

from __future__ import annotations

from aws_cdk import (
    Duration,
    RemovalPolicy,
    Stack,
)
from aws_cdk import (
    aws_apigateway as apigw,
)
from aws_cdk import (
    aws_dynamodb as dynamodb,
)
from aws_cdk import (
    aws_ec2 as ec2,
)
from aws_cdk import (
    aws_ecr as ecr,
)
from aws_cdk import (
    aws_ecs as ecs,
)
from aws_cdk import (
    aws_iam as iam,
)
from aws_cdk import (
    aws_lambda as lambda_,
)
from aws_cdk import (
    aws_logs as logs,
)
from aws_cdk import (
    aws_secretsmanager as secretsmanager,
)
from constructs import Construct


class CogamerStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs: object) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # VPC
        vpc = ec2.Vpc(self, "Vpc", max_azs=2, nat_gateways=1)

        # DynamoDB table
        table = dynamodb.Table(
            self,
            "Table",
            table_name="cogamer",
            partition_key=dynamodb.Attribute(name="pk", type=dynamodb.AttributeType.STRING),
            sort_key=dynamodb.Attribute(name="sk", type=dynamodb.AttributeType.STRING),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.DESTROY,
        )
        table.add_global_secondary_index(
            index_name="gsi-sk",
            partition_key=dynamodb.Attribute(name="sk", type=dynamodb.AttributeType.STRING),
        )

        # ECR repository
        repo = ecr.Repository(
            self,
            "Repo",
            repository_name="cogamer",
            removal_policy=RemovalPolicy.DESTROY,
            empty_on_delete=True,
        )

        # ECS cluster
        ecs.Cluster(self, "Cluster", cluster_name="cogamer", vpc=vpc)

        # Task execution role
        execution_role = iam.Role(
            self,
            "ExecutionRole",
            assumed_by=iam.ServicePrincipal("ecs-tasks.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name("service-role/AmazonECSTaskExecutionRolePolicy"),
            ],
        )

        # Task role (what the container can do)
        task_role = iam.Role(
            self,
            "TaskRole",
            assumed_by=iam.ServicePrincipal("ecs-tasks.amazonaws.com"),
        )
        table.grant_read_write_data(task_role)
        task_role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "secretsmanager:GetSecretValue",
                    "secretsmanager:PutSecretValue",
                    "secretsmanager:CreateSecret",
                    "secretsmanager:DeleteSecret",
                ],
                resources=[
                    f"arn:aws:secretsmanager:{self.region}:{self.account}:secret:cogamer/*",
                ],
            )
        )
        # Bedrock for Claude Code
        task_role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "bedrock:InvokeModel",
                    "bedrock:InvokeModelWithResponseStream",
                ],
                resources=[
                    "arn:aws:bedrock:*::foundation-model/anthropic.*",
                    f"arn:aws:bedrock:*:{self.account}:inference-profile/us.anthropic.*",
                ],
            )
        )
        # SSM for ECS Exec
        task_role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "ssmmessages:CreateControlChannel",
                    "ssmmessages:CreateDataChannel",
                    "ssmmessages:OpenControlChannel",
                    "ssmmessages:OpenDataChannel",
                ],
                resources=["*"],
            )
        )

        # Task definition
        task_def = ecs.FargateTaskDefinition(
            self,
            "TaskDef",
            family="cogamer-task",
            cpu=1024,
            memory_limit_mib=4096,
            execution_role=execution_role,
            task_role=task_role,
        )

        task_def.add_container(
            "cogamer",
            image=ecs.ContainerImage.from_ecr_repository(repo),
            logging=ecs.LogDriver.aws_logs(
                stream_prefix="cogamer",
                log_group=logs.LogGroup(
                    self,
                    "LogGroup",
                    log_group_name="/cogamer/tasks",
                    retention=logs.RetentionDays.ONE_WEEK,
                    removal_policy=RemovalPolicy.DESTROY,
                ),
            ),
            environment={
                "COGAMER_TABLE": table.table_name,
                "COGAMER_API_URL": "https://api.softmax-cogamers.com",
                "AWS_REGION": self.region,
                "AWS_DEFAULT_REGION": self.region,
                "CLAUDE_CODE_USE_BEDROCK": "1",
                "CLAUDE_CODE_ACCEPT_TOS": "1",
            },
        )

        # Security group for tasks
        task_sg = ec2.SecurityGroup(self, "TaskSg", vpc=vpc, allow_all_outbound=True)
        task_sg.add_ingress_rule(ec2.Peer.any_ipv4(), ec2.Port.tcp(22), "SSH access")

        # --- API Lambda ---

        api_lambda_role = iam.Role(
            self,
            "ApiLambdaRole",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name("service-role/AWSLambdaBasicExecutionRole"),
                iam.ManagedPolicy.from_aws_managed_policy_name("service-role/AWSLambdaVPCAccessExecutionRole"),
            ],
        )
        table.grant_read_write_data(api_lambda_role)
        api_lambda_role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "secretsmanager:GetSecretValue",
                    "secretsmanager:PutSecretValue",
                    "secretsmanager:CreateSecret",
                    "secretsmanager:DeleteSecret",
                ],
                resources=[
                    f"arn:aws:secretsmanager:{self.region}:{self.account}:secret:cogamer/*",
                ],
            )
        )
        api_lambda_role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "ecs:RunTask",
                    "ecs:StopTask",
                    "ecs:DescribeTasks",
                    "ecs:TagResource",
                    "ec2:DescribeNetworkInterfaces",
                    "ec2:DescribeSubnets",
                ],
                resources=["*"],
            )
        )
        api_lambda_role.add_to_policy(
            iam.PolicyStatement(
                actions=["iam:PassRole"],
                resources=[execution_role.role_arn, task_role.role_arn],
            )
        )

        public_subnets = vpc.select_subnets(subnet_type=ec2.SubnetType.PUBLIC)

        # Softmax auth secret for user resolution
        softmax_auth_secret = secretsmanager.Secret.from_secret_name_v2(
            self,
            "SoftmaxAuthSecret",
            "cogamer/softmax-auth-secret",
        )
        softmax_auth_secret.grant_read(api_lambda_role)

        api_fn = lambda_.DockerImageFunction(
            self,
            "ApiFunction",
            function_name="cogamer-api",
            code=lambda_.DockerImageCode.from_ecr(repo, tag_or_digest="api-latest"),
            role=api_lambda_role,
            timeout=Duration.seconds(30),
            memory_size=512,
            environment={
                "COGAMER_TABLE": table.table_name,
                "COGAMER_ECS_CLUSTER": "cogamer",
                "COGAMER_ECS_TASK_DEF": "cogamer-task",
                "COGAMER_ECS_SUBNETS": ",".join([s.subnet_id for s in public_subnets.subnets]),
                "COGAMER_ECS_SECURITY_GROUPS": task_sg.security_group_id,
            },
        )

        # --- API Gateway ---
        # Cloudflare handles SSL and proxies to this API Gateway.
        # CNAME api.softmax-cogamers.com -> <api-id>.execute-api.us-east-1.amazonaws.com
        apigw.LambdaRestApi(
            self,
            "ApiGateway",
            handler=api_fn,
            rest_api_name="cogamer-api",
        )
