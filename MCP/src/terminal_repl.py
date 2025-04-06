#!/usr/bin/env python3
import asyncio
import os
import sys
import re
import fcntl
import termios
import json
import time
from typing import Dict, Any, List, Optional, Union

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

# Path to the main module for importing shared code
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.main import app, Message, MessageType, manager

# Terminal session management globals
_active_terminals = {}
_current_terminal_id = None

async def _execute_terminal_command(command, terminal_id=None):
    """Execute a command in a terminal and capture its output"""
    if not terminal_id and not _current_terminal_id:
        raise ValueError("No active terminal session")
    
    terminal_id = terminal_id or _current_terminal_id
    if terminal_id not in _active_terminals:
        raise ValueError(f"Terminal session {terminal_id} not found")
    
    # Get the terminal session
    terminal = _active_terminals[terminal_id]
    
    # Write the command to the terminal
    terminal['process'].stdin.write(f"{command}\n".encode())
    await terminal['process'].stdin.drain()
    
    # Wait a moment for command to process
    await asyncio.sleep(0.2)
    
    # Collect output
    output = []
    while True:
        try:
            line = await asyncio.wait_for(terminal['process'].stdout.readline(), 0.1)
            if not line:
                break
            output.append(line.decode().rstrip())
        except asyncio.TimeoutError:
            break
    
    # Update stored output
    terminal['output'].extend(output)
    return output

async def handle_create_terminal_session(message_id: str, params: Dict[str, Any], websocket: WebSocket):
    """
    Create a new terminal session.
    
    Params:
      - shell: Optional shell to use (defaults to $SHELL or /bin/bash)
      - cwd: Working directory for the shell (defaults to current directory)
    """
    global _active_terminals, _current_terminal_id
    
    shell = params.get("shell", os.environ.get("SHELL", "/bin/bash"))
    cwd = params.get("cwd", os.getcwd())
    name = params.get("name", f"Terminal-{len(_active_terminals) + 1}")
    
    try:
        # Create a unique terminal ID
        import uuid
        terminal_id = str(uuid.uuid4())
        
        # Start the shell process
        process = await asyncio.create_subprocess_exec(
            shell,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=cwd
        )
        
        # Store the terminal session
        _active_terminals[terminal_id] = {
            'process': process,
            'shell': shell,
            'cwd': cwd,
            'name': name,
            'output': [],
            'created_at': time.time()
        }
        
        # Set as current terminal if it's the first one
        if not _current_terminal_id:
            _current_terminal_id = terminal_id
        
        # Wait a moment for the shell to initialize and capture any initial output
        await asyncio.sleep(0.5)
        initial_output = []
        while True:
            try:
                line = await asyncio.wait_for(process.stdout.readline(), 0.1)
                if not line:
                    break
                initial_output.append(line.decode().rstrip())
            except asyncio.TimeoutError:
                break
        
        _active_terminals[terminal_id]['output'].extend(initial_output)
        
        await manager.send_response(message_id, {
            "terminalId": terminal_id,
            "name": name,
            "shell": shell,
            "initialOutput": initial_output
        }, websocket)
    
    except Exception as e:
        await manager.send_error(message_id, 500, str(e), websocket)

async def handle_list_terminal_sessions(message_id: str, params: Dict[str, Any], websocket: WebSocket):
    """
    List all active terminal sessions.
    """
    global _active_terminals, _current_terminal_id
    
    try:
        sessions = []
        for terminal_id, terminal in _active_terminals.items():
            sessions.append({
                "terminalId": terminal_id,
                "name": terminal['name'],
                "shell": terminal['shell'],
                "cwd": terminal['cwd'],
                "isCurrent": terminal_id == _current_terminal_id,
                "createdAt": terminal['created_at'],
                "outputLineCount": len(terminal['output'])
            })
        
        await manager.send_response(message_id, {"sessions": sessions}, websocket)
    
    except Exception as e:
        await manager.send_error(message_id, 500, str(e), websocket)

async def handle_switch_terminal_session(message_id: str, params: Dict[str, Any], websocket: WebSocket):
    """
    Switch to a different terminal session.
    
    Params:
      - terminalId: ID of the terminal session to switch to
    """
    global _active_terminals, _current_terminal_id
    
    terminal_id = params.get("terminalId", "")
    if not terminal_id:
        await manager.send_error(message_id, 400, "Terminal ID is required", websocket)
        return
    
    if terminal_id not in _active_terminals:
        await manager.send_error(message_id, 404, f"Terminal session with ID {terminal_id} not found", websocket)
        return
    
    try:
        _current_terminal_id = terminal_id
        terminal = _active_terminals[terminal_id]
        
        await manager.send_response(message_id, {
            "terminalId": terminal_id,
            "name": terminal['name'],
            "shell": terminal['shell'],
            "cwd": terminal['cwd']
        }, websocket)
    
    except Exception as e:
        await manager.send_error(message_id, 500, str(e), websocket)

async def handle_close_terminal_session(message_id: str, params: Dict[str, Any], websocket: WebSocket):
    """
    Close a terminal session.
    
    Params:
      - terminalId: ID of the terminal session to close (defaults to current session)
    """
    global _active_terminals, _current_terminal_id
    
    terminal_id = params.get("terminalId", _current_terminal_id)
    if not terminal_id:
        await manager.send_error(message_id, 400, "No active terminal session", websocket)
        return
    
    if terminal_id not in _active_terminals:
        await manager.send_error(message_id, 404, f"Terminal session with ID {terminal_id} not found", websocket)
        return
    
    try:
        # Get the terminal session
        terminal = _active_terminals[terminal_id]
        
        # Kill the process
        if terminal['process']:
            terminal['process'].kill()
            await terminal['process'].wait()
        
        # Remove from active terminals
        del _active_terminals[terminal_id]
        
        # Reset current terminal if this was the current one
        if terminal_id == _current_terminal_id:
            if _active_terminals:
                _current_terminal_id = next(iter(_active_terminals))
            else:
                _current_terminal_id = None
        
        await manager.send_response(message_id, {
            "success": True,
            "message": f"Terminal session {terminal_id} closed",
            "currentTerminalId": _current_terminal_id
        }, websocket)
    
    except Exception as e:
        await manager.send_error(message_id, 500, str(e), websocket)

async def handle_write_to_terminal(message_id: str, params: Dict[str, Any], websocket: WebSocket):
    """
    Write text to the active terminal session.
    
    Params:
      - text: Text to write to the terminal
      - terminalId: Optional ID of the terminal session to write to (defaults to current session)
    """
    global _active_terminals, _current_terminal_id
    
    text = params.get("text", "")
    terminal_id = params.get("terminalId", _current_terminal_id)
    
    if not text:
        await manager.send_error(message_id, 400, "Text to write is required", websocket)
        return
    
    if not terminal_id:
        await manager.send_error(message_id, 400, "No active terminal session", websocket)
        return
    
    if terminal_id not in _active_terminals:
        await manager.send_error(message_id, 404, f"Terminal session with ID {terminal_id} not found", websocket)
        return
    
    try:
        # Get the terminal session
        terminal = _active_terminals[terminal_id]
        
        # Write the text to the terminal
        terminal['process'].stdin.write(f"{text}\n".encode())
        await terminal['process'].stdin.drain()
        
        # Wait a moment for command to process
        await asyncio.sleep(0.2)
        
        # Collect output
        output = []
        while True:
            try:
                line = await asyncio.wait_for(terminal['process'].stdout.readline(), 0.1)
                if not line:
                    break
                output.append(line.decode().rstrip())
            except asyncio.TimeoutError:
                break
        
        # Update stored output
        terminal['output'].extend(output)
        
        await manager.send_response(message_id, {
            "output": output,
            "lineCount": len(output)
        }, websocket)
    
    except Exception as e:
        await manager.send_error(message_id, 500, str(e), websocket)

async def handle_read_terminal_output(message_id: str, params: Dict[str, Any], websocket: WebSocket):
    """
    Read output from the active terminal session.
    
    Params:
      - lineCount: Number of lines to read (defaults to 10)
      - fromEnd: Whether to read from the end of the output (defaults to True)
      - terminalId: Optional ID of the terminal session to read from (defaults to current session)
    """
    global _active_terminals, _current_terminal_id
    
    line_count = params.get("lineCount", 10)
    from_end = params.get("fromEnd", True)
    terminal_id = params.get("terminalId", _current_terminal_id)
    
    if not terminal_id:
        await manager.send_error(message_id, 400, "No active terminal session", websocket)
        return
    
    if terminal_id not in _active_terminals:
        await manager.send_error(message_id, 404, f"Terminal session with ID {terminal_id} not found", websocket)
        return
    
    try:
        # Get the terminal session
        terminal = _active_terminals[terminal_id]
        
        # Get the requested lines
        if from_end:
            output = terminal['output'][-line_count:] if terminal['output'] else []
        else:
            output = terminal['output'][:line_count] if terminal['output'] else []
        
        await manager.send_response(message_id, {
            "output": output,
            "lineCount": len(output),
            "totalLines": len(terminal['output'])
        }, websocket)
    
    except Exception as e:
        await manager.send_error(message_id, 500, str(e), websocket)

async def handle_send_control_character(message_id: str, params: Dict[str, Any], websocket: WebSocket):
    """
    Send a control character to the active terminal session.
    
    Params:
      - character: Control character to send (e.g., 'c' for Ctrl+C)
      - terminalId: Optional ID of the terminal session (defaults to current session)
    """
    global _active_terminals, _current_terminal_id
    
    character = params.get("character", "")
    terminal_id = params.get("terminalId", _current_terminal_id)
    
    if not character:
        await manager.send_error(message_id, 400, "Control character is required", websocket)
        return
    
    if not terminal_id:
        await manager.send_error(message_id, 400, "No active terminal session", websocket)
        return
    
    if terminal_id not in _active_terminals:
        await manager.send_error(message_id, 404, f"Terminal session with ID {terminal_id} not found", websocket)
        return
    
    try:
        # Get the terminal session
        terminal = _active_terminals[terminal_id]
        
        # Map control character to the appropriate ASCII value
        ctrl_chars = {
            'c': 3,  # Ctrl+C (SIGINT)
            'd': 4,  # Ctrl+D (EOF)
            'z': 26, # Ctrl+Z (SIGTSTP)
            'l': 12, # Ctrl+L (clear screen)
            'a': 1,  # Ctrl+A (beginning of line)
            'e': 5,  # Ctrl+E (end of line)
            'u': 21, # Ctrl+U (clear line)
            'r': 18, # Ctrl+R (reverse search)
        }
        
        char_code = ctrl_chars.get(character.lower())
        if not char_code:
            await manager.send_error(message_id, 400, f"Unsupported control character: {character}", websocket)
            return
        
        # Send the control character
        terminal['process'].stdin.write(bytes([char_code]))
        await terminal['process'].stdin.drain()
        
        # Wait a moment for processing
        await asyncio.sleep(0.2)
        
        # Collect output
        output = []
        while True:
            try:
                line = await asyncio.wait_for(terminal['process'].stdout.readline(), 0.1)
                if not line:
                    break
                output.append(line.decode().rstrip())
            except asyncio.TimeoutError:
                break
        
        # Update stored output
        terminal['output'].extend(output)
        
        await manager.send_response(message_id, {
            "success": True,
            "character": character,
            "output": output,
            "lineCount": len(output)
        }, websocket)
    
    except Exception as e:
        await manager.send_error(message_id, 500, str(e), websocket)

async def handle_clear_terminal_output(message_id: str, params: Dict[str, Any], websocket: WebSocket):
    """
    Clear the stored output for a terminal session.
    
    Params:
      - terminalId: Optional ID of the terminal session (defaults to current session)
    """
    global _active_terminals, _current_terminal_id
    
    terminal_id = params.get("terminalId", _current_terminal_id)
    
    if not terminal_id:
        await manager.send_error(message_id, 400, "No active terminal session", websocket)
        return
    
    if terminal_id not in _active_terminals:
        await manager.send_error(message_id, 404, f"Terminal session with ID {terminal_id} not found", websocket)
        return
    
    try:
        # Get the terminal session
        terminal = _active_terminals[terminal_id]
        
        # Clear the output
        terminal['output'] = []
        
        await manager.send_response(message_id, {
            "success": True,
            "message": f"Terminal output cleared for session {terminal_id}"
        }, websocket)
    
    except Exception as e:
        await manager.send_error(message_id, 500, str(e), websocket)

async def handle_execute_repl_command(message_id: str, params: Dict[str, Any], websocket: WebSocket):
    """
    Execute a command in a REPL environment.
    
    Params:
      - command: Command to execute
      - repl: Type of REPL ('python', 'clojure', etc.)
      - terminalId: Optional ID of the terminal session (defaults to current session)
    """
    global _active_terminals, _current_terminal_id
    
    command = params.get("command", "")
    repl_type = params.get("repl", "")
    terminal_id = params.get("terminalId", _current_terminal_id)
    
    if not command:
        await manager.send_error(message_id, 400, "Command is required", websocket)
        return
    
    if not repl_type:
        await manager.send_error(message_id, 400, "REPL type is required", websocket)
        return
    
    if not terminal_id:
        await manager.send_error(message_id, 400, "No active terminal session", websocket)
        return
    
    if terminal_id not in _active_terminals:
        await manager.send_error(message_id, 404, f"Terminal session with ID {terminal_id} not found", websocket)
        return
    
    try:
        # Get the terminal session
        terminal = _active_terminals[terminal_id]
        
        # Check if REPL is already started
        repl_started = False
        
        # Start the appropriate REPL if not already started
        if not repl_started:
            if repl_type.lower() == 'python':
                await _execute_terminal_command("python3", terminal_id)
            elif repl_type.lower() in ['clojure', 'clj']:
                await _execute_terminal_command("clj", terminal_id)
            elif repl_type.lower() == 'clojurescript' or repl_type.lower() == 'cljs':
                await _execute_terminal_command("clj -m cljs.main", terminal_id)
            else:
                await manager.send_error(message_id, 400, f"Unsupported REPL type: {repl_type}", websocket)
                return
        
        # Wait a moment for the REPL to start
        await asyncio.sleep(0.5)
        
        # Execute the command in the REPL
        terminal['process'].stdin.write(f"{command}\n".encode())
        await terminal['process'].stdin.drain()
        
        # Wait for the result (REPL outputs can take time)
        await asyncio.sleep(0.5)
        
        # Collect output
        output = []
        while True:
            try:
                line = await asyncio.wait_for(terminal['process'].stdout.readline(), 0.1)
                if not line:
                    break
                output.append(line.decode().rstrip())
            except asyncio.TimeoutError:
                break
        
        # Update stored output
        terminal['output'].extend(output)
        
        await manager.send_response(message_id, {
            "repl": repl_type,
            "command": command,
            "output": output,
            "lineCount": len(output)
        }, websocket)
    
    except Exception as e:
        await manager.send_error(message_id, 500, str(e), websocket)

# Register terminal methods
TERMINAL_HANDLERS = {
    "createTerminalSession": handle_create_terminal_session,
    "listTerminalSessions": handle_list_terminal_sessions,
    "switchTerminalSession": handle_switch_terminal_session,
    "closeTerminalSession": handle_close_terminal_session,
    "writeToTerminal": handle_write_to_terminal,
    "readTerminalOutput": handle_read_terminal_output,
    "sendControlCharacter": handle_send_control_character,
    "clearTerminalOutput": handle_clear_terminal_output,
    "executeReplCommand": handle_execute_repl_command,
}

# Update the METHOD_HANDLERS dictionary with terminal handlers
from src.main import METHOD_HANDLERS
METHOD_HANDLERS.update(TERMINAL_HANDLERS)

# Register cleanup for terminal sessions
import atexit

def cleanup_terminals():
    """Clean up terminal resources on process exit"""
    for terminal_id, terminal in _active_terminals.items():
        if terminal['process']:
            terminal['process'].kill()

atexit.register(cleanup_terminals)

# Make this runnable as a standalone server too
if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8007))
    host = os.environ.get("HOST", "0.0.0.0")
    print(f"Starting Terminal REPL MCP Server on {host}:{port}")
    print(f"Available methods: {', '.join(TERMINAL_HANDLERS.keys())}")
    uvicorn.run(app, host=host, port=port)