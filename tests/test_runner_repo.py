"""
Runner-focused tests: allowlist loading and path resolution, readfile validation, grep tool choice (rg vs git grep).
"""
import json
import os
import sys
import tempfile
from unittest.mock import patch

import pytest

# Add repo root so runner package is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import after path is set; use fresh env in tests
import runner.runner as runner_module


def test_load_allowlist_from_temp_file():
    with tempfile.TemporaryDirectory() as tmp:
        repos_path = os.path.join(tmp, "repos.json")
        with open(repos_path, "w", encoding="utf-8") as f:
            json.dump({"knucklebot": "knucklebot", "urgo_ai": "urgo/urgo_ai"}, f)
        with patch.dict(os.environ, {"RUNNER_REPO_ALLOWLIST": repos_path, "RUNNER_REPOS_BASE": tmp, "RUNNER_STATE_DIR": os.path.join(tmp, "state")}, clear=False):
            # Reload so module picks up env
            import importlib
            importlib.reload(runner_module)
            allowlist = runner_module.load_allowlist()
            assert allowlist == {"knucklebot": "knucklebot", "urgo_ai": "urgo/urgo_ai"}
            path = runner_module.resolve_repo_path("knucklebot")
            assert os.path.realpath(path) == os.path.realpath(os.path.join(tmp, "knucklebot"))
            path2 = runner_module.resolve_repo_path("urgo_ai")
            assert os.path.realpath(path2) == os.path.realpath(os.path.join(tmp, "urgo", "urgo_ai"))


def test_resolve_repo_path_rejects_path_traversal():
    with tempfile.TemporaryDirectory() as tmp:
        base = os.path.join(tmp, "base")
        os.makedirs(base, exist_ok=True)
        repos_path = os.path.join(tmp, "repos.json")
        # Allowlist entry that would escape base
        with open(repos_path, "w", encoding="utf-8") as f:
            json.dump({"evil": "../other"}, f)
        with patch.dict(os.environ, {"RUNNER_REPO_ALLOWLIST": repos_path, "RUNNER_REPOS_BASE": base, "RUNNER_STATE_DIR": os.path.join(tmp, "state")}, clear=False):
            import importlib
            importlib.reload(runner_module)
            with pytest.raises(ValueError, match="outside RUNNER_REPOS_BASE"):
                runner_module.resolve_repo_path("evil")


def test_resolve_repo_path_rejects_absolute_outside_base():
    with tempfile.TemporaryDirectory() as tmp:
        base = os.path.join(tmp, "base")
        other = os.path.join(tmp, "other")
        os.makedirs(base, exist_ok=True)
        os.makedirs(other, exist_ok=True)
        repos_path = os.path.join(tmp, "repos.json")
        with open(repos_path, "w", encoding="utf-8") as f:
            json.dump({"outside": other}, f)
        with patch.dict(os.environ, {"RUNNER_REPO_ALLOWLIST": repos_path, "RUNNER_REPOS_BASE": base, "RUNNER_STATE_DIR": os.path.join(tmp, "state")}, clear=False):
            import importlib
            importlib.reload(runner_module)
            with pytest.raises(ValueError, match="outside RUNNER_REPOS_BASE"):
                runner_module.resolve_repo_path("outside")


def test_resolve_repo_path_not_allowlisted():
    with tempfile.TemporaryDirectory() as tmp:
        repos_path = os.path.join(tmp, "repos.json")
        with open(repos_path, "w", encoding="utf-8") as f:
            json.dump({"only": "repo"}, f)
        with patch.dict(os.environ, {"RUNNER_REPO_ALLOWLIST": repos_path, "RUNNER_REPOS_BASE": tmp, "RUNNER_STATE_DIR": os.path.join(tmp, "state")}, clear=False):
            import importlib
            importlib.reload(runner_module)
            with pytest.raises(ValueError, match="repo not allowlisted"):
                runner_module.resolve_repo_path("other")


def test_load_allowlist_fallback_to_state_dir():
    with tempfile.TemporaryDirectory() as tmp:
        state_dir = os.path.join(tmp, "state")
        os.makedirs(state_dir, exist_ok=True)
        fallback_path = os.path.join(state_dir, "repos.json")
        with open(fallback_path, "w", encoding="utf-8") as f:
            json.dump({"fallback_repo": "fp"}, f)
        # Primary path that does not exist
        with patch.dict(os.environ, {
            "RUNNER_REPO_ALLOWLIST": os.path.join(tmp, "nonexistent", "repos.json"),
            "RUNNER_REPOS_BASE": tmp,
            "RUNNER_STATE_DIR": state_dir,
        }, clear=False):
            import importlib
            importlib.reload(runner_module)
            allowlist = runner_module.load_allowlist()
            # Fallback is tried second; primary doesn't exist so fallback is used
            assert "fallback_repo" in allowlist
            assert allowlist["fallback_repo"] == "fp"


def test_repo_readfile_validation_start_end():
    """run_job repo_readfile: start < 1 or end < start or line range > MAX_LINES raises."""
    with tempfile.TemporaryDirectory() as tmp:
        repo_dir = os.path.join(tmp, "repo")
        os.makedirs(repo_dir, exist_ok=True)
        os.makedirs(os.path.join(repo_dir, ".git"), exist_ok=True)
        with open(os.path.join(repo_dir, "f.txt"), "w") as f:
            f.write("line1\nline2\n")
        repos_path = os.path.join(tmp, "repos.json")
        with open(repos_path, "w", encoding="utf-8") as f:
            json.dump({"r": repo_dir}, f)
        with patch.dict(os.environ, {
            "RUNNER_REPO_ALLOWLIST": repos_path,
            "RUNNER_REPOS_BASE": tmp,
            "RUNNER_STATE_DIR": os.path.join(tmp, "state"),
        }, clear=False):
            import importlib
            importlib.reload(runner_module)
            with pytest.raises(ValueError, match="start must be"):
                runner_module.run_job("repo_readfile", json.dumps({"repo": "r", "path": "f.txt", "start": 0, "end": 10}))
            with pytest.raises(ValueError, match="end must be"):
                runner_module.run_job("repo_readfile", json.dumps({"repo": "r", "path": "f.txt", "start": 5, "end": 3}))
            max_lines = runner_module.RUNNER_MAX_LINES
            with pytest.raises(ValueError, match="RUNNER_MAX_LINES"):
                runner_module.run_job("repo_readfile", json.dumps({"repo": "r", "path": "f.txt", "start": 1, "end": 1 + max_lines}))


def test_repo_readfile_rejects_path_traversal():
    with tempfile.TemporaryDirectory() as tmp:
        repo_dir = os.path.join(tmp, "repo")
        os.makedirs(repo_dir, exist_ok=True)
        os.makedirs(os.path.join(repo_dir, ".git"), exist_ok=True)
        repos_path = os.path.join(tmp, "repos.json")
        with open(repos_path, "w", encoding="utf-8") as f:
            json.dump({"r": repo_dir}, f)
        with patch.dict(os.environ, {
            "RUNNER_REPO_ALLOWLIST": repos_path,
            "RUNNER_REPOS_BASE": tmp,
            "RUNNER_STATE_DIR": os.path.join(tmp, "state"),
        }, clear=False):
            import importlib
            importlib.reload(runner_module)
            with pytest.raises(ValueError, match="relative"):
                runner_module.run_job("repo_readfile", json.dumps({"repo": "r", "path": "../other/file.txt", "start": 1, "end": 10}))


def test_repo_grep_uses_rg_when_present():
    with tempfile.TemporaryDirectory() as tmp:
        repo_dir = os.path.join(tmp, "repo")
        os.makedirs(repo_dir, exist_ok=True)
        os.makedirs(os.path.join(repo_dir, ".git"), exist_ok=True)
        repos_path = os.path.join(tmp, "repos.json")
        with open(repos_path, "w", encoding="utf-8") as f:
            json.dump({"r": repo_dir}, f)
        with patch.dict(os.environ, {
            "RUNNER_REPO_ALLOWLIST": repos_path,
            "RUNNER_REPOS_BASE": tmp,
            "RUNNER_STATE_DIR": os.path.join(tmp, "state"),
        }, clear=False):
            import importlib
            importlib.reload(runner_module)
            with patch("runner.runner.shutil.which", return_value="/usr/bin/rg"):
                with patch("runner.runner.run_cmd") as mock_run:
                    mock_run.return_value = ("", "", 0)
                    runner_module.run_job("repo_grep", json.dumps({"repo": "r", "query": "foo", "path": ""}))
                    mock_run.assert_called_once()
                    argv = mock_run.call_args[0][0]
                    assert "rg" in argv
                    assert "-n" in argv
                    assert "foo" in argv


def test_repo_grep_uses_git_grep_when_rg_missing():
    with tempfile.TemporaryDirectory() as tmp:
        repo_dir = os.path.join(tmp, "repo")
        os.makedirs(repo_dir, exist_ok=True)
        os.makedirs(os.path.join(repo_dir, ".git"), exist_ok=True)
        repos_path = os.path.join(tmp, "repos.json")
        with open(repos_path, "w", encoding="utf-8") as f:
            json.dump({"r": repo_dir}, f)
        with patch.dict(os.environ, {
            "RUNNER_REPO_ALLOWLIST": repos_path,
            "RUNNER_REPOS_BASE": tmp,
            "RUNNER_STATE_DIR": os.path.join(tmp, "state"),
        }, clear=False):
            import importlib
            importlib.reload(runner_module)
            with patch("runner.runner.shutil.which", return_value=None):
                with patch("runner.runner.run_cmd") as mock_run:
                    mock_run.return_value = ("", "", 0)
                    runner_module.run_job("repo_grep", json.dumps({"repo": "r", "query": "foo", "path": ""}))
                    mock_run.assert_called_once()
                    argv = mock_run.call_args[0][0]
                    assert "git" in argv
                    assert "grep" in argv
                    assert "foo" in argv
