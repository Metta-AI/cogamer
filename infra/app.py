#!/usr/bin/env python3
"""CDK app entry point."""

import aws_cdk as cdk
from stack import CogamerStack

app = cdk.App()
CogamerStack(
    app,
    "CogamerStack",
    env=cdk.Environment(account="815935788409", region="us-east-1"),
)
app.synth()
