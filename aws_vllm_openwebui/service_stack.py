from aws_cdk import (
    Stack,
    aws_ecs as ecs,
    aws_ec2 as ec2,
    aws_autoscaling as autoscaling,
    aws_iam as iam,
    aws_secretsmanager as secretsmanager,
    aws_efs as efs,
    Duration,
    RemovalPolicy,
)
from constructs import Construct


class VLLMServiceStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, network_stack, lb_stack, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # Get model name from context or use default
        model_name = self.node.try_get_context("vllm").get("model", "google/medgemma-4b-it") if self.node.try_get_context("vllm") else "google/medgemma-4b-it"

        # Import the existing HuggingFace token secret
        hf_token_secret = secretsmanager.Secret.from_secret_name_v2(
            self, "HFTokenSecret",
            "HuggingFaceToken"  # The name of your pre-created secret
        )

        # Create IAM role for EC2 instances
        role = iam.Role(
            self, "VLLMInstanceRole",
            assumed_by=iam.ServicePrincipal("ec2.amazonaws.com")
        )

        # Add managed policies
        role.add_managed_policy(
            iam.ManagedPolicy.from_aws_managed_policy_name("AmazonSSMManagedInstanceCore")
        )
        
        # Add policy to read HF token
        role.add_to_policy(iam.PolicyStatement(
            actions=["secretsmanager:GetSecretValue"],
            resources=[f"arn:aws:secretsmanager:{self.region}:{self.account}:secret:HuggingFaceToken*"]
        ))

        # Use AWS Deep Learning AMI with GPU support
        dl_ami = ec2.MachineImage.generic_linux({
            "us-east-1": "ami-0fcdcdcc9cf0407ae"  # Deep Learning OSS Nvidia Driver AMI GPU PyTorch 2.6 (Ubuntu 22.04) (64-bit (x86))
        })

        # Create launch template
        launch_template = ec2.LaunchTemplate(
            self, "VLLMLaunchTemplate",
            instance_type=ec2.InstanceType("g5.xlarge"),  # GPU instance for vLLM
            machine_image=dl_ami,
            role=role,
            block_devices=[
                ec2.BlockDevice(
                    device_name="/dev/sda1",  # Root volume (will appear as nvme0n1p1 inside the instance)
                    volume=ec2.BlockDeviceVolume.ebs(
                        volume_size=70,  # 70 GB EBS volume
                        volume_type=ec2.EbsDeviceVolumeType.GP3,  # GP3 for better performance
                        delete_on_termination=True
                    )
                )
            ],
            user_data=ec2.UserData.custom(f'''#!/bin/bash
export PATH=/opt/conda/bin:$PATH

# Install vLLM
python -m pip install --upgrade pip
pip install vllm

# Get HuggingFace token from Secrets Manager
HF_TOKEN=$(aws secretsmanager get-secret-value --secret-id HuggingFaceToken --query SecretString --output text --region {self.region}) 

# Login to HuggingFace
huggingface-cli login --token $HF_TOKEN

# Create service file
cat << EOF > /etc/systemd/system/vllm.service
[Unit]
Description=vLLM Service
After=network.target

[Service]
Environment=HF_TOKEN=$HF_TOKEN
ExecStart=vllm serve {model_name}  --port 8000  --host 0.0.0.0  --gpu-memory-utilization 0.9
Restart=always
User=ubuntu
WorkingDirectory=/home/ubuntu

[Install]
WantedBy=multi-user.target
EOF

# Start vLLM service
systemctl daemon-reload
systemctl enable vllm
systemctl start vllm

# Wait for vLLM to be ready and kill health check
(
  while ! curl -s http://localhost:8000/v1/models > /dev/null; do
    sleep 30
  done
) &
'''),
            security_group=network_stack.vllm_sg
        )

        # Create Auto Scaling Group
        self.vllm_asg = autoscaling.AutoScalingGroup(
            self, "VLLMASG",
            vpc=network_stack.vpc,
            vpc_subnets=ec2.SubnetSelection(
                subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS
            ),
            launch_template=launch_template,
            min_capacity=1,
            max_capacity=2,
            desired_capacity=1
        )

        # Attach ASG to target group
        self.vllm_asg.attach_to_application_target_group(lb_stack.vllm_target_group)

        # Create ECS cluster for WebUI
        self.cluster = ecs.Cluster(
            self, "WebUICluster",
            vpc=network_stack.vpc,
            container_insights=True
        )
        
        # Create EFS file system for persistent storage
        file_system = efs.FileSystem(
            self, "WebUIFileSystem",
            vpc=network_stack.vpc,
            security_group=network_stack.efs_sg,
            encrypted=True,
            performance_mode=efs.PerformanceMode.GENERAL_PURPOSE,
            throughput_mode=efs.ThroughputMode.BURSTING,
            removal_policy=RemovalPolicy.DESTROY  # For testing; change to RETAIN for production
        )
            
        # Create access point for OpenWebUI data directory
        access_point = efs.AccessPoint(
            self, "WebUIAccessPoint",
            file_system=file_system,
            path="/openwebui-data",  # Use root path for simplicity
            create_acl=efs.Acl(
                owner_gid="0",
                owner_uid="0",
                permissions="755"  # More permissive for testing
            ),
            posix_user=efs.PosixUser(
                gid="0",
                uid="0"
            )
        )

        # Create WebUI service
        webui_task = ecs.FargateTaskDefinition(
            self, "WebUITask",
            cpu=2048,
            memory_limit_mib=4096,
            runtime_platform=ecs.RuntimePlatform(
                cpu_architecture=ecs.CpuArchitecture.ARM64  # Use ARM64 for OpenWebUI as specified in README
            )
        )
        
        # Add EFS volume to task definition
        webui_task.add_volume(
            name="webui-data",
            efs_volume_configuration=ecs.EfsVolumeConfiguration(
                file_system_id=file_system.file_system_id,
                transit_encryption="ENABLED",
                authorization_config=ecs.AuthorizationConfig(
                    access_point_id=access_point.access_point_id,
                    iam="ENABLED"
                ),
                root_directory="/"  # Ensure we're mounting from the root
            )
        )

        webui_container = webui_task.add_container(
            "WebUIContainer",
            image=ecs.ContainerImage.from_registry("ghcr.io/open-webui/open-webui:main"),
            environment={
                "ENABLE_OLLAMA_API": "false",
                "OPENAI_API_BASE_URL": f"http://{lb_stack.vllm_alb.load_balancer_dns_name}/v1",
                "DATA_DIR": "/app/backend/data",  # Explicitly set the data directory
                "DATABASE_URL": "sqlite:////app/backend/data/database.db"  # Explicitly set the database path
            },
            logging=ecs.LogDrivers.aws_logs(
                stream_prefix="webui"
            )
        )
        
        # Add mount point for EFS volume
        webui_container.add_mount_points(
            ecs.MountPoint(
                container_path="/app/backend/data",  # OpenWebUI data directory
                source_volume="webui-data",
                read_only=False
            )
        )
        
        # Add user configuration to ensure proper permissions
        webui_task.add_to_task_role_policy(
            iam.PolicyStatement(
                actions=[
                    "elasticfilesystem:ClientMount",
                    "elasticfilesystem:ClientWrite",
                    "elasticfilesystem:ClientRootAccess",
                    "elasticfilesystem:DescribeMountTargets"
                ],
                resources=[file_system.file_system_arn],
                conditions={
                    "Bool": {
                        "elasticfilesystem:AccessedViaMountTarget": "true"
                    }
                }
            )
        )

        webui_container.add_port_mappings(
            ecs.PortMapping(container_port=8080)  # OpenWebUI uses port 8080 by default
        )

        self.webui_service = ecs.FargateService(
            self, "WebUIService",
            cluster=self.cluster,
            task_definition=webui_task,
            security_groups=[network_stack.webui_sg],
            vpc_subnets=ec2.SubnetSelection(
                subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS
            ),
            assign_public_ip=False,
            desired_count=1,
            min_healthy_percent=100,
            platform_version=ecs.FargatePlatformVersion.VERSION1_4  # Required for EFS
        )

        # Attach WebUI service to ALB target group
        self.webui_service.attach_to_application_target_group(lb_stack.webui_target_group)
