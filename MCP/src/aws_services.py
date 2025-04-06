import asyncio
import json
import os
import sys
import base64
import requests
import re
import tempfile
from typing import Dict, Any, List, Optional, Union

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

# Path to the main module for importing shared code
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.main import app, Message, MessageType, manager

async def handle_aws_cli_command(message_id: str, params: Dict[str, Any], websocket: WebSocket):
    """
    Execute an AWS CLI command and return the results
    Params:
      - command: The AWS CLI command to execute (e.g., "s3 ls")
      - profile: Optional AWS profile to use
      - region: Optional AWS region to use
      - outputFormat: Optional output format (json, text, table)
    """
    command = params.get("command", "")
    profile = params.get("profile", "")
    region = params.get("region", "")
    output_format = params.get("outputFormat", "json")
    
    if not command:
        await manager.send_error(message_id, 400, "AWS CLI command is required", websocket)
        return
    
    try:
        # Build the AWS CLI command with profile and region if provided
        aws_command = "aws"
        
        if profile:
            aws_command += f" --profile {profile}"
        
        if region:
            aws_command += f" --region {region}"
        
        aws_command += f" --output {output_format} {command}"
        
        # Execute the AWS CLI command
        process = await asyncio.create_subprocess_shell(
            aws_command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()
        
        output = stdout.decode() if stdout else ""
        error = stderr.decode() if stderr else ""
        
        # Try to parse the JSON output if format is JSON
        result = {
            "command": aws_command,
            "rawOutput": output,
            "error": error,
            "exitCode": process.returncode
        }
        
        if output_format == "json" and output:
            try:
                parsed_json = json.loads(output)
                result["parsedOutput"] = parsed_json
            except json.JSONDecodeError:
                # Output wasn't valid JSON, just keep the raw output
                pass
        
        await manager.send_response(message_id, result, websocket)
    
    except Exception as e:
        await manager.send_error(message_id, 500, str(e), websocket)

async def handle_aws_service_docs(message_id: str, params: Dict[str, Any], websocket: WebSocket):
    """
    Fetch AWS service documentation
    Params:
      - service: AWS service name (e.g., "s3", "lambda", "ec2")
      - category: Optional category of documentation (e.g., "API", "CLI", "SDK")
      - query: Optional search query within the documentation
    """
    service = params.get("service", "").lower()
    category = params.get("category", "").lower()
    query = params.get("query", "")
    
    if not service:
        await manager.send_error(message_id, 400, "AWS service name is required", websocket)
        return
    
    try:
        result = {
            "service": service,
            "category": category,
            "query": query,
            "documentation": []
        }
        
        # Determine documentation source URLs based on service and category
        doc_urls = []
        
        if category == "api" or not category:
            doc_urls.append(f"https://docs.aws.amazon.com/{service}/latest/APIReference/Welcome.html")
        
        if category == "cli" or not category:
            doc_urls.append(f"https://docs.aws.amazon.com/cli/latest/reference/{service}/index.html")
        
        if category == "sdk" or not category:
            # Add Python SDK docs as an example
            doc_urls.append(f"https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/{service}.html")
        
        if category == "guide" or not category:
            doc_urls.append(f"https://docs.aws.amazon.com/{service}/latest/userguide/Welcome.html")
        
        # Get AWS documentation content
        docs = []
        for url in doc_urls:
            try:
                response = requests.get(url, timeout=10)
                
                if response.status_code == 200:
                    content = response.text
                    
                    # If query is provided, try to find relevant sections
                    if query:
                        # Simple regex-based extraction of relevant sections
                        query_pattern = re.compile(rf'<h\d[^>]*>.*?{re.escape(query)}.*?</h\d>.*?(?=<h\d|$)', 
                                                 re.IGNORECASE | re.DOTALL)
                        matches = query_pattern.findall(content)
                        
                        if matches:
                            relevant_content = "\n".join(matches)
                        else:
                            relevant_content = f"Query '{query}' not found in {url}"
                    else:
                        # Just extract the main content area (simplified)
                        main_content_pattern = re.compile(r'<main[^>]*>(.*?)</main>', re.DOTALL)
                        main_match = main_content_pattern.search(content)
                        relevant_content = main_match.group(1) if main_match else "Main content not found"
                    
                    docs.append({
                        "url": url,
                        "title": f"AWS {service.upper()} Documentation",
                        "content": relevant_content
                    })
                else:
                    docs.append({
                        "url": url,
                        "error": f"Failed to fetch documentation: HTTP {response.status_code}"
                    })
            
            except Exception as e:
                docs.append({
                    "url": url,
                    "error": f"Error fetching documentation: {str(e)}"
                })
        
        result["documentation"] = docs
        await manager.send_response(message_id, result, websocket)
    
    except Exception as e:
        await manager.send_error(message_id, 500, str(e), websocket)

async def handle_cloudformation_template(message_id: str, params: Dict[str, Any], websocket: WebSocket):
    """
    Generate or validate CloudFormation templates
    Params:
      - action: "generate", "validate", or "explain"
      - resources: List of AWS resources to include in the template (for generation)
      - template: Existing template content (for validation or explanation)
      - format: "json" or "yaml" for template format
    """
    action = params.get("action", "").lower()
    resources = params.get("resources", [])
    template_content = params.get("template", "")
    template_format = params.get("format", "yaml").lower()
    
    if not action:
        await manager.send_error(message_id, 400, "Action is required", websocket)
        return
    
    try:
        result = {
            "action": action,
            "format": template_format
        }
        
        if action == "generate":
            if not resources:
                await manager.send_error(message_id, 400, "Resources are required for template generation", websocket)
                return
            
            # Start with a basic template structure
            if template_format == "json":
                template = {
                    "AWSTemplateFormatVersion": "2010-09-09",
                    "Description": "Generated CloudFormation template",
                    "Resources": {}
                }
                
                # Add resources based on the requested types
                for resource in resources:
                    resource_type = resource.get("type", "")
                    resource_name = resource.get("name", f"Resource{len(template['Resources']) + 1}")
                    properties = resource.get("properties", {})
                    
                    if resource_type.startswith("AWS::"):
                        template["Resources"][resource_name] = {
                            "Type": resource_type,
                            "Properties": properties
                        }
                
                result["template"] = json.dumps(template, indent=2)
            
            else:  # YAML format
                template_lines = [
                    "AWSTemplateFormatVersion: '2010-09-09'",
                    "Description: 'Generated CloudFormation template'",
                    "Resources:"
                ]
                
                # Add resources based on the requested types
                for resource in resources:
                    resource_type = resource.get("type", "")
                    resource_name = resource.get("name", f"Resource{len(resources)}")
                    properties = resource.get("properties", {})
                    
                    if resource_type.startswith("AWS::"):
                        template_lines.append(f"  {resource_name}:")
                        template_lines.append(f"    Type: {resource_type}")
                        template_lines.append("    Properties:")
                        
                        # Add properties (simplified)
                        for prop_name, prop_value in properties.items():
                            if isinstance(prop_value, dict):
                                template_lines.append(f"      {prop_name}:")
                                for sub_key, sub_value in prop_value.items():
                                    template_lines.append(f"        {sub_key}: {sub_value}")
                            else:
                                template_lines.append(f"      {prop_name}: {prop_value}")
                
                result["template"] = "\n".join(template_lines)
        
        elif action == "validate":
            if not template_content:
                await manager.send_error(message_id, 400, "Template content is required for validation", websocket)
                return
            
            # Save template to a temporary file
            with tempfile.NamedTemporaryFile(suffix=f".{template_format}", delete=False) as temp_file:
                temp_file_path = temp_file.name
                temp_file.write(template_content.encode())
            
            try:
                # Use AWS CLI to validate the template
                process = await asyncio.create_subprocess_shell(
                    f"aws cloudformation validate-template --template-body file://{temp_file_path} --output json",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                stdout, stderr = await process.communicate()
                
                output = stdout.decode() if stdout else ""
                error = stderr.decode() if stderr else ""
                
                if process.returncode == 0:
                    try:
                        validation_result = json.loads(output)
                        result["valid"] = True
                        result["details"] = validation_result
                    except json.JSONDecodeError:
                        result["valid"] = True
                        result["rawOutput"] = output
                else:
                    result["valid"] = False
                    result["error"] = error
            
            finally:
                # Clean up the temporary file
                try:
                    os.unlink(temp_file_path)
                except:
                    pass
        
        elif action == "explain":
            if not template_content:
                await manager.send_error(message_id, 400, "Template content is required for explanation", websocket)
                return
            
            # Parse the template to explain its components
            if template_format == "json":
                try:
                    template = json.loads(template_content)
                    
                    # Extract resources
                    resources_info = []
                    for resource_name, resource_data in template.get("Resources", {}).items():
                        resource_type = resource_data.get("Type", "Unknown")
                        properties = resource_data.get("Properties", {})
                        
                        resources_info.append({
                            "name": resource_name,
                            "type": resource_type,
                            "properties": properties
                        })
                    
                    # Extract parameters
                    parameters_info = []
                    for param_name, param_data in template.get("Parameters", {}).items():
                        parameters_info.append({
                            "name": param_name,
                            "type": param_data.get("Type", "String"),
                            "description": param_data.get("Description", ""),
                            "default": param_data.get("Default", "")
                        })
                    
                    # Extract outputs
                    outputs_info = []
                    for output_name, output_data in template.get("Outputs", {}).items():
                        outputs_info.append({
                            "name": output_name,
                            "description": output_data.get("Description", ""),
                            "value": output_data.get("Value", "")
                        })
                    
                    result["explanation"] = {
                        "description": template.get("Description", "No description provided"),
                        "resourceCount": len(resources_info),
                        "resources": resources_info,
                        "parameters": parameters_info,
                        "outputs": outputs_info
                    }
                
                except json.JSONDecodeError as e:
                    result["error"] = f"Invalid JSON template: {str(e)}"
            
            else:  # YAML format
                try:
                    import yaml
                    
                    template = yaml.safe_load(template_content)
                    
                    # Extract resources (similar to JSON processing)
                    resources_info = []
                    for resource_name, resource_data in template.get("Resources", {}).items():
                        resource_type = resource_data.get("Type", "Unknown")
                        properties = resource_data.get("Properties", {})
                        
                        resources_info.append({
                            "name": resource_name,
                            "type": resource_type,
                            "properties": properties
                        })
                    
                    # Extract parameters
                    parameters_info = []
                    for param_name, param_data in template.get("Parameters", {}).items():
                        parameters_info.append({
                            "name": param_name,
                            "type": param_data.get("Type", "String"),
                            "description": param_data.get("Description", ""),
                            "default": param_data.get("Default", "")
                        })
                    
                    # Extract outputs
                    outputs_info = []
                    for output_name, output_data in template.get("Outputs", {}).items():
                        outputs_info.append({
                            "name": output_name,
                            "description": output_data.get("Description", ""),
                            "value": output_data.get("Value", "")
                        })
                    
                    result["explanation"] = {
                        "description": template.get("Description", "No description provided"),
                        "resourceCount": len(resources_info),
                        "resources": resources_info,
                        "parameters": parameters_info,
                        "outputs": outputs_info
                    }
                
                except Exception as e:
                    result["error"] = f"Error parsing YAML template: {str(e)}"
                    result["note"] = "Make sure PyYAML is installed (pip install pyyaml)"
        
        else:
            await manager.send_error(message_id, 400, f"Unknown action: {action}", websocket)
            return
        
        await manager.send_response(message_id, result, websocket)
    
    except Exception as e:
        await manager.send_error(message_id, 500, str(e), websocket)

async def handle_aws_cdk_helper(message_id: str, params: Dict[str, Any], websocket: WebSocket):
    """
    Assist with AWS CDK development
    Params:
      - action: "init", "synth", "deploy", "diff", or "explain"
      - language: Programming language for CDK (TypeScript, Python, Java, C#)
      - projectPath: Path to the CDK project
      - stackName: Optional stack name for certain operations
      - code: Optional CDK code snippet for explanation
    """
    action = params.get("action", "").lower()
    language = params.get("language", "typescript").lower()
    project_path = params.get("projectPath", os.getcwd())
    stack_name = params.get("stackName", "")
    code = params.get("code", "")
    
    if not action:
        await manager.send_error(message_id, 400, "Action is required", websocket)
        return
    
    try:
        result = {
            "action": action,
            "language": language
        }
        
        if action == "init":
            # Map language to CDK language option
            lang_map = {
                "typescript": "typescript",
                "ts": "typescript",
                "python": "python",
                "py": "python",
                "java": "java",
                "csharp": "csharp",
                "cs": "csharp",
                "c#": "csharp"
            }
            
            # Get the language option for CDK
            cdk_lang = lang_map.get(language, "typescript")
            
            # Execute CDK init command
            process = await asyncio.create_subprocess_shell(
                f"cd {project_path} && npx cdk init app --language {cdk_lang}",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await process.communicate()
            
            output = stdout.decode() if stdout else ""
            error = stderr.decode() if stderr else ""
            
            result["output"] = output
            result["error"] = error
            result["exitCode"] = process.returncode
        
        elif action == "synth":
            # Stack parameter is optional for synth
            stack_param = f"{stack_name}" if stack_name else ""
            
            # Execute CDK synth command
            process = await asyncio.create_subprocess_shell(
                f"cd {project_path} && npx cdk synth {stack_param}",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await process.communicate()
            
            output = stdout.decode() if stdout else ""
            error = stderr.decode() if stderr else ""
            
            result["output"] = output
            result["error"] = error
            result["exitCode"] = process.returncode
            
            # Try to extract CloudFormation template from output
            if "Resources:" in output:
                # Find where the template starts
                template_start = output.find("Resources:")
                if template_start != -1:
                    result["template"] = output[template_start:]
        
        elif action == "deploy":
            if not stack_name:
                await manager.send_error(message_id, 400, "Stack name is required for deployment", websocket)
                return
            
            # Execute CDK deploy command
            process = await asyncio.create_subprocess_shell(
                f"cd {project_path} && npx cdk deploy {stack_name} --require-approval never",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await process.communicate()
            
            output = stdout.decode() if stdout else ""
            error = stderr.decode() if stderr else ""
            
            result["output"] = output
            result["error"] = error
            result["exitCode"] = process.returncode
        
        elif action == "diff":
            # Stack parameter is optional for diff
            stack_param = f"{stack_name}" if stack_name else ""
            
            # Execute CDK diff command
            process = await asyncio.create_subprocess_shell(
                f"cd {project_path} && npx cdk diff {stack_param}",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await process.communicate()
            
            output = stdout.decode() if stdout else ""
            error = stderr.decode() if stderr else ""
            
            result["output"] = output
            result["error"] = error
            result["exitCode"] = process.returncode
        
        elif action == "explain":
            if not code:
                await manager.send_error(message_id, 400, "CDK code is required for explanation", websocket)
                return
            
            # Analyze the CDK code
            # This is a simplified analysis, a real implementation would need
            # to understand CDK constructs in different languages
            
            # Look for common CDK patterns based on language
            resource_types = []
            
            if language in ["typescript", "ts"]:
                # Look for TypeScript CDK construct patterns
                resource_pattern = re.compile(r'new\s+([A-Za-z0-9.]+)\(')
                resource_types = resource_pattern.findall(code)
            
            elif language in ["python", "py"]:
                # Look for Python CDK construct patterns
                resource_pattern = re.compile(r'([A-Za-z0-9_]+)\(')
                resource_types = resource_pattern.findall(code)
            
            # Basic info about common CDK constructs
            construct_info = {
                "Stack": "A CloudFormation stack definition",
                "Construct": "A basic CDK construct building block",
                "Function": "Lambda function resource",
                "Bucket": "S3 bucket resource",
                "Table": "DynamoDB table resource",
                "Queue": "SQS queue resource",
                "Topic": "SNS topic resource",
                "Role": "IAM role resource",
                "Policy": "IAM policy resource",
                "VPC": "VPC network resource",
                "Subnet": "VPC subnet resource",
                "SecurityGroup": "VPC security group resource"
            }
            
            # Build explanation
            resources_found = []
            for resource in resource_types:
                # Strip namespace prefixes
                simple_name = resource.split('.')[-1]
                
                # Check if we have info for this construct
                description = construct_info.get(simple_name, "Unknown CDK construct")
                
                resources_found.append({
                    "name": resource,
                    "type": simple_name,
                    "description": description
                })
            
            result["explanation"] = {
                "language": language,
                "constructs": resources_found,
                "constructCount": len(resources_found)
            }
        
        else:
            await manager.send_error(message_id, 400, f"Unknown action: {action}", websocket)
            return
        
        await manager.send_response(message_id, result, websocket)
    
    except Exception as e:
        await manager.send_error(message_id, 500, str(e), websocket)

async def handle_aws_sam_helper(message_id: str, params: Dict[str, Any], websocket: WebSocket):
    """
    Assist with AWS SAM development
    Params:
      - action: "init", "build", "deploy", "local" (for local testing)
      - projectPath: Path to the SAM project
      - templatePath: Path to SAM template file
      - stackName: Optional stack name for deployment
      - runtime: Runtime for initialization (e.g., "python3.9", "nodejs14.x")
    """
    action = params.get("action", "").lower()
    project_path = params.get("projectPath", os.getcwd())
    template_path = params.get("templatePath", "template.yaml")
    stack_name = params.get("stackName", "")
    runtime = params.get("runtime", "")
    
    if not action:
        await manager.send_error(message_id, 400, "Action is required", websocket)
        return
    
    try:
        result = {
            "action": action,
            "projectPath": project_path
        }
        
        if action == "init":
            if not runtime:
                await manager.send_error(message_id, 400, "Runtime is required for initialization", websocket)
                return
            
            # Execute SAM init command
            process = await asyncio.create_subprocess_shell(
                f"cd {project_path} && sam init --runtime {runtime} --name sam-app",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await process.communicate()
            
            output = stdout.decode() if stdout else ""
            error = stderr.decode() if stderr else ""
            
            result["output"] = output
            result["error"] = error
            result["exitCode"] = process.returncode
        
        elif action == "build":
            # Execute SAM build command
            process = await asyncio.create_subprocess_shell(
                f"cd {project_path} && sam build --template {template_path}",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await process.communicate()
            
            output = stdout.decode() if stdout else ""
            error = stderr.decode() if stderr else ""
            
            result["output"] = output
            result["error"] = error
            result["exitCode"] = process.returncode
        
        elif action == "deploy":
            if not stack_name:
                await manager.send_error(message_id, 400, "Stack name is required for deployment", websocket)
                return
            
            # Execute SAM deploy command (with guided=false for non-interactive mode)
            process = await asyncio.create_subprocess_shell(
                f"cd {project_path} && sam deploy --template {template_path} --stack-name {stack_name} --no-confirm-changeset --no-fail-on-empty-changeset",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await process.communicate()
            
            output = stdout.decode() if stdout else ""
            error = stderr.decode() if stderr else ""
            
            result["output"] = output
            result["error"] = error
            result["exitCode"] = process.returncode
        
        elif action == "local":
            # Added optional params
            event = params.get("event", "")
            function_id = params.get("functionId", "")
            
            if not function_id:
                await manager.send_error(message_id, 400, "Function ID is required for local testing", websocket)
                return
            
            # Create a command for local invocation
            command = f"cd {project_path} && sam local invoke {function_id}"
            
            # Add event file if provided
            if event:
                # Save event to a temporary file
                with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as temp_file:
                    temp_event_path = temp_file.name
                    temp_file.write(event.encode())
                
                command += f" -e {temp_event_path}"
            
            try:
                # Execute SAM local invoke command
                process = await asyncio.create_subprocess_shell(
                    command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                stdout, stderr = await process.communicate()
                
                output = stdout.decode() if stdout else ""
                error = stderr.decode() if stderr else ""
                
                result["output"] = output
                result["error"] = error
                result["exitCode"] = process.returncode
            
            finally:
                # Clean up temporary event file if it was created
                if event:
                    try:
                        os.unlink(temp_event_path)
                    except:
                        pass
        
        else:
            await manager.send_error(message_id, 400, f"Unknown action: {action}", websocket)
            return
        
        await manager.send_response(message_id, result, websocket)
    
    except Exception as e:
        await manager.send_error(message_id, 500, str(e), websocket)

# Register AWS methods
AWS_HANDLERS = {
    "awsCliCommand": handle_aws_cli_command,
    "awsServiceDocs": handle_aws_service_docs,
    "cloudFormationTemplate": handle_cloudformation_template,
    "awsCdkHelper": handle_aws_cdk_helper,
    "awsSamHelper": handle_aws_sam_helper,
}

# Update the METHOD_HANDLERS dictionary
from src.main import METHOD_HANDLERS
METHOD_HANDLERS.update(AWS_HANDLERS)

# Make this runnable as a standalone server too
if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8004))
    host = os.environ.get("HOST", "0.0.0.0")
    print(f"Starting AWS Services MCP Server on {host}:{port}")
    print(f"Available methods: {', '.join(AWS_HANDLERS.keys())}")
    uvicorn.run(app, host=host, port=port)