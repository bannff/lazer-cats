#!/bin/bash
# Script to start MCP servers when VS Code launches

# Change to the MCP directory
cd "$(dirname "$0")"

# Start all MCP servers
python3 mcp_manager.py start

echo "All MCP servers started successfully!"
exit 0