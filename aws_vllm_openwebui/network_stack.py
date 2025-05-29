from aws_cdk import (
    Stack,
    aws_ec2 as ec2,
    CfnOutput,
)
from constructs import Construct


class VLLMNetworkStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # Create VPC with public and private subnets
        self.vpc = ec2.Vpc(
            self, "VPC",
            max_azs=2,
            nat_gateways=1,
            subnet_configuration=[
                ec2.SubnetConfiguration(
                    name="Public",
                    subnet_type=ec2.SubnetType.PUBLIC,
                    cidr_mask=24
                ),
                ec2.SubnetConfiguration(
                    name="Private",
                    subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS,
                    cidr_mask=24
                )
            ]
        )

        # Create security groups for ALBs
        self.vllm_alb_sg = ec2.SecurityGroup(
            self, "VLLMALBSecurityGroup",
            vpc=self.vpc,
            description="Security group for vLLM ALB",
            allow_all_outbound=True
        )

        self.webui_alb_sg = ec2.SecurityGroup(
            self, "WebUIALBSecurityGroup",
            vpc=self.vpc,
            description="Security group for WebUI ALB",
            allow_all_outbound=True
        )

        # Create security groups for services
        self.vllm_sg = ec2.SecurityGroup(
            self, "VLLMSecurityGroup",
            vpc=self.vpc,
            description="Security group for vLLM instances",
            allow_all_outbound=True
        )

        self.webui_sg = ec2.SecurityGroup(
            self, "WebUISecurityGroup",
            vpc=self.vpc,
            description="Security group for WebUI service",
            allow_all_outbound=True
        )

        # Allow WebUI ALB to access WebUI service
        self.webui_sg.add_ingress_rule(
            self.webui_alb_sg,
            ec2.Port.tcp(80),
            "Allow access from WebUI ALB"
        )

        # Allow vLLM ALB to access vLLM service
        self.vllm_sg.add_ingress_rule(
            self.vllm_alb_sg,
            ec2.Port.tcp(8000),
            "Allow access from vLLM ALB"
        )

        # Allow WebUI service to access vLLM ALB
        self.vllm_alb_sg.add_ingress_rule(
            self.webui_sg,
            ec2.Port.tcp(80),
            "Allow access from WebUI service"
        )

        # Allow public access to WebUI ALB
        self.webui_alb_sg.add_ingress_rule(
            ec2.Peer.any_ipv4(),
            ec2.Port.tcp(80),
            "Allow public HTTP access"
        )
        
        # Allow EFS access from WebUI security group
        self.efs_sg = ec2.SecurityGroup(
            self, "EFSSecurityGroup",
            vpc=self.vpc,
            description="Security group for EFS",
            allow_all_outbound=True
        )
        
        # Allow NFS access from WebUI security group to EFS security group
        self.efs_sg.add_ingress_rule(
            self.webui_sg,
            ec2.Port.tcp(2049),
            "Allow NFS access from WebUI service"
        )
        
        # Add a more permissive rule for ECS tasks
        self.efs_sg.add_ingress_rule(
            ec2.Peer.ipv4(self.vpc.vpc_cidr_block),
            ec2.Port.tcp(2049),
            "Allow NFS access from all resources in VPC"
        )

        # Outputs
        CfnOutput(self, "VpcId", value=self.vpc.vpc_id)
