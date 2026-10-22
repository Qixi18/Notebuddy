"""Small, explainable teaching-context classifier for local assistant prompts."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TeachingContext:
    learning_goal: str
    discipline: str
    matched_terms: tuple[str, ...] = ()


_DISCIPLINE_TERMS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("数学", ("函数", "导数", "积分", "矩阵", "概率", "定理", "方程", "向量")),
    ("计算机科学", ("代码", "算法", "数据结构", "数据库", "网络", "依赖注入", "编译器")),
    ("物理", ("力", "速度", "加速度", "能量", "电场", "磁场", "量子")),
    ("化学", ("分子", "原子", "反应", "化合物", "酸碱", "氧化")),
    ("经济学", ("供给", "需求", "市场", "通胀", "成本", "收益", "边际")),
    ("社会科学", ("社会", "制度", "组织", "文化", "样本", "回归", "问卷")),
)

_GOAL_TERMS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("准备复习", ("复习", "总结", "考点", "考试", "重点")),
    (
        "解决练习",
        (
            "怎么做", "怎么算", "如何算", "怎么求", "如何求", "算一下", "求值",
            "计算", "解题", "练习", "例题", "证明", "这道题", "这题",
        ),
    ),
    ("比较方法", ("区别", "比较", "优缺点", "什么时候用", "对比")),
    ("理解概念", ("是什么", "为什么", "含义", "解释", "理解")),
)


def infer_context(question: str, requested_goal: str | None = None) -> TeachingContext:
    normalized = question.casefold()
    discipline = "通用课程"
    matched: list[str] = []
    for candidate, terms in _DISCIPLINE_TERMS:
        hits = [term for term in terms if term.casefold() in normalized]
        if hits:
            discipline = candidate
            matched.extend(hits)
            break
    if requested_goal and requested_goal.strip():
        learning_goal = requested_goal.strip()[:60]
    else:
        learning_goal = "理解概念"
        for candidate, terms in _GOAL_TERMS:
            if any(term.casefold() in normalized for term in terms):
                learning_goal = candidate
                break
    return TeachingContext(
        learning_goal=learning_goal,
        discipline=discipline,
        matched_terms=tuple(matched),
    )
