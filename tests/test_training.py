import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from waiterbot.storage import Store
from waiterbot.training import Training, StaleAction


def question(identity="q1"):
    return {"id": identity, "category": "Меню", "question": "Состав?", "options": ["А", "Б", "В", "Г"], "correct": 1}


class TrainingTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.store = Store(Path(temporary.name) / "bot.sqlite3")
        self.store.initialize()
        self.training = Training(self.store)

    def start(self, questions=None, mode="test"):
        return self.training.start(101, "waiter", "Меню", questions or [question()], "all", mode)

    def test_restart_preserves_question_feedback_and_score(self):
        session = self.start([question("q1"), question("q2")])
        current = self.training.answer(101, session["id"], 0, 1)
        restarted = Training(Store(self.store.db_path))
        self.assertEqual(restarted.store.get_session(101), current)
        current = restarted.next(101, session["id"], 1)
        self.assertEqual((current["phase"], current["score"]), ("question", 1))
        with self.assertRaises(StaleAction):
            restarted.answer(101, session["id"], 0, 2)
        current = restarted.answer(101, session["id"], 1, 2)
        completed = restarted.next(101, session["id"], 2)
        self.assertEqual((completed["phase"], completed["score"]), ("complete", 1))
        self.assertEqual(len(self.store.read_results()), 1)
        self.assertIsNone(self.store.get_session(101))

    def test_duplicate_clicks_and_cross_user_actions_do_not_advance(self):
        session = self.start()
        def answer(_):
            try:
                self.training.answer(101, session["id"], 0, 1)
                return True
            except StaleAction:
                return False
        with ThreadPoolExecutor(max_workers=8) as pool:
            self.assertEqual(sum(pool.map(answer, range(16))), 1)
        current = self.store.get_session(101)
        self.assertEqual((current["score"], current["index"], len(current["answers"])), (1, 1, 1))
        with self.assertRaises(StaleAction):
            self.training.next(102, session["id"], 1)
        self.training.next(101, session["id"], 1)
        with self.assertRaises(StaleAction):
            self.training.next(101, session["id"], 1)

    def test_cancelled_test_old_buttons_cannot_change_new_attempt(self):
        old = self.start()
        self.training.cancel(101, old["id"])
        new = self.start()
        with self.assertRaises(StaleAction):
            self.training.answer(101, old["id"], 0, 1)
        with self.assertRaises(StaleAction):
            self.training.cancel(101, old["id"])
        self.assertEqual(self.store.get_session(101), new)
        self.assertEqual(self.store.read_results(), [])

    def test_active_attempt_is_never_silently_replaced(self):
        session = self.start()
        with self.assertRaises(ValueError):
            self.start()
        self.assertEqual(self.store.get_session(101), session)

    def test_invalid_choice_changes_nothing(self):
        session = self.start()
        for choice in (0, 5, True):
            with self.assertRaises(ValueError):
                self.training.answer(101, session["id"], 0, choice)
        self.assertEqual(self.store.get_session(101), session)

    def test_practice_clears_mistake_without_inflating_assessment(self):
        session = self.start()
        self.training.answer(101, session["id"], 0, 2)
        self.training.next(101, session["id"], 1)
        self.assertEqual(self.store.get_mistakes(101), [question()])
        session = self.start(self.store.get_mistakes(101), "practice")
        self.training.answer(101, session["id"], 0, 1)
        self.training.next(101, session["id"], 1)
        self.assertEqual(self.store.get_mistakes(101), [])
        self.assertEqual(len(self.store.read_results(mode="test")), 1)
        self.assertEqual(len(self.store.read_results(mode="practice")), 1)
