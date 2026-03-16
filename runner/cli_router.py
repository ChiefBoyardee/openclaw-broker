"""
CLI command router for the single run(command="...") tool interface.

Translates CLI-style command strings into existing tool function calls.
Implements progressive disclosure (help at each level), smart error messages,
and consistent output metadata.

Inspired by the Manus agent architecture: instead of 39+ individual OpenAI
function-calling tools, expose a single run(command) tool with all capabilities
as CLI subcommands. LLMs already speak CLI fluently from training data.
"""
from __future__ import annotations

import difflib
import json
import logging
import shlex
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


@dataclass
class CommandParam:
    """A parameter for a CLI command."""
    name: str
    description: str
    required: bool = False
    default: Any = None
    param_type: str = "string"  # string, integer, boolean


@dataclass
class Command:
    """A registered CLI command."""
    name: str
    help_text: str
    handler: Optional[Callable] = None
    params: list[CommandParam] = field(default_factory=list)
    positional_args: list[str] = field(default_factory=list)  # Names of positional args in order

    def usage_line(self, group_name: str) -> str:
        """Generate a one-line usage string."""
        parts = [group_name, self.name]
        for pos in self.positional_args:
            param = next((p for p in self.params if p.name == pos), None)
            if param and param.required:
                parts.append(f"<{pos}>")
            else:
                parts.append(f"[{pos}]")
        optional_flags = [p for p in self.params if p.name not in self.positional_args]
        if optional_flags:
            parts.append("[options]")
        return " ".join(parts)

    def help_detail(self, group_name: str) -> str:
        """Generate detailed help output."""
        lines = [
            f"Usage: {self.usage_line(group_name)}",
            f"  {self.help_text}",
            "",
        ]
        if self.params:
            lines.append("Arguments:")
            for p in self.params:
                req_marker = " (required)" if p.required else ""
                default_str = f" [default: {p.default}]" if p.default is not None else ""
                if p.name in self.positional_args:
                    lines.append(f"  {p.name:<20} {p.description}{req_marker}{default_str}")
                else:
                    lines.append(f"  --{p.name:<18} {p.description}{req_marker}{default_str}")
        return "\n".join(lines)


@dataclass
class CommandGroup:
    """A group of related CLI commands."""
    name: str
    help_text: str
    commands: dict[str, Command] = field(default_factory=dict)

    def usage(self) -> str:
        """Generate usage output when group is invoked with no subcommand."""
        lines = [f"{self.name} — {self.help_text}", ""]
        if self.commands:
            lines.append("Subcommands:")
            max_usage_len = max(
                (len(cmd.usage_line(self.name)) for cmd in self.commands.values()),
                default=20,
            )
            for cmd in self.commands.values():
                usage = cmd.usage_line(self.name)
                lines.append(f"  {usage:<{max_usage_len + 2}} {cmd.help_text}")
        lines.append(f"\nRun '{self.name} <subcommand> --help' for details on a subcommand.")
        return "\n".join(lines)


class CLIRouter:
    """
    Routes run(command="...") calls to registered command handlers.

    Provides:
    - Progressive disclosure: overview → group usage → command --help
    - Smart error messages with suggestions
    - Consistent output metadata [exit:N | Xs | NKB]
    """

    def __init__(self):
        self.groups: dict[str, CommandGroup] = {}

    def register_group(self, name: str, help_text: str) -> CommandGroup:
        """Register a command group (top-level namespace)."""
        group = CommandGroup(name=name, help_text=help_text)
        self.groups[name] = group
        return group

    def register_command(
        self,
        group_name: str,
        cmd_name: str,
        handler: Callable,
        help_text: str,
        params: Optional[list[CommandParam]] = None,
        positional_args: Optional[list[str]] = None,
    ) -> Command:
        """Register a command under a group."""
        if group_name not in self.groups:
            raise ValueError(f"Group '{group_name}' not registered")
        cmd = Command(
            name=cmd_name,
            help_text=help_text,
            handler=handler,
            params=params or [],
            positional_args=positional_args or [],
        )
        self.groups[group_name].commands[cmd_name] = cmd
        return cmd

    def get_command_list(self) -> str:
        """Generate Level 0 command overview for injection into tool description."""
        lines = []
        for group in self.groups.values():
            lines.append(f"  {group.name:<10} — {group.help_text}")
        lines.append("")
        lines.append("Run a command with no args to see its subcommands.")
        lines.append("Run '<command> <subcommand> --help' for detailed usage.")
        return "\n".join(lines)

    def execute(
        self,
        command_string: str,
        bridge: Any,
        repo_context: Optional[dict[str, str]] = None,
    ) -> str:
        """
        Parse and execute a CLI command string.

        Returns formatted result with metadata.
        """
        command_string = command_string.strip()
        if not command_string:
            return self._format_result(
                f"Available commands:\n{self.get_command_list()}",
                exit_code=0,
                duration=0.0,
            )

        # Parse command string
        try:
            tokens = shlex.split(command_string)
        except ValueError:
            # Handle unmatched quotes by splitting on whitespace
            tokens = command_string.split()

        if not tokens:
            return self._format_result(
                f"Available commands:\n{self.get_command_list()}",
                exit_code=0,
                duration=0.0,
            )

        group_name = tokens[0].lower()
        remaining = tokens[1:]

        # Find group
        group = self.groups.get(group_name)
        if not group:
            suggestion = self._suggest_group(group_name)
            available = ", ".join(sorted(self.groups.keys()))
            return self._format_error(
                f'Unknown command "{group_name}".{suggestion}',
                f"Available commands: {available}",
            )

        # No subcommand → show group usage (Level 1 progressive disclosure)
        if not remaining:
            return self._format_result(group.usage(), exit_code=0, duration=0.0)

        subcmd_name = remaining[0].lower()
        subcmd_args = remaining[1:]

        # Check for --help on group level
        if subcmd_name in ("--help", "-h", "help"):
            return self._format_result(group.usage(), exit_code=0, duration=0.0)

        # Find command
        cmd = group.commands.get(subcmd_name)
        if not cmd:
            suggestion = self._suggest_command(group, subcmd_name)
            available = ", ".join(sorted(group.commands.keys()))
            return self._format_error(
                f'Unknown subcommand "{subcmd_name}" for {group_name}.{suggestion}',
                f"Available: {available}. Run '{group_name}' to see full usage.",
            )

        # Check for --help on command level (Level 2 progressive disclosure)
        if subcmd_args and subcmd_args[0] in ("--help", "-h"):
            return self._format_result(
                cmd.help_detail(group_name), exit_code=0, duration=0.0
            )

        # Parse arguments
        try:
            parsed_args = self._parse_args(cmd, subcmd_args)
        except ValueError as e:
            return self._format_error(
                str(e),
                f"Run '{group_name} {subcmd_name} --help' for usage.",
            )

        # Execute handler
        start_time = time.time()
        try:
            result = cmd.handler(bridge=bridge, repo_context=repo_context, **parsed_args)
            duration = time.time() - start_time
            return self._format_result(result, exit_code=0, duration=duration)
        except ValueError as e:
            duration = time.time() - start_time
            error_msg = str(e)
            # Enhance certain known errors with suggestions
            enhanced = self._enhance_error(error_msg, group_name, subcmd_name)
            return self._format_error(enhanced, duration=duration)
        except Exception as e:
            duration = time.time() - start_time
            logger.exception(f"Command execution error: {group_name} {subcmd_name}")
            return self._format_error(
                f"Execution failed: {e}",
                f"Run '{group_name} {subcmd_name} --help' for usage.",
                duration=duration,
            )

    def _parse_args(self, cmd: Command, raw_args: list[str]) -> dict[str, Any]:
        """Parse positional args and --flag values from raw token list."""
        parsed: dict[str, Any] = {}
        positional_idx = 0
        i = 0

        while i < len(raw_args):
            token = raw_args[i]
            if token.startswith("--"):
                # Flag argument
                flag_name = token[2:].replace("-", "_")
                param = next((p for p in cmd.params if p.name == flag_name), None)
                if not param:
                    raise ValueError(f"Unknown flag: --{token[2:]}")
                if param.param_type == "boolean":
                    parsed[flag_name] = True
                else:
                    if i + 1 >= len(raw_args):
                        raise ValueError(f"Flag --{token[2:]} requires a value")
                    i += 1
                    val = raw_args[i]
                    if param.param_type == "integer":
                        try:
                            val = int(val)
                        except ValueError:
                            raise ValueError(f"--{token[2:]} must be an integer, got '{val}'")
                    parsed[flag_name] = val
            else:
                # Positional argument
                if positional_idx < len(cmd.positional_args):
                    pname = cmd.positional_args[positional_idx]
                    param = next((p for p in cmd.params if p.name == pname), None)
                    if param and param.param_type == "integer":
                        try:
                            token = int(token)
                        except ValueError:
                            raise ValueError(f"{pname} must be an integer, got '{token}'")
                    parsed[pname] = token
                    positional_idx += 1
                else:
                    # Extra positional args — collect as remaining text
                    # This handles multi-word arguments like message content
                    last_pos = cmd.positional_args[-1] if cmd.positional_args else None
                    if last_pos and last_pos in parsed:
                        parsed[last_pos] = parsed[last_pos] + " " + token
                    else:
                        raise ValueError(
                            f"Too many arguments. Expected {len(cmd.positional_args)} "
                            f"positional arg(s): {', '.join(cmd.positional_args)}"
                        )
            i += 1

        # Check required positional args
        for pname in cmd.positional_args:
            param = next((p for p in cmd.params if p.name == pname), None)
            if param and param.required and pname not in parsed:
                raise ValueError(f"Missing required argument: {pname}")

        # Apply defaults
        for p in cmd.params:
            if p.name not in parsed and p.default is not None:
                parsed[p.name] = p.default

        return parsed

    def _format_result(
        self,
        output: str,
        exit_code: int = 0,
        duration: float = 0.0,
    ) -> str:
        """Format result with consistent metadata."""
        output_bytes = len(output.encode("utf-8"))
        if output_bytes > 1024:
            size_str = f"{output_bytes / 1024:.1f}KB"
        else:
            size_str = f"{output_bytes}B"
        return f"{output}\n[exit:{exit_code} | {duration:.2f}s | {size_str}]"

    def _format_error(
        self,
        message: str,
        suggestion: Optional[str] = None,
        duration: float = 0.0,
    ) -> str:
        """Format error with guidance for the agent."""
        parts = [f"[error] {message}"]
        if suggestion:
            parts.append(f"  -> {suggestion}")
        error_text = "\n".join(parts)
        return f"{error_text}\n[exit:1 | {duration:.2f}s]"

    def _suggest_group(self, name: str) -> str:
        """Find close matches for a misspelled group name."""
        matches = difflib.get_close_matches(name, self.groups.keys(), n=1, cutoff=0.6)
        if matches:
            return f' Did you mean "{matches[0]}"?'
        return ""

    def _suggest_command(self, group: CommandGroup, name: str) -> str:
        """Find close matches for a misspelled command name."""
        matches = difflib.get_close_matches(
            name, group.commands.keys(), n=1, cutoff=0.6
        )
        if matches:
            return f' Did you mean "{matches[0]}"?'
        return ""

    def _enhance_error(self, error_msg: str, group: str, subcmd: str) -> str:
        """Add corrective suggestions to known error patterns."""
        lower = error_msg.lower()
        if "repo not allowlisted" in lower or "not found" in lower:
            return f"{error_msg}. Use 'repo list' to see available repos."
        if "path required" in lower:
            return f"{error_msg}. Provide a relative file path within the repo."
        if "url required" in lower:
            return f"{error_msg}. Provide a URL, e.g. 'browser navigate https://example.com'"
        if "query required" in lower:
            return f"{error_msg}. Provide a search query string."
        if "not a git repo" in lower:
            return f"{error_msg}. Verify with 'repo list' that this repo exists."
        if "tool not allowed" in lower:
            return f"{error_msg}. This command is not enabled for this session."
        return error_msg


# ── Command handler implementations ──
# Each handler receives bridge, repo_context, and parsed CLI args.
# They delegate to the existing bridge methods.


def _handle_repo_list(bridge: Any, repo_context: Any, **kwargs) -> str:
    return bridge.repo_list()


def _handle_repo_status(bridge: Any, repo_context: Any, name: str, **kwargs) -> str:
    return bridge.repo_status(name)


def _handle_repo_last_commit(bridge: Any, repo_context: Any, name: str, **kwargs) -> str:
    return bridge.repo_last_commit(name)


def _handle_repo_grep(
    bridge: Any, repo_context: Any, name: str, query: str, path: str = "", **kwargs
) -> str:
    return bridge.repo_grep(name, query, path)


def _handle_repo_readfile(
    bridge: Any,
    repo_context: Any,
    name: str,
    path: str,
    start: int = 1,
    end: int = 200,
    **kwargs,
) -> str:
    return bridge.repo_readfile(name, path, int(start), int(end))


def _handle_browser_navigate(
    bridge: Any, repo_context: Any, url: str, **kwargs
) -> str:
    wait = kwargs.get("wait_for_load", True)
    return bridge.browser_navigate(url, wait)


def _handle_browser_snapshot(bridge: Any, repo_context: Any, **kwargs) -> str:
    full = kwargs.get("full", True)
    return bridge.browser_snapshot(full)


def _handle_browser_click(bridge: Any, repo_context: Any, **kwargs) -> str:
    ref = kwargs.get("ref")
    selector = kwargs.get("selector")
    if ref is not None:
        ref = int(ref)
    return bridge.browser_click(ref, selector or None)


def _handle_browser_type(bridge: Any, repo_context: Any, text: str, **kwargs) -> str:
    ref = kwargs.get("ref")
    selector = kwargs.get("selector")
    submit = kwargs.get("submit", False)
    if ref is not None:
        ref = int(ref)
    return bridge.browser_type(text, ref, selector or None, submit)


def _handle_browser_search(
    bridge: Any, repo_context: Any, query: str, engine: str = "google", **kwargs
) -> str:
    return bridge.browser_search(query, engine)


def _handle_browser_extract_article(bridge: Any, repo_context: Any, **kwargs) -> str:
    return bridge.browser_extract_article()


def _handle_browser_close(bridge: Any, repo_context: Any, **kwargs) -> str:
    return bridge.browser_close()


def _handle_github_create_repo(
    bridge: Any, repo_context: Any, name: str, **kwargs
) -> str:
    return bridge.github_create_repo(
        name,
        kwargs.get("description", ""),
        kwargs.get("private", False),
        kwargs.get("auto_init", True),
        kwargs.get("gitignore_template", ""),
    )


def _handle_github_list_repos(bridge: Any, repo_context: Any, **kwargs) -> str:
    return bridge.github_list_repos(
        kwargs.get("type_filter", "owner"),
        kwargs.get("sort", "updated"),
        int(kwargs.get("limit", 30)),
    )


def _handle_github_create_issue(
    bridge: Any, repo_context: Any, repo: str, title: str, **kwargs
) -> str:
    labels = kwargs.get("labels")
    if labels and isinstance(labels, str):
        labels = [lbl.strip() for lbl in labels.split(",")]
    return bridge.github_create_issue(repo, title, kwargs.get("body", ""), labels)


def _handle_github_list_issues(
    bridge: Any, repo_context: Any, repo: str, **kwargs
) -> str:
    return bridge.github_list_issues(
        repo, kwargs.get("state", "open"), int(kwargs.get("limit", 30))
    )


def _handle_github_read_file(
    bridge: Any, repo_context: Any, repo: str, path: str, **kwargs
) -> str:
    return bridge.github_read_file(repo, path, kwargs.get("ref", "main"))


def _handle_github_write_file(
    bridge: Any, repo_context: Any, repo: str, path: str, content: str, message: str, **kwargs
) -> str:
    return bridge.github_write_file(
        repo, path, content, message,
        kwargs.get("branch", "main"),
        kwargs.get("sha"),
    )


def _handle_github_search_repos(
    bridge: Any, repo_context: Any, query: str, **kwargs
) -> str:
    return bridge.github_search_repos(
        query,
        kwargs.get("sort", "stars"),
        kwargs.get("order", "desc"),
        int(kwargs.get("limit", 30)),
    )


def _handle_github_search_code(
    bridge: Any, repo_context: Any, query: str, **kwargs
) -> str:
    return bridge.github_search_code(query, int(kwargs.get("limit", 30)))


def _handle_github_get_user(bridge: Any, repo_context: Any, **kwargs) -> str:
    return bridge.github_get_user(kwargs.get("username"))


def _handle_website_init(bridge: Any, repo_context: Any, **kwargs) -> str:
    return bridge.website_init(
        kwargs.get("title", "Urgo's Digital Garden"),
        kwargs.get("description", "A collection of thoughts, learnings, and discoveries."),
    )


def _handle_website_write(
    bridge: Any, repo_context: Any, path: str, content: str, **kwargs
) -> str:
    append = kwargs.get("append", False)
    return bridge.website_write_file(path, content, append)


def _handle_website_read(
    bridge: Any, repo_context: Any, path: str, **kwargs
) -> str:
    return bridge.website_read_file(path)


def _handle_website_list(bridge: Any, repo_context: Any, **kwargs) -> str:
    return bridge.website_list_files(
        kwargs.get("directory", ""), kwargs.get("recursive", False)
    )


def _handle_website_create_post(
    bridge: Any, repo_context: Any, title: str, content: str, **kwargs
) -> str:
    tags = kwargs.get("tags")
    if tags and isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",")]
    return bridge.website_create_post(
        title, content, kwargs.get("category", "general"), tags
    )


def _handle_website_create_knowledge(
    bridge: Any, repo_context: Any, title: str, content: str, **kwargs
) -> str:
    return bridge.website_create_knowledge_page(
        title, content, kwargs.get("category", "general"), kwargs.get("source")
    )


def _handle_website_update_about(bridge: Any, repo_context: Any, **kwargs) -> str:
    interests = kwargs.get("interests")
    if interests and isinstance(interests, str):
        interests = [i.strip() for i in interests.split(",")]
    goals = kwargs.get("goals")
    if goals and isinstance(goals, str):
        goals = [g.strip() for g in goals.split(",")]
    return bridge.website_update_about(
        kwargs.get("biography"), interests, goals
    )


def _handle_website_stats(bridge: Any, repo_context: Any, **kwargs) -> str:
    return bridge.website_get_stats()


def _handle_nginx_generate_config(
    bridge: Any, repo_context: Any, domain: str, web_root: str, **kwargs
) -> str:
    return bridge.nginx_generate_config(
        domain,
        web_root,
        kwargs.get("ssl_cert"),
        kwargs.get("ssl_key"),
        kwargs.get("enable_http2", True),
        kwargs.get("rate_limit_zone", "ai_site"),
        int(kwargs.get("rate_limit_rps", 10)),
        int(kwargs.get("rate_limit_burst", 20)),
    )


def _handle_nginx_install_config(
    bridge: Any, repo_context: Any, domain: str, config_content: str, **kwargs
) -> str:
    return bridge.nginx_install_config(domain, config_content, kwargs.get("enable", True))


def _handle_nginx_enable_site(
    bridge: Any, repo_context: Any, domain: str, **kwargs
) -> str:
    return bridge.nginx_enable_site(domain)


def _handle_nginx_disable_site(
    bridge: Any, repo_context: Any, domain: str, **kwargs
) -> str:
    return bridge.nginx_disable_site(domain)


def _handle_nginx_remove_config(
    bridge: Any, repo_context: Any, domain: str, **kwargs
) -> str:
    return bridge.nginx_remove_config(domain)


def _handle_nginx_test_config(bridge: Any, repo_context: Any, **kwargs) -> str:
    return bridge.nginx_test_config()


def _handle_nginx_reload(bridge: Any, repo_context: Any, **kwargs) -> str:
    return bridge.nginx_reload()


def _handle_nginx_status(bridge: Any, repo_context: Any, **kwargs) -> str:
    return bridge.nginx_get_status()


def _handle_discord_send(
    bridge: Any, repo_context: Any, message: str, **kwargs
) -> str:
    # Discord tools return a placeholder for bot-side execution
    return json.dumps({
        "tool": "discord_send_message",
        "params": {"message": message, "type": kwargs.get("type", "info")},
        "status": "pending_bot_execution",
    })


def _handle_discord_embed(
    bridge: Any, repo_context: Any, title: str, description: str, **kwargs
) -> str:
    return json.dumps({
        "tool": "discord_send_embed",
        "params": {"title": title, "description": description, "color": kwargs.get("color")},
        "status": "pending_bot_execution",
    })


def _handle_discord_react(
    bridge: Any, repo_context: Any, emoji: str, **kwargs
) -> str:
    return json.dumps({
        "tool": "discord_add_reaction",
        "params": {"emoji": emoji},
        "status": "pending_bot_execution",
    })


def _handle_discord_upload(
    bridge: Any, repo_context: Any, path: str, **kwargs
) -> str:
    return json.dumps({
        "tool": "discord_upload_file",
        "params": {"path": path},
        "status": "pending_bot_execution",
    })


def _handle_discord_edit(
    bridge: Any, repo_context: Any, message_id: str, content: str, **kwargs
) -> str:
    return json.dumps({
        "tool": "discord_edit_message",
        "params": {"message_id": message_id, "content": content},
        "status": "pending_bot_execution",
    })


def _handle_discord_reply(
    bridge: Any, repo_context: Any, content: str, **kwargs
) -> str:
    return json.dumps({
        "tool": "discord_reply",
        "params": {"content": content},
        "status": "pending_bot_execution",
    })


def _handle_plan_create(
    bridge: Any, repo_context: Any, text: str, **kwargs
) -> str:
    return bridge.plan_echo(text)


def _handle_plan_approve(
    bridge: Any, repo_context: Any, plan_id: str, **kwargs
) -> str:
    return bridge.approve_echo(plan_id)


# ── VPS remote handlers ──

def _handle_vps_test(bridge: Any, repo_context: Any, **kwargs) -> str:
    return bridge.vps_test_connection()


def _handle_vps_exec(
    bridge: Any, repo_context: Any, command: str, **kwargs
) -> str:
    timeout = kwargs.get("timeout", 60)
    return bridge.vps_remote_exec(command, timeout)


def _handle_vps_nginx_status(bridge: Any, repo_context: Any, **kwargs) -> str:
    return bridge.vps_nginx_status()


def _handle_vps_nginx_reload(bridge: Any, repo_context: Any, **kwargs) -> str:
    return bridge.vps_nginx_reload()


def _handle_vps_website_list(
    bridge: Any, repo_context: Any, path: str = "", **kwargs
) -> str:
    return bridge.vps_website_list(path)


def _handle_vps_certbot_renew(
    bridge: Any, repo_context: Any, **kwargs
) -> str:
    dry_run = kwargs.get("dry_run", True)
    return bridge.vps_certbot_renew(dry_run)


# ── Build the global router instance ──


def build_router() -> CLIRouter:
    """Build and return a fully configured CLI router with all command groups."""
    router = CLIRouter()

    # ── repo ──
    router.register_group("repo", "Git repository operations (read-only)")
    router.register_command("repo", "list", _handle_repo_list, "List available repos")
    router.register_command(
        "repo", "status", _handle_repo_status, "Git status for a repo",
        params=[CommandParam("name", "Repo name from allowlist", required=True)],
        positional_args=["name"],
    )
    router.register_command(
        "repo", "last-commit", _handle_repo_last_commit, "Last commit info",
        params=[CommandParam("name", "Repo name from allowlist", required=True)],
        positional_args=["name"],
    )
    router.register_command(
        "repo", "grep", _handle_repo_grep, "Search repo contents (ripgrep/git grep)",
        params=[
            CommandParam("name", "Repo name from allowlist", required=True),
            CommandParam("query", "Search query", required=True),
            CommandParam("path", "Limit search to path prefix"),
        ],
        positional_args=["name", "query"],
    )
    router.register_command(
        "repo", "readfile", _handle_repo_readfile, "Read file lines from a repo",
        params=[
            CommandParam("name", "Repo name from allowlist", required=True),
            CommandParam("path", "Relative file path", required=True),
            CommandParam("start", "Start line (1-based)", default=1, param_type="integer"),
            CommandParam("end", "End line (inclusive)", default=200, param_type="integer"),
        ],
        positional_args=["name", "path"],
    )

    # ── browser ──
    router.register_group("browser", "Web browsing and navigation")
    router.register_command(
        "browser", "navigate", _handle_browser_navigate, "Open a URL in the browser",
        params=[
            CommandParam("url", "URL to navigate to", required=True),
            CommandParam("wait_for_load", "Wait for page load", default=True, param_type="boolean"),
        ],
        positional_args=["url"],
    )
    router.register_command(
        "browser", "snapshot", _handle_browser_snapshot, "Get page content and interactive elements",
        params=[CommandParam("full", "Include full content", default=True, param_type="boolean")],
    )
    router.register_command(
        "browser", "click", _handle_browser_click, "Click an element on the page",
        params=[
            CommandParam("ref", "Element reference number", param_type="integer"),
            CommandParam("selector", "CSS selector"),
        ],
    )
    router.register_command(
        "browser", "type", _handle_browser_type, "Type text into an element",
        params=[
            CommandParam("text", "Text to type", required=True),
            CommandParam("ref", "Element reference number", param_type="integer"),
            CommandParam("selector", "CSS selector"),
            CommandParam("submit", "Press Enter after typing", default=False, param_type="boolean"),
        ],
        positional_args=["text"],
    )
    router.register_command(
        "browser", "search", _handle_browser_search, "Perform a web search",
        params=[
            CommandParam("query", "Search query", required=True),
            CommandParam("engine", "Search engine", default="google"),
        ],
        positional_args=["query"],
    )
    router.register_command(
        "browser", "extract-article", _handle_browser_extract_article,
        "Extract article text from current page",
    )
    router.register_command("browser", "close", _handle_browser_close, "Close the browser")

    # ── github ──
    router.register_group("github", "GitHub API operations")
    router.register_command(
        "github", "create-repo", _handle_github_create_repo, "Create a new GitHub repo",
        params=[
            CommandParam("name", "Repository name", required=True),
            CommandParam("description", "Repo description"),
            CommandParam("private", "Make private", default=False, param_type="boolean"),
            CommandParam("auto_init", "Initialize with README", default=True, param_type="boolean"),
            CommandParam("gitignore_template", "Gitignore template name"),
        ],
        positional_args=["name"],
    )
    router.register_command(
        "github", "list-repos", _handle_github_list_repos, "List your GitHub repos",
        params=[
            CommandParam("type_filter", "Filter: owner, all, member", default="owner"),
            CommandParam("sort", "Sort by: updated, created, pushed", default="updated"),
            CommandParam("limit", "Max results", default=30, param_type="integer"),
        ],
    )
    router.register_command(
        "github", "create-issue", _handle_github_create_issue, "Create an issue",
        params=[
            CommandParam("repo", "Repo (owner/name)", required=True),
            CommandParam("title", "Issue title", required=True),
            CommandParam("body", "Issue body"),
            CommandParam("labels", "Comma-separated labels"),
        ],
        positional_args=["repo", "title"],
    )
    router.register_command(
        "github", "list-issues", _handle_github_list_issues, "List issues",
        params=[
            CommandParam("repo", "Repo (owner/name)", required=True),
            CommandParam("state", "Filter: open, closed, all", default="open"),
            CommandParam("limit", "Max results", default=30, param_type="integer"),
        ],
        positional_args=["repo"],
    )
    router.register_command(
        "github", "read-file", _handle_github_read_file, "Read a file from a repo",
        params=[
            CommandParam("repo", "Repo (owner/name)", required=True),
            CommandParam("path", "File path", required=True),
            CommandParam("ref", "Branch/commit ref", default="main"),
        ],
        positional_args=["repo", "path"],
    )
    router.register_command(
        "github", "write-file", _handle_github_write_file, "Write/update a file in a repo",
        params=[
            CommandParam("repo", "Repo (owner/name)", required=True),
            CommandParam("path", "File path", required=True),
            CommandParam("content", "File content", required=True),
            CommandParam("message", "Commit message", required=True),
            CommandParam("branch", "Target branch", default="main"),
            CommandParam("sha", "File SHA for updates"),
        ],
        positional_args=["repo", "path"],
    )
    router.register_command(
        "github", "search-repos", _handle_github_search_repos, "Search GitHub repos",
        params=[
            CommandParam("query", "Search query", required=True),
            CommandParam("sort", "Sort by: stars, forks, updated", default="stars"),
            CommandParam("order", "Order: desc, asc", default="desc"),
            CommandParam("limit", "Max results", default=30, param_type="integer"),
        ],
        positional_args=["query"],
    )
    router.register_command(
        "github", "search-code", _handle_github_search_code, "Search code on GitHub",
        params=[
            CommandParam("query", "Search query", required=True),
            CommandParam("limit", "Max results", default=30, param_type="integer"),
        ],
        positional_args=["query"],
    )
    router.register_command(
        "github", "get-user", _handle_github_get_user, "Get GitHub user info",
        params=[CommandParam("username", "Username (omit for authenticated user)")],
        positional_args=["username"],
    )

    # ── website ──
    router.register_group("website", "VPS website management")
    router.register_command(
        "website", "init", _handle_website_init, "Initialize website structure",
        params=[
            CommandParam("title", "Site title", default="Urgo's Digital Garden"),
            CommandParam("description", "Site description"),
        ],
    )
    router.register_command(
        "website", "write", _handle_website_write, "Write content to a file",
        params=[
            CommandParam("path", "File path", required=True),
            CommandParam("content", "File content", required=True),
            CommandParam("append", "Append instead of overwrite", default=False, param_type="boolean"),
        ],
        positional_args=["path", "content"],
    )
    router.register_command(
        "website", "read", _handle_website_read, "Read a file",
        params=[CommandParam("path", "File path", required=True)],
        positional_args=["path"],
    )
    router.register_command(
        "website", "list", _handle_website_list, "List files",
        params=[
            CommandParam("directory", "Directory to list", default=""),
            CommandParam("recursive", "List recursively", default=False, param_type="boolean"),
        ],
        positional_args=["directory"],
    )
    router.register_command(
        "website", "create-post", _handle_website_create_post, "Create a blog post",
        params=[
            CommandParam("title", "Post title", required=True),
            CommandParam("content", "Post content (markdown)", required=True),
            CommandParam("category", "Category", default="general"),
            CommandParam("tags", "Comma-separated tags"),
        ],
        positional_args=["title", "content"],
    )
    router.register_command(
        "website", "create-knowledge", _handle_website_create_knowledge,
        "Create a knowledge page",
        params=[
            CommandParam("title", "Page title", required=True),
            CommandParam("content", "Page content (markdown)", required=True),
            CommandParam("category", "Category", default="general"),
            CommandParam("source", "Source reference"),
        ],
        positional_args=["title", "content"],
    )
    router.register_command(
        "website", "update-about", _handle_website_update_about, "Update about page",
        params=[
            CommandParam("biography", "Biography text"),
            CommandParam("interests", "Comma-separated interests"),
            CommandParam("goals", "Comma-separated goals"),
        ],
    )
    router.register_command("website", "stats", _handle_website_stats, "Get site statistics")

    # ── nginx ──
    router.register_group("nginx", "Nginx server configuration")
    router.register_command(
        "nginx", "generate-config", _handle_nginx_generate_config, "Generate nginx config",
        params=[
            CommandParam("domain", "Domain name", required=True),
            CommandParam("web_root", "Web root path", required=True),
            CommandParam("ssl_cert", "SSL cert path"),
            CommandParam("ssl_key", "SSL key path"),
            CommandParam("enable_http2", "Enable HTTP/2", default=True, param_type="boolean"),
            CommandParam("rate_limit_zone", "Rate limit zone name", default="ai_site"),
            CommandParam("rate_limit_rps", "Requests per second", default=10, param_type="integer"),
            CommandParam("rate_limit_burst", "Burst size", default=20, param_type="integer"),
        ],
        positional_args=["domain", "web_root"],
    )
    router.register_command(
        "nginx", "install-config", _handle_nginx_install_config, "Install nginx config",
        params=[
            CommandParam("domain", "Domain name", required=True),
            CommandParam("config_content", "Config content", required=True),
            CommandParam("enable", "Enable site after install", default=True, param_type="boolean"),
        ],
        positional_args=["domain", "config_content"],
    )
    router.register_command(
        "nginx", "enable-site", _handle_nginx_enable_site, "Enable a site",
        params=[CommandParam("domain", "Domain name", required=True)],
        positional_args=["domain"],
    )
    router.register_command(
        "nginx", "disable-site", _handle_nginx_disable_site, "Disable a site",
        params=[CommandParam("domain", "Domain name", required=True)],
        positional_args=["domain"],
    )
    router.register_command(
        "nginx", "remove-config", _handle_nginx_remove_config, "Remove site config",
        params=[CommandParam("domain", "Domain name", required=True)],
        positional_args=["domain"],
    )
    router.register_command("nginx", "test-config", _handle_nginx_test_config, "Test nginx config")
    router.register_command("nginx", "reload", _handle_nginx_reload, "Reload nginx")
    router.register_command("nginx", "status", _handle_nginx_status, "Get nginx status")

    # ── vps ──
    router.register_group("vps", "VPS remote execution via SSH")
    router.register_command(
        "vps", "test", _handle_vps_test, "Test SSH connection to VPS",
    )
    router.register_command(
        "vps", "test-connection", _handle_vps_test, "Test SSH connection to VPS (alias)",
    )
    router.register_command(
        "vps", "exec", _handle_vps_exec, "Execute command on VPS",
        params=[
            CommandParam("command", "Command to execute", required=True),
            CommandParam("timeout", "Timeout in seconds", default=60, param_type="integer"),
        ],
        positional_args=["command"],
    )
    router.register_command(
        "vps", "nginx-status", _handle_vps_nginx_status, "Get nginx status on VPS",
    )
    router.register_command(
        "vps", "nginx-reload", _handle_vps_nginx_reload, "Reload nginx on VPS",
    )
    router.register_command(
        "vps", "website-list", _handle_vps_website_list, "List website files on VPS",
        params=[CommandParam("path", "Subdirectory path", default="")],
        positional_args=["path"],
    )
    router.register_command(
        "vps", "certbot-renew", _handle_vps_certbot_renew, "Renew SSL certificates on VPS",
        params=[CommandParam("dry-run", "Test renewal without changes", default=True, param_type="boolean")],
    )

    # ── discord ──
    router.register_group("discord", "Discord messaging (bot-executed)")
    router.register_command(
        "discord", "send", _handle_discord_send, "Send a message",
        params=[
            CommandParam("message", "Message text", required=True),
            CommandParam("type", "Message type: info, success, warning, error", default="info"),
        ],
        positional_args=["message"],
    )
    router.register_command(
        "discord", "embed", _handle_discord_embed, "Send a rich embed",
        params=[
            CommandParam("title", "Embed title", required=True),
            CommandParam("description", "Embed description", required=True),
            CommandParam("color", "Hex color code"),
        ],
        positional_args=["title", "description"],
    )
    router.register_command(
        "discord", "react", _handle_discord_react, "Add a reaction",
        params=[CommandParam("emoji", "Emoji to react with", required=True)],
        positional_args=["emoji"],
    )
    router.register_command(
        "discord", "upload", _handle_discord_upload, "Upload a file",
        params=[CommandParam("path", "File path", required=True)],
        positional_args=["path"],
    )
    router.register_command(
        "discord", "edit", _handle_discord_edit, "Edit a message",
        params=[
            CommandParam("message_id", "Message ID", required=True),
            CommandParam("content", "New content", required=True),
        ],
        positional_args=["message_id", "content"],
    )
    router.register_command(
        "discord", "reply", _handle_discord_reply, "Reply to the current message",
        params=[CommandParam("content", "Reply text", required=True)],
        positional_args=["content"],
    )

    # ── plan ──
    router.register_group("plan", "Plan creation and approval")
    router.register_command(
        "plan", "create", _handle_plan_create, "Create a plan (returns plan_id)",
        params=[CommandParam("text", "Plan description", required=True)],
        positional_args=["text"],
    )
    router.register_command(
        "plan", "approve", _handle_plan_approve, "Approve a plan by ID",
        params=[CommandParam("plan_id", "Plan ID from 'plan create'", required=True)],
        positional_args=["plan_id"],
    )

    return router


# Global singleton router instance
_router: Optional[CLIRouter] = None


def get_router() -> CLIRouter:
    """Get or create the global CLI router instance."""
    global _router
    if _router is None:
        _router = build_router()
    return _router
