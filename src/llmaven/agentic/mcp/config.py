# MCP-specific configuration (reuses AgenticConfig)
#
# The MCP server shares the same AGENTIC_* environment variables as the
# rest of the agentic stack. No separate config class is needed.
# Import AgenticConfig directly from llmaven.agentic.settings wherever
# MCP server configuration is required.
#
# Example:
# from llmaven.agentic.settings import config
# config.qdrant_url # AGENTIC_QDRANT_URL
# config.collection_name # AGENTIC_COLLECTION_NAME
# config.enable_rerank # AGENTIC_ENABLE_RERANK

from llmaven.agentic.settings import AgenticConfig, config

__all__ = ["AgenticConfig", "config"]