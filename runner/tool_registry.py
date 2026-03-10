"""
Tool registry and dispatcher for LLM tool-calling (Sprint 5). OpenAI function-calling schema; dispatch to runner helpers.

Supports bidirectional tool categories:
- RUNNER_LOCAL: Tools executed entirely on the runner (repo tools, browser, etc.)
- BIDIRECTIONAL: Tools that can be executed by either runner or bot
- BOT_ONLY: Tools that must be executed by the Discord bot (Discord-native tools)
"""
from __future__ import annotations

import json
import re
from enum import Enum
from typing import Any, Optional


class ToolCategory(Enum):
    """Categories for tool execution location."""
    RUNNER_LOCAL = "runner_local"      # Executed on runner
    BIDIRECTIONAL = "bidirectional"    # Can be executed by either
    BOT_ONLY = "bot_only"              # Must be executed by bot


# Tool category mapping
TOOL_CATEGORIES: dict[str, ToolCategory] = {
    # Runner-local tools
    "repo_list": ToolCategory.RUNNER_LOCAL,
    "repo_status": ToolCategory.RUNNER_LOCAL,
    "repo_last_commit": ToolCategory.RUNNER_LOCAL,
    "repo_grep": ToolCategory.RUNNER_LOCAL,
    "repo_readfile": ToolCategory.RUNNER_LOCAL,
    "plan_echo": ToolCategory.RUNNER_LOCAL,
    "approve_echo": ToolCategory.RUNNER_LOCAL,
    # Browser tools (runner-local)
    "browser_navigate": ToolCategory.RUNNER_LOCAL,
    "browser_snapshot": ToolCategory.RUNNER_LOCAL,
    "browser_click": ToolCategory.RUNNER_LOCAL,
    "browser_type": ToolCategory.RUNNER_LOCAL,
    "browser_search": ToolCategory.RUNNER_LOCAL,
    "browser_extract_article": ToolCategory.RUNNER_LOCAL,
    "browser_close": ToolCategory.RUNNER_LOCAL,
    # GitHub tools (runner-local, needs API key on runner)
    "github_create_repo": ToolCategory.RUNNER_LOCAL,
    "github_list_repos": ToolCategory.RUNNER_LOCAL,
    "github_create_issue": ToolCategory.RUNNER_LOCAL,
    "github_list_issues": ToolCategory.RUNNER_LOCAL,
    "github_read_file": ToolCategory.RUNNER_LOCAL,
    "github_write_file": ToolCategory.RUNNER_LOCAL,
    "github_search_repos": ToolCategory.RUNNER_LOCAL,
    "github_search_code": ToolCategory.RUNNER_LOCAL,
    "github_get_user": ToolCategory.RUNNER_LOCAL,
    # Website tools (runner-local)
    "website_init": ToolCategory.RUNNER_LOCAL,
    "website_write_file": ToolCategory.RUNNER_LOCAL,
    "website_read_file": ToolCategory.RUNNER_LOCAL,
    "website_list_files": ToolCategory.RUNNER_LOCAL,
    "website_create_post": ToolCategory.RUNNER_LOCAL,
    "website_create_knowledge_page": ToolCategory.RUNNER_LOCAL,
    "website_update_about": ToolCategory.RUNNER_LOCAL,
    "website_get_stats": ToolCategory.RUNNER_LOCAL,
    # Nginx tools (runner-local, needs sudo)
    "nginx_generate_config": ToolCategory.RUNNER_LOCAL,
    "nginx_install_config": ToolCategory.RUNNER_LOCAL,
    "nginx_enable_site": ToolCategory.RUNNER_LOCAL,
    "nginx_disable_site": ToolCategory.RUNNER_LOCAL,
    "nginx_remove_config": ToolCategory.RUNNER_LOCAL,
    "nginx_test_config": ToolCategory.RUNNER_LOCAL,
    "nginx_reload": ToolCategory.RUNNER_LOCAL,
    "nginx_get_status": ToolCategory.RUNNER_LOCAL,
    # Discord-native tools (bot-only)
    "discord_send_message": ToolCategory.BOT_ONLY,
    "discord_send_embed": ToolCategory.BOT_ONLY,
    "discord_add_reaction": ToolCategory.BOT_ONLY,
    "discord_upload_file": ToolCategory.BOT_ONLY,
    "discord_edit_message": ToolCategory.BOT_ONLY,
    "discord_reply": ToolCategory.BOT_ONLY,
    "self_memory_add_fact": ToolCategory.BOT_ONLY,
    "self_memory_add_reflection": ToolCategory.BOT_ONLY,
}


def get_tool_category(tool_name: str) -> ToolCategory:
    """Get the category for a tool."""
    return TOOL_CATEGORIES.get(tool_name, ToolCategory.RUNNER_LOCAL)


def is_bidirectional_tool(tool_name: str) -> bool:
    """Check if a tool is bidirectional (can be executed by bot)."""
    category = get_tool_category(tool_name)
    return category in (ToolCategory.BIDIRECTIONAL, ToolCategory.BOT_ONLY)


def is_bot_only_tool(tool_name: str) -> bool:
    """Check if a tool must be executed by the bot."""
    return get_tool_category(tool_name) == ToolCategory.BOT_ONLY

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
    # Nginx Management tools
    {
        "type": "function",
        "function": {
            "name": "nginx_generate_config",
            "description": "Generate a security-hardened nginx configuration for a domain.",
            "parameters": {
                "type": "object",
                "properties": {
                    "domain": {"type": "string", "description": "Domain name (e.g., 'urgo.sgc.earth')"},
                    "web_root": {"type": "string", "description": "Absolute path to website files (e.g., '/var/www/urgo')"},
                    "ssl_cert": {"type": "string", "description": "Path to SSL certificate (optional)"},
                    "ssl_key": {"type": "string", "description": "Path to SSL certificate key (optional)"},
                    "enable_http2": {"type": "boolean", "description": "Enable HTTP/2 (requires SSL)", "default": True},
                    "rate_limit_zone": {"type": "string", "description": "Rate limiting zone name", "default": "ai_site"},
                    "rate_limit_rps": {"type": "integer", "description": "Requests per second limit", "default": 10},
                    "rate_limit_burst": {"type": "integer", "description": "Burst capacity", "default": 20},
                },
                "required": ["domain", "web_root"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "nginx_install_config",
            "description": "Install nginx configuration file for a domain.",
            "parameters": {
                "type": "object",
                "properties": {
                    "domain": {"type": "string", "description": "Domain name"},
                    "config_content": {"type": "string", "description": "Nginx configuration content"},
                    "enable": {"type": "boolean", "description": "Enable the site after install", "default": True},
                },
                "required": ["domain", "config_content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "nginx_enable_site",
            "description": "Enable an nginx site by creating symlink.",
            "parameters": {
                "type": "object",
                "properties": {
                    "domain": {"type": "string", "description": "Domain name to enable"},
                },
                "required": ["domain"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "nginx_disable_site",
            "description": "Disable an nginx site by removing symlink.",
            "parameters": {
                "type": "object",
                "properties": {
                    "domain": {"type": "string", "description": "Domain name to disable"},
                },
                "required": ["domain"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "nginx_remove_config",
            "description": "Remove nginx configuration for a domain.",
            "parameters": {
                "type": "object",
                "properties": {
                    "domain": {"type": "string", "description": "Domain name to remove"},
                },
                "required": ["domain"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "nginx_test_config",
            "description": "Test nginx configuration syntax.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "nginx_reload",
            "description": "Reload nginx configuration safely (tests first).",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "nginx_get_status",
            "description": "Get nginx service status and site information.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    # Discord-native tools (bidirectional - executed by bot)
    {
        "type": "function",
        "function": {
            "name": "discord_send_message",
            "description": "Send a text message to the Discord channel. Use this to provide intermediate updates to the user during long-running tasks.",
            "parameters": {
                "type": "object",
                "properties": {
                    "message": {
                        "type": "string",
                        "description": "The message content to send (max 2000 chars)",
                    },
                    "type": {
                        "type": "string",
                        "enum": ["info", "success", "warning", "error"],
                        "description": "Message type for styling",
                    },
                },
                "required": ["message"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "discord_send_embed",
            "description": "Send a rich embed message to the Discord channel. Useful for structured data or formatted results.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Embed title"},
                    "description": {"type": "string", "description": "Embed description"},
                    "color": {"type": "integer", "description": "Embed color as decimal"},
                },
                "required": ["title", "description"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "discord_add_reaction",
            "description": "Add a reaction emoji to the user's message. Use sparingly to indicate progress or status.",
            "parameters": {
                "type": "object",
                "properties": {
                    "emoji": {"type": "string", "description": "The emoji to add"},
                },
                "required": ["emoji"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "discord_upload_file",
            "description": "Upload a file attachment to the channel.",
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {"type": "string", "description": "File content as string"},
                    "filename": {"type": "string", "description": "Name of the file"},
                    "description": {"type": "string", "description": "Optional message"},
                },
                "required": ["content", "filename"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "discord_reply",
            "description": "Reply directly to the user's message.",
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {"type": "string", "description": "Reply content"},
                    "mention": {"type": "boolean", "description": "Whether to mention the user"},
                },
                "required": ["content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "self_memory_add_fact",
            "description": "Explicitly save a fact about yourself (Urgo) to your persistent memory. Use this for lore, origins, and personal discoveries.",
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {"type": "string", "description": "The fact to remember about yourself (e.g. 'I was created to explore code')"},
                    "category": {"type": "string", "description": "Optional category (origins, capabilities, preferences)", "default": "other"}
                },
                "required": ["content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "self_memory_add_reflection",
            "description": "Save a personal reflection, realization, or insight about your experiences or the world.",
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {"type": "string", "description": "The reflection or insight"},
                    "importance": {"type": "number", "description": "Importance level 0.0 to 2.0", "default": 1.0}
                },
                "required": ["content"]
            }
        }
    }
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

    For BOT_ONLY tools, returns a placeholder indicating the tool needs bot-side execution.
    """
    allowed = getattr(runner_bridge, "allowed_tools", None)
    if allowed is not None and name not in allowed:
        raise ValueError(f"tool not allowed: {name}")

    # Handle BOT_ONLY tools - return placeholder for bot execution
    if is_bot_only_tool(name):
        return json.dumps({
            "tool": name,
            "params": args,
            "status": "pending_bot_execution",
            "note": "This tool must be executed by the Discord bot. Creating bidirectional tool call."
        })
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
    # Nginx Management tools
    if name == "nginx_generate_config":
        domain = args.get("domain", "")
        web_root = args.get("web_root", "")
        if not domain or not web_root:
            raise ValueError("domain and web_root required")
        return runner_bridge.nginx_generate_config(
            domain,
            web_root,
            args.get("ssl_cert"),
            args.get("ssl_key"),
            args.get("enable_http2", True),
            args.get("rate_limit_zone", "ai_site"),
            args.get("rate_limit_rps", 10),
            args.get("rate_limit_burst", 20),
        )
    if name == "nginx_install_config":
        domain = args.get("domain", "")
        config_content = args.get("config_content", "")
        if not domain or not config_content:
            raise ValueError("domain and config_content required")
        return runner_bridge.nginx_install_config(domain, config_content, args.get("enable", True))
    if name == "nginx_enable_site":
        domain = args.get("domain", "")
        if not domain:
            raise ValueError("domain required")
        return runner_bridge.nginx_enable_site(domain)
    if name == "nginx_disable_site":
        domain = args.get("domain", "")
        if not domain:
            raise ValueError("domain required")
        return runner_bridge.nginx_disable_site(domain)
    if name == "nginx_remove_config":
        domain = args.get("domain", "")
        if not domain:
            raise ValueError("domain required")
        return runner_bridge.nginx_remove_config(domain)
    if name == "nginx_test_config":
        return runner_bridge.nginx_test_config()
    if name == "nginx_reload":
        return runner_bridge.nginx_reload()
    if name == "nginx_get_status":
        return runner_bridge.nginx_get_status()
    raise ValueError(f"unknown tool: {name}")


def parse_tool_args(arguments: str) -> dict[str, Any]:
    """Parse tool call arguments JSON string. Returns dict or raises."""
    if not (arguments or arguments.strip()):
        return {}
    try:
        return json.loads(arguments)
    except json.JSONDecodeError as e:
        raise ValueError(f"invalid tool arguments JSON: {e}") from e
