"""
AgenticAIOps - Main Agent

The core agent that orchestrates tools and LLM interactions.
"""

import json
from typing import Dict, Any, List, Optional, Callable
from dataclasses import dataclass
import anthropic

from .tools.kubernetes import KubernetesTools, KUBERNETES_TOOLS
from .tools.aws import AWSTools, AWS_TOOLS
from .tools.diagnostics import DiagnosticTools, DIAGNOSTIC_TOOLS
from .prompts.system import SYSTEM_PROMPT


@dataclass
class ToolCall:
    """Represents a tool call request from the LLM."""
    name: str
    arguments: Dict[str, Any]
    id: str


class AgenticAIOpsAgent:
    """
    The main agent class that coordinates between:
    - User input
    - LLM reasoning
    - Tool execution
    - Response generation
    """
    
    def __init__(
        self,
        cluster_name: str,
        region: Optional[str] = None,
        model: str = "claude-sonnet-4-20250514",
        require_confirmation: bool = True,
        api_key: Optional[str] = None
    ):
        """
        Initialize the agent.
        
        Args:
            cluster_name: EKS cluster name to operate on
            region: AWS region
            model: Claude model to use
            require_confirmation: Whether to require confirmation for write ops
            api_key: Anthropic API key (uses ANTHROPIC_API_KEY env var if not provided)
        """
        self.cluster_name = cluster_name
        self.model = model
        self.require_confirmation = require_confirmation
        
        # Initialize tools
        self.k8s = KubernetesTools()
        self.aws = AWSTools(region=region)
        self.diagnostics = DiagnosticTools(self.k8s, self.aws)
        
        # Initialize LLM client
        self.client = anthropic.Anthropic(api_key=api_key)
        
        # Track conversation history
        self.messages: List[Dict[str, Any]] = []
        
        # Pending confirmation state
        self.pending_action: Optional[Dict[str, Any]] = None
        
        # Tool registry
        self._register_tools()
    
    def _register_tools(self):
        """Register all available tools."""
        self.tools_schema = []
        self.tool_handlers: Dict[str, Callable] = {}
        
        # Write operations that need confirmation
        self.write_operations = {
            "scale_deployment",
            "restart_deployment",
            "rollback_deployment"
        }
        
        # Kubernetes tools
        for tool in KUBERNETES_TOOLS:
            self._add_tool(
                name=tool["name"],
                description=tool["description"],
                parameters=tool["parameters"],
                handler=getattr(self.k8s, tool["name"])
            )
        
        # AWS tools
        for tool in AWS_TOOLS:
            self._add_tool(
                name=tool["name"],
                description=tool["description"],
                parameters=tool["parameters"],
                handler=getattr(self.aws, tool["name"])
            )
        
        # Diagnostic tools
        for tool in DIAGNOSTIC_TOOLS:
            self._add_tool(
                name=tool["name"],
                description=tool["description"],
                parameters=tool["parameters"],
                handler=getattr(self.diagnostics, tool["name"])
            )
    
    def _add_tool(
        self,
        name: str,
        description: str,
        parameters: Dict[str, str],
        handler: Callable
    ):
        """Add a tool to the registry."""
        # Convert to Anthropic tool schema
        properties = {}
        for param_name, param_desc in parameters.items():
            properties[param_name] = {
                "type": "string",
                "description": param_desc
            }
        
        self.tools_schema.append({
            "name": name,
            "description": description,
            "input_schema": {
                "type": "object",
                "properties": properties,
                "required": [k for k in parameters.keys() if "required" in parameters[k].lower()]
            }
        })
        
        self.tool_handlers[name] = handler
    
    def chat(self, user_message: str) -> str:
        """
        Process a user message and return a response.
        
        Args:
            user_message: The user's input
        
        Returns:
            Agent's response
        """
        # Handle confirmation response
        if self.pending_action:
            if user_message.lower().strip() in ["yes", "y", "confirm"]:
                result = self._execute_pending_action()
                self.pending_action = None
                return result
            else:
                self.pending_action = None
                return "Action cancelled."
        
        # Add user message to history
        self.messages.append({
            "role": "user",
            "content": user_message
        })
        
        # Call LLM with tools
        response = self._call_llm()
        
        return response
    
    def _call_llm(self) -> str:
        """Call the LLM and process tool calls."""
        response = self.client.messages.create(
            model=self.model,
            max_tokens=4096,
            system=SYSTEM_PROMPT.format(cluster_name=self.cluster_name),
            tools=self.tools_schema,
            messages=self.messages
        )
        
        # Process the response
        result_parts = []
        tool_results = []
        
        for content in response.content:
            if content.type == "text":
                result_parts.append(content.text)
            
            elif content.type == "tool_use":
                tool_name = content.name
                tool_args = content.input
                tool_id = content.id
                
                # Check if this is a write operation needing confirmation
                if self.require_confirmation and tool_name in self.write_operations:
                    self.pending_action = {
                        "tool_name": tool_name,
                        "tool_args": tool_args,
                        "tool_id": tool_id
                    }
                    
                    confirmation_msg = self._format_confirmation(tool_name, tool_args)
                    result_parts.append(confirmation_msg)
                    
                    # Don't continue tool execution
                    break
                
                # Execute the tool
                tool_result = self._execute_tool(tool_name, tool_args)
                
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_id,
                    "content": json.dumps(tool_result, default=str)
                })
        
        # If we have tool results, continue the conversation
        if tool_results and not self.pending_action:
            # Add assistant's message with tool use
            self.messages.append({
                "role": "assistant",
                "content": response.content
            })
            
            # Add tool results
            self.messages.append({
                "role": "user",
                "content": tool_results
            })
            
            # Continue the conversation
            return self._call_llm()
        
        # Add final response to history
        if result_parts:
            final_response = "\n".join(result_parts)
            self.messages.append({
                "role": "assistant",
                "content": final_response
            })
            return final_response
        
        return "I apologize, but I couldn't generate a response. Please try again."
    
    def _execute_tool(self, tool_name: str, tool_args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a tool and return results."""
        handler = self.tool_handlers.get(tool_name)
        if not handler:
            return {"success": False, "error": f"Unknown tool: {tool_name}"}
        
        try:
            # Convert string arguments to appropriate types
            processed_args = self._process_tool_args(tool_args)
            result = handler(**processed_args)
            return result
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def _process_tool_args(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Process and convert tool arguments."""
        processed = {}
        for key, value in args.items():
            if isinstance(value, str):
                # Try to parse as int
                if value.isdigit():
                    processed[key] = int(value)
                # Try to parse as bool
                elif value.lower() in ["true", "false"]:
                    processed[key] = value.lower() == "true"
                else:
                    processed[key] = value
            else:
                processed[key] = value
        return processed
    
    def _format_confirmation(self, tool_name: str, tool_args: Dict[str, Any]) -> str:
        """Format a confirmation message for a write operation."""
        action_descriptions = {
            "scale_deployment": f"Scale deployment '{tool_args.get('deployment_name')}' to {tool_args.get('replicas')} replicas",
            "restart_deployment": f"Rolling restart deployment '{tool_args.get('deployment_name')}'",
            "rollback_deployment": f"Rollback deployment '{tool_args.get('deployment_name')}' to previous version"
        }
        
        description = action_descriptions.get(tool_name, tool_name)
        namespace = tool_args.get("namespace", "default")
        
        return f"""
⚠️ **Action Confirmation Required**

**Action**: {description}
**Namespace**: {namespace}
**Details**: {json.dumps(tool_args, indent=2)}

This will modify your cluster. Reply 'yes' to confirm or 'no' to cancel.
"""
    
    def _execute_pending_action(self) -> str:
        """Execute a pending action that was confirmed."""
        if not self.pending_action:
            return "No pending action."
        
        tool_name = self.pending_action["tool_name"]
        tool_args = self.pending_action["tool_args"]
        
        result = self._execute_tool(tool_name, tool_args)
        
        if result.get("success"):
            return f"✅ Action completed successfully.\n\n{json.dumps(result, indent=2, default=str)}"
        else:
            return f"❌ Action failed.\n\n{result.get('error', 'Unknown error')}"
    
    def reset(self):
        """Reset the conversation history."""
        self.messages = []
        self.pending_action = None


# Convenience function for quick usage
def create_agent(
    cluster_name: str,
    region: Optional[str] = None,
    **kwargs
) -> AgenticAIOpsAgent:
    """Create and return an AgenticAIOpsAgent instance."""
    return AgenticAIOpsAgent(
        cluster_name=cluster_name,
        region=region,
        **kwargs
    )
