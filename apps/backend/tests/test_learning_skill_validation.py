import pytest

from app.services.quiz import QuizSchemaError, validate_quiz_payload
from app.services.skills import (
    SkillSchemaError,
    validate_contrast_payload,
    validate_outline_payload,
)


def test_quiz_generation_requires_an_answer_in_the_options() -> None:
    valid = {"items": [{
        "type": "choice", "stem": "Which term?", "options": ["A", "B"],
        "answer": "A", "explanation": "The source says A.",
    }]}
    assert validate_quiz_payload(valid, expected_count=1)[0]["answer"] == "A"
    valid["items"][0]["answer"] = "C"
    with pytest.raises(QuizSchemaError, match="答案不在选项中"):
        validate_quiz_payload(valid, expected_count=1)


def test_review_outline_rejects_duplicate_modules() -> None:
    payload = {"modules": [
        {"title": "Limits", "items": [{"point": "Definition"}]},
        {"title": "Limits", "items": [{"point": "Examples"}]},
    ]}
    with pytest.raises(SkillSchemaError, match="重复"):
        validate_outline_payload(payload)


def test_concept_contrast_rejects_the_same_concept_on_both_sides() -> None:
    payload = {"pairs": [{
        "a": "Limit", "b": "Limit", "core": "Difference",
        "dimensions": [{"name": "Definition", "a": "A", "b": "B"},
                       {"name": "Use", "a": "A", "b": "B"}],
    }]}
    with pytest.raises(SkillSchemaError, match="相同"):
        validate_contrast_payload(payload)
