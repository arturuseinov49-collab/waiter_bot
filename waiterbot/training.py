"""Training transitions. No network or Telegram dependency."""
import copy
import random
import uuid
from datetime import datetime, timezone


class StaleAction(ValueError):
    pass


class Training:
    def __init__(self, store):
        self.store = store

    def start(self, user_id, role, category, questions, count, mode="test"):
        if self.store.get_session(user_id):
            raise ValueError("У тебя есть незаконченный тест. Продолжи его или заверши через меню.")
        if mode not in ("test", "practice"):
            raise ValueError("Неизвестный режим")
        selected = copy.deepcopy(questions)
        random.shuffle(selected)
        if count != "all":
            selected = selected[:int(count)]
        if not selected:
            raise ValueError("В этом разделе пока нет вопросов.")
        session = {"id": uuid.uuid4().hex[:16], "role_key": role, "category": category,
                   "questions": selected, "index": 0, "score": 0, "answers": [],
                   "mode": mode, "phase": "question", "created_at": datetime.now(timezone.utc).isoformat()}
        if not self.store.compare_session(user_id, None, session):
            raise StaleAction("Тест уже начат. Нажми «Продолжить».")
        return session

    def _current(self, user_id, session_id, index, phase):
        session = self.store.get_session(user_id)
        if not session or (session["id"], session["index"], session["phase"]) != (session_id, index, phase):
            raise StaleAction("Эта кнопка устарела. Нажми «Продолжить» в меню.")
        return session

    def answer(self, user_id, session_id, index, chosen):
        previous = self._current(user_id, session_id, index, "question")
        session = copy.deepcopy(previous)
        question = session["questions"][index]
        if isinstance(chosen, bool) or chosen not in range(1, len(question["options"]) + 1):
            raise ValueError("Неизвестный вариант ответа")
        correct = chosen == question["correct"]
        session["answers"].append({"question": question, "chosen": chosen, "correct": correct})
        session["score"] += int(correct)
        session["index"] += 1
        session["phase"] = "feedback"
        if not self.store.compare_session(user_id, previous, session):
            raise StaleAction("Ответ уже принят. Нажми «Продолжить».")
        return session

    def next(self, user_id, session_id, index):
        previous = self._current(user_id, session_id, index, "feedback")
        session = copy.deepcopy(previous)
        if index == len(session["questions"]):
            self.store.finish_session(user_id, session)
            session["phase"] = "complete"
        else:
            session["phase"] = "question"
            if not self.store.compare_session(user_id, previous, session):
                raise StaleAction("Вопрос уже открыт. Нажми «Продолжить».")
        return session

    def cancel(self, user_id, session_id):
        session = self.store.get_session(user_id)
        if not session or session["id"] != session_id:
            raise StaleAction("Этот тест уже закрыт.")
        if session["index"] == len(session["questions"]):
            self.store.finish_session(user_id, session)
        elif not self.store.compare_session(user_id, session, None):
            raise StaleAction("Состояние теста изменилось. Открой меню заново.")
