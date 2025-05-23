import aws_cdk as core
import aws_cdk.assertions as assertions

from aws_vllm_openwebui.aws_vllm_openwebui_stack import AwsVllmOpenwebuiStack

# example tests. To run these tests, uncomment this file along with the example
# resource in aws_vllm_openwebui/aws_vllm_openwebui_stack.py
def test_sqs_queue_created():
    app = core.App()
    stack = AwsVllmOpenwebuiStack(app, "aws-vllm-openwebui")
    template = assertions.Template.from_stack(stack)

#     template.has_resource_properties("AWS::SQS::Queue", {
#         "VisibilityTimeout": 300
#     })
