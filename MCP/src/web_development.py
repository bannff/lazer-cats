import asyncio
import json
import os
import sys
import re
import base64
import shutil
from typing import Dict, Any, List, Optional, Union

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

# Path to the main module for importing shared code
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.main import app, Message, MessageType, manager

async def handle_create_web_project(message_id: str, params: Dict[str, Any], websocket: WebSocket):
    """
    Create a new web project with a specified framework
    Params:
      - projectType: Type of project (react, vue, angular, next, express, etc.)
      - projectName: Name of the project
      - projectPath: Path where to create the project
      - options: Additional options for the project setup
    """
    project_type = params.get("projectType", "").lower()
    project_name = params.get("projectName", "web-app")
    project_path = params.get("projectPath", os.getcwd())
    options = params.get("options", {})
    
    if not project_type:
        await manager.send_error(message_id, 400, "Project type is required", websocket)
        return
    
    try:
        result = {"projectType": project_type, "projectName": project_name}
        create_command = ""
        
        # Handle different project types
        if project_type in ["react", "react-app", "create-react-app"]:
            create_command = f"npx create-react-app {project_name}"
            result["projectFramework"] = "React"
        
        elif project_type in ["vite", "vite-react"]:
            template = options.get("template", "react")
            create_command = f"npm create vite@latest {project_name} -- --template {template}"
            result["projectFramework"] = f"Vite with {template} template"
        
        elif project_type in ["next", "nextjs", "next.js"]:
            create_command = f"npx create-next-app {project_name}"
            result["projectFramework"] = "Next.js"
        
        elif project_type in ["vue", "vuejs", "vue.js"]:
            create_command = f"npm init vue@latest {project_name}"
            result["projectFramework"] = "Vue.js"
        
        elif project_type in ["angular", "ng"]:
            create_command = f"npx @angular/cli new {project_name}"
            result["projectFramework"] = "Angular"
        
        elif project_type in ["express", "node-express"]:
            # Create a base Express project
            os.makedirs(os.path.join(project_path, project_name), exist_ok=True)
            project_dir = os.path.join(project_path, project_name)
            
            # Initialize package.json
            npm_init_process = await asyncio.create_subprocess_shell(
                f"cd {project_dir} && npm init -y",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            await npm_init_process.communicate()
            
            # Install Express
            npm_install_process = await asyncio.create_subprocess_shell(
                f"cd {project_dir} && npm install express",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            await npm_install_process.communicate()
            
            # Create a basic Express app
            app_js = """
const express = require('express');
const app = express();
const port = process.env.PORT || 3000;

// Middleware
app.use(express.json());
app.use(express.urlencoded({ extended: true }));

// Routes
app.get('/', (req, res) => {
  res.send('Express API is running');
});

// Start server
app.listen(port, () => {
  console.log(`Server listening on port ${port}`);
});
            """
            
            with open(os.path.join(project_dir, 'app.js'), 'w') as f:
                f.write(app_js)
            
            result["projectFramework"] = "Express.js"
            result["projectPath"] = project_dir
            result["creationMethod"] = "manual"
        
        else:
            # Unknown project type
            await manager.send_error(
                message_id, 
                400, 
                f"Unknown project type: {project_type}. Supported types: react, vue, angular, next, express, vite", 
                websocket
            )
            return
        
        # Execute the create command if we have one
        if create_command:
            process = await asyncio.create_subprocess_shell(
                f"cd {project_path} && {create_command}",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await process.communicate()
            
            result["output"] = stdout.decode() if stdout else ""
            result["error"] = stderr.decode() if stderr else ""
            result["exitCode"] = process.returncode
            result["projectPath"] = os.path.join(project_path, project_name)
            result["creationMethod"] = "cli"
        
        await manager.send_response(message_id, result, websocket)
    
    except Exception as e:
        await manager.send_error(message_id, 500, str(e), websocket)

async def handle_run_npm_command(message_id: str, params: Dict[str, Any], websocket: WebSocket):
    """
    Run an npm/yarn/pnpm command
    Params:
      - command: The command to run (install, start, build, etc.)
      - packageManager: npm, yarn, or pnpm (defaults to npm)
      - packages: Optional list of packages to install
      - cwd: Working directory
      - isLongRunning: Whether this is a long-running command (like start)
    """
    command = params.get("command", "")
    package_manager = params.get("packageManager", "npm").lower()
    packages = params.get("packages", [])
    cwd = params.get("cwd", os.getcwd())
    is_long_running = params.get("isLongRunning", False)
    
    if not command:
        await manager.send_error(message_id, 400, "Command is required", websocket)
        return
    
    try:
        # Construct the full command
        full_command = f"{package_manager} {command}"
        
        # Add packages if provided
        if packages and isinstance(packages, list) and len(packages) > 0:
            package_list = " ".join(packages)
            full_command += f" {package_list}"
        
        # For long-running commands, use the long-running command handler
        if is_long_running:
            long_running_params = {
                "command": full_command,
                "cwd": cwd,
                "processId": f"npm_{command}_{message_id}"
            }
            await handle_start_long_running_command(message_id, long_running_params, websocket)
        else:
            # For normal commands, execute and wait for completion
            process = await asyncio.create_subprocess_shell(
                f"cd {cwd} && {full_command}",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await process.communicate()
            
            result = {
                "command": full_command,
                "output": stdout.decode() if stdout else "",
                "error": stderr.decode() if stderr else "",
                "exitCode": process.returncode
            }
            
            await manager.send_response(message_id, result, websocket)
    
    except Exception as e:
        await manager.send_error(message_id, 500, str(e), websocket)

async def handle_analyze_web_project(message_id: str, params: Dict[str, Any], websocket: WebSocket):
    """
    Analyze a web project to determine framework, dependencies, etc.
    Params:
      - projectPath: Path to the project
    """
    project_path = params.get("projectPath", os.getcwd())
    
    if not os.path.exists(project_path):
        await manager.send_error(message_id, 404, f"Project path not found: {project_path}", websocket)
        return
    
    try:
        result = {
            "projectPath": project_path,
            "files": {},
            "dependencies": {},
            "devDependencies": {},
            "scripts": {},
            "framework": "unknown"
        }
        
        # Check for package.json
        package_json_path = os.path.join(project_path, "package.json")
        if os.path.exists(package_json_path):
            with open(package_json_path, 'r') as f:
                package_data = json.load(f)
                
                result["name"] = package_data.get("name", "")
                result["version"] = package_data.get("version", "")
                result["dependencies"] = package_data.get("dependencies", {})
                result["devDependencies"] = package_data.get("devDependencies", {})
                result["scripts"] = package_data.get("scripts", {})
        
        # Detect framework
        frameworks = {
            "react": ["react", "react-dom"],
            "vue": ["vue"],
            "angular": ["@angular/core"],
            "next.js": ["next"],
            "express": ["express"],
            "svelte": ["svelte"],
            "ember": ["ember"]
        }
        
        all_deps = {**result.get("dependencies", {}), **result.get("devDependencies", {})}
        
        for framework, packages in frameworks.items():
            if any(pkg in all_deps for pkg in packages):
                result["framework"] = framework
                break
        
        # Count files by type
        file_counts = {}
        for root, dirs, files in os.walk(project_path):
            # Skip node_modules
            if "node_modules" in root:
                continue
                
            for file in files:
                ext = os.path.splitext(file)[1].lower()
                if ext:
                    file_counts[ext] = file_counts.get(ext, 0) + 1
        
        result["files"] = file_counts
        
        await manager.send_response(message_id, result, websocket)
    
    except Exception as e:
        await manager.send_error(message_id, 500, str(e), websocket)

async def handle_generate_component(message_id: str, params: Dict[str, Any], websocket: WebSocket):
    """
    Generate a UI component for a specific framework
    Params:
      - componentName: Name of the component
      - framework: Framework (react, vue, angular, svelte)
      - outputPath: Where to save the component
      - props: List of props for the component
      - description: Description of what the component should do
    """
    component_name = params.get("componentName", "")
    framework = params.get("framework", "react").lower()
    output_path = params.get("outputPath", "")
    props = params.get("props", [])
    description = params.get("description", "A simple component")
    
    if not component_name:
        await manager.send_error(message_id, 400, "Component name is required", websocket)
        return
    
    try:
        # Ensure output directory exists
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        
        component_code = ""
        
        if framework == "react":
            # Generate React component
            props_list = ", ".join(props) if props else ""
            props_declaration = "\n  // Props\n" + "\n".join([f"  const {prop} = props.{prop};" for prop in props]) if props else ""
            
            component_code = f"""import React from 'react';

/**
 * {component_name} - {description}
 */
function {component_name}(props) {{
{props_declaration}

  return (
    <div className="{component_name.lower()}">
      {{"{"}}/* Component content here */{"}"}}
      <h2>{component_name}</h2>
      <p>Your component content goes here</p>
    </div>
  );
}}

export default {component_name};
"""
            
            # Create a CSS file if output path is provided
            if output_path:
                css_path = os.path.join(os.path.dirname(output_path), f"{component_name}.css")
                with open(css_path, 'w') as f:
                    f.write(f"""/* Styles for {component_name} */
.{component_name.lower()} {{
  padding: 20px;
  border: 1px solid #eee;
  border-radius: 5px;
}}
""")
        
        elif framework == "vue":
            # Generate Vue component
            props_declaration = "\n    ".join([f"{prop}: {{type: String, required: false}}," for prop in props]) if props else ""
            
            component_code = f"""<template>
  <div class="{component_name.lower()}">
    <h2>{component_name}</h2>
    <p>Your component content goes here</p>
  </div>
</template>

<script>
export default {{
  name: '{component_name}',
  props: {{
    {props_declaration}
  }},
  data() {{
    return {{
      // Component data here
    }}
  }},
  methods: {{
    // Component methods here
  }}
}}
</script>

<style scoped>
.{component_name.lower()} {{
  padding: 20px;
  border: 1px solid #eee;
  border-radius: 5px;
}}
</style>
"""
        
        elif framework == "angular":
            # Generate Angular component
            kebab_case = re.sub(r'(?<!^)(?=[A-Z])', '-', component_name).lower()
            
            component_code = f"""import {{ Component, Input }} from '@angular/core';

@Component({{
  selector: 'app-{kebab_case}',
  templateUrl: './{kebab_case}.component.html',
  styleUrls: ['./{kebab_case}.component.css']
}})
export class {component_name}Component {{
  // Inputs
  {("@Input() " + ";\n  @Input() ".join(props) + ";") if props else "// No inputs defined"}

  constructor() {{ }}

  ngOnInit(): void {{
    // Initialization logic here
  }}
}}
"""
            
            # Create HTML and CSS files
            if output_path:
                html_path = os.path.join(os.path.dirname(output_path), f"{kebab_case}.component.html")
                with open(html_path, 'w') as f:
                    f.write(f"""<div class="{kebab_case}">
  <h2>{component_name}</h2>
  <p>Your component content goes here</p>
</div>
""")
                
                css_path = os.path.join(os.path.dirname(output_path), f"{kebab_case}.component.css")
                with open(css_path, 'w') as f:
                    f.write(f""".{kebab_case} {{
  padding: 20px;
  border: 1px solid #eee;
  border-radius: 5px;
}}
""")
        
        elif framework == "svelte":
            # Generate Svelte component
            props_export = "\n  ".join([f"export let {prop};" for prop in props]) if props else "// No props defined"
            
            component_code = f"""<script>
  // Props
  {props_export}
</script>

<div class="{component_name.lower()}">
  <h2>{component_name}</h2>
  <p>Your component content goes here</p>
</div>

<style>
  .{component_name.lower()} {{
    padding: 20px;
    border: 1px solid #eee;
    border-radius: 5px;
  }}
</style>
"""
        
        else:
            await manager.send_error(
                message_id, 
                400, 
                f"Unsupported framework: {framework}. Supported frameworks: react, vue, angular, svelte", 
                websocket
            )
            return
        
        # Write the component to file if output path is provided
        if output_path:
            with open(output_path, 'w') as f:
                f.write(component_code)
        
        await manager.send_response(message_id, {
            "componentName": component_name,
            "framework": framework,
            "outputPath": output_path if output_path else "Not saved to file",
            "code": component_code
        }, websocket)
    
    except Exception as e:
        await manager.send_error(message_id, 500, str(e), websocket)

async def handle_optimize_frontend(message_id: str, params: Dict[str, Any], websocket: WebSocket):
    """
    Analyze and optimize frontend assets
    Params:
      - filePath: Path to the file to optimize
      - type: Type of optimization (image, css, js)
    """
    file_path = params.get("filePath", "")
    optimization_type = params.get("type", "auto").lower()
    
    if not file_path or not os.path.exists(file_path):
        await manager.send_error(message_id, 404, f"File not found: {file_path}", websocket)
        return
    
    try:
        result = {
            "filePath": file_path,
            "type": optimization_type,
            "originalSize": os.path.getsize(file_path)
        }
        
        file_ext = os.path.splitext(file_path)[1].lower()
        
        # Auto-detect type if not specified
        if optimization_type == "auto":
            if file_ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp']:
                optimization_type = "image"
            elif file_ext == '.css':
                optimization_type = "css"
            elif file_ext == '.js':
                optimization_type = "js"
            else:
                await manager.send_error(message_id, 400, f"Couldn't determine optimization type for: {file_path}", websocket)
                return
        
        # Create backup of original file
        backup_path = file_path + ".backup"
        shutil.copy2(file_path, backup_path)
        
        if optimization_type == "image":
            try:
                from PIL import Image
                
                # Optimize image
                img = Image.open(file_path)
                
                # Create optimized version
                optimized_path = file_path.replace(file_ext, f".optimized{file_ext}")
                
                # Determine appropriate format and quality
                format_opts = {}
                if file_ext in ['.jpg', '.jpeg']:
                    format_opts = {'format': 'JPEG', 'quality': 85, 'optimize': True}
                elif file_ext == '.png':
                    format_opts = {'format': 'PNG', 'optimize': True}
                elif file_ext == '.webp':
                    format_opts = {'format': 'WEBP', 'quality': 85}
                else:
                    format_opts = {'optimize': True}
                
                img.save(optimized_path, **format_opts)
                
                result["optimizedSize"] = os.path.getsize(optimized_path)
                result["optimizedPath"] = optimized_path
                result["reductionPercent"] = round((1 - (result["optimizedSize"] / result["originalSize"])) * 100, 2)
                
                # Add image dimensions
                result["dimensions"] = {'width': img.width, 'height': img.height}
            
            except ImportError:
                result["error"] = "Image optimization requires the Pillow library"
                result["installCommand"] = "pip install Pillow"
        
        elif optimization_type == "css":
            # Simple CSS minification
            with open(file_path, 'r') as f:
                css_content = f.read()
            
            # Very basic minification (remove comments, extra whitespace)
            css_content = re.sub(r'/\*.*?\*/', '', css_content, flags=re.DOTALL)  # Remove comments
            css_content = re.sub(r'\s+', ' ', css_content)  # Collapse whitespace
            css_content = css_content.replace('} ', '}').replace(' {', '{')  # Remove space around braces
            css_content = re.sub(r';\s*}', '}', css_content)  # Remove last semicolon in rule
            
            optimized_path = file_path.replace('.css', '.min.css')
            with open(optimized_path, 'w') as f:
                f.write(css_content)
            
            result["optimizedSize"] = os.path.getsize(optimized_path)
            result["optimizedPath"] = optimized_path
            result["reductionPercent"] = round((1 - (result["optimizedSize"] / result["originalSize"])) * 100, 2)
        
        elif optimization_type == "js":
            # JavaScript optimization requires external tools
            result["message"] = "JavaScript optimization requires tools like Terser or UglifyJS"
            result["recommendation"] = "Use build tools like webpack, Rollup or Parcel for JS optimization"
        
        # Restore original file from backup
        os.remove(backup_path)
        
        await manager.send_response(message_id, result, websocket)
    
    except Exception as e:
        # Restore from backup if exists
        backup_path = file_path + ".backup"
        if os.path.exists(backup_path):
            shutil.copy2(backup_path, file_path)
            os.remove(backup_path)
        
        await manager.send_error(message_id, 500, str(e), websocket)

# Register web development methods
WEB_DEV_HANDLERS = {
    "createWebProject": handle_create_web_project,
    "runNpmCommand": handle_run_npm_command,
    "analyzeWebProject": handle_analyze_web_project,
    "generateComponent": handle_generate_component,
    "optimizeFrontend": handle_optimize_frontend,
}

# Update the METHOD_HANDLERS dictionary with web development handlers
from src.main import METHOD_HANDLERS, handle_start_long_running_command
METHOD_HANDLERS.update(WEB_DEV_HANDLERS)

# Make this runnable as a standalone server too
if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8003))
    host = os.environ.get("HOST", "0.0.0.0")
    print(f"Starting Web Development MCP Server on {host}:{port}")
    print(f"Available methods: {', '.join(WEB_DEV_HANDLERS.keys())}")
    uvicorn.run(app, host=host, port=port)