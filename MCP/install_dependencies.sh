#!/bin/bash
# MCP Server Dependencies Installation Script

echo "Installing MCP server dependencies..."

# Check if Python is installed
if ! command -v python3 &> /dev/null; then
    echo "Python 3 is required but not installed. Please install Python 3 and try again."
    exit 1
fi

# Install base Python packages
echo "Installing base Python packages..."
pip install -r requirements.txt

# Install Playwright (required for web_browser server)
echo "Installing Playwright for web browser automation..."
pip install playwright
python3 -m playwright install

# Install dotenv (required for Obsidian server)
echo "Installing python-dotenv for configuration management..."
pip install python-dotenv

# Install FastAPI and Uvicorn (required for all servers)
echo "Installing FastAPI and Uvicorn for API servers..."
pip install fastapi uvicorn

echo "All dependencies installed successfully!"
echo ""
echo "Note: For the Obsidian server to work, you need to:"
echo "1. Install the 'Local REST API' plugin in Obsidian"
echo "2. Add your API key to mcp_config.json or create a .env file with OBSIDIAN_API_KEY"

exit 0