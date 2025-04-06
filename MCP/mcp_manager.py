#!/usr/bin/env python3
import os
import sys
import subprocess
import signal
import time
import json
import atexit
from pathlib import Path

# Configuration
MCP_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PID_FILE = os.path.join(MCP_BASE_DIR, ".mcp_servers.pid")
LOG_DIR = os.path.join(MCP_BASE_DIR, "logs")
CONFIG_FILE = os.path.join(MCP_BASE_DIR, "mcp_config.json")

# Create logs directory if it doesn't exist
os.makedirs(LOG_DIR, exist_ok=True)

# Default configuration
DEFAULT_CONFIG = {
    "servers": [
        {
            "name": "core_mcp",
            "script": os.path.join(MCP_BASE_DIR, "src", "main.py"),
            "port": 8000,
            "enabled": True,
            "env": {}
        }
    ]
}

def load_config():
    """Load the MCP server configuration"""
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r') as f:
                return json.load(f)
        except json.JSONDecodeError:
            print(f"Error parsing {CONFIG_FILE}, using default configuration")
            return DEFAULT_CONFIG
    else:
        # Create default config if it doesn't exist
        with open(CONFIG_FILE, 'w') as f:
            json.dump(DEFAULT_CONFIG, f, indent=4)
        return DEFAULT_CONFIG

def save_server_pids(pid_dict):
    """Save the server PIDs to a file"""
    with open(PID_FILE, 'w') as f:
        json.dump(pid_dict, f)

def load_server_pids():
    """Load the server PIDs from a file"""
    if os.path.exists(PID_FILE):
        try:
            with open(PID_FILE, 'r') as f:
                return json.load(f)
        except json.JSONDecodeError:
            return {}
    return {}

def is_process_running(pid):
    """Check if a process with the given PID is running"""
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False

def start_servers():
    """Start all enabled MCP servers"""
    config = load_config()
    pid_dict = {}
    
    print("Starting MCP servers...")
    
    for server in config["servers"]:
        if server.get("enabled", True):
            name = server["name"]
            script = server["script"]
            port = server.get("port", 8000)
            
            # Set environment variables
            env = os.environ.copy()
            env["PORT"] = str(port)
            for key, value in server.get("env", {}).items():
                env[key] = value
            
            log_file = os.path.join(LOG_DIR, f"{name}.log")
            with open(log_file, 'w') as log:
                process = subprocess.Popen(
                    [sys.executable, script],
                    stdout=log,
                    stderr=log,
                    cwd=MCP_BASE_DIR,
                    env=env
                )
                pid_dict[name] = process.pid
                print(f"Started {name} on port {port} (PID: {process.pid})")
    
    save_server_pids(pid_dict)
    return pid_dict

def stop_servers():
    """Stop all running MCP servers"""
    pid_dict = load_server_pids()
    
    if not pid_dict:
        print("No MCP servers found to stop")
        return
    
    print("Stopping MCP servers...")
    
    for name, pid in pid_dict.items():
        try:
            if is_process_running(pid):
                os.kill(pid, signal.SIGTERM)
                print(f"Stopped {name} (PID: {pid})")
            else:
                print(f"{name} (PID: {pid}) is not running")
        except Exception as e:
            print(f"Error stopping {name}: {e}")
    
    # Remove the PID file
    if os.path.exists(PID_FILE):
        os.remove(PID_FILE)

def register_cleanup():
    """Register function to clean up servers on exit"""
    atexit.register(stop_servers)

def check_servers():
    """Check if servers are running, start them if not"""
    pid_dict = load_server_pids()
    
    if not pid_dict:
        # No PIDs found, start servers
        return start_servers()
    
    # Check each server
    servers_to_start = []
    for name, pid in pid_dict.items():
        if not is_process_running(pid):
            print(f"{name} (PID: {pid}) is not running")
            servers_to_start.append(name)
    
    if servers_to_start:
        # Some servers need to be restarted
        stop_servers()  # Clean up any remaining processes
        return start_servers()
    
    print("All MCP servers are running")
    return pid_dict

def daemon_mode():
    """Run in daemon mode - start servers and keep running to monitor them"""
    pid_dict = start_servers()
    print(f"MCP servers started. Running in daemon mode. Press Ctrl+C to exit.")
    try:
        while True:
            # Check every 30 seconds if servers are still running
            time.sleep(30)
            for name, pid in list(pid_dict.items()):
                if not is_process_running(pid):
                    print(f"Server {name} (PID: {pid}) has stopped. Restarting...")
                    # Restart the specific server
                    config = load_config()
                    for server in config["servers"]:
                        if server.get("name") == name and server.get("enabled", True):
                            script = server["script"]
                            port = server.get("port", 8000)
                            
                            # Set environment variables
                            env = os.environ.copy()
                            env["PORT"] = str(port)
                            for key, value in server.get("env", {}).items():
                                env[key] = value
                            
                            log_file = os.path.join(LOG_DIR, f"{name}.log")
                            with open(log_file, 'a') as log:
                                log.write(f"\n--- Server restarted at {time.ctime()} ---\n")
                                process = subprocess.Popen(
                                    [sys.executable, script],
                                    stdout=log,
                                    stderr=log,
                                    cwd=MCP_BASE_DIR,
                                    env=env
                                )
                                pid_dict[name] = process.pid
                                print(f"Restarted {name} on port {port} (PID: {process.pid})")
                            
                            save_server_pids(pid_dict)
                            break
    except KeyboardInterrupt:
        print("Stopping MCP servers due to keyboard interrupt...")
        stop_servers()
        print("All MCP servers stopped.")

if __name__ == "__main__":
    command = sys.argv[1] if len(sys.argv) > 1 else "start"
    
    if command == "start":
        # Don't register cleanup handler for normal "start" command anymore
        # We'll just start the servers and exit, letting them run in the background
        start_servers()
        print("MCP servers started. Use 'python mcp_manager.py stop' to stop them.")
    elif command == "daemon":
        # New command to run in daemon mode (monitoring and keeping servers alive)
        register_cleanup()  # Only register cleanup in daemon mode
        daemon_mode()
    elif command == "stop":
        stop_servers()
    elif command == "restart":
        stop_servers()
        time.sleep(1)
        start_servers()
    elif command == "status":
        pid_dict = load_server_pids()
        if not pid_dict:
            print("No MCP servers are registered")
        else:
            for name, pid in pid_dict.items():
                status = "running" if is_process_running(pid) else "stopped"
                print(f"{name} (PID: {pid}): {status}")
    else:
        print(f"Unknown command: {command}")
        print("Usage: python mcp_manager.py [start|stop|restart|status|daemon]")