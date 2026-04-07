#!/usr/bin/env python3
import json
import tempfile
import unittest
from pathlib import Path

from telegram_history import import_telegram_history, imported_history_items


class TelegramHistoryTests(unittest.TestCase):
    def test_import_json_export_marks_messages_as_historical(self):
        with tempfile.TemporaryDirectory(prefix="meridian-telegram-history-") as tmpdir:
            export_path = Path(tmpdir) / "telegram.json"
            export_path.write_text(
                json.dumps(
                    {
                        "messages": [
                            {"id": 1, "date": "2026-03-01T01:02:03Z", "from": "me", "text": "Hello Leviathann"},
                            {"id": 2, "date": "2026-03-01T01:03:03Z", "from": "Leviathann", "text": "Hello back"},
                        ]
                    }
                ),
                encoding="utf-8",
            )
            result = import_telegram_history(
                export_path,
                "telegram:5322393870",
                manager_name="Leviathann",
                loom_root=tmpdir,
            )
            self.assertTrue(result["ok"])
            items = imported_history_items("telegram:5322393870", loom_root=tmpdir)
            self.assertEqual(len(items), 2)
            self.assertEqual(items[0]["speaker"], "user")
            self.assertEqual(items[1]["speaker"], "manager")
            self.assertTrue(items[0]["imported"])
            self.assertEqual(items[0]["status"], "historical")
            self.assertEqual(items[0]["source_label"], "imported_history")


if __name__ == "__main__":
    unittest.main()
