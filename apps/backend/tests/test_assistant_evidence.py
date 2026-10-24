from app.ai.evidence import extract_claims
from app.retrieval.service import RetrievedChunk


def test_answer_markers_map_each_claim_to_course_and_web_sources():
    chunks = [
        RetrievedChunk(
            material_id="material-1", lecture_title="第一讲", page_number=2,
            text="课程直接事实", score=2.0, page_block_id="block-1", direct_support=True,
        ),
        RetrievedChunk(
            material_id="material-1", lecture_title="第二讲", page_number=4,
            text="课程相关内容", score=1.0, page_block_id="block-2", direct_support=False,
        ),
    ]
    claims = extract_claims(
        "结论一 [课程资料：第一讲 | 第 2 页]\n\n结论二 [网络来源 1]",
        chunks,
        [{"title": "外部来源", "url": "https://example.com"}],
    )
    assert [(claim.claim_key, claim.chunk_indexes, claim.web_indexes) for claim in claims] == [
        ("claim-1", (0,), ()),
        ("claim-2", (), (0,)),
    ]
    assert claims[0].support_level == "direct"
    assert claims[0].evidence_type == "course_direct"
    assert claims[1].support_level == "supplement"
    assert claims[1].evidence_type == "web_supplement"


def test_unmarked_answer_is_explicitly_related_to_retrieved_sources():
    chunks = [RetrievedChunk(
        material_id="material-1", lecture_title="第一讲", page_number=1,
        text="相关", score=1.0, page_block_id="block-1", direct_support=False,
    )]
    claims = extract_claims("模型没有输出来源标记。", chunks, [])
    assert claims[0].chunk_indexes == (0,)
    assert claims[0].support_level == "related"


def test_answer_categories_keep_unverified_explanations_distinct():
    claims = extract_claims(
        "[通用解释] 这是脱离课程资料的基础说明。\n\n[模型推断] 这是基于多条线索的推断。",
        [RetrievedChunk(
            material_id="material-1", lecture_title="第一讲", page_number=1,
            text="课程事实", score=1.0, page_block_id="block-1", direct_support=True,
        )],
        [{"title": "外部来源", "url": "https://example.com"}],
    )
    assert [claim.evidence_type for claim in claims] == ["general_explanation", "model_inference"]
    assert claims[0].support_level == "unverified"
    assert claims[0].chunk_indexes == () and claims[0].web_indexes == ()
    assert claims[1].support_level == "direct"


def test_multi_page_marker_links_every_listed_page():
    """模型常在一个标记里列多页（第 2、3、5 页），必须逐个命中。"""
    chunks = [
        RetrievedChunk(
            material_id="material-1", lecture_title="第一讲", page_number=2,
            text="页 2", score=1.0, page_block_id="block-1", direct_support=True,
        ),
        RetrievedChunk(
            material_id="material-1", lecture_title="第一讲", page_number=3,
            text="页 3", score=1.0, page_block_id="block-2", direct_support=True,
        ),
        RetrievedChunk(
            material_id="material-1", lecture_title="第一讲", page_number=5,
            text="页 5", score=1.0, page_block_id="block-3", direct_support=True,
        ),
    ]
    claims = extract_claims("结论。[课程资料：第一讲 | 第 2、3、5 页]", chunks, [])
    assert claims[0].chunk_indexes == (0, 1, 2)
    assert claims[0].evidence_type == "course_direct"


def test_multi_page_marker_accepts_ranges_and_ignores_unknown_pages():
    chunks = [
        RetrievedChunk(
            material_id="material-1", lecture_title="第一讲", page_number=2,
            text="页 2", score=1.0, page_block_id="block-1", direct_support=False,
        ),
        RetrievedChunk(
            material_id="material-1", lecture_title="第一讲", page_number=3,
            text="页 3", score=1.0, page_block_id="block-2", direct_support=False,
        ),
    ]
    # 区间写法：第 2-3 页
    claims = extract_claims("区间。[课程资料：第一讲 | 第 2-3 页]", chunks, [])
    assert claims[0].chunk_indexes == (0, 1)
    # 页码超出实际来源的只标命中的，不虚标
    claims = extract_claims("越界。[课程资料：第一讲 | 第 2、99 页]", chunks, [])
    assert claims[0].chunk_indexes == (0,)
