from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.db.database import Base, get_db
from app.db.models import Course, Quiz, QuizAttempt, QuizItem
from app.main import app


def test_quiz_api_scores_on_server_deduplicates_retries_and_scopes_courses(tmp_path) -> None:
    engine = create_engine(f"sqlite:///{(tmp_path / 'quiz.sqlite3').as_posix()}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)

    def test_db():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = test_db
    try:
        with factory() as db:
            first_course, other_course = Course(name="First"), Course(name="Other")
            db.add_all([first_course, other_course])
            db.flush()
            first_quiz = Quiz(course_id=first_course.id, title="First quiz")
            first_quiz.items.append(QuizItem(
                seq=1, item_type="choice", stem="Choose A", options_json='["A","B"]',
                answer="A", explanation="A is correct",
            ))
            other_quiz = Quiz(course_id=other_course.id, title="Other quiz")
            other_quiz.items.append(QuizItem(
                seq=1, item_type="choice", stem="Choose B", options_json='["A","B"]',
                answer="B", explanation="B is correct",
            ))
            db.add_all([first_quiz, other_quiz])
            db.commit()
            first_course_id, other_course_id = first_course.id, other_course.id
            quiz_id, item_id = first_quiz.id, first_quiz.items[0].id
            other_item_id = other_quiz.items[0].id

        with TestClient(app) as client:
            listed = client.get(f"/api/v1/courses/{first_course_id}/quizzes")
            assert listed.status_code == 200
            assert [row["id"] for row in listed.json()] == [quiz_id]
            assert "answer" not in listed.json()[0]["items"][0]
            assert "answer" not in client.get(f"/api/v1/quizzes/{quiz_id}").json()["items"][0]

            foreign = client.post(f"/api/v1/quizzes/{quiz_id}/attempts", json={
                "answers": [{"item_id": other_item_id, "answer": "B"}],
            })
            assert foreign.status_code == 422
            duplicate = client.post(f"/api/v1/quizzes/{quiz_id}/attempts", json={
                "answers": [{"item_id": item_id, "answer": "A"}, {"item_id": item_id, "answer": "B"}],
            })
            assert duplicate.status_code == 422
            with Session(engine) as db:
                assert db.scalar(select(func.count()).select_from(QuizAttempt)) == 0

            wrong = {"answers": [{"item_id": item_id, "answer": "B"}]}
            first = client.post(f"/api/v1/quizzes/{quiz_id}/attempts", json=wrong)
            assert first.status_code == 200
            assert first.json()["results"][0]["correct"] is False
            assert first.json()["results"][0]["answer"] == "A"
            repeated = client.post(f"/api/v1/quizzes/{quiz_id}/attempts", json=wrong)
            assert repeated.status_code == 200
            assert repeated.json()["results"][0]["correct"] is False

            mistakes = client.get(f"/api/v1/courses/{first_course_id}/quiz-mistakes").json()
            assert [row["item_id"] for row in mistakes] == [item_id]
            assert client.get(f"/api/v1/courses/{other_course_id}/quiz-mistakes").json() == []
            with Session(engine) as db:
                assert db.scalar(select(func.count()).select_from(QuizAttempt)) == 1
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
