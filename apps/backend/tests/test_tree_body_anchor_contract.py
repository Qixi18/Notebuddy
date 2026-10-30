from app.api.v1.forest import course_tree
from app.notes.store import write_document
from app.schemas.notebook import CourseTreeRead
from tests.notebook_fixtures import make_course, make_notebook

pytest_plugins = ["tests.notebook_fixtures"]


def test_tree_response_exposes_the_body_anchor_required_by_frontend_leaf_projection(session):
    course = make_course(session, "Digital logic")
    book = make_notebook(session, course, "Gates")
    write_document(session, book, {"type": "doc", "content": [
        {"type": "heading", "attrs": {"blockId": "gate-heading", "level": 1},
         "content": [{"type": "text", "text": "AND gate"}]},
        {"type": "paragraph", "attrs": {"blockId": "gate-body"},
         "content": [{"type": "text", "text": "Both inputs must be one."}]},
    ]}, expected_revision=0)
    session.commit()
    payload = CourseTreeRead.model_validate(course_tree(course.id, session)).model_dump()
    section = payload["notebooks"][0]["chapters"][0]["sections"][0]
    assert section.get("block_id") == "gate-heading"
    assert section["notebook_id"] == book.id
    assert section["id"] == "gate-heading"
