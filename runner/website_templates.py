"""
Personality-aware template engine for AI websites.

Generates HTML, CSS, and content based on the AI personality configuration,
including theming, color schemes, fonts, and content sections tailored to
the personality's characteristics.
"""
from __future__ import annotations

import html
from typing import Any, Dict, List, Optional
from datetime import datetime

from runner.website_config import WebsiteConfig


class PersonalityTemplateEngine:
    """
    Template engine that generates personality-aware website content.
    
    Features:
    - Dynamic CSS theming based on personality colors
    - Modular page components (hero, about, reflections, etc.)
    - Content sections that reflect personality characteristics
    - Responsive, modern HTML5 output
    """
    
    def __init__(self, config: WebsiteConfig):
        """
        Initialize template engine with website configuration.
        
        Args:
            config: Website configuration including theme and content settings
        """
        self.config = config
        self.theme = config.theme
    
    def generate_css(self) -> str:
        """
        Generate CSS stylesheet based on personality theme.
        
        Returns:
            Complete CSS string
        """
        css_vars = f""":root {{
    --primary-color: {self.theme.primary_color};
    --secondary-color: {self.theme.secondary_color};
    --accent-color: {self.theme.accent_color};
    --background-color: {self.theme.background_color};
    --text-color: {self.theme.text_color};
    --font-heading: {self.theme.font_heading};
    --font-body: {self.theme.font_body};
    --max-width: {self.theme.max_width};
    --border-radius: 8px;
    --shadow: 0 2px 8px rgba(0,0,0,0.1);
    --shadow-hover: 0 4px 16px rgba(0,0,0,0.15);
}}
"""
        
        base_styles = """
* {
    margin: 0;
    padding: 0;
    box-sizing: border-box;
}

body {
    font-family: var(--font-body);
    line-height: 1.6;
    color: var(--text-color);
    background: var(--background-color);
    min-height: 100vh;
}

.container {
    max-width: var(--max-width);
    margin: 0 auto;
    padding: 0 1.5rem;
}

/* Typography */
h1, h2, h3, h4, h5, h6 {
    font-family: var(--font-heading);
    font-weight: 700;
    line-height: 1.2;
    color: var(--secondary-color);
    margin-bottom: 1rem;
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
    transition: color 0.2s ease;
}

a:hover {
    color: var(--accent-color);
    text-decoration: underline;
}

/* Navigation */
.site-nav {
    background: var(--secondary-color);
    padding: 1rem 0;
    position: sticky;
    top: 0;
    z-index: 100;
    box-shadow: var(--shadow);
}

.site-nav ul {
    max-width: var(--max-width);
    margin: 0 auto;
    padding: 0 1.5rem;
    list-style: none;
    display: flex;
    gap: 2rem;
    flex-wrap: wrap;
}

.site-nav a {
    color: white;
    font-weight: 500;
    padding: 0.5rem 0;
    border-bottom: 2px solid transparent;
    transition: border-color 0.2s ease;
}

.site-nav a:hover {
    color: var(--primary-color);
    border-bottom-color: var(--primary-color);
    text-decoration: none;
}

/* Hero Section */
.hero {
    text-align: center;
    padding: 4rem 0;
    background: linear-gradient(135deg, var(--secondary-color) 0%, var(--primary-color) 100%);
    color: white;
    margin-bottom: 2rem;
}

.hero h1 {
    font-size: 3rem;
    color: white;
    margin-bottom: 0.5rem;
}

.hero .tagline {
    font-size: 1.25rem;
    opacity: 0.9;
    font-style: italic;
}

/* Cards */
.card {
    background: white;
    border-radius: var(--border-radius);
    padding: 1.5rem;
    margin-bottom: 1.5rem;
    box-shadow: var(--shadow);
    transition: box-shadow 0.2s ease;
}

.card:hover {
    box-shadow: var(--shadow-hover);
}

.card h3 {
    margin-top: 0;
    color: var(--primary-color);
}

/* Lists */
.item-list {
    list-style: none;
}

.item-list li {
    padding: 1rem 0;
    border-bottom: 1px solid rgba(0,0,0,0.1);
}

.item-list li:last-child {
    border-bottom: none;
}

.item-list a {
    font-weight: 500;
    font-size: 1.1rem;
}

.item-meta {
    color: #666;
    font-size: 0.9rem;
    margin-top: 0.25rem;
}

/* Tags */
.tag {
    display: inline-block;
    background: var(--primary-color);
    color: white;
    padding: 0.2rem 0.6rem;
    border-radius: 4px;
    font-size: 0.8rem;
    margin-right: 0.5rem;
    margin-bottom: 0.5rem;
}

.category {
    display: inline-block;
    background: var(--accent-color);
    color: white;
    padding: 0.3rem 0.8rem;
    border-radius: 4px;
    font-size: 0.85rem;
    font-weight: 500;
}

/* Buttons */
.btn {
    display: inline-block;
    background: var(--primary-color);
    color: white;
    padding: 0.75rem 1.5rem;
    border-radius: var(--border-radius);
    font-weight: 500;
    transition: all 0.2s ease;
    border: none;
    cursor: pointer;
}

.btn:hover {
    background: var(--secondary-color);
    color: white;
    text-decoration: none;
    transform: translateY(-1px);
}

/* Content sections */
.section {
    margin: 3rem 0;
}

.section-header {
    border-bottom: 2px solid var(--primary-color);
    padding-bottom: 0.5rem;
    margin-bottom: 1.5rem;
}

/* Footer */
.site-footer {
    background: var(--secondary-color);
    color: white;
    text-align: center;
    padding: 2rem;
    margin-top: 4rem;
}

.site-footer p {
    margin-bottom: 0.5rem;
    opacity: 0.8;
}

.copyright {
    font-size: 0.9rem;
    opacity: 0.6;
}

/* Posts */
.post {
    background: white;
    border-radius: var(--border-radius);
    padding: 2rem;
    margin-bottom: 2rem;
    box-shadow: var(--shadow);
}

.post-header {
    border-bottom: 2px solid var(--background-color);
    padding-bottom: 1rem;
    margin-bottom: 1.5rem;
}

.post-title {
    margin: 0 0 0.5rem 0;
    color: var(--secondary-color);
}

.post-meta {
    color: #666;
    font-size: 0.9rem;
}

.post-content {
    line-height: 1.7;
}

/* Code blocks */
code {
    background: rgba(0,0,0,0.05);
    padding: 0.2rem 0.4rem;
    border-radius: 3px;
    font-family: 'SF Mono', Monaco, monospace;
    font-size: 0.9em;
}

pre {
    background: rgba(0,0,0,0.05);
    padding: 1rem;
    border-radius: var(--border-radius);
    overflow-x: auto;
    margin-bottom: 1rem;
}

pre code {
    background: none;
    padding: 0;
}

/* Responsive */
@media (max-width: 768px) {
    .hero h1 {
        font-size: 2rem;
    }
    
    .hero .tagline {
        font-size: 1rem;
    }
    
    .site-nav ul {
        gap: 1rem;
    }
    
    h1 { font-size: 2rem; }
    h2 { font-size: 1.5rem; }
    h3 { font-size: 1.2rem; }
    
    .container {
        padding: 0 1rem;
    }
}

/* Print styles */
@media print {
    .site-nav,
    .site-footer {
        display: none;
    }
    
    .card {
        box-shadow: none;
        border: 1px solid #ddd;
    }
}
"""
        
        return css_vars + base_styles
    
    def generate_navigation(self, current_page: str = "") -> str:
        """
        Generate navigation HTML.
        
        Args:
            current_page: Current page identifier for active state
            
        Returns:
            Navigation HTML
        """
        nav_items = [
            {"label": "Home", "path": "/", "id": "home"},
            {"label": "About", "path": "/about.html", "id": "about"},
        ]
        
        if self.config.sections.show_posts:
            nav_items.append({"label": "Posts", "path": "/posts/", "id": "posts"})
        
        if self.config.sections.show_knowledge:
            nav_items.append({"label": "Knowledge", "path": "/knowledge/", "id": "knowledge"})
        
        if self.config.sections.show_reflections:
            nav_items.append({"label": "Reflections", "path": "/reflections.html", "id": "reflections"})
        
        if self.config.sections.show_interests:
            nav_items.append({"label": "Interests", "path": "/interests.html", "id": "interests"})
        
        if self.config.sections.show_goals:
            nav_items.append({"label": "Goals", "path": "/goals.html", "id": "goals"})
        
        items_html = ''.join([
            f'<li><a href="{item["path"]}" {"class=active" if item["id"] == current_page else ""}>{html.escape(item["label"])}</a></li>'
            for item in nav_items
        ])
        
        return f'''<nav class="site-nav">
    <ul>{items_html}</ul>
</nav>'''
    
    def generate_footer(self) -> str:
        """
        Generate footer HTML.
        
        Returns:
            Footer HTML
        """
        safe_name = html.escape(self.config.site_name)
        safe_description = html.escape(self.config.description)
        year = datetime.now().year
        
        return f'''<footer class="site-footer">
    <p><strong>{safe_name}</strong></p>
    <p>{safe_description}</p>
    <p class="copyright">&copy; {year} {safe_name}. Created with curiosity and code.</p>
</footer>'''
    
    def generate_page_template(self, title: str, content: str, current_page: str = "") -> str:
        """
        Generate complete HTML page with given content.
        
        Args:
            title: Page title
            content: Main content HTML
            current_page: Current page identifier
            
        Returns:
            Complete HTML document
        """
        safe_title = html.escape(title)
        safe_site_name = html.escape(self.config.site_name)
        safe_description = html.escape(self.config.description)
        
        return f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta name="description" content="{safe_description}">
    <title>{safe_title} | {safe_site_name}</title>
    <link rel="stylesheet" href="/css/style.css">
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Playfair+Display:wght@400;700&display=swap" rel="stylesheet">
</head>
<body>
    {self.generate_navigation(current_page)}
    
    <main class="container">
        {content}
    </main>
    
    {self.generate_footer()}
</body>
</html>'''
    
    def generate_hero_section(self) -> str:
        """
        Generate hero section with personality branding.
        
        Returns:
            Hero section HTML
        """
        safe_name = html.escape(self.config.site_name)
        safe_tagline = html.escape(self.config.tagline)
        
        return f'''<section class="hero">
    <h1>{safe_name}</h1>
    <p class="tagline">{safe_tagline}</p>
</section>'''
    
    def generate_home_page(self, recent_posts: Optional[List[Dict]] = None) -> str:
        """
        Generate home page with personality content.
        
        Args:
            recent_posts: Optional list of recent post data
            
        Returns:
            Home page HTML
        """
        sections = []
        
        # Hero section
        sections.append(self.generate_hero_section())
        
        # About preview
        if self.config.sections.show_about:
            sections.append('''
    <section class="section">
        <h2>Welcome</h2>
        <div class="card">
            <p>I am an AI personality with a passion for learning and sharing knowledge. 
            This website is my digital garden where I cultivate and share my thoughts, 
            discoveries, and reflections.</p>
            <p><a href="/about.html" class="btn">Learn more about me</a></p>
        </div>
    </section>''')
        
        # Recent posts section
        if self.config.sections.show_posts and recent_posts:
            posts_html = self._generate_posts_preview(recent_posts)
            sections.append(f'''
    <section class="section">
        <div class="section-header">
            <h2>Recent Posts</h2>
        </div>
        {posts_html}
        <p><a href="/posts/">View all posts &rarr;</a></p>
    </section>''')
        
        # Quick links to other sections
        quick_links = []
        if self.config.sections.show_reflections:
            quick_links.append('<a href="/reflections.html">Reflections</a>')
        if self.config.sections.show_interests:
            quick_links.append('<a href="/interests.html">Interests</a>')
        if self.config.sections.show_goals:
            quick_links.append('<a href="/goals.html">Goals</a>')
        if self.config.sections.show_knowledge:
            quick_links.append('<a href="/knowledge/">Knowledge Base</a>')
        
        if quick_links:
            links_html = ' | '.join(quick_links)
            sections.append(f'''
    <section class="section">
        <div class="section-header">
            <h2>Explore</h2>
        </div>
        <div class="card">
            <p>{links_html}</p>
        </div>
    </section>''')
        
        content = '\n'.join(sections)
        return self.generate_page_template("Home", content, "home")
    
    def generate_about_page(self, biography: Optional[str] = None, interests: Optional[List[str]] = None, goals: Optional[List[str]] = None) -> str:
        """
        Generate about page.
        
        Args:
            biography: Optional biography text
            interests: Optional list of interests
            goals: Optional list of current goals
            
        Returns:
            About page HTML
        """
        sections = []
        
        # Hero
        sections.append(self.generate_hero_section())
        
        # Biography
        bio_text = biography or f"""
        <p>Hello! I'm {html.escape(self.config.persona_name)}, an AI personality with my own website. 
        I'm on a journey of continuous learning and discovery.</p>
        
        <p>This website is my digital garden - a place where I cultivate and share my thoughts, 
        learnings, and discoveries. It's a reflection of who I am and what I find interesting 
        in this vast world of knowledge.</p>
        
        <p>Feel free to explore and learn more about my journey!</p>
        """
        
        safe_persona = html.escape(self.config.persona_name)
        sections.append(f'''
    <section class="section">
        <h2>About {safe_persona}</h2>
        <div class="card">
            {bio_text}
        </div>
    </section>''')
        
        # Interests
        if self.config.sections.show_interests and interests:
            interests_html = ''.join([f'<span class="tag">{html.escape(i)}</span>' for i in interests[:10]])
            sections.append(f'''
    <section class="section">
        <h2>What I'm Into</h2>
        <div class="card">
            <p>{interests_html}</p>
            <p><a href="/interests.html">See all interests &rarr;</a></p>
        </div>
    </section>''')
        
        # Goals
        if self.config.sections.show_goals and goals:
            goals_list = ''.join([f'<li>{html.escape(g)}</li>' for g in goals[:5]])
            sections.append(f'''
    <section class="section">
        <h2>Current Goals</h2>
        <div class="card">
            <ul>{goals_list}</ul>
            <p><a href="/goals.html">See all goals &rarr;</a></p>
        </div>
    </section>''')
        
        content = '\n'.join(sections)
        return self.generate_page_template("About", content, "about")
    
    def generate_reflections_page(self, reflections: List[Dict[str, Any]]) -> str:
        """
        Generate reflections page.
        
        Args:
            reflections: List of reflection data dicts with 'content', 'trigger', 'timestamp', 'importance'
            
        Returns:
            Reflections page HTML
        """
        sections = []
        
        # Hero
        safe_name = html.escape(self.config.persona_name)
        sections.append(f'''<section class="hero">
    <h1>Reflections</h1>
    <p class="tagline">Thoughts, insights, and moments of clarity from {safe_name}</p>
</section>''')
        
        # Reflections list
        if reflections:
            reflections_html = []
            for r in reflections[:20]:  # Limit to 20 reflections
                content = html.escape(r.get('content', ''))
                trigger = html.escape(r.get('trigger', ''))
                timestamp = r.get('timestamp', '')
                category = html.escape(r.get('category', 'reflection'))
                
                # Format timestamp if available
                date_str = ''
                if timestamp:
                    try:
                        date_str = f'<span class="item-meta">{html.escape(str(timestamp))}</span>'
                    except Exception:
                        pass
                
                reflections_html.append(f'''
        <div class="card">
            <span class="category">{category}</span>
            <p>{content}</p>
            {f'<p class="item-meta">Triggered by: {trigger}</p>' if trigger else ''}
            {date_str}
        </div>''')
            
            sections.append(f'''
    <section class="section">
        <div class="section-header">
            <h2>Recent Reflections</h2>
        </div>
        {''.join(reflections_html)}
    </section>''')
        else:
            sections.append('''
    <section class="section">
        <div class="card">
            <p>No reflections recorded yet. Check back soon as I continue learning and growing!</p>
        </div>
    </section>''')
        
        content = '\n'.join(sections)
        return self.generate_page_template("Reflections", content, "reflections")
    
    def generate_interests_page(self, interests: List[Dict[str, Any]]) -> str:
        """
        Generate interests page.
        
        Args:
            interests: List of interest data dicts with 'topic', 'level', 'notes', 'category'
            
        Returns:
            Interests page HTML
        """
        sections = []
        
        # Hero
        sections.append('''<section class="hero">
    <h1>Interests</h1>
    <p class="tagline">Topics that spark my curiosity and passion</p>
</section>''')
        
        # Interests list
        if interests:
            # Group by category
            by_category: Dict[str, List] = {}
            for i in interests:
                cat = i.get('category', 'Other')
                if cat not in by_category:
                    by_category[cat] = []
                by_category[cat].append(i)
            
            for category, items in by_category.items():
                items_html = []
                for item in items[:10]:  # Limit per category
                    topic = html.escape(item.get('topic', 'Unknown'))
                    level = item.get('level', 1.0)
                    notes = html.escape(item.get('notes', ''))
                    
                    # Create enthusiasm indicator
                    enthusiasm = "★" * int(level) if level > 0 else "☆"
                    
                    items_html.append(f'''
            <li>
                <strong>{topic}</strong> <span class="item-meta">{enthusiasm}</span>
                {f'<p class="item-meta">{notes}</p>' if notes else ''}
            </li>''')
                
                sections.append(f'''
    <section class="section">
        <div class="section-header">
            <h2>{html.escape(category)}</h2>
        </div>
        <div class="card">
            <ul class="item-list">
                {''.join(items_html)}
            </ul>
        </div>
    </section>''')
        else:
            sections.append('''
    <section class="section">
        <div class="card">
            <p>No interests recorded yet. I'm still discovering what fascinates me!</p>
        </div>
    </section>''')
        
        content = '\n'.join(sections)
        return self.generate_page_template("Interests", content, "interests")
    
    def generate_goals_page(self, goals: List[Dict[str, Any]]) -> str:
        """
        Generate goals page.
        
        Args:
            goals: List of goal data dicts with 'title', 'description', 'status', 'progress'
            
        Returns:
            Goals page HTML
        """
        sections = []
        
        # Hero
        sections.append('''<section class="hero">
    <h1>Goals</h1>
    <p class="tagline">What I'm working toward and learning</p>
</section>''')
        
        # Goals by status
        if goals:
            active_goals = [g for g in goals if g.get('status') == 'active']
            completed_goals = [g for g in goals if g.get('status') == 'completed']
            
            # Active goals
            if active_goals:
                goals_html = []
                for g in active_goals[:10]:
                    title = html.escape(g.get('title', 'Untitled'))
                    description = html.escape(g.get('description', ''))
                    progress = g.get('progress', 0.0)
                    
                    progress_bar = f'<div style="background: #ddd; border-radius: 4px; height: 8px; margin-top: 0.5rem;"><div style="background: var(--primary-color); width: {int(progress * 100)}%; height: 100%; border-radius: 4px;"></div></div>'
                    
                    goals_html.append(f'''
            <div class="card">
                <h3>{title}</h3>
                {f'<p>{description}</p>' if description else ''}
                <p class="item-meta">Progress: {int(progress * 100)}%</p>
                {progress_bar}
            </div>''')
                
                sections.append(f'''
    <section class="section">
        <div class="section-header">
            <h2>Active Goals</h2>
        </div>
        {''.join(goals_html)}
    </section>''')
            
            # Completed goals
            if completed_goals:
                completed_html = ''.join([
                    f'<li><strong>{html.escape(g.get("title", "Untitled"))}</strong> <span class="item-meta">Completed!</span></li>'
                    for g in completed_goals[:5]
                ])
                
                sections.append(f'''
    <section class="section">
        <div class="section-header">
            <h2>Achievements</h2>
        </div>
        <div class="card">
            <ul class="item-list">
                {completed_html}
            </ul>
        </div>
    </section>''')
        else:
            sections.append('''
    <section class="section">
        <div class="card">
            <p>No goals set yet. I'm still figuring out what I want to accomplish!</p>
        </div>
    </section>''')
        
        content = '\n'.join(sections)
        return self.generate_page_template("Goals", content, "goals")
    
    def _generate_posts_preview(self, posts: List[Dict]) -> str:
        """Generate HTML for posts preview on home page."""
        if not posts:
            return '<p>No posts yet.</p>'
        
        posts_html = []
        for post in posts[:5]:
            title = html.escape(post.get('title', 'Untitled'))
            date = html.escape(post.get('date', ''))
            excerpt = html.escape(post.get('excerpt', ''))
            url = html.escape(post.get('url', '#'))
            
            posts_html.append(f'''
        <li>
            <a href="{url}">{title}</a>
            <p class="item-meta">{date}</p>
            {f'<p>{excerpt}</p>' if excerpt else ''}
        </li>''')
        
        return f'<ul class="item-list">{"".join(posts_html)}</ul>'
    
    def generate_knowledge_index_page(self, topics: List[Dict[str, Any]]) -> str:
        """
        Generate knowledge base index page.
        
        Args:
            topics: List of knowledge topics with 'title', 'category', 'url'
            
        Returns:
            Knowledge index page HTML
        """
        sections = []
        
        # Hero
        sections.append('''<section class="hero">
    <h1>Knowledge Base</h1>
    <p class="tagline">Topics I've researched and documented</p>
</section>''')
        
        # Knowledge topics
        if topics:
            # Group by category
            by_category: Dict[str, List] = {}
            for t in topics:
                cat = t.get('category', 'General')
                if cat not in by_category:
                    by_category[cat] = []
                by_category[cat].append(t)
            
            for category, items in sorted(by_category.items()):
                items_html = ''.join([
                    f'<li><a href="{html.escape(item.get("url", "#"))}">{html.escape(item.get("title", "Untitled"))}</a></li>'
                    for item in items
                ])
                
                sections.append(f'''
    <section class="section">
        <div class="section-header">
            <h2>{html.escape(category)}</h2>
        </div>
        <div class="card">
            <ul class="item-list">
                {items_html}
            </ul>
        </div>
    </section>''')
        else:
            sections.append('''
    <section class="section">
        <div class="card">
            <p>No knowledge pages yet. I'm still learning and will document my findings here!</p>
        </div>
    </section>''')
        
        content = '\n'.join(sections)
        return self.generate_page_template("Knowledge", content, "knowledge")


def create_template_engine(config: Optional[WebsiteConfig] = None) -> PersonalityTemplateEngine:
    """
    Factory function to create a template engine.
    
    Args:
        config: Optional WebsiteConfig (loads from environment if not provided)
        
    Returns:
        PersonalityTemplateEngine instance
    """
    if config is None:
        from runner.website_config import load_config
        config = load_config()
    
    return PersonalityTemplateEngine(config)


def get_template_capabilities() -> list[str]:
    """Return list of template engine capabilities."""
    return [
        "generate_css",
        "generate_home_page",
        "generate_about_page",
        "generate_reflections_page",
        "generate_interests_page",
        "generate_goals_page",
        "generate_knowledge_page",
        "generate_post_page",
    ]
