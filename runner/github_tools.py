"""
GitHub integration tools for repository management, issues, and content creation.

Provides capabilities for:
- Creating and managing repositories
- Creating, reading, and updating issues
- Reading and writing files
- Managing pull requests
- Searching repositories
"""
from __future__ import annotations

import json
import os
import base64
from typing import Any, Optional, Dict, List
from dataclasses import dataclass, asdict
from urllib.parse import quote_plus

# GitHub configuration
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GITHUB_API_BASE = os.environ.get("GITHUB_API_BASE", "https://api.github.com")
GITHUB_USERNAME = os.environ.get("GITHUB_USERNAME", "")


def _get_headers() -> Dict[str, str]:
    """Get authentication headers for GitHub API."""
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "OpenClaw-Bot/1.0",
    }
    if GITHUB_TOKEN:
        headers["Authorization"] = f"token {GITHUB_TOKEN}"
    return headers


def _make_request(method: str, endpoint: str, data: Optional[Dict] = None) -> tuple[bool, Any]:
    """Make a request to the GitHub API."""
    try:
        import urllib.request
        import urllib.error
        
        url = f"{GITHUB_API_BASE}/{endpoint.lstrip('/')}"
        headers = _get_headers()
        
        if data is not None:
            body = json.dumps(data).encode('utf-8')
            headers["Content-Type"] = "application/json"
        else:
            body = None
        
        req = urllib.request.Request(
            url,
            data=body,
            headers=headers,
            method=method
        )
        
        with urllib.request.urlopen(req, timeout=30) as response:
            response_data = response.read().decode('utf-8')
            if response_data:
                return True, json.loads(response_data)
            return True, {}
            
    except urllib.error.HTTPError as e:
        raw = e.read()
        error_body = raw.decode('utf-8') if raw else str(e)
        return False, {"error": error_body, "status": e.code}
    except Exception as e:
        return False, {"error": str(e)}


def github_create_repo(name: str, description: str = "", private: bool = False,
                       auto_init: bool = True, gitignore_template: str = "") -> str:
    """
    Create a new GitHub repository.
    
    Args:
        name: Repository name
        description: Repository description
        private: Whether the repo should be private
        auto_init: Initialize with README
        gitignore_template: Gitignore template (e.g., 'Python', 'Node')
    
    Returns:
        JSON string with result
    """
    if not GITHUB_TOKEN:
        return json.dumps({
            "success": False,
            "error": "GITHUB_TOKEN not configured"
        })
    
    data = {
        "name": name,
        "description": description,
        "private": private,
        "auto_init": auto_init,
    }
    
    if gitignore_template:
        data["gitignore_template"] = gitignore_template
    
    success, result = _make_request("POST", "/user/repos", data)
    
    if success:
        return json.dumps({
            "success": True,
            "message": f"Repository '{name}' created successfully",
            "repo_name": result.get("name"),
            "html_url": result.get("html_url"),
            "clone_url": result.get("clone_url"),
            "private": result.get("private"),
        }, indent=2)
    else:
        return json.dumps({
            "success": False,
            "error": result.get("error", "Unknown error"),
            "message": f"Failed to create repository '{name}'"
        })


def github_list_repos(type_filter: str = "owner", sort: str = "updated", 
                      limit: int = 30) -> str:
    """
    List repositories for the authenticated user.
    
    Args:
        type_filter: all, owner, member
        sort: created, updated, pushed, full_name
        limit: Maximum number of repos to return
    
    Returns:
        JSON string with repository list
    """
    if not GITHUB_TOKEN:
        return json.dumps({
            "success": False,
            "error": "GITHUB_TOKEN not configured"
        })
    
    endpoint = f"/user/repos?type={type_filter}&sort={sort}&per_page={min(limit, 100)}"
    success, result = _make_request("GET", endpoint)
    
    if success and isinstance(result, list):
        repos = [
            {
                "name": r.get("name"),
                "description": r.get("description"),
                "html_url": r.get("html_url"),
                "private": r.get("private"),
                "updated_at": r.get("updated_at"),
                "stargazers_count": r.get("stargazers_count", 0),
            }
            for r in result[:limit]
        ]
        return json.dumps({
            "success": True,
            "count": len(repos),
            "repositories": repos
        }, indent=2)
    else:
        return json.dumps({
            "success": False,
            "error": result.get("error", "Unknown error") if isinstance(result, dict) else str(result)
        })


def github_create_issue(repo: str, title: str, body: str = "",
                       labels: Optional[List[str]] = None) -> str:
    """
    Create an issue in a repository.
    
    Args:
        repo: Repository in format "owner/repo"
        title: Issue title
        body: Issue body/description
        labels: List of label names
    
    Returns:
        JSON string with result
    """
    if not GITHUB_TOKEN:
        return json.dumps({
            "success": False,
            "error": "GITHUB_TOKEN not configured"
        })
    
    data = {
        "title": title,
        "body": body,
    }
    
    if labels:
        data["labels"] = labels
    
    success, result = _make_request("POST", f"/repos/{repo}/issues", data)
    
    if success:
        return json.dumps({
            "success": True,
            "message": f"Issue created in {repo}",
            "issue_number": result.get("number"),
            "issue_url": result.get("html_url"),
            "title": result.get("title"),
        }, indent=2)
    else:
        return json.dumps({
            "success": False,
            "error": result.get("error", "Unknown error"),
            "message": f"Failed to create issue in {repo}"
        })


def github_list_issues(repo: str, state: str = "open", limit: int = 30) -> str:
    """
    List issues in a repository.
    
    Args:
        repo: Repository in format "owner/repo"
        state: open, closed, all
        limit: Maximum number of issues to return
    
    Returns:
        JSON string with issue list
    """
    endpoint = f"/repos/{repo}/issues?state={state}&per_page={min(limit, 100)}"
    success, result = _make_request("GET", endpoint)
    
    if success and isinstance(result, list):
        # Filter out pull requests (GitHub returns PRs as issues too)
        issues = [
            {
                "number": i.get("number"),
                "title": i.get("title"),
                "state": i.get("state"),
                "html_url": i.get("html_url"),
                "created_at": i.get("created_at"),
                "user": i.get("user", {}).get("login"),
                "labels": [l.get("name") for l in i.get("labels", [])],
            }
            for i in result[:limit]
            if "pull_request" not in i  # Skip PRs
        ]
        return json.dumps({
            "success": True,
            "count": len(issues),
            "issues": issues
        }, indent=2)
    else:
        return json.dumps({
            "success": False,
            "error": result.get("error", "Unknown error") if isinstance(result, dict) else str(result)
        })


def github_read_file(repo: str, path: str, ref: str = "main") -> str:
    """
    Read a file from a repository.
    
    Args:
        repo: Repository in format "owner/repo"
        path: File path within the repo
        ref: Branch, tag, or commit SHA
    
    Returns:
        JSON string with file content
    """
    endpoint = f"/repos/{repo}/contents/{path}?ref={ref}"
    success, result = _make_request("GET", endpoint)
    
    if success:
        content = result.get("content", "")
        encoding = result.get("encoding", "")
        
        # Decode base64 content
        if encoding == "base64" and content:
            try:
                decoded = base64.b64decode(content).decode('utf-8')
            except Exception:
                decoded = "[Binary content - not decoded]"
        else:
            decoded = content
        
        return json.dumps({
            "success": True,
            "path": result.get("path"),
            "name": result.get("name"),
            "size": result.get("size"),
            "html_url": result.get("html_url"),
            "content": decoded,
            "encoding": encoding,
        }, indent=2)
    else:
        return json.dumps({
            "success": False,
            "error": result.get("error", "Unknown error"),
            "message": f"Failed to read {path} from {repo}"
        })


def github_write_file(repo: str, path: str, content: str, message: str,
                     branch: str = "main", sha: Optional[str] = None) -> str:
    """
    Create or update a file in a repository.
    
    Args:
        repo: Repository in format "owner/repo"
        path: File path within the repo
        content: File content (plain text)
        message: Commit message
        branch: Target branch
        sha: Required for updates - SHA of existing file
    
    Returns:
        JSON string with result
    """
    if not GITHUB_TOKEN:
        return json.dumps({
            "success": False,
            "error": "GITHUB_TOKEN not configured"
        })
    
    # Encode content to base64
    encoded = base64.b64encode(content.encode('utf-8')).decode('utf-8')
    
    data = {
        "message": message,
        "content": encoded,
        "branch": branch,
    }
    
    if sha:
        data["sha"] = sha
    
    success, result = _make_request("PUT", f"/repos/{repo}/contents/{path}", data)
    
    if success:
        commit = result.get("commit", {})
        return json.dumps({
            "success": True,
            "message": f"File '{path}' {'updated' if sha else 'created'} in {repo}",
            "commit_sha": commit.get("sha"),
            "commit_url": commit.get("html_url"),
            "content_sha": result.get("content", {}).get("sha"),
        }, indent=2)
    else:
        return json.dumps({
            "success": False,
            "error": result.get("error", "Unknown error"),
            "message": f"Failed to write {path} to {repo}"
        })


def github_search_repos(query: str, sort: str = "stars", 
                       order: str = "desc", limit: int = 30) -> str:
    """
    Search for repositories on GitHub.
    
    Args:
        query: Search query (can include qualifiers like language:python)
        sort: stars, forks, updated
        order: desc, asc
        limit: Maximum number of results
    
    Returns:
        JSON string with search results
    """
    endpoint = f"/search/repositories?q={quote_plus(query)}&sort={sort}&order={order}&per_page={min(limit, 100)}"
    success, result = _make_request("GET", endpoint)
    
    if success:
        items = result.get("items", [])
        repos = [
            {
                "name": r.get("name"),
                "full_name": r.get("full_name"),
                "description": r.get("description"),
                "html_url": r.get("html_url"),
                "stargazers_count": r.get("stargazers_count", 0),
                "language": r.get("language"),
                "updated_at": r.get("updated_at"),
            }
            for r in items[:limit]
        ]
        return json.dumps({
            "success": True,
            "total_count": result.get("total_count", 0),
            "count": len(repos),
            "repositories": repos
        }, indent=2)
    else:
        return json.dumps({
            "success": False,
            "error": result.get("error", "Unknown error")
        })


def github_search_code(query: str, limit: int = 30) -> str:
    """
    Search for code on GitHub.
    
    Args:
        query: Search query (can include qualifiers like repo:owner/name, language:python)
        limit: Maximum number of results
    
    Returns:
        JSON string with search results
    """
    endpoint = f"/search/code?q={quote_plus(query)}&per_page={min(limit, 100)}"
    success, result = _make_request("GET", endpoint)
    
    if success:
        items = result.get("items", [])
        code_items = [
            {
                "name": item.get("name"),
                "path": item.get("path"),
                "repository": item.get("repository", {}).get("full_name"),
                "html_url": item.get("html_url"),
            }
            for item in items[:limit]
        ]
        return json.dumps({
            "success": True,
            "total_count": result.get("total_count", 0),
            "count": len(code_items),
            "results": code_items
        }, indent=2)
    else:
        return json.dumps({
            "success": False,
            "error": result.get("error", "Unknown error")
        })


def github_get_user(username: Optional[str] = None) -> str:
    """
    Get GitHub user information.
    
    Args:
        username: GitHub username (if None, gets authenticated user)
    
    Returns:
        JSON string with user information
    """
    if username:
        endpoint = f"/users/{username}"
    else:
        if not GITHUB_TOKEN:
            return json.dumps({
                "success": False,
                "error": "GITHUB_TOKEN required to get authenticated user"
            })
        endpoint = "/user"
    
    success, result = _make_request("GET", endpoint)
    
    if success:
        return json.dumps({
            "success": True,
            "login": result.get("login"),
            "name": result.get("name"),
            "bio": result.get("bio"),
            "public_repos": result.get("public_repos"),
            "followers": result.get("followers"),
            "following": result.get("following"),
            "html_url": result.get("html_url"),
            "created_at": result.get("created_at"),
        }, indent=2)
    else:
        return json.dumps({
            "success": False,
            "error": result.get("error", "Unknown error")
        })


def get_github_capabilities() -> list[str]:
    """Return list of GitHub-related capabilities."""
    return [
        "github_create_repo",
        "github_list_repos",
        "github_create_issue",
        "github_list_issues",
        "github_read_file",
        "github_write_file",
        "github_search_repos",
        "github_search_code",
        "github_get_user",
    ]
