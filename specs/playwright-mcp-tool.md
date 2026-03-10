# Playwright MCP Tool — Technical Workup

## Overview

A local MCP tool (`agents/browser.py`) that gives Ada headless browser capabilities via Playwright. Unlike WebFetch (static HTML only), this handles JavaScript-rendered pages, form interaction, login sessions, and dynamic content extraction.

Primary use case: **web search and site interaction** — checking store inventory by zip code, reading JS-heavy pages, extracting structured data from rendered DOM.

## User Requirements

Daniel asks Ada to browse a website (e.g. Home Depot, Lowe's) and look for a specific product, ensuring the store location matches his zip code. The expected behavior:

1. **Navigate and search** — Go to the website, find the search box, enter the product query
2. **Set location** — Find where to enter a zip code or store location, set it to Daniel's zip code
3. **Handle ambiguity** — If the site presents choices (e.g. "There are 2 stores near 77459 — which one?"), ask Daniel rather than guessing
4. **Extract results** — Return product availability, pricing, and any relevant details
5. **Ask, don't assume** — Any point where the next step is unclear (multiple options, unexpected page state, CAPTCHA), stop and ask Daniel for direction

The tool must be conversational — Ada should narrate what she's doing ("I'm on the Home Depot homepage, searching for Honda mowers...") and surface decisions rather than making them silently.

## User Acceptance Criteria

- [ ] Ada can navigate to a retail website (e.g. Home Depot) and search for a product by name
- [ ] Ada can find and set the store location to a given zip code
- [ ] When multiple stores match a zip code, Ada asks Daniel which one rather than guessing
- [ ] Ada extracts and reports product availability, pricing, and relevant details
- [ ] When a page hits a CAPTCHA or bot detection, Ada stops and tells Daniel
- [ ] When any step is ambiguous or has multiple options, Ada asks for direction
- [ ] Ada narrates what she's doing conversationally as she browses
- [ ] `web_search` returns structured results via DuckDuckGo without requiring API keys
- [ ] Browser sessions auto-close after 5 minutes idle
- [ ] Container builds and runs with headless Chromium

> **Future:** Full vision-based browser interaction (including CAPTCHA handling) deferred to Claude computer use integration.

## Code References

| File | Action |
|------|--------|
| `agents/browser.py` | **Create** — all Playwright MCP tool functions |
| `.claude/skills/browse/SKILL.md` | **Create** — `/browse` skill |
| `specs/skills/browse/SKILL.md` | **Create** — version-controlled copy |
| `requirements.txt` | **Modify** — add `playwright>=1.40.0` |
| `Dockerfile` | **Modify** — add Playwright system deps + Chromium install |

## Architecture

```
User: "check Home Depot for Honda mowers in 77459"
  │
  ▼
Claude (skill: /browse)
  │  reads skill → decides multi-step plan
  │
  ├─ browser_navigate("https://homedepot.com")
  ├─ browser_type("#search-input", "Honda mower")
  ├─ browser_click("button.search-submit")
  ├─ browser_type("#zip-code", "77459")
  ├─ browser_click("button.update-store")
  ├─ browser_content()  ← returns accessibility tree
  │
  ▼
Claude interprets results, responds to user
```

## Component 1: MCP Tool — `agents/browser.py`

### Design Decisions

**Session-based, not stateless.** Browser state (current page, cookies, login) must persist across tool calls within a conversation. A global `_browser_sessions` dict maps session keys to Playwright contexts. Contexts auto-close after idle timeout.

**Accessibility tree over screenshots.** The accessibility tree is 2-5KB of structured text vs. a full screenshot image. Cheaper, faster, and works with text-only Claude. Screenshots available as fallback for debugging or visual-only content.

**Headless Chromium only.** No display server needed. Playwright manages the browser lifecycle.

### Tool Functions

```python
from agent_tooling import tool
from playwright.sync_api import sync_playwright, Browser, Page
import json
import time
import threading

# --- Session management ---
_sessions: dict[str, dict] = {}   # key → {page, context, browser, last_used}
_lock = threading.Lock()
_IDLE_TIMEOUT = 300  # 5 min

def _get_or_create_session(session_key: str = "default") -> Page:
    """Get existing browser page or create a new one."""
    with _lock:
        if session_key in _sessions:
            _sessions[session_key]["last_used"] = time.time()
            return _sessions[session_key]["page"]
        pw = sync_playwright().start()
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 720},
        )
        page = context.new_page()
        _sessions[session_key] = {
            "pw": pw, "browser": browser, "context": context,
            "page": page, "last_used": time.time(),
        }
        return page

def _cleanup_idle():
    """Called periodically — close sessions idle > _IDLE_TIMEOUT."""
    now = time.time()
    with _lock:
        expired = [k for k, v in _sessions.items()
                   if now - v["last_used"] > _IDLE_TIMEOUT]
        for k in expired:
            s = _sessions.pop(k)
            s["context"].close()
            s["browser"].close()
            s["pw"].stop()


# --- MCP Tools ---

@tool(tags=["web", "browser"])
def browser_navigate(url: str, session_key: str = "default") -> str:
    """Navigate to a URL and return the page title + accessibility snapshot.

    Args:
        url: Full URL to navigate to.
        session_key: Browser session identifier (default: "default").

    Returns:
        JSON with title, url, and accessibility tree (truncated to 8000 chars).
    """
    page = _get_or_create_session(session_key)
    page.goto(url, wait_until="networkidle", timeout=30000)
    tree = page.accessibility.snapshot()
    tree_str = json.dumps(tree, indent=2)
    if len(tree_str) > 8000:
        tree_str = tree_str[:8000] + "\n... [truncated]"
    return json.dumps({
        "title": page.title(),
        "url": page.url,
        "accessibility_tree": tree_str,
    })


@tool(tags=["web", "browser"])
def browser_click(selector: str, session_key: str = "default") -> str:
    """Click an element on the current page.

    Args:
        selector: CSS selector, text selector ('text=Sign In'), or role
                  selector ('role=button[name="Submit"]').
        session_key: Browser session identifier.

    Returns:
        JSON with new page title and URL after click.
    """
    page = _get_or_create_session(session_key)
    page.click(selector, timeout=10000)
    page.wait_for_load_state("networkidle", timeout=15000)
    return json.dumps({
        "title": page.title(),
        "url": page.url,
    })


@tool(tags=["web", "browser"])
def browser_type(selector: str, text: str,
                 press_enter: bool = False,
                 session_key: str = "default") -> str:
    """Type text into an input field.

    Args:
        selector: CSS selector for the input element.
        text: Text to type.
        press_enter: Press Enter after typing (default: False).
        session_key: Browser session identifier.

    Returns:
        JSON confirmation with page title and URL.
    """
    page = _get_or_create_session(session_key)
    page.fill(selector, text, timeout=10000)
    if press_enter:
        page.press(selector, "Enter")
        page.wait_for_load_state("networkidle", timeout=15000)
    return json.dumps({
        "title": page.title(),
        "url": page.url,
    })


@tool(tags=["web", "browser"])
def browser_content(session_key: str = "default",
                    mode: str = "accessibility") -> str:
    """Get current page content.

    Args:
        session_key: Browser session identifier.
        mode: "accessibility" (default, structured tree) or "text" (inner text).

    Returns:
        JSON with page content (truncated to 12000 chars).
    """
    page = _get_or_create_session(session_key)
    if mode == "text":
        content = page.inner_text("body")
    else:
        tree = page.accessibility.snapshot()
        content = json.dumps(tree, indent=2)
    if len(content) > 12000:
        content = content[:12000] + "\n... [truncated]"
    return json.dumps({
        "title": page.title(),
        "url": page.url,
        "content": content,
    })


@tool(tags=["web", "browser"])
def browser_screenshot(session_key: str = "default") -> str:
    """Take a screenshot of the current page (base64 PNG).

    Args:
        session_key: Browser session identifier.

    Returns:
        JSON with base64-encoded PNG screenshot.
    """
    import base64
    page = _get_or_create_session(session_key)
    png_bytes = page.screenshot(full_page=False)
    return json.dumps({
        "title": page.title(),
        "url": page.url,
        "screenshot_base64": base64.b64encode(png_bytes).decode(),
        "media_type": "image/png",
    })


@tool(tags=["web", "browser"])
def browser_close(session_key: str = "default") -> str:
    """Close a browser session and free resources.

    Args:
        session_key: Session to close. Use "all" to close everything.

    Returns:
        Confirmation message.
    """
    with _lock:
        if session_key == "all":
            for s in _sessions.values():
                s["context"].close()
                s["browser"].close()
                s["pw"].stop()
            _sessions.clear()
            return "All browser sessions closed."
        s = _sessions.pop(session_key, None)
        if s:
            s["context"].close()
            s["browser"].close()
            s["pw"].stop()
            return f"Session '{session_key}' closed."
        return f"No session '{session_key}' found."


@tool(tags=["web", "browser"])
def web_search(query: str, engine: str = "duckduckgo",
               max_results: int = 10) -> str:
    """Search the web and return structured results.

    Uses a real browser to perform the search, bypassing API restrictions.
    DuckDuckGo is default (no bot detection). Google available but may
    trigger CAPTCHAs.

    Args:
        query: Search query string.
        engine: "duckduckgo" (default) or "google".
        max_results: Maximum results to return (default: 10).

    Returns:
        JSON array of search results with title, url, snippet.
    """
    page = _get_or_create_session("_web_search")

    if engine == "google":
        page.goto(f"https://www.google.com/search?q={query}", timeout=30000)
        page.wait_for_load_state("networkidle")
        results = page.eval_on_selector_all(
            "div.g",
            """els => els.map(el => ({
                title: el.querySelector('h3')?.textContent || '',
                url: el.querySelector('a')?.href || '',
                snippet: el.querySelector('.VwiC3b')?.textContent || ''
            })).filter(r => r.title && r.url)"""
        )
    else:
        page.goto(f"https://duckduckgo.com/?q={query}", timeout=30000)
        page.wait_for_load_state("networkidle")
        # Wait for results to render (JS-heavy)
        page.wait_for_selector("[data-result]", timeout=10000)
        results = page.eval_on_selector_all(
            "[data-result]",
            """els => els.map(el => ({
                title: el.querySelector('h2 a')?.textContent || '',
                url: el.querySelector('h2 a')?.href || '',
                snippet: el.querySelector('.result__snippet')?.textContent || ''
            })).filter(r => r.title && r.url)"""
        )

    return json.dumps({
        "query": query,
        "engine": engine,
        "count": min(len(results), max_results),
        "results": results[:max_results],
    })
```

### Why These Six Tools

| Tool | Purpose |
|------|---------|
| `browser_navigate` | Go to a URL, get accessibility tree |
| `browser_click` | Interact with buttons, links, tabs |
| `browser_type` | Fill forms, search boxes, zip codes |
| `browser_content` | Re-read page after interactions |
| `browser_screenshot` | Visual debugging fallback |
| `browser_close` | Clean up resources |
| `web_search` | High-level search via real browser |

The accessibility tree is the key differentiator from WebFetch. It contains roles, names, and values — Claude can reason about interactive elements ("there's a button named 'Update Store', I should click it") without needing vision.

## Component 2: Skill — `/browse`

**File**: `.claude/skills/browse/SKILL.md`

```markdown
---
name: browse
description: "Browse the web interactively. Navigate pages, fill forms, click
  buttons, and extract content from JavaScript-rendered sites. Use when WebFetch
  fails or the task requires interaction (store lookups, form submissions, etc)."
argument-hint: "[url-or-task-description]"
tools: Read, Write, Bash
model: sonnet
user-invocable: true
---

# Browse

## When to Use
- Page requires JavaScript to render (SPAs, React, dynamic content)
- Task requires interaction (typing a zip code, clicking filters, submitting forms)
- WebFetch returns empty or useless HTML
- Need to navigate through multiple pages (search → click result → extract)

## When NOT to Use
- Static page with content in the HTML → use WebFetch instead (faster, cheaper)
- API exists for the data → use the API directly
- Searching for general knowledge → use WebSearch (built-in) first

## Procedure

1. **Assess the task.** Decide whether it's a simple page read or multi-step
   interaction. If multi-step, plan the sequence before starting.

2. **Navigate.** Call `browser_navigate(url)`. Read the accessibility tree
   to understand the page structure. Look for:
   - Input fields (role: textbox, searchbox)
   - Buttons (role: button, link)
   - Navigation elements (tabs, menus)
   - Content areas (headings, text, lists)

3. **Interact.** Use `browser_type` for input fields, `browser_click` for
   buttons and links. After each interaction, check the result with
   `browser_content()`.

4. **Extract.** Once on the target page, use `browser_content(mode="text")`
   to get plain text, or `browser_content(mode="accessibility")` for
   structured data. Parse what you need.

5. **Clean up.** Call `browser_close()` when done, especially if the task
   is complete. Sessions auto-close after 5 minutes idle, but explicit
   cleanup is preferred.

## Selector Strategy

Prefer selectors in this order:
1. `role=button[name="Submit"]` — most stable, accessibility-based
2. `text=Sign In` — readable, works for visible text
3. `#element-id` — fast, but IDs change across deploys
4. `.class-name` — fragile, use as last resort

## Error Handling

- **Timeout**: Page didn't load → try with `wait_until="domcontentloaded"`
  instead of `networkidle`
- **Selector not found**: Re-read the accessibility tree to find the correct
  element name or role
- **CAPTCHA**: Stop. Tell Daniel the site requires human verification. Do not
  attempt to solve CAPTCHAs.
- **Bot detection**: Try DuckDuckGo instead of Google. For persistent blocks,
  tell Daniel the site is not automatable.

## Web Search via Browser

For searches that need real browser rendering:
```
web_search("Honda mower HRN216", engine="duckduckgo")
```
Returns structured JSON with title, url, snippet. Use `browser_navigate`
on interesting results to read the full page.
```

## Component 3: Container Changes

### Dockerfile Additions

```dockerfile
# After existing apt-get install block:
# Playwright system dependencies (Chromium)
RUN npx playwright install-deps chromium

# After pip install requirements.txt:
RUN /opt/venv/bin/pip install playwright \
    && /opt/venv/bin/python -m playwright install chromium
```

**Size impact**: ~400MB for Chromium binary + ~50MB for Playwright Python package. Total container size increase ~450MB.

### requirements.txt Addition

```
playwright>=1.40.0
```

### No Other Changes Required

- **No new containers** — runs inside `hive_mind`
- **No new MCP servers** — standard `agents/` auto-discovery
- **No new secrets** — no API keys needed
- **No docker-compose changes** — no new services or volumes

## Isolation Considerations

Playwright tools will be auto-discovered and run in the MCP server process (not subprocess-isolated like `create_tool` output). This is acceptable because:

1. The tool is first-party code, not user-generated
2. Browser runs headless in the same container — no host access
3. No credentials passed to browser (login sessions handled through Playwright context, not env vars)
4. The 5-minute idle timeout prevents resource leaks

If stricter isolation is desired later, the tools can be moved to subprocess isolation by adding an `allowed_env` list and using `make_isolated_wrapper`.

## Implementation Order

1. **Add `playwright` to requirements.txt**
2. **Add Playwright install to Dockerfile** (system deps + browser binary)
3. **Write `agents/browser.py`** — start with `browser_navigate` + `browser_content` + `web_search`
4. **Rebuild container** — verify Chromium launches headless
5. **Write `.claude/skills/browse/SKILL.md`**
6. **Smoke test**: `web_search("weather austin tx")` → should return structured results
7. **Integration test**: Navigate to a real site, type in a form, extract results

## Estimated Container Build Time Impact

- First build: +3-5 minutes (download Chromium + system deps)
- Subsequent builds: cached (Chromium layer doesn't change)
- Runtime overhead: Chromium process starts on first `browser_navigate`, ~2-3 seconds cold start

## Risks and Mitigations

| Risk | Mitigation |
|------|-----------|
| Container size bloat (+450MB) | Chromium is the only browser installed; could slim further with `--with-deps` flag |
| Bot detection on some sites | DuckDuckGo as default engine; realistic user-agent string |
| Resource leaks (zombie browsers) | 5-min idle timeout + explicit `browser_close` |
| CAPTCHAs | Skill instructs Claude to stop and tell Daniel |
| Slow cold start | First call takes 2-3s; subsequent calls reuse session |
| Memory pressure | One Chromium instance per session key; typically 1-2 active |
