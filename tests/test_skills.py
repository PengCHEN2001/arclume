"""Tests for metadata-driven Skill loading and selection."""

from pathlib import Path
import tempfile
import unittest

from core.skill_loader import SkillLoader


class SkillLoaderTests(unittest.TestCase):
    """Verify metadata parsing, filtering, and cache invalidation."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        (root / "billing").mkdir()
        (root / "billing" / "SKILL.md").write_text(
            "---\n"
            "name: billing\n"
            "description: Billing rules\n"
            "keywords: refund, payment\n"
            "agents: billing\n"
            "enabled: true\n"
            "---\n"
            "# Billing\nUse verified billing facts.",
            encoding="utf-8",
        )
        (root / "disabled").mkdir()
        (root / "disabled" / "SKILL.md").write_text(
            "---\n"
            "name: disabled\n"
            "description: Disabled rules\n"
            "keywords: refund\n"
            "agents: billing\n"
            "enabled: false\n"
            "---\n"
            "# Disabled\nDo not inject this.",
            encoding="utf-8",
        )
        self.loader = SkillLoader(root, max_prompt_chars=200, skill_max_chars=200)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_load_parses_metadata(self) -> None:
        document = self.loader.load("billing")

        self.assertEqual(document.name, "billing")
        self.assertEqual(document.agents, ("billing",))
        self.assertEqual(document.keywords, ("refund", "payment"))
        self.assertTrue(document.enabled)
        self.assertIn("Use verified billing facts", document.content)

    def test_select_filters_by_agent_and_enabled(self) -> None:
        selected = self.loader.select_for_agent("billing", "I need a refund")

        self.assertEqual([document.name for document in selected], ["billing"])

        selected_for_technical = self.loader.select_for_agent("technical", "I need a refund")
        self.assertEqual(selected_for_technical, [])

    def test_explicit_names_are_an_allowlist(self) -> None:
        selected = self.loader.select_for_agent(
            "billing",
            "I need a refund",
            ["billing", "disabled"],
        )

        self.assertEqual([document.name for document in selected], ["billing"])

    def test_reload_reads_changed_content(self) -> None:
        path = Path(self.temp_dir.name) / "billing" / "SKILL.md"
        self.assertIn("verified billing facts", self.loader.load("billing").content)

        path.write_text(
            path.read_text(encoding="utf-8").replace(
                "verified billing facts", "updated billing facts"
            ),
            encoding="utf-8",
        )
        self.loader.reload()

        self.assertIn("updated billing facts", self.loader.load("billing").content)


if __name__ == "__main__":
    unittest.main()
