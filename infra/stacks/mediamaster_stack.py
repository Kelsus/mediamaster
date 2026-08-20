from pathlib import Path

import aws_cdk as cdk
from aws_cdk import (
    aws_apigatewayv2 as apigwv2,
    aws_apigatewayv2_integrations as apigwv2_integrations,
    aws_cloudfront as cloudfront,
    aws_cloudfront_origins as origins,
    aws_cognito as cognito,
    aws_dynamodb as dynamodb,
    aws_events as events,
    aws_events_targets as targets,
    aws_iam as iam,
    aws_lambda as lambda_,
    aws_s3 as s3,
    aws_s3_deployment as s3_deployment,
)
from constructs import Construct

REPO_ROOT = Path(__file__).resolve().parents[2]

# Rewrites extensionless paths to the SPA entry point. Attached only to the
# default (S3) behavior, so /api/* is never touched.
SPA_REWRITE_FN = """\
function handler(event) {
  var request = event.request;
  if (!request.uri.includes('.')) {
    request.uri = '/index.html';
  }
  return request;
}
"""


class MediamasterStack(cdk.Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # Passkey RP ID must equal the domain the app is served from. The
        # CloudFront domain is only known after the first deploy, so it arrives
        # via context (deploy.sh does a second pass with the real value).
        rp_id = self.node.try_get_context("rp_id") or "localhost"

        table = dynamodb.TableV2(
            self,
            "Table",
            table_name="mediamaster",
            partition_key=dynamodb.Attribute(name="PK", type=dynamodb.AttributeType.STRING),
            sort_key=dynamodb.Attribute(name="SK", type=dynamodb.AttributeType.STRING),
            billing=dynamodb.Billing.on_demand(),
            point_in_time_recovery_specification=dynamodb.PointInTimeRecoverySpecification(
                point_in_time_recovery_enabled=True
            ),
            removal_policy=cdk.RemovalPolicy.RETAIN,
        )

        user_pool = cognito.UserPool(
            self,
            "UserPool",
            user_pool_name="mediamaster",
            feature_plan=cognito.FeaturePlan.ESSENTIALS,
            sign_in_aliases=cognito.SignInAliases(email=True),
            sign_in_policy=cognito.SignInPolicy(
                allowed_first_auth_factors=cognito.AllowedFirstAuthFactors(
                    password=True, passkey=True
                )
            ),
            self_sign_up_enabled=False,
            passkey_relying_party_id=rp_id,
            passkey_user_verification=cognito.PasskeyUserVerification.REQUIRED,
            removal_policy=cdk.RemovalPolicy.RETAIN,
        )
        client = user_pool.add_client(
            "SpaClient",
            auth_flows=cognito.AuthFlow(user=True),
            prevent_user_existence_errors=True,
        )

        bundle = lambda_.Code.from_asset(str(REPO_ROOT / "backend" / "lambda_build"))
        anthropic_key_param = "/mediamaster/anthropic-api-key"

        # Taste engine: long-running, invoked async, calls the Claude API.
        scorer_fn = lambda_.Function(
            self,
            "ScorerFunction",
            runtime=lambda_.Runtime.PYTHON_3_12,
            architecture=lambda_.Architecture.ARM_64,
            handler="mediamaster_api.scorer.handler",
            code=bundle,
            memory_size=512,
            timeout=cdk.Duration.minutes(15),
            environment={
                "TABLE_NAME": table.table_name,
                "ANTHROPIC_KEY_PARAM": anthropic_key_param,
                "USER_POOL_ID": user_pool.user_pool_id,
            },
        )
        table.grant_read_write_data(scorer_fn)
        scorer_fn.add_to_role_policy(
            iam.PolicyStatement(
                actions=["ssm:GetParameter"],
                resources=[
                    f"arn:aws:ssm:{self.region}:{self.account}:parameter{anthropic_key_param}"
                ],
            )
        )
        # The scheduled scout resolves the pool's single user itself.
        scorer_fn.add_to_role_policy(
            iam.PolicyStatement(
                actions=["cognito-idp:ListUsers"],
                resources=[user_pool.user_pool_arn],
            )
        )

        # Monthly season scout: 09:00 UTC on the 1st.
        events.Rule(
            self,
            "MonthlySeasonScout",
            schedule=events.Schedule.cron(minute="0", hour="9", day="1", month="*", year="*"),
            targets=[
                targets.LambdaFunction(
                    scorer_fn,
                    event=events.RuleTargetInput.from_object({"mode": "scout"}),
                )
            ],
        )

        api_fn = lambda_.Function(
            self,
            "ApiFunction",
            runtime=lambda_.Runtime.PYTHON_3_12,
            architecture=lambda_.Architecture.ARM_64,
            handler="mediamaster_api.main.handler",
            code=bundle,
            memory_size=512,
            timeout=cdk.Duration.seconds(28),
            environment={
                "TABLE_NAME": table.table_name,
                "USER_POOL_ID": user_pool.user_pool_id,
                "USER_POOL_CLIENT_ID": client.user_pool_client_id,
                "SCORER_FUNCTION_NAME": scorer_fn.function_name,
            },
        )
        table.grant_read_write_data(api_fn)
        scorer_fn.grant_invoke(api_fn)

        http_api = apigwv2.HttpApi(
            self,
            "HttpApi",
            default_integration=apigwv2_integrations.HttpLambdaIntegration("ApiIntegration", api_fn),
        )

        site_bucket = s3.Bucket(
            self,
            "SiteBucket",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            removal_policy=cdk.RemovalPolicy.DESTROY,
            auto_delete_objects=True,
        )

        spa_rewrite = cloudfront.Function(
            self,
            "SpaRewrite",
            code=cloudfront.FunctionCode.from_inline(SPA_REWRITE_FN),
            runtime=cloudfront.FunctionRuntime.JS_2_0,
        )

        api_domain = cdk.Fn.select(2, cdk.Fn.split("/", http_api.api_endpoint))
        distribution = cloudfront.Distribution(
            self,
            "Distribution",
            default_behavior=cloudfront.BehaviorOptions(
                origin=origins.S3BucketOrigin.with_origin_access_control(site_bucket),
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                cache_policy=cloudfront.CachePolicy.CACHING_OPTIMIZED,
                compress=True,
                function_associations=[
                    cloudfront.FunctionAssociation(
                        function=spa_rewrite,
                        event_type=cloudfront.FunctionEventType.VIEWER_REQUEST,
                    )
                ],
            ),
            additional_behaviors={
                "/api/*": cloudfront.BehaviorOptions(
                    origin=origins.HttpOrigin(api_domain),
                    viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.HTTPS_ONLY,
                    allowed_methods=cloudfront.AllowedMethods.ALLOW_ALL,
                    cache_policy=cloudfront.CachePolicy.CACHING_DISABLED,
                    origin_request_policy=cloudfront.OriginRequestPolicy.ALL_VIEWER_EXCEPT_HOST_HEADER,
                )
            },
            default_root_object="index.html",
        )

        frontend_dist = REPO_ROOT / "frontend" / "dist"
        if frontend_dist.is_dir():
            s3_deployment.BucketDeployment(
                self,
                "SiteDeployment",
                sources=[s3_deployment.Source.asset(str(frontend_dist))],
                destination_bucket=site_bucket,
                distribution=distribution,
                distribution_paths=["/*"],
            )

        cdk.CfnOutput(self, "DistributionDomain", value=distribution.distribution_domain_name)
        cdk.CfnOutput(self, "AppUrl", value=f"https://{distribution.distribution_domain_name}")
        cdk.CfnOutput(self, "UserPoolId", value=user_pool.user_pool_id)
        cdk.CfnOutput(self, "UserPoolClientId", value=client.user_pool_client_id)
        cdk.CfnOutput(self, "TableName", value=table.table_name)
        cdk.CfnOutput(self, "RpId", value=rp_id)
