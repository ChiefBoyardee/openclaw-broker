"""
Conversational Tool Formatters for OpenClaw Discord Bot.

This module transforms raw broker tool outputs into natural, conversational responses.
Instead of returning raw JSON or technical data, these formatters present information
in a way that fits Urgo's personality and maintains conversation flow.
"""

import json
from typing import Dict, Any, Optional, List
import logging

logger = logging.getLogger(__name__)


class ConversationalToolFormatter:
    """
    Formats raw tool outputs into natural language responses.

    Each formatter takes the raw result from a broker tool and transforms it
    into a conversational response that fits Urgo's personality.
    """

    @staticmethod
    def format_repo_list(result: Dict[str, Any]) -> str:
        """
        Format repository list results conversationally.

        Input: {"ok": true, "command": "repo_list", "repos": [{"name": "...", "path": "..."}]}
        Output: Natural language description of available repos
        """
        if not result.get("ok", False):
            error = result.get("error", "Unknown error")
            return f"I had trouble checking your repositories: {error}"

        repos = result.get("repos", [])
        if not repos:
            return "I don't see any repositories configured right now. You can add repositories to allow me to explore your code!"

        count = len(repos)

        if count == 1:
            intro = "I found 1 repository for you:"
        else:
            intro = f"I found {count} repositories for you:"

        lines = [intro, ""]

        for i, repo in enumerate(repos, 1):
            name = repo.get("name", "unknown")
            path = repo.get("path", "")
            lines.append(f"{i}. **{name}**")
            if path:
                lines.append(f"   📁 `{path}`")
            lines.append("")

        lines.append("You can ask me to explore any of these repositories, search for code, or read specific files!")

        return "\n".join(lines)

    @staticmethod
    def format_repo_status(result: Dict[str, Any], repo_name: str) -> str:
        """
        Format repository status results conversationally.

        Input: {"ok": true, "command": "repo_status", "repo": "...", "branch": "...", "dirty": true/false}
        Output: Natural language description of repo status
        """
        if not result.get("ok", False):
            error = result.get("error", "Unknown error")
            return f"I couldn't check the status of **{repo_name}**: {error}"

        branch = result.get("branch", "unknown")
        dirty = result.get("dirty", False)
        ahead_behind = result.get("ahead_behind", {})

        lines = [f"Here's the status of **{repo_name}**:", ""]

        lines.append(f"🌿 Current branch: `{branch}`")

        if dirty:
            lines.append("⚠️ You have uncommitted changes in this repository.")
        else:
            lines.append("✅ Working directory is clean - all changes are committed.")

        if ahead_behind:
            ahead = ahead_behind.get("ahead", 0)
            behind = ahead_behind.get("behind", 0)
            if ahead > 0 or behind > 0:
                lines.append("")
                if ahead > 0:
                    lines.append(f"⬆️ {ahead} commit{'s' if ahead > 1 else ''} ahead of remote")
                if behind > 0:
                    lines.append(f"⬇️ {behind} commit{'s' if behind > 1 else ''} behind remote")

        return "\n".join(lines)

    @staticmethod
    def format_repo_last_commit(result: Dict[str, Any], repo_name: str) -> str:
        """
        Format last commit information conversationally.

        Input: {"ok": true, "command": "repo_last_commit", ...}
        Output: Natural language description of the latest commit
        """
        if not result.get("ok", False):
            error = result.get("error", "Unknown error")
            return f"I couldn't get the last commit info for **{repo_name}**: {error}"

        commit = result.get("commit", {})
        if not commit:
            return f"I couldn't find any commit history for **{repo_name}**."

        message = commit.get("message", "No message")
        author = commit.get("author", "Unknown")
        date = commit.get("date", "Unknown date")
        hash_short = commit.get("hash", "")[:7]

        # Truncate message if too long
        if len(message) > 200:
            message = message[:200] + "..."

        lines = [
            f"Here's the latest commit in **{repo_name}**:",
            "",
            f"💬 **{message}**",
            "",
            f"👤 Author: {author}",
            f"📅 Date: {date}",
        ]

        if hash_short:
            lines.append(f"🔖 Hash: `{hash_short}`")

        return "\n".join(lines)

    @staticmethod
    def format_repo_grep(result: Dict[str, Any], query: str, repo_name: str) -> str:
        """
        Format grep search results conversationally.

        Input: {"ok": true, "command": "repo_grep", "results": [...]}
        Output: Natural language description of search results
        """
        if not result.get("ok", False):
            error = result.get("error", "Unknown error")
            return f"I had trouble searching for '{query}' in **{repo_name}**: {error}"

        results = result.get("results", [])
        if not results:
            return f"I searched through **{repo_name}** for '{query}' but didn't find any matches. Maybe try a different search term?"

        count = len(results)

        if count == 1:
            intro = f"I found 1 match for '{query}' in **{repo_name}**:"
        else:
            intro = f"I found {count} matches for '{query}' in **{repo_name}**:"

        lines = [intro, ""]

        # Group by file
        by_file: Dict[str, List[Dict]] = {}
        for match in results:
            file_path = match.get("file", "unknown")
            if file_path not in by_file:
                by_file[file_path] = []
            by_file[file_path].append(match)

        for file_path, matches in list(by_file.items())[:10]:  # Limit to 10 files
            lines.append(f"📄 **{file_path}** ({len(matches)} match{'es' if len(matches) > 1 else ''})")

            for match in matches[:3]:  # Max 3 matches per file
                line_num = match.get("line", "?")
                content = match.get("content", "")
                # Highlight the match in the content
                if content:
                    # Truncate if too long
                    if len(content) > 100:
                        content = content[:100] + "..."
                    lines.append(f"   Line {line_num}: `{content}`")

            if len(matches) > 3:
                lines.append(f"   ... and {len(matches) - 3} more matches in this file")
            lines.append("")

        if len(by_file) > 10:
            lines.append(f"... and results in {len(by_file) - 10} more files")

        lines.append("Would you like me to show you the content of any of these files? Just ask!")

        return "\n".join(lines)

    @staticmethod
    def format_repo_readfile(result: Dict[str, Any], file_path: str, repo_name: str) -> str:
        """
        Format file read results conversationally.

        Input: {"ok": true, "command": "repo_readfile", "content": "..."}
        Output: Natural language presentation of file content
        """
        if not result.get("ok", False):
            error = result.get("error", "Unknown error")
            return f"I couldn't read **{file_path}** from **{repo_name}**: {error}"

        content = result.get("content", "")
        lines_count = result.get("lines", 0)
        start_line = result.get("start", 1)
        end_line = result.get("end", start_line + lines_count - 1)

        if not content:
            return f"**{file_path}** in **{repo_name}** appears to be empty."

        # Format based on file type
        file_ext = file_path.split(".")[-1].lower() if "." in file_path else ""

        lines = [
            f"Here's the content of **{file_path}** from **{repo_name}**",
        ]

        if lines_count > 0:
            lines.append(f"(showing lines {start_line}-{end_line}):")
        lines.append("")

        # Wrap content in code block
        code_fence = f"```{file_ext}" if file_ext else "```"
        lines.append(code_fence)

        # Limit content length for display
        max_chars = 1900  # Discord limit safety
        if len(content) > max_chars:
            content = content[:max_chars] + "\n\n... [content truncated]"

        lines.append(content)
        lines.append("```")

        return "\n".join(lines)

    @staticmethod
    def format_github_list_repos(result: Dict[str, Any]) -> str:
        """
        Format GitHub repository list conversationally.

        Input: GitHub API response or tool result
        Output: Natural language description of GitHub repos
        """
        if isinstance(result, str):
            try:
                result = json.loads(result)
            except json.JSONDecodeError:
                return f"I got a response from GitHub, but couldn't parse it properly. Here's what they said:\n```\n{result[:500]}\n```"

        if not result.get("success", False):
            error = result.get("error", "Unknown error")
            return f"I had trouble fetching your GitHub repositories: {error}"

        repos = result.get("repos", [])
        if not repos:
            return "I don't see any GitHub repositories. Make sure your GitHub token is configured correctly!"

        count = len(repos)

        if count == 1:
            intro = "I found 1 GitHub repository for you:"
        else:
            intro = f"I found {count} GitHub repositories for you:"

        lines = [intro, ""]

        for i, repo in enumerate(repos[:15], 1):  # Limit to 15
            name = repo.get("name", "unknown")
            desc = repo.get("description", "")
            stars = repo.get("stars", 0)
            private = repo.get("private", False)

            visibility = "🔒" if private else "🌐"
            lines.append(f"{i}. {visibility} **{name}**")

            if desc:
                # Truncate description
                if len(desc) > 80:
                    desc = desc[:80] + "..."
                lines.append(f"   {desc}")

            if stars > 0:
                lines.append(f"   ⭐ {stars} star{'s' if stars > 1 else ''}")

            lines.append("")

        if len(repos) > 15:
            lines.append(f"... and {len(repos) - 15} more repositories")

        return "\n".join(lines)

    @staticmethod
    def format_github_list_issues(result: Dict[str, Any], repo_name: str) -> str:
        """
        Format GitHub issues list conversationally.

        Input: GitHub issues API response
        Output: Natural language description of issues
        """
        if isinstance(result, str):
            try:
                result = json.loads(result)
            except json.JSONDecodeError:
                return "I got a response but couldn't parse the issues properly."

        if not result.get("success", False):
            error = result.get("error", "Unknown error")
            return f"I had trouble fetching issues for **{repo_name}**: {error}"

        issues = result.get("issues", [])
        if not issues:
            return f"Great news! There are no open issues in **{repo_name}**. Everything looks clean! 🎉"

        count = len(issues)

        if count == 1:
            intro = f"I found 1 open issue in **{repo_name}**:"
        else:
            intro = f"I found {count} open issues in **{repo_name}**:"

        lines = [intro, ""]

        for i, issue in enumerate(issues[:10], 1):  # Limit to 10
            title = issue.get("title", "Untitled")
            number = issue.get("number", "?")
            _state = issue.get("state", "unknown")
            labels = issue.get("labels", [])

            lines.append(f"{i}. **#{number}**: {title}")

            if labels:
                label_str = ", ".join(labels[:3])
                lines.append(f"   🏷️ {label_str}")

            lines.append("")

        if len(issues) > 10:
            lines.append(f"... and {len(issues) - 10} more issues")

        return "\n".join(lines)

    @staticmethod
    def format_capabilities(result: Dict[str, Any]) -> str:
        """
        Format capabilities/system status conversationally.

        Input: {"ok": true, "worker_id": "...", "capabilities": [...]}
        Output: Natural language description of what the bot can do
        """
        if not result.get("ok", False):
            return "I'm having trouble checking my capabilities right now. Try again in a moment!"

        worker_id = result.get("worker_id", "unknown")
        caps = result.get("capabilities", [])

        lines = [
            "I'm operational and ready to help! 🤖",
            "",
            f"**Worker ID:** `{worker_id}`",
            "",
            "**My capabilities include:**",
            "",
        ]

        # Group capabilities by category
        categories = {
            "llm": [],
            "repo": [],
            "github": [],
            "web": [],
            "website": [],
            "nginx": [],
            "system": [],
        }

        for cap in sorted(caps):
            if cap.startswith("llm:"):
                categories["llm"].append(cap)
            elif cap.startswith("repo_"):
                categories["repo"].append(cap)
            elif cap.startswith("github_"):
                categories["github"].append(cap)
            elif cap.startswith("browser_"):
                categories["web"].append(cap)
            elif cap.startswith("website_"):
                categories["website"].append(cap)
            elif cap.startswith("nginx_"):
                categories["nginx"].append(cap)
            else:
                categories["system"].append(cap)

        for category, items in categories.items():
            if items:
                emoji = {
                    "llm": "🧠",
                    "repo": "📁",
                    "github": "🐙",
                    "web": "🌐",
                    "website": "🌐",
                    "nginx": "🖥️",
                    "system": "⚙️",
                }.get(category, "•")

                lines.append(f"{emoji} **{category.title()}:** {', '.join(items[:5])}")
                if len(items) > 5:
                    lines.append(f"   ... and {len(items) - 5} more")

        lines.append("")
        lines.append("Just ask me naturally what you'd like to do, and I'll help you out!")

        return "\n".join(lines)

    @staticmethod
    def format_ping(result: Dict[str, Any]) -> str:
        """
        Format ping results conversationally.

        Input: {"ok": true, "result": "pong", "timestamp": ...}
        Output: Natural language ping response
        """
        if not result.get("ok", False):
            return "I'm having trouble reaching the broker right now. The system might be busy or experiencing issues."

        return "Pong! 🏓 I'm here and ready to help! The broker is responding normally."


# Global formatter instance
_formatter_instance: Optional[ConversationalToolFormatter] = None


def get_formatter() -> ConversationalToolFormatter:
    """Get or create the global formatter instance."""
    global _formatter_instance
    if _formatter_instance is None:
        _formatter_instance = ConversationalToolFormatter()
    return _formatter_instance


def format_tool_result(command: str, result: Any, **context) -> str:
    """
    Convenience function to format any tool result.

    Args:
        command: The command that was executed
        result: The raw result from the tool
        **context: Additional context (repo_name, file_path, query, etc.)

    Returns:
        Natural language formatted response
    """
    formatter = get_formatter()

    # Parse result if it's a string
    if isinstance(result, str):
        try:
            result = json.loads(result)
        except json.JSONDecodeError:
            # Return raw result if can't parse
            return f"Here's what I found:\n```\n{result[:1000]}\n```"

    # Route to appropriate formatter
    formatters = {
        "repo_list": lambda: formatter.format_repo_list(result),
        "repo_status": lambda: formatter.format_repo_status(result, context.get("repo_name", "repository")),
        "repo_last_commit": lambda: formatter.format_repo_last_commit(result, context.get("repo_name", "repository")),
        "repo_grep": lambda: formatter.format_repo_grep(result, context.get("query", ""), context.get("repo_name", "repository")),
        "repo_readfile": lambda: formatter.format_repo_readfile(result, context.get("file_path", "file"), context.get("repo_name", "repository")),
        "github_list_repos": lambda: formatter.format_github_list_repos(result),
        "github_list_issues": lambda: formatter.format_github_list_issues(result, context.get("repo_name", "repository")),
        "capabilities": lambda: formatter.format_capabilities(result),
        "ping": lambda: formatter.format_ping(result),
    }

    formatter_func = formatters.get(command)
    if formatter_func:
        try:
            return formatter_func()
        except Exception as e:
            logger.error(f"Error formatting {command} result: {e}")
            # Fall back to raw result on formatting error
            return f"I got a result but had trouble formatting it. Here's the raw data:\n```json\n{json.dumps(result, indent=2)[:1000]}\n```"
    else:
        # Unknown command - return generic formatted JSON
        return f"Here's what I found:\n```json\n{json.dumps(result, indent=2)[:1500]}\n```"


# Example usage and testing
if __name__ == "__main__":
    # Test the formatters
    test_results = {
        "repo_list": {
            "ok": True,
            "command": "repo_list",
            "repos": [
                {"name": "openclaw-broker", "path": "/opt/repos/openclaw-broker"},
                {"name": "my-website", "path": "/home/user/my-website"},
            ]
        },
        "repo_status": {
            "ok": True,
            "command": "repo_status",
            "branch": "main",
            "dirty": True,
            "ahead_behind": {"ahead": 2, "behind": 0}
        },
        "ping": {
            "ok": True,
            "result": "pong",
            "timestamp": 1234567890
        }
    }

    formatter = ConversationalToolFormatter()

    for cmd, result in test_results.items():
        print(f"\n{'='*60}")
        print(f"Command: {cmd}")
        print(f"{'='*60}")
        formatted = format_tool_result(cmd, result, repo_name="openclaw-broker")
        print(formatted)
