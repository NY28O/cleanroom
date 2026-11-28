import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SKILL = Path(__file__).resolve().parents[1] / "skill/prop-image-batch"
SPEC = importlib.util.spec_from_file_location("skill_update_cli", SKILL / "scripts/batch.py")
CLI = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CLI)


class UpdateTests(unittest.TestCase):
    def test_check_update_only_reports(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(CLI, "_remote_revision", return_value={"revision": "abc123", "message": "new", "date": "2026-11-28"}):
            CLI.SKILL = Path(folder)
            CLI.STATE = CLI.SKILL / ".skill-state.json"
            CLI.check_update()
            self.assertFalse(list(Path(folder).iterdir()))

    def test_update_is_explicit_and_writes_version_state(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(CLI, "_remote_revision", return_value={"revision": "new123", "message": "new", "date": "2026-11-28"}):
            CLI.SKILL = Path(folder)
            CLI.STATE = CLI.SKILL / ".skill-state.json"
            (CLI.SKILL / "SKILL.md").parent.mkdir(parents=True, exist_ok=True)
            (CLI.SKILL / "SKILL.md").write_text("old", encoding="utf8")
            with patch.object(CLI, "urlopen", side_effect=RuntimeError("archive not needed in unit test")):
                with self.assertRaises(RuntimeError):
                    CLI.update_skill()
            self.assertEqual((CLI.SKILL / "SKILL.md").read_text("utf8"), "old")
