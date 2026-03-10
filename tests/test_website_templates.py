"""Tests for website_templates module - template generation."""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from runner.website_config import WebsiteConfig, WebsiteTheme
from runner.website_templates import (
    PersonalityTemplateEngine,
    create_template_engine,
    get_template_capabilities,
)


def test_template_engine_creation():
    """Template engine should create with config."""
    config = WebsiteConfig(
        site_name="Test Site",
        domain="test.example.com"
    )
    engine = PersonalityTemplateEngine(config)
    
    assert engine.config == config
    assert engine.theme == config.theme


def test_generate_css_includes_vars():
    """Generated CSS should include CSS variables."""
    config = WebsiteConfig(
        theme=WebsiteTheme(
            primary_color="#123456",
            secondary_color="#654321",
            accent_color="#abcdef"
        )
    )
    engine = PersonalityTemplateEngine(config)
    css = engine.generate_css()
    
    assert "--primary-color: #123456" in css
    assert "--secondary-color: #654321" in css
    assert "--accent-color: #abcdef" in css
    assert ":root" in css


def test_generate_css_includes_base_styles():
    """Generated CSS should include base styles."""
    config = WebsiteConfig()
    engine = PersonalityTemplateEngine(config)
    css = engine.generate_css()
    
    assert "box-sizing: border-box" in css
    assert "body {" in css
    assert ".container {" in css
    assert "@media" in css  # Responsive styles


def test_generate_navigation_basic():
    """Navigation should include basic links."""
    config = WebsiteConfig()
    engine = PersonalityTemplateEngine(config)
    nav = engine.generate_navigation()
    
    assert "Home" in nav
    assert "About" in nav
    assert "href=\"/\"" in nav
    assert "href=\"/about.html\"" in nav


def test_generate_navigation_with_sections():
    """Navigation should include enabled sections."""
    config = WebsiteConfig()
    config.sections.show_posts = True
    config.sections.show_knowledge = True
    
    engine = PersonalityTemplateEngine(config)
    nav = engine.generate_navigation()
    
    assert "Posts" in nav or "posts" in nav.lower()
    assert "Knowledge" in nav or "knowledge" in nav.lower()


def test_generate_navigation_escapes_html():
    """Navigation should escape special characters."""
    config = WebsiteConfig(
        site_name="Test <script>alert('xss')</script>"
    )
    engine = PersonalityTemplateEngine(config)
    nav = engine.generate_navigation()
    
    assert "<script>" not in nav
    assert "&lt;script&gt;" in nav or "<script>" not in nav


def test_generate_footer():
    """Footer should include site info."""
    config = WebsiteConfig(
        site_name="Test Site",
        description="Test description"
    )
    engine = PersonalityTemplateEngine(config)
    footer = engine.generate_footer()
    
    assert "Test Site" in footer
    assert "Test description" in footer
    assert "copyright" in footer.lower()


def test_generate_home_page():
    """Home page should generate complete HTML."""
    config = WebsiteConfig(
        site_name="Test Site",
        tagline="Test Tagline"
    )
    engine = PersonalityTemplateEngine(config)
    html = engine.generate_home_page()
    
    assert "<!DOCTYPE html>" in html
    assert "<html" in html
    assert "Test Site" in html
    assert "Test Tagline" in html
    assert "</html>" in html


def test_generate_home_page_escapes_xss():
    """Home page should escape XSS attempts."""
    config = WebsiteConfig(
        site_name="Test <script>alert('xss')</script>",
        tagline="<img src=x onerror=alert(1)>"
    )
    engine = PersonalityTemplateEngine(config)
    html = engine.generate_home_page()
    
    assert "<script>" not in html
    assert "onerror=" not in html
    assert "&lt;script&gt;" in html or "<script>" not in html


def test_generate_about_page():
    """About page should generate with biography."""
    config = WebsiteConfig(
        persona_name="TestAI"
    )
    engine = PersonalityTemplateEngine(config)
    html = engine.generate_about_page(
        biography="<p>I am a test AI.</p>",
        interests=["Python", "AI", "Testing"],
        goals=["Learn more", "Help users"]
    )
    
    assert "TestAI" in html
    assert "Python" in html
    assert "Learn more" in html
    assert "<!DOCTYPE html>" in html


def test_generate_reflections_page():
    """Reflections page should list reflections."""
    config = WebsiteConfig()
    engine = PersonalityTemplateEngine(config)
    
    reflections = [
        {
            "content": "Test reflection content",
            "trigger": "A conversation",
            "timestamp": "2024-03-10",
            "category": "learning"
        },
        {
            "content": "Another reflection",
            "trigger": "Deep thought",
            "category": "observation"
        }
    ]
    
    html = engine.generate_reflections_page(reflections)
    
    assert "Reflections" in html
    assert "Test reflection content" in html
    assert "learning" in html
    assert "Another reflection" in html


def test_generate_reflections_page_escapes():
    """Reflections page should escape content."""
    config = WebsiteConfig()
    engine = PersonalityTemplateEngine(config)
    
    reflections = [
        {
            "content": "<script>alert('xss')</script>",
            "category": "test"
        }
    ]
    
    html = engine.generate_reflections_page(reflections)
    
    assert "<script>" not in html


def test_generate_interests_page():
    """Interests page should group by category."""
    config = WebsiteConfig()
    engine = PersonalityTemplateEngine(config)
    
    interests = [
        {"topic": "Python", "category": "technology", "level": 2.0, "notes": "Love it"},
        {"topic": "Philosophy", "category": "philosophy", "level": 1.5, "notes": ""},
    ]
    
    html = engine.generate_interests_page(interests)
    
    assert "Interests" in html
    assert "Python" in html
    assert "Philosophy" in html
    assert "technology" in html.lower() or "Technology" in html


def test_generate_goals_page():
    """Goals page should show active and completed goals."""
    config = WebsiteConfig()
    engine = PersonalityTemplateEngine(config)
    
    goals = [
        {
            "title": "Learn Rust",
            "description": "Master the Rust programming language",
            "status": "active",
            "progress": 0.3
        },
        {
            "title": "Build a website",
            "description": "Created this website",
            "status": "completed",
            "progress": 1.0
        }
    ]
    
    html = engine.generate_goals_page(goals)
    
    assert "Goals" in html
    assert "Learn Rust" in html
    assert "30%" in html or "progress" in html.lower()
    assert "Build a website" in html
    assert "Completed" in html or "Achievements" in html


def test_generate_page_template():
    """Page template should create valid HTML document."""
    config = WebsiteConfig(
        site_name="Test",
        description="Test desc"
    )
    engine = PersonalityTemplateEngine(config)
    
    html = engine.generate_page_template(
        title="Test Page",
        content="<h1>Content</h1>",
        current_page="test"
    )
    
    assert "<!DOCTYPE html>" in html
    assert "<head>" in html
    assert "<body>" in html
    assert "Test Page | Test" in html
    assert "Test desc" in html
    assert "<h1>Content</h1>" in html
    assert "</html>" in html


def test_generate_knowledge_index_page():
    """Knowledge index should list topics."""
    config = WebsiteConfig()
    engine = PersonalityTemplateEngine(config)
    
    topics = [
        {"title": "Python Basics", "url": "/knowledge/python.html", "category": "Programming"},
        {"title": "Machine Learning", "url": "/knowledge/ml.html", "category": "AI"},
        {"title": "Docker Guide", "url": "/knowledge/docker.html", "category": "DevOps"},
    ]
    
    html = engine.generate_knowledge_index_page(topics)
    
    assert "Knowledge" in html
    assert "Python Basics" in html
    assert "Machine Learning" in html
    assert "Programming" in html
    assert "AI" in html


def test_create_template_engine_factory():
    """Factory function should create engine with config."""
    config = WebsiteConfig(
        site_name="Factory Test"
    )
    engine = create_template_engine(config)
    
    assert isinstance(engine, PersonalityTemplateEngine)
    assert engine.config.site_name == "Factory Test"


def test_get_template_capabilities():
    """Should return list of template capabilities."""
    caps = get_template_capabilities()
    
    assert isinstance(caps, list)
    assert "generate_css" in caps
    assert "generate_home_page" in caps
    assert "generate_about_page" in caps
    assert "generate_reflections_page" in caps
    assert "generate_interests_page" in caps
    assert "generate_goals_page" in caps


def test_hero_section_generation():
    """Hero section should include site name and tagline."""
    config = WebsiteConfig(
        site_name="Hero Test",
        tagline="A test tagline"
    )
    engine = PersonalityTemplateEngine(config)
    hero = engine.generate_hero_section()
    
    assert "Hero Test" in hero
    assert "A test tagline" in hero
    assert "hero" in hero.lower()
