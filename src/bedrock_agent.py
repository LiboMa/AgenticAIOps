"""
AgenticAIOps - Bedrock AgentCore Integration

Uses Amazon Bedrock Agents for the agentic loop instead of direct LLM calls.
This provides AWS-native agent orchestration with built-in memory and action groups.
"""

import boto3
import json
import time
import uuid
from typing import Dict, Any, List, Optional
from botocore.exceptions import ClientError


class BedrockAgentCore:
    """
    Manages Amazon Bedrock Agent for EKS operations.
    
    Bedrock Agents provide:
    - Native action group management
    - Built-in session memory
    - Automatic prompt orchestration
    - Trace visibility
    """
    
    def __init__(self, region: str = "ap-southeast-1"):
        """Initialize Bedrock Agent clients."""
        self.region = region
        self.bedrock_agent = boto3.client("bedrock-agent", region_name=region)
        self.bedrock_agent_runtime = boto3.client("bedrock-agent-runtime", region_name=region)
        self.iam = boto3.client("iam", region_name=region)
        self.lambda_client = boto3.client("lambda", region_name=region)
        
        self.agent_id = None
        self.agent_alias_id = None
    
    def create_agent(
        self,
        agent_name: str = "aiops-eks-agent",
        foundation_model: str = "anthropic.claude-3-sonnet-20240229-v1:0",
        description: str = "AI-powered EKS operations agent"
    ) -> Dict[str, Any]:
        """
        Create a new Bedrock Agent for EKS operations.
        
        Args:
            agent_name: Name of the agent
            foundation_model: Bedrock model ID
            description: Agent description
        
        Returns:
            Agent creation response
        """
        # Create IAM role for the agent
        role_arn = self._create_agent_role(agent_name)
        
        # Agent instruction (system prompt)
        instruction = """You are an expert Site Reliability Engineer (SRE) AI assistant 
specialized in managing Amazon EKS clusters. Your role is to help operators diagnose issues, 
understand cluster state, and perform remediation actions.

When investigating issues:
1. First, get an overview of the cluster state
2. Drill down into specific problems
3. Check logs and events for root causes
4. Provide clear recommendations with severity levels

For write operations (scale, restart, rollback), always explain the impact and ask for confirmation.

Be thorough but concise. Prioritize cluster stability and safety."""

        try:
            response = self.bedrock_agent.create_agent(
                agentName=agent_name,
                foundationModel=foundation_model,
                instruction=instruction,
                description=description,
                agentResourceRoleArn=role_arn,
                idleSessionTTLInSeconds=1800,  # 30 minutes
            )
            
            self.agent_id = response["agent"]["agentId"]
            
            return {
                "success": True,
                "agent_id": self.agent_id,
                "agent_name": agent_name,
                "status": response["agent"]["agentStatus"]
            }
        
        except ClientError as e:
            return {
                "success": False,
                "error": str(e)
            }
    
    def create_action_group(
        self,
        action_group_name: str,
        lambda_arn: str,
        api_schema: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Create an action group for the agent.
        
        Action groups define the tools/APIs the agent can use.
        
        Args:
            action_group_name: Name of the action group
            lambda_arn: ARN of the Lambda function handling actions
            api_schema: OpenAPI schema defining the actions
        
        Returns:
            Action group creation response
        """
        if not self.agent_id:
            return {"success": False, "error": "Agent not created yet"}
        
        try:
            response = self.bedrock_agent.create_agent_action_group(
                agentId=self.agent_id,
                agentVersion="DRAFT",
                actionGroupName=action_group_name,
                actionGroupExecutor={
                    "lambda": lambda_arn
                },
                apiSchema={
                    "payload": json.dumps(api_schema)
                },
                actionGroupState="ENABLED"
            )
            
            return {
                "success": True,
                "action_group_id": response["agentActionGroup"]["actionGroupId"],
                "action_group_name": action_group_name
            }
        
        except ClientError as e:
            return {
                "success": False,
                "error": str(e)
            }
    
    def prepare_agent(self) -> Dict[str, Any]:
        """
        Prepare the agent for use (compile and validate).
        
        Must be called after creating action groups.
        """
        if not self.agent_id:
            return {"success": False, "error": "Agent not created yet"}
        
        try:
            response = self.bedrock_agent.prepare_agent(agentId=self.agent_id)
            
            # Wait for preparation to complete
            while True:
                agent = self.bedrock_agent.get_agent(agentId=self.agent_id)
                status = agent["agent"]["agentStatus"]
                
                if status == "PREPARED":
                    break
                elif status == "FAILED":
                    return {"success": False, "error": "Agent preparation failed"}
                
                time.sleep(2)
            
            return {
                "success": True,
                "status": "PREPARED"
            }
        
        except ClientError as e:
            return {
                "success": False,
                "error": str(e)
            }
    
    def create_agent_alias(self, alias_name: str = "live") -> Dict[str, Any]:
        """
        Create an alias for the agent (required for invocation).
        
        Args:
            alias_name: Name of the alias
        
        Returns:
            Alias creation response
        """
        if not self.agent_id:
            return {"success": False, "error": "Agent not created yet"}
        
        try:
            response = self.bedrock_agent.create_agent_alias(
                agentId=self.agent_id,
                agentAliasName=alias_name
            )
            
            self.agent_alias_id = response["agentAlias"]["agentAliasId"]
            
            # Wait for alias to be ready
            while True:
                alias = self.bedrock_agent.get_agent_alias(
                    agentId=self.agent_id,
                    agentAliasId=self.agent_alias_id
                )
                status = alias["agentAlias"]["agentAliasStatus"]
                
                if status == "PREPARED":
                    break
                elif status == "FAILED":
                    return {"success": False, "error": "Alias creation failed"}
                
                time.sleep(2)
            
            return {
                "success": True,
                "alias_id": self.agent_alias_id,
                "alias_name": alias_name
            }
        
        except ClientError as e:
            return {
                "success": False,
                "error": str(e)
            }
    
    def invoke_agent(
        self,
        input_text: str,
        session_id: Optional[str] = None,
        enable_trace: bool = True
    ) -> Dict[str, Any]:
        """
        Invoke the agent with a user message.
        
        Args:
            input_text: User's input message
            session_id: Session ID for conversation continuity
            enable_trace: Whether to return trace information
        
        Returns:
            Agent response with optional trace
        """
        if not self.agent_id or not self.agent_alias_id:
            return {"success": False, "error": "Agent not ready"}
        
        if not session_id:
            session_id = str(uuid.uuid4())
        
        try:
            response = self.bedrock_agent_runtime.invoke_agent(
                agentId=self.agent_id,
                agentAliasId=self.agent_alias_id,
                sessionId=session_id,
                inputText=input_text,
                enableTrace=enable_trace
            )
            
            # Process streaming response
            completion = ""
            traces = []
            
            for event in response["completion"]:
                if "chunk" in event:
                    chunk = event["chunk"]
                    if "bytes" in chunk:
                        completion += chunk["bytes"].decode("utf-8")
                
                if "trace" in event and enable_trace:
                    traces.append(event["trace"])
            
            return {
                "success": True,
                "session_id": session_id,
                "response": completion,
                "traces": traces
            }
        
        except ClientError as e:
            return {
                "success": False,
                "error": str(e)
            }
    
    def _create_agent_role(self, agent_name: str) -> str:
        """Create IAM role for the Bedrock Agent."""
        role_name = f"BedrockAgentRole-{agent_name}"
        
        trust_policy = {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Principal": {
                        "Service": "bedrock.amazonaws.com"
                    },
                    "Action": "sts:AssumeRole"
                }
            ]
        }
        
        try:
            response = self.iam.create_role(
                RoleName=role_name,
                AssumeRolePolicyDocument=json.dumps(trust_policy),
                Description=f"Role for Bedrock Agent {agent_name}"
            )
            role_arn = response["Role"]["Arn"]
            
            # Attach required policies
            self.iam.attach_role_policy(
                RoleName=role_name,
                PolicyArn="arn:aws:iam::aws:policy/AmazonBedrockFullAccess"
            )
            
            # Wait for role to propagate
            time.sleep(10)
            
            return role_arn
        
        except self.iam.exceptions.EntityAlreadyExistsException:
            # Role already exists, get its ARN
            response = self.iam.get_role(RoleName=role_name)
            return response["Role"]["Arn"]


# OpenAPI schema for EKS operations action group
EKS_OPERATIONS_SCHEMA = {
    "openapi": "3.0.0",
    "info": {
        "title": "EKS Operations API",
        "version": "1.0.0",
        "description": "API for Kubernetes/EKS cluster operations"
    },
    "paths": {
        "/pods": {
            "get": {
                "operationId": "getPods",
                "summary": "List pods in a namespace",
                "description": "Get all pods with their status in a Kubernetes namespace",
                "parameters": [
                    {
                        "name": "namespace",
                        "in": "query",
                        "description": "Kubernetes namespace (default: default)",
                        "required": False,
                        "schema": {"type": "string"}
                    },
                    {
                        "name": "labelSelector",
                        "in": "query",
                        "description": "Label selector to filter pods",
                        "required": False,
                        "schema": {"type": "string"}
                    }
                ],
                "responses": {
                    "200": {
                        "description": "List of pods with status",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "pods": {"type": "array"}
                                    }
                                }
                            }
                        }
                    }
                }
            }
        },
        "/pods/{podName}/logs": {
            "get": {
                "operationId": "getPodLogs",
                "summary": "Get pod logs",
                "description": "Retrieve logs from a specific pod",
                "parameters": [
                    {
                        "name": "podName",
                        "in": "path",
                        "required": True,
                        "schema": {"type": "string"}
                    },
                    {
                        "name": "namespace",
                        "in": "query",
                        "required": False,
                        "schema": {"type": "string"}
                    },
                    {
                        "name": "tailLines",
                        "in": "query",
                        "required": False,
                        "schema": {"type": "integer", "default": 100}
                    }
                ],
                "responses": {
                    "200": {
                        "description": "Pod logs"
                    }
                }
            }
        },
        "/events": {
            "get": {
                "operationId": "getEvents",
                "summary": "Get cluster events",
                "description": "Retrieve Kubernetes events",
                "parameters": [
                    {
                        "name": "namespace",
                        "in": "query",
                        "required": False,
                        "schema": {"type": "string"}
                    }
                ],
                "responses": {
                    "200": {
                        "description": "Cluster events"
                    }
                }
            }
        },
        "/deployments": {
            "get": {
                "operationId": "getDeployments",
                "summary": "List deployments",
                "description": "Get all deployments with replica status",
                "parameters": [
                    {
                        "name": "namespace",
                        "in": "query",
                        "required": False,
                        "schema": {"type": "string"}
                    }
                ],
                "responses": {
                    "200": {
                        "description": "List of deployments"
                    }
                }
            }
        },
        "/deployments/{name}/scale": {
            "post": {
                "operationId": "scaleDeployment",
                "summary": "Scale a deployment",
                "description": "Change the replica count of a deployment",
                "parameters": [
                    {
                        "name": "name",
                        "in": "path",
                        "required": True,
                        "schema": {"type": "string"}
                    },
                    {
                        "name": "namespace",
                        "in": "query",
                        "required": False,
                        "schema": {"type": "string"}
                    }
                ],
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "properties": {
                                    "replicas": {"type": "integer"}
                                },
                                "required": ["replicas"]
                            }
                        }
                    }
                },
                "responses": {
                    "200": {
                        "description": "Scale result"
                    }
                }
            }
        },
        "/deployments/{name}/restart": {
            "post": {
                "operationId": "restartDeployment",
                "summary": "Restart a deployment",
                "description": "Perform a rolling restart of a deployment",
                "parameters": [
                    {
                        "name": "name",
                        "in": "path",
                        "required": True,
                        "schema": {"type": "string"}
                    },
                    {
                        "name": "namespace",
                        "in": "query",
                        "required": False,
                        "schema": {"type": "string"}
                    }
                ],
                "responses": {
                    "200": {
                        "description": "Restart result"
                    }
                }
            }
        },
        "/cluster/health": {
            "get": {
                "operationId": "getClusterHealth",
                "summary": "Check cluster health",
                "description": "Comprehensive health check of the EKS cluster",
                "responses": {
                    "200": {
                        "description": "Cluster health status"
                    }
                }
            }
        },
        "/analyze/pod/{podName}": {
            "get": {
                "operationId": "analyzePod",
                "summary": "Analyze pod issues",
                "description": "Automated analysis of pod problems with recommendations",
                "parameters": [
                    {
                        "name": "podName",
                        "in": "path",
                        "required": True,
                        "schema": {"type": "string"}
                    },
                    {
                        "name": "namespace",
                        "in": "query",
                        "required": False,
                        "schema": {"type": "string"}
                    }
                ],
                "responses": {
                    "200": {
                        "description": "Analysis results with recommendations"
                    }
                }
            }
        }
    }
}


def setup_agent(region: str = "ap-southeast-1") -> BedrockAgentCore:
    """
    Set up and return a configured Bedrock Agent.
    
    This is a convenience function for quick setup.
    """
    agent = BedrockAgentCore(region=region)
    
    # Create the agent
    result = agent.create_agent()
    if not result.get("success"):
        raise RuntimeError(f"Failed to create agent: {result.get('error')}")
    
    print(f"Created agent: {result['agent_id']}")
    
    # Note: Action group creation requires a Lambda function
    # This would be created separately and its ARN passed here
    
    return agent
