"""Browser automation MCP tools via Playwright.

Provides headless browser capabilities for navigating JavaScript-rendered
pages, filling forms, clicking elements, extracting content, and performing
web searches. Sessions persist across tool calls and auto-close after idle.

Session management uses a module-level dict with thread-safe locking,
following the lazy-singleton pattern from agents/memory.py.
"""

import base64
import json
import logging
import threading
import time
from urllib.parse import quote_plus

from agent_tooling import tool

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None  # type: ignore[assignment,misc]

logger = logging.getLogger(__name__)

# --- Session management ---
_sessions: dict[str, dict] = {}
_lock = threading.Lock()
_IDLE_TIMEOUT = 300  # 5 minutes


def _get_or_create_session(session_key: str = "default"):
    """Get existing browser page or create a new one.

    Args:
        session_key: Identifier for the browser session.

    Returns:
        The Playwright Page object for the given session.
    """
    with _lock:
        if session_key in _sessions:
            _sessions[session_key]["last_used"] = time.time()
            return _sessions[session_key]["page"]
        pw = sync_playwright().start()
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 720},
        )
        page = context.new_page()
        _sessions[session_key] = {
            "pw": pw,
            "browser": browser,
            "context": context,
            "page": page,
            "last_used": time.time(),
        }
        return page


def _cleanup_idle() -> None:
    """Close sessions idle longer than _IDLE_TIMEOUT."""
    now = time.time()
    with _lock:
        expired = [
            k for k, v in _sessions.items() if now - v["last_used"] > _IDLE_TIMEOUT
        ]
        for k in expired:
            s = _sessions.pop(k)
            try:
                s["context"].close()
                s["browser"].close()
                s["pw"].stop()
            except Exception:
                logger.warning("Error cleaning up session '%s'", k)


def _detect_captcha(page) -> bool:
    """Check if the current page has CAPTCHA or bot detection.

    Inspects page title and body text for common CAPTCHA indicators.

    Args:
        page: Playwright Page object.

    Returns:
        True if CAPTCHA-like content is detected.
    """
    indicators = [
        "captcha",
        "recaptcha",
        "hcaptcha",
        "robot",
        "bot detection",
        "verify you are human",
    ]
    try:
        title = (page.title() or "").lower()
        body_text = (page.inner_text("body") or "").lower()
        combined = title + " " + body_text
        return any(indicator in combined for indicator in indicators)
    except Exception:
        return False


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
    try:
        _cleanup_idle()
        page = _get_or_create_session(session_key)
        page.goto(url, wait_until="networkidle", timeout=30000)
        tree = page.accessibility.snapshot()
        tree_str = json.dumps(tree, indent=2)
        if len(tree_str) > 8000:
            tree_str = tree_str[:8000] + "\n... [truncated]"

        result: dict = {
            "title": page.title(),
            "url": page.url,
            "accessibility_tree": tree_str,
        }

        if _detect_captcha(page):
            result["captcha_detected"] = True
            result["warning"] = (
                "CAPTCHA or bot detection detected. "
                "The site may require human verification."
            )

        return json.dumps(result)
    except Exception as e:
        logger.exception("browser_navigate failed")
        return json.dumps({"error": str(e)})


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
    try:
        page = _get_or_create_session(session_key)
        page.click(selector, timeout=10000)
        page.wait_for_load_state("networkidle", timeout=15000)
        return json.dumps({
            "title": page.title(),
            "url": page.url,
        })
    except Exception as e:
        logger.exception("browser_click failed")
        return json.dumps({"error": str(e)})


@tool(tags=["web", "browser"])
def browser_type(
    selector: str,
    text: str,
    press_enter: bool = False,
    session_key: str = "default",
) -> str:
    """Type text into an input field.

    Args:
        selector: CSS selector for the input element.
        text: Text to type.
        press_enter: Press Enter after typing (default: False).
        session_key: Browser session identifier.

    Returns:
        JSON confirmation with page title and URL.
    """
    try:
        page = _get_or_create_session(session_key)
        page.fill(selector, text, timeout=10000)
        if press_enter:
            page.press(selector, "Enter")
            page.wait_for_load_state("networkidle", timeout=15000)
        return json.dumps({
            "title": page.title(),
            "url": page.url,
        })
    except Exception as e:
        logger.exception("browser_type failed")
        return json.dumps({"error": str(e)})


@tool(tags=["web", "browser"])
def browser_content(
    session_key: str = "default",
    mode: str = "accessibility",
) -> str:
    """Get current page content.

    Args:
        session_key: Browser session identifier.
        mode: "accessibility" (default, structured tree) or "text" (inner text).

    Returns:
        JSON with page content (truncated to 12000 chars).
    """
    try:
        page = _get_or_create_session(session_key)
        if mode == "text":
            content = page.inner_text("body")
        else:
            tree = page.accessibility.snapshot()
            content = json.dumps(tree, indent=2)
        if len(content) > 12000:
            content = content[:12000] + "\n... [truncated]"

        result: dict = {
            "title": page.title(),
            "url": page.url,
            "content": content,
        }

        if _detect_captcha(page):
            result["captcha_detected"] = True
            result["warning"] = (
                "CAPTCHA or bot detection detected. "
                "The site may require human verification."
            )

        return json.dumps(result)
    except Exception as e:
        logger.exception("browser_content failed")
        return json.dumps({"error": str(e)})


@tool(tags=["web", "browser"])
def browser_screenshot(session_key: str = "default") -> str:
    """Take a screenshot of the current page (base64 PNG).

    Args:
        session_key: Browser session identifier.

    Returns:
        JSON with base64-encoded PNG screenshot.
    """
    try:
        page = _get_or_create_session(session_key)
        png_bytes = page.screenshot(full_page=False)
        return json.dumps({
            "title": page.title(),
            "url": page.url,
            "screenshot_base64": base64.b64encode(png_bytes).decode(),
            "media_type": "image/png",
        })
    except Exception as e:
        logger.exception("browser_screenshot failed")
        return json.dumps({"error": str(e)})


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
                try:
                    s["context"].close()
                    s["browser"].close()
                    s["pw"].stop()
                except Exception:
                    logger.warning("Error closing session during 'all' cleanup")
            _sessions.clear()
            return "All browser sessions closed."
        if session_key not in _sessions:
            return f"No session '{session_key}' found."
        s = _sessions.pop(session_key)
        try:
            s["context"].close()
            s["browser"].close()
            s["pw"].stop()
        except Exception:
            logger.warning("Error closing session '%s'", session_key)
        return f"Session '{session_key}' closed."


@tool(tags=["web", "browser"])
def web_search(
    query: str,
    engine: str = "duckduckgo",
    max_results: int = 10,
) -> str:
    """Search the web and return structured results.

    Uses a real browser to perform the search, bypassing API restrictions.
    DuckDuckGo is default (no bot detection). Google available but may
    trigger CAPTCHAs.

    Args:
        query: Search query string.
        engine: "duckduckgo" (default) or "google".
        max_results: Maximum results to return (default: 10).

    Returns:
        JSON with query, engine, count, and results array (title, url, snippet).
    """
    try:
        page = _get_or_create_session("_web_search")

        if engine == "google":
            page.goto(
                f"https://www.google.com/search?q={quote_plus(query)}",
                timeout=30000,
            )
            page.wait_for_load_state("networkidle")
            results = page.eval_on_selector_all(
                "div.g",
                """els => els.map(el => ({
                    title: el.querySelector('h3')?.textContent || '',
                    url: el.querySelector('a')?.href || '',
                    snippet: el.querySelector('.VwiC3b')?.textContent || ''
                })).filter(r => r.title && r.url)""",
            )
        else:
            page.goto(
                f"https://duckduckgo.com/?q={quote_plus(query)}",
                timeout=30000,
            )
            page.wait_for_load_state("networkidle")
            page.wait_for_selector("[data-result]", timeout=10000)
            results = page.eval_on_selector_all(
                "[data-result]",
                """els => els.map(el => ({
                    title: el.querySelector('h2 a')?.textContent || '',
                    url: el.querySelector('h2 a')?.href || '',
                    snippet: el.querySelector('.result__snippet')?.textContent || ''
                })).filter(r => r.title && r.url)""",
            )

        return json.dumps({
            "query": query,
            "engine": engine,
            "count": min(len(results), max_results),
            "results": results[:max_results],
        })
    except Exception as e:
        logger.exception("web_search failed")
        return json.dumps({"error": str(e)})
