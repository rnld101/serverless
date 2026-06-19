# Deployment Plan — Hybrid EC2 + Lambda

## Architecture

```
Browser  →  EC2 :80  (Apache → index.html)
             ↓
          EC2 :8000  (uvicorn → FastAPI Orders API)
             ↓
          DynamoDB: OrdersDB
             ↓  (Streams)
          Lambda: NotificationFunction  →  SES Email
```

---

## Step 1 — Verify SES Email (do this first)

SES sandbox requires the sender address to be verified. Click the link in the email that arrives.

```bash
aws ses verify-email-identity \
  --email-address arnoldrnld101@gmail.com \
  --region us-east-1
```

---

## Step 2 — Create DynamoDB Table with Streams

```bash
aws dynamodb create-table \
  --table-name OrdersDB \
  --attribute-definitions \
      AttributeName=customer_id,AttributeType=S \
      AttributeName=order_id,AttributeType=S \
  --key-schema \
      AttributeName=customer_id,KeyType=HASH \
      AttributeName=order_id,KeyType=RANGE \
  --billing-mode PAY_PER_REQUEST \
  --stream-specification StreamEnabled=true,StreamViewType=NEW_IMAGE \
  --region us-east-1
```

Capture the Stream ARN (needed in Step 6):

```bash
aws dynamodb describe-table \
  --table-name OrdersDB \
  --query "Table.LatestStreamArn" \
  --output text \
  --region us-east-1
```

---

## Step 3 — Create IAM Roles

### 3a. EC2 Instance Profile (for Orders API to access DynamoDB)

```bash
# Role that EC2 can assume
aws iam create-role \
  --role-name EC2OrdersRole \
  --assume-role-policy-document '{
    "Version": "2012-10-17",
    "Statement": [{
      "Effect": "Allow",
      "Principal": { "Service": "ec2.amazonaws.com" },
      "Action": "sts:AssumeRole"
    }]
  }'

aws iam attach-role-policy \
  --role-name EC2OrdersRole \
  --policy-arn arn:aws:iam::aws:policy/AmazonDynamoDBFullAccess

# Wrap it in an instance profile so EC2 can use it
aws iam create-instance-profile --instance-profile-name EC2OrdersProfile
aws iam add-role-to-instance-profile \
  --instance-profile-name EC2OrdersProfile \
  --role-name EC2OrdersRole
```

### 3b. Lambda Execution Role (for Notification Lambda)

```bash
aws iam create-role \
  --role-name LambdaNotificationRole \
  --assume-role-policy-document '{
    "Version": "2012-10-17",
    "Statement": [{
      "Effect": "Allow",
      "Principal": { "Service": "lambda.amazonaws.com" },
      "Action": "sts:AssumeRole"
    }]
  }'

aws iam attach-role-policy \
  --role-name LambdaNotificationRole \
  --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole

aws iam attach-role-policy \
  --role-name LambdaNotificationRole \
  --policy-arn arn:aws:iam::aws:policy/AmazonSESFullAccess

aws iam attach-role-policy \
  --role-name LambdaNotificationRole \
  --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaDynamoDBExecutionRole
```

Get the Lambda Role ARN (needed in Step 6):

```bash
aws iam get-role \
  --role-name LambdaNotificationRole \
  --query "Role.Arn" \
  --output text
```

---

## Step 4 — Launch the EC2 Instance

### 4a. Create a Security Group

```bash
aws ec2 create-security-group \
  --group-name orders-sg \
  --description "Orders App Security Group"

# Get the group ID from the output, then open the required ports:
aws ec2 authorize-security-group-ingress \
  --group-name orders-sg \
  --protocol tcp --port 22 --cidr 0.0.0.0/0    # SSH

aws ec2 authorize-security-group-ingress \
  --group-name orders-sg \
  --protocol tcp --port 80 --cidr 0.0.0.0/0    # Apache (index.html)

aws ec2 authorize-security-group-ingress \
  --group-name orders-sg \
  --protocol tcp --port 8000 --cidr 0.0.0.0/0  # FastAPI (uvicorn)
```

### 4b. Launch the instance

Replace `<YOUR_KEY_PAIR>` with your existing key pair name (or create one in the console first):

```bash
aws ec2 run-instances \
  --image-id ami-0e86e20dae9224db8 \
  --instance-type t2.micro \
  --key-name <YOUR_KEY_PAIR> \
  --security-groups orders-sg \
  --iam-instance-profile Name=EC2OrdersProfile \
  --tag-specifications 'ResourceType=instance,Tags=[{Key=Name,Value=OrdersServer}]' \
  --region us-east-1
```

> **AMI note:** `ami-0e86e20dae9224db8` is Ubuntu 22.04 LTS in us-east-1. Verify the latest Ubuntu AMI for your region in the EC2 console if needed.

Get the public IP once the instance is running:

```bash
aws ec2 describe-instances \
  --filters "Name=tag:Name,Values=OrdersServer" \
  --query "Reservations[0].Instances[0].PublicIpAddress" \
  --output text \
  --region us-east-1
```

> Save this IP — you'll use it in SSH commands and in index.html.

---

## Step 5 — Configure the EC2 (SSH in)

```bash
ssh -i <YOUR_KEY_PAIR>.pem ubuntu@<EC2_PUBLIC_IP>
```

### 5a. Install dependencies

```bash
sudo apt update -y && sudo apt upgrade -y
sudo apt install -y python3 python3-pip apache2 git
```

### 5b. Deploy the Orders API

```bash
# Copy your project files to the server (run from your LOCAL machine):
scp -i <YOUR_KEY_PAIR>.pem -r customer-orders-api/ ubuntu@<EC2_PUBLIC_IP>:~/

# Back on the EC2:
cd ~/customer-orders-api
pip3 install -r requirements.txt
```

Create a systemd service so the API runs on boot and restarts if it crashes:

```bash
sudo tee /etc/systemd/system/orders-api.service > /dev/null <<EOF
[Unit]
Description=Orders FastAPI Service
After=network.target

[Service]
User=ubuntu
WorkingDirectory=/home/ubuntu/customer-orders-api
ExecStart=/usr/local/bin/uvicorn main:app --host 0.0.0.0 --port 8000
Restart=always
Environment="DYNAMODB_TABLE_NAME=OrdersDB"
Environment="AWS_DEFAULT_REGION=us-east-1"

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable orders-api
sudo systemctl start orders-api
```

Verify it's running:

```bash
sudo systemctl status orders-api
curl http://localhost:8000/orders
```

### 5c. Update index.html with the real EC2 IP

On your **local machine**, edit line 86 of [index.html](index.html):

```js
// Change this:
const API_BASE_URL = "http://54.92.137.18:8000";

// To this:
const API_BASE_URL = "http://<EC2_PUBLIC_IP>:8000";
```

### 5d. Deploy index.html via Apache

Copy the updated file to the server:

```bash
# From your LOCAL machine:
scp -i <YOUR_KEY_PAIR>.pem index.html ubuntu@<EC2_PUBLIC_IP>:~/
```

Then on the EC2:

```bash
sudo cp ~/index.html /var/www/html/index.html
sudo systemctl enable apache2
sudo systemctl start apache2
```

**Your UI is now live at:** `http://<EC2_PUBLIC_IP>`

---

## Step 6 — Deploy the Notification Lambda

From your **local machine:**

```bash
# Package (no extra dependencies — boto3 is in the Lambda runtime)
zip notification_lambda.zip notification_lambda.py

# Deploy
aws lambda create-function \
  --function-name NotificationFunction \
  --runtime python3.11 \
  --role <LAMBDA_ROLE_ARN> \
  --handler notification_lambda.lambda_handler \
  --zip-file fileb://notification_lambda.zip \
  --timeout 30 \
  --environment "Variables={SENDER=arnoldrnld101@gmail.com,RECIPIENT=arnoldrnld101@gmail.com}" \
  --region us-east-1

# Connect the DynamoDB Stream
aws lambda create-event-source-mapping \
  --function-name NotificationFunction \
  --event-source-arn <STREAM_ARN> \
  --starting-position LATEST \
  --batch-size 10 \
  --region us-east-1
```

---

## Step 7 — End-to-End Demo Test

1. Open `http://<EC2_PUBLIC_IP>` in your browser
2. Create an order (e.g., Customer ID: `CUST-101`, Items: `Laptop, Mouse`)
3. The order appears in the table — confirms EC2 → DynamoDB is working
4. Wait ~30 seconds, check your email — SES email confirms Lambda → Streams → SES is working
5. Change the status dropdown to `COMPLETED` — confirms PATCH is working
6. Click Delete — confirms DELETE is working

---

## Cleanup

```bash
# Terminate EC2
aws ec2 terminate-instances --instance-ids <INSTANCE_ID> --region us-east-1

# Delete Lambda
aws lambda delete-function --function-name NotificationFunction --region us-east-1

# Delete DynamoDB table
aws dynamodb delete-table --table-name OrdersDB --region us-east-1

# Delete security group (after instance is terminated)
aws ec2 delete-security-group --group-name orders-sg --region us-east-1

# Delete IAM roles
aws iam remove-role-from-instance-profile --instance-profile-name EC2OrdersProfile --role-name EC2OrdersRole
aws iam delete-instance-profile --instance-profile-name EC2OrdersProfile
aws iam detach-role-policy --role-name EC2OrdersRole --policy-arn arn:aws:iam::aws:policy/AmazonDynamoDBFullAccess
aws iam delete-role --role-name EC2OrdersRole

aws iam detach-role-policy --role-name LambdaNotificationRole --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole
aws iam detach-role-policy --role-name LambdaNotificationRole --policy-arn arn:aws:iam::aws:policy/AmazonSESFullAccess
aws iam detach-role-policy --role-name LambdaNotificationRole --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaDynamoDBExecutionRole
aws iam delete-role --role-name LambdaNotificationRole
```
