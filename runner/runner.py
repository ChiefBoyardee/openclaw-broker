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

import requests

from runner.llm_config import get_llm_config
from runner.llm_loop import run_llm_tool_loop

# --- Config from env ---
BROKER_URL = os.environ.get("BROKER_URL", "http://127.0.0.1:8000").strip().rstrip("/")
WORKER_TOKEN = os.environ.get("WORKER_TOKEN", "")
WORKER_ID = os.environ.get("WORKER_ID", "") or socket.gethostname()
RUNNER_STATE_DIR = os.environ.get("RUNNER_STATE_DIR", "/var/lib/openclaw-runner/state")
POLL_INTERVAL_SEC = int(os.environ.get("POLL_INTERVAL_SEC", "10"))
RESULT_TIMEOUT_SEC = int(os.environ.get("RESULT_TIMEOUT_SEC", "300"))

# Repo commands (Sprint 3)
RUNNER_REPOS_BASE = os.environ.get("RUNNER_REPOS_BASE", "/home/jay/src")
RUNNER_REPO_ALLOWLIST = os.environ.get("RUNNER_REPO_ALLOWLIST", "/etc/openclaw/repos.json")
RUNNER_CMD_TIMEOUT_SECONDS = int(os.environ.get("RUNNER_CMD_TIMEOUT_SECONDS", "15"))
RUNNER_MAX_OUTPUT_BYTES = int(os.environ.get("RUNNER_MAX_OUTPUT_BYTES", "20000"))
RUNNER_MAX_FILE_BYTES = int(os.environ.get("RUNNER_MAX_FILE_BYTES", "200000"))
RUNNER_MAX_LINES = int(os.environ.get("RUNNER_MAX_LINES", "400"))

RESULT_RETRY_BACKOFF = [0.5, 1.0, 2.0]
RESULT_RETRY_ATTEMPTS = 3

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
                print(f"[runner] {method} {r.status_code}: {r.text}", file=sys.stderr)
                return False
            # 5xx or other
            print(f"[runner] {method} {r.status_code} (attempt {attempt + 1}/{RESULT_RETRY_ATTEMPTS})", file=sys.stderr)
        except requests.RequestException as e:
            print(f"[runner] {method} request error (attempt {attempt + 1}/{RESULT_RETRY_ATTEMPTS}): {e}", file=sys.stderr)
        if attempt < RESULT_RETRY_ATTEMPTS - 1:
            time.sleep(RESULT_RETRY_BACKOFF[attempt])
    return False


def main():
    if not WORKER_TOKEN:
        print("[runner] ERROR: WORKER_TOKEN not set", file=sys.stderr)
        sys.exit(1)
    _ensure_plans_dir()
    caps_list = _worker_caps_list()
    headers = {"X-Worker-Token": WORKER_TOKEN, "X-Worker-Id": WORKER_ID}
    if caps_list:
        headers["X-Worker-Caps"] = json.dumps(caps_list)
    print(f"[runner] started; broker={BROKER_URL} worker_id={WORKER_ID} poll_interval={POLL_INTERVAL_SEC}s caps={caps_list}")
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
            print(f"[runner] claimed job id={job_id} command={command}")

            try:
                result = run_job(command, payload)
                ok = _post_with_retry(
                    "result",
                    f"{BROKER_URL}/jobs/{job_id}/result",
                    headers,
                    {"result": result},
                )
                if ok:
                    print(f"[runner] result posted id={job_id}")
            except Exception as e:
                err_msg = str(e) or "unknown"
                print(f"[runner] job failed: {err_msg}", file=sys.stderr)
                ok = _post_with_retry(
                    "fail",
                    f"{BROKER_URL}/jobs/{job_id}/fail",
                    headers,
                    {"error": err_msg},
                )
                if ok:
                    print(f"[runner] fail posted id={job_id}")

        except requests.RequestException as e:
            print(f"[runner] request error: {e}", file=sys.stderr)
            time.sleep(POLL_INTERVAL_SEC)
        except Exception as e:
            print(f"[runner] error: {e}", file=sys.stderr)
            time.sleep(POLL_INTERVAL_SEC)


def run_job(command: str, payload: str) -> str:
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
        ]
        worker_caps = _worker_caps_list()
        if "llm_task" not in caps:
            caps.append("llm_task")
        for c in worker_caps:
            if c.startswith("llm:") and c not in caps:
                caps.append(c)
        out = {
            "worker_id": WORKER_ID,
            "capabilities": caps,
            "version": "mvp",
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
        max_steps = payload_obj["max_steps"] if "max_steps" in payload_obj else config.get("max_steps", 6)
        max_steps = int(max_steps)
        if max_steps < 1:
            max_steps = 1
        # Bridge for tool_registry.dispatch: methods + allowed_tools, worker_id
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
        bridge = _Bridge()
        envelope = run_llm_tool_loop(prompt, tools_list, repo_context, max_steps, config, bridge)
        return json.dumps(envelope)

    return f"unknown command: {command}"


if __name__ == "__main__":
    main()