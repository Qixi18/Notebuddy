"""Budget and truncation recovery at the real synchronous provider boundary."""

from __future__ import annotations

import json
from dataclasses import replace

import httpx
import pytest

from app.ai.deepseek import DeepSeekClient, DeepSeekError
from app.core.config import settings
from app.generation import composer
from app.generation.composer import CompositionError, compose_deepseek
from app.generation.planner import build_plan


def _snapshot(*, blocks=4, text="根据资料整理内容。", generator="deepseek"):
    return {
        "notebook_title": "合成资料", "current_outline": [],
        "generator": generator, "batch_chars": 18_000,
        "sources": [{
            "asset_id": "asset-1", "name": "合成资料", "parse_run_id": "run-1",
            "sections": [{
                "section_id": "s1", "title": "概念", "level": 2,
                "blocks": [{"block_id": f"b{index}", "type": "paragraph", "text": text}
                           for index in range(blocks)],
            }],
        }],
    }


def _client(monkeypatch, responder):
    client = DeepSeekClient(replace(settings, deepseek_api_key="synthetic-test-key"))
    monkeypatch.setattr(composer, "DeepSeekClient", lambda: client)

    def post(_url, **kwargs):
        body = responder(kwargs["json"])
        return httpx.Response(200, json=body, request=httpx.Request("POST", "https://test.invalid"))

    monkeypatch.setattr(httpx, "post", post)
    return client


def _response(content, reason="stop"):
    return {
        "choices": [{"finish_reason": reason, "message": {"content": content}}],
        "usage": {"prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 30},
    }


def _valid_result(payload):
    blocks = [block for unit in json.loads(payload["messages"][1]["content"])["units"]
              for block in unit["blocks"]]
    # Deliberately reuse IDs across independent provider responses.
    return _response(json.dumps({
        "nodes": [{"type": "paragraph", "attrs": {"blockId": f"p{index}"},
                   "content": [{"type": "text", "text": block["text"]}]}
                  for index, block in enumerate(blocks)],
        "sources": {f"p{index}": [block["block_id"]] for index, block in enumerate(blocks)},
    }))


@pytest.mark.parametrize("content", [None, "", '{"nodes":[', '{"nodes":[],"sources":{}}'])
def test_length_finish_is_recoverable_even_for_empty_or_parseable_json(monkeypatch, content):
    client = _client(monkeypatch, lambda _: _response(content, "length"))
    with pytest.raises(DeepSeekError) as captured:
        client.complete_json([{"role": "user", "content": "合成 JSON"}])
    assert captured.value.code == "output_truncated"
    assert client.last_finish_reason == "length"
    assert client.last_usage == {"prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 30}


def test_generation_reserves_output_for_json_without_changing_default_completion(monkeypatch):
    def responder(payload):
        if payload.get("thinking") != {"type": "disabled"}:
            return _response("", "length")
        assert payload["max_tokens"] == 20_000
        return _valid_result(payload)

    client = _client(monkeypatch, responder)
    snapshot = _snapshot(blocks=1)
    plan = build_plan(snapshot)
    result = compose_deepseek(snapshot, plan, plan["batches"][0])
    assert list(result.source_map.values()) == [["b0"]]
    # General completion continues to use the provider's default thinking setting.
    with pytest.raises(DeepSeekError):
        client.complete_json([{"role": "user", "content": "合成 JSON"}])


def test_truncated_old_batch_is_split_without_losing_sources_or_colliding_ids(monkeypatch):
    requests = []

    def responder(payload):
        blocks = [block for unit in json.loads(payload["messages"][1]["content"])["units"]
                  for block in unit["blocks"]]
        requests.append([block["block_id"] for block in blocks])
        return _response('{"nodes":[', "length") if len(blocks) > 2 else _valid_result(payload)

    _client(monkeypatch, responder)
    snapshot = _snapshot()
    original = json.dumps(snapshot)
    plan = build_plan(snapshot)
    result = compose_deepseek(snapshot, plan, [unit["unit_id"] for unit in plan["units"]])
    assert requests == [["b0", "b1", "b2", "b3"], ["b0", "b1"], ["b2", "b3"]]
    assert len(result.nodes) == 4
    assert len({node["attrs"]["blockId"] for node in result.nodes}) == 4
    assert sorted(source for ids in result.source_map.values() for source in ids) == [
        "b0", "b1", "b2", "b3",
    ]
    assert json.dumps(snapshot) == original


def test_indivisible_truncation_fails_once_with_actionable_error(monkeypatch):
    calls = []

    def responder(payload):
        calls.append(payload)
        return _response(None, "length")

    _client(monkeypatch, responder)
    snapshot = _snapshot(blocks=1)
    plan = build_plan(snapshot)
    with pytest.raises(CompositionError, match="原文块") as captured:
        compose_deepseek(snapshot, plan, plan["batches"][0])
    assert captured.value.code == "model_output_limit"
    assert len(calls) == 1


def test_planner_budgets_structure_for_many_short_source_blocks():
    snapshot = _snapshot(blocks=100, text="内容")
    plan = build_plan(snapshot)
    assert len(plan["batches"]) > 1
    assert sorted(block for unit in plan["units"] for block in unit["block_ids"]) == sorted(
        f"b{index}" for index in range(100)
    )


def test_old_plan_is_proactively_partitioned_by_output_budget(monkeypatch):
    seen = []

    def responder(payload):
        blocks = [block for unit in json.loads(payload["messages"][1]["content"])["units"]
                  for block in unit["blocks"]]
        seen.append(len(blocks))
        # A realistic fixed envelope cost per generated Tiptap node/source link.
        return _response("", "length") if len(blocks) > 30 else _valid_result(payload)

    _client(monkeypatch, responder)
    snapshot = _snapshot(blocks=100, text="内容", generator="offline-extractive")
    plan = build_plan(snapshot)  # Represents a previously persisted character-only plan.
    result = compose_deepseek(snapshot, plan, plan["batches"][0])
    assert len(result.nodes) == 100
    assert len(result.source_map) == 100
    assert max(seen) <= 30


def test_adaptive_splitting_has_a_fixed_request_ceiling(monkeypatch):
    calls = []

    def responder(payload):
        blocks = [block for unit in json.loads(payload["messages"][1]["content"])["units"]
                  for block in unit["blocks"]]
        calls.append(len(blocks))
        return _response("", "length") if len(blocks) > 1 else _valid_result(payload)

    _client(monkeypatch, responder)
    snapshot = _snapshot(blocks=100)
    plan = build_plan(snapshot)
    with pytest.raises(CompositionError, match="请求上限") as captured:
        compose_deepseek(snapshot, plan, [unit["unit_id"] for unit in plan["units"]])
    assert captured.value.code == "model_output_limit"
    assert len(calls) == 32


def test_split_subrequest_cannot_cite_other_subrequest_sources(monkeypatch):
    def responder(payload):
        units = json.loads(payload["messages"][1]["content"])["units"]
        ids = [block["block_id"] for unit in units for block in unit["blocks"]]
        if len(ids) > 2:
            return _response("", "length")
        if ids == ["b0", "b1"]:
            return _valid_result(payload)
        if len(payload["messages"]) > 2:
            nodes = json.loads(payload["messages"][-2]["content"])["nodes"]
            return _response(json.dumps({"sources": {
                node["attrs"]["blockId"]: ["b0"] for node in nodes
            }}))
        result = json.loads(_valid_result(payload)["choices"][0]["message"]["content"])
        result["sources"] = {key: ["b0"] for key in result["sources"]}
        return _response(json.dumps(result))

    _client(monkeypatch, responder)
    snapshot = _snapshot()
    plan = build_plan(snapshot)
    with pytest.raises(CompositionError) as captured:
        compose_deepseek(snapshot, plan, plan["batches"][0])
    assert captured.value.code == "invalid_sources"


def test_format_repair_uses_the_same_non_thinking_output_cap(monkeypatch):
    nodes = [{"type": "paragraph", "attrs": {"blockId": "p0"},
              "content": [{"type": "text", "text": "合成正文"}]}]

    def responder(payload):
        assert payload["max_tokens"] == 20_000
        assert payload["thinking"] == {"type": "disabled"}
        return _response(json.dumps({"nodes": nodes, "sources": {"p0": ["b0"]}}))

    _client(monkeypatch, responder)
    result = composer.repair_deepseek_document_format(nodes, {"p0": ["b0"]}, {"b0"}, "格式错误")
    assert result.source_map == {"p0": ["b0"]}


@pytest.mark.parametrize("changed_id,changed_source", [("new-id", "b0"), ("p0", "b1")])
def test_format_repair_cannot_change_original_ids_or_evidence(monkeypatch, changed_id, changed_source):
    nodes = [{"type": "paragraph", "attrs": {"blockId": "p0"},
              "content": [{"type": "text", "text": "合成正文"}]}]
    repaired_nodes = [{**nodes[0], "attrs": {"blockId": changed_id}}]
    _client(monkeypatch, lambda _: _response(json.dumps({
        "nodes": repaired_nodes, "sources": {changed_id: [changed_source]},
    })))
    with pytest.raises(CompositionError) as captured:
        composer.repair_deepseek_document_format(nodes, {"p0": ["b0"]}, {"b0", "b1"}, "格式错误")
    assert captured.value.code == "document_format_repair_failed"


def test_format_repair_truncation_fails_after_one_request(monkeypatch):
    calls = []

    def responder(payload):
        calls.append(payload)
        return _response("", "length")

    _client(monkeypatch, responder)
    nodes = [{"type": "blockMath", "attrs": {"blockId": "p0", "latex": ""}}]
    with pytest.raises(CompositionError) as captured:
        composer.repair_deepseek_document_format(nodes, {"p0": ["b0"]}, {"b0"}, "公式为空")
    assert captured.value.code == "document_format_repair_failed"
    assert len(calls) == 1
