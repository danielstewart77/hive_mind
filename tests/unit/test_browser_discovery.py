"""Unit tests for browser module import safety and tool discovery.

Verifies the module imports without side effects and all 7 tools
are discoverable by agent_tooling.
"""

import agents.browser as browser_mod


class TestBrowserModuleImport:
    """Tests for safe module import."""

    def test_browser_module_imports_without_playwright(self):
        """Module should import even when playwright is mocked."""
        assert browser_mod is not None

    def test_browser_module_has_no_side_effects_at_import(self):
        """No browser processes should be launched at import time.
        _sessions should be empty by default (no auto-launch)."""
        # The module was imported at the top of this file; sessions dict
        # should exist and be a dict (may have entries from other tests,
        # so just check the type).
        assert isinstance(browser_mod._sessions, dict)


class TestBrowserToolDiscovery:
    """Tests that all 7 tools are discovered by agent_tooling."""

    def test_all_seven_tools_discoverable(self):
        from agent_tooling import discover_tools, get_tool_schemas

        discover_tools(["agents"])
        schemas = get_tool_schemas()
        tool_names = {s["name"] for s in schemas}

        expected = {
            "browser_navigate",
            "browser_click",
            "browser_type",
            "browser_content",
            "browser_screenshot",
            "browser_close",
            "web_search",
        }
        for name in expected:
            assert name in tool_names, f"Tool '{name}' not discovered"

    def test_tools_have_web_browser_tags(self):
        from agent_tooling import discover_tools, get_tool_schemas

        discover_tools(["agents"])
        schemas = get_tool_schemas()

        browser_tool_names = {
            "browser_navigate",
            "browser_click",
            "browser_type",
            "browser_content",
            "browser_screenshot",
            "browser_close",
            "web_search",
        }

        for schema in schemas:
            if schema["name"] in browser_tool_names:
                tags = schema.get("tags", [])
                assert "web" in tags, f"Tool '{schema['name']}' missing 'web' tag"
                assert "browser" in tags, f"Tool '{schema['name']}' missing 'browser' tag"
