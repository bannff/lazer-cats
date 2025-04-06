import asyncio
import json
import os
import sys
import importlib.util
import pkgutil
import inspect
from typing import Dict, Any, List, Optional, Union

async def handle_python_inspect(message_id: str, params: Dict[str, Any], websocket: WebSocket):
    """Inspect Python modules, classes, and functions"""
    module_name = params.get("module", "")
    class_name = params.get("class", "")
    function_name = params.get("function", "")
    
    try:
        result = {}
        
        if module_name:
            # Try to import the module
            try:
                module = importlib.import_module(module_name)
                
                # Get basic module info
                module_info = {
                    "name": module.__name__,
                    "file": getattr(module, "__file__", "Unknown"),
                    "doc": inspect.getdoc(module) or "",
                }
                
                # Get all module attributes
                attrs = []
                for name, obj in inspect.getmembers(module):
                    if not name.startswith("_"):  # Skip private/special attributes
                        attr_type = type(obj).__name__
                        attrs.append({"name": name, "type": attr_type})
                
                module_info["attributes"] = attrs
                
                # Get all classes in the module
                classes = []
                for name, obj in inspect.getmembers(module, inspect.isclass):
                    if obj.__module__ == module.__name__:  # Only include classes defined in this module
                        classes.append({"name": name})
                
                module_info["classes"] = classes
                
                # Get all functions in the module
                functions = []
                for name, obj in inspect.getmembers(module, inspect.isfunction):
                    if obj.__module__ == module.__name__:  # Only include functions defined in this module
                        functions.append({"name": name})
                
                module_info["functions"] = functions
                
                result["module"] = module_info
                
                # If a class was specified, get info about it
                if class_name and hasattr(module, class_name):
                    cls = getattr(module, class_name)
                    if inspect.isclass(cls):
                        class_info = {
                            "name": cls.__name__,
                            "doc": inspect.getdoc(cls) or "",
                            "methods": [],
                            "attributes": []
                        }
                        
                        # Get class methods
                        for name, method in inspect.getmembers(cls, inspect.isfunction):
                            if not name.startswith("_") or name == "__init__":
                                try:
                                    signature = str(inspect.signature(method))
                                    method_doc = inspect.getdoc(method) or ""
                                    class_info["methods"].append({
                                        "name": name,
                                        "signature": signature,
                                        "doc": method_doc
                                    })
                                except:
                                    class_info["methods"].append({"name": name})
                        
                        # Get class attributes
                        for name, value in cls.__dict__.items():
                            if not name.startswith("_") and not inspect.isfunction(value):
                                class_info["attributes"].append({
                                    "name": name,
                                    "type": type(value).__name__
                                })
                        
                        result["class"] = class_info
                
                # If a function was specified, get info about it
                if function_name and hasattr(module, function_name):
                    func = getattr(module, function_name)
                    if inspect.isfunction(func):
                        func_info = {
                            "name": func.__name__,
                            "doc": inspect.getdoc(func) or "",
                            "signature": str(inspect.signature(func))
                        }
                        
                        result["function"] = func_info
            
            except ImportError:
                result["error"] = f"Could not import module '{module_name}'"
            except Exception as e:
                result["error"] = str(e)
        
        await manager.send_response(message_id, result, websocket)
    except Exception as e:
        await manager.send_error(message_id, 500, str(e), websocket)

async def handle_python_run_code(message_id: str, params: Dict[str, Any], websocket: WebSocket):
    """Run Python code and return the result"""
    code = params.get("code", "")
    timeout = params.get("timeout", 5)  # Default 5 second timeout
    
    if not code:
        await manager.send_error(message_id, 400, "No code provided", websocket)
        return
    
    # Create a temporary file to hold the code
    import tempfile
    import uuid
    
    temp_dir = tempfile.gettempdir()
    file_id = str(uuid.uuid4())
    file_path = os.path.join(temp_dir, f"temp_code_{file_id}.py")
    
    try:
        with open(file_path, "w") as f:
            f.write(code)
        
        # Run the code in a separate process with timeout
        process = await asyncio.create_subprocess_shell(
            f"python3 {file_path}",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout)
            
            result = {
                "output": stdout.decode() if stdout else "",
                "error": stderr.decode() if stderr else "",
                "exitCode": process.returncode
            }
            
            await manager.send_response(message_id, result, websocket)
        except asyncio.TimeoutError:
            process.kill()
            await manager.send_error(message_id, 408, f"Code execution timed out after {timeout} seconds", websocket)
    except Exception as e:
        await manager.send_error(message_id, 500, str(e), websocket)
    finally:
        # Clean up the temporary file
        try:
            os.remove(file_path)
        except:
            pass

async def handle_python_pip(message_id: str, params: Dict[str, Any], websocket: WebSocket):
    """Handle pip package management"""
    action = params.get("action", "")
    package = params.get("package", "")
    
    if not action:
        await manager.send_error(message_id, 400, "No action specified", websocket)
        return
    
    try:
        if action == "install" and package:
            # Install a package using pip
            process = await asyncio.create_subprocess_shell(
                f"python3 -m pip install {package}",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await process.communicate()
            
            result = {
                "output": stdout.decode() if stdout else "",
                "error": stderr.decode() if stderr else "",
                "success": process.returncode == 0
            }
            
            await manager.send_response(message_id, result, websocket)
        
        elif action == "uninstall" and package:
            # Uninstall a package using pip
            process = await asyncio.create_subprocess_shell(
                f"python3 -m pip uninstall -y {package}",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await process.communicate()
            
            result = {
                "output": stdout.decode() if stdout else "",
                "error": stderr.decode() if stderr else "",
                "success": process.returncode == 0
            }
            
            await manager.send_response(message_id, result, websocket)
        
        elif action == "list":
            # List installed packages
            process = await asyncio.create_subprocess_shell(
                "python3 -m pip list",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await process.communicate()
            
            output = stdout.decode() if stdout else ""
            
            # Parse the output to get a list of packages
            packages = []
            for line in output.split("\n")[2:]:  # Skip the header lines
                if line.strip():
                    parts = line.split()
                    if len(parts) >= 2:
                        packages.append({"name": parts[0], "version": parts[1]})
            
            result = {
                "packages": packages,
                "success": process.returncode == 0
            }
            
            await manager.send_response(message_id, result, websocket)
        
        elif action == "search" and package:
            # Search for packages on PyPI
            process = await asyncio.create_subprocess_shell(
                f"python3 -m pip search {package}",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await process.communicate()
            
            # Note: pip search might be disabled in newer pip versions
            if "ERROR: XMLRPC request failed" in (stderr.decode() if stderr else ""):
                # If direct pip search is disabled, use the PyPI API
                from aiohttp import ClientSession
                
                async with ClientSession() as session:
                    async with session.get(f"https://pypi.org/pypi/{package}/json") as response:
                        if response.status == 200:
                            data = await response.json()
                            result = {
                                "package": {
                                    "name": data["info"]["name"],
                                    "version": data["info"]["version"],
                                    "summary": data["info"]["summary"],
                                    "description": data["info"]["description"],
                                    "author": data["info"]["author"],
                                    "author_email": data["info"]["author_email"],
                                    "home_page": data["info"]["home_page"],
                                }
                            }
                        else:
                            result = {
                                "error": f"Package {package} not found",
                                "success": False
                            }
            else:
                result = {
                    "output": stdout.decode() if stdout else "",
                    "error": stderr.decode() if stderr else "",
                    "success": process.returncode == 0
                }
            
            await manager.send_response(message_id, result, websocket)
        
        else:
            await manager.send_error(message_id, 400, f"Invalid action '{action}' or missing package name", websocket)
    
    except Exception as e:
        await manager.send_error(message_id, 500, str(e), websocket)

async def handle_python_venv(message_id: str, params: Dict[str, Any], websocket: WebSocket):
    """Handle Python virtual environment management"""
    action = params.get("action", "")
    venv_path = params.get("path", "")
    
    if not action:
        await manager.send_error(message_id, 400, "No action specified", websocket)
        return
    
    try:
        if action == "create" and venv_path:
            # Create a virtual environment
            process = await asyncio.create_subprocess_shell(
                f"python3 -m venv {venv_path}",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await process.communicate()
            
            result = {
                "output": stdout.decode() if stdout else "",
                "error": stderr.decode() if stderr else "",
                "success": process.returncode == 0,
                "path": venv_path
            }
            
            await manager.send_response(message_id, result, websocket)
        
        elif action == "activate" and venv_path:
            # Return the activation command (user would have to execute this separately)
            # Since we can't directly affect the environment of the parent process
            
            # Build activation commands for different shells
            activate_path = os.path.join(venv_path, "bin", "activate")
            
            if os.path.exists(activate_path):
                result = {
                    "success": True,
                    "commands": {
                        "bash/zsh": f"source {activate_path}",
                        "fish": f"source {os.path.join(venv_path, 'bin', 'activate.fish')}",
                        "cmd": f"{os.path.join(venv_path, 'Scripts', 'activate.bat')}",
                        "powershell": f"{os.path.join(venv_path, 'Scripts', 'Activate.ps1')}"
                    },
                    "note": "You need to run the appropriate activation command in your terminal to activate the virtual environment"
                }
                
                await manager.send_response(message_id, result, websocket)
            else:
                await manager.send_error(message_id, 404, f"Virtual environment not found at {venv_path}", websocket)
        
        else:
            await manager.send_error(message_id, 400, f"Invalid action '{action}' or missing virtual environment path", websocket)
    
    except Exception as e:
        await manager.send_error(message_id, 500, str(e), websocket)

# Add Python-specific handlers to the METHOD_HANDLERS dictionary
METHOD_HANDLERS.update({
    "pythonInspect": handle_python_inspect,
    "pythonRunCode": handle_python_run_code,
    "pythonPip": handle_python_pip,
    "pythonVenv": handle_python_venv,
})