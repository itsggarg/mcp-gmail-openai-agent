import asyncio
from agent import build_agent
from agents import Runner

# main task with the use case
TASK = "Send 'hi' to '202111032@diu.iiitvadodara.ac.in"

async def main():
    agent, mcp_server = build_agent()
    try:
        await mcp_server.connect()
        result = await Runner.run(agent, TASK)
        print("✅ Final Output:\n", result.final_output)
    finally:
        await mcp_server.cleanup()

if __name__ == "__main__":
    asyncio.run(main())