# Model Context Protocol (MCP) Server Collection

This repository contains a collection of Model Context Protocol (MCP) servers that enable AI assistants to interact with various tools and services. These servers allow AI models to access and control different aspects of your development environment.

## What is MCP?

The Model Context Protocol (MCP) is a standardized interface that allows AI models to interact with external tools and services. It provides a way for AI assistants to:

1. Access information from your local files, applications, and services
2. Perform actions on your behalf in a controlled and secure manner
3. Extend AI capabilities beyond just text generation

## Included Servers

This collection includes the following MCP servers:

1. **core_mcp** (port 8000) - Core file system operations and command execution
2. **art_generation** (port 8001) - AI image generation capabilities
3. **document_management** (port 8002) - Document handling and processing
4. **web_development** (port 8003) - Web project creation and management
5. **aws_services** (port 8004) - AWS integration and cloud operations
6. **github_integration** (port 8005) - GitHub repository interaction
7. **web_browser** (port 8006) - Headless browser control for web navigation
8. **terminal_repl** (port 8007) - Terminal and REPL environment access
9. **obsidian** (port 8008) - Obsidian note-taking app integration

## Setup Instructions

### Prerequisites

- Python 3.10 or higher
- pip (Python package manager)
- Required Python packages (installed via `install_dependencies.sh`)

### Installation

1. Clone this repository:
   ```
   git clone https://github.com/yourusername/mcp.git
   cd mcp
   ```

2. Install dependencies:
   ```
   ./install_dependencies.sh
   ```

3. Configure your MCP servers in `mcp_config.json` if needed

4. Start the MCP servers:
   ```
   python mcp_manager.py start
   ```

### Server-Specific Setup

#### Web Browser Server
Requires Playwright:
```bash
python -m playwright install
```

#### Obsidian Server
Requires the Obsidian Local REST API plugin and an API key. Add your key to the MCP configuration.

## Usage

- Start all servers: `python mcp_manager.py start`
- Stop all servers: `python mcp_manager.py stop`
- Restart all servers: `python mcp_manager.py restart`
- Check status: `python mcp_manager.py status`

## Integration with AI Tools

These MCP servers can be used with various AI tools that support the Model Context Protocol, including:

- Claude Desktop
- GitHub Copilot
- Other MCP-compatible AI assistants

## Directory Structure

```
MCP/
│── install_dependencies.sh    # Script to install required dependencies
│── mcp_config.json            # Configuration for all MCP servers
│── mcp_manager.py             # Script to manage MCP servers
│── requirements.txt           # Python package requirements
│── start_server.sh            # Script to start individual servers
│── vscode_startup.sh          # Script to start servers when VS Code launches
│
├── logs/                      # Log files for each server
│
└── src/                       # Source code for all MCP servers
    ├── main.py                # Core MCP functionality
    ├── art_generation.py      # AI image generation server
    ├── aws_services.py        # AWS services integration
    ├── document_management.py # Document handling server
    ├── github_integration.py  # GitHub integration server
    ├── terminal_repl.py       # Terminal and REPL access server
    ├── web_browser.py         # Web browser automation server
    ├── web_development.py     # Web development tools server
    ├── obsidian.py            # Obsidian notes integration
    └── clojure_extension.py   # Clojure language support
```

## Security Considerations

- These servers provide significant access to your system and should be used with caution
- MCP servers don't currently implement authentication - they're designed for personal use
- Be mindful of which AI tools you grant access to these servers

## License

MIT License - See LICENSE file for details