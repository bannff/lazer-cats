import asyncio
import json
import os
import sys
from typing import Dict, Any, List, Optional

# Path to the main module for importing shared code
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.main import app, Message, MessageType, manager, METHOD_HANDLERS
from fastapi import FastAPI, WebSocket, WebSocketDisconnect

# Import long-running command handlers
from src.main import handle_start_long_running_command, handle_kill_process

async def handle_clojure_deps(message_id: str, params: Dict[str, Any], websocket: WebSocket):
    """Handle analysis of Clojure project dependencies"""
    project_path = params.get("projectPath", os.getcwd())
    try:
        deps_files = []
        
        # Look for project.clj (Leiningen)
        lein_path = os.path.join(project_path, "project.clj")
        if os.path.exists(lein_path):
            deps_files.append({"type": "leiningen", "path": lein_path})
            
            # Try to extract dependencies
            lein_deps_process = await asyncio.create_subprocess_shell(
                f"cd {project_path} && lein deps :tree",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await lein_deps_process.communicate()
            
            if stdout:
                deps_files[0]["dependencies"] = stdout.decode().strip()
        
        # Look for deps.edn (Clojure CLI)
        deps_edn_path = os.path.join(project_path, "deps.edn")
        if os.path.exists(deps_edn_path):
            deps_files.append({"type": "deps.edn", "path": deps_edn_path})
            
            # Try to extract dependencies
            clj_deps_process = await asyncio.create_subprocess_shell(
                f"cd {project_path} && clojure -Stree",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await clj_deps_process.communicate()
            
            if stdout:
                deps_files[-1]["dependencies"] = stdout.decode().strip()
        
        # Look for shadow-cljs.edn (ClojureScript)
        shadow_path = os.path.join(project_path, "shadow-cljs.edn")
        if os.path.exists(shadow_path):
            deps_files.append({"type": "shadow-cljs", "path": shadow_path})
        
        await manager.send_response(message_id, {"depsFiles": deps_files}, websocket)
    except Exception as e:
        await manager.send_error(message_id, 500, str(e), websocket)

async def handle_clojure_repl(message_id: str, params: Dict[str, Any], websocket: WebSocket):
    """Start or interact with a Clojure REPL"""
    action = params.get("action", "start")
    process_id = params.get("processId", "")
    code = params.get("code", "")
    project_path = params.get("projectPath", os.getcwd())
    
    try:
        if action == "start":
            # Check if we should start a Leiningen REPL or Clojure CLI REPL
            has_lein = os.path.exists(os.path.join(project_path, "project.clj"))
            has_deps_edn = os.path.exists(os.path.join(project_path, "deps.edn"))
            
            command = ""
            if has_lein:
                command = "lein repl"
            elif has_deps_edn:
                command = "clojure -M:repl"
            else:
                command = "clojure"
            
            # Use the long running command handler to start the REPL
            repl_params = {
                "command": command,
                "cwd": project_path,
                "processId": f"clj_repl_{message_id}"
            }
            
            # Delegate to the long running command handler
            await handle_start_long_running_command(message_id, repl_params, websocket)
        
        elif action == "eval" and process_id and code:
            if process_id not in manager.running_processes:
                await manager.send_error(message_id, 404, f"REPL process {process_id} not found", websocket)
                return
            
            # Send code to the REPL process stdin
            process = manager.running_processes[process_id]
            code_with_newline = code + "\n"
            process.stdin.write(code_with_newline.encode())
            await process.stdin.drain()
            
            # Wait a moment for the REPL to process
            await asyncio.sleep(0.5)
            
            # Get the output from the process buffer
            output_lines = manager.process_output_buffers[process_id].copy()
            manager.process_output_buffers[process_id] = []
            
            await manager.send_response(message_id, {
                "result": "\n".join(output_lines),
                "processId": process_id
            }, websocket)
        
        elif action == "stop" and process_id:
            # Delegate to the kill process handler
            await handle_kill_process(message_id, {"processId": process_id}, websocket)
        
        else:
            await manager.send_error(message_id, 400, "Invalid REPL action or missing parameters", websocket)
    
    except Exception as e:
        await manager.send_error(message_id, 500, str(e), websocket)

async def handle_clojure_test(message_id: str, params: Dict[str, Any], websocket: WebSocket):
    """Run Clojure tests"""
    project_path = params.get("projectPath", os.getcwd())
    test_path = params.get("testPath", "")
    
    try:
        command = ""
        
        # Determine the right command based on project structure
        if os.path.exists(os.path.join(project_path, "project.clj")):
            if test_path:
                command = f"cd {project_path} && lein test {test_path}"
            else:
                command = f"cd {project_path} && lein test"
        elif os.path.exists(os.path.join(project_path, "deps.edn")):
            if test_path:
                command = f"cd {project_path} && clojure -M:test {test_path}"
            else:
                command = f"cd {project_path} && clojure -M:test"
        else:
            await manager.send_error(message_id, 400, "No Clojure project found", websocket)
            return
        
        # Execute the test command
        process = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()
        
        test_output = stdout.decode() if stdout else ""
        test_error = stderr.decode() if stderr else ""
        
        # Parse test results
        tests_run = 0
        tests_failed = 0
        
        for line in test_output.split("\n"):
            if "Ran " in line and " tests" in line:
                try:
                    tests_run = int(line.split("Ran ")[1].split(" tests")[0])
                except:
                    pass
            
            if "FAIL in" in line:
                tests_failed += 1
        
        result = {
            "output": test_output,
            "error": test_error,
            "exitCode": process.returncode,
            "testsRun": tests_run,
            "testsFailed": tests_failed,
            "success": process.returncode == 0
        }
        
        await manager.send_response(message_id, result, websocket)
    except Exception as e:
        await manager.send_error(message_id, 500, str(e), websocket)

# Add Clojure-specific handlers to the METHOD_HANDLERS dictionary
METHOD_HANDLERS.update({
    "clojureDeps": handle_clojure_deps,
    "clojureRepl": handle_clojure_repl,
    "clojureTest": handle_clojure_test,
})