"""Tests for github_tools — URL encoding, error body parsing, auth headers."""
import sys
import os
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from urllib.parse import quote_plus
from unittest.mock import patch, MagicMock
import urllib.error

from runner.github_tools import (
    _make_request,
    github_search_repos,
    github_search_code,
)


# ---------- URL encoding ----------

def test_search_repos_encodes_special_chars():
    """Query with special chars is properly encoded in the URL."""
    with patch("runner.github_tools._make_request") as mock_req:
        mock_req.return_value = (True, {"items": [], "total_count": 0})
        github_search_repos("test query&inject=1")
        call_args = mock_req.call_args
        endpoint = call_args[0][1]
        # The query should be URL-encoded, not contain raw &
        assert "&inject=1" not in endpoint.split("?q=")[1].split("&sort=")[0]
        assert quote_plus("test query&inject=1") in endpoint


def test_search_code_encodes_special_chars():
    """Query with special chars is properly encoded in search_code."""
    with patch("runner.github_tools._make_request") as mock_req:
        mock_req.return_value = (True, {"items": [], "total_count": 0})
        github_search_code("file:*.py #include")
        call_args = mock_req.call_args
        endpoint = call_args[0][1]
        # Should use quote_plus, not naive replace
        assert quote_plus("file:*.py #include") in endpoint


# ---------- Error body double-read fix ----------

def test_make_request_reads_error_body_once():
    """HTTPError body is read exactly once, preserving the error message."""
    error_msg = '{"message": "Not Found"}'
    mock_response = MagicMock()
    mock_response.read.return_value = error_msg.encode("utf-8")
    mock_response.code = 404

    http_error = urllib.error.HTTPError(
        url="https://api.github.com/test",
        code=404,
        msg="Not Found",
        hdrs={},
        fp=None,
    )
    # Override read to return our message exactly once
    http_error.read = MagicMock(return_value=error_msg.encode("utf-8"))

    with patch("urllib.request.urlopen", side_effect=http_error):
        success, result = _make_request("GET", "/test")

    assert not success
    assert "Not Found" in result.get("error", "")
    # read() should have been called exactly once
    assert http_error.read.call_count == 1


# ---------- Auth header presence ----------

def test_make_request_includes_auth_when_token_set():
    """When GITHUB_TOKEN is set, Authorization header is included."""
    with patch.dict(os.environ, {"GITHUB_TOKEN": "ghp_test123"}):
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_resp = MagicMock()
            mock_resp.read.return_value = b'{"ok": true}'
            mock_resp.status = 200
            mock_resp.__enter__ = MagicMock(return_value=mock_resp)
            mock_resp.__exit__ = MagicMock(return_value=False)
            mock_urlopen.return_value = mock_resp

            # Re-import to pick up new token
            import importlib
            import runner.github_tools as gt
            original_token = gt.GITHUB_TOKEN
            gt.GITHUB_TOKEN = "ghp_test123"
            try:
                _make_request("GET", "/repos/test/test")
                if mock_urlopen.called:
                    request = mock_urlopen.call_args[0][0]
                    assert request.has_header("Authorization") or request.has_header("authorization")
            finally:
                gt.GITHUB_TOKEN = original_token
