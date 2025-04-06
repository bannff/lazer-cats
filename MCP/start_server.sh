#!/bin/bash

# Install dependencies if not already installed
python3 -m pip install -r requirements.txt

# Run the MCP server
python3 src/main.py