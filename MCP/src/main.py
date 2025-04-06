import asyncio
import json
import os
import sys
import subprocess
import shutil
from enum import Enum
from typing import Any, Dict, List, Optional, Union

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

app = FastAPI()

class MessageType(str, Enum):
    REQUEST = "request"
    RESPONSE = "response"
    ERROR = "error"

class Message(BaseModel):
    type: MessageType
    id: str
    method: Optional[str] = None
    params: Optional[Dict[str, Any]] = None
    result: Optional[Any] = None
    error: Optional[Dict[str, Any]] = None

class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []
        self.running_processes: Dict[str, asyncio.subprocess.Process] = {}
        self.process_output_buffers: Dict[str, List[str]] = {}

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def send_response(self, message_id: str, result: Any, websocket: WebSocket):
        response = Message(
            type=MessageType.RESPONSE,
            id=message_id,
            result=result
        )
        await websocket.send_text(response.model_dump_json())

    async def send_error(self, message_id: str, error_code: int, error_message: str, websocket: WebSocket):
        error_response = Message(
            type=MessageType.ERROR,
            id=message_id,
            error={"code": error_code, "message": error_message}
        )
        await websocket.send_text(error_response.model_dump_json())

manager = ConnectionManager()

# Core functionality handlers
async def handle_execute_command(message_id: str, params: Dict[str, Any], websocket: WebSocket):
    command = params.get("command", "")
    cwd = params.get("cwd", os.getcwd())
    env_vars = params.get("env", {})
    
    # Merge environment variables
    env = os.environ.copy()
    env.update(env_vars)
    
    try:
        # WARNING: Running arbitrary commands is a security risk.
        # In a production environment, you should validate and sanitize commands.
        process = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
            env=env
        )
        stdout, stderr = await process.communicate()
        
        output = stdout.decode() if stdout else ""
        error = stderr.decode() if stderr else ""
        
        result = {
            "output": output,
            "error": error,
            "exitCode": process.returncode
        }
        await manager.send_response(message_id, result, websocket)
    except Exception as e:
        await manager.send_error(message_id, 500, str(e), websocket)

async def handle_start_long_running_command(message_id: str, params: Dict[str, Any], websocket: WebSocket):
    command = params.get("command", "")
    cwd = params.get("cwd", os.getcwd())
    env_vars = params.get("env", {})
    process_id = params.get("processId", message_id)
    
    # Merge environment variables
    env = os.environ.copy()
    env.update(env_vars)
    
    try:
        # Start the process
        process = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            stdin=asyncio.subprocess.PIPE,  # Added stdin for interactive processes
            cwd=cwd,
            env=env
        )
        
        # Store the process
        manager.running_processes[process_id] = process
        manager.process_output_buffers[process_id] = []
        
        # Start background task to collect output
        asyncio.create_task(collect_process_output(process_id, process, websocket))
        
        await manager.send_response(message_id, {"processId": process_id, "status": "started"}, websocket)
    except Exception as e:
        await manager.send_error(message_id, 500, str(e), websocket)

async def collect_process_output(process_id: str, process: asyncio.subprocess.Process, websocket: WebSocket):
    """Collect output from a running process in the background."""
    while True:
        if process.stdout.at_eof() and process.stderr.at_eof():
            if process.returncode is not None:
                exit_code = process.returncode
                # Process has completed
                manager.process_output_buffers[process_id].append(f"Process exited with code {exit_code}")
                del manager.running_processes[process_id]
                break
        
        try:
            stdout_line = await asyncio.wait_for(process.stdout.readline(), 0.1)
            if stdout_line:
                line = stdout_line.decode().rstrip()
                manager.process_output_buffers[process_id].append(line)
        except asyncio.TimeoutError:
            pass
        
        try:
            stderr_line = await asyncio.wait_for(process.stderr.readline(), 0.1)
            if stderr_line:
                line = stderr_line.decode().rstrip()
                manager.process_output_buffers[process_id].append(f"ERROR: {line}")
        except asyncio.TimeoutError:
            pass
        
        # Short delay to prevent CPU hogging
        await asyncio.sleep(0.1)

async def handle_get_process_output(message_id: str, params: Dict[str, Any], websocket: WebSocket):
    process_id = params.get("processId", "")
    
    if process_id not in manager.process_output_buffers:
        await manager.send_error(message_id, 404, f"Process {process_id} not found", websocket)
        return
    
    # Get output lines and clear buffer
    output_lines = manager.process_output_buffers[process_id].copy()
    manager.process_output_buffers[process_id] = []
    
    # Check if process is still running
    is_running = process_id in manager.running_processes
    
    result = {
        "output": output_lines,
        "isRunning": is_running
    }
    
    await manager.send_response(message_id, result, websocket)

async def handle_kill_process(message_id: str, params: Dict[str, Any], websocket: WebSocket):
    process_id = params.get("processId", "")
    
    if process_id not in manager.running_processes:
        await manager.send_error(message_id, 404, f"Process {process_id} not found", websocket)
        return
    
    try:
        process = manager.running_processes[process_id]
        process.kill()
        # Wait for the process to be fully killed
        await process.wait()
        
        # Clean up
        if process_id in manager.running_processes:
            del manager.running_processes[process_id]
        
        await manager.send_response(message_id, {"status": "killed"}, websocket)
    except Exception as e:
        await manager.send_error(message_id, 500, str(e), websocket)

async def handle_read_file(message_id: str, params: Dict[str, Any], websocket: WebSocket):
    file_path = params.get("path", "")
    encoding = params.get("encoding", "utf-8")
    try:
        with open(file_path, "r", encoding=encoding) as file:
            content = file.read()
        await manager.send_response(message_id, {"content": content}, websocket)
    except Exception as e:
        await manager.send_error(message_id, 500, str(e), websocket)

async def handle_write_file(message_id: str, params: Dict[str, Any], websocket: WebSocket):
    file_path = params.get("path", "")
    content = params.get("content", "")
    encoding = params.get("encoding", "utf-8")
    try:
        # Ensure the directory exists
        os.makedirs(os.path.dirname(os.path.abspath(file_path)), exist_ok=True)
        
        with open(file_path, "w", encoding=encoding) as file:
            file.write(content)
        await manager.send_response(message_id, {"success": True}, websocket)
    except Exception as e:
        await manager.send_error(message_id, 500, str(e), websocket)

async def handle_list_directory(message_id: str, params: Dict[str, Any], websocket: WebSocket):
    directory_path = params.get("path", ".")
    try:
        items = []
        for item in os.listdir(directory_path):
            full_path = os.path.join(directory_path, item)
            stat_info = os.stat(full_path)
            items.append({
                "name": item,
                "path": full_path,
                "isDirectory": os.path.isdir(full_path),
                "size": stat_info.st_size,
                "modifiedTime": stat_info.st_mtime
            })
        await manager.send_response(message_id, {"items": items}, websocket)
    except Exception as e:
        await manager.send_error(message_id, 500, str(e), websocket)

async def handle_create_directory(message_id: str, params: Dict[str, Any], websocket: WebSocket):
    directory_path = params.get("path", "")
    try:
        os.makedirs(directory_path, exist_ok=True)
        await manager.send_response(message_id, {"success": True}, websocket)
    except Exception as e:
        await manager.send_error(message_id, 500, str(e), websocket)

async def handle_delete_file(message_id: str, params: Dict[str, Any], websocket: WebSocket):
    path = params.get("path", "")
    try:
        if os.path.isdir(path):
            shutil.rmtree(path)
        else:
            os.remove(path)
        await manager.send_response(message_id, {"success": True}, websocket)
    except Exception as e:
        await manager.send_error(message_id, 500, str(e), websocket)

async def handle_rename_file(message_id: str, params: Dict[str, Any], websocket: WebSocket):
    old_path = params.get("oldPath", "")
    new_path = params.get("newPath", "")
    try:
        # Ensure the target directory exists
        os.makedirs(os.path.dirname(os.path.abspath(new_path)), exist_ok=True)
        
        shutil.move(old_path, new_path)
        await manager.send_response(message_id, {"success": True}, websocket)
    except Exception as e:
        await manager.send_error(message_id, 500, str(e), websocket)

async def handle_search_files(message_id: str, params: Dict[str, Any], websocket: WebSocket):
    directory_path = params.get("path", ".")
    pattern = params.get("pattern", "*")
    include_content = params.get("includeContent", False)
    max_depth = params.get("maxDepth", -1)
    
    try:
        results = []
        
        def search_directory(dir_path, current_depth=0):
            if max_depth >= 0 and current_depth > max_depth:
                return
            
            try:
                for item in os.listdir(dir_path):
                    full_path = os.path.join(dir_path, item)
                    
                    if os.path.isdir(full_path):
                        search_directory(full_path, current_depth + 1)
                    else:
                        import fnmatch
                        if fnmatch.fnmatch(item, pattern):
                            file_info = {
                                "path": full_path,
                                "name": item
                            }
                            
                            if include_content:
                                try:
                                    with open(full_path, "r", encoding="utf-8") as f:
                                        file_info["content"] = f.read()
                                except:
                                    file_info["content"] = "Error: Unable to read file content"
                            
                            results.append(file_info)
            except Exception as e:
                # Skip directories that can't be accessed
                pass
        
        search_directory(directory_path)
        await manager.send_response(message_id, {"files": results}, websocket)
    except Exception as e:
        await manager.send_error(message_id, 500, str(e), websocket)

async def handle_check_python_env(message_id: str, params: Dict[str, Any], websocket: WebSocket):
    try:
        python_info = {}
        
        # Get Python version
        python_version_process = await asyncio.create_subprocess_shell(
            "python3 --version",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await python_version_process.communicate()
        python_info["pythonVersion"] = stdout.decode().strip() if stdout else stderr.decode().strip()
        
        # Get pip packages
        pip_list_process = await asyncio.create_subprocess_shell(
            "python3 -m pip list",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await pip_list_process.communicate()
        pip_output = stdout.decode() if stdout else ""
        
        packages = []
        for line in pip_output.split("\n")[2:]:  # Skip the header lines
            if line.strip():
                parts = line.split()
                if len(parts) >= 2:
                    packages.append({"name": parts[0], "version": parts[1]})
        
        python_info["installedPackages"] = packages
        
        await manager.send_response(message_id, python_info, websocket)
    except Exception as e:
        await manager.send_error(message_id, 500, str(e), websocket)

async def handle_check_clojure_env(message_id: str, params: Dict[str, Any], websocket: WebSocket):
    try:
        clojure_info = {}
        
        # Check if Clojure/ClojureScript is installed
        clj_process = await asyncio.create_subprocess_shell(
            "which clojure clj lein && echo 'Clojure tools installed' || echo 'Clojure tools not found'",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await clj_process.communicate()
        clojure_info["clojureToolsStatus"] = stdout.decode().strip()
        
        # Check versions if installed
        if "not found" not in clojure_info["clojureToolsStatus"]:
            # Try to get Leiningen version
            lein_process = await asyncio.create_subprocess_shell(
                "lein --version 2>/dev/null || echo 'Leiningen not found'",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await lein_process.communicate()
            clojure_info["leiningenVersion"] = stdout.decode().strip()
            
            # Try to get Clojure CLI version
            clj_version_process = await asyncio.create_subprocess_shell(
                "clojure --version 2>/dev/null || echo 'Clojure CLI not found'",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await clj_version_process.communicate()
            clojure_info["clojureCliVersion"] = stdout.decode().strip()
        
        await manager.send_response(message_id, clojure_info, websocket)
    except Exception as e:
        await manager.send_error(message_id, 500, str(e), websocket)

# Initialize our METHOD_HANDLERS dictionary with core handlers
METHOD_HANDLERS = {
    "executeCommand": handle_execute_command,
    "startLongRunningCommand": handle_start_long_running_command,
    "getProcessOutput": handle_get_process_output,
    "killProcess": handle_kill_process,
    "readFile": handle_read_file,
    "writeFile": handle_write_file,
    "listDirectory": handle_list_directory,
    "createDirectory": handle_create_directory,
    "deleteFile": handle_delete_file,
    "renameFile": handle_rename_file,
    "searchFiles": handle_search_files,
    "checkPythonEnvironment": handle_check_python_env,
    "checkClojureEnvironment": handle_check_clojure_env,
}

# Import and register extensions
try:
    from src.python_extension import METHOD_HANDLERS as PYTHON_HANDLERS
    METHOD_HANDLERS.update(PYTHON_HANDLERS)
except ImportError:
    print("Python extension not found. Python-specific functions will not be available.")

try:
    from src.clojure_extension import METHOD_HANDLERS as CLOJURE_HANDLERS
    METHOD_HANDLERS.update(CLOJURE_HANDLERS)
except ImportError:
    print("Clojure extension not found. Clojure-specific functions will not be available.")

@app.websocket("/mcp")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            try:
                message_data = json.loads(data)
                message = Message(**message_data)
                
                if message.type == MessageType.REQUEST and message.method:
                    handler = METHOD_HANDLERS.get(message.method)
                    if handler:
                        await handler(message.id, message.params or {}, websocket)
                    else:
                        await manager.send_error(
                            message.id, 
                            404, 
                            f"Method '{message.method}' not found", 
                            websocket
                        )
                else:
                    # Ignore non-request messages
                    pass
            except json.JSONDecodeError:
                # Ignore invalid JSON
                pass
            except Exception as e:
                # Log the error but don't crash the websocket
                print(f"Error processing message: {str(e)}", file=sys.stderr)
    except WebSocketDisconnect:
        manager.disconnect(websocket)

@app.get("/")
async def root():
    return {
        "name": "Model Context Protocol Server",
        "version": "1.0.0",
        "status": "running",
        "endpoints": {
            "mcp": "/mcp (WebSocket)"
        },
        "supportedLanguages": ["python", "clojure", "general"]
    }

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    host = os.environ.get("HOST", "0.0.0.0")
    print(f"Starting MCP Server on {host}:{port}")
    print(f"Available methods: {', '.join(METHOD_HANDLERS.keys())}")
    uvicorn.run(app, host=host, port=port)