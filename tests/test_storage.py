import copy
from contextlib import closing
import json
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from openpyxl import Workbook

from waiterbot.storage import LEGACY_RESULTS_HEADERS, Store


ROLES = {"waiter": {"label": "🍽 Официант"}, "cook": {"label": "👨‍🍳 Повар"}}


def question(identity="q1", correct=1):
    return {"id": identity, "category": "Меню", "question": f"Вопрос {identity}", "options": ["Да", "Нет", "Иногда", "Никогда"], "correct": correct}


def completed(identity="session-1", *, correct=False, mode="test", role="waiter"):
    item = question()
    return {"id": identity, "role_key": role, "category": "Меню", "mode": mode,
            "questions": [item], "index": 1, "score": int(correct),
            "answers": [{"question": item, "chosen": 1 if correct else 2, "correct": correct}],
            "chat_id": 101, "message_id": 50, "created_at": "2026-09-22T12:00:00+03:00"}


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.store = Store(self.directory / "data" / "bot.sqlite3")
        self.store.initialize()

    def workbook(self, *, headers=None, rows=None):
        workbook = Workbook()
        sheet = workbook.active
        sheet.append(LEGACY_RESULTS_HEADERS if headers is None else headers)
        for row in rows or []:
            sheet.append(row)
        path = self.directory / "results.xlsx"
        workbook.save(path)
        workbook.close()
        return path

    def write_legacy_json(self):
        (self.directory / "user_roles.json").write_text(json.dumps({"101": "waiter"}), encoding="utf-8")
        (self.directory / "settings.json").write_text(json.dumps({"waiter": 15, "cook": "all"}), encoding="utf-8")

    def test_migration_is_idempotent_and_preserves_originals(self):
        self.write_legacy_json()
        path = self.workbook(rows=[["21.09.2026 12:34", 101, "Сотрудник", "@employee", ROLES["waiter"]["label"], "Меню", 3, 5, 60]])
        original = {name: (self.directory / name).read_bytes() for name in ("user_roles.json", "settings.json", "results.xlsx")}
        self.assertEqual(self.store.migrate_legacy(self.directory, ROLES), {"roles": 1, "settings": 2, "results": 1})
        self.assertEqual(self.store.migrate_legacy(self.directory, ROLES), {"roles": 0, "settings": 0, "results": 0})
        self.assertEqual(self.store.get_role(101), "waiter")
        self.assertEqual(self.store.get_question_count("cook"), "all")
        result = self.store.read_results()[0]
        self.assertEqual((result["name"], result["username"], result["role_label"], result["percent"], result["mode"]), ("Сотрудник", "employee", "🍽 Официант", 60, "test"))
        self.assertEqual(result["created_at"], "2026-09-21T12:34:00")
        self.assertTrue(path.exists())
        for name, content in original.items():
            self.assertEqual((self.directory / name).read_bytes(), content)

    def test_bad_headers_roll_back_all_legacy_imports(self):
        self.write_legacy_json()
        self.workbook(headers=["Дата", "Другая схема"])
        with self.assertRaisesRegex(ValueError, "заголовки"):
            self.store.migrate_legacy(self.directory, ROLES)
        self.assertIsNone(self.store.get_role(101))
        self.assertEqual(self.store.get_question_count("waiter"), 10)
        self.workbook()
        self.assertEqual(self.store.migrate_legacy(self.directory, ROLES)["roles"], 1)

    def test_bad_json_is_not_silently_replaced(self):
        source = self.directory / "user_roles.json"
        source.write_text("{truncated", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "user_roles.json"):
            self.store.migrate_legacy(self.directory, ROLES)
        self.assertEqual(source.read_text(encoding="utf-8"), "{truncated")

    def test_bad_result_rolls_back_earlier_rows(self):
        self.workbook(rows=[
            ["21.09.2026 12:34", 101, "Первый", "-", "🍽 Официант", "Меню", 3, 5, 60],
            ["21.09.2026 12:35", 102, "Второй", "-", "🍽 Официант", "Меню", 9, 5, 180],
        ])
        with self.assertRaisesRegex(ValueError, "некорректный результат"):
            self.store.migrate_legacy(self.directory, ROLES)
        self.assertEqual(self.store.read_results(), [])

    def test_missing_legacy_sources_can_be_imported_later(self):
        self.assertEqual(self.store.migrate_legacy(self.directory, ROLES), {"roles": 0, "settings": 0, "results": 0})
        self.write_legacy_json()
        self.assertEqual(self.store.migrate_legacy(self.directory, ROLES)["roles"], 1)

    def test_state_survives_restart_and_profile_update_preserves_role(self):
        session = completed()
        self.store.set_role(101, "waiter")
        self.store.upsert_user(101, "Новое имя", None)
        self.store.set_question_count("waiter", 20)
        self.store.save_session(101, session)
        reopened = Store(self.store.db_path)
        reopened.initialize()
        self.assertEqual(reopened.get_role(101), "waiter")
        self.assertEqual(reopened.get_question_count("waiter"), 20)
        self.assertEqual(reopened.get_session(101), session)
        self.assertTrue(reopened.finish_session(101, session))
        self.assertEqual(reopened.read_results()[0]["name"], "Новое имя")
        self.assertIsNone(reopened.get_session(101))

    def test_finish_is_idempotent_and_keeps_newer_session(self):
        old, new = completed("old"), completed("new")
        self.store.save_session(101, new)
        self.assertTrue(self.store.finish_session(101, old))
        self.assertFalse(self.store.finish_session(101, old))
        self.assertEqual(self.store.get_session(101)["id"], "new")
        self.assertEqual(len(self.store.read_results()), 1)
        with closing(sqlite3.connect(self.store.db_path)) as connection:
            self.assertEqual(connection.execute("SELECT misses FROM mistakes").fetchone()[0], 1)

    def test_practice_does_not_inflate_test_statistics(self):
        self.store.finish_session(101, completed("test"))
        self.store.finish_session(101, completed("practice", correct=True, mode="practice"))
        self.assertEqual(len(self.store.read_results(mode="test")), 1)
        self.assertEqual(len(self.store.read_results(mode="practice")), 1)
        self.assertEqual(len(self.store.read_results()), 2)
        self.assertEqual(self.store.get_mistakes(101), [])

    def test_mistakes_are_personal_resolved_and_reopened(self):
        self.store.finish_session(101, completed("wrong-1"))
        self.store.finish_session(102, completed("wrong-other"))
        self.assertEqual(self.store.get_mistakes(101, "waiter"), [question()])
        self.assertEqual(self.store.get_mistakes(101, "cook"), [])
        self.store.finish_session(101, completed("correct", correct=True))
        self.assertEqual(self.store.get_mistakes(101), [])
        self.assertEqual(self.store.get_mistakes(102), [question()])
        self.store.finish_session(101, completed("wrong-again"))
        self.assertEqual(self.store.get_mistakes(101), [question()])
        with closing(sqlite3.connect(self.store.db_path)) as connection:
            self.assertEqual(connection.execute("SELECT misses FROM mistakes WHERE user_id=101").fetchone()[0], 2)

    def test_parallel_writes_and_duplicate_finalization(self):
        def write(index):
            user_id = 1000 + index
            self.store.upsert_user(user_id, f"Сотрудник {index}", None)
            self.store.set_role(user_id, "waiter")
            self.store.save_session(user_id, completed(f"concurrent-{index}"))
            return self.store.finish_session(user_id, completed(f"concurrent-{index}"))
        with ThreadPoolExecutor(max_workers=8) as pool:
            self.assertTrue(all(pool.map(write, range(32))))
            duplicate_results = list(pool.map(lambda _: self.store.finish_session(101, completed("same-id")), range(20)))
        self.assertEqual(sum(duplicate_results), 1)
        self.assertEqual(len(self.store.read_results()), 33)
        self.assertTrue(all(self.store.get_session(1000 + i) is None for i in range(32)))

    def test_results_latest_limit_is_chronological_and_user_scoped(self):
        for index in range(4):
            self.store.finish_session(101, completed(f"result-{index}"))
        self.store.finish_session(102, completed("other"))
        self.assertEqual([r["session_id"] for r in self.store.read_results(user_id=101, limit=2)], ["result-2", "result-3"])
        self.assertEqual(self.store.read_results(limit=0), [])

    def test_incomplete_or_manipulated_results_fail_without_writes(self):
        for field, value in (("index", 0), ("score", 1), ("mode", "unknown")):
            session = completed()
            session[field] = value
            with self.assertRaises(ValueError):
                self.store.finish_session(101, session)
        session = copy.deepcopy(completed())
        session["answers"][0]["chosen"] = 99
        with self.assertRaises(ValueError):
            self.store.finish_session(101, session)
        self.assertEqual(self.store.read_results(), [])

    def test_online_backup_is_consistent_and_source_is_untouched(self):
        self.store.finish_session(101, completed())
        backup = self.directory / "backups" / "backup.sqlite3"
        self.store.backup(backup)
        self.assertEqual(Store(backup).read_results(), self.store.read_results())
        with closing(sqlite3.connect(backup)) as connection:
            self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")
        self.store.finish_session(101, completed("later"))
        self.assertEqual(len(Store(backup).read_results()), 1)
        self.assertEqual(len(self.store.read_results()), 2)
        with self.assertRaises(ValueError):
            self.store.backup(self.store.db_path)


if __name__ == "__main__":
    unittest.main()
