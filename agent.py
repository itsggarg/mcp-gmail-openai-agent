import os
import openai
from agents import Agent
from agents.mcp import MCPServerSse
from dotenv import load_dotenv

load_dotenv()
openai.api_key = os.getenv("OPENAI_API_KEY")
TOOL_URL = os.getenv("MCP_TOOL_URL")
# return openai agent connected to mcp tool
def build_agent():
    mcp_server = MCPServerSse({"url": TOOL_URL})
    agent = Agent(
        name="Gmail Agent",
        instructions="Handling mails and drafts.",
        mcp_servers=[mcp_server],
    )
    return agent, mcp_server