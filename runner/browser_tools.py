"""
Browser automation tools for web browsing and content extraction.

Provides capabilities for:
- Navigating to URLs
- Taking snapshots of page content
- Clicking elements
- Typing into forms
- Extracting structured content
- Multi-step browsing sessions
"""
from __future__ import annotations

import json
import os
from typing import Any, Optional, Dict, List
from dataclasses import dataclass

# Browser configuration
BROWSER_HEADLESS = os.environ.get("BROWSER_HEADLESS", "true").lower() == "true"
BROWSER_TIMEOUT = int(os.environ.get("BROWSER_TIMEOUT", "30000"))
BROWSER_MAX_CONTENT_LENGTH = int(os.environ.get("BROWSER_MAX_CONTENT_LENGTH", "4000"))

# Track browser state (singleton pattern)
_browser_state: Optional[Dict[str, Any]] = None


@dataclass
class BrowserSession:
    """Represents a browser session state."""
    current_url: str = ""
    page_title: str = ""
    tabs: List[Dict[str, str]] = None
    
    def __post_init__(self):
        if self.tabs is None:
            self.tabs = []


@dataclass
class PageSnapshot:
    """Represents a snapshot of a web page."""
    url: str
    title: str
    content: str
    interactive_elements: List[Dict[str, Any]]
    links: List[Dict[str, str]]
    forms: List[Dict[str, Any]]
    truncated: bool = False


def _get_browser_state() -> Dict[str, Any]:
    """Get or initialize browser state."""
    global _browser_state
    if _browser_state is None:
        _browser_state = {
            "session": None,
            "playwright": None,
            "browser": None,
            "context": None,
            "page": None,
        }
    return _browser_state


def _init_browser() -> Dict[str, Any]:
    """Initialize Playwright browser instance."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise RuntimeError(
            "Playwright not installed. Run: pip install playwright && playwright install chromium"
        )
    
    state = _get_browser_state()
    
    if state["browser"] is None:
        state["playwright"] = sync_playwright().start()
        state["browser"] = state["playwright"].chromium.launch(headless=BROWSER_HEADLESS)
        state["context"] = state["browser"].new_context(
            viewport={"width": 1280, "height": 720},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        )
        state["page"] = state["context"].new_page()
        state["session"] = BrowserSession()
    
    return state


def _cleanup_browser() -> None:
    """Clean up browser resources."""
    global _browser_state
    if _browser_state:
        try:
            if _browser_state.get("page"):
                _browser_state["page"].close()
            if _browser_state.get("context"):
                _browser_state["context"].close()
            if _browser_state.get("browser"):
                _browser_state["browser"].close()
            if _browser_state.get("playwright"):
                _browser_state["playwright"].stop()
        except Exception:
            pass
        _browser_state = None


def _truncate_content(content: str, max_length: int = BROWSER_MAX_CONTENT_LENGTH) -> tuple[str, bool]:
    """Truncate content to max length."""
    if len(content) <= max_length:
        return content, False
    return content[:max_length] + "\n...[truncated]", True


def _extract_text_content(page) -> str:
    """Extract readable text content from page."""
    try:
        # Try to get main content first
        content = page.evaluate("""
            () => {
                // Try to find main content areas
                const selectors = [
                    'main', 'article', '[role="main"]',
                    '.content', '.main-content', '.article-content',
                    '#content', '#main-content',
                    'body'
                ];
                for (const selector of selectors) {
                    const el = document.querySelector(selector);
                    if (el) {
                        return el.innerText;
                    }
                }
                return document.body.innerText;
            }
        """)
        return content or ""
    except Exception as e:
        return f"Error extracting content: {str(e)}"


def _extract_links(page) -> List[Dict[str, str]]:
    """Extract all links from page."""
    try:
        links = page.evaluate("""
            () => Array.from(document.querySelectorAll('a[href]'))
                .map((a, i) => ({
                    ref: i,
                    text: a.innerText?.trim().substring(0, 100) || '',
                    href: a.href,
                    title: a.title || ''
                }))
                .filter(a => a.text || a.title)
                .slice(0, 50)
        """)
        return links or []
    except Exception:
        return []


def _extract_forms(page) -> List[Dict[str, Any]]:
    """Extract forms and input fields from page."""
    try:
        forms = page.evaluate("""
            () => Array.from(document.querySelectorAll('form, input, textarea, select, button'))
                .map((el, i) => {
                    const info = {
                        ref: i,
                        tag: el.tagName.toLowerCase(),
                        type: el.type || '',
                        name: el.name || '',
                        id: el.id || '',
                        placeholder: el.placeholder || '',
                        value: el.value?.substring(0, 100) || ''
                    };
                    if (el.tagName === 'BUTTON' || (el.tagName === 'INPUT' && 
                        ['submit', 'button'].includes(el.type))) {
                        info.text = el.innerText?.trim() || el.value || '';
                    }
                    return info;
                })
                .slice(0, 30)
        """)
        return forms or []
    except Exception:
        return []


def _extract_interactive_elements(page) -> List[Dict[str, Any]]:
    """Extract clickable/interactive elements."""
    try:
        elements = page.evaluate("""
            () => Array.from(document.querySelectorAll(
                'button, a, input[type="submit"], [role="button"], [onclick], select, input[type="text"], input[type="search"]'
            ))
                .map((el, i) => ({
                    ref: i,
                    tag: el.tagName.toLowerCase(),
                    type: el.type || '',
                    text: el.innerText?.trim().substring(0, 100) || 
                          el.value?.substring(0, 100) || 
                          el.placeholder || '',
                    ariaLabel: el.getAttribute('aria-label') || ''
                }))
                .filter(el => el.text || el.ariaLabel)
                .slice(0, 40)
        """)
        return elements or []
    except Exception:
        return []


def browser_navigate(url: str, wait_for_load: bool = True) -> str:
    """
    Navigate to a URL and extract page content.
    
    Args:
        url: The URL to navigate to
        wait_for_load: Whether to wait for page load
    
    Returns:
        JSON string with navigation result including page content
    """
    try:
        state = _init_browser()
        page = state["page"]
        
        # Validate URL
        if not url.startswith(('http://', 'https://')):
            url = 'https://' + url
        
        # Navigate
        page.goto(url, wait_until="networkidle" if wait_for_load else "commit", 
                 timeout=BROWSER_TIMEOUT)
        
        # Update session
        state["session"].current_url = page.url
        state["session"].page_title = page.title()
        
        # Auto-extract page content so the LLM gets useful text in one call
        content = _extract_text_content(page)
        content, truncated = _truncate_content(content)
        
        result = {
            "success": True,
            "url": page.url,
            "title": page.title(),
            "content": content,
            "truncated": truncated,
            "message": f"Navigated to {page.url} and extracted content ({len(content)} chars)"
        }
        return json.dumps(result)
        
    except Exception as e:
        result = {
            "success": False,
            "error": str(e),
            "message": f"Failed to navigate: {str(e)}"
        }
        return json.dumps(result)


def browser_snapshot(full_content: bool = True) -> str:
    """
    Take a snapshot of the current page.
    
    Args:
        full_content: Whether to include full page content
    
    Returns:
        JSON string with page snapshot
    """
    try:
        state = _get_browser_state()
        if state["page"] is None:
            return json.dumps({
                "success": False,
                "error": "No active browser session. Navigate to a URL first."
            })
        
        page = state["page"]
        
        # Extract page information
        title = page.title()
        url = page.url
        
        snapshot_data = {
            "url": url,
            "title": title,
            "links": _extract_links(page),
            "forms": _extract_forms(page),
            "interactive_elements": _extract_interactive_elements(page)
        }
        
        if full_content:
            content = _extract_text_content(page)
            content, truncated = _truncate_content(content)
            snapshot_data["content"] = content
            snapshot_data["truncated"] = truncated
        
        return json.dumps({
            "success": True,
            "snapshot": snapshot_data
        }, indent=2)
        
    except Exception as e:
        return json.dumps({
            "success": False,
            "error": str(e)
        })


def browser_click(ref: Optional[int] = None, selector: Optional[str] = None) -> str:
    """
    Click an element on the page.
    
    Args:
        ref: Reference number from snapshot interactive_elements
        selector: CSS selector as alternative to ref
    
    Returns:
        JSON string with click result
    """
    try:
        state = _get_browser_state()
        if state["page"] is None:
            return json.dumps({
                "success": False,
                "error": "No active browser session"
            })
        
        page = state["page"]
        
        if ref is not None:
            # Click by reference — use the same selector, filter, and slice as
            # _extract_interactive_elements so that ref indices match exactly.
            click_result = page.evaluate(f"""
                () => {{
                    const all = Array.from(document.querySelectorAll(
                        'button, a, input[type="submit"], [role="button"], [onclick], select, input[type="text"], input[type="search"]'
                    ));
                    const visible = all
                        .filter(el => {{
                            const text = el.innerText?.trim().substring(0, 100) || 
                                         el.value?.substring(0, 100) || 
                                         el.placeholder || '';
                            const ariaLabel = el.getAttribute('aria-label') || '';
                            return text || ariaLabel;
                        }})
                        .slice(0, 40);
                    if ({ref} >= visible.length) return {{ error: true }};
                    visible[{ref}].click();
                    return {{ error: false }};
                }}
            """)
            if click_result and click_result.get("error"):
                return json.dumps({
                    "success": False,
                    "error": f"Element with ref {ref} not found (max ref: unknown)"
                })
        elif selector:
            page.click(selector)
        else:
            return json.dumps({
                "success": False,
                "error": "Must provide either ref or selector"
            })
        
        # Wait for navigation or changes
        page.wait_for_load_state("networkidle", timeout=5000)
        
        return json.dumps({
            "success": True,
            "url": page.url,
            "title": page.title(),
            "message": "Click successful"
        })
        
    except Exception as e:
        return json.dumps({
            "success": False,
            "error": str(e)
        })


def browser_type(text: str, ref: Optional[int] = None, 
                 selector: Optional[str] = None, submit: bool = False) -> str:
    """
    Type text into an input field.
    
    Args:
        text: Text to type
        ref: Reference number from snapshot forms
        selector: CSS selector as alternative to ref
        submit: Whether to press Enter after typing
    
    Returns:
        JSON string with type result
    """
    try:
        state = _get_browser_state()
        if state["page"] is None:
            return json.dumps({
                "success": False,
                "error": "No active browser session"
            })
        
        page = state["page"]
        
        if ref is not None:
            # Type by reference
            input_selector = "input, textarea, select"
            elements = page.query_selector_all(input_selector)
            if ref >= len(elements):
                return json.dumps({
                    "success": False,
                    "error": f"Input with ref {ref} not found"
                })
            elements[ref].fill(text)
        elif selector:
            page.fill(selector, text)
        else:
            return json.dumps({
                "success": False,
                "error": "Must provide either ref or selector"
            })
        
        if submit:
            page.keyboard.press("Enter")
            page.wait_for_load_state("networkidle", timeout=5000)
        
        return json.dumps({
            "success": True,
            "message": f"Typed '{text[:50]}...' into field" if len(text) > 50 else f"Typed '{text}' into field"
        })
        
    except Exception as e:
        return json.dumps({
            "success": False,
            "error": str(e)
        })


def browser_search(query: str, engine: str = "google") -> str:
    """
    Perform a web search.
    
    Args:
        query: Search query
        engine: Search engine (google, duckduckgo, bing)
    
    Returns:
        JSON string with search results
    """
    try:
        state = _init_browser()
        page = state["page"]
        
        # Navigate to search engine
        search_urls = {
            "google": f"https://www.google.com/search?q={query.replace(' ', '+')}",
            "duckduckgo": f"https://duckduckgo.com/?q={query.replace(' ', '+')}",
            "bing": f"https://www.bing.com/search?q={query.replace(' ', '+')}"
        }
        
        url = search_urls.get(engine, search_urls["google"])
        page.goto(url, wait_until="networkidle", timeout=BROWSER_TIMEOUT)
        
        # Extract search results
        results = page.evaluate("""
            () => {
                const results = [];
                // Try different result selectors
                const selectors = [
                    'div[data-ved] h3',  // Google
                    'h2 a',  // DuckDuckGo
                    'li.b_algo h2 a',  // Bing
                    'h3 a',  // Generic
                    '.result__a',  // DDG alternate
                    '.g h3'  // Google alternate
                ];
                
                for (const selector of selectors) {
                    const elements = document.querySelectorAll(selector);
                    for (let i = 0; i < Math.min(elements.length, 10); i++) {
                        const el = elements[i];
                        const link = el.closest('a') || el.querySelector('a') || el;
                        const href = link.href || link.getAttribute('href') || '';
                        const title = el.innerText || el.textContent || '';
                        if (href && title && !href.startsWith('javascript:')) {
                            results.push({
                                title: title.trim().substring(0, 150),
                                url: href,
                                snippet: ''
                            });
                        }
                    }
                    if (results.length > 0) break;
                }
                return results.slice(0, 8);
            }
        """)
        
        return json.dumps({
            "success": True,
            "query": query,
            "engine": engine,
            "results": results,
            "result_count": len(results)
        }, indent=2)
        
    except Exception as e:
        return json.dumps({
            "success": False,
            "error": str(e),
            "query": query
        })


def browser_extract_article() -> str:
    """
    Extract article content from current page using readability-style extraction.
    
    Returns:
        JSON string with extracted article
    """
    try:
        state = _get_browser_state()
        if state["page"] is None:
            return json.dumps({
                "success": False,
                "error": "No active browser session"
            })
        
        page = state["page"]
        
        # Article extraction script
        article_data = page.evaluate("""
            () => {
                // Try to find article content
                const articleSelectors = [
                    'article',
                    '[itemtype*="Article"]',
                    '.article-content',
                    '.post-content',
                    '.entry-content',
                    '.story-content',
                    'main',
                    '[role="main"]'
                ];
                
                let content = '';
                let usedSelector = '';
                
                for (const selector of articleSelectors) {
                    const el = document.querySelector(selector);
                    if (el) {
                        content = el.innerText;
                        usedSelector = selector;
                        if (content.length > 500) break;
                    }
                }
                
                // If no article found, try to extract from body
                if (!content || content.length < 200) {
                    // Remove navigation, ads, etc.
                    const body = document.body.cloneNode(true);
                    const toRemove = body.querySelectorAll(
                        'nav, header, footer, aside, .sidebar, .ads, .advertisement, script, style'
                    );
                    toRemove.forEach(el => el.remove());
                    content = body.innerText;
                }
                
                // Get metadata
                const title = document.querySelector('h1, .article-title, .post-title')?.innerText 
                    || document.title;
                const author = document.querySelector(
                    '[rel="author"], .author, .byline, [itemprop="author"]'
                )?.innerText || '';
                const published = document.querySelector(
                    '[itemprop="datePublished"], time, .published, .date'
                )?.getAttribute('datetime') || 
                    document.querySelector('[itemprop="datePublished"], time, .published, .date')?.innerText || '';
                
                return {
                    title: title?.trim(),
                    author: author?.trim(),
                    published: published,
                    content: content?.trim(),
                    wordCount: content?.split(/\\s+/).length || 0,
                    selector: usedSelector
                };
            }
        """)
        
        # Truncate content if needed
        content = article_data.get('content', '')
        content, truncated = _truncate_content(content, BROWSER_MAX_CONTENT_LENGTH)
        article_data['content'] = content
        article_data['truncated'] = truncated
        
        return json.dumps({
            "success": True,
            "article": article_data
        }, indent=2)
        
    except Exception as e:
        return json.dumps({
            "success": False,
            "error": str(e)
        })


def browser_close() -> str:
    """
    Close the browser session.
    
    Returns:
        JSON string with close result
    """
    try:
        _cleanup_browser()
        return json.dumps({
            "success": True,
            "message": "Browser session closed"
        })
    except Exception as e:
        return json.dumps({
            "success": False,
            "error": str(e)
        })


def get_browser_capabilities() -> list[str]:
    """Return list of browser-related capabilities."""
    return [
        "browser_navigate",
        "browser_snapshot",
        "browser_click",
        "browser_type",
        "browser_search",
        "browser_extract_article",
        "browser_close",
    ]
