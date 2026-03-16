"""
Tests for browser tools using Playwright.
We create a local HTML file as a fixture so we don't need real network requests.
"""
import asyncio
import json
import os
import sys
import tempfile
import threading
from http.server import HTTPServer, SimpleHTTPRequestHandler

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from runner import browser_tools as bt

# Skip the entire module when Playwright is not installed
try:
    import playwright  # noqa: F401
    _PLAYWRIGHT_AVAILABLE = True
except ImportError:
    _PLAYWRIGHT_AVAILABLE = False

pytestmark = pytest.mark.skipif(
    not _PLAYWRIGHT_AVAILABLE,
    reason="Playwright not installed (pip install playwright && playwright install chromium)",
)

# Port for our local test server
TEST_PORT = 8089
TEST_HTML = """
<!DOCTYPE html>
<html>
<head><title>Test Page</title></head>
<body>
    <h1>Welcome to the Test Page</h1>
    <p>This is a paragraph.</p>
    <button id="btn1" onclick="document.getElementById('res').innerText = 'Clicked!'">Click Me</button>
    <a href="/link.html">A Link</a>
    <input type="text" id="inp1" placeholder="Type here" aria-label="Search box">
    <div id="res"></div>
</body>
</html>
"""

@pytest.fixture(scope="module")
def local_server():
    """Start a local HTTP server serving a test HTML page."""
    with tempfile.TemporaryDirectory() as td:
        index_path = os.path.join(td, "index.html")
        with open(index_path, "w", encoding="utf-8") as f:
            f.write(TEST_HTML)

        class Handler(SimpleHTTPRequestHandler):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, directory=td, **kwargs)
            
            # Silence logging
            def log_message(self, format, *args):
                pass
                
        httpd = HTTPServer(("127.0.0.1", TEST_PORT), Handler)
        server_thread = threading.Thread(target=httpd.serve_forever)
        server_thread.daemon = True
        server_thread.start()
        
        yield f"http://127.0.0.1:{TEST_PORT}/index.html"
        
        httpd.shutdown()


def test_browser_readfile_and_click(local_server):
    """Test reading a page and clicking an element."""
    async def _run():
        # 1. Navigate to the page
        nav_res = json.loads(await asyncio.to_thread(bt.browser_navigate, url=local_server))
        assert nav_res["success"] is True, f"Navigate failed: {nav_res}"
        
        # 2. Get snapshot (markdown + elements)
        read_res = json.loads(await asyncio.to_thread(bt.browser_snapshot))
        assert read_res["success"] is True, f"Snapshot failed: {read_res}"
        assert "Welcome to the Test Page" in read_res.get("snapshot", {}).get("content", ""), f"Content missing. Full response: {read_res}"
        assert "Click Me" in read_res.get("snapshot", {}).get("content", ""), f"Click Me missing: {read_res}"
        
        # Verify elements extraction worked
        elements = read_res.get("snapshot", {}).get("interactive_elements", [])
        assert len(elements) >= 3  # Button, Link, Input
        
        # Find the button ref
        btn_ref = None
        for el in elements:
            if el["text"] == "Click Me" or el.get("tag") == "button":
                btn_ref = el["ref"]
                break
                
        assert btn_ref is not None, "Button 'Click Me' not found in elements"
        
        # 3. Click the button
        click_res = json.loads(await asyncio.to_thread(bt.browser_click, ref=btn_ref))
        assert click_res["success"] is True, f"Click failed: {click_res}"
        
        # 4. Type text
        type_res = json.loads(await asyncio.to_thread(bt.browser_type, selector="input[id='inp1']", text="Hello"))
        assert type_res["success"] is True, f"Failed type: {type_res}"
        
    asyncio.run(_run())
    
def teardown_module(module):
    """Ensure browser state is cleaned up after tests."""
    bt._cleanup_browser()
