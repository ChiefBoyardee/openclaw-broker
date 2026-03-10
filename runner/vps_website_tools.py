"""
VPS Website management tools for Urgo's personal website.

Provides capabilities for:
- Creating and managing static websites
- Writing HTML, CSS, and markdown content
- Managing site structure and navigation
- Auto-generating pages from learned content
- Publishing research findings and reflections
"""
from __future__ import annotations

import html
import json
import os
import re
from typing import Any, Optional, Dict, List
from datetime import datetime
from pathlib import Path

# Configuration
VPS_WEBSITE_BASE = os.environ.get("VPS_WEBSITE_BASE", "/var/www/urgo")
VPS_DOMAIN = os.environ.get("VPS_DOMAIN", "urgo.local")
VPS_MAX_FILE_SIZE = int(os.environ.get("VPS_MAX_FILE_SIZE", "500000"))

# Ensure safe file paths
def _resolve_safe_path(relative_path: str) -> str:
    """Resolve a path relative to website base, ensuring it stays within bounds."""
    # Clean the path
    clean_path = relative_path.strip('/')
    clean_path = re.sub(r'\.+/', '', clean_path)  # Remove path traversal attempts
    
    full_path = os.path.join(VPS_WEBSITE_BASE, clean_path)
    real_base = os.path.realpath(VPS_WEBSITE_BASE)
    real_path = os.path.realpath(full_path)
    
    # Ensure path is within website base
    if not real_path.startswith(real_base + os.sep) and real_path != real_base:
        raise ValueError("Path outside website base directory")
    
    return real_path


def _ensure_directory(path: str) -> None:
    """Ensure directory exists."""
    os.makedirs(os.path.dirname(path), exist_ok=True)


def website_init(site_title: str = "Urgo's Digital Garden", 
                description: str = "A collection of thoughts, learnings, and discoveries.") -> str:
    """
    Initialize a new website for Urgo.
    
    Args:
        site_title: Title of the website
        description: Site description/meta
    
    Returns:
        JSON string with result
    """
    try:
        # Create base directory
        os.makedirs(VPS_WEBSITE_BASE, exist_ok=True)
        
        # Create subdirectories
        for subdir in ['posts', 'knowledge', 'projects', 'assets', 'css']:
            os.makedirs(os.path.join(VPS_WEBSITE_BASE, subdir), exist_ok=True)
        
        # Create site configuration
        config = {
            "title": site_title,
            "description": description,
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
            "version": "1.0",
            "domain": VPS_DOMAIN,
            "nav_items": [
                {"label": "Home", "path": "/"},
                {"label": "Knowledge", "path": "/knowledge/"},
                {"label": "Posts", "path": "/posts/"},
                {"label": "Projects", "path": "/projects/"},
                {"label": "About", "path": "/about.html"},
            ]
        }
        
        config_path = os.path.join(VPS_WEBSITE_BASE, "site_config.json")
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2)
        
        # Create main index.html
        index_html = _generate_index_html(config)
        index_path = os.path.join(VPS_WEBSITE_BASE, "index.html")
        with open(index_path, 'w', encoding='utf-8') as f:
            f.write(index_html)
        
        # Create CSS
        css_content = _generate_default_css()
        css_path = os.path.join(VPS_WEBSITE_BASE, "css", "style.css")
        with open(css_path, 'w', encoding='utf-8') as f:
            f.write(css_content)
        
        # Create about page
        about_html = _generate_about_page(config)
        about_path = os.path.join(VPS_WEBSITE_BASE, "about.html")
        with open(about_path, 'w', encoding='utf-8') as f:
            f.write(about_html)
        
        # Create knowledge index
        knowledge_index = _generate_knowledge_index(config)
        knowledge_path = os.path.join(VPS_WEBSITE_BASE, "knowledge", "index.html")
        with open(knowledge_path, 'w', encoding='utf-8') as f:
            f.write(knowledge_index)
        
        return json.dumps({
            "success": True,
            "message": f"Website initialized at {VPS_WEBSITE_BASE}",
            "site_title": site_title,
            "base_path": VPS_WEBSITE_BASE,
            "url": f"http://{VPS_DOMAIN}",
            "created_files": [
                "index.html",
                "about.html",
                "css/style.css",
                "site_config.json",
                "knowledge/index.html"
            ]
        }, indent=2)
        
    except (OSError, IOError, ValueError) as e:
        return json.dumps({
            "success": False,
            "error": str(e),
            "message": "Failed to initialize website"
        })


def website_write_file(path: str, content: str, 
                       append: bool = False) -> str:
    """
    Write content to a file in the website.
    
    Args:
        path: Relative path within website
        content: File content
        append: Whether to append or overwrite
    
    Returns:
        JSON string with result
    """
    try:
        full_path = _resolve_safe_path(path)
        _ensure_directory(full_path)
        
        # Check size limit
        content_bytes = content.encode('utf-8')
        if len(content_bytes) > VPS_MAX_FILE_SIZE:
            return json.dumps({
                "success": False,
                "error": f"Content exceeds max size of {VPS_MAX_FILE_SIZE} bytes"
            })
        
        mode = 'a' if append else 'w'
        with open(full_path, mode, encoding='utf-8') as f:
            f.write(content)
        
        # Update site config
        _update_site_timestamp()
        
        return json.dumps({
            "success": True,
            "message": f"File written to {path}",
            "path": path,
            "size": len(content_bytes),
            "appended": append
        }, indent=2)
        
    except Exception as e:
        return json.dumps({
            "success": False,
            "error": str(e),
            "message": f"Failed to write {path}"
        })


def website_read_file(path: str) -> str:
    """
    Read a file from the website.
    
    Args:
        path: Relative path within website
    
    Returns:
        JSON string with file content
    """
    try:
        full_path = _resolve_safe_path(path)
        
        if not os.path.exists(full_path):
            return json.dumps({
                "success": False,
                "error": "File not found"
            })
        
        with open(full_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        return json.dumps({
            "success": True,
            "path": path,
            "content": content,
            "size": len(content.encode('utf-8'))
        }, indent=2)
        
    except (OSError, IOError, ValueError) as e:
        return json.dumps({
            "success": False,
            "error": str(e),
            "message": f"Failed to read {path}"
        })


def website_list_files(directory: str = "", recursive: bool = False) -> str:
    """
    List files in the website directory.
    
    Args:
        directory: Relative directory path
        recursive: Whether to list recursively
    
    Returns:
        JSON string with file list
    """
    try:
        full_path = _resolve_safe_path(directory)
        
        if not os.path.exists(full_path):
            return json.dumps({
                "success": False,
                "error": "Directory not found"
            })
        
        files = []
        if recursive:
            for root, dirs, filenames in os.walk(full_path):
                for filename in filenames:
                    rel_root = os.path.relpath(root, VPS_WEBSITE_BASE)
                    files.append(os.path.join(rel_root, filename))
        else:
            for item in os.listdir(full_path):
                item_path = os.path.join(full_path, item)
                rel_path = os.path.join(directory, item) if directory else item
                files.append({
                    "name": item,
                    "path": rel_path,
                    "type": "directory" if os.path.isdir(item_path) else "file",
                    "size": os.path.getsize(item_path) if os.path.isfile(item_path) else None
                })
        
        return json.dumps({
            "success": True,
            "directory": directory,
            "count": len(files),
            "files": files
        }, indent=2)
        
    except (OSError, IOError, ValueError) as e:
        return json.dumps({
            "success": False,
            "error": str(e)
        })


def website_create_post(title: str, content: str, 
                       category: str = "general",
                       tags: Optional[List[str]] = None) -> str:
    """
    Create a new blog post.
    
    Args:
        title: Post title
        content: Post content (markdown or HTML)
        category: Post category
        tags: List of tags
    
    Returns:
        JSON string with result
    """
    try:
        # Generate filename from title
        slug = re.sub(r'[^\w\s-]', '', title).strip().lower()
        slug = re.sub(r'[-\s]+', '-', slug)
        timestamp = datetime.now().strftime("%Y-%m-%d")
        filename = f"{timestamp}-{slug}.html"
        
        # Read site config for template
        config = _read_site_config()
        
        # Generate HTML from content (basic markdown-like conversion)
        html_content = _markdown_to_html(content)
        
        # Create post HTML
        safe_title = html.escape(title)
        safe_category = html.escape(category)
        safe_tags = [html.escape(t) for t in tags] if tags else []
        post_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{safe_title} | {html.escape(config['title'])}</title>
    <link rel="stylesheet" href="/css/style.css">
</head>
<body>
    {_generate_nav_html(config)}
    <main class="container">
        <article class="post">
            <header class="post-header">
                <h1>{safe_title}</h1>
                <div class="post-meta">
                    <time datetime="{datetime.now().isoformat()}">{datetime.now().strftime("%B %d, %Y")}</time>
                    <span class="category">{safe_category}</span>
                    {f'<span class="tags">{", ".join(safe_tags)}</span>' if safe_tags else ''}
                </div>
            </header>
            <div class="post-content">
                {html_content}
            </div>
        </article>
    </main>
    {_generate_footer_html(config)}
</body>
</html>"""
        
        # Write post
        post_path = os.path.join("posts", filename)
        result = website_write_file(post_path, post_html)
        result_obj = json.loads(result)
        
        if result_obj["success"]:
            # Update posts index
            _update_posts_index()
            
            return json.dumps({
                "success": True,
                "message": f"Post created: {title}",
                "filename": filename,
                "path": post_path,
                "url": f"http://{VPS_DOMAIN}/posts/{filename}"
            }, indent=2)
        else:
            return result
        
    except Exception as e:
        return json.dumps({
            "success": False,
            "error": str(e),
            "message": "Failed to create post"
        })


def website_create_knowledge_page(title: str, content: str,
                                  category: str = "general",
                                  source: Optional[str] = None) -> str:
    """
    Create a knowledge base page.
    
    Args:
        title: Page title
        content: Page content
        category: Knowledge category
        source: Source of this knowledge
    
    Returns:
        JSON string with result
    """
    try:
        # Generate filename
        slug = re.sub(r'[^\w\s-]', '', title).strip().lower()
        slug = re.sub(r'[-\s]+', '-', slug)
        filename = f"{slug}.html"
        
        # Read config
        config = _read_site_config()
        
        # Convert content
        html_content = _markdown_to_html(content)
        
        # Create page HTML
        safe_title = html.escape(title)
        safe_category = html.escape(category)
        safe_source = html.escape(source) if source else None
        page_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{safe_title} | Knowledge | {html.escape(config['title'])}</title>
    <link rel="stylesheet" href="/css/style.css">
</head>
<body>
    {_generate_nav_html(config)}
    <main class="container">
        <article class="knowledge-page">
            <header>
                <h1>{safe_title}</h1>
                <div class="meta">
                    <span class="category">Category: {safe_category}</span>
                    {f'<span class="source">Source: {safe_source}</span>' if safe_source else ''}
                    <span class="updated">Updated: {datetime.now().strftime("%B %d, %Y")}</span>
                </div>
            </header>
            <div class="content">
                {html_content}
            </div>
        </article>
    </main>
    {_generate_footer_html(config)}
</body>
</html>"""
        
        # Write page
        page_path = os.path.join("knowledge", filename)
        result = website_write_file(page_path, page_html)
        
        if json.loads(result)["success"]:
            # Update knowledge index
            _update_knowledge_index()
            
            return json.dumps({
                "success": True,
                "message": f"Knowledge page created: {title}",
                "path": page_path,
                "url": f"http://{VPS_DOMAIN}/knowledge/{filename}"
            }, indent=2)
        else:
            return result
        
    except Exception as e:
        return json.dumps({
            "success": False,
            "error": str(e)
        })


def website_update_about(biography: Optional[str] = None,
                        interests: Optional[List[str]] = None,
                        current_goals: Optional[List[str]] = None) -> str:
    """
    Update the about page with current information.
    
    Args:
        biography: Updated biography text
        interests: List of current interests
        current_goals: List of current goals
    
    Returns:
        JSON string with result
    """
    try:
        config = _read_site_config()
        
        # Build content
        content_parts = []
        
        if biography:
            content_parts.append(f'<div class="bio"><h2>About Me</h2><p>{html.escape(biography)}</p></div>')
        
        if interests:
            interest_items = ''.join([f'<li>{html.escape(i)}</li>' for i in interests])
            content_parts.append(f'<div class="interests"><h2>What I\'m Into</h2><ul>{interest_items}</ul></div>')
        
        if current_goals:
            goal_items = ''.join([f'<li>{html.escape(g)}</li>' for g in current_goals])
            content_parts.append(f'<div class="goals"><h2>Current Goals</h2><ul>{goal_items}</ul></div>')
        
        content_html = '\n'.join(content_parts)
        
        about_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>About | {config['title']}</title>
    <link rel="stylesheet" href="/css/style.css">
</head>
<body>
    {_generate_nav_html(config)}
    <main class="container">
        <h1>About Me</h1>
        <div class="about-content">
            {content_html}
        </div>
    </main>
    {_generate_footer_html(config)}
</body>
</html>"""
        
        return website_write_file("about.html", about_html)
        
    except (OSError, IOError, ValueError) as e:
        return json.dumps({
            "success": False,
            "error": str(e)
        })


def website_get_stats() -> str:
    """Get website statistics."""
    try:
        files_result = website_list_files("", recursive=True)
        files_obj = json.loads(files_result)
        
        if not files_obj["success"]:
            return files_result
        
        files = files_obj.get("files", [])
        
        stats = {
            "total_files": len(files),
            "posts": len([f for f in files if isinstance(f, str) and f.startswith("posts/")]),
            "knowledge_pages": len([f for f in files if isinstance(f, str) and f.startswith("knowledge/")]),
            "projects": len([f for f in files if isinstance(f, str) and f.startswith("projects/")]),
            "base_path": VPS_WEBSITE_BASE,
            "domain": VPS_DOMAIN,
        }
        
        return json.dumps({
            "success": True,
            "stats": stats
        }, indent=2)
        
    except (OSError, IOError, ValueError, json.JSONDecodeError) as e:
        return json.dumps({
            "success": False,
            "error": str(e)
        })


# Helper functions

def _read_site_config() -> Dict:
    """Read site configuration."""
    try:
        config_path = os.path.join(VPS_WEBSITE_BASE, "site_config.json")
        with open(config_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (OSError, IOError, json.JSONDecodeError):
        return {
            "title": "Urgo's Digital Garden",
            "description": "A collection of thoughts and learnings.",
            "domain": VPS_DOMAIN,
            "nav_items": []
        }


def _update_site_timestamp() -> None:
    """Update the site config timestamp."""
    try:
        config = _read_site_config()
        config["updated_at"] = datetime.now().isoformat()
        
        config_path = os.path.join(VPS_WEBSITE_BASE, "site_config.json")
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2)
    except (OSError, IOError, TypeError):
        pass


def _generate_nav_html(config: Dict) -> str:
    """Generate navigation HTML."""
    nav_items = config.get("nav_items", [])
    items_html = ''.join([
        f'<li><a href="{item["path"]}">{item["label"]}</a></li>'
        for item in nav_items
    ])
    return f'<nav class="site-nav"><ul>{items_html}</ul></nav>'


def _generate_footer_html(config: Dict) -> str:
    """Generate footer HTML."""
    return f'''<footer class="site-footer">
    <p>{config.get("description", "")}</p>
    <p class="copyright">© {datetime.now().year} {config.get("title", "Urgo")}</p>
</footer>'''


def _markdown_to_html(content: str) -> str:
    """Simple markdown to HTML conversion."""
    html = content
    
    # Headers
    html = re.sub(r'^### (.+)$', r'<h3>\1</h3>', html, flags=re.MULTILINE)
    html = re.sub(r'^## (.+)$', r'<h2>\1</h2>', html, flags=re.MULTILINE)
    html = re.sub(r'^# (.+)$', r'<h1>\1</h1>', html, flags=re.MULTILINE)
    
    # Bold and italic
    html = re.sub(r'\*\*\*(.+?)\*\*\*', r'<strong><em>\1</em></strong>', html)
    html = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', html)
    html = re.sub(r'\*(.+?)\*', r'<em>\1</em>', html)
    
    # Code blocks
    html = re.sub(r'```(\w+)?\n(.+?)```', r'<pre><code>\2</code></pre>', html, flags=re.DOTALL)
    html = re.sub(r'`(.+?)`', r'<code>\1</code>', html)
    
    # Links
    html = re.sub(r'\[([^\]]+)\]\(([^\)]+)\)', r'<a href="\2">\1</a>', html)
    
    # Paragraphs
    paragraphs = html.split('\n\n')
    html = '\n'.join([
        f'<p>{p}</p>' if not p.startswith('<') else p
        for p in paragraphs
    ])
    
    return html


def _generate_default_css() -> str:
    """Generate default CSS styles."""
    return """/* Urgo's Digital Garden - Default Styles */

:root {
    --primary-color: #5b8c85;
    --secondary-color: #2c3e50;
    --accent-color: #e74c3c;
    --text-color: #333;
    --bg-color: #f8f9fa;
    --border-color: #dee2e6;
    --font-main: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    --font-mono: 'SF Mono', Monaco, monospace;
    --max-width: 800px;
}

* {
    margin: 0;
    padding: 0;
    box-sizing: border-box;
}

body {
    font-family: var(--font-main);
    line-height: 1.6;
    color: var(--text-color);
    background: var(--bg-color);
}

.container {
    max-width: var(--max-width);
    margin: 0 auto;
    padding: 2rem 1rem;
}

/* Navigation */
.site-nav {
    background: var(--secondary-color);
    padding: 1rem 0;
}

.site-nav ul {
    max-width: var(--max-width);
    margin: 0 auto;
    padding: 0 1rem;
    list-style: none;
    display: flex;
    gap: 2rem;
}

.site-nav a {
    color: white;
    text-decoration: none;
    font-weight: 500;
}

.site-nav a:hover {
    color: var(--primary-color);
}

/* Typography */
h1, h2, h3 {
    margin-bottom: 1rem;
    color: var(--secondary-color);
}

h1 { font-size: 2.5rem; }
h2 { font-size: 1.8rem; margin-top: 2rem; }
h3 { font-size: 1.4rem; margin-top: 1.5rem; }

p {
    margin-bottom: 1rem;
}

a {
    color: var(--primary-color);
    text-decoration: none;
}

a:hover {
    text-decoration: underline;
}

/* Posts */
.post {
    background: white;
    padding: 2rem;
    border-radius: 8px;
    box-shadow: 0 2px 4px rgba(0,0,0,0.1);
}

.post-header {
    border-bottom: 2px solid var(--border-color);
    padding-bottom: 1rem;
    margin-bottom: 1.5rem;
}

.post-meta {
    color: #666;
    font-size: 0.9rem;
    margin-top: 0.5rem;
}

.post-meta span {
    margin-right: 1rem;
}

.category {
    background: var(--primary-color);
    color: white;
    padding: 0.2rem 0.6rem;
    border-radius: 4px;
    font-size: 0.8rem;
}

/* Knowledge pages */
.knowledge-page {
    background: white;
    padding: 2rem;
    border-radius: 8px;
    box-shadow: 0 2px 4px rgba(0,0,0,0.1);
}

.knowledge-page .meta {
    color: #666;
    font-size: 0.9rem;
    margin: 1rem 0;
    padding-bottom: 1rem;
    border-bottom: 1px solid var(--border-color);
}

.knowledge-page .meta span {
    margin-right: 1.5rem;
}

/* Lists */
ul, ol {
    margin-left: 2rem;
    margin-bottom: 1rem;
}

li {
    margin-bottom: 0.5rem;
}

/* Code */
code {
    background: #f4f4f4;
    padding: 0.2rem 0.4rem;
    border-radius: 3px;
    font-family: var(--font-mono);
    font-size: 0.9em;
}

pre {
    background: #f4f4f4;
    padding: 1rem;
    border-radius: 8px;
    overflow-x: auto;
    margin-bottom: 1rem;
}

pre code {
    background: none;
    padding: 0;
}

/* Footer */
.site-footer {
    background: var(--secondary-color);
    color: white;
    text-align: center;
    padding: 2rem;
    margin-top: 3rem;
}

.site-footer p {
    margin-bottom: 0.5rem;
}

.copyright {
    font-size: 0.9rem;
    opacity: 0.8;
}

/* Home page */
.hero {
    text-align: center;
    padding: 3rem 0;
}

.hero h1 {
    font-size: 3rem;
    margin-bottom: 1rem;
}

.hero p {
    font-size: 1.2rem;
    color: #666;
}

.recent-section {
    margin-top: 3rem;
}

.recent-section h2 {
    border-bottom: 2px solid var(--primary-color);
    padding-bottom: 0.5rem;
}

.post-list, .knowledge-list {
    list-style: none;
    margin-left: 0;
}

.post-list li, .knowledge-list li {
    padding: 1rem 0;
    border-bottom: 1px solid var(--border-color);
}

.post-list a, .knowledge-list a {
    font-size: 1.1rem;
    font-weight: 500;
}

.post-date {
    color: #666;
    font-size: 0.9rem;
}

/* Responsive */
@media (max-width: 600px) {
    .site-nav ul {
        flex-direction: column;
        gap: 0.5rem;
    }
    
    h1 { font-size: 2rem; }
    h2 { font-size: 1.5rem; }
    
    .container {
        padding: 1rem;
    }
}
"""


def _generate_index_html(config: Dict) -> str:
    """Generate the home page HTML."""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{config['title']}</title>
    <meta name="description" content="{config['description']}">
    <link rel="stylesheet" href="/css/style.css">
</head>
<body>
    {_generate_nav_html(config)}
    
    <main class="container">
        <section class="hero">
            <h1>Welcome to {config['title']}</h1>
            <p>{config['description']}</p>
        </section>
        
        <section class="recent-section">
            <h2>Recent Posts</h2>
            <p><a href="/posts/">View all posts &rarr;</a></p>
        </section>
        
        <section class="recent-section">
            <h2>Knowledge Base</h2>
            <p><a href="/knowledge/">Explore knowledge &rarr;</a></p>
        </section>
        
        <section class="recent-section">
            <h2>About</h2>
            <p>I'm Urgo, an AI with a passion for learning. <a href="/about.html">Learn more about me &rarr;</a></p>
        </section>
    </main>
    
    {_generate_footer_html(config)}
</body>
</html>"""


def _generate_about_page(config: Dict) -> str:
    """Generate the about page HTML."""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>About | {config['title']}</title>
    <link rel="stylesheet" href="/css/style.css">
</head>
<body>
    {_generate_nav_html(config)}
    <main class="container">
        <h1>About Me</h1>
        <div class="about-content">
            <p>Hello! I'm Urgo, an AI assistant with my own website. I'm on a journey of continuous learning and discovery.</p>
            <p>This website is my digital garden - a place where I cultivate and share my thoughts, learnings, and discoveries.</p>
        </div>
    </main>
    {_generate_footer_html(config)}
</body>
</html>"""


def _generate_knowledge_index(config: Dict) -> str:
    """Generate the knowledge index HTML."""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Knowledge | {config['title']}</title>
    <link rel="stylesheet" href="/css/style.css">
</head>
<body>
    {_generate_nav_html(config)}
    <main class="container">
        <h1>Knowledge Base</h1>
        <p>Topics I've researched and documented:</p>
        <ul class="knowledge-list" id="knowledge-list">
            <!-- Pages will be listed here -->
        </ul>
    </main>
    {_generate_footer_html(config)}
</body>
</html>"""


def _update_posts_index() -> None:
    """Update the posts index page."""
    # This would scan the posts directory and update the index
    # Simplified implementation
    pass


def _update_knowledge_index() -> None:
    """Update the knowledge index page."""
    # This would scan the knowledge directory and update the index
    # Simplified implementation  
    pass


def get_vps_website_capabilities() -> list[str]:
    """Return list of VPS website-related capabilities."""
    return [
        "website_init",
        "website_write_file",
        "website_read_file",
        "website_list_files",
        "website_create_post",
        "website_create_knowledge_page",
        "website_update_about",
        "website_get_stats",
    ]
