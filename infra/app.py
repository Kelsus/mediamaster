#!/usr/bin/env python3
import os

import aws_cdk as cdk

from stacks.mediamaster_stack import MediamasterStack

app = cdk.App()
MediamasterStack(
    app,
    "Mediamaster",
    env=cdk.Environment(
        account=os.environ.get("CDK_DEFAULT_ACCOUNT"),
        region="us-east-1",
    ),
)
app.synth()
