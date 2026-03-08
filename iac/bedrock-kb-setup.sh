#!/bin/bash
# =============================================================================
# AgenticAIOps - Bedrock Knowledge Base Setup
# IaC Reference Script
# =============================================================================

REGION="ap-southeast-1"
ACCOUNT_ID="533267047935"
KB_ROLE_NAME="AgenticAIOps-KB-Role"
S3_BUCKET="agentic-aiops-kb-1769960769"
COLLECTION_NAME="agentic-aiops-kb"

# -----------------------------------------------------------------------------
# 1. Create IAM Role for Bedrock KB
# -----------------------------------------------------------------------------
cat > /tmp/kb-trust-policy.json << 'POLICY'
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Principal": {
                "Service": "bedrock.amazonaws.com"
            },
            "Action": "sts:AssumeRole",
            "Condition": {
                "StringEquals": {
                    "aws:SourceAccount": "ACCOUNT_ID"
                }
            }
        }
    ]
}
POLICY
sed -i "s/ACCOUNT_ID/$ACCOUNT_ID/g" /tmp/kb-trust-policy.json

aws iam create-role \
    --role-name $KB_ROLE_NAME \
    --assume-role-policy-document file:///tmp/kb-trust-policy.json

# S3 access policy
aws iam put-role-policy \
    --role-name $KB_ROLE_NAME \
    --policy-name S3Access \
    --policy-document "{
        \"Version\": \"2012-10-17\",
        \"Statement\": [{
            \"Effect\": \"Allow\",
            \"Action\": [\"s3:GetObject\", \"s3:ListBucket\"],
            \"Resource\": [
                \"arn:aws:s3:::$S3_BUCKET\",
                \"arn:aws:s3:::$S3_BUCKET/*\"
            ]
        }]
    }"

# Bedrock policy
aws iam attach-role-policy \
    --role-name $KB_ROLE_NAME \
    --policy-arn arn:aws:iam::aws:policy/AmazonBedrockFullAccess

# -----------------------------------------------------------------------------
# 2. Create OpenSearch Serverless Collection
# -----------------------------------------------------------------------------

# Encryption policy
aws opensearchserverless create-security-policy \
    --name ${COLLECTION_NAME}-encryption \
    --type encryption \
    --policy "{\"Rules\":[{\"ResourceType\":\"collection\",\"Resource\":[\"collection/$COLLECTION_NAME\"]}],\"AWSOwnedKey\":true}" \
    --region $REGION

# Network policy
aws opensearchserverless create-security-policy \
    --name ${COLLECTION_NAME}-network \
    --type network \
    --policy "[{\"Rules\":[{\"ResourceType\":\"collection\",\"Resource\":[\"collection/$COLLECTION_NAME\"]},{\"ResourceType\":\"dashboard\",\"Resource\":[\"collection/$COLLECTION_NAME\"]}],\"AllowFromPublic\":true}]" \
    --region $REGION

# Data access policy
aws opensearchserverless create-access-policy \
    --name ${COLLECTION_NAME}-data \
    --type data \
    --policy "[{\"Rules\":[{\"ResourceType\":\"collection\",\"Resource\":[\"collection/$COLLECTION_NAME\"],\"Permission\":[\"aoss:CreateCollectionItems\",\"aoss:UpdateCollectionItems\",\"aoss:DescribeCollectionItems\"]},{\"ResourceType\":\"index\",\"Resource\":[\"index/$COLLECTION_NAME/*\"],\"Permission\":[\"aoss:CreateIndex\",\"aoss:UpdateIndex\",\"aoss:DescribeIndex\",\"aoss:ReadDocument\",\"aoss:WriteDocument\"]}],\"Principal\":[\"arn:aws:iam::$ACCOUNT_ID:role/$KB_ROLE_NAME\"]}]" \
    --region $REGION

# Create collection
aws opensearchserverless create-collection \
    --name $COLLECTION_NAME \
    --type VECTORSEARCH \
    --region $REGION

echo "等待 Collection 变为 ACTIVE..."
# Wait for collection to be active (typically 3-5 minutes)

# -----------------------------------------------------------------------------
# 3. Create Bedrock Knowledge Base
# -----------------------------------------------------------------------------
# (After collection is ACTIVE)

# Get collection ARN
COLLECTION_ARN=$(aws opensearchserverless batch-get-collection \
    --names $COLLECTION_NAME \
    --region $REGION \
    --query 'collectionDetails[0].arn' --output text)

# Create Knowledge Base
aws bedrock-agent create-knowledge-base \
    --name "AgenticAIOps-KB" \
    --role-arn "arn:aws:iam::$ACCOUNT_ID:role/$KB_ROLE_NAME" \
    --knowledge-base-configuration "{
        \"type\": \"VECTOR\",
        \"vectorKnowledgeBaseConfiguration\": {
            \"embeddingModelArn\": \"arn:aws:bedrock:$REGION::foundation-model/amazon.titan-embed-text-v1\"
        }
    }" \
    --storage-configuration "{
        \"type\": \"OPENSEARCH_SERVERLESS\",
        \"opensearchServerlessConfiguration\": {
            \"collectionArn\": \"$COLLECTION_ARN\",
            \"vectorIndexName\": \"bedrock-knowledge-base-default-index\",
            \"fieldMapping\": {
                \"vectorField\": \"bedrock-knowledge-base-default-vector\",
                \"textField\": \"AMAZON_BEDROCK_TEXT_CHUNK\",
                \"metadataField\": \"AMAZON_BEDROCK_METADATA\"
            }
        }
    }" \
    --region $REGION

# -----------------------------------------------------------------------------
# 4. Create Data Source
# -----------------------------------------------------------------------------
# (After KB is created, use KB_ID from above)

# aws bedrock-agent create-data-source \
#     --name "eks-patterns" \
#     --knowledge-base-id $KB_ID \
#     --data-source-configuration "{
#         \"type\": \"S3\",
#         \"s3Configuration\": {
#             \"bucketArn\": \"arn:aws:s3:::$S3_BUCKET\",
#             \"inclusionPrefixes\": [\"eks-patterns/\"]
#         }
#     }" \
#     --region $REGION

echo "完成！"
