import asyncio
import json
import os
import sys
import base64
import io
from typing import Dict, Any, List, Optional, Union

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

# Path to the main module for importing shared code
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.main import app, Message, MessageType, manager

async def handle_generate_image(message_id: str, params: Dict[str, Any], websocket: WebSocket):
    """
    Generate an image using a local model or API
    Params:
      - prompt: String description for image generation
      - width: Image width (default: 512)
      - height: Image height (default: 512)
      - style: Optional style for the image
    """
    prompt = params.get("prompt", "")
    width = params.get("width", 512)
    height = params.get("height", 512)
    style = params.get("style", "photo")
    
    if not prompt:
        await manager.send_error(message_id, 400, "No prompt provided", websocket)
        return
    
    try:
        # Try to use a local API or fall back to CLI tools
        try:
            from PIL import Image
            from diffusers import DiffusionPipeline
            import torch
            
            # Check if we have stable diffusion models
            if os.path.exists(os.path.expanduser("~/.cache/huggingface/hub")):
                # Initialize the pipeline
                pipe = DiffusionPipeline.from_pretrained(
                    "runwayml/stable-diffusion-v1-5",
                    torch_dtype=torch.float16
                )
                if torch.cuda.is_available():
                    pipe = pipe.to("cuda")
                else:
                    pipe = pipe.to("cpu")
                
                # Generate the image
                image = pipe(prompt, height=height, width=width).images[0]
                
                # Convert to base64
                buffered = io.BytesIO()
                image.save(buffered, format="PNG")
                img_str = base64.b64encode(buffered.getvalue()).decode()
                
                result = {
                    "base64Image": img_str,
                    "prompt": prompt,
                    "width": width,
                    "height": height,
                    "style": style
                }
                await manager.send_response(message_id, result, websocket)
                return
            
        except ImportError:
            # Local models not available, try external API
            pass
        
        # Try to use an external API (e.g., Stability AI, OpenAI DALL-E)
        # This is a fallback if local models are not available
        # We'll simulate the response for demonstration purposes
        
        await manager.send_response(message_id, {
            "message": "Art generation request received",
            "explanation": "For actual image generation, you need to install diffusers, torch, and transformers packages, or integrate with external APIs like OpenAI DALL-E or Stability AI.",
            "prompt": prompt,
            "width": width,
            "height": height,
            "style": style
        }, websocket)
    
    except Exception as e:
        await manager.send_error(message_id, 500, str(e), websocket)

async def handle_image_edit(message_id: str, params: Dict[str, Any], websocket: WebSocket):
    """
    Edit an existing image 
    Params:
      - image: Base64 encoded image data
      - prompt: Description of edits to make
      - mask: Optional base64 encoded mask for inpainting
    """
    image = params.get("image", "")
    prompt = params.get("prompt", "")
    mask = params.get("mask", "")
    
    if not image or not prompt:
        await manager.send_error(message_id, 400, "Image and prompt are required", websocket)
        return
    
    try:
        # Simulated response for now
        await manager.send_response(message_id, {
            "message": "Image edit request received",
            "explanation": "For actual image editing, you need to install appropriate packages or integrate with external APIs.",
            "prompt": prompt
        }, websocket)
    
    except Exception as e:
        await manager.send_error(message_id, 500, str(e), websocket)

async def handle_convert_image(message_id: str, params: Dict[str, Any], websocket: WebSocket):
    """
    Convert an image from one format to another
    Params:
      - image: Base64 encoded image data
      - format: Target format (png, jpg, webp, etc.)
      - quality: Quality for lossy formats (1-100)
    """
    image_data = params.get("image", "")
    target_format = params.get("format", "png").lower()
    quality = params.get("quality", 90)
    
    if not image_data:
        await manager.send_error(message_id, 400, "Image data is required", websocket)
        return
    
    try:
        from PIL import Image
        import io
        import base64
        
        # Decode the base64 image
        image_bytes = base64.b64decode(image_data)
        image = Image.open(io.BytesIO(image_bytes))
        
        # Convert the image
        output_buffer = io.BytesIO()
        if target_format in ['jpg', 'jpeg']:
            image = image.convert('RGB')  # Remove alpha for JPEG
            image.save(output_buffer, format='JPEG', quality=quality)
        elif target_format == 'webp':
            image.save(output_buffer, format='WEBP', quality=quality)
        elif target_format == 'png':
            image.save(output_buffer, format='PNG')
        else:
            # Default to PNG
            image.save(output_buffer, format='PNG')
        
        # Get the converted image as base64
        output_buffer.seek(0)
        converted_image = base64.b64encode(output_buffer.getvalue()).decode('utf-8')
        
        await manager.send_response(message_id, {
            "convertedImage": converted_image,
            "format": target_format,
            "size": len(output_buffer.getvalue())
        }, websocket)
    
    except ImportError:
        await manager.send_response(message_id, {
            "message": "Image conversion requires the Pillow library",
            "installCommand": "pip install Pillow"
        }, websocket)
    except Exception as e:
        await manager.send_error(message_id, 500, str(e), websocket)

# Register art generation methods
ART_HANDLERS = {
    "generateImage": handle_generate_image,
    "editImage": handle_image_edit,
    "convertImage": handle_convert_image,
}

# Update the METHOD_HANDLERS dictionary
from src.main import METHOD_HANDLERS
METHOD_HANDLERS.update(ART_HANDLERS)

# Make this runnable as a standalone server too
if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8001))
    host = os.environ.get("HOST", "0.0.0.0")
    print(f"Starting Art Generation MCP Server on {host}:{port}")
    print(f"Available methods: {', '.join(ART_HANDLERS.keys())}")
    uvicorn.run(app, host=host, port=port)