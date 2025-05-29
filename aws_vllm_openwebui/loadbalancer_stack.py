from aws_cdk import (
    Stack,
    aws_elasticloadbalancingv2 as elbv2,
    aws_ec2 as ec2,
    Duration,
    CfnOutput,
)
from constructs import Construct


class VLLMLoadBalancerStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, network_stack, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

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

        self.webui_listener = self.webui_alb.add_listener(
            "WebUIListener",
            port=80,
            default_target_groups=[self.webui_target_group]
        )

        # Output the ALB DNS names
        CfnOutput(self, "VLLMALBDnsName", value=self.vllm_alb.load_balancer_dns_name)
        CfnOutput(self, "WebUIEndpoint", 
                 value=f"http://{self.webui_alb.load_balancer_dns_name}",
                 description="WebUI endpoint")
