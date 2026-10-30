from app.api.v1.courses import create_course
from app.db.models import Course, ForestCourseProfile
from app.forest.service import ensure_profile
from app.schemas.api import CourseCreate

pytest_plugins = ["tests.notebook_fixtures"]


def test_new_empty_courses_take_available_home_slots_and_stop_at_three(session):
    created = [create_course(CourseCreate(name=f"课程 {i}"), session) for i in range(4)]
    assert [session.get(ForestCourseProfile, course.id).learning_state for course in created] == [
        "learning", "learning", "learning", "planned",
    ]


def test_removed_course_frees_a_home_slot_and_existing_choices_are_preserved(session):
    first = create_course(CourseCreate(name="第一门"), session)
    profile = session.get(ForestCourseProfile, first.id)
    profile.learning_state = "planned"
    session.commit()
    second = create_course(CourseCreate(name="第二门"), session)
    assert ensure_profile(session, first).learning_state == "planned"
    assert session.get(ForestCourseProfile, second.id).learning_state == "learning"


def test_deleted_learning_courses_do_not_use_up_home_slots(session):
    from app.db.models import utc_now

    first = create_course(CourseCreate(name="已删除"), session)
    session.get(Course, first.id).deleted_at = utc_now()
    session.commit()
    created = [create_course(CourseCreate(name=f"新课程 {i}"), session) for i in range(3)]
    assert all(session.get(ForestCourseProfile, course.id).learning_state == "learning" for course in created)
