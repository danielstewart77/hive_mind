"""Unit tests for the /browse skill SKILL.md files.

Verifies that both copies exist, are identical, and contain required
frontmatter and content.
"""

import os

import yaml


ACTIVE_SKILL = "/usr/src/app/.claude/skills/browse/SKILL.md"
SPEC_SKILL = "/usr/src/app/specs/skills/browse/SKILL.md"


def _read_file(path: str) -> str:
    with open(path) as f:
        return f.read()


def _parse_frontmatter(content: str) -> dict:
    """Parse YAML frontmatter from a SKILL.md file."""
    if not content.startswith("---"):
        return {}
    parts = content.split("---", 2)
    if len(parts) < 3:
        return {}
    return yaml.safe_load(parts[1]) or {}


class TestBrowseSkillExists:
    """Tests that both skill file copies exist and are identical."""

    def test_active_skill_file_exists(self):
        assert os.path.isfile(ACTIVE_SKILL), f"Missing: {ACTIVE_SKILL}"

    def test_spec_skill_file_exists(self):
        assert os.path.isfile(SPEC_SKILL), f"Missing: {SPEC_SKILL}"

    def test_both_copies_are_identical(self):
        active = _read_file(ACTIVE_SKILL)
        spec = _read_file(SPEC_SKILL)
        assert active == spec, "Active and spec copies of SKILL.md differ"


class TestBrowseSkillFrontmatter:
    """Tests for YAML frontmatter fields."""

    def test_has_required_frontmatter_fields(self):
        content = _read_file(ACTIVE_SKILL)
        fm = _parse_frontmatter(content)
        assert "name" in fm
        assert "description" in fm
        assert "user-invocable" in fm

    def test_name_is_browse(self):
        content = _read_file(ACTIVE_SKILL)
        fm = _parse_frontmatter(content)
        assert fm["name"] == "browse"

    def test_user_invocable_is_true(self):
        content = _read_file(ACTIVE_SKILL)
        fm = _parse_frontmatter(content)
        assert fm["user-invocable"] is True


class TestBrowseSkillContent:
    """Tests for skill content."""

    def test_mentions_captcha_handling(self):
        content = _read_file(ACTIVE_SKILL)
        assert "captcha" in content.lower() or "CAPTCHA" in content

    def test_mentions_selector_strategy(self):
        content = _read_file(ACTIVE_SKILL)
        assert "role=" in content or "selector" in content.lower()
