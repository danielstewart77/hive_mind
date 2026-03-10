"""Integration tests for browser tool workflows.

All Playwright interactions are mocked. Tests verify cross-tool session
state management and JSON contract consistency.
"""

import json
import sys
import time
import types
from unittest.mock import MagicMock

import agents.browser as browser_mod
import pytest


@pytest.fixture(autouse=True)
def _mock_playwright(monkeypatch):
    """Mock Playwright for integration tests."""
    playwright_mock = MagicMock(spec=types.ModuleType)
    playwright_mock.__name__ = "playwright"

    playwright_sync_mock = MagicMock(spec=types.ModuleType)
    playwright_sync_mock.__name__ = "playwright.sync_api"
    playwright_sync_mock.sync_playwright = MagicMock()
    playwright_sync_mock.Browser = MagicMock()
    playwright_sync_mock.BrowserContext = MagicMock()
    playwright_sync_mock.Page = MagicMock()
    playwright_sync_mock.Playwright = MagicMock()
    playwright_sync_mock.TimeoutError = TimeoutError

    monkeypatch.setitem(sys.modules, "playwright", playwright_mock)
    monkeypatch.setitem(sys.modules, "playwright.sync_api", playwright_sync_mock)


def _reset_sessions():
    """Clear module-level session state for clean tests."""
    browser_mod._sessions.clear()


def _install_session(session_key: str = "default"):
    """Install a mock session and return the mock page."""
    mock_page = MagicMock()
    mock_page.title.return_value = "Test Page"
    mock_page.url = "https://example.com"
    mock_page.accessibility.snapshot.return_value = {
        "role": "document",
        "name": "Test",
    }
    mock_page.inner_text.return_value = "Normal page content"
    mock_page.screenshot.return_value = b"\x89PNGfakedata"
    mock_page.eval_on_selector_all.return_value = [
        {"title": "Result 1", "url": "https://r1.com", "snippet": "Snippet 1"},
    ]
    browser_mod._sessions[session_key] = {
        "pw": MagicMock(),
        "browser": MagicMock(),
        "context": MagicMock(),
        "page": mock_page,
        "last_used": time.time(),
    }
    return mock_page


class TestBrowserWorkflow:
    """Integration tests for multi-tool browser workflows."""

    def test_navigate_then_type_then_click_sequence(self):
        """A sequence of navigate -> type -> click -> content returns valid JSON
        at each step, with sessions persisting across calls."""
        _reset_sessions()
        mock_page = _install_session()

        # Navigate
        result = browser_mod.browser_navigate("https://example.com")
        data = json.loads(result)
        assert "title" in data
        assert "url" in data

        # Type
        result = browser_mod.browser_type("#search", "test", press_enter=True)
        data = json.loads(result)
        assert "title" in data
        mock_page.fill.assert_called_once()

        # Click
        result = browser_mod.browser_click("button.submit")
        data = json.loads(result)
        assert "title" in data
        mock_page.click.assert_called_once()

        # Content
        result = browser_mod.browser_content(mode="text")
        data = json.loads(result)
        assert "content" in data

        # Session persisted across all calls
        assert "default" in browser_mod._sessions

    def test_navigate_then_close_cleans_up(self):
        """Navigating then closing leaves _sessions empty."""
        _reset_sessions()
        _install_session()

        browser_mod.browser_navigate("https://example.com")
        assert "default" in browser_mod._sessions

        browser_mod.browser_close(session_key="default")
        assert "default" not in browser_mod._sessions

    def test_web_search_uses_separate_session(self):
        """web_search does not interfere with a 'default' session."""
        _reset_sessions()
        _install_session("default")
        _install_session("_web_search")

        # Navigate in default session
        browser_mod.browser_navigate(
            "https://example.com", session_key="default"
        )

        # Search in _web_search session
        result = browser_mod.web_search("test query")
        data = json.loads(result)
        assert "results" in data

        # Both sessions still exist
        assert "default" in browser_mod._sessions
        assert "_web_search" in browser_mod._sessions

    def test_idle_timeout_cleanup_during_workflow(self):
        """After manually setting last_used to the past and calling
        _cleanup_idle(), the session is removed."""
        _reset_sessions()
        _install_session()

        # Artificially age the session
        browser_mod._sessions["default"]["last_used"] = (
            time.time() - browser_mod._IDLE_TIMEOUT - 10
        )

        browser_mod._cleanup_idle()
        assert "default" not in browser_mod._sessions
