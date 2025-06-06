# vLLM with OpenWebUI on AWS ECS

This CDK project deploys a scalable vLLM inference service with OpenWebUI on AWS ECS. The infrastructure includes GPU-powered instances for vLLM and ARM instances for the web interface, all configured with security and scalability best practices.

## Architecture

- **vLLM Service**:
  - Runs on g5.xlarge instances with GPU support
  - Deployed in private subnets
  - Uses internal Application Load Balancer
  - Sticky sessions for memory state retention
  - HuggingFace authentication integration
  - Serves google/medgemma-4b-it model

- **OpenWebUI**:
  - Uses official image (ghcr.io/open-webui/open-webui:main)
  - Runs on t4g.large ARM instances
  - Public access through Application Load Balancer
  - Automatic connection to vLLM service

## Prerequisites

1. AWS CDK CLI installed
2. Python 3.x
3. AWS CLI configured with appropriate credentials
4. HuggingFace account and API token
5. Docker installed locally for building images
6. Currently, the cdk supports only the us-east-1 and us-west-2. 

## Setup

1. Create and activate a virtual environment:
   ```bash
   uv venv
   source .venv/bin/activate
   ```

2. Install dependencies:
   ```bash
   uv pip install -r requirements.txt
   ```

3. Configure HuggingFace token:
   - Create a token at https://huggingface.co/settings/tokens
   - Create a secret in AWS Secrets Manager before deployment:
     ```bash
     aws secretsmanager create-secret \
         --name HuggingFaceToken \
         --description "HuggingFace API token for vLLM service" \
         --secret-string "hf_your_token_here"
     ```

4. Accept MedGemma license on Huggingface Model Card (https://huggingface.co/google/medgemma-4b-it)
![](./img/MedGemmaLicense.png)

## Deployment

1. Bootstrap CDK (if not already done):
   ```bash
   cdk bootstrap
   ```

2. Deploy the stacks:
   ```bash
   cdk deploy --all
   ```

3. After deployment:
   - The OpenWebUI URL will be displayed in the outputs (both HTTP and HTTPS URLs)
   - The HTTPS URL uses CloudFront for secure access
   - Wait for the model to download and initialize (this may take several minutes)
   - Access the OpenWebUI interface using the HTTPS URL from the outputs

## Project Structure

```
.
├── aws_vllm_openwebui/
│   ├── network_stack.py      # VPC, subnets, and security groups
│   ├── loadbalancer_stack.py # ALBs and target groups
│   └── service_stack.py      # ECS and EC2 services
├── docker/
│   ├── vllm/
│   │   ├── Dockerfile       # vLLM service container
│   │   └── entrypoint.sh    # vLLM startup script
├── app.py                    # CDK app entry point
├── requirements.txt          # Python dependencies
└── cdk.json                 # CDK configuration
```

## Configuration

### vLLM Service

- Model: google/medgemma-4b-it
- Instance type: g5.xlarge
- Memory limit: 15GB
- GPU count: 1
- Auto-scaling enabled

### OpenWebUI

- Image: ghcr.io/open-webui/open-webui:main
- Instance type: t4g.large
- Memory limit: 3GB
- Public access enabled

## Security

- Services run in private subnets
- Only OpenWebUI ALB is internet-facing, but restricted to CloudFront access only
- CloudFront provides HTTPS access with a valid SSL certificate
- Custom header authentication between CloudFront and ALB
- HuggingFace token stored in Secrets Manager
- Internal communication secured
- Auto-scaling groups in private subnets

## Monitoring

- CloudWatch logs enabled for both services
- Container insights enabled
- Health checks configured
- ALB metrics available

### Checking vLLM Logs

To check vLLM service logs on the EC2 instance:

1. Find the instance id of the EC2 instance from the console.

2. Connect to the EC2 instance using SSM Session Manager:
   ```bash
   aws ssm start-session --target <instance-id>
   ```

3. View the vLLM service logs using journalctl:
   ```bash
   sudo journalctl -u vllm.service -f
   ```

4. Check system logs for GPU-related information:
   ```bash
   sudo dmesg | grep -i nvidia
   ```

### Checking OpenWebUI Logs

To check OpenWebUI logs:

1. Open the Elastic Container Service console in AWS
2. Select the ECS cluster (name will look like "VLLMServiceStack-WebUICluster*")
3. Click the Service with the name look like "VLLMServiceStack-WebUIService*"
4. View the "Logs" Tab

You can also use AWS CLI to fetch the logs:
```bash
# First, find the exact log group name
aws logs describe-log-groups --log-group-name-prefix "VLLMServiceStack-WebUITaskWebUIContainerLogGroup"

# Then list log streams using the exact name from the output above
aws logs describe-log-streams --log-group-name "EXACT_LOG_GROUP_NAME"

# Get logs from a specific stream
aws logs get-log-events --log-group-name "EXACT_LOG_GROUP_NAME" --log-stream-name "stream-name"
```

## Model Initialization

After deployment, the vLLM service will begin downloading and loading the model, which can take 10-15 minutes depending on your internet connection and instance type.

### Initialization Phases:
1. **Instance Startup**: EC2 instance boots and runs user data script (~2 minutes)
2. **Model Download**: The model files are downloaded from HuggingFace (~5-10 minutes)
3. **Model Loading**: The model is loaded into GPU memory (~3-5 minutes)
4. **Service Ready**: The vLLM API becomes available

During this time, the OpenWebUI interface will be available, but you may see connection errors until the model is ready to use.

### Checking Status:
You can monitor the initialization process by checking the EC2 instance logs:
```bash
# Connect to the EC2 instance
aws ssm start-session --target i-instanceid

# View the vLLM service logs
sudo journalctl -u vllm.service -f

# Check if the model is loaded and API is responding
curl http://localhost:8000/v1/models
```

When the model is fully loaded, you'll see log messages indicating that the API server is running and the model is ready to serve requests.
- View logs: Check CloudWatch Logs in AWS Console
- The Open WebUI will also display the google/medGemma from the dropdown model menu

## Useful commands

- Deploy changes: `cdk deploy --all`
- Compare changes: `cdk diff`
- Destroy stacks: `cdk destroy --all`

## Cost Considerations

- g5.xlarge instances for vLLM (GPU instances, major cost)
- t4g.large instances for OpenWebUI
- Application Load Balancers
- Data transfer between services
- CloudWatch Logs storage
- Secrets Manager usage

## Troubleshooting

1. Deployment issues:
   - In case you find the errors related to "This CDK CLI is not compatible with the CDK library used by your application.", either upgrade your cdk cli version, or use npx to run a specific version without having to upgrade the CDK CLI.
   e.g. "npx aws-cdk@2.1005.0 bootstrap"

2. Model initialization issues:
   - Check vLLM service logs in CloudWatch
   - Verify HuggingFace token is correctly set and the license is accepted
   - Ensure enough storage for model

3. Connection issues:
   - Verify security group rules
   - Check ALB health checks
   - Validate network configuration

4. Performance issues:
   - Monitor GPU utilization
   - Check memory usage
   - Verify sticky session configuration

## License

This project is licensed under the MIT License - see the LICENSE file for details.
