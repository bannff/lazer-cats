#!/usr/bin/env python3
import asyncio
import sys
import os
import base64
from typing import Dict, Any, List, Optional, Union

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

# Path to the main module for importing shared code
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.main import app, Message, MessageType, manager

# Global browser and page management
_browser = None
_browser_context = None
_current_page = None
_playwright_instance = None
_tabs = {}
_current_tab_id = None

async def _import_playwright():
    """Dynamically import Playwright to avoid early import errors"""
    try:
        from playwright.async_api import async_playwright
        return async_playwright()
    except ImportError:
        error_message = (
            "Playwright is not installed. Please install it with:\n"
            "pip install playwright\n"
            "playwright install"
        )
        print(error_message, file=sys.stderr)
        raise ImportError(error_message)

async def _ensure_browser():
    """Ensure a browser instance is available with SSL validation disabled"""
    global _browser, _browser_context, _playwright_instance
    
    if _browser is None:
        _playwright_instance = await _import_playwright()
        _browser = await _playwright_instance.chromium.launch()
        
        # Create a browser context that ignores HTTPS errors
        _browser_context = await _browser.new_context(
            ignore_https_errors=True,  # Ignore SSL certificate errors
        )
    return _browser, _browser_context

async def _close_current_page():
    """Close the current page if it exists"""
    global _current_page
    if _current_page:
        try:
            await _current_page.close()
        except Exception:
            pass
        _current_page = None

async def _safe_cleanup():
    """Safely clean up browser resources"""
    global _browser, _current_page, _browser_context, _playwright_instance, _tabs
    
    try:
        # Close all tabs
        for tab_id, page in _tabs.items():
            try:
                await page.close()
            except Exception:
                pass
        _tabs = {}
        
        if _current_page:
            try:
                await _current_page.close()
            except Exception:
                pass
        
        if _browser_context:
            try:
                await _browser_context.close()
            except Exception:
                pass
        
        if _browser:
            try:
                await _browser.close()
            except Exception:
                pass
        
        if _playwright_instance:
            try:
                await _playwright_instance.stop()
            except Exception:
                pass
    except Exception as e:
        print(f"Error during cleanup: {e}", file=sys.stderr)
    finally:
        # Reset global variables
        _browser = None
        _browser_context = None
        _current_page = None
        _playwright_instance = None
        _tabs = {}
        _current_tab_id = None

async def handle_browse_to(message_id: str, params: Dict[str, Any], websocket: WebSocket):
    """
    Navigate to a specific URL and return the page's HTML content.
    
    Params:
      - url: The full URL to navigate to
    """
    global _current_page, _current_tab_id
    
    url = params.get("url", "")
    if not url:
        await manager.send_error(message_id, 400, "URL is required", websocket)
        return
    
    try:
        # Ensure browser is launched with SSL validation disabled
        _, browser_context = await _ensure_browser()
        
        # Close any existing page if not using tabs
        if not _current_tab_id:
            await _close_current_page()
            
            # Create a new page and navigate
            _current_page = await browser_context.new_page()
        else:
            # Use the current tab
            _current_page = _tabs[_current_tab_id]
        
        # Navigate to URL
        await _current_page.goto(url, 
            wait_until='networkidle',
            timeout=30000,  # 30 seconds timeout
        )
        
        # Get full page content
        page_content = await _current_page.content()
        title = await _current_page.title()
        
        await manager.send_response(message_id, {
            "url": url,
            "title": title,
            "content": page_content
        }, websocket)
    
    except Exception as e:
        await manager.send_error(message_id, 500, str(e), websocket)

async def handle_extract_text_content(message_id: str, params: Dict[str, Any], websocket: WebSocket):
    """
    Extract text content from the current page, optionally using a CSS selector.
    
    Params:
      - selector: Optional CSS selector to target specific elements
    """
    global _current_page
    
    if not _current_page:
        await manager.send_error(message_id, 400, "No page is currently loaded. Use browseTo first.", websocket)
        return
    
    selector = params.get("selector", None)
    
    try:
        if selector:
            # If selector is provided, extract text from matching elements
            elements = await _current_page.query_selector_all(selector)
            text_content = "\n".join([await el.inner_text() for el in elements])
        else:
            # If no selector, extract all visible text from the page
            text_content = await _current_page.inner_text('body')
        
        await manager.send_response(message_id, {"textContent": text_content}, websocket)
    
    except Exception as e:
        await manager.send_error(message_id, 500, str(e), websocket)

async def handle_click_element(message_id: str, params: Dict[str, Any], websocket: WebSocket):
    """
    Click an element on the current page.
    
    Params:
      - selector: CSS selector for the element to click
    """
    global _current_page
    
    if not _current_page:
        await manager.send_error(message_id, 400, "No page is currently loaded. Use browseTo first.", websocket)
        return
    
    selector = params.get("selector", "")
    if not selector:
        await manager.send_error(message_id, 400, "Element selector is required", websocket)
        return
    
    try:
        element = await _current_page.query_selector(selector)
        if not element:
            await manager.send_error(message_id, 404, f"No element found with selector: {selector}", websocket)
            return
        
        await element.click()
        await manager.send_response(message_id, {"success": True, "message": f"Successfully clicked element: {selector}"}, websocket)
    
    except Exception as e:
        await manager.send_error(message_id, 500, str(e), websocket)

async def handle_get_page_screenshots(message_id: str, params: Dict[str, Any], websocket: WebSocket):
    """
    Capture screenshot of the current page.
    
    Params:
      - fullPage: Whether to capture the entire page or just the viewport
      - selector: Optional CSS selector to screenshot a specific element
    """
    global _current_page
    
    if not _current_page:
        await manager.send_error(message_id, 400, "No page is currently loaded. Use browseTo first.", websocket)
        return
    
    full_page = params.get("fullPage", False)
    selector = params.get("selector", None)
    
    try:
        if selector:
            element = await _current_page.query_selector(selector)
            if not element:
                await manager.send_error(message_id, 404, f"No element found with selector: {selector}", websocket)
                return
            screenshot_bytes = await element.screenshot()
        else:
            screenshot_bytes = await _current_page.screenshot(full_page=full_page)
        
        # Convert to base64 for easy transmission
        screenshot_base64 = base64.b64encode(screenshot_bytes).decode('utf-8')
        
        await manager.send_response(message_id, {"screenshot": screenshot_base64}, websocket)
    
    except Exception as e:
        await manager.send_error(message_id, 500, str(e), websocket)

async def handle_get_page_links(message_id: str, params: Dict[str, Any], websocket: WebSocket):
    """
    Extract all links from the current page.
    
    Params:
      - filterPattern: Optional text pattern to filter links
    """
    global _current_page
    
    if not _current_page:
        await manager.send_error(message_id, 400, "No page is currently loaded. Use browseTo first.", websocket)
        return
    
    filter_pattern = params.get("filterPattern", None)
    
    try:
        # Use JavaScript to extract all links
        links = await _current_page.evaluate("""
            () => {
                const links = document.querySelectorAll('a');
                return Array.from(links).map(link => {
                    return {
                        url: link.href,
                        text: link.innerText.trim(),
                        title: link.title
                    };
                });
            }
        """)
        
        # Apply filter if needed
        if filter_pattern:
            links = [link for link in links if filter_pattern.lower() in link["url"].lower() or 
                    filter_pattern.lower() in link["text"].lower() or 
                    (link["title"] and filter_pattern.lower() in link["title"].lower())]
        
        await manager.send_response(message_id, {"links": links}, websocket)
    
    except Exception as e:
        await manager.send_error(message_id, 500, str(e), websocket)

async def handle_input_text(message_id: str, params: Dict[str, Any], websocket: WebSocket):
    """
    Input text into a specific element on the page.
    
    Params:
      - selector: CSS selector for the input element
      - text: Text to input
    """
    global _current_page
    
    if not _current_page:
        await manager.send_error(message_id, 400, "No page is currently loaded. Use browseTo first.", websocket)
        return
    
    selector = params.get("selector", "")
    text = params.get("text", "")
    
    if not selector:
        await manager.send_error(message_id, 400, "Element selector is required", websocket)
        return
    
    try:
        element = await _current_page.query_selector(selector)
        if not element:
            await manager.send_error(message_id, 404, f"No element found with selector: {selector}", websocket)
            return
        
        await element.fill(text)
        await manager.send_response(message_id, {"success": True, "message": f"Successfully input text into element: {selector}"}, websocket)
    
    except Exception as e:
        await manager.send_error(message_id, 500, str(e), websocket)

async def handle_create_new_tab(message_id: str, params: Dict[str, Any], websocket: WebSocket):
    """
    Create a new browser tab.
    
    Params:
      - url: Optional URL to navigate to in the new tab
    """
    global _tabs, _current_tab_id, _current_page
    
    try:
        # Ensure browser is launched
        _, browser_context = await _ensure_browser()
        
        # Create a new page/tab
        new_page = await browser_context.new_page()
        
        # Generate a unique tab ID
        import uuid
        tab_id = str(uuid.uuid4())
        
        # Store the tab
        _tabs[tab_id] = new_page
        _current_tab_id = tab_id
        _current_page = new_page
        
        # Navigate to URL if provided
        url = params.get("url", None)
        if url:
            await new_page.goto(url, wait_until='networkidle', timeout=30000)
            title = await new_page.title()
        else:
            title = "New Tab"
        
        await manager.send_response(message_id, {
            "tabId": tab_id,
            "title": title,
            "url": url or "about:blank"
        }, websocket)
    
    except Exception as e:
        await manager.send_error(message_id, 500, str(e), websocket)

async def handle_switch_tab(message_id: str, params: Dict[str, Any], websocket: WebSocket):
    """
    Switch to a different tab.
    
    Params:
      - tabId: ID of the tab to switch to
    """
    global _tabs, _current_tab_id, _current_page
    
    tab_id = params.get("tabId", "")
    if not tab_id:
        await manager.send_error(message_id, 400, "Tab ID is required", websocket)
        return
    
    if tab_id not in _tabs:
        await manager.send_error(message_id, 404, f"Tab with ID {tab_id} not found", websocket)
        return
    
    try:
        _current_tab_id = tab_id
        _current_page = _tabs[tab_id]
        
        title = await _current_page.title()
        url = _current_page.url
        
        await manager.send_response(message_id, {
            "tabId": tab_id,
            "title": title,
            "url": url
        }, websocket)
    
    except Exception as e:
        await manager.send_error(message_id, 500, str(e), websocket)

async def handle_list_tabs(message_id: str, params: Dict[str, Any], websocket: WebSocket):
    """
    List all open tabs.
    """
    global _tabs, _current_tab_id
    
    try:
        tabs_info = []
        
        for tab_id, page in _tabs.items():
            try:
                title = await page.title()
                url = page.url
            except:
                title = "Unknown"
                url = "Unknown"
            
            tabs_info.append({
                "tabId": tab_id,
                "title": title,
                "url": url,
                "isCurrent": tab_id == _current_tab_id
            })
        
        await manager.send_response(message_id, {"tabs": tabs_info}, websocket)
    
    except Exception as e:
        await manager.send_error(message_id, 500, str(e), websocket)

async def handle_close_tab(message_id: str, params: Dict[str, Any], websocket: WebSocket):
    """
    Close a tab.
    
    Params:
      - tabId: Optional ID of the tab to close (defaults to current tab)
    """
    global _tabs, _current_tab_id, _current_page
    
    tab_id = params.get("tabId", _current_tab_id)
    if not tab_id:
        await manager.send_error(message_id, 400, "No tab is currently active", websocket)
        return
    
    if tab_id not in _tabs:
        await manager.send_error(message_id, 404, f"Tab with ID {tab_id} not found", websocket)
        return
    
    try:
        # Close the tab
        await _tabs[tab_id].close()
        
        # Remove from tabs dictionary
        del _tabs[tab_id]
        
        # Reset current tab if this was the current tab
        if tab_id == _current_tab_id:
            _current_tab_id = next(iter(_tabs)) if _tabs else None
            _current_page = _tabs[_current_tab_id] if _current_tab_id else None
        
        await manager.send_response(message_id, {
            "success": True,
            "message": f"Tab {tab_id} closed successfully",
            "currentTabId": _current_tab_id
        }, websocket)
    
    except Exception as e:
        await manager.send_error(message_id, 500, str(e), websocket)

async def handle_get_page_info(message_id: str, params: Dict[str, Any], websocket: WebSocket):
    """
    Get detailed information about the current page.
    """
    global _current_page
    
    if not _current_page:
        await manager.send_error(message_id, 400, "No page is currently loaded. Use browseTo first.", websocket)
        return
    
    try:
        url = _current_page.url
        title = await _current_page.title()
        
        # Get page metrics
        metrics = await _current_page.evaluate("""
            () => {
                return {
                    width: window.innerWidth,
                    height: window.innerHeight,
                    devicePixelRatio: window.devicePixelRatio,
                    hasSelection: window.getSelection().toString() !== '',
                    loadingStatus: document.readyState
                };
            }
        """)
        
        # Get meta information
        meta_info = await _current_page.evaluate("""
            () => {
                const metas = document.querySelectorAll('meta');
                const result = {};
                metas.forEach(meta => {
                    if (meta.name) {
                        result[meta.name] = meta.content;
                    } else if (meta.property) {
                        result[meta.property] = meta.content;
                    }
                });
                return result;
            }
        """)
        
        await manager.send_response(message_id, {
            "url": url,
            "title": title,
            "metrics": metrics,
            "metaInfo": meta_info
        }, websocket)
    
    except Exception as e:
        await manager.send_error(message_id, 500, str(e), websocket)

async def handle_scroll_page(message_id: str, params: Dict[str, Any], websocket: WebSocket):
    """
    Scroll the page in a specified direction and amount.
    
    Params:
      - direction: Direction to scroll ('up', 'down', 'left', 'right')
      - amount: Amount to scroll ('page', 'half', or a number)
    """
    global _current_page
    
    if not _current_page:
        await manager.send_error(message_id, 400, "No page is currently loaded. Use browseTo first.", websocket)
        return
    
    direction = params.get("direction", "down").lower()
    amount = params.get("amount", "page")
    
    if direction not in ['up', 'down', 'left', 'right']:
        await manager.send_error(message_id, 400, "Direction must be one of: up, down, left, right", websocket)
        return
    
    try:
        # Convert amount to pixels
        if amount == "page":
            js_amount = "window.innerHeight - 50" if direction in ['up', 'down'] else "window.innerWidth - 50"
        elif amount == "half":
            js_amount = "window.innerHeight / 2" if direction in ['up', 'down'] else "window.innerWidth / 2"
        else:
            try:
                int_amount = int(amount)
                js_amount = str(int_amount)
            except ValueError:
                await manager.send_error(message_id, 400, "Amount must be 'page', 'half', or a number", websocket)
                return
        
        # Apply direction
        if direction == "up":
            js_amount = f"-({js_amount})"
        elif direction == "left":
            js_amount = f"-({js_amount})"
        
        # Execute scroll
        if direction in ['up', 'down']:
            await _current_page.evaluate(f"window.scrollBy(0, {js_amount})")
        else:
            await _current_page.evaluate(f"window.scrollBy({js_amount}, 0)")
        
        await manager.send_response(message_id, {
            "success": True,
            "message": f"Scrolled {direction} by {amount}"
        }, websocket)
    
    except Exception as e:
        await manager.send_error(message_id, 500, str(e), websocket)

async def handle_execute_javascript(message_id: str, params: Dict[str, Any], websocket: WebSocket):
    """
    Execute JavaScript code on the current page.
    
    Params:
      - script: JavaScript code to execute
    """
    global _current_page
    
    if not _current_page:
        await manager.send_error(message_id, 400, "No page is currently loaded. Use browseTo first.", websocket)
        return
    
    script = params.get("script", "")
    if not script:
        await manager.send_error(message_id, 400, "JavaScript code is required", websocket)
        return
    
    try:
        result = await _current_page.evaluate(script)
        
        # Convert result to string if it's not serializable
        if result is not None and not isinstance(result, (str, int, float, bool, list, dict, type(None))):
            result = str(result)
        
        await manager.send_response(message_id, {"result": result}, websocket)
    
    except Exception as e:
        await manager.send_error(message_id, 500, str(e), websocket)

async def handle_refresh_page(message_id: str, params: Dict[str, Any], websocket: WebSocket):
    """
    Refresh the current page.
    """
    global _current_page
    
    if not _current_page:
        await manager.send_error(message_id, 400, "No page is currently loaded. Use browseTo first.", websocket)
        return
    
    try:
        await _current_page.reload(wait_until='networkidle', timeout=30000)
        
        title = await _current_page.title()
        url = _current_page.url
        
        await manager.send_response(message_id, {
            "success": True,
            "title": title,
            "url": url
        }, websocket)
    
    except Exception as e:
        await manager.send_error(message_id, 500, str(e), websocket)

# Register browser methods
WEB_BROWSER_HANDLERS = {
    "browseTo": handle_browse_to,
    "extractTextContent": handle_extract_text_content,
    "clickElement": handle_click_element,
    "getPageScreenshots": handle_get_page_screenshots,
    "getPageLinks": handle_get_page_links,
    "inputText": handle_input_text,
    "createNewTab": handle_create_new_tab,
    "switchTab": handle_switch_tab,
    "listTabs": handle_list_tabs,
    "closeTab": handle_close_tab,
    "getPageInfo": handle_get_page_info,
    "scrollPage": handle_scroll_page,
    "executeJavaScript": handle_execute_javascript,
    "refreshPage": handle_refresh_page,
}

# Update the METHOD_HANDLERS dictionary with web browser handlers
from src.main import METHOD_HANDLERS
METHOD_HANDLERS.update(WEB_BROWSER_HANDLERS)

# Register cleanup on process exit
import atexit
import asyncio

def cleanup_browser():
    """Clean up browser resources on process exit"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(_safe_cleanup())
    loop.close()

atexit.register(cleanup_browser)

# Make this runnable as a standalone server too
if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8006))
    host = os.environ.get("HOST", "0.0.0.0")
    print(f"Starting Web Browser MCP Server on {host}:{port}")
    print(f"Available methods: {', '.join(WEB_BROWSER_HANDLERS.keys())}")
    uvicorn.run(app, host=host, port=port)