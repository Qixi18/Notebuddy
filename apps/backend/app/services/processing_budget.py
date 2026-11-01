"""Fail-closed per-Asset CNY reservations around document-processing model calls.

All prices are operator supplied and snapshotted per call. Shared requests are
charged in full to every participating Asset before dispatch; this deliberately
overstates per-file cost to guarantee no Asset borrows another Asset's budget.
"""
from __future__ import annotations

import json
import os
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from decimal import ROUND_CEILING, Decimal, InvalidOperation
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy import select, update
from sqlalchemy.dialects.sqlite import insert

from app.db.database import SessionLocal
from app.db.models import FileProcessingBudget, ProviderUsageReservation, new_id, utc_now

BUDGET_LIMIT_FEN = 1000
FX_MAX_AGE_DAYS = 30


class ProcessingBudgetError(RuntimeError):
    def __init__(self, message: str, *, code: str = "budget_config_missing") -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class Tariff:
    kind: str
    model: str
    input_usd_per_million: Decimal
    output_usd_per_million: Decimal
    max_image_tokens: int
    fx_usd_cny: Decimal
    fx_buffer_percent: Decimal
    fx_source: str
    fx_as_of: str
    tariff_version: str
    tariff_source: str

    def snapshot(self) -> dict[str, Any]:
        return {
            "kind": self.kind, "model": self.model,
            "input_usd_per_million": str(self.input_usd_per_million),
            "output_usd_per_million": str(self.output_usd_per_million),
            "max_image_tokens": self.max_image_tokens,
            "fx_usd_cny": str(self.fx_usd_cny),
            "fx_buffer_percent": str(self.fx_buffer_percent),
            "fx_source": self.fx_source, "fx_as_of": self.fx_as_of,
            "tariff_version": self.tariff_version, "tariff_source": self.tariff_source,
        }


def _decimal(name: str, default: str = "0") -> Decimal:
    try:
        value = Decimal(os.getenv(name, default).strip())
    except (InvalidOperation, ValueError, AttributeError) as exc:
        raise ProcessingBudgetError(f"预算配置 {name} 必须是数字") from exc
    if not value.is_finite() or value < 0:
        raise ProcessingBudgetError(f"预算配置 {name} 必须是非负有限数")
    return value


def _safe_source(name: str) -> str:
    value = os.getenv(name, "").strip()
    try:
        parsed = urlsplit(value)
    except ValueError:
        parsed = None
    if (not parsed or parsed.scheme not in {"https", "http"} or not parsed.hostname
            or parsed.username or parsed.password or parsed.query or parsed.fragment):
        raise ProcessingBudgetError(f"预算价格来源 {name} 必须是无凭据的公开 HTTP(S) URL")
    return value


def _load_tariff(kind: str, model: str) -> Tariff:
    if kind not in {"text", "vision"} or not model:
        raise ProcessingBudgetError("没有可用于该模型请求的价格配置")
    if kind == "text":
        input_rate = _decimal("DEEPSEEK_INPUT_COST_PER_MILLION")
        output_rate = _decimal("DEEPSEEK_OUTPUT_COST_PER_MILLION")
        version = os.getenv("DEEPSEEK_PRICE_VERSION", "").strip()
        source = _safe_source("DEEPSEEK_PRICE_SOURCE")
        image_tokens = 0
    else:
        input_rate = _decimal("NOTEBOOK_VISION_INPUT_COST_PER_MILLION")
        output_rate = _decimal("NOTEBOOK_VISION_OUTPUT_COST_PER_MILLION")
        version = os.getenv("NOTEBOOK_VISION_PRICE_VERSION", "").strip()
        source = _safe_source("NOTEBOOK_VISION_PRICE_SOURCE")
        try:
            image_tokens = int(os.getenv("NOTEBOOK_VISION_MAX_IMAGE_TOKENS", "0"))
        except ValueError as exc:
            raise ProcessingBudgetError("NOTEBOOK_VISION_MAX_IMAGE_TOKENS 必须是整数") from exc
        if not 1 <= image_tokens <= 100_000:
            raise ProcessingBudgetError("视觉模型每张图片的最大计价 Token 必须配置在 1 至 100000")
    if input_rate <= 0 or output_rate <= 0 or not version:
        raise ProcessingBudgetError(f"{kind} 模型价格、版本号必须完整且价格大于零")
    fx = _decimal("NOTEBOOK_BUDGET_USD_CNY_RATE")
    buffer = _decimal("NOTEBOOK_BUDGET_FX_BUFFER_PERCENT", "25")
    if fx <= 0 or buffer > 200:
        raise ProcessingBudgetError("美元兑人民币汇率必须大于零，安全缓冲须为 0–200%")
    fx_source = _safe_source("NOTEBOOK_BUDGET_FX_RATE_SOURCE")
    fx_as_of = os.getenv("NOTEBOOK_BUDGET_FX_RATE_AS_OF", "").strip()
    try:
        priced_on = date.fromisoformat(fx_as_of)
    except ValueError as exc:
        raise ProcessingBudgetError("必须填写有效的 NOTEBOOK_BUDGET_FX_RATE_AS_OF 日期") from exc
    age = (datetime.now(UTC).date() - priced_on).days
    if age < 0 or age > FX_MAX_AGE_DAYS:
        raise ProcessingBudgetError(f"汇率日期超出有效期（最多 {FX_MAX_AGE_DAYS} 天），请更新价格快照")
    return Tariff(kind, model, input_rate, output_rate, image_tokens, fx, buffer,
                  fx_source, fx_as_of, version, source)


def pricing_status() -> dict[str, Any]:
    result: dict[str, Any] = {"limit_cny": "10.00", "currency": "CNY", "fx_max_age_days": FX_MAX_AGE_DAYS}
    for kind, model, prefix in (
        ("text", os.getenv("DEEPSEEK_MODEL", ""), "DEEPSEEK"),
        ("vision", os.getenv("NOTEBOOK_VISION_MODEL", ""), "NOTEBOOK_VISION"),
    ):
        try:
            tariff = _load_tariff(kind, model)
        except ProcessingBudgetError as exc:
            result[kind] = {"ready": False, "model": model or None, "reason": str(exc)}
        else:
            result[kind] = {"ready": True, "model": model, "tariff_version": tariff.tariff_version,
                            "fx_as_of": tariff.fx_as_of, "fx_buffer_percent": str(tariff.fx_buffer_percent),
                            "input_usd_per_million": str(tariff.input_usd_per_million),
                            "output_usd_per_million": str(tariff.output_usd_per_million),
                            "max_image_tokens": tariff.max_image_tokens,
                            "price_source": tariff.tariff_source,
                            "fx_usd_cny": str(tariff.fx_usd_cny), "fx_source": tariff.fx_source}
    if not result["text"]["ready"]:
        result["text"].update({
            "input_usd_per_million": os.getenv("DEEPSEEK_INPUT_COST_PER_MILLION", ""),
            "output_usd_per_million": os.getenv("DEEPSEEK_OUTPUT_COST_PER_MILLION", ""),
            "tariff_version": os.getenv("DEEPSEEK_PRICE_VERSION", ""),
            "price_source": os.getenv("DEEPSEEK_PRICE_SOURCE", ""),
        })
    if not result["vision"]["ready"]:
        result["vision"].update({
            "input_usd_per_million": os.getenv("NOTEBOOK_VISION_INPUT_COST_PER_MILLION", ""),
            "output_usd_per_million": os.getenv("NOTEBOOK_VISION_OUTPUT_COST_PER_MILLION", ""),
            "max_image_tokens": os.getenv("NOTEBOOK_VISION_MAX_IMAGE_TOKENS", ""),
            "tariff_version": os.getenv("NOTEBOOK_VISION_PRICE_VERSION", ""),
            "price_source": os.getenv("NOTEBOOK_VISION_PRICE_SOURCE", ""),
        })
    result["fx_usd_cny"] = os.getenv("NOTEBOOK_BUDGET_USD_CNY_RATE", "")
    result["fx_source"] = os.getenv("NOTEBOOK_BUDGET_FX_RATE_SOURCE", "")
    result["fx_as_of"] = os.getenv("NOTEBOOK_BUDGET_FX_RATE_AS_OF", "")
    result["fx_buffer_percent"] = os.getenv("NOTEBOOK_BUDGET_FX_BUFFER_PERCENT", "25")
    return result


def ensure_budget_ready(kind: str) -> None:
    model = os.getenv("NOTEBOOK_VISION_MODEL", "") if kind == "vision" else os.getenv("DEEPSEEK_MODEL", "")
    _load_tariff(kind, model.strip())


def _ceil_fen(cny: Decimal) -> int:
    return int((cny * Decimal(100)).to_integral_value(rounding=ROUND_CEILING))


def _quote(tariff: Tariff, *, prompt_upper_tokens: int, max_tokens: int, image_count: int) -> tuple[int, int]:
    prompt = Decimal(max(0, prompt_upper_tokens))
    images = Decimal(max(0, image_count) * tariff.max_image_tokens)
    output = Decimal(max(0, max_tokens))
    usd = ((prompt + images) * tariff.input_usd_per_million
           + output * tariff.output_usd_per_million) / Decimal(1_000_000)
    cny = usd * tariff.fx_usd_cny * (Decimal(1) + tariff.fx_buffer_percent / Decimal(100))
    return _ceil_fen(cny), _ceil_fen((prompt * tariff.input_usd_per_million
                                      + images * tariff.input_usd_per_million
                                      + output * tariff.output_usd_per_million)
                                     / Decimal(1_000_000) * tariff.fx_usd_cny
                                     * (Decimal(1) + tariff.fx_buffer_percent / Decimal(100)))


def _payload_bounds(value: Any) -> tuple[int, int]:
    images = 0

    def strip_image_payload(item: Any) -> Any:
        nonlocal images
        if isinstance(item, list):
            return [strip_image_payload(child) for child in item]
        if isinstance(item, dict):
            if "image_url" in item or item.get("type") in {"input_image", "image"}:
                images += 1
                return {key: "[image]" if key == "image_url" else strip_image_payload(child)
                        for key, child in item.items() if key != "image_url"}
            return {key: strip_image_payload(child) for key, child in item.items()}
        return item

    textual = json.dumps(strip_image_payload(value), ensure_ascii=False, separators=(",", ":"))
    # Byte fallback bounds token count; extra envelope headroom covers provider framing.
    return len(textual.encode("utf-8")) + 512, images


@dataclass(frozen=True)
class BudgetContext:
    asset_ids: tuple[str, ...]
    notebook_id: str
    stage: str
    job_id: str | None
    step_key: str | None
    kind: str

    def with_assets(self, asset_ids: list[str] | tuple[str, ...], *, stage: str | None = None,
                    job_id: str | None = None, step_key: str | None = None,
                    kind: str | None = None) -> BudgetContext:
        return replace(self, asset_ids=tuple(sorted(set(asset_ids))), stage=stage or self.stage,
                       job_id=job_id if job_id is not None else self.job_id,
                       step_key=step_key if step_key is not None else self.step_key,
                       kind=kind or self.kind)


_active_budget: ContextVar[BudgetContext | None] = ContextVar("notebook_file_budget", default=None)


@contextmanager
def processing_budget_scope(*, asset_ids: list[str] | tuple[str, ...], notebook_id: str,
                            stage: str, job_id: str | None = None,
                            step_key: str | None = None, kind: str = "text") -> Iterator[BudgetContext]:
    context = BudgetContext(tuple(sorted(set(asset_ids))), notebook_id, stage, job_id, step_key, kind)
    token = _active_budget.set(context)
    try:
        yield context
    finally:
        _active_budget.reset(token)


@contextmanager
def budget_scope_if_active(*, asset_ids: list[str] | tuple[str, ...], notebook_id: str,
                           stage: str, job_id: str | None = None,
                           step_key: str | None = None, kind: str = "text") -> Iterator[None]:
    """Attach a file ledger around an optional standard-parser vision call."""
    if not asset_ids:
        yield
        return
    with processing_budget_scope(asset_ids=asset_ids, notebook_id=notebook_id,
                                 stage=stage, job_id=job_id, step_key=step_key, kind=kind):
        yield


@contextmanager
def processing_budget_assets(asset_ids: list[str] | tuple[str, ...], *, stage: str | None = None,
                             step_key: str | None = None, kind: str | None = None) -> Iterator[None]:
    current = _active_budget.get()
    if current is None:
        raise ProcessingBudgetError("文件模型调用缺少 Asset 预算归属", code="budget_context_missing")
    token = _active_budget.set(current.with_assets(asset_ids, stage=stage, step_key=step_key, kind=kind))
    try:
        yield
    finally:
        _active_budget.reset(token)


def _reserve(context: BudgetContext, *, provider: str, model: str, messages: Any,
             max_tokens: int) -> dict[str, Any]:
    if not context.asset_ids or not context.notebook_id:
        raise ProcessingBudgetError("文件模型调用缺少 Notebook/Asset 预算归属", code="budget_context_missing")
    tariff = _load_tariff(context.kind, model)
    prompt_tokens, image_count = _payload_bounds(messages)
    reserved_fen, _ = _quote(tariff, prompt_upper_tokens=prompt_tokens,
                             max_tokens=max_tokens, image_count=image_count)
    if reserved_fen <= 0:
        raise ProcessingBudgetError("无法计算本次模型调用的保守费用上界")
    call_id = str(uuid.uuid4())
    now = utc_now()
    fx_json = json.dumps({"usd_cny": str(tariff.fx_usd_cny), "source": tariff.fx_source,
                          "as_of": tariff.fx_as_of, "buffer_percent": str(tariff.fx_buffer_percent)},
                         ensure_ascii=False, sort_keys=True)
    pricing_json = json.dumps({**tariff.snapshot(), "prompt_upper_tokens": prompt_tokens,
                               "image_count": image_count, "max_output_tokens": max_tokens,
                               "shared_request_policy": "full_charge_to_each_asset"},
                              ensure_ascii=False, sort_keys=True)
    with SessionLocal() as db:
        db.execute(insert(FileProcessingBudget).values(
            asset_id=context.asset_ids[0], notebook_id=context.notebook_id,
            limit_fen=BUDGET_LIMIT_FEN, settled_fen=0, reserved_fen=0,
            status="active", currency="CNY", created_at=now, updated_at=now,
        ).on_conflict_do_nothing(index_elements=["asset_id"]))
        for asset_id in context.asset_ids[1:]:
            db.execute(insert(FileProcessingBudget).values(
                asset_id=asset_id, notebook_id=context.notebook_id,
                limit_fen=BUDGET_LIMIT_FEN, settled_fen=0, reserved_fen=0,
                status="active", currency="CNY", created_at=now, updated_at=now,
            ).on_conflict_do_nothing(index_elements=["asset_id"]))
        db.flush()
        exhausted_asset = None
        for asset_id in context.asset_ids:
            budget = db.get(FileProcessingBudget, asset_id)
            if budget is None or budget.notebook_id not in {None, context.notebook_id}:
                db.rollback()
                raise ProcessingBudgetError("文件预算 Notebook 归属不匹配", code="budget_scope_conflict")
            if budget.status != "active":
                db.rollback()
                raise ProcessingBudgetError(
                    f"本文件预算状态为 {budget.status}，已阻止新的付费请求",
                    code="budget_exhausted" if budget.status == "exhausted" else "budget_uncertain",
                )
            result = db.execute(update(FileProcessingBudget).where(
                FileProcessingBudget.asset_id == asset_id,
                FileProcessingBudget.status == "active",
                FileProcessingBudget.limit_fen - FileProcessingBudget.settled_fen
                - FileProcessingBudget.reserved_fen >= reserved_fen,
            ).values(reserved_fen=FileProcessingBudget.reserved_fen + reserved_fen,
                     notebook_id=context.notebook_id, updated_at=now))
            if result.rowcount != 1:
                exhausted_asset = asset_id
                db.rollback()
                break
        if exhausted_asset is not None:
            # Rollback may also have removed a just-created ledger row. Recreate
            # the row before marking it exhausted so repeated attempts stay gated.
            db.execute(insert(FileProcessingBudget).values(
                asset_id=exhausted_asset, notebook_id=context.notebook_id,
                limit_fen=BUDGET_LIMIT_FEN, settled_fen=0, reserved_fen=0,
                status="active", currency="CNY", created_at=now, updated_at=now,
            ).on_conflict_do_nothing(index_elements=["asset_id"]))
            budget = db.get(FileProcessingBudget, exhausted_asset)
            if budget is not None and budget.status == "active":
                db.execute(update(FileProcessingBudget).where(
                    FileProcessingBudget.asset_id == exhausted_asset,
                    FileProcessingBudget.status == "active",
                ).values(status="exhausted", updated_at=now))
            db.commit()
            raise ProcessingBudgetError(
                "已达到本文件 10.00 元预算上限，未发起新的模型请求",
                code="budget_exhausted",
            )
        for asset_id in context.asset_ids:
            db.add(ProviderUsageReservation(
                id=new_id(), call_id=call_id, asset_id=asset_id, notebook_id=context.notebook_id,
                stage=context.stage, job_id=context.job_id, step_key=context.step_key,
                provider=provider, model=model, tariff_version=tariff.tariff_version,
                currency="CNY", fx_snapshot_json=fx_json, pricing_snapshot_json=pricing_json,
                reserved_fen=reserved_fen, state="reserved", created_at=now,
            ))
        db.commit()
    return {"call_id": call_id, "asset_ids": context.asset_ids, "reserved_fen": reserved_fen,
            "tariff": tariff, "prompt_upper_tokens": prompt_tokens, "image_count": image_count,
            "max_tokens": max_tokens, "provider": provider, "model": model}


def _settle(reservation: dict[str, Any], usage: dict[str, int] | None) -> None:
    if (not isinstance(usage, dict) or "prompt_tokens" not in usage
            or "completion_tokens" not in usage):
        _mark_uncertain(reservation, "usage_missing")
        raise ProcessingBudgetError(
            "供应商未返回完整 Token 用量；本次额度已保留并停止后续付费请求",
            code="budget_usage_unknown",
        )
    tariff: Tariff = reservation["tariff"]
    image_token_allowance = reservation["image_count"] * tariff.max_image_tokens
    # Never clamp provider usage down to the reserved input bound: a provider
    # mismatch must increase the booked charge and mark an overrun.
    prompt_tokens = max(0, int(usage["prompt_tokens"]) - image_token_allowance)
    # Image price is reserved and settled at the configured per-image upper bound.
    _, charged_fen = _quote(tariff, prompt_upper_tokens=prompt_tokens,
                            max_tokens=max(0, int(usage["completion_tokens"])),
                            image_count=reservation["image_count"])
    charged_fen = max(1, charged_fen)
    now = utc_now()
    with SessionLocal() as db:
        rows = list(db.scalars(select(ProviderUsageReservation).where(
            ProviderUsageReservation.call_id == reservation["call_id"],
        )).all())
        if not rows or any(row.state != "reserved" for row in rows):
            raise ProcessingBudgetError("模型用量账单状态不一致，已停止处理", code="budget_settlement_conflict")
        overrun = charged_fen > reservation["reserved_fen"]
        for row in rows:
            budget = db.get(FileProcessingBudget, row.asset_id)
            if budget is None:
                raise ProcessingBudgetError("文件预算账本缺失", code="budget_settlement_conflict")
            budget.reserved_fen = max(0, budget.reserved_fen - row.reserved_fen)
            budget.settled_fen += charged_fen
            if overrun or budget.settled_fen + budget.reserved_fen > budget.limit_fen:
                budget.status = "overrun"
                row.state = "overrun"
            else:
                row.state = "settled"
                if budget.settled_fen + budget.reserved_fen >= budget.limit_fen:
                    budget.status = "exhausted"
            budget.updated_at = now
            row.charged_fen = charged_fen
            row.provider_usage_json = json.dumps(usage, ensure_ascii=False, sort_keys=True)
            row.settled_at = now
        db.commit()
    if charged_fen > reservation["reserved_fen"]:
        raise ProcessingBudgetError("供应商 usage 超过调用前保守预留上界，预算已标记超额", code="budget_overrun")


def _mark_uncertain(reservation: dict[str, Any], reason: str) -> None:
    now = utc_now()
    with SessionLocal() as db:
        rows = list(db.scalars(select(ProviderUsageReservation).where(
            ProviderUsageReservation.call_id == reservation["call_id"],
        )).all())
        for row in rows:
            row.state = "uncertain"
            row.provider_usage_json = json.dumps({"uncertainty": reason}, sort_keys=True)
            budget = db.get(FileProcessingBudget, row.asset_id)
            if budget is not None:
                budget.status = "uncertain"
                budget.updated_at = now
        db.commit()


def _mark_pre_dispatch_failure(reservation: dict[str, Any], exc: BaseException) -> None:
    _mark_uncertain(reservation, f"request_failed:{type(exc).__name__}")


class ActiveBudgetGuard:
    def __init__(self, context: BudgetContext) -> None:
        self.context = context

    def before_request(self, *, provider: str, model: str, messages: Any, max_tokens: int) -> dict[str, Any]:
        return _reserve(self.context, provider=provider, model=model, messages=messages,
                        max_tokens=max_tokens)

    def after_response(self, reservation: dict[str, Any], usage: dict[str, int] | None) -> None:
        _settle(reservation, usage)

    def request_failed(self, reservation: dict[str, Any], exc: BaseException) -> None:
        _mark_pre_dispatch_failure(reservation, exc)


def active_budget_guard() -> ActiveBudgetGuard | None:
    context = _active_budget.get()
    return ActiveBudgetGuard(context) if context else None


def budget_read(asset_id: str) -> dict[str, Any] | None:
    with SessionLocal() as db:
        budget = db.get(FileProcessingBudget, asset_id)
        if budget is None:
            return None
        rows = list(db.scalars(select(ProviderUsageReservation).where(
            ProviderUsageReservation.asset_id == asset_id,
        ).order_by(ProviderUsageReservation.created_at)).all())
        return {
            "asset_id": budget.asset_id, "notebook_id": budget.notebook_id,
            "currency": budget.currency, "limit_fen": budget.limit_fen,
            "settled_fen": budget.settled_fen, "reserved_fen": budget.reserved_fen,
            "remaining_fen": max(0, budget.limit_fen - budget.settled_fen - budget.reserved_fen),
            "status": budget.status,
            "reservations": [{
                "call_id": row.call_id, "stage": row.stage, "job_id": row.job_id,
                "step_key": row.step_key, "provider": row.provider, "model": row.model,
                "tariff_version": row.tariff_version, "reserved_fen": row.reserved_fen,
                "charged_fen": row.charged_fen, "state": row.state,
                "created_at": row.created_at, "settled_at": row.settled_at,
            } for row in rows],
        }
