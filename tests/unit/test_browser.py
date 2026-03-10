"""Unit tests for agents/browser.py -- browser MCP tools.

All Playwright objects are mocked. Tests verify return value shapes,
error handling, and session management logic.
"""

import json
import time
from unittest.mock import MagicMock, patch

# Import once -- do not re-import to avoid pydantic_core shared lib issues
import agents.browser as browser_mod


def _reset_sessions():
    """Clear module-level session state for clean tests."""
    browser_mod._sessions.clear()


# ---------------------------------------------------------------------------
# Step 3: Session management + browser_navigate
# ---------------------------------------------------------------------------


class TestBrowserSessionManagement:
    """Tests for _get_or_create_session and _cleanup_idle."""

    def test_get_or_create_session_creates_new_session(self):
        _reset_sessions()
        mock_pw_instance = MagicMock()
        mock_browser = MagicMock()
        mock_context = MagicMock()
        mock_page = MagicMock()

        mock_pw_instance.chromium.launch.return_value = mock_browser
        mock_browser.new_context.return_value = mock_context
        mock_context.new_page.return_value = mock_page

        with patch.object(browser_mod, "sync_playwright") as mock_sp:
            mock_sp.return_value.start.return_value = mock_pw_instance
            page = browser_mod._get_or_create_session("test_key")

        assert page is mock_page
        assert "test_key" in browser_mod._sessions
        session = browser_mod._sessions["test_key"]
        assert "pw" in session
        assert "browser" in session
        assert "context" in session
        assert "page" in session
        assert "last_used" in session

    def test_get_or_create_session_reuses_existing(self):
        _reset_sessions()
        mock_page = MagicMock()
        browser_mod._sessions["reuse_key"] = {
            "pw": MagicMock(),
            "browser": MagicMock(),
            "context": MagicMock(),
            "page": mock_page,
            "last_used": time.time() - 10,
        }
        old_last_used = browser_mod._sessions["reuse_key"]["last_used"]
        page = browser_mod._get_or_create_session("reuse_key")
        assert page is mock_page
        assert browser_mod._sessions["reuse_key"]["last_used"] > old_last_used

    def test_cleanup_idle_removes_expired_sessions(self):
        _reset_sessions()
        mock_session = {
            "pw": MagicMock(),
            "browser": MagicMock(),
            "context": MagicMock(),
            "page": MagicMock(),
            "last_used": time.time() - browser_mod._IDLE_TIMEOUT - 10,
        }
        browser_mod._sessions["expired"] = mock_session
        browser_mod._cleanup_idle()
        assert "expired" not in browser_mod._sessions
        mock_session["context"].close.assert_called_once()
        mock_session["browser"].close.assert_called_once()
        mock_session["pw"].stop.assert_called_once()

    def test_cleanup_idle_keeps_active_sessions(self):
        _reset_sessions()
        mock_session = {
            "pw": MagicMock(),
            "browser": MagicMock(),
            "context": MagicMock(),
            "page": MagicMock(),
            "last_used": time.time(),
        }
        browser_mod._sessions["active"] = mock_session
        browser_mod._cleanup_idle()
        assert "active" in browser_mod._sessions


def _make_mock_page(
    title: str = "Test Page",
    url: str = "https://example.com",
    body_text: str = "Normal page content",
    a11y_snapshot: dict | None = None,
):
    """Create a mock Page with standard attributes."""
    mock_page = MagicMock()
    mock_page.title.return_value = title
    mock_page.url = url
    mock_page.inner_text.return_value = body_text
    mock_page.accessibility.snapshot.return_value = a11y_snapshot or {
        "role": "document",
        "name": "Test",
    }
    mock_page.screenshot.return_value = b"\x89PNG\r\n\x1a\nfakedata"
    mock_page.eval_on_selector_all.return_value = [
        {"title": "Result 1", "url": "https://r1.com", "snippet": "Snippet 1"},
        {"title": "Result 2", "url": "https://r2.com", "snippet": "Snippet 2"},
        {"title": "Result 3", "url": "https://r3.com", "snippet": "Snippet 3"},
    ]
    return mock_page


def _install_session(session_key: str = "default", **page_kwargs):
    """Install a mock session and return the mock page."""
    mock_page = _make_mock_page(**page_kwargs)
    browser_mod._sessions[session_key] = {
        "pw": MagicMock(),
        "browser": MagicMock(),
        "context": MagicMock(),
        "page": mock_page,
        "last_used": time.time(),
    }
    return mock_page


class TestBrowserNavigate:
    """Tests for browser_navigate tool."""

    def test_navigate_returns_json_with_title_url_tree(self):
        _reset_sessions()
        _install_session()

        result = browser_mod.browser_navigate("https://example.com")
        data = json.loads(result)
        assert "title" in data
        assert "url" in data
        assert "accessibility_tree" in data
        assert data["title"] == "Test Page"
        assert data["url"] == "https://example.com"

    def test_navigate_truncates_large_accessibility_tree(self):
        _reset_sessions()
        mock_page = _install_session()
        large_tree = {"role": "document", "name": "x" * 10000}
        mock_page.accessibility.snapshot.return_value = large_tree

        result = browser_mod.browser_navigate("https://example.com")
        data = json.loads(result)
        tree_str = data["accessibility_tree"]
        assert len(tree_str) <= 8100  # 8000 + suffix
        assert "... [truncated]" in tree_str

    def test_navigate_handles_timeout_error(self):
        _reset_sessions()
        mock_page = _install_session()
        mock_page.goto.side_effect = TimeoutError("Navigation timeout")

        result = browser_mod.browser_navigate("https://slow-site.com")
        data = json.loads(result)
        assert "error" in data

    def test_navigate_includes_captcha_warning_in_response(self):
        _reset_sessions()
        _install_session(
            title="Robot verification",
            body_text="Please verify you are human",
        )

        result = browser_mod.browser_navigate("https://example.com")
        data = json.loads(result)
        assert data.get("captcha_detected") is True
        assert "warning" in data


# ---------------------------------------------------------------------------
# Step 4: browser_click and browser_type
# ---------------------------------------------------------------------------


class TestBrowserClick:
    """Tests for browser_click tool."""

    def test_click_returns_json_with_title_url(self):
        _reset_sessions()
        _install_session(title="Clicked Page", url="https://example.com/clicked")

        result = browser_mod.browser_click("button.submit")
        data = json.loads(result)
        assert data["title"] == "Clicked Page"
        assert data["url"] == "https://example.com/clicked"

    def test_click_timeout_returns_error(self):
        _reset_sessions()
        mock_page = _install_session()
        mock_page.click.side_effect = TimeoutError("Click timeout")

        result = browser_mod.browser_click("button.missing")
        data = json.loads(result)
        assert "error" in data


class TestBrowserType:
    """Tests for browser_type tool."""

    def test_type_fills_input_and_returns_json(self):
        _reset_sessions()
        mock_page = _install_session(
            title="Typed Page", url="https://example.com/typed"
        )

        result = browser_mod.browser_type("#search", "test query")
        data = json.loads(result)
        mock_page.fill.assert_called_once_with("#search", "test query", timeout=10000)
        assert data["title"] == "Typed Page"
        assert data["url"] == "https://example.com/typed"

    def test_type_with_press_enter_presses_enter(self):
        _reset_sessions()
        mock_page = _install_session()

        browser_mod.browser_type("#search", "test query", press_enter=True)
        mock_page.press.assert_called_once_with("#search", "Enter")

    def test_type_without_press_enter_skips_enter(self):
        _reset_sessions()
        mock_page = _install_session()

        browser_mod.browser_type("#search", "test query", press_enter=False)
        mock_page.press.assert_not_called()

    def test_type_timeout_returns_error(self):
        _reset_sessions()
        mock_page = _install_session()
        mock_page.fill.side_effect = TimeoutError("Fill timeout")

        result = browser_mod.browser_type("#missing", "text")
        data = json.loads(result)
        assert "error" in data


# ---------------------------------------------------------------------------
# Step 5: browser_content and browser_screenshot
# ---------------------------------------------------------------------------


class TestBrowserContent:
    """Tests for browser_content tool."""

    def test_content_accessibility_mode_returns_tree(self):
        _reset_sessions()
        _install_session()

        result = browser_mod.browser_content(mode="accessibility")
        data = json.loads(result)
        assert "content" in data
        assert "document" in data["content"]

    def test_content_text_mode_returns_inner_text(self):
        _reset_sessions()
        mock_page = _install_session(body_text="Page body text")

        result = browser_mod.browser_content(mode="text")
        data = json.loads(result)
        mock_page.inner_text.assert_called_with("body")
        assert "Page body text" in data["content"]

    def test_content_truncates_at_12000_chars(self):
        _reset_sessions()
        _install_session(body_text="x" * 15000)

        result = browser_mod.browser_content(mode="text")
        data = json.loads(result)
        assert len(data["content"]) <= 12100  # 12000 + suffix
        assert "... [truncated]" in data["content"]

    def test_content_invalid_mode_defaults_to_accessibility(self):
        _reset_sessions()
        mock_page = _install_session()

        result = browser_mod.browser_content(mode="invalid_mode")
        data = json.loads(result)
        assert "content" in data
        mock_page.accessibility.snapshot.assert_called()

    def test_content_includes_captcha_warning(self):
        _reset_sessions()
        _install_session(
            title="Robot verification",
            body_text="Please verify you are human",
        )
        result = browser_mod.browser_content(mode="text")
        data = json.loads(result)
        assert data.get("captcha_detected") is True
        assert "warning" in data


class TestBrowserScreenshot:
    """Tests for browser_screenshot tool."""

    def test_screenshot_returns_base64_png(self):
        _reset_sessions()
        _install_session()

        result = browser_mod.browser_screenshot()
        data = json.loads(result)
        assert "screenshot_base64" in data
        assert "media_type" in data
        assert data["media_type"] == "image/png"
        assert len(data["screenshot_base64"]) > 0

    def test_screenshot_error_returns_json_error(self):
        _reset_sessions()
        mock_page = _install_session()
        mock_page.screenshot.side_effect = Exception("Screenshot failed")

        result = browser_mod.browser_screenshot()
        data = json.loads(result)
        assert "error" in data


# ---------------------------------------------------------------------------
# Step 6: browser_close and web_search
# ---------------------------------------------------------------------------


class TestBrowserClose:
    """Tests for browser_close tool."""

    def test_close_specific_session_removes_it(self):
        _reset_sessions()
        mock_session = {
            "pw": MagicMock(),
            "browser": MagicMock(),
            "context": MagicMock(),
            "page": MagicMock(),
            "last_used": time.time(),
        }
        browser_mod._sessions["my_session"] = mock_session

        result = browser_mod.browser_close(session_key="my_session")
        assert "my_session" not in browser_mod._sessions
        mock_session["context"].close.assert_called_once()
        mock_session["browser"].close.assert_called_once()
        mock_session["pw"].stop.assert_called_once()
        assert "closed" in result.lower() or "my_session" in result

    def test_close_all_clears_all_sessions(self):
        _reset_sessions()
        for key in ["s1", "s2", "s3"]:
            browser_mod._sessions[key] = {
                "pw": MagicMock(),
                "browser": MagicMock(),
                "context": MagicMock(),
                "page": MagicMock(),
                "last_used": time.time(),
            }

        result = browser_mod.browser_close(session_key="all")
        assert len(browser_mod._sessions) == 0
        assert "all" in result.lower() or "All" in result

    def test_close_nonexistent_session_returns_message(self):
        _reset_sessions()
        result = browser_mod.browser_close(session_key="nonexistent")
        assert "no session" in result.lower() or "No session" in result


class TestWebSearch:
    """Tests for web_search tool."""

    def test_search_duckduckgo_returns_structured_results(self):
        _reset_sessions()
        _install_session(session_key="_web_search")

        result = browser_mod.web_search("test query")
        data = json.loads(result)
        assert "query" in data
        assert "engine" in data
        assert "count" in data
        assert "results" in data
        assert data["query"] == "test query"
        assert data["engine"] == "duckduckgo"

    def test_search_google_uses_google_url(self):
        _reset_sessions()
        mock_page = _install_session(session_key="_web_search")

        browser_mod.web_search("test query", engine="google")
        call_args = mock_page.goto.call_args
        assert "google.com" in call_args[0][0]

    def test_search_respects_max_results(self):
        _reset_sessions()
        _install_session(session_key="_web_search")

        result = browser_mod.web_search("test query", max_results=2)
        data = json.loads(result)
        assert data["count"] == 2
        assert len(data["results"]) == 2

    def test_search_uses_dedicated_session_key(self):
        _reset_sessions()
        # Set up a separate "default" session
        _install_session(session_key="default")
        _install_session(session_key="_web_search")

        browser_mod.web_search("test query")
        assert "default" in browser_mod._sessions
        assert "_web_search" in browser_mod._sessions

    def test_search_url_encodes_query(self):
        _reset_sessions()
        mock_page = _install_session(session_key="_web_search")
        browser_mod.web_search("Honda mower & parts")
        call_args = mock_page.goto.call_args
        url = call_args[0][0]
        # The query should be URL-encoded: & becomes %26, spaces become +
        assert "Honda+mower+%26+parts" in url

    def test_search_url_encodes_query_google(self):
        _reset_sessions()
        mock_page = _install_session(session_key="_web_search")
        browser_mod.web_search("price = $100", engine="google")
        call_args = mock_page.goto.call_args
        url = call_args[0][0]
        # The query should be URL-encoded: = becomes %3D, $ becomes %24
        assert "price" in url
        assert "=" not in url.split("?q=", 1)[1]

    def test_search_error_returns_json_error(self):
        _reset_sessions()
        mock_page = _install_session(session_key="_web_search")
        mock_page.goto.side_effect = Exception("Network error")

        result = browser_mod.web_search("test query")
        data = json.loads(result)
        assert "error" in data


# ---------------------------------------------------------------------------
# Step 7: CAPTCHA detection
# ---------------------------------------------------------------------------


class TestCaptchaDetection:
    """Tests for _detect_captcha helper."""

    def test_detects_recaptcha_in_page_content(self):
        mock_page = _make_mock_page(body_text="Please complete the reCAPTCHA")
        assert browser_mod._detect_captcha(mock_page) is True

    def test_detects_hcaptcha_in_page_content(self):
        mock_page = _make_mock_page(body_text="hCaptcha challenge")
        assert browser_mod._detect_captcha(mock_page) is True

    def test_no_captcha_returns_false(self):
        mock_page = _make_mock_page(body_text="Welcome to our store")
        assert browser_mod._detect_captcha(mock_page) is False

    def test_navigate_includes_captcha_warning_in_response(self):
        _reset_sessions()
        _install_session(
            title="Robot verification",
            body_text="Please verify you are human",
        )

        result = browser_mod.browser_navigate("https://example.com")
        data = json.loads(result)
        assert data.get("captcha_detected") is True
        assert "warning" in data
