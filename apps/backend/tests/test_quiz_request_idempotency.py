"""自测卷作答的幂等语义：区分「网络重试」与「用户重新答题」。

- 带 request_key：同一次作答动作（含重试）严格 exactly-once；换键即新作答，
  即使选了同一个选项也如实记成一次新作答。
- 不带 request_key：沿用「最近一次答案相同即视为重试」的旧兜底，保证重试安全。
- 并发：同一键并发提交最终只落一行（SQLite 用写锁串行，PostgreSQL 用唯一索引兜底，
  后者由 IntegrityError 回放分支覆盖）。
"""

from __future__ import annotations

import threading

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import Quiz, QuizAttempt, QuizItem
from app.services.quiz import grade_answers


def _make_quiz(db: Session) -> tuple[str, str]:
    quiz = Quiz(course_id="course-1", title="Review")
    quiz.items.append(QuizItem(
        seq=1, item_type="choice", stem="Question?", options_json='["A","B"]', answer="A",
    ))
    db.add(quiz)
    db.flush()
    return quiz.id, quiz.items[0].id


def _memory_engine():
    engine = create_engine("sqlite:///:memory:")
    Quiz.__table__.create(engine)
    QuizItem.__table__.create(engine)
    QuizAttempt.__table__.create(engine)
    return engine


def _count(db: Session) -> int:
    return db.scalar(select(func.count()).select_from(QuizAttempt)) or 0


def test_request_key_replay_is_exactly_once():
    engine = _memory_engine()
    with Session(engine) as db:
        quiz_id, item_id = _make_quiz(db)
        quiz = db.get(Quiz, quiz_id)
        entry = [{"item_id": item_id, "answer": "B", "request_key": "rk-1"}]
        first = grade_answers(db, quiz, entry)
        second = grade_answers(db, quiz, entry)
        assert first[0]["correct"] is False
        assert second[0]["correct"] is False
        assert _count(db) == 1, "同一个 request_key 重发只能落一行"


def test_new_request_key_is_a_new_answer_even_with_same_option():
    engine = _memory_engine()
    with Session(engine) as db:
        quiz_id, item_id = _make_quiz(db)
        quiz = db.get(Quiz, quiz_id)
        grade_answers(db, quiz, [{"item_id": item_id, "answer": "B", "request_key": "rk-a"}])
        grade_answers(db, quiz, [{"item_id": item_id, "answer": "B", "request_key": "rk-b"}])
        assert _count(db) == 2, "换键就是用户重新答题，即使选项相同也要留痕"


def test_legacy_submission_without_key_keeps_retry_safety():
    engine = _memory_engine()
    with Session(engine) as db:
        quiz_id, item_id = _make_quiz(db)
        quiz = db.get(Quiz, quiz_id)
        entry = [{"item_id": item_id, "answer": "A"}]
        assert grade_answers(db, quiz, entry)[0]["correct"] is True
        assert grade_answers(db, quiz, entry)[0]["correct"] is True
        assert _count(db) == 1, "不带键时沿用旧兜底，重发不能重复落行"


def test_concurrent_same_request_key_writes_one_row(tmp_path):
    engine = create_engine(
        f"sqlite:///{(tmp_path / 'quiz.sqlite3').as_posix()}",
        connect_args={"timeout": 10},
    )
    Quiz.__table__.create(engine)
    QuizItem.__table__.create(engine)
    QuizAttempt.__table__.create(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory() as db:
        quiz_id, item_id = _make_quiz(db)
        db.commit()

    submission = [{"item_id": item_id, "answer": "A", "request_key": "same-key"}]
    barrier = threading.Barrier(2)
    errors: list[BaseException] = []
    results: list[list[dict]] = []
    lock = threading.Lock()

    def submit() -> None:
        try:
            barrier.wait(timeout=10)
            with factory() as db:
                quiz = db.get(Quiz, quiz_id)
                outcome = grade_answers(db, quiz, submission)
                db.commit()
            with lock:
                results.append(outcome)
        except BaseException as exc:
            with lock:
                errors.append(exc)

    threads = [threading.Thread(target=submit) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert not errors, errors
    assert len(results) == 2
    assert all(outcome[0]["correct"] is True for outcome in results)
    with factory() as db:
        assert _count(db) == 1
    engine.dispose()
