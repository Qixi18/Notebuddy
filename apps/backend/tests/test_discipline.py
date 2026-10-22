from app.ai.discipline import infer_context
from app.ai.prompts import build_answer_messages


def test_teaching_context_is_explainable_and_request_goal_wins():
    context = infer_context("请比较两个算法的时间复杂度", "准备复习")
    assert context.learning_goal == "准备复习"
    assert context.discipline == "计算机科学"
    assert "算法" in context.matched_terms


def test_answer_prompt_includes_learning_goal_and_discipline():
    messages = build_answer_messages(
        "导数是什么？",
        "[第一讲] 课程片段",
        learning_goal="解决练习",
        discipline="数学",
    )
    assert "学习目标：解决练习" in messages[-1]["content"]
    assert "学科提示：数学" in messages[-1]["content"]


def test_goal_is_inferred_from_question_when_not_supplied():
    """界面不再下发 learning_goal，必须靠关键词推断出合理目标。"""
    assert infer_context("这个矩阵的秩怎么算", None).learning_goal == "解决练习"
    assert infer_context("红黑树和 AVL 的区别是什么", None).learning_goal == "比较方法"
    assert infer_context("这门课考试重点有哪些", None).learning_goal == "准备复习"
    assert infer_context("什么是闭包", None).learning_goal == "理解概念"


def test_blank_requested_goal_falls_back_to_inference():
    """旧客户端可能仍传空串，不能因此吞掉推断。"""
    assert infer_context("这道题怎么做", "   ").learning_goal == "解决练习"
