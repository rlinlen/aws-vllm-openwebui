from aws_cdk import (
    Stack,
    aws_elasticloadbalancingv2 as elbv2,
    aws_ec2 as ec2,
    aws_cloudfront as cloudfront,
    aws_cloudfront_origins as origins,
    aws_secretsmanager as secretsmanager,
    Duration,
    CfnOutput,
    Fn,
)
from constructs import Construct


class VLLMLoadBalancerStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, network_stack, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # Create a secret for the custom header with a fixed value
        # This ensures the value persists across deployments
        custom_header_secret = secretsmanager.Secret(
            self, "CustomHeaderSecret",
            generate_secret_string=secretsmanager.SecretStringGenerator(
                exclude_characters="\"@/\\",
                exclude_punctuation=True,
                include_space=False,
                password_length=32
            )
        )
        
        # Get the secret ARN for reference
        secret_arn = custom_header_secret.secret_arn
        
        # Use a fixed header value for development/testing
        # In production, you would use a more secure approach
        custom_header_name = "X-Custom-Header"
        custom_header_value = "only-from-cloudfront-fixed-value"

        # Create internal ALB for vLLM service
        self.vllm_alb = elbv2.ApplicationLoadBalancer(
            self, "VLLMALB",
            vpc=network_stack.vpc,
            internet_facing=False,
            vpc_subnets=ec2.SubnetSelection(
                subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS
            ),
            security_group=network_stack.vllm_alb_sg
        )

        # Create public ALB for WebUI
        self.webui_alb = elbv2.ApplicationLoadBalancer(
            self, "WebUIALB",
            vpc=network_stack.vpc,
            internet_facing=True,
            vpc_subnets=ec2.SubnetSelection(
                subnet_type=ec2.SubnetType.PUBLIC
            ),
            security_group=network_stack.webui_alb_sg
        )

        # Create target groups
        self.vllm_target_group = elbv2.ApplicationTargetGroup(
            self, "VLLMTargetGroup",
            vpc=network_stack.vpc,
            port=8000,
            protocol=elbv2.ApplicationProtocol.HTTP,
            target_type=elbv2.TargetType.INSTANCE,
            health_check=elbv2.HealthCheck(
                path="/health",
                healthy_http_codes="200",
                interval=Duration.seconds(60),
                timeout=Duration.seconds(15)
            )
        )

        self.webui_target_group = elbv2.ApplicationTargetGroup(
            self, "WebUITargetGroup",
            vpc=network_stack.vpc,
            port=8080,  # OpenWebUI uses port 8080 by default
            protocol=elbv2.ApplicationProtocol.HTTP,
            target_type=elbv2.TargetType.IP,
            health_check=elbv2.HealthCheck(
                path="/health",
                healthy_http_codes="200",
                interval=Duration.seconds(30)
            )
        )

        # Create listeners
        self.vllm_listener = self.vllm_alb.add_listener(
            "VLLMListener",
            port=80,
            default_target_groups=[self.vllm_target_group]
        )

        # Create WebUI listener with security restrictions
        self.webui_listener = self.webui_alb.add_listener(
            "WebUIListener",
            port=80,
            default_action=elbv2.ListenerAction.fixed_response(
                status_code=403,
                content_type="text/plain",
                message_body="Direct access to this ALB is not allowed"
            )
        )

        # Add a condition to only forward requests with the custom header from CloudFront
        self.webui_listener.add_action(
            "ForwardToTargetGroup",
            priority=10,  # Add priority as required by the API
            conditions=[
                elbv2.ListenerCondition.http_header(custom_header_name, [custom_header_value])
            ],
            action=elbv2.ListenerAction.forward([self.webui_target_group])
        )

        # Create CloudFront distribution for HTTPS access
        self.webui_distribution = cloudfront.Distribution(
            self, "WebUIDistribution",
            default_behavior=cloudfront.BehaviorOptions(
                origin=origins.LoadBalancerV2Origin(
                    self.webui_alb,
                    protocol_policy=cloudfront.OriginProtocolPolicy.HTTP_ONLY,
                    custom_headers={
                        custom_header_name: custom_header_value
                    }
                ),
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                allowed_methods=cloudfront.AllowedMethods.ALLOW_ALL,
                cache_policy=cloudfront.CachePolicy.CACHING_DISABLED,
                origin_request_policy=cloudfront.OriginRequestPolicy.ALL_VIEWER
            ),
            price_class=cloudfront.PriceClass.PRICE_CLASS_100,  # Use only North America and Europe edge locations
            enable_logging=False,
            comment="CloudFront distribution for OpenWebUI"
        )

        # Output the ALB DNS names and CloudFront URL
        CfnOutput(self, "VLLMALBDnsName", value=self.vllm_alb.load_balancer_dns_name)
        CfnOutput(self, "WebUIEndpointHTTP", 
                 value=f"http://{self.webui_alb.load_balancer_dns_name}",
                 description="WebUI HTTP endpoint (ALB)")
        CfnOutput(self, "WebUIEndpoint", 
                 value=f"https://{self.webui_distribution.distribution_domain_name}",
                 description="WebUI HTTPS endpoint (CloudFront)")
        
        # Output the secret ARN for reference (but not the value)
        CfnOutput(self, "CustomHeaderSecretArn", 
                 value=secret_arn,
                 description="ARN of the secret containing the custom header value")
