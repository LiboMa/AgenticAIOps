"""
AgenticAIOps - Bedrock LLM Backend

Support for Amazon Bedrock as the LLM provider.
"""

import json
from typing import Dict, Any, List, Optional
import boto3
from botocore.exceptions import ClientError


class BedrockLLM:
    """
    Amazon Bedrock LLM client for AgenticAIOps.
    
    Supports Claude models via Bedrock's converse API.
    """
    
    def __init__(
        self,
        model_id: str = "anthropic.claude-3-sonnet-20240229-v1:0",
        region: Optional[str] = None
    ):
        """
        Initialize Bedrock client.
        
        Args:
            model_id: Bedrock model ID
            region: AWS region (defaults to session region)
        """
        self.model_id = model_id
        self.region = region or boto3.Session().region_name or "us-east-1"
        
        self.client = boto3.client(
            "bedrock-runtime",
            region_name=self.region
        )
    
    def chat(
        self,
        messages: List[Dict[str, Any]],
        system: Optional[str] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        max_tokens: int = 4096
    ) -> Dict[str, Any]:
        """
        Send a chat request to Bedrock.
        
        Args:
            messages: Conversation messages
            system: System prompt
            tools: Tool definitions
            max_tokens: Maximum tokens to generate
        
        Returns:
            Response from Bedrock
        """
        # Build the request
        request = {
            "modelId": self.model_id,
            "messages": self._convert_messages(messages),
            "inferenceConfig": {
                "maxTokens": max_tokens
            }
        }
        
        if system:
            request["system"] = [{"text": system}]
        
        if tools:
            request["toolConfig"] = {
                "tools": self._convert_tools(tools)
            }
        
        try:
            response = self.client.converse(**request)
            return self._parse_response(response)
        
        except ClientError as e:
            return {
                "success": False,
                "error": str(e),
                "error_code": e.response["Error"]["Code"]
            }
    
    def _convert_messages(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Convert messages to Bedrock format."""
        converted = []
        
        for msg in messages:
            role = msg["role"]
            content = msg["content"]
            
            if role == "system":
                # System messages handled separately
                continue
            
            # Handle different content formats
            if isinstance(content, str):
                converted.append({
                    "role": role,
                    "content": [{"text": content}]
                })
            elif isinstance(content, list):
                # Handle tool use and tool results
                bedrock_content = []
                for item in content:
                    if hasattr(item, "type"):
                        # Anthropic SDK object
                        if item.type == "text":
                            bedrock_content.append({"text": item.text})
                        elif item.type == "tool_use":
                            bedrock_content.append({
                                "toolUse": {
                                    "toolUseId": item.id,
                                    "name": item.name,
                                    "input": item.input
                                }
                            })
                    elif isinstance(item, dict):
                        if item.get("type") == "tool_result":
                            bedrock_content.append({
                                "toolResult": {
                                    "toolUseId": item["tool_use_id"],
                                    "content": [{"text": item["content"]}]
                                }
                            })
                        elif "text" in item:
                            bedrock_content.append({"text": item["text"]})
                
                if bedrock_content:
                    converted.append({
                        "role": role,
                        "content": bedrock_content
                    })
        
        return converted
    
    def _convert_tools(self, tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Convert tool definitions to Bedrock format."""
        converted = []
        
        for tool in tools:
            converted.append({
                "toolSpec": {
                    "name": tool["name"],
                    "description": tool["description"],
                    "inputSchema": {
                        "json": tool["input_schema"]
                    }
                }
            })
        
        return converted
    
    def _parse_response(self, response: Dict[str, Any]) -> Dict[str, Any]:
        """Parse Bedrock response into standard format."""
        output = response.get("output", {})
        message = output.get("message", {})
        
        content = []
        for item in message.get("content", []):
            if "text" in item:
                content.append({
                    "type": "text",
                    "text": item["text"]
                })
            elif "toolUse" in item:
                tool_use = item["toolUse"]
                content.append({
                    "type": "tool_use",
                    "id": tool_use["toolUseId"],
                    "name": tool_use["name"],
                    "input": tool_use["input"]
                })
        
        return {
            "success": True,
            "role": message.get("role", "assistant"),
            "content": content,
            "stop_reason": response.get("stopReason"),
            "usage": response.get("usage", {})
        }


# Model ID mappings for convenience
BEDROCK_MODELS = {
    "claude-3-opus": "anthropic.claude-3-opus-20240229-v1:0",
    "claude-3-sonnet": "anthropic.claude-3-sonnet-20240229-v1:0",
    "claude-3-haiku": "anthropic.claude-3-haiku-20240307-v1:0",
    "claude-3-5-sonnet": "anthropic.claude-3-5-sonnet-20240620-v1:0",
    "claude-instant": "anthropic.claude-instant-v1"
}


def get_bedrock_model_id(model_name: str) -> str:
    """Get full Bedrock model ID from short name."""
    return BEDROCK_MODELS.get(model_name, model_name)
