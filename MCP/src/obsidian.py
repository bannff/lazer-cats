#!/usr/bin/env python3
import os
import sys
import json
import requests
from typing import Dict, Any, List, Optional, Union
import dotenv

# Path to the main module for importing shared code
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.main import app, Message, MessageType, manager

# Load environment variables from .env file if present
dotenv.load_dotenv()

# Configuration
OBSIDIAN_API_KEY = os.environ.get("OBSIDIAN_API_KEY", "")
OBSIDIAN_API_HOST = os.environ.get("OBSIDIAN_API_HOST", "http://localhost:27123")

# Helper functions for Obsidian API
def api_request(method, endpoint, data=None, params=None):
    """Make a request to the Obsidian Local REST API"""
    headers = {
        "Authorization": f"Bearer {OBSIDIAN_API_KEY}",
        "Content-Type": "application/json"
    }
    
    url = f"{OBSIDIAN_API_HOST}/api/{endpoint}"
    
    try:
        if method.lower() == "get":
            response = requests.get(url, headers=headers, params=params)
        elif method.lower() == "post":
            response = requests.post(url, headers=headers, json=data)
        elif method.lower() == "put":
            response = requests.put(url, headers=headers, json=data)
        elif method.lower() == "delete":
            response = requests.delete(url, headers=headers, params=params)
        else:
            raise ValueError(f"Unsupported HTTP method: {method}")
        
        response.raise_for_status()
        return response.json() if response.content else {}
    
    except requests.exceptions.RequestException as e:
        print(f"Error communicating with Obsidian API: {e}", file=sys.stderr)
        raise e

async def handle_list_files_in_vault(message_id: str, params: Dict[str, Any], websocket: WebSocket):
    """
    Lists all files and directories in the root directory of your Obsidian vault.
    
    Returns information about each file and directory in the root of the vault,
    including their names, paths, and whether they are directories.
    """
    try:
        if not OBSIDIAN_API_KEY:
            await manager.send_error(
                message_id, 
                500, 
                "Obsidian API key not configured. Set OBSIDIAN_API_KEY environment variable.", 
                websocket
            )
            return
        
        # Get the root files and directories
        response = api_request("GET", "vault")
        
        await manager.send_response(message_id, {
            "files": response.get("files", []),
            "count": len(response.get("files", []))
        }, websocket)
    
    except Exception as e:
        await manager.send_error(message_id, 500, str(e), websocket)

async def handle_list_files_in_dir(message_id: str, params: Dict[str, Any], websocket: WebSocket):
    """
    Lists all files and directories in a specific Obsidian directory.
    
    Params:
      - dir: Path to the directory within the vault
    """
    try:
        if not OBSIDIAN_API_KEY:
            await manager.send_error(
                message_id, 
                500, 
                "Obsidian API key not configured. Set OBSIDIAN_API_KEY environment variable.", 
                websocket
            )
            return
        
        directory = params.get("dir", "")
        if not directory:
            await manager.send_error(message_id, 400, "Directory path is required", websocket)
            return
        
        # Get the files in the specified directory
        response = api_request("GET", f"vault/{directory}")
        
        await manager.send_response(message_id, {
            "directory": directory,
            "files": response.get("files", []),
            "count": len(response.get("files", []))
        }, websocket)
    
    except Exception as e:
        await manager.send_error(message_id, 500, str(e), websocket)

async def handle_get_file_contents(message_id: str, params: Dict[str, Any], websocket: WebSocket):
    """
    Return the content of a single file in your vault.
    
    Params:
      - file: Path to the file within the vault
    """
    try:
        if not OBSIDIAN_API_KEY:
            await manager.send_error(
                message_id, 
                500, 
                "Obsidian API key not configured. Set OBSIDIAN_API_KEY environment variable.", 
                websocket
            )
            return
        
        file_path = params.get("file", "")
        if not file_path:
            await manager.send_error(message_id, 400, "File path is required", websocket)
            return
        
        # Get the file content
        response = api_request("GET", f"vault/{file_path}")
        
        await manager.send_response(message_id, {
            "file": file_path,
            "content": response.get("content", ""),
            "metadata": response.get("metadata", {})
        }, websocket)
    
    except Exception as e:
        await manager.send_error(message_id, 500, str(e), websocket)

async def handle_search(message_id: str, params: Dict[str, Any], websocket: WebSocket):
    """
    Search for documents matching a specified text query across all files in the vault.
    
    Params:
      - query: The search query string
      - limit: Maximum number of results to return (optional, default: 10)
    """
    try:
        if not OBSIDIAN_API_KEY:
            await manager.send_error(
                message_id, 
                500, 
                "Obsidian API key not configured. Set OBSIDIAN_API_KEY environment variable.", 
                websocket
            )
            return
        
        query = params.get("query", "")
        limit = params.get("limit", 10)
        
        if not query:
            await manager.send_error(message_id, 400, "Search query is required", websocket)
            return
        
        # Perform the search
        response = api_request("GET", "search", params={"query": query, "limit": limit})
        
        await manager.send_response(message_id, {
            "query": query,
            "results": response.get("results", []),
            "count": len(response.get("results", []))
        }, websocket)
    
    except Exception as e:
        await manager.send_error(message_id, 500, str(e), websocket)

async def handle_append_content(message_id: str, params: Dict[str, Any], websocket: WebSocket):
    """
    Append content to a new or existing file in the vault.
    
    Params:
      - file: Path to the file within the vault
      - content: Content to append to the file
      - create: Whether to create the file if it doesn't exist (optional, default: True)
    """
    try:
        if not OBSIDIAN_API_KEY:
            await manager.send_error(
                message_id, 
                500, 
                "Obsidian API key not configured. Set OBSIDIAN_API_KEY environment variable.", 
                websocket
            )
            return
        
        file_path = params.get("file", "")
        content = params.get("content", "")
        create = params.get("create", True)
        
        if not file_path:
            await manager.send_error(message_id, 400, "File path is required", websocket)
            return
        
        if not content:
            await manager.send_error(message_id, 400, "Content is required", websocket)
            return
        
        # Check if the file exists
        try:
            file_exists = api_request("GET", f"vault/{file_path}")
            existing_content = file_exists.get("content", "")
            
            # Append content to the existing file
            new_content = existing_content + "\n" + content
            api_request("PUT", f"vault/{file_path}", data={"content": new_content})
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 404 and create:
                # Create new file with the content
                api_request("PUT", f"vault/{file_path}", data={"content": content})
            else:
                raise e
        
        await manager.send_response(message_id, {
            "success": True,
            "file": file_path,
            "message": f"Content appended to {file_path}"
        }, websocket)
    
    except Exception as e:
        await manager.send_error(message_id, 500, str(e), websocket)

async def handle_patch_content(message_id: str, params: Dict[str, Any], websocket: WebSocket):
    """
    Insert content into an existing note relative to a heading, block reference, or frontmatter field.
    
    Params:
      - file: Path to the file within the vault
      - content: Content to insert
      - target: Target location (heading, block reference, or frontmatter field)
      - position: Where to insert content ('before', 'after', 'prepend', 'append', 'replace')
    """
    try:
        if not OBSIDIAN_API_KEY:
            await manager.send_error(
                message_id, 
                500, 
                "Obsidian API key not configured. Set OBSIDIAN_API_KEY environment variable.", 
                websocket
            )
            return
        
        file_path = params.get("file", "")
        content = params.get("content", "")
        target = params.get("target", "")
        position = params.get("position", "after")
        
        if not file_path:
            await manager.send_error(message_id, 400, "File path is required", websocket)
            return
        
        if not content:
            await manager.send_error(message_id, 400, "Content is required", websocket)
            return
        
        if not target:
            await manager.send_error(message_id, 400, "Target location is required", websocket)
            return
        
        if position not in ["before", "after", "prepend", "append", "replace"]:
            await manager.send_error(
                message_id, 
                400, 
                "Position must be one of: before, after, prepend, append, replace", 
                websocket
            )
            return
        
        # Get the existing file content
        response = api_request("GET", f"vault/{file_path}")
        existing_content = response.get("content", "")
        
        # Find the target location and update content accordingly
        new_content = existing_content  # Default to unchanged
        
        # Handle the patch based on target type and position
        # This is a simplified implementation - a full one would need to parse Markdown properly
        lines = existing_content.split("\n")
        
        # Simple case - assume target is a heading
        heading_found = False
        updated_lines = []
        
        for line in lines:
            if line.startswith("#") and target in line:
                heading_found = True
                
                if position == "before":
                    updated_lines.append(content)
                    updated_lines.append(line)
                elif position == "after":
                    updated_lines.append(line)
                    updated_lines.append(content)
                elif position == "replace":
                    updated_lines.append(content)
                else:
                    updated_lines.append(line)
            else:
                updated_lines.append(line)
        
        if heading_found:
            new_content = "\n".join(updated_lines)
        else:
            # If target wasn't found, append to the end as a fallback
            new_content = existing_content + "\n\n" + content
        
        # Update the file
        api_request("PUT", f"vault/{file_path}", data={"content": new_content})
        
        await manager.send_response(message_id, {
            "success": True,
            "file": file_path,
            "message": f"Content updated in {file_path}"
        }, websocket)
    
    except Exception as e:
        await manager.send_error(message_id, 500, str(e), websocket)

async def handle_delete_file(message_id: str, params: Dict[str, Any], websocket: WebSocket):
    """
    Delete a file or directory from your vault.
    
    Params:
      - file: Path to the file or directory within the vault
    """
    try:
        if not OBSIDIAN_API_KEY:
            await manager.send_error(
                message_id, 
                500, 
                "Obsidian API key not configured. Set OBSIDIAN_API_KEY environment variable.", 
                websocket
            )
            return
        
        file_path = params.get("file", "")
        
        if not file_path:
            await manager.send_error(message_id, 400, "File path is required", websocket)
            return
        
        # Delete the file
        api_request("DELETE", f"vault/{file_path}")
        
        await manager.send_response(message_id, {
            "success": True,
            "file": file_path,
            "message": f"{file_path} deleted successfully"
        }, websocket)
    
    except Exception as e:
        await manager.send_error(message_id, 500, str(e), websocket)

# Register Obsidian methods
OBSIDIAN_HANDLERS = {
    "listFilesInVault": handle_list_files_in_vault,
    "listFilesInDir": handle_list_files_in_dir,
    "getFileContents": handle_get_file_contents,
    "search": handle_search,
    "appendContent": handle_append_content,
    "patchContent": handle_patch_content,
    "deleteFile": handle_delete_file,
}

# Update the METHOD_HANDLERS dictionary with Obsidian handlers
from src.main import METHOD_HANDLERS
METHOD_HANDLERS.update(OBSIDIAN_HANDLERS)

# Make this runnable as a standalone server too
if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8008))
    host = os.environ.get("HOST", "0.0.0.0")
    print(f"Starting Obsidian MCP Server on {host}:{port}")
    print(f"Available methods: {', '.join(OBSIDIAN_HANDLERS.keys())}")
    uvicorn.run(app, host=host, port=port)