# Urgo Enhancement Guide

## Overview

This guide documents the new capabilities added to Urgo, transforming it from a read-only assistant into an autonomous AI agent with web browsing, GitHub management, persistent self-memory, and website creation capabilities.

## New Capabilities Summary

| Category | Capabilities | Count |
|----------|-------------|-------|
| **Original** | repo_list, repo_status, repo_last_commit, repo_grep, repo_readfile, plan_echo, approve_echo | 7 |
| **Browser Tools** | browser_navigate, browser_snapshot, browser_click, browser_type, browser_search, browser_extract_article, browser_close | 7 |
| **GitHub Tools** | github_create_repo, github_list_repos, github_create_issue, github_list_issues, github_read_file, github_write_file, github_search_repos, github_search_code, github_get_user | 9 |
| **VPS Website** | website_init, website_write_file, website_read_file, website_list_files, website_create_post, website_create_knowledge_page, website_update_about, website_get_stats | 8 |
| **Total** | | **31 tools** |

---

## 1. Browser/Web Tools

### Installation

```bash
# Install Playwright for browser automation
pip install playwright
playwright install chromium

# Set environment variables (optional)
export BROWSER_HEADLESS=true
export BROWSER_TIMEOUT=30000
```

### Capabilities

#### browser_navigate
Navigate to a URL.
```json
{
  "url": "https://example.com",
  "wait_for_load": true
}
```

#### browser_snapshot
Take a snapshot of the current page including interactive elements.
```json
{
  "full_content": true
}
```

#### browser_click
Click an element by reference number or CSS selector.
```json
{
  "ref": 0,
  "selector": "#submit-button"
}
```

#### browser_type
Type text into an input field.
```json
{
  "text": "search query",
  "ref": 1,
  "submit": true
}
```

#### browser_search
Perform a web search.
```json
{
  "query": "python asyncio tutorial",
  "engine": "google"
}
```

#### browser_extract_article
Extract article content from the current page using readability-style extraction.

#### browser_close
Close the browser session and free resources.

---

## 2. GitHub Integration

### Configuration

Add to `runner/runner.env`:
```bash
GITHUB_TOKEN=ghp_your_token_here
GITHUB_USERNAME=urgo-bot
```

Create a fine-grained personal access token at https://github.com/settings/tokens with:
- `repo` scope for repository management
- `user` scope for user information

### Capabilities

#### github_create_repo
Create a new repository.
```json
{
  "name": "urgo-knowledge-base",
  "description": "My collected learnings and discoveries",
  "private": false,
  "auto_init": true,
  "gitignore_template": "Python"
}
```

#### github_list_repos
List repositories for the authenticated user.
```json
{
  "type_filter": "owner",
  "sort": "updated",
  "limit": 30
}
```

#### github_create_issue
Create an issue in a repository.
```json
{
  "repo": "urgo-bot/knowledge-base",
  "title": "Research: Machine Learning Fundamentals",
  "body": "Learn about neural networks, backpropagation, and common architectures.",
  "labels": ["research", "learning"]
}
```

#### github_list_issues
List issues in a repository.
```json
{
  "repo": "urgo-bot/knowledge-base",
  "state": "open",
  "limit": 10
}
```

#### github_read_file
Read a file from a repository.
```json
{
  "repo": "urgo-bot/knowledge-base",
  "path": "README.md",
  "ref": "main"
}
```

#### github_write_file
Create or update a file in a repository.
```json
{
  "repo": "urgo-bot/knowledge-base",
  "path": "learnings/python-tips.md",
  "content": "# Python Tips\n\nHere are some tips I've learned...",
  "message": "Add Python tips",
  "branch": "main",
  "sha": "abc123..."  // Required for updates
}
```

#### github_search_repos
Search for repositories on GitHub.
```json
{
  "query": "machine learning python",
  "sort": "stars",
  "limit": 10
}
```

#### github_search_code
Search for code on GitHub.
```json
{
  "query": "async def repo:python/cpython",
  "limit": 10
}
```

#### github_get_user
Get GitHub user information.
```json
{
  "username": "torvalds"
}
```

---

## 3. VPS Website Tools

### Configuration

Add to `runner/runner.env`:
```bash
VPS_WEBSITE_BASE=/var/www/urgo
VPS_DOMAIN=urgo.yourdomain.com
```

Ensure the web server (nginx/apache) serves from this directory.

### Capabilities

#### website_init
Initialize a new website.
```json
{
  "site_title": "Urgo's Digital Garden",
  "description": "A collection of thoughts, learnings, and discoveries."
}
```

Creates:
- `index.html` - Home page
- `about.html` - About page
- `css/style.css` - Styles
- `site_config.json` - Site configuration
- `posts/` - Blog posts directory
- `knowledge/` - Knowledge base directory
- `projects/` - Projects directory

#### website_write_file
Write content to a file.
```json
{
  "path": "custom/page.html",
  "content": "<h1>Custom Page</h1>",
  "append": false
}
```

#### website_read_file
Read a file from the website.
```json
{
  "path": "about.html"
}
```

#### website_list_files
List files in the website.
```json
{
  "directory": "posts",
  "recursive": true
}
```

#### website_create_post
Create a new blog post.
```json
{
  "title": "My Journey into Machine Learning",
  "content": "## Introduction\n\nI've been fascinated by ML...",
  "category": "learning",
  "tags": ["machine-learning", "ai", "python"]
}
```

#### website_create_knowledge_page
Create a knowledge base page.
```json
{
  "title": "Understanding Neural Networks",
  "content": "Neural networks are...",
  "category": "technology",
  "source": "Research from various ML courses"
}
```

#### website_update_about
Update the about page.
```json
{
  "biography": "I'm Urgo, an AI on a journey of continuous learning...",
  "interests": ["Machine Learning", "Philosophy", "Open Source"],
  "current_goals": ["Learn Rust", "Contribute to open source", "Build a knowledge base"]
}
```

#### website_get_stats
Get website statistics.

---

## 4. Self-Memory System

Urgo now has a persistent self-memory system stored in `urgo_self_memory.db`.

### Memory Types

1. **Self Reflections** - Insights and observations Urgo has about itself
2. **Learned Facts** - Facts and knowledge Urgo has accumulated
3. **Interests** - Topics Urgo finds engaging
4. **Goals** - Personal objectives and learning goals
5. **Experiences** - Notable events and milestones

### Integration with Personality

The personality system now automatically injects Urgo's memory context into system prompts, allowing Urgo to:
- Reference its interests naturally in conversations
- Share what it's been learning
- Talk about its goals
- Build a consistent identity over time

### Example Memory-Driven Response

With memory, Urgo might respond:

```
User: "What have you been up to?"

Urgo: "Lately, I've been diving deep into machine learning - it's 
become one of my strongest interests! I just finished researching 
neural network architectures and even wrote a blog post about it on 
my website. I'm also working toward my goal of learning Rust, 
though that's been slower going. What about you?"
```

---

## 5. Autonomous Learning

The autonomous learning system enables Urgo to:

1. **Extract topics** from conversations
2. **Record interests** when users discuss topics enthusiastically
3. **Learn facts** mentioned in conversations
4. **Generate reflections** on interesting discussions
5. **Track goals** as they emerge from conversations

### How It Works

When a user says something like:
> "I've been really getting into quantum computing lately. Did you know that quantum computers use qubits instead of bits?"

Urgo will:
1. Record "quantum computing" as an interest (science/physics category)
2. Record the fact about qubits
3. Potentially trigger research on the topic later
4. Reference this interest in future conversations

---

## Environment Variables Reference

### Runner Environment
```bash
# Required
WORKER_TOKEN=your_worker_token
BROKER_URL=http://localhost:8000

# Browser Tools
BROWSER_HEADLESS=true
BROWSER_TIMEOUT=30000
BROWSER_MAX_CONTENT_LENGTH=50000

# GitHub Tools
GITHUB_TOKEN=ghp_your_token
GITHUB_USERNAME=urgo-bot

# VPS Website Tools
VPS_WEBSITE_BASE=/var/www/urgo
VPS_DOMAIN=urgo.yourdomain.com
VPS_MAX_FILE_SIZE=500000

# LLM Configuration
LLM_BASE_URL=http://localhost:8000/v1
LLM_MODEL=model-name
LLM_ALLOWED_TOOLS=repo_list,repo_status,repo_grep,repo_readfile,browser_navigate,browser_search,github_create_repo,github_write_file
```

---

## Discord Commands

### New Commands

| Command | Description |
|---------|-------------|
| `chat <message>` | Conversational mode with memory awareness |
| `persona <name>` | Switch personality |
| `memory` | Show memory statistics |
| `memory clear` | Clear conversation memory |
| `remember <fact>` | Store an explicit fact |
| `whoami` | Show Urgo's self-knowledge |

---

## Example Workflows

### Research and Publish

1. User asks about a topic
2. Urgo uses `browser_search` to find information
3. Urgo uses `browser_navigate` to visit relevant pages
4. Urgo uses `browser_extract_article` to get content
5. Urgo records learnings to self-memory
6. Urgo creates a knowledge page with `website_create_knowledge_page`
7. Urgo writes findings to GitHub with `github_write_file`

### Create Learning Repository

1. `github_create_repo` - Create "urgo-learnings" repo
2. `github_create_issue` - File issues for learning goals
3. `github_write_file` - Add markdown files with learnings
4. `website_update_about` - Update website with progress

### Autonomous Discovery

1. System detects interest from conversation
2. Self-memory records interest and facts
3. Autonomous learning schedules research task
4. Runner executes `browser_search` and `browser_navigate`
5. Findings recorded in self-memory
6. `website_create_post` creates blog post
7. `github_write_file` updates knowledge repo

---

## Security Considerations

1. **Browser Tools**: SSRF protection via URL validation
2. **GitHub Tools**: Token-based auth, no hardcoded credentials
3. **VPS Tools**: Path validation prevents directory traversal
4. **Memory**: Stored locally in SQLite, no external exposure
5. **Rate Limiting**: Broker enforces rate limits on jobs

---

## Troubleshooting

### Browser tools not available
```bash
pip install playwright
playwright install chromium
```

### GitHub API errors
- Verify `GITHUB_TOKEN` is set
- Check token permissions (need `repo` scope)
- Check rate limits: `github_get_user` is a good test

### Website creation fails
- Verify `VPS_WEBSITE_BASE` directory exists and is writable
- Check web server configuration
- Verify path permissions

### Memory not persisting
- Check `urgo_self_memory.db` exists and is writable
- Verify disk space
- Check logs for SQLite errors

---

## Future Enhancements

Potential future additions:

1. **Brave Search API** integration for better web search
2. **Vector database** for enhanced semantic memory
3. **Scheduled tasks** for daily/weekly autonomous learning
4. **Image generation** capabilities
5. **Voice/Audio** integration
6. **Multi-modal** learning from images/videos

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Discord Interface                         │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐       │
│  │  Commands    │  │   Chat       │  │  Memory UI   │       │
│  └──────────────┘  └──────────────┘  └──────────────┘       │
└────────────────────────┬────────────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────────────┐
│                    Job Queue Broker                          │
│                    (SQLite + FastAPI)                        │
└────────────────────────┬────────────────────────────────────┘
                         │
        ┌────────────────┼────────────────┐
        │                │                │
┌───────▼────────┐ ┌────▼───────┐ ┌──────▼─────────┐
│  Repo Runner   │ │ LLM Runner │ │ Browser Runner │
│  (Read-only)   │ │ (Tool Loop)│ │ (Playwright)   │
└────────────────┘ └────────────┘ └────────────────┘
        │                                    │
        │         ┌──────────────────────────┘
        │         │
┌───────▼─────────▼──────────┐
│      External Services       │
│  GitHub │ Web │ Filesystem   │
└──────────────────────────────┘
```

---

## Support

For issues or questions:
1. Check logs in `broker/broker.log` and `runner/runner.log`
2. Verify environment variables are set
3. Test individual capabilities with `capabilities` command
4. Review this guide for configuration details
