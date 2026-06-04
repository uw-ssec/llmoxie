import os

import pytest
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client


@pytest.mark.integration
@pytest.mark.asyncio
async def test_mcp_server_responds_to_tool_list():
    async with stdio_client(
        StdioServerParameters(
            command="python", 
            args=["-m", "llmaven.agentic.mcp"])
    ) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()

            assert len(tools.tools) == 1
            assert tools.tools[0].name == "search_knowledge_base"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_search_returns_valid_results(qdrant_url):
    """Test that search_knowledge_base returns valid results via MCP.

    Uses a testcontainer Qdrant instance. The collection will be empty so
    the test verifies the response structure is valid rather than specific content.
    """
    env = {**os.environ, "AGENTIC_QDRANT_URL": qdrant_url}

    async with stdio_client(
        StdioServerParameters(
            command="python", 
            args=["-m", "llmaven.agentic.mcp"], 
            env=env)
    ) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            result = await session.call_tool(
                "search_knowledge_base",
                arguments={"query": "test query", "limit": 5},
            )

            # Result should be a valid response (empty results for empty collection)
            assert result is not None
            assert not result.isError