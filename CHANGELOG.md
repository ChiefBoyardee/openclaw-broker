# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased] - 2026-03-09

### Security Fixes (Critical)
* **memory.py**: Fixed SQL `#` comment syntax bug to `--` to restore semantic search functionality.
* **memory.py**: Added `PRAGMA journal_mode=WAL` to discord bot memory databases to prevent locking and corruption during concurrent access.
* **memory.py**: Fixed `_get_embedding` synchronization bug where async function wasn't awaited correctly.
* **self_memory.py**: Added WAL pragma to prevent DB corruption.
* **redaction.py**: Added `WORKER_TOKEN` to redaction patterns to prevent credential leaks.
* **vps_website_tools.py**: Added `html.escape()` on all user-controlled values in templates to prevent XSS.
* **github_tools.py**: Added `urllib.parse.quote_plus()` for query parameters to prevent parameter injection.

### Bug Fixes
* **browser_tools.py**: Rewrote `browser_click` reference logic to accurately match `_extract_interactive_elements` selectors.
* **github_tools.py**: Fixed double `e.read()` error that was consuming the error body resulting in lost error information.
* **chat_commands.py**: Implemented actual `handle_forget_command` logic, replacing the previous placeholder stub.

### Code Quality & Architecture
* **Python Packages**: Added `__init__.py` to `discord_bot/` and `runner/` directories to establish them as proper python modules.
* **Exception Handling**: Refined roughly ~50 instances of bare `except Exception` blocks, replacing them with specific exception types such as `sqlite3.Error`, `playwright.async_api.Error`, and `urllib.error.URLError`.
* **Structured Logging**: Replaced scattered `print()` statements across `broker/app.py`, `discord_bot/bot.py`, and `runner/runner.py` with the standard `logging` library configured to stdout.

### Testing additions
Added 19 new resilient tests, bringing the test matrix up to 130 fully passing tests.
* **VPS Website Tools**: 9 tests simulating website builds, directory manipulations, path traversal blocking, and XSS escaping.
* **GitHub Tools**: 4 tests validating issue listing, creating, formatting, URL encoding, and file editing.
* **Memory & Personality**: 10 tests validating conversation memory CRUD, prompt execution, Persona switching and WAL configuration.
* **Browser Automation**: Added integration tests using Playwright headless browsers testing local server interactions.
* **Chat Commands**: Developed an integration test suite validating `DiscordBot` LLM interactions and commands independently from active broker connections.
