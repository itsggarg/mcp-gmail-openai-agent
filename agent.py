"""
Gmail Agent Builder Module

This module creates and configures an OpenAI agent with Gmail capabilities
through MCP (Model Context Protocol) server integration.
"""
import os
import openai
from agents import Agent
from agents.mcp import MCPServerSse
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure OpenAI API
openai.api_key = os.getenv("OPENAI_API_KEY")
TOOL_URL = os.getenv("MCP_TOOL_URL")


def build_agent():
    """
    Build and configure a Gmail agent with MCP server connection.
    
    Returns:
        tuple: (agent, mcp_server) - Configured Agent instance and MCPServerSse instance
    
    Raises:
        ValueError: If required environment variables are not set
    """
    if not openai.api_key:
        raise ValueError("OPENAI_API_KEY environment variable is required")
    
    if not TOOL_URL:
        raise ValueError("MCP_TOOL_URL environment variable is required")
    
    # Initialize MCP server connection
    mcp_server = MCPServerSse({"url": TOOL_URL})
    
    # Create agent with Gmail handling capabilities
    agent = Agent(
        name="Gmail Agent",
        instructions="Handling mails and drafts.",
        mcp_servers=[mcp_server],
    )
    
    return agent, mcp_server
