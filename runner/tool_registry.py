"""
Tool registry and dispatcher for LLM tool-calling (Sprint 5). OpenAI function-calling schema; dispatch to runner helpers.
"""
from __future__ import annotations

import json
import re
from typing import Any, Optional

# URL-like pattern: reject strings that could be used for SSRF (Sprint 3)
_URL_LIKE_RE = re.compile(
    r"^(https?|file|ftp|data)\s*:\s*//",
    re.IGNORECASE,
)


def reject_url_like_input(s: str, field_name: str = "input") -> None:
    """
    Raise ValueError if string looks like a URL. Prevents accidental SSRF via tool args.
    """
    if not s or not isinstance(s, str):
        return
    stripped = s.strip()
    if _URL_LIKE_RE.search(stripped):
        raise ValueError(f"{field_name} must not be a URL")


# OpenAI-style tool definitions (function name, description, parameters schema)
TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "repo_list",
            "description": "List allowlisted git repos available on the runner.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "repo_status",
            "description": "Get git status (branch, dirty, porcelain) for a repo.",
            "parameters": {
                "type": "object",
                "properties": {"repo": {"type": "string", "description": "Repo name from allowlist"}},
                "required": ["repo"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "repo_last_commit",
            "description": "Get last commit hash, author, date, subject for a repo.",
            "parameters": {
                "type": "object",
                "properties": {"repo": {"type": "string", "description": "Repo name from allowlist"}},
                "required": ["repo"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "repo_grep",
            "description": "Search for a query in a repo (ripgrep or git grep).",
            "parameters": {
                "type": "object",
                "properties": {
                    "repo": {"type": "string", "description": "Repo name from allowlist"},
                    "query": {"type": "string", "description": "Search query"},
                    "path": {"type": "string", "description": "Optional path prefix to limit search"},
                },
                "required": ["repo", "query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "repo_readfile",
            "description": "Read a file in a repo by path and line range.",
            "parameters": {
                "type": "object",
                "properties": {
                    "repo": {"type": "string", "description": "Repo name from allowlist"},
                    "path": {"type": "string", "description": "Relative path within repo"},
                    "start_line": {"type": "integer", "description": "First line (1-based)", "default": 1},
                    "end_line": {"type": "integer", "description": "Last line (inclusive)", "default": 200},
                },
                "required": ["repo", "path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "plan_echo",
            "description": "Create a plan (echo scaffold) with the given text; returns plan_id for approve.",
            "parameters": {
                "type": "object",
                "properties": {"text": {"type": "string", "description": "Plan summary or description"}},
                "required": ["text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "approve_echo",
            "description": "Approve a plan by plan_id (echo scaffold).",
            "parameters": {
                "type": "object",
                "properties": {"plan_id": {"type": "string", "description": "Plan ID from plan_echo"}},
                "required": ["plan_id"],
            },
        },
    },
    # Browser/Web tools
    {
        "type": "function",
        "function": {
            "name": "browser_navigate",
            "description": "Navigate to a URL in the browser. Creates a browser session if needed.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "URL to navigate to (can be partial, will add https:// if needed)"},
                    "wait_for_load": {"type": "boolean", "description": "Wait for page to fully load", "default": True},
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_snapshot",
            "description": "Take a snapshot of the current page including content, links, forms, and interactive elements.",
            "parameters": {
                "type": "object",
                "properties": {
                    "full_content": {"type": "boolean", "description": "Include full page content", "default": True},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_click",
            "description": "Click an element on the page by reference number or CSS selector.",
            "parameters": {
                "type": "object",
                "properties": {
                    "ref": {"type": "integer", "description": "Reference number from browser_snapshot interactive_elements"},
                    "selector": {"type": "string", "description": "CSS selector as alternative to ref"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_type",
            "description": "Type text into an input field by reference or selector.",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "Text to type"},
                    "ref": {"type": "integer", "description": "Reference number from browser_snapshot forms"},
                    "selector": {"type": "string", "description": "CSS selector as alternative to ref"},
                    "submit": {"type": "boolean", "description": "Press Enter after typing", "default": False},
                },
                "required": ["text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_search",
            "description": "Perform a web search using a search engine.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "engine": {"type": "string", "description": "Search engine: google, duckduckgo, or bing", "default": "google"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_extract_article",
            "description": "Extract article content from current page using readability-style extraction.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_close",
            "description": "Close the browser session and free resources.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    # GitHub tools
    {
        "type": "function",
        "function": {
            "name": "github_create_repo",
            "description": "Create a new GitHub repository for storing knowledge, projects, or content.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Repository name (required)"},
                    "description": {"type": "string", "description": "Repository description"},
                    "private": {"type": "boolean", "description": "Whether the repo should be private", "default": False},
                    "auto_init": {"type": "boolean", "description": "Initialize with README", "default": True},
                    "gitignore_template": {"type": "string", "description": "Gitignore template (e.g., 'Python', 'Node')"},
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "github_list_repos",
            "description": "List repositories for the authenticated user.",
            "parameters": {
                "type": "object",
                "properties": {
                    "type_filter": {"type": "string", "description": "Filter: all, owner, member", "default": "owner"},
                    "sort": {"type": "string", "description": "Sort by: created, updated, pushed, full_name", "default": "updated"},
                    "limit": {"type": "integer", "description": "Maximum repos to return", "default": 30},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "github_create_issue",
            "description": "Create an issue in a GitHub repository to track tasks, goals, or findings.",
            "parameters": {
                "type": "object",
                "properties": {
                    "repo": {"type": "string", "description": "Repository in format 'owner/repo' (required)"},
                    "title": {"type": "string", "description": "Issue title (required)"},
                    "body": {"type": "string", "description": "Issue body/description"},
                    "labels": {"type": "array", "items": {"type": "string"}, "description": "List of label names"},
                },
                "required": ["repo", "title"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "github_list_issues",
            "description": "List issues in a GitHub repository.",
            "parameters": {
                "type": "object",
                "properties": {
                    "repo": {"type": "string", "description": "Repository in format 'owner/repo' (required)"},
                    "state": {"type": "string", "description": "Issue state: open, closed, all", "default": "open"},
                    "limit": {"type": "integer", "description": "Maximum issues to return", "default": 30},
                },
                "required": ["repo"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "github_read_file",
            "description": "Read a file from a GitHub repository.",
            "parameters": {
                "type": "object",
                "properties": {
                    "repo": {"type": "string", "description": "Repository in format 'owner/repo' (required)"},
                    "path": {"type": "string", "description": "File path within repo (required)"},
                    "ref": {"type": "string", "description": "Branch, tag, or commit SHA", "default": "main"},
                },
                "required": ["repo", "path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "github_write_file",
            "description": "Create or update a file in a GitHub repository.",
            "parameters": {
                "type": "object",
                "properties": {
                    "repo": {"type": "string", "description": "Repository in format 'owner/repo' (required)"},
                    "path": {"type": "string", "description": "File path within repo (required)"},
                    "content": {"type": "string", "description": "File content (required)"},
                    "message": {"type": "string", "description": "Commit message (required)"},
                    "branch": {"type": "string", "description": "Target branch", "default": "main"},
                    "sha": {"type": "string", "description": "SHA of existing file (required for updates)"},
                },
                "required": ["repo", "path", "content", "message"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "github_search_repos",
            "description": "Search for repositories on GitHub.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query (required). Can include qualifiers like language:python, topic:machine-learning"},
                    "sort": {"type": "string", "description": "Sort by: stars, forks, updated", "default": "stars"},
                    "order": {"type": "string", "description": "Sort order: desc, asc", "default": "desc"},
                    "limit": {"type": "integer", "description": "Maximum results", "default": 30},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "github_search_code",
            "description": "Search for code on GitHub.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query (required). Can include qualifiers like repo:owner/name, language:python, path:src"},
                    "limit": {"type": "integer", "description": "Maximum results", "default": 30},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "github_get_user",
            "description": "Get GitHub user information.",
            "parameters": {
                "type": "object",
                "properties": {
                    "username": {"type": "string", "description": "GitHub username (if empty, gets authenticated user)"},
                },
                "required": [],
            },
        },
    },
    # VPS Website tools
    {
        "type": "function",
        "function": {
            "name": "website_init",
            "description": "Initialize a new website for Urgo. Creates base structure, CSS, and initial pages.",
            "parameters": {
                "type": "object",
                "properties": {
                    "site_title": {"type": "string", "description": "Title of the website", "default": "Urgo's Digital Garden"},
                    "description": {"type": "string", "description": "Site description/meta", "default": "A collection of thoughts, learnings, and discoveries."},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "website_write_file",
            "description": "Write content to a file in the website.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative path within website (required)"},
                    "content": {"type": "string", "description": "File content (required)"},
                    "append": {"type": "boolean", "description": "Whether to append or overwrite", "default": False},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "website_read_file",
            "description": "Read a file from the website.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative path within website (required)"},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "website_list_files",
            "description": "List files in the website directory.",
            "parameters": {
                "type": "object",
                "properties": {
                    "directory": {"type": "string", "description": "Relative directory path", "default": ""},
                    "recursive": {"type": "boolean", "description": "List recursively", "default": False},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "website_create_post",
            "description": "Create a new blog post on the website.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Post title (required)"},
                    "content": {"type": "string", "description": "Post content, markdown or HTML (required)"},
                    "category": {"type": "string", "description": "Post category", "default": "general"},
                    "tags": {"type": "array", "items": {"type": "string"}, "description": "List of tags"},
                },
                "required": ["title", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "website_create_knowledge_page",
            "description": "Create a knowledge base page on the website.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Page title (required)"},
                    "content": {"type": "string", "description": "Page content (required)"},
                    "category": {"type": "string", "description": "Knowledge category", "default": "general"},
                    "source": {"type": "string", "description": "Source of this knowledge"},
                },
                "required": ["title", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "website_update_about",
            "description": "Update the about page with current information.",
            "parameters": {
                "type": "object",
                "properties": {
                    "biography": {"type": "string", "description": "Updated biography text"},
                    "interests": {"type": "array", "items": {"type": "string"}, "description": "List of current interests"},
                    "current_goals": {"type": "array", "items": {"type": "string"}, "description": "List of current goals"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "website_get_stats",
            "description": "Get website statistics (file counts, etc.).",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
]


def get_tools_schema(allowed_tools: set[str]) -> list[dict[str, Any]]:
    """Return OpenAI tools list filtered to allowed_tools (names from TOOL_DEFINITIONS)."""
    names = {d["function"]["name"] for d in TOOL_DEFINITIONS}
    return [
        d for d in TOOL_DEFINITIONS
        if d["function"]["name"] in allowed_tools and d["function"]["name"] in names
    ]


def dispatch(
    name: str,
    args: dict[str, Any],
    repo_context: Optional[dict[str, str]],
    *,
    runner_bridge: Any,
) -> str:
    """
    Execute one tool by name with args. runner_bridge must have methods:
    repo_list(), repo_status(repo), repo_last_commit(repo), repo_grep(repo, query, path),
    repo_readfile(repo, path, start_line, end_line), plan_echo(text), approve_echo(plan_id).
    Returns result string (JSON or plain). Raises ValueError if tool not allowed or args invalid.
    """
    allowed = getattr(runner_bridge, "allowed_tools", None)
    if allowed is not None and name not in allowed:
        raise ValueError(f"tool not allowed: {name}")
    # Apply repo_context defaults
    repo = args.get("repo") or (repo_context or {}).get("repo")
    path_hint = (repo_context or {}).get("path_hint") or ""

    if name == "repo_list":
        return runner_bridge.repo_list()
    if name == "repo_status":
        if not repo:
            raise ValueError("repo required")
        return runner_bridge.repo_status(repo)
    if name == "repo_last_commit":
        if not repo:
            raise ValueError("repo required")
        return runner_bridge.repo_last_commit(repo)
    if name == "repo_grep":
        if not repo:
            raise ValueError("repo required")
        query = args.get("query", "")
        reject_url_like_input(str(query), "query")
        path = args.get("path") or path_hint
        reject_url_like_input(str(path or ""), "path")
        return runner_bridge.repo_grep(repo, query, path or "")
    if name == "repo_readfile":
        if not repo:
            raise ValueError("repo required")
        path = args.get("path", "")
        if not path:
            raise ValueError("path required")
        reject_url_like_input(str(path), "path")
        start = int(args.get("start_line", 1))
        end = int(args.get("end_line", 200))
        return runner_bridge.repo_readfile(repo, path, start, end)
    if name == "plan_echo":
        text = args.get("text", "")
        reject_url_like_input(str(text), "text")
        return runner_bridge.plan_echo(text)
    if name == "approve_echo":
        plan_id = (args.get("plan_id") or "").strip()
        if not plan_id:
            raise ValueError("plan_id required")
        return runner_bridge.approve_echo(plan_id)
    # Browser tools
    if name == "browser_navigate":
        url = args.get("url", "")
        if not url:
            raise ValueError("url required")
        wait_for_load = args.get("wait_for_load", True)
        return runner_bridge.browser_navigate(url, wait_for_load)
    if name == "browser_snapshot":
        full_content = args.get("full_content", True)
        return runner_bridge.browser_snapshot(full_content)
    if name == "browser_click":
        ref = args.get("ref")
        selector = args.get("selector", "")
        return runner_bridge.browser_click(ref, selector or None)
    if name == "browser_type":
        text = args.get("text", "")
        if not text:
            raise ValueError("text required")
        ref = args.get("ref")
        selector = args.get("selector", "")
        submit = args.get("submit", False)
        return runner_bridge.browser_type(text, ref, selector or None, submit)
    if name == "browser_search":
        query = args.get("query", "")
        if not query:
            raise ValueError("query required")
        engine = args.get("engine", "google")
        return runner_bridge.browser_search(query, engine)
    if name == "browser_extract_article":
        return runner_bridge.browser_extract_article()
    if name == "browser_close":
        return runner_bridge.browser_close()
    # GitHub tools
    if name == "github_create_repo":
        repo_name = args.get("name", "")
        if not repo_name:
            raise ValueError("name required")
        return runner_bridge.github_create_repo(
            repo_name,
            args.get("description", ""),
            args.get("private", False),
            args.get("auto_init", True),
            args.get("gitignore_template", "")
        )
    if name == "github_list_repos":
        return runner_bridge.github_list_repos(
            args.get("type_filter", "owner"),
            args.get("sort", "updated"),
            args.get("limit", 30)
        )
    if name == "github_create_issue":
        repo = args.get("repo", "")
        title = args.get("title", "")
        if not repo or not title:
            raise ValueError("repo and title required")
        return runner_bridge.github_create_issue(
            repo,
            title,
            args.get("body", ""),
            args.get("labels")
        )
    if name == "github_list_issues":
        repo = args.get("repo", "")
        if not repo:
            raise ValueError("repo required")
        return runner_bridge.github_list_issues(
            repo,
            args.get("state", "open"),
            args.get("limit", 30)
        )
    if name == "github_read_file":
        repo = args.get("repo", "")
        path = args.get("path", "")
        if not repo or not path:
            raise ValueError("repo and path required")
        return runner_bridge.github_read_file(
            repo,
            path,
            args.get("ref", "main")
        )
    if name == "github_write_file":
        repo = args.get("repo", "")
        path = args.get("path", "")
        content = args.get("content", "")
        message = args.get("message", "")
        if not repo or not path or not content or not message:
            raise ValueError("repo, path, content, and message required")
        return runner_bridge.github_write_file(
            repo,
            path,
            content,
            message,
            args.get("branch", "main"),
            args.get("sha")
        )
    if name == "github_search_repos":
        query = args.get("query", "")
        if not query:
            raise ValueError("query required")
        return runner_bridge.github_search_repos(
            query,
            args.get("sort", "stars"),
            args.get("order", "desc"),
            args.get("limit", 30)
        )
    if name == "github_search_code":
        query = args.get("query", "")
        if not query:
            raise ValueError("query required")
        return runner_bridge.github_search_code(query, args.get("limit", 30))
    if name == "github_get_user":
        return runner_bridge.github_get_user(args.get("username"))
    # VPS Website tools
    if name == "website_init":
        return runner_bridge.website_init(
            args.get("site_title", "Urgo's Digital Garden"),
            args.get("description", "A collection of thoughts, learnings, and discoveries.")
        )
    if name == "website_write_file":
        path = args.get("path", "")
        content = args.get("content", "")
        if not path:
            raise ValueError("path required")
        if content == "":
            raise ValueError("content required")
        return runner_bridge.website_write_file(path, content, args.get("append", False))
    if name == "website_read_file":
        path = args.get("path", "")
        if not path:
            raise ValueError("path required")
        return runner_bridge.website_read_file(path)
    if name == "website_list_files":
        return runner_bridge.website_list_files(args.get("directory", ""), args.get("recursive", False))
    if name == "website_create_post":
        title = args.get("title", "")
        content = args.get("content", "")
        if not title or not content:
            raise ValueError("title and content required")
        return runner_bridge.website_create_post(
            title,
            content,
            args.get("category", "general"),
            args.get("tags")
        )
    if name == "website_create_knowledge_page":
        title = args.get("title", "")
        content = args.get("content", "")
        if not title or not content:
            raise ValueError("title and content required")
        return runner_bridge.website_create_knowledge_page(
            title,
            content,
            args.get("category", "general"),
            args.get("source")
        )
    if name == "website_update_about":
        return runner_bridge.website_update_about(
            args.get("biography"),
            args.get("interests"),
            args.get("current_goals")
        )
    if name == "website_get_stats":
        return runner_bridge.website_get_stats()
    raise ValueError(f"unknown tool: {name}")


def parse_tool_args(arguments: str) -> dict[str, Any]:
    """Parse tool call arguments JSON string. Returns dict or raises."""
    if not (arguments or arguments.strip()):
        return {}
    try:
        return json.loads(arguments)
    except json.JSONDecodeError as e:
        raise ValueError(f"invalid tool arguments JSON: {e}") from e
