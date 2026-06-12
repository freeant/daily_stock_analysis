# -*- coding: utf-8 -*-
"""
Structured sniper price levels for dashboard.battle_plan.sniper_points_struct.

Mirrors sniper_points text fields as machine-readable numbers for downstream
systems (e.g. fmswing). Text sniper_points remain the human-readable source of truth.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Literal, Optional, Tuple, Union

from pydantic import BaseModel, ConfigDict, Field, ValidationError

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1

SNIPER_POINTS_STRUCT_JSON_SNIPPET = """            "sniper_points_struct": {
                "schema_version": 1,
                "applicable": true,
                "not_applicable_reason": null,
                "ideal_buy": {"low": 1.67, "high": 1.68, "basis": "MA5", "condition": "缩量回踩企稳"},
                "secondary_buy": {"low": 1.60, "high": 1.62, "basis": "MA10", "condition": "MA5失守后回踩获得支撑"},
                "stop_loss": {"price": 1.54, "trigger": "intraday_below", "basis": "MA20"},
                "take_profit": {"targets": [1.85, 2.00], "basis": "前高/整数关口"}
            },"""

SNIPER_POINTS_STRUCT_PROMPT_SECTION = """
【结构化狙击点位 sniper_points_struct】
在 battle_plan 中，除现有 sniper_points 四段文字外，必须额外输出 sniper_points_struct 字段，将同样的价位以纯数字形式镜像。规则：

1. 数字一致性（最重要）：sniper_points_struct 中的每一个数字，必须与 sniper_points 对应文字中出现的数字完全一致。不允许在结构化字段里给出文字中没有的新价位，也不允许遗漏文字中的关键价位。先写文字，再照抄数字。

2. applicable 判定：
   - 当前趋势/条件下存在可执行买入点 → applicable=true；
   - 文字结论为「不适用 / 暂无买点 / 严禁买入 / 等待右侧信号」等 → applicable=false，将原因概括到 not_applicable_reason（一句话），ideal_buy 与 secondary_buy 必须为 null。
   - applicable=false 时，若文字中给了持仓者的防守位，仍可输出 stop_loss。

3. 买入区间：ideal_buy / secondary_buy 用 low / high 表示区间，low <= high；文字只给单一价位时 low 与 high 相等。「MA5附近」这类表述，用报告 data_perspective.price_position 中对应均线的数值。basis 填价位锚点（如 MA5 / MA10 / 前低 / 整数关口），condition 填触发条件原文摘要（如「缩量回踩企稳」）。条件描述只放 condition，不得影响数字。

4. 止损：stop_loss.price 为单一数字。文字含「收盘跌破 / 收盘有效跌破」→ trigger=close_below；「跌破即 / 盘中跌破 / 触及即」或未明确 → trigger=intraday_below。文字同时给均线位和整数关口两个止损参考时，取更严格（更高）的那个，basis 注明。

5. 止盈：take_profit.targets 按从低到高排列，最多 3 个；文字给「第一目标 / 第二目标」时全部保留，不得只取第一个。

6. 合理性自检：所有价位必须与 current_price 同一数量级（0.3 倍 ~ 3 倍区间内）；ideal_buy 区间应低于或接近 current_price；stop_loss 必须低于 ideal_buy.low；take_profit 所有目标必须高于 ideal_buy.high。自检不通过时，回头修正文字与数字，而不是输出矛盾数据。

7. 格式：严格按 schema 输出，不增减字段；数字一律为 JSON number（不带引号、不带「元」）；缺失的可选信息用 null，不要用空字符串或 0 占位。

Few-shot A — 可买（多头回踩）：
文字 ideal_buy: "缩量回踩MA5附近1.67-1.68，出现下影线或十字星企稳信号时可轻仓试探"
     stop_loss: "跌破MA20即1.54止损（或1.55整数关口），严格执行"
     take_profit: "第一目标1.85（前高+今日高点），第二目标2.00整数关口"
结构化：applicable=true；ideal_buy 1.67-1.68；stop_loss 1.54 intraday_below MA20；take_profit [1.85, 2.00]。

Few-shot B — 不可买（空头排列）：
文字 ideal_buy: "暂不适用——空头排列严禁买入。等待放量站上MA5(1321)且MA5走平拐头"
结构化：applicable=false，not_applicable_reason 概括原因；ideal_buy/secondary_buy=null；1321 是未来观察位，不得填入 ideal_buy。
"""


class BuyZoneStruct(BaseModel):
    model_config = ConfigDict(extra="forbid")

    low: float = Field(gt=0)
    high: float = Field(gt=0)
    basis: Optional[str] = None
    condition: Optional[str] = None


class StopLossStruct(BaseModel):
    model_config = ConfigDict(extra="forbid")

    price: float = Field(gt=0)
    trigger: Literal["intraday_below", "close_below"]
    basis: Optional[str] = None


class TakeProfitStruct(BaseModel):
    model_config = ConfigDict(extra="forbid")

    targets: List[float] = Field(min_length=1, max_length=3)
    basis: Optional[str] = None


class SniperPointsStruct(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1]
    applicable: bool
    not_applicable_reason: Optional[str] = None
    ideal_buy: Optional[BuyZoneStruct] = None
    secondary_buy: Optional[BuyZoneStruct] = None
    stop_loss: Optional[StopLossStruct] = None
    take_profit: Optional[TakeProfitStruct] = None


def _coerce_positive_float(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        numeric = float(value)
        return numeric if numeric > 0 else None
    if isinstance(value, str):
        text = value.strip().replace(",", "")
        if not text:
            return None
        try:
            numeric = float(text)
        except ValueError:
            return None
        return numeric if numeric > 0 else None
    return None


def extract_current_price(dashboard: Optional[Dict[str, Any]]) -> Optional[float]:
    if not isinstance(dashboard, dict):
        return None
    data_perspective = dashboard.get("data_perspective")
    if not isinstance(data_perspective, dict):
        return None
    price_position = data_perspective.get("price_position")
    if not isinstance(price_position, dict):
        return None
    return _coerce_positive_float(price_position.get("current_price"))


def get_sniper_points_struct(dashboard: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not isinstance(dashboard, dict):
        return None
    battle_plan = dashboard.get("battle_plan")
    if not isinstance(battle_plan, dict):
        return None
    struct = battle_plan.get("sniper_points_struct")
    return struct if isinstance(struct, dict) else None


def strip_sniper_points_struct(dashboard: Optional[Dict[str, Any]]) -> None:
    if not isinstance(dashboard, dict):
        return
    battle_plan = dashboard.get("battle_plan")
    if not isinstance(battle_plan, dict):
        return
    battle_plan.pop("sniper_points_struct", None)


def _collect_price_values(struct: SniperPointsStruct) -> List[float]:
    prices: List[float] = []
    for zone in (struct.ideal_buy, struct.secondary_buy):
        if zone is not None:
            prices.extend([zone.low, zone.high])
    if struct.stop_loss is not None:
        prices.append(struct.stop_loss.price)
    if struct.take_profit is not None:
        prices.extend(struct.take_profit.targets)
    return prices


def _validate_semantics(
    struct: SniperPointsStruct,
    current_price: Optional[float],
) -> List[str]:
    errors: List[str] = []

    if not struct.applicable:
        if struct.ideal_buy is not None:
            errors.append("ideal_buy must be null when applicable=false")
        if struct.secondary_buy is not None:
            errors.append("secondary_buy must be null when applicable=false")
    else:
        if struct.ideal_buy is None:
            errors.append("ideal_buy is required when applicable=true")

    for label, zone in (("ideal_buy", struct.ideal_buy), ("secondary_buy", struct.secondary_buy)):
        if zone is None:
            continue
        if zone.low > zone.high:
            errors.append(f"{label}.low must be <= {label}.high")

    if struct.take_profit is not None:
        targets = struct.take_profit.targets
        if targets != sorted(targets):
            errors.append("take_profit.targets must be sorted ascending")

    if struct.applicable and struct.ideal_buy is not None:
        ideal_low = struct.ideal_buy.low
        ideal_high = struct.ideal_buy.high
        if struct.stop_loss is not None and struct.stop_loss.price >= ideal_low:
            errors.append("stop_loss.price must be below ideal_buy.low")
        if struct.take_profit is not None:
            for index, target in enumerate(struct.take_profit.targets):
                if target <= ideal_high:
                    errors.append(
                        f"take_profit.targets[{index}] must be above ideal_buy.high"
                    )
        if current_price is not None:
            if ideal_high > current_price * 1.05:
                errors.append("ideal_buy.high should be below or near current_price when applicable")

    if current_price is not None and current_price > 0:
        lower_bound = current_price * 0.3
        upper_bound = current_price * 3.0
        for price in _collect_price_values(struct):
            if price < lower_bound or price > upper_bound:
                errors.append(
                    "all prices must be within 0.3x~3x of current_price "
                    f"({current_price})"
                )
                break

    return errors


def validate_sniper_points_struct(
    raw: Any,
    *,
    current_price: Optional[float] = None,
) -> Tuple[bool, List[str]]:
    """Validate schema + semantic rules. Returns (ok, error_messages)."""
    if raw is None:
        return True, []
    if not isinstance(raw, dict):
        return False, ["sniper_points_struct must be an object"]

    try:
        struct = SniperPointsStruct.model_validate(raw)
    except ValidationError as exc:
        return False, [str(exc.errors()[0].get("msg", exc))]

    semantic_errors = _validate_semantics(struct, current_price)
    if semantic_errors:
        return False, semantic_errors
    return True, []


def validate_dashboard_sniper_points_struct(
    dashboard: Optional[Dict[str, Any]],
) -> Tuple[bool, List[str]]:
    struct = get_sniper_points_struct(dashboard)
    if struct is None:
        return True, []
    current_price = extract_current_price(dashboard)
    return validate_sniper_points_struct(struct, current_price=current_price)


def finalize_dashboard_sniper_points_struct(
    dashboard: Optional[Dict[str, Any]],
    *,
    strip_on_failure: bool = True,
) -> Tuple[bool, List[str]]:
    """
    Validate sniper_points_struct on a dashboard dict.

    On failure, strip the field when strip_on_failure=True (downstream text fallback).
    Returns (valid, errors). valid=True when field absent or passes validation.
    """
    ok, errors = validate_dashboard_sniper_points_struct(dashboard)
    if ok:
        return True, []
    if strip_on_failure:
        strip_sniper_points_struct(dashboard)
        logger.warning(
            "[sniper_points_struct] validation failed, field omitted: %s",
            "; ".join(errors),
        )
    return False, errors


def build_sniper_struct_retry_prompt(
    base_prompt: str,
    previous_response: str,
    errors: List[str],
    *,
    report_language: str = "zh",
) -> str:
    error_block = "\n".join(f"- {item}" for item in errors)
    if report_language == "en":
        prefix = (
            "### sniper_points_struct validation failed. Fix the issues below and "
            "return the full JSON again. Keep sniper_points text unchanged unless "
            "you must align numbers:\n"
            f"{error_block}"
        )
    else:
        prefix = (
            "### sniper_points_struct 校验失败。请根据以下问题修正后重新输出完整 JSON。"
            "除为对齐数字所必需外，不要改动 sniper_points 原文：\n"
            f"{error_block}"
        )
    return "\n\n".join([
        base_prompt,
        prefix,
        previous_response.strip(),
    ])
