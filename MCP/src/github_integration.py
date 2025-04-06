import asyncio
import json
import os
import sys
import base64
import requests
import re
import tempfile
from typing import Dict, Any, List, Optional, Union
from datetime import datetime

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

# Path to the main module for importing shared code
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.main import app, Message, MessageType, manager

# GitHub API base URL
GITHUB_API_BASE = "https://api.github.com"

async def handle_github_auth(message_id: str, params: Dict[str, Any], websocket: WebSocket):
    """
    Authenticate with GitHub using personal access token or OAuth
    Params:
      - token: GitHub personal access token
      - storeToken: Whether to store the token for future use (default: true)
      - testConnection: Whether to test the token's validity (default: true)
    """
    token = params.get("token", "")
    store_token = params.get("storeToken", True)
    test_connection = params.get("testConnection", True)
    
    if not token:
        await manager.send_error(message_id, 400, "GitHub token is required", websocket)
        return
    
    try:
        # Create result data structure
        result = {
            "authenticated": False,
            "tokenStored": False
        }
        
        # Test the token if requested
        if test_connection:
            headers = {
                "Authorization": f"token {token}",
                "Accept": "application/vnd.github.v3+json"
            }
            
            response = requests.get(f"{GITHUB_API_BASE}/user", headers=headers)
            
            if response.status_code == 200:
                user_data = response.json()
                result["authenticated"] = True
                result["user"] = {
                    "login": user_data.get("login"),
                    "name": user_data.get("name"),
                    "id": user_data.get("id"),
                    "avatar_url": user_data.get("avatar_url"),
                    "html_url": user_data.get("html_url")
                }
            else:
                result["error"] = f"Authentication failed: {response.status_code} - {response.text}"
        
        # Store the token if requested
        if store_token:
            token_file = os.path.expanduser("~/.github_mcp_token")
            with open(token_file, "w") as f:
                f.write(token)
            os.chmod(token_file, 0o600)  # Set file permissions to owner-only read/write
            result["tokenStored"] = True
        
        await manager.send_response(message_id, result, websocket)
    
    except Exception as e:
        await manager.send_error(message_id, 500, str(e), websocket)

async def get_github_token():
    """Helper function to get the stored GitHub token"""
    token_file = os.path.expanduser("~/.github_mcp_token")
    if os.path.exists(token_file):
        with open(token_file, "r") as f:
            return f.read().strip()
    return None

async def handle_github_repos(message_id: str, params: Dict[str, Any], websocket: WebSocket):
    """
    List or search GitHub repositories
    Params:
      - action: "list" for user repos, "search" for searching all of GitHub
      - query: Search query (required for search action)
      - username: Username for listing repos (defaults to authenticated user)
      - filter: Filter options like "owner", "member", "all" (for list)
      - sort: Sort criteria like "updated", "stars", "forks"
      - perPage: Number of results per page (default: 30, max: 100)
      - page: Page number for pagination (default: 1)
    """
    action = params.get("action", "list").lower()
    query = params.get("query", "")
    username = params.get("username", "")
    filter_option = params.get("filter", "all")
    sort_option = params.get("sort", "updated")
    per_page = min(int(params.get("perPage", 30)), 100)
    page = int(params.get("page", 1))
    
    # Get stored GitHub token
    token = await get_github_token()
    if not token:
        await manager.send_error(message_id, 401, "GitHub token not found. Please authenticate first.", websocket)
        return
    
    try:
        headers = {
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github.v3+json"
        }
        
        result = {
            "action": action,
            "page": page,
            "perPage": per_page,
            "repositories": []
        }
        
        if action == "list":
            # Default to authenticated user if username not provided
            if not username:
                # Get authenticated user
                user_response = requests.get(f"{GITHUB_API_BASE}/user", headers=headers)
                if user_response.status_code != 200:
                    await manager.send_error(
                        message_id, 
                        user_response.status_code, 
                        f"Failed to get user info: {user_response.text}", 
                        websocket
                    )
                    return
                
                username = user_response.json().get("login")
            
            # List repositories for the user
            repos_url = f"{GITHUB_API_BASE}/users/{username}/repos"
            params = {
                "type": filter_option, 
                "sort": sort_option,
                "per_page": per_page,
                "page": page
            }
            
            response = requests.get(repos_url, headers=headers, params=params)
        
        elif action == "search":
            if not query:
                await manager.send_error(message_id, 400, "Search query is required", websocket)
                return
            
            # Search for repositories
            search_url = f"{GITHUB_API_BASE}/search/repositories"
            params = {
                "q": query,
                "sort": sort_option,
                "per_page": per_page,
                "page": page
            }
            
            response = requests.get(search_url, headers=headers, params=params)
        
        else:
            await manager.send_error(message_id, 400, f"Unknown action: {action}", websocket)
            return
        
        if response.status_code == 200:
            data = response.json()
            
            # Process repositories
            if action == "search":
                repos = data.get("items", [])
                result["totalCount"] = data.get("total_count", 0)
            else:
                repos = data
            
            # Extract relevant repo info
            for repo in repos:
                repo_info = {
                    "id": repo.get("id"),
                    "name": repo.get("name"),
                    "fullName": repo.get("full_name"),
                    "private": repo.get("private", False),
                    "htmlUrl": repo.get("html_url"),
                    "description": repo.get("description"),
                    "fork": repo.get("fork", False),
                    "createdAt": repo.get("created_at"),
                    "updatedAt": repo.get("updated_at"),
                    "pushedAt": repo.get("pushed_at"),
                    "homepage": repo.get("homepage"),
                    "size": repo.get("size"),
                    "stargazersCount": repo.get("stargazers_count"),
                    "watchersCount": repo.get("watchers_count"),
                    "language": repo.get("language"),
                    "forksCount": repo.get("forks_count"),
                    "openIssuesCount": repo.get("open_issues_count"),
                    "defaultBranch": repo.get("default_branch"),
                    "owner": {
                        "login": repo.get("owner", {}).get("login"),
                        "id": repo.get("owner", {}).get("id"),
                        "avatarUrl": repo.get("owner", {}).get("avatar_url"),
                        "htmlUrl": repo.get("owner", {}).get("html_url")
                    }
                }
                
                result["repositories"].append(repo_info)
            
            # Add pagination info if available
            if "Link" in response.headers:
                pagination = {}
                link_header = response.headers["Link"]
                links = link_header.split(",")
                
                for link in links:
                    match = re.search(r'<([^>]+)>;\s*rel="([^"]+)"', link)
                    if match:
                        url, rel = match.groups()
                        pagination[rel] = url
                
                result["pagination"] = pagination
        
        else:
            await manager.send_error(
                message_id,
                response.status_code,
                f"GitHub API error: {response.text}",
                websocket
            )
            return
        
        await manager.send_response(message_id, result, websocket)
    
    except Exception as e:
        await manager.send_error(message_id, 500, str(e), websocket)

async def handle_github_repo_content(message_id: str, params: Dict[str, Any], websocket: WebSocket):
    """
    Get content from a GitHub repository
    Params:
      - repo: Repository name (format: owner/repo)
      - path: Path within the repository (default: root)
      - ref: Git reference (branch, tag, commit SHA) (default: main/master)
      - fetchFiles: Whether to fetch file contents for small files (default: true)
      - recursive: For directories, whether to fetch recursively (default: false)
    """
    repo = params.get("repo", "")
    path = params.get("path", "")
    ref = params.get("ref", "")
    fetch_files = params.get("fetchFiles", True)
    recursive = params.get("recursive", False)
    
    if not repo:
        await manager.send_error(message_id, 400, "Repository name is required", websocket)
        return
    
    # Get stored GitHub token
    token = await get_github_token()
    if not token:
        await manager.send_error(message_id, 401, "GitHub token not found. Please authenticate first.", websocket)
        return
    
    try:
        headers = {
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github.v3+json"
        }
        
        # Clean up path
        path = path.lstrip('/')
        
        # Build the URL
        url = f"{GITHUB_API_BASE}/repos/{repo}/contents/{path}"
        params = {}
        
        if ref:
            params["ref"] = ref
        
        if recursive and not path:
            # To get recursive content for an entire repo, use the Git Trees API
            url = f"{GITHUB_API_BASE}/repos/{repo}/git/trees/{ref or 'master'}"
            params["recursive"] = "1"
        
        response = requests.get(url, headers=headers, params=params)
        
        if response.status_code == 200:
            data = response.json()
            
            result = {
                "repo": repo,
                "path": path,
                "ref": ref,
            }
            
            if recursive and not path:
                # Processing Git Trees API response
                result["type"] = "tree"
                result["items"] = []
                
                for item in data.get("tree", []):
                    item_info = {
                        "path": item.get("path"),
                        "type": item.get("type"),
                        "size": item.get("size"),
                        "sha": item.get("sha")
                    }
                    
                    result["items"].append(item_info)
            
            elif isinstance(data, list):
                # Directory content
                result["type"] = "directory"
                result["items"] = []
                
                for item in data:
                    item_info = {
                        "name": item.get("name"),
                        "path": item.get("path"),
                        "type": item.get("type"),
                        "size": item.get("size"),
                        "sha": item.get("sha"),
                        "url": item.get("html_url")
                    }
                    
                    # Fetch content for small files if requested
                    if fetch_files and item.get("type") == "file" and item.get("size", 0) < 100000:
                        file_response = requests.get(item.get("download_url"), headers=headers)
                        if file_response.status_code == 200:
                            item_info["content"] = file_response.text
                    
                    result["items"].append(item_info)
            
            else:
                # Single file content
                result["type"] = "file"
                result["name"] = data.get("name")
                result["size"] = data.get("size")
                result["sha"] = data.get("sha")
                result["url"] = data.get("html_url")
                
                if fetch_files and data.get("size", 0) < 1000000:
                    if data.get("encoding") == "base64" and data.get("content"):
                        content = base64.b64decode(data.get("content")).decode("utf-8")
                        result["content"] = content
                    else:
                        # Fetch raw content
                        file_response = requests.get(data.get("download_url"), headers=headers)
                        if file_response.status_code == 200:
                            result["content"] = file_response.text
            
            await manager.send_response(message_id, result, websocket)
        
        else:
            await manager.send_error(
                message_id,
                response.status_code,
                f"GitHub API error: {response.text}",
                websocket
            )
    
    except Exception as e:
        await manager.send_error(message_id, 500, str(e), websocket)

async def handle_github_issues(message_id: str, params: Dict[str, Any], websocket: WebSocket):
    """
    Manage GitHub issues
    Params:
      - action: "list", "get", "create", "update", "comment"
      - repo: Repository name (format: owner/repo)
      - issueNumber: Issue number (required for get, update, comment)
      - title: Issue title (required for create)
      - body: Issue body text
      - labels: List of issue labels
      - assignees: List of usernames to assign
      - state: Issue state ("open" or "closed") for updating
      - commentBody: Comment text (required for comment action)
    """
    action = params.get("action", "").lower()
    repo = params.get("repo", "")
    issue_number = params.get("issueNumber")
    title = params.get("title", "")
    body = params.get("body", "")
    labels = params.get("labels", [])
    assignees = params.get("assignees", [])
    state = params.get("state", "")
    comment_body = params.get("commentBody", "")
    
    if not repo:
        await manager.send_error(message_id, 400, "Repository name is required", websocket)
        return
    
    if not action:
        await manager.send_error(message_id, 400, "Action is required", websocket)
        return
    
    # Get stored GitHub token
    token = await get_github_token()
    if not token:
        await manager.send_error(message_id, 401, "GitHub token not found. Please authenticate first.", websocket)
        return
    
    try:
        headers = {
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github.v3+json"
        }
        
        if action == "list":
            # List issues in the repository
            url = f"{GITHUB_API_BASE}/repos/{repo}/issues"
            params = {
                "state": "all",
                "per_page": 100
            }
            
            response = requests.get(url, headers=headers, params=params)
            
            if response.status_code == 200:
                issues = response.json()
                result = {
                    "repo": repo,
                    "issueCount": len(issues),
                    "issues": []
                }
                
                for issue in issues:
                    # Check if it's a pull request (has pull_request key)
                    if "pull_request" in issue:
                        continue
                    
                    issue_info = {
                        "number": issue.get("number"),
                        "title": issue.get("title"),
                        "state": issue.get("state"),
                        "createdAt": issue.get("created_at"),
                        "updatedAt": issue.get("updated_at"),
                        "closedAt": issue.get("closed_at"),
                        "url": issue.get("html_url"),
                        "labels": [label.get("name") for label in issue.get("labels", [])],
                        "user": {
                            "login": issue.get("user", {}).get("login"),
                            "avatarUrl": issue.get("user", {}).get("avatar_url")
                        }
                    }
                    
                    result["issues"].append(issue_info)
                
                await manager.send_response(message_id, result, websocket)
            
            else:
                await manager.send_error(
                    message_id,
                    response.status_code,
                    f"GitHub API error: {response.text}",
                    websocket
                )
        
        elif action == "get":
            if not issue_number:
                await manager.send_error(message_id, 400, "Issue number is required", websocket)
                return
            
            # Get a specific issue
            url = f"{GITHUB_API_BASE}/repos/{repo}/issues/{issue_number}"
            response = requests.get(url, headers=headers)
            
            if response.status_code == 200:
                issue = response.json()
                
                # Get issue comments
                comments_url = f"{GITHUB_API_BASE}/repos/{repo}/issues/{issue_number}/comments"
                comments_response = requests.get(comments_url, headers=headers)
                comments = comments_response.json() if comments_response.status_code == 200 else []
                
                result = {
                    "repo": repo,
                    "number": issue.get("number"),
                    "title": issue.get("title"),
                    "body": issue.get("body"),
                    "state": issue.get("state"),
                    "createdAt": issue.get("created_at"),
                    "updatedAt": issue.get("updated_at"),
                    "closedAt": issue.get("closed_at"),
                    "url": issue.get("html_url"),
                    "labels": [label.get("name") for label in issue.get("labels", [])],
                    "assignees": [assignee.get("login") for assignee in issue.get("assignees", [])],
                    "user": {
                        "login": issue.get("user", {}).get("login"),
                        "avatarUrl": issue.get("user", {}).get("avatar_url")
                    },
                    "comments": []
                }
                
                for comment in comments:
                    comment_info = {
                        "id": comment.get("id"),
                        "body": comment.get("body"),
                        "createdAt": comment.get("created_at"),
                        "updatedAt": comment.get("updated_at"),
                        "user": {
                            "login": comment.get("user", {}).get("login"),
                            "avatarUrl": comment.get("user", {}).get("avatar_url")
                        }
                    }
                    
                    result["comments"].append(comment_info)
                
                await manager.send_response(message_id, result, websocket)
            
            else:
                await manager.send_error(
                    message_id,
                    response.status_code,
                    f"GitHub API error: {response.text}",
                    websocket
                )
        
        elif action == "create":
            if not title:
                await manager.send_error(message_id, 400, "Issue title is required", websocket)
                return
            
            # Create a new issue
            url = f"{GITHUB_API_BASE}/repos/{repo}/issues"
            data = {
                "title": title,
                "body": body
            }
            
            if labels:
                data["labels"] = labels
            
            if assignees:
                data["assignees"] = assignees
            
            response = requests.post(url, headers=headers, json=data)
            
            if response.status_code == 201:
                issue = response.json()
                
                result = {
                    "success": True,
                    "repo": repo,
                    "number": issue.get("number"),
                    "title": issue.get("title"),
                    "url": issue.get("html_url")
                }
                
                await manager.send_response(message_id, result, websocket)
            
            else:
                await manager.send_error(
                    message_id,
                    response.status_code,
                    f"GitHub API error: {response.text}",
                    websocket
                )
        
        elif action == "update":
            if not issue_number:
                await manager.send_error(message_id, 400, "Issue number is required", websocket)
                return
            
            # Update an existing issue
            url = f"{GITHUB_API_BASE}/repos/{repo}/issues/{issue_number}"
            data = {}
            
            if title:
                data["title"] = title
            
            if body:
                data["body"] = body
            
            if state:
                data["state"] = state
            
            if labels:
                data["labels"] = labels
            
            if assignees:
                data["assignees"] = assignees
            
            response = requests.patch(url, headers=headers, json=data)
            
            if response.status_code == 200:
                issue = response.json()
                
                result = {
                    "success": True,
                    "repo": repo,
                    "number": issue.get("number"),
                    "title": issue.get("title"),
                    "state": issue.get("state"),
                    "url": issue.get("html_url")
                }
                
                await manager.send_response(message_id, result, websocket)
            
            else:
                await manager.send_error(
                    message_id,
                    response.status_code,
                    f"GitHub API error: {response.text}",
                    websocket
                )
        
        elif action == "comment":
            if not issue_number:
                await manager.send_error(message_id, 400, "Issue number is required", websocket)
                return
            
            if not comment_body:
                await manager.send_error(message_id, 400, "Comment body is required", websocket)
                return
            
            # Add a comment to an issue
            url = f"{GITHUB_API_BASE}/repos/{repo}/issues/{issue_number}/comments"
            data = {
                "body": comment_body
            }
            
            response = requests.post(url, headers=headers, json=data)
            
            if response.status_code == 201:
                comment = response.json()
                
                result = {
                    "success": True,
                    "repo": repo,
                    "issueNumber": issue_number,
                    "commentId": comment.get("id"),
                    "url": comment.get("html_url")
                }
                
                await manager.send_response(message_id, result, websocket)
            
            else:
                await manager.send_error(
                    message_id,
                    response.status_code,
                    f"GitHub API error: {response.text}",
                    websocket
                )
        
        else:
            await manager.send_error(message_id, 400, f"Unknown action: {action}", websocket)
    
    except Exception as e:
        await manager.send_error(message_id, 500, str(e), websocket)

async def handle_github_pull_requests(message_id: str, params: Dict[str, Any], websocket: WebSocket):
    """
    Manage GitHub pull requests
    Params:
      - action: "list", "get", "create", "update", "merge"
      - repo: Repository name (format: owner/repo)
      - number: PR number (required for get, update, merge)
      - title: PR title (required for create)
      - body: PR description
      - head: Source branch (required for create)
      - base: Target branch (required for create)
      - draft: Whether to create as draft PR (boolean)
      - state: PR state ("open" or "closed") for updating
      - mergeMethod: Merge method ("merge", "squash", "rebase") for merge action
    """
    action = params.get("action", "").lower()
    repo = params.get("repo", "")
    pr_number = params.get("number")
    title = params.get("title", "")
    body = params.get("body", "")
    head = params.get("head", "")
    base = params.get("base", "")
    draft = params.get("draft", False)
    state = params.get("state", "")
    merge_method = params.get("mergeMethod", "merge")
    
    if not repo:
        await manager.send_error(message_id, 400, "Repository name is required", websocket)
        return
    
    if not action:
        await manager.send_error(message_id, 400, "Action is required", websocket)
        return
    
    # Get stored GitHub token
    token = await get_github_token()
    if not token:
        await manager.send_error(message_id, 401, "GitHub token not found. Please authenticate first.", websocket)
        return
    
    try:
        headers = {
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github.v3+json"
        }
        
        if action == "list":
            # List pull requests in the repository
            url = f"{GITHUB_API_BASE}/repos/{repo}/pulls"
            params = {
                "state": "all",
                "per_page": 100
            }
            
            response = requests.get(url, headers=headers, params=params)
            
            if response.status_code == 200:
                pull_requests = response.json()
                result = {
                    "repo": repo,
                    "pullRequestCount": len(pull_requests),
                    "pullRequests": []
                }
                
                for pr in pull_requests:
                    pr_info = {
                        "number": pr.get("number"),
                        "title": pr.get("title"),
                        "state": pr.get("state"),
                        "draft": pr.get("draft", False),
                        "createdAt": pr.get("created_at"),
                        "updatedAt": pr.get("updated_at"),
                        "closedAt": pr.get("closed_at"),
                        "mergedAt": pr.get("merged_at"),
                        "url": pr.get("html_url"),
                        "user": {
                            "login": pr.get("user", {}).get("login"),
                            "avatarUrl": pr.get("user", {}).get("avatar_url")
                        },
                        "head": pr.get("head", {}).get("ref"),
                        "base": pr.get("base", {}).get("ref")
                    }
                    
                    result["pullRequests"].append(pr_info)
                
                await manager.send_response(message_id, result, websocket)
            
            else:
                await manager.send_error(
                    message_id,
                    response.status_code,
                    f"GitHub API error: {response.text}",
                    websocket
                )
        
        elif action == "get":
            if not pr_number:
                await manager.send_error(message_id, 400, "Pull request number is required", websocket)
                return
            
            # Get a specific pull request
            url = f"{GITHUB_API_BASE}/repos/{repo}/pulls/{pr_number}"
            response = requests.get(url, headers=headers)
            
            if response.status_code == 200:
                pr = response.json()
                
                # Get PR reviews
                reviews_url = f"{GITHUB_API_BASE}/repos/{repo}/pulls/{pr_number}/reviews"
                reviews_response = requests.get(reviews_url, headers=headers)
                reviews = reviews_response.json() if reviews_response.status_code == 200 else []
                
                # Get PR comments
                comments_url = f"{GITHUB_API_BASE}/repos/{repo}/pulls/{pr_number}/comments"
                comments_response = requests.get(comments_url, headers=headers)
                comments = comments_response.json() if comments_response.status_code == 200 else []
                
                # Get PR files
                files_url = f"{GITHUB_API_BASE}/repos/{repo}/pulls/{pr_number}/files"
                files_response = requests.get(files_url, headers=headers)
                files = files_response.json() if files_response.status_code == 200 else []
                
                result = {
                    "repo": repo,
                    "number": pr.get("number"),
                    "title": pr.get("title"),
                    "body": pr.get("body"),
                    "state": pr.get("state"),
                    "draft": pr.get("draft", False),
                    "merged": pr.get("merged", False),
                    "mergeable": pr.get("mergeable"),
                    "createdAt": pr.get("created_at"),
                    "updatedAt": pr.get("updated_at"),
                    "closedAt": pr.get("closed_at"),
                    "mergedAt": pr.get("merged_at"),
                    "url": pr.get("html_url"),
                    "user": {
                        "login": pr.get("user", {}).get("login"),
                        "avatarUrl": pr.get("user", {}).get("avatar_url")
                    },
                    "head": {
                        "ref": pr.get("head", {}).get("ref"),
                        "sha": pr.get("head", {}).get("sha"),
                        "repo": pr.get("head", {}).get("repo", {}).get("full_name")
                    },
                    "base": {
                        "ref": pr.get("base", {}).get("ref"),
                        "sha": pr.get("base", {}).get("sha"),
                        "repo": pr.get("base", {}).get("repo", {}).get("full_name")
                    },
                    "reviews": [],
                    "comments": [],
                    "files": []
                }
                
                # Process reviews
                for review in reviews:
                    review_info = {
                        "id": review.get("id"),
                        "state": review.get("state"),
                        "body": review.get("body"),
                        "submittedAt": review.get("submitted_at"),
                        "user": {
                            "login": review.get("user", {}).get("login"),
                            "avatarUrl": review.get("user", {}).get("avatar_url")
                        }
                    }
                    
                    result["reviews"].append(review_info)
                
                # Process comments
                for comment in comments:
                    comment_info = {
                        "id": comment.get("id"),
                        "body": comment.get("body"),
                        "path": comment.get("path"),
                        "position": comment.get("position"),
                        "createdAt": comment.get("created_at"),
                        "updatedAt": comment.get("updated_at"),
                        "user": {
                            "login": comment.get("user", {}).get("login"),
                            "avatarUrl": comment.get("user", {}).get("avatar_url")
                        }
                    }
                    
                    result["comments"].append(comment_info)
                
                # Process files
                for file in files:
                    file_info = {
                        "filename": file.get("filename"),
                        "status": file.get("status"),
                        "additions": file.get("additions"),
                        "deletions": file.get("deletions"),
                        "changes": file.get("changes"),
                        "patch": file.get("patch")
                    }
                    
                    result["files"].append(file_info)
                
                await manager.send_response(message_id, result, websocket)
            
            else:
                await manager.send_error(
                    message_id,
                    response.status_code,
                    f"GitHub API error: {response.text}",
                    websocket
                )
        
        elif action == "create":
            if not title:
                await manager.send_error(message_id, 400, "Pull request title is required", websocket)
                return
            
            if not head:
                await manager.send_error(message_id, 400, "Source branch (head) is required", websocket)
                return
            
            if not base:
                await manager.send_error(message_id, 400, "Target branch (base) is required", websocket)
                return
            
            # Create a new pull request
            url = f"{GITHUB_API_BASE}/repos/{repo}/pulls"
            data = {
                "title": title,
                "body": body,
                "head": head,
                "base": base,
                "draft": draft
            }
            
            response = requests.post(url, headers=headers, json=data)
            
            if response.status_code == 201:
                pr = response.json()
                
                result = {
                    "success": True,
                    "repo": repo,
                    "number": pr.get("number"),
                    "title": pr.get("title"),
                    "url": pr.get("html_url")
                }
                
                await manager.send_response(message_id, result, websocket)
            
            else:
                await manager.send_error(
                    message_id,
                    response.status_code,
                    f"GitHub API error: {response.text}",
                    websocket
                )
        
        elif action == "update":
            if not pr_number:
                await manager.send_error(message_id, 400, "Pull request number is required", websocket)
                return
            
            # Update an existing pull request
            url = f"{GITHUB_API_BASE}/repos/{repo}/pulls/{pr_number}"
            data = {}
            
            if title:
                data["title"] = title
            
            if body:
                data["body"] = body
            
            if state:
                data["state"] = state
            
            if base:
                data["base"] = base
            
            response = requests.patch(url, headers=headers, json=data)
            
            if response.status_code == 200:
                pr = response.json()
                
                result = {
                    "success": True,
                    "repo": repo,
                    "number": pr.get("number"),
                    "title": pr.get("title"),
                    "state": pr.get("state"),
                    "url": pr.get("html_url")
                }
                
                await manager.send_response(message_id, result, websocket)
            
            else:
                await manager.send_error(
                    message_id,
                    response.status_code,
                    f"GitHub API error: {response.text}",
                    websocket
                )
        
        elif action == "merge":
            if not pr_number:
                await manager.send_error(message_id, 400, "Pull request number is required", websocket)
                return
            
            # Merge a pull request
            url = f"{GITHUB_API_BASE}/repos/{repo}/pulls/{pr_number}/merge"
            data = {
                "merge_method": merge_method
            }
            
            response = requests.put(url, headers=headers, json=data)
            
            if response.status_code == 200:
                result = {
                    "success": True,
                    "repo": repo,
                    "number": pr_number,
                    "merged": True,
                    "mergeMethod": merge_method
                }
                
                await manager.send_response(message_id, result, websocket)
            
            else:
                await manager.send_error(
                    message_id,
                    response.status_code,
                    f"GitHub API error: {response.text}",
                    websocket
                )
        
        else:
            await manager.send_error(message_id, 400, f"Unknown action: {action}", websocket)
    
    except Exception as e:
        await manager.send_error(message_id, 500, str(e), websocket)

async def handle_github_code_search(message_id: str, params: Dict[str, Any], websocket: WebSocket):
    """
    Search for code in GitHub repositories
    Params:
      - query: Search query string
      - repo: Optional specific repository to search (format: owner/repo)
      - language: Optional language filter
      - perPage: Number of results per page (default: 30, max: 100)
      - page: Page number for pagination (default: 1)
    """
    query = params.get("query", "")
    repo = params.get("repo", "")
    language = params.get("language", "")
    per_page = min(int(params.get("perPage", 30)), 100)
    page = int(params.get("page", 1))
    
    if not query:
        await manager.send_error(message_id, 400, "Search query is required", websocket)
        return
    
    # Get stored GitHub token
    token = await get_github_token()
    if not token:
        await manager.send_error(message_id, 401, "GitHub token not found. Please authenticate first.", websocket)
        return
    
    try:
        headers = {
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github.v3+json"
        }
        
        # Build the search query
        search_query = query
        
        if repo:
            search_query += f" repo:{repo}"
        
        if language:
            search_query += f" language:{language}"
        
        # Send the search request
        url = f"{GITHUB_API_BASE}/search/code"
        params = {
            "q": search_query,
            "per_page": per_page,
            "page": page
        }
        
        response = requests.get(url, headers=headers, params=params)
        
        if response.status_code == 200:
            data = response.json()
            
            result = {
                "query": search_query,
                "totalCount": data.get("total_count", 0),
                "page": page,
                "perPage": per_page,
                "items": []
            }
            
            for item in data.get("items", []):
                # Get the file content
                content_url = item.get("url")
                content_response = requests.get(content_url, headers=headers)
                content = None
                
                if content_response.status_code == 200:
                    content_data = content_response.json()
                    if content_data.get("encoding") == "base64" and content_data.get("content"):
                        try:
                            content = base64.b64decode(content_data.get("content")).decode("utf-8")
                        except:
                            content = "Binary content (could not decode)"
                
                item_info = {
                    "name": item.get("name"),
                    "path": item.get("path"),
                    "repository": {
                        "name": item.get("repository", {}).get("name"),
                        "fullName": item.get("repository", {}).get("full_name"),
                        "url": item.get("repository", {}).get("html_url")
                    },
                    "url": item.get("html_url"),
                    "content": content
                }
                
                result["items"].append(item_info)
            
            await manager.send_response(message_id, result, websocket)
        
        else:
            await manager.send_error(
                message_id,
                response.status_code,
                f"GitHub API error: {response.text}",
                websocket
            )
    
    except Exception as e:
        await manager.send_error(message_id, 500, str(e), websocket)

async def handle_github_clone(message_id: str, params: Dict[str, Any], websocket: WebSocket):
    """
    Clone a GitHub repository locally
    Params:
      - repo: Repository name (format: owner/repo)
      - path: Local path where to clone the repository
      - branch: Branch to checkout after cloning (default: default branch)
      - depth: Depth for shallow clone (optional)
    """
    repo = params.get("repo", "")
    path = params.get("path", "")
    branch = params.get("branch", "")
    depth = params.get("depth")
    
    if not repo:
        await manager.send_error(message_id, 400, "Repository name is required", websocket)
        return
    
    # Default to current directory if path not provided
    if not path:
        path = os.getcwd()
    
    try:
        # Construct the clone command
        clone_url = f"https://github.com/{repo}.git"
        clone_cmd = f"git clone {clone_url}"
        
        # Add depth parameter if provided
        if depth:
            clone_cmd += f" --depth {depth}"
        
        # Add path parameter
        clone_cmd += f" {path}"
        
        # Execute the clone command
        clone_process = await asyncio.create_subprocess_shell(
            clone_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await clone_process.communicate()
        
        # Check if clone was successful
        if clone_process.returncode == 0:
            result = {
                "success": True,
                "repo": repo,
                "path": path,
                "output": stdout.decode() if stdout else ""
            }
            
            # If a specific branch is requested, checkout that branch
            if branch:
                repo_dir = os.path.join(path, repo.split("/")[1])
                checkout_cmd = f"cd {repo_dir} && git checkout {branch}"
                
                checkout_process = await asyncio.create_subprocess_shell(
                    checkout_cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                checkout_stdout, checkout_stderr = await checkout_process.communicate()
                
                result["checkoutSuccess"] = checkout_process.returncode == 0
                result["checkoutOutput"] = checkout_stdout.decode() if checkout_stdout else ""
                result["checkoutError"] = checkout_stderr.decode() if checkout_stderr else ""
            
            await manager.send_response(message_id, result, websocket)
        
        else:
            await manager.send_error(
                message_id,
                500,
                f"Git clone failed: {stderr.decode() if stderr else 'Unknown error'}",
                websocket
            )
    
    except Exception as e:
        await manager.send_error(message_id, 500, str(e), websocket)

async def handle_github_commits(message_id: str, params: Dict[str, Any], websocket: WebSocket):
    """
    Get commit history for a repository
    Params:
      - repo: Repository name (format: owner/repo)
      - branch: Branch name (default: default branch)
      - path: File path to get history for a specific file (optional)
      - since: ISO 8601 date to filter commits after this date
      - until: ISO 8601 date to filter commits before this date
      - perPage: Number of results per page (default: 30, max: 100)
      - page: Page number for pagination (default: 1)
    """
    repo = params.get("repo", "")
    branch = params.get("branch", "")
    path = params.get("path", "")
    since = params.get("since", "")
    until = params.get("until", "")
    per_page = min(int(params.get("perPage", 30)), 100)
    page = int(params.get("page", 1))
    
    if not repo:
        await manager.send_error(message_id, 400, "Repository name is required", websocket)
        return
    
    # Get stored GitHub token
    token = await get_github_token()
    if not token:
        await manager.send_error(message_id, 401, "GitHub token not found. Please authenticate first.", websocket)
        return
    
    try:
        headers = {
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github.v3+json"
        }
        
        # Construct the API URL
        url = f"{GITHUB_API_BASE}/repos/{repo}/commits"
        request_params = {
            "per_page": per_page,
            "page": page
        }
        
        if branch:
            request_params["sha"] = branch
        
        if path:
            request_params["path"] = path
        
        if since:
            request_params["since"] = since
        
        if until:
            request_params["until"] = until
        
        response = requests.get(url, headers=headers, params=request_params)
        
        if response.status_code == 200:
            commits = response.json()
            
            result = {
                "repo": repo,
                "branch": branch if branch else "default",
                "path": path if path else "root",
                "page": page,
                "perPage": per_page,
                "commits": []
            }
            
            for commit in commits:
                commit_info = {
                    "sha": commit.get("sha"),
                    "url": commit.get("html_url"),
                    "message": commit.get("commit", {}).get("message", ""),
                    "author": {
                        "name": commit.get("commit", {}).get("author", {}).get("name"),
                        "email": commit.get("commit", {}).get("author", {}).get("email"),
                        "date": commit.get("commit", {}).get("author", {}).get("date")
                    },
                    "committer": {
                        "name": commit.get("commit", {}).get("committer", {}).get("name"),
                        "email": commit.get("commit", {}).get("committer", {}).get("email"),
                        "date": commit.get("commit", {}).get("committer", {}).get("date")
                    }
                }
                
                # Add GitHub user info if available
                if commit.get("author"):
                    commit_info["author"]["username"] = commit.get("author", {}).get("login")
                    commit_info["author"]["avatarUrl"] = commit.get("author", {}).get("avatar_url")
                
                result["commits"].append(commit_info)
            
            # Add pagination info if available
            if "Link" in response.headers:
                pagination = {}
                link_header = response.headers["Link"]
                links = link_header.split(",")
                
                for link in links:
                    match = re.search(r'<([^>]+)>;\s*rel="([^"]+)"', link)
                    if match:
                        url, rel = match.groups()
                        pagination[rel] = url
                
                result["pagination"] = pagination
            
            await manager.send_response(message_id, result, websocket)
        
        else:
            await manager.send_error(
                message_id,
                response.status_code,
                f"GitHub API error: {response.text}",
                websocket
            )
    
    except Exception as e:
        await manager.send_error(message_id, 500, str(e), websocket)

async def handle_github_gists(message_id: str, params: Dict[str, Any], websocket: WebSocket):
    """
    Manage GitHub Gists
    Params:
      - action: "list", "get", "create", "update", "delete"
      - gistId: Gist ID (required for get, update, delete)
      - description: Gist description
      - public: Whether the gist is public (boolean)
      - files: Object mapping filenames to content
    """
    action = params.get("action", "").lower()
    gist_id = params.get("gistId", "")
    description = params.get("description", "")
    public = params.get("public", True)
    files = params.get("files", {})
    
    if not action:
        await manager.send_error(message_id, 400, "Action is required", websocket)
        return
    
    # Get stored GitHub token
    token = await get_github_token()
    if not token:
        await manager.send_error(message_id, 401, "GitHub token not found. Please authenticate first.", websocket)
        return
    
    try:
        headers = {
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github.v3+json"
        }
        
        if action == "list":
            # List user's gists
            url = f"{GITHUB_API_BASE}/gists"
            response = requests.get(url, headers=headers)
            
            if response.status_code == 200:
                gists = response.json()
                
                result = {
                    "gistCount": len(gists),
                    "gists": []
                }
                
                for gist in gists:
                    gist_info = {
                        "id": gist.get("id"),
                        "description": gist.get("description"),
                        "public": gist.get("public"),
                        "createdAt": gist.get("created_at"),
                        "updatedAt": gist.get("updated_at"),
                        "url": gist.get("html_url"),
                        "files": list(gist.get("files", {}).keys())
                    }
                    
                    result["gists"].append(gist_info)
                
                await manager.send_response(message_id, result, websocket)
            
            else:
                await manager.send_error(
                    message_id,
                    response.status_code,
                    f"GitHub API error: {response.text}",
                    websocket
                )
        
        elif action == "get":
            if not gist_id:
                await manager.send_error(message_id, 400, "Gist ID is required", websocket)
                return
            
            # Get a specific gist
            url = f"{GITHUB_API_BASE}/gists/{gist_id}"
            response = requests.get(url, headers=headers)
            
            if response.status_code == 200:
                gist = response.json()
                
                files_content = {}
                for filename, file_info in gist.get("files", {}).items():
                    files_content[filename] = {
                        "content": file_info.get("content"),
                        "language": file_info.get("language"),
                        "size": file_info.get("size")
                    }
                
                result = {
                    "id": gist.get("id"),
                    "description": gist.get("description"),
                    "public": gist.get("public"),
                    "createdAt": gist.get("created_at"),
                    "updatedAt": gist.get("updated_at"),
                    "url": gist.get("html_url"),
                    "files": files_content
                }
                
                await manager.send_response(message_id, result, websocket)
            
            else:
                await manager.send_error(
                    message_id,
                    response.status_code,
                    f"GitHub API error: {response.text}",
                    websocket
                )
        
        elif action == "create":
            if not files:
                await manager.send_error(message_id, 400, "At least one file is required", websocket)
                return
            
            # Create a new gist
            url = f"{GITHUB_API_BASE}/gists"
            
            # Format the files data
            formatted_files = {}
            for filename, content in files.items():
                if isinstance(content, dict) and "content" in content:
                    formatted_files[filename] = {"content": content["content"]}
                else:
                    formatted_files[filename] = {"content": content}
            
            data = {
                "description": description,
                "public": public,
                "files": formatted_files
            }
            
            response = requests.post(url, headers=headers, json=data)
            
            if response.status_code == 201:
                gist = response.json()
                
                result = {
                    "success": True,
                    "id": gist.get("id"),
                    "url": gist.get("html_url"),
                    "description": gist.get("description"),
                    "public": gist.get("public")
                }
                
                await manager.send_response(message_id, result, websocket)
            
            else:
                await manager.send_error(
                    message_id,
                    response.status_code,
                    f"GitHub API error: {response.text}",
                    websocket
                )
        
        elif action == "update":
            if not gist_id:
                await manager.send_error(message_id, 400, "Gist ID is required", websocket)
                return
            
            # Update an existing gist
            url = f"{GITHUB_API_BASE}/gists/{gist_id}"
            data = {}
            
            if description:
                data["description"] = description
            
            if files:
                # Format the files data
                formatted_files = {}
                for filename, content in files.items():
                    if isinstance(content, dict):
                        if "content" in content:
                            formatted_files[filename] = {"content": content["content"]}
                        elif "delete" in content and content["delete"]:
                            # To delete a file, set its content to null
                            formatted_files[filename] = None
                    else:
                        formatted_files[filename] = {"content": content}
                
                data["files"] = formatted_files
            
            response = requests.patch(url, headers=headers, json=data)
            
            if response.status_code == 200:
                gist = response.json()
                
                result = {
                    "success": True,
                    "id": gist.get("id"),
                    "url": gist.get("html_url"),
                    "description": gist.get("description"),
                    "updatedAt": gist.get("updated_at")
                }
                
                await manager.send_response(message_id, result, websocket)
            
            else:
                await manager.send_error(
                    message_id,
                    response.status_code,
                    f"GitHub API error: {response.text}",
                    websocket
                )
        
        elif action == "delete":
            if not gist_id:
                await manager.send_error(message_id, 400, "Gist ID is required", websocket)
                return
            
            # Delete a gist
            url = f"{GITHUB_API_BASE}/gists/{gist_id}"
            response = requests.delete(url, headers=headers)
            
            if response.status_code == 204:
                result = {
                    "success": True,
                    "id": gist_id,
                    "deleted": True
                }
                
                await manager.send_response(message_id, result, websocket)
            
            else:
                await manager.send_error(
                    message_id,
                    response.status_code,
                    f"GitHub API error: {response.text}",
                    websocket
                )
        
        else:
            await manager.send_error(message_id, 400, f"Unknown action: {action}", websocket)
    
    except Exception as e:
        await manager.send_error(message_id, 500, str(e), websocket)

# Register GitHub methods
GITHUB_HANDLERS = {
    "githubAuth": handle_github_auth,
    "githubRepos": handle_github_repos,
    "githubRepoContent": handle_github_repo_content,
    "githubIssues": handle_github_issues,
    "githubPullRequests": handle_github_pull_requests,
    "githubCodeSearch": handle_github_code_search,
    "githubClone": handle_github_clone,
    "githubCommits": handle_github_commits,
    "githubGists": handle_github_gists,
}

# Update the METHOD_HANDLERS dictionary
from src.main import METHOD_HANDLERS
METHOD_HANDLERS.update(GITHUB_HANDLERS)

# Make this runnable as a standalone server too
if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8005))
    host = os.environ.get("HOST", "0.0.0.0")
    print(f"Starting GitHub MCP Server on {host}:{port}")
    print(f"Available methods: {', '.join(GITHUB_HANDLERS.keys())}")
    uvicorn.run(app, host=host, port=port)