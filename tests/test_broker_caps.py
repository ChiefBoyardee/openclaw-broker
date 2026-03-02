"""
Unit tests for broker caps parsing and matching (broker.caps).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from broker.caps import is_command_allowed, job_matches_worker, job_required_caps, parse_worker_caps


def test_parse_worker_caps_empty():
    assert parse_worker_caps(None) == set()
    assert parse_worker_caps("") == set()
    assert parse_worker_caps("   ") == set()


def test_parse_worker_caps_comma_separated():
    assert parse_worker_caps("a,b,c") == {"a", "b", "c"}
    assert parse_worker_caps(" llm:vllm , repo_tools ") == {"llm:vllm", "repo_tools"}


def test_parse_worker_caps_json_array():
    assert parse_worker_caps('["llm:vllm","repo_tools"]') == {"llm:vllm", "repo_tools"}
    assert parse_worker_caps("[ ]") == set()
    assert parse_worker_caps('["a"]') == {"a"}


def test_parse_worker_caps_invalid_json_falls_back_to_comma():
    # "a,b" does not start with "[", so never tries JSON; exercises comma path
    assert parse_worker_caps("a,b") == {"a", "b"}
    # "[a,b]" starts with "[" but is invalid JSON (unquoted); fallback to comma split
    assert parse_worker_caps("[a,b]") == {"[a", "b]"}


def test_job_required_caps_empty():
    assert job_required_caps(None) is None
    assert job_required_caps("") is None
    assert job_required_caps("   ") is None


def test_job_required_caps_valid():
    assert job_required_caps('{"caps":["llm:vllm"]}') == {"llm:vllm"}
    assert job_required_caps('{"caps":["llm:vllm","repo_tools"]}') == {"llm:vllm", "repo_tools"}
    assert job_required_caps('{"caps":[]}') == set()


def test_job_required_caps_no_caps_key():
    assert job_required_caps('{}') is None
    assert job_required_caps('{"other":1}') is None


def test_job_required_caps_malformed():
    assert job_required_caps("not json") is None
    assert job_required_caps('{"caps":') is None


def test_job_required_caps_empty_strings_filtered():
    assert job_required_caps('{"caps":[""]}') == set()
    assert job_required_caps('{"caps":["a","","b"]}') == {"a", "b"}


def test_job_matches_worker_no_requires():
    assert job_matches_worker(None, set()) is True
    assert job_matches_worker(None, {"llm:vllm"}) is True
    assert job_matches_worker("", set()) is True


def test_job_matches_worker_subset():
    assert job_matches_worker('{"caps":["llm:vllm"]}', {"llm:vllm", "repo_tools"}) is True
    assert job_matches_worker('{"caps":["llm:vllm"]}', {"llm:vllm"}) is True


def test_job_matches_worker_not_subset():
    assert job_matches_worker('{"caps":["llm:vllm"]}', set()) is False
    assert job_matches_worker('{"caps":["llm:vllm"]}', {"llm:jetson"}) is False
    assert job_matches_worker('{"caps":["llm:vllm","repo_tools"]}', {"llm:vllm"}) is False


def test_job_matches_worker_empty_caps_any_worker():
    assert job_matches_worker('{"caps":[""]}', set()) is True
    assert job_matches_worker('{"caps":[]}', set()) is True


def test_is_command_allowed():
    assert is_command_allowed("ping") is True
    assert is_command_allowed("llm_task") is True
    assert is_command_allowed("repo_list") is True
    assert is_command_allowed("evil_command") is False
    assert is_command_allowed("") is False
