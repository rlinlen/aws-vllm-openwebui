#!/usr/bin/env python3
import os
import aws_cdk as cdk
from aws_vllm_openwebui.network_stack import VLLMNetworkStack
from aws_vllm_openwebui.loadbalancer_stack import VLLMLoadBalancerStack
from aws_vllm_openwebui.service_stack import VLLMServiceStack

app = cdk.App()

# Define environment
env = cdk.Environment(
    account=os.environ.get("CDK_DEFAULT_ACCOUNT"),
    region=os.environ.get("CDK_DEFAULT_REGION")
)

# Create the stacks with dependencies and environment
network_stack = VLLMNetworkStack(app, "VLLMNetworkStack", env=env)
lb_stack = VLLMLoadBalancerStack(app, "VLLMLoadBalancerStack", network_stack, env=env)
service_stack = VLLMServiceStack(app, "VLLMServiceStack", network_stack, lb_stack, env=env)

# Add dependencies
lb_stack.add_dependency(network_stack)
service_stack.add_dependency(lb_stack)

app.synth()
