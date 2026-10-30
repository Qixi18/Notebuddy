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


def test_repeated_quiz_answer_does_not_create_duplicate_attempt() -> None:
    engine = create_engine("sqlite:///:memory:")
    Quiz.__table__.create(engine)
    QuizItem.__table__.create(engine)
    QuizAttempt.__table__.create(engine)
    with Session(engine) as db:
        quiz = Quiz(course_id="course-1", title="Review")
        quiz.items.append(QuizItem(seq=1, item_type="choice", stem="Question?", answer="A"))
        db.add(quiz)
        db.flush()
        submission = [{"item_id": quiz.items[0].id, "answer": "A"}]
        first = grade_answers(db, quiz, submission)
        second = grade_answers(db, quiz, submission)
        assert first[0]["correct"] is True
        assert second[0]["correct"] is True
        assert db.scalar(select(func.count()).select_from(QuizAttempt)) == 1


def test_concurrent_duplicate_submissions_still_write_one_attempt(tmp_path) -> None:
    """同一答案的并发重试不能各插一行。

    幂等判定看的是「最近一次作答」，所以读-写之间必须串行。两个线程同时提交
    完全相同的答案，无论交错顺序如何，最终只能有一条 attempt，且两边结论一致。
    """
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

    submission = [{"item_id": item_id, "answer": "A"}]
    barrier = threading.Barrier(2)
    results: list[list[dict]] = []
    errors: list[BaseException] = []
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
        assert db.scalar(select(func.count()).select_from(QuizAttempt)) == 1
    engine.dispose()
