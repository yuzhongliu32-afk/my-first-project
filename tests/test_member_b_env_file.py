"""--env-file loader: loads only allowed names, never overrides, never echoes values."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from modules.member_b.env_file import load_env_file


class EnvFileTests(unittest.TestCase):
    def write(self, text):
        d = tempfile.mkdtemp()
        p = Path(d) / ".env"
        p.write_text(text, encoding="utf-8")
        return p

    def test_loads_allowed_names_only(self):
        p = self.write('# comment\nOPENAI_API_KEY="sk-test-placeholder"\nexport OPENAI_MODEL=model-x\n'
                       'JIRA_API_TOKEN=should-not-load\nOPENAI_INPUT_USD_PER_MILLION=\n')
        with mock.patch.dict(os.environ, {}, clear=True):
            loaded = load_env_file(p)
            self.assertEqual(sorted(loaded), ["OPENAI_API_KEY", "OPENAI_MODEL"])
            self.assertEqual(os.environ["OPENAI_API_KEY"], "sk-test-placeholder")
            self.assertNotIn("JIRA_API_TOKEN", os.environ)
            self.assertNotIn("OPENAI_INPUT_USD_PER_MILLION", os.environ)

    def test_existing_environment_wins(self):
        p = self.write("OPENAI_MODEL=from-file\n")
        with mock.patch.dict(os.environ, {"OPENAI_MODEL": "from-shell"}, clear=True):
            self.assertEqual(load_env_file(p), [])
            self.assertEqual(os.environ["OPENAI_MODEL"], "from-shell")

    def test_missing_file(self):
        with self.assertRaises(FileNotFoundError):
            load_env_file("/nonexistent/.env")


if __name__ == "__main__":
    unittest.main()
