"""--env-file loader: loads only allowed names, never overrides, never echoes values."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from modules.member_b.env_file import load_env_file, read_env_file, set_values


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


class EnvWriteTests(unittest.TestCase):
    def test_notepad_bom_is_read(self):
        d = Path(tempfile.mkdtemp()) / ".env"
        d.write_bytes(b"\xef\xbb\xbfOPENAI_MODEL=model-x\n")
        self.assertEqual(read_env_file(d), {"OPENAI_MODEL": "model-x"})

    def test_set_values_replaces_and_keeps_other_lines(self):
        d = Path(tempfile.mkdtemp()) / ".env"
        d.write_text("# comment\nOPENAI_API_KEY=\nJIRA_EMAIL=\nOPENAI_MODEL=old\n", encoding="utf-8")
        set_values(d, {"OPENAI_API_KEY": "sk-test-placeholder-abcdef", "OPENAI_MODEL": "new"})
        text = d.read_text(encoding="utf-8")
        self.assertIn("# comment", text)
        self.assertIn("JIRA_EMAIL=", text)
        self.assertEqual(read_env_file(d), {"OPENAI_API_KEY": "sk-test-placeholder-abcdef", "OPENAI_MODEL": "new"})
        self.assertEqual(text.count("OPENAI_MODEL="), 1)

    def test_server_picks_up_saved_env_without_restart(self):
        from modules.member_b.http_api import MemberBHTTPHandler
        d = Path(tempfile.mkdtemp()) / ".env"
        d.write_text("OPENAI_API_KEY=\n", encoding="utf-8")
        old = (MemberBHTTPHandler.env_file_path, MemberBHTTPHandler._env_mtime)
        try:
            with mock.patch.dict(os.environ, {}, clear=True):
                MemberBHTTPHandler.env_file_path, MemberBHTTPHandler._env_mtime = d, None
                MemberBHTTPHandler.sync_env_file()
                self.assertNotIn("OPENAI_API_KEY", os.environ)
                set_values(d, {"OPENAI_API_KEY": "sk-test-placeholder-abcdef", "OPENAI_MODEL": "m"})
                os.utime(d, (1, 2))  # make sure the modification time differs
                MemberBHTTPHandler.sync_env_file()
                self.assertEqual(os.environ["OPENAI_MODEL"], "m")
                self.assertTrue(os.environ["OPENAI_API_KEY"].startswith("sk-test"))
        finally:
            MemberBHTTPHandler.env_file_path, MemberBHTTPHandler._env_mtime = old


if __name__ == "__main__":
    unittest.main()
