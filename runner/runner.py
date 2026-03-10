"""
OpenClaw Runner — worker that long-polls broker /jobs/next and posts /jobs/{id}/result or /jobs/{id}/fail.
Runs on worker machine (e.g. WSL). Reads config from env (runner.env).
"""
from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import time
import uuid
import logging

import requests

from runner.llm_config import get_llm_config
from runner.llm_loop import run_llm_tool_loop, run_llm_tool_loop_streaming
from runner.redaction import redact_output, should_redact_output
from runner.streaming_client import create_stream_client

logger = logging.getLogger(__name__)

# --- Config from env ---
BROKER_URL = os.environ.get("BROKER_URL", "http://127.0.0.1:8000").strip().rstrip("/")
WORKER_TOKEN = os.environ.get("WORKER_TOKEN", "")
WORKER_ID = os.environ.get("WORKER_ID", "") or socket.gethostname()
RUNNER_STATE_DIR = os.environ.get("RUNNER_STATE_DIR", "/var/lib/openclaw-runner/state")
POLL_INTERVAL_SEC = int(os.environ.get("POLL_INTERVAL_SEC", "10"))
RESULT_TIMEOUT_SEC = int(os.environ.get("RESULT_TIMEOUT_SEC", "300"))

# Repo commands (Sprint 3)
RUNNER_REPOS_BASE = os.environ.get("RUNNER_REPOS_BASE", "/home/user/src")
RUNNER_REPO_ALLOWLIST = os.environ.get("RUNNER_REPO_ALLOWLIST", "/etc/openclaw/repos.json")
RUNNER_CMD_TIMEOUT_SECONDS = int(os.environ.get("RUNNER_CMD_TIMEOUT_SECONDS", "15"))
RUNNER_MAX_OUTPUT_BYTES = int(os.environ.get("RUNNER_MAX_OUTPUT_BYTES", "20000"))
RUNNER_MAX_FILE_BYTES = int(os.environ.get("RUNNER_MAX_FILE_BYTES", "200000"))
RUNNER_MAX_LINES = int(os.environ.get("RUNNER_MAX_LINES", "400"))

RESULT_RETRY_BACKOFF = [0.5, 1.0, 2.0]
RESULT_RETRY_ATTEMPTS = 3

# Streaming configuration
LLM_MODE = os.environ.get("LLM_MODE", "agentic_streaming")  # 'simple' or 'agentic_streaming'
ENABLE_BIDIRECTIONAL_TOOLS = os.environ.get("ENABLE_BIDIRECTIONAL_TOOLS", "true").lower() in ("true", "1", "yes")

# Worker capabilities for broker job routing (Sprint 5): e.g. WORKER_CAPS=llm:vllm,repo_tools or LLM_CAP=llm:vllm
WORKER_CAPS_STR = (os.environ.get("WORKER_CAPS", "") or "").strip()
LLM_CAP = (os.environ.get("LLM_CAP", "") or "").strip()


def _worker_caps_list() -> list[str]:
    """Return list of caps to send as X-Worker-Caps (JSON array). Includes repo_tools and optional LLM cap."""
    if WORKER_CAPS_STR:
        caps = [c.strip() for c in WORKER_CAPS_STR.split(",") if c.strip()]
    else:
        caps = []
    if LLM_CAP and LLM_CAP not in caps:
        caps.append(LLM_CAP)
    if "repo_tools" not in caps:
        caps.append("repo_tools")
    return caps

PLANS_DIR = os.path.join(RUNNER_STATE_DIR, "plans")
REPOS_JSON_FALLBACK = os.path.join(RUNNER_STATE_DIR, "repos.json")


def _ensure_plans_dir() -> None:
    os.makedirs(PLANS_DIR, exist_ok=True)


# --- Repo subsystem (read-only, allowlist, safe subprocess) ---


def load_allowlist() -> dict[str, str]:
    """Load repo allowlist from RUNNER_REPO_ALLOWLIST or fallback to RUNNER_STATE_DIR/repos.json."""
    for path in (RUNNER_REPO_ALLOWLIST, REPOS_JSON_FALLBACK):
        if not path or not os.path.isfile(path):
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                return {}
            return {str(k): str(v) for k, v in data.items()}
        except (OSError, json.JSONDecodeError, TypeError):
            continue
    return {}


def resolve_repo_path(name: str) -> str:
    """Resolve allowlisted repo name to absolute path. Raises ValueError if not allowlisted or path outside base."""
    allowlist = load_allowlist()
    if name not in allowlist:
        raise ValueError("repo not allowlisted")
    value = allowlist[name].strip()
    base_real = os.path.realpath(RUNNER_REPOS_BASE)
    if os.path.isabs(value):
        resolved = os.path.realpath(value)
        if resolved != base_real and not resolved.startswith(base_real + os.sep):
            raise ValueError("repo path outside RUNNER_REPOS_BASE")
        return resolved
    joined = os.path.normpath(os.path.join(RUNNER_REPOS_BASE, value))
    resolved = os.path.realpath(joined)
    if resolved != base_real and not resolved.startswith(base_real + os.sep):
        raise ValueError("repo path outside RUNNER_REPOS_BASE")
    return resolved


def run_cmd(argv: list[str], cwd: str) -> tuple[str, str, int]:
    """Run command with list argv; no shell. Returns (stdout, stderr, returncode). Raises ValueError on timeout."""
    try:
        proc = subprocess.run(
            argv,
            cwd=cwd,
            timeout=RUNNER_CMD_TIMEOUT_SECONDS,
            capture_output=True,
            text=True,
            shell=False,
        )
        return (proc.stdout or "", proc.stderr or "", proc.returncode)
    except subprocess.TimeoutExpired:
        raise ValueError(f"command timed out after {RUNNER_CMD_TIMEOUT_SECONDS}s")


def truncate_bytes(s: str, max_bytes: int) -> str:
    """Truncate string to max_bytes in UTF-8; decode with errors=ignore."""
    encoded = s.encode("utf-8")
    if len(encoded) <= max_bytes:
        return s
    return encoded[:max_bytes].decode("utf-8", errors="ignore")


def _repo_envelope(
    command: str,
    repo: str | None,
    data: dict | None,
    truncated: bool = False,
    error: str | None = None,
) -> str:
    out = {
        "ok": error is None,
        "worker_id": WORKER_ID,
        "command": command,
        "repo": repo,
        "truncated": truncated,
        "data": data,
        "error": error,
    }
    return json.dumps(out)


def _ensure_git_repo(repo_path: str) -> None:
    if not os.path.isdir(os.path.join(repo_path, ".git")):
        raise ValueError("not a git repo")


def _repo_list() -> str:
    allowlist = load_allowlist()
    repos = []
    for name, path_spec in allowlist.items():
        try:
            path = resolve_repo_path(name)
            _ensure_git_repo(path)
            repos.append({"name": name, "path": path})
        except (ValueError, OSError):
            continue
    return _repo_envelope("repo_list", None, {"repos": repos})


def _repo_status(repo_name: str) -> str:
    repo_path = resolve_repo_path(repo_name)
    _ensure_git_repo(repo_path)
    out, err, code = run_cmd(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=repo_path)
    branch = (out + err).strip().split("\n")[0] if (out or err) else ""
    out2, err2, _ = run_cmd(["git", "status", "--porcelain=v1"], cwd=repo_path)
    porcelain = (out2 + err2).strip()
    dirty = bool(porcelain)
    truncated = False
    if len(porcelain.encode("utf-8")) > RUNNER_MAX_OUTPUT_BYTES:
        porcelain = truncate_bytes(porcelain, RUNNER_MAX_OUTPUT_BYTES)
        truncated = True
    data = {"repo": repo_name, "branch": branch, "dirty": dirty, "porcelain": porcelain}
    return _repo_envelope("repo_status", repo_name, data, truncated=truncated)


def _repo_last_commit(repo_name: str) -> str:
    repo_path = resolve_repo_path(repo_name)
    _ensure_git_repo(repo_path)
    out, err, code = run_cmd(
        ["git", "log", "-1", "--pretty=format:%H%n%an%n%ad%n%s"],
        cwd=repo_path,
    )
    if code != 0:
        raise ValueError((out + err).strip() or "git log failed")
    lines = out.strip().split("\n")
    hash_s = lines[0] if len(lines) > 0 else ""
    author = lines[1] if len(lines) > 1 else ""
    date = lines[2] if len(lines) > 2 else ""
    subject = lines[3] if len(lines) > 3 else ""
    data = {"hash": hash_s, "author": author, "date": date, "subject": subject}
    return _repo_envelope("repo_last_commit", repo_name, data)


def _repo_grep(repo_name: str, query: str, path_prefix: str) -> str:
    repo_path = resolve_repo_path(repo_name)
    _ensure_git_repo(repo_path)
    rg_path = shutil.which("rg")
    argv = []
    if rg_path:
        argv = ["rg", "-n", "--no-heading", "--smart-case", query]
        if path_prefix:
            argv.append(path_prefix)
    else:
        argv = ["git", "grep", "-n", query, "--"]
        if path_prefix:
            argv.append(path_prefix)
    out, err, code = run_cmd(argv, cwd=repo_path)
    if code not in (0, 1):
        raise ValueError((out + err).strip() or "search failed")
    combined = out.strip()
    truncated = False
    if len(combined.encode("utf-8")) > RUNNER_MAX_OUTPUT_BYTES:
        combined = truncate_bytes(combined, RUNNER_MAX_OUTPUT_BYTES)
        truncated = True
    return _repo_envelope("repo_grep", repo_name, {"matches": combined}, truncated=truncated)


def _repo_readfile(repo_name: str, path: str, start: int, end: int) -> str:
    if path.startswith("/") or ".." in os.path.normpath(path).split(os.sep):
        raise ValueError("path must be relative and not contain ..")
    repo_path = resolve_repo_path(repo_name)
    _ensure_git_repo(repo_path)
    if start < 1:
        raise ValueError("start must be >= 1")
    if end < start:
        raise ValueError("end must be >= start")
    if (end - start + 1) > RUNNER_MAX_LINES:
        raise ValueError(f"line range exceeds RUNNER_MAX_LINES ({RUNNER_MAX_LINES})")
    abs_path = os.path.normpath(os.path.join(repo_path, path))
    real_abs = os.path.realpath(abs_path)
    real_repo = os.path.realpath(repo_path)
    if real_abs != real_repo and not real_abs.startswith(real_repo + os.sep):
        raise ValueError("path outside repo")
    if not os.path.isfile(real_abs):
        raise ValueError("not a file or not found")
    size = os.path.getsize(real_abs)
    if size > RUNNER_MAX_FILE_BYTES:
        raise ValueError(f"file exceeds RUNNER_MAX_FILE_BYTES ({RUNNER_MAX_FILE_BYTES})")
    with open(real_abs, "r", encoding="utf-8", errors="replace") as f:
        lines = f.readlines()
    max_line = len(lines)
    start1 = max(1, min(start, max_line))
    end1 = min(end, max_line)
    if end1 < start1:
        end1 = start1
    content_lines = lines[start1 - 1 : end1]
    content = "".join(content_lines)
    truncated = False
    if (end - start + 1) > RUNNER_MAX_LINES:
        truncated = True
    # Cap lines we actually return
    if len(content_lines) > RUNNER_MAX_LINES:
        content = "".join(content_lines[: RUNNER_MAX_LINES])
        truncated = True
    data = {"path": path, "start": start1, "end": end1, "content": content}
    return _repo_envelope("repo_readfile", repo_name, data, truncated=truncated)


def _plan_echo_impl(text: str) -> str:
    """Echo plan scaffold; used by run_job(plan_echo) and by LLM tool bridge."""
    plan_id = str(uuid.uuid4())
    summary = f"Echo plan for: {text[:200]}" if text else "Echo plan (no payload)"
    plan_obj = {
        "type": "plan",
        "plan_id": plan_id,
        "summary": summary,
        "proposed_actions": ["(no-op)"],
        "requires_approval": True,
    }
    path = os.path.join(PLANS_DIR, f"{plan_id}.json")
    with open(path, "w") as f:
        json.dump(plan_obj, f, indent=2)
    return json.dumps(plan_obj)


def _approve_echo_impl(plan_id: str) -> str:
    """Approve echo scaffold; used by run_job(approve_echo) and by LLM tool bridge."""
    path = os.path.join(PLANS_DIR, f"{plan_id}.json")
    if not os.path.isfile(path):
        raise ValueError("unknown plan_id")
    approval = {
        "type": "approval",
        "plan_id": plan_id,
        "status": "approved",
        "applied": False,
        "note": "no-op (scaffold)",
    }
    return json.dumps(approval)


def _post_with_retry(method: str, url: str, headers: dict, json_body: dict, timeout: int = 30) -> bool:
    """
    POST to broker; retry on 5xx or network errors. Return True if terminal success (200).
    - 200 -> success (terminal)
    - 4xx (including 404) -> terminal, no retry; return False
    - 5xx or RequestException -> retry up to RESULT_RETRY_ATTEMPTS with backoff
    """
    for attempt in range(RESULT_RETRY_ATTEMPTS):
        try:
            r = requests.post(url, headers=headers, json=json_body, timeout=timeout)
            if r.status_code == 200:
                return True
            if 400 <= r.status_code < 500:
                logger.warning(f"[{method}] {r.status_code}: {r.text}")
                return False
            # 5xx or other
            logger.warning(f"[{method}] {r.status_code} (attempt {attempt + 1}/{RESULT_RETRY_ATTEMPTS})")
        except requests.RequestException as e:
            logger.warning(f"[{method}] request error (attempt {attempt + 1}/{RESULT_RETRY_ATTEMPTS}): {e}")
        if attempt < RESULT_RETRY_ATTEMPTS - 1:
            time.sleep(RESULT_RETRY_BACKOFF[attempt])
    return False


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )
    if not WORKER_TOKEN:
        logger.error("WORKER_TOKEN not set")
        sys.exit(1)
    _ensure_plans_dir()
    caps_list = _worker_caps_list()
    headers = {"X-Worker-Token": WORKER_TOKEN, "X-Worker-Id": WORKER_ID}
    if caps_list:
        headers["X-Worker-Caps"] = json.dumps(caps_list)
    logger.info(f"started; broker={BROKER_URL} worker_id={WORKER_ID} poll_interval={POLL_INTERVAL_SEC}s caps={caps_list}")
    while True:
        try:
            r = requests.get(f"{BROKER_URL}/jobs/next", headers=headers, timeout=30)
            r.raise_for_status()
            data = r.json()
            job = data.get("job")
            if not job:
                time.sleep(POLL_INTERVAL_SEC)
                continue
            job_id = job["id"]
            command = job.get("command", "")
            payload = job.get("payload", "")
            logger.info(f"claimed job id={job_id} command={command}")

            try:
                result = run_job(command, payload, job_id)
                if should_redact_output():
                    result = redact_output(result)
                ok = _post_with_retry(
                    "result",
                    f"{BROKER_URL}/jobs/{job_id}/result",
                    headers,
                    {"result": result},
                )
                if ok:
                    logger.info(f"result posted id={job_id}")
            except Exception as e:
                logger.exception("job failed with exception")
                err_msg = str(e) or "unknown"
                if should_redact_output():
                    err_msg = redact_output(err_msg)
                logger.error(f"job failed: {err_msg}")
                ok = _post_with_retry(
                    "fail",
                    f"{BROKER_URL}/jobs/{job_id}/fail",
                    headers,
                    {"error": err_msg},
                )
                if ok:
                    logger.info(f"fail posted id={job_id}")

        except requests.RequestException as e:
            logger.warning(f"request error: {e}")
            time.sleep(POLL_INTERVAL_SEC)
        except Exception as e:
            logger.exception(f"unexpected polling error: {e}")
            time.sleep(POLL_INTERVAL_SEC)


# --- Embedding subsystem (runs on WSL, saves VPS CPU) ---
# Model loaded once, reused across embed jobs
_embedding_model = None
_embedding_model_name = os.environ.get("EMBEDDING_MODEL", "Qwen/Qwen3-Embedding-0.6B")

def _get_embedding_model():
    """Lazy-load the embedding model (sentence-transformers)."""
    global _embedding_model
    if _embedding_model is None:
        try:
            from sentence_transformers import SentenceTransformer
            logger.info(f"Loading embedding model: {_embedding_model_name}")
            # Auto-detect CUDA or fall back to CPU
            import torch
            device = "cuda" if torch.cuda.is_available() else "cpu"
            _embedding_model = SentenceTransformer(_embedding_model_name, device=device)
            logger.info(f"Embedding model loaded on {device}")
        except ImportError as e:
            raise ImportError(f"sentence-transformers required for embeddings: {e}")
    return _embedding_model

def _embed_text(text: str) -> dict:
    """Generate embeddings for text. Returns dict with embedding array and metadata."""
    if not text:
        raise ValueError("text is required for embedding")
    model = _get_embedding_model()
    # Truncate to safe limit
    truncated = text[:10000]
    embedding = model.encode(truncated, convert_to_numpy=True)
    return {
        "embedding": embedding.tolist(),
        "dimension": len(embedding),
        "model": _embedding_model_name,
        "device": str(model.device),
    }


def run_job(command: str, payload: str, job_id: str = "") -> str:
    """Execute the job and return result string (plain or JSON string)."""
    if command == "ping":
        return f"pong: {payload}"

    if command == "capabilities":
        caps = [
            "ping",
            "capabilities",
            "plan_echo",
            "approve_echo",
            "repo_list",
            "repo_status",
            "repo_last_commit",
            "repo_grep",
            "repo_readfile",
            "embed",
            "llm_task",
            "llm_agentic",  # New streaming agentic mode
        ]
        # Add browser capabilities if playwright is available
        try:
            from runner.browser_tools import get_browser_capabilities
            browser_caps = get_browser_capabilities()
            for cap in browser_caps:
                if cap not in caps:
                    caps.append(cap)
        except ImportError:
            pass
        # Add GitHub capabilities
        try:
            from runner.github_tools import get_github_capabilities
            github_caps = get_github_capabilities()
            for cap in github_caps:
                if cap not in caps:
                    caps.append(cap)
        except ImportError:
            pass
        # Add VPS website capabilities
        try:
            from runner.vps_website_tools import get_vps_website_capabilities
            vps_caps = get_vps_website_capabilities()
            for cap in vps_caps:
                if cap not in caps:
                    caps.append(cap)
        except ImportError:
            pass
        # Add Nginx capabilities
        try:
            from runner.nginx_configurator import get_nginx_capabilities
            nginx_caps = get_nginx_capabilities()
            for cap in nginx_caps:
                if cap not in caps:
                    caps.append(cap)
        except ImportError:
            pass
        worker_caps = _worker_caps_list()
        if "llm_task" not in caps:
            caps.append("llm_task")
        for c in worker_caps:
            if c.startswith("llm:") and c not in caps:
                caps.append(c)
        out = {
            "worker_id": WORKER_ID,
            "capabilities": caps,
            "version": "2.0-agentic",
            "streaming": {
                "enabled": ENABLE_BIDIRECTIONAL_TOOLS,
                "mode": LLM_MODE,
                "heartbeat_seconds": int(os.environ.get("STREAMING_HEARTBEAT_SECONDS", "30")),
            },
        }
        return json.dumps(out)

    if command == "plan_echo":
        return _plan_echo_impl(payload or "")

    if command == "approve_echo":
        plan_id = (payload or "").strip()
        if not plan_id:
            raise ValueError("plan_id required")
        return _approve_echo_impl(plan_id)

    # Repo commands (read-only; return JSON envelope)
    if command == "repo_list":
        return _repo_list()

    if command == "repo_status":
        try:
            obj = json.loads(payload) if payload else {}
        except json.JSONDecodeError:
            raise ValueError("payload must be valid JSON")
        repo = obj.get("repo")
        if not repo:
            raise ValueError("repo required")
        return _repo_status(repo)

    if command == "repo_last_commit":
        try:
            obj = json.loads(payload) if payload else {}
        except json.JSONDecodeError:
            raise ValueError("payload must be valid JSON")
        repo = obj.get("repo")
        if not repo:
            raise ValueError("repo required")
        return _repo_last_commit(repo)

    if command == "repo_grep":
        try:
            obj = json.loads(payload) if payload else {}
        except json.JSONDecodeError:
            raise ValueError("payload must be valid JSON")
        repo = obj.get("repo")
        query = obj.get("query", "")
        path_prefix = obj.get("path", "") or ""
        if not repo:
            raise ValueError("repo required")
        return _repo_grep(repo, query, path_prefix)

    if command == "repo_readfile":
        try:
            obj = json.loads(payload) if payload else {}
        except json.JSONDecodeError:
            raise ValueError("payload must be valid JSON")
        repo = obj.get("repo")
        path = obj.get("path", "")
        start = int(obj.get("start", 1))
        end = int(obj.get("end", 200))
        if not repo:
            raise ValueError("repo required")
        if not path:
            raise ValueError("path required")
        return _repo_readfile(repo, path, start, end)

    if command == "llm_task":
        try:
            payload_obj = json.loads(payload) if payload else {}
        except json.JSONDecodeError:
            raise ValueError("llm_task payload must be valid JSON")
        prompt = (payload_obj.get("prompt") or "").strip()
        if not prompt:
            raise ValueError("llm_task payload must include prompt")
        config = get_llm_config()
        if not config.get("base_url") or not config.get("model"):
            raise ValueError("LLM not configured (set LLM_BASE_URL and LLM_MODEL)")
        tools_list = payload_obj.get("tools")
        if not tools_list:
            tools_list = list(config.get("allowed_tools", []))
        allowed_set = config.get("allowed_tools") or set()
        if not allowed_set.issuperset(tools_list):
            raise ValueError("llm_task tools must be subset of LLM_ALLOWED_TOOLS")
        repo_context = payload_obj.get("repo_context")
        conversation_history = payload_obj.get("conversation_history")
        max_steps = payload_obj["max_steps"] if "max_steps" in payload_obj else config.get("max_steps", 6)
        max_steps = int(max_steps)
        if max_steps < 1:
            max_steps = 1
        # Check if streaming mode is requested
        streaming = payload_obj.get("streaming", False) or LLM_MODE == "agentic_streaming"

        # Use job_id from payload or from the job parameter (for runner-claimed jobs)
        job_id_for_streaming = payload_obj.get("job_id") or job_id

        # Create streaming client if in streaming mode
        stream_client = None
        if streaming and job_id_for_streaming:
            stream_client = create_stream_client(job_id_for_streaming)
            logger.info(f"Streaming mode enabled for job {job_id_for_streaming}")

        # Bridge for tool_registry.dispatch: methods + allowed_tools, worker_id
        # Import browser tools
        from runner.browser_tools import (
            browser_navigate, browser_snapshot, browser_click, browser_type,
            browser_search, browser_extract_article, browser_close,
            get_browser_capabilities
        )
        # Import GitHub tools
        from runner.github_tools import (
            github_create_repo, github_list_repos, github_create_issue, github_list_issues,
            github_read_file, github_write_file, github_search_repos, github_search_code,
            github_get_user, get_github_capabilities
        )
        # Import VPS website tools
        from runner.vps_website_tools import (
            website_init, website_write_file, website_read_file, website_list_files,
            website_create_post, website_create_knowledge_page, website_update_about,
            website_get_stats, get_vps_website_capabilities
        )
        # Import Nginx configurator
        from runner.nginx_configurator import (
            nginx_generate_config, nginx_install_config, nginx_enable_site,
            nginx_disable_site, nginx_remove_config, nginx_test_config,
            nginx_reload, nginx_get_status, get_nginx_capabilities
        )

        class _Bridge:
            allowed_tools = allowed_set
            worker_id = WORKER_ID
            def repo_list(_self):
                return _repo_list()
            def repo_status(_self, repo: str):
                return _repo_status(repo)
            def repo_last_commit(_self, repo: str):
                return _repo_last_commit(repo)
            def repo_grep(_self, repo: str, query: str, path: str):
                return _repo_grep(repo, query, path)
            def repo_readfile(_self, repo: str, path: str, start: int, end: int):
                return _repo_readfile(repo, path, start, end)
            def plan_echo(_self, text: str):
                return _plan_echo_impl(text)
            def approve_echo(_self, plan_id: str):
                return _approve_echo_impl(plan_id)
            # Browser tools
            def browser_navigate(_self, url: str, wait_for_load: bool = True):
                return browser_navigate(url, wait_for_load)
            def browser_snapshot(_self, full_content: bool = True):
                return browser_snapshot(full_content)
            def browser_click(_self, ref: Optional[int] = None, selector: Optional[str] = None):
                return browser_click(ref, selector)
            def browser_type(_self, text: str, ref: Optional[int] = None, selector: Optional[str] = None, submit: bool = False):
                return browser_type(text, ref, selector, submit)
            def browser_search(_self, query: str, engine: str = "google"):
                return browser_search(query, engine)
            def browser_extract_article(_self):
                return browser_extract_article()
            def browser_close(_self):
                return browser_close()
            # GitHub tools
            def github_create_repo(_self, name: str, description: str = "", private: bool = False,
                                  auto_init: bool = True, gitignore_template: str = ""):
                return github_create_repo(name, description, private, auto_init, gitignore_template)
            def github_list_repos(_self, type_filter: str = "owner", sort: str = "updated", limit: int = 30):
                return github_list_repos(type_filter, sort, limit)
            def github_create_issue(_self, repo: str, title: str, body: str = "", labels: Optional[list] = None):
                return github_create_issue(repo, title, body, labels)
            def github_list_issues(_self, repo: str, state: str = "open", limit: int = 30):
                return github_list_issues(repo, state, limit)
            def github_read_file(_self, repo: str, path: str, ref: str = "main"):
                return github_read_file(repo, path, ref)
            def github_write_file(_self, repo: str, path: str, content: str, message: str,
                                 branch: str = "main", sha: Optional[str] = None):
                return github_write_file(repo, path, content, message, branch, sha)
            def github_search_repos(_self, query: str, sort: str = "stars", order: str = "desc", limit: int = 30):
                return github_search_repos(query, sort, order, limit)
            def github_search_code(_self, query: str, limit: int = 30):
                return github_search_code(query, limit)
            def github_get_user(_self, username: Optional[str] = None):
                return github_get_user(username)
            # VPS Website tools
            def website_init(_self, site_title: str = "Urgo's Digital Garden", description: str = "A collection of thoughts, learnings, and discoveries."):
                return website_init(site_title, description)
            def website_write_file(_self, path: str, content: str, append: bool = False):
                return website_write_file(path, content, append)
            def website_read_file(_self, path: str):
                return website_read_file(path)
            def website_list_files(_self, directory: str = "", recursive: bool = False):
                return website_list_files(directory, recursive)
            def website_create_post(_self, title: str, content: str, category: str = "general", tags: Optional[list] = None):
                return website_create_post(title, content, category, tags)
            def website_create_knowledge_page(_self, title: str, content: str, category: str = "general", source: Optional[str] = None):
                return website_create_knowledge_page(title, content, category, source)
            def website_update_about(_self, biography: Optional[str] = None, interests: Optional[list] = None, current_goals: Optional[list] = None):
                return website_update_about(biography, interests, current_goals)
            def website_get_stats(_self):
                return website_get_stats()
            # Nginx Management tools
            def nginx_generate_config(_self, domain: str, web_root: str, ssl_cert: Optional[str] = None, ssl_key: Optional[str] = None, enable_http2: bool = True, rate_limit_zone: str = "ai_site", rate_limit_rps: int = 10, rate_limit_burst: int = 20):
                return nginx_generate_config(domain, web_root, ssl_cert, ssl_key, enable_http2, rate_limit_zone, rate_limit_rps, rate_limit_burst)
            def nginx_install_config(_self, domain: str, config_content: str, enable: bool = True):
                return nginx_install_config(domain, config_content, enable)
            def nginx_enable_site(_self, domain: str):
                return nginx_enable_site(domain)
            def nginx_disable_site(_self, domain: str):
                return nginx_disable_site(domain)
            def nginx_remove_config(_self, domain: str):
                return nginx_remove_config(domain)
            def nginx_test_config(_self):
                return nginx_test_config()
            def nginx_reload(_self):
                return nginx_reload()
            def nginx_get_status(_self):
                return nginx_get_status()
        bridge = _Bridge()

        if stream_client and stream_client.enabled:
            # Use streaming version
            envelope = run_llm_tool_loop_streaming(
                prompt, tools_list, repo_context, max_steps, config, bridge,
                conversation_history, stream_client
            )
        else:
            # Use standard version
            envelope = run_llm_tool_loop(prompt, tools_list, repo_context, max_steps, config, bridge, conversation_history)

        return json.dumps(envelope)

    if command == "llm_agentic":
        # Agentic streaming mode - always uses streaming
        try:
            payload_obj = json.loads(payload) if payload else {}
        except json.JSONDecodeError:
            raise ValueError("llm_agentic payload must be valid JSON")

        prompt = (payload_obj.get("prompt") or "").strip()
        if not prompt:
            raise ValueError("llm_agentic payload must include prompt")

        # Use job_id from payload or from the job parameter
        job_id_for_streaming = payload_obj.get("job_id") or job_id
        if not job_id_for_streaming:
            raise ValueError("llm_agentic requires job_id for streaming")

        config = get_llm_config()
        if not config.get("base_url") or not config.get("model"):
            raise ValueError("LLM not configured (set LLM_BASE_URL and LLM_MODEL)")

        tools_list = payload_obj.get("tools") or list(config.get("allowed_tools", []))
        repo_context = payload_obj.get("repo_context")
        conversation_history = payload_obj.get("conversation_history")
        max_steps = payload_obj.get("max_steps", config.get("max_steps", 10))
        max_steps = int(max_steps)
        if max_steps < 1:
            max_steps = 1

        # Create streaming client
        stream_client = create_stream_client(job_id_for_streaming)
        if not stream_client.enabled:
            logger.warning(f"Streaming not enabled for job {job_id_for_streaming}, falling back to standard mode")

        # Post initial message
        stream_client.post_message("Starting agentic task...", "info")

        # Build bridge
        bridge = _Bridge()

        # Run streaming loop
        envelope = run_llm_tool_loop_streaming(
            prompt, tools_list, repo_context, max_steps, config, bridge,
            conversation_history, stream_client
        )

        return json.dumps(envelope)

    if command == "embed":
        try:
            obj = json.loads(payload) if payload else {}
        except json.JSONDecodeError:
            raise ValueError("embed payload must be valid JSON")
        text = obj.get("text", "").strip()
        if not text:
            raise ValueError("text is required for embedding")
        result = _embed_text(text)
        return json.dumps(result)

    return f"unknown command: {command}"


if __name__ == "__main__":
    main()