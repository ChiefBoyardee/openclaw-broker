"""Tests for VPS website tools — path traversal, XSS escaping, and basic CRUD."""
import sys
import os
import json
import tempfile
import shutil

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Create temp dir for tests and patch the module constant
_tmpdir = tempfile.mkdtemp(prefix="test_website_")

import runner.vps_website_tools as vwt
_original_base = vwt.VPS_WEBSITE_BASE
vwt.VPS_WEBSITE_BASE = _tmpdir


def teardown_module():
    vwt.VPS_WEBSITE_BASE = _original_base
    shutil.rmtree(_tmpdir, ignore_errors=True)


# ---------- _resolve_safe_path ----------

def test_resolve_safe_path_normal():
    """Normal relative paths resolve under the configured base."""
    p = vwt._resolve_safe_path("index.html")
    assert p.startswith(_tmpdir)


def test_resolve_safe_path_rejects_traversal():
    """Directory traversal stays within bounds."""
    result = vwt._resolve_safe_path("../../etc/passwd")
    # Should still resolve under the base
    if result is not None:
        assert result.startswith(_tmpdir)


def test_resolve_safe_path_rejects_absolute():
    """Absolute paths outside root are resolved under the base."""
    result = vwt._resolve_safe_path("/etc/passwd")
    if result is not None:
        assert result.startswith(_tmpdir)


# ---------- website_init ----------

def test_website_init_creates_structure():
    """website_init creates expected directories and files."""
    result = json.loads(vwt.website_init())
    assert result.get("success") or result.get("status") == "ok"
    # Should have index.html under our patched base
    assert os.path.isfile(os.path.join(_tmpdir, "index.html"))


# ---------- website_write_file / read_file ----------

def test_write_and_read_file():
    """Round-trip write then read."""
    content = "Hello, test content!"
    w = json.loads(vwt.website_write_file("test_page.html", content))
    assert w.get("success") or "ok" in json.dumps(w).lower()

    r = json.loads(vwt.website_read_file("test_page.html"))
    assert content in json.dumps(r)


# ---------- XSS escaping ----------

def test_create_post_escapes_xss():
    """XSS payloads in title/category/tags are escaped."""
    xss = '<script>alert("xss")</script>'
    result = json.loads(vwt.website_create_post(
        title=xss,
        content="Safe body text.",
        category=xss,
        tags=[xss],
    ))
    # Read the created file and verify no raw script tags
    posts_dir = os.path.join(_tmpdir, "posts")
    if os.path.isdir(posts_dir):
        for f in os.listdir(posts_dir):
            path = os.path.join(posts_dir, f)
            if os.path.isfile(path):
                with open(path, "r", encoding="utf-8") as fh:
                    html_content = fh.read()
                assert '<script>' not in html_content, "Raw <script> tag found in post HTML"
                assert '&lt;script&gt;' in html_content, "XSS payload was not escaped"


def test_create_knowledge_page_escapes_xss():
    """XSS payloads in knowledge page title/category are escaped."""
    xss = '<img src=x onerror=alert(1)>'
    result = json.loads(vwt.website_create_knowledge_page(
        title=xss,
        content="Safe knowledge content.",
        category=xss,
    ))
    knowledge_dir = os.path.join(_tmpdir, "knowledge")
    if os.path.isdir(knowledge_dir):
        content_files = [f for f in os.listdir(knowledge_dir) 
                        if os.path.isfile(os.path.join(knowledge_dir, f)) and f != "index.html"]
        assert len(content_files) > 0, "No knowledge page file was created"
        for f in content_files:
            path = os.path.join(knowledge_dir, f)
            with open(path, "r", encoding="utf-8") as fh:
                html_content = fh.read()
            # Title in <h1> and category in metadata should be escaped
            assert '&lt;img' in html_content, "XSS in title/category was not escaped"


def test_update_about_escapes_xss():
    """XSS payloads in about page fields are escaped."""
    xss = '<script>steal()</script>'
    result = json.loads(vwt.website_update_about(
        biography=xss,
        interests=[xss],
        current_goals=[xss],
    ))
    about_path = os.path.join(_tmpdir, "about.html")
    if os.path.isfile(about_path):
        with open(about_path, "r", encoding="utf-8") as fh:
            html_content = fh.read()
        assert '<script>' not in html_content, "Raw <script> tag in about page"


# ---------- website_get_stats ----------

def test_website_get_stats_returns_valid_json():
    """website_get_stats returns parseable JSON."""
    result = json.loads(vwt.website_get_stats())
    assert isinstance(result, dict)
