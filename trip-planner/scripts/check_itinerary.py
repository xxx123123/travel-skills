"""Check the feasibility of a travel plan before showing it to the traveler."""

import argparse
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
import re


def timestamp(value):
    if isinstance(value, str) and re.fullmatch(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2})?(Z|[+-](?:[01]\d|2[0-3]):[0-5]\d)", value
    ) and not value.endswith("-00:00"):
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    raise ValueError(f"需要带明确 UTC 偏移的时间：{value!r}")


def event_time(value):
    if isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return date.fromisoformat(value)
    return timestamp(value)


def text(obj, key):
    value = obj.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} 必须是非空字符串")
    return value.strip()


def rows(obj, key, *, required=False):
    values = obj.get(key, None if required else [])
    if not isinstance(values, list) or not all(isinstance(row, dict) for row in values):
        raise ValueError(f"{key} 必须是对象数组")
    return values


def amount(value, field):
    if type(value) not in (int, Decimal) or not Decimal(value).is_finite() or value < 0:
        raise ValueError(f"{field} 必须是非负金额")
    return Decimal(value)


def check(plan):
    if not isinstance(plan, dict):
        raise ValueError("行程必须是 JSON 对象")
    text(plan, "calendar")
    text(plan, "trip_id")
    conflicts, pending = [], []

    def add(target, code, message, *event_ids):
        target.append({"code": code, "message": message, "event_ids": list(event_ids)})

    events = {}
    timed = []
    for event in rows(plan, "events", required=True):
        key, title = text(event, "id"), text(event, "title")
        if key in events:
            raise ValueError(f"重复日程 ID：{key}")
        start = event_time(event.get("start"))
        end = event_time(event["end"]) if "end" in event else None
        if end is not None and (type(start) is not type(end) or end <= start):
            raise ValueError(f"{key} 的结束时间必须晚于开始，且使用同一种时间格式")
        events[key] = (title, start, end)
        if isinstance(start, datetime):
            timed.append((start, key, end))
        if "last_entry" in event:
            cutoff = event["last_entry"]
            if cutoff is None or not isinstance(start, datetime):
                add(pending, "entry_unknown", f"待核实「{title}」到达时间或最后入场时间", key)
            elif start > timestamp(cutoff):
                add(conflicts, "late_entry", f"「{title}」的到达时间已过最后入场", key)
    if not events:
        raise ValueError("events 至少需要一个日程")

    # At equal starts, check occupied intervals before milestones. Adjacent intervals may touch.
    timed.sort(key=lambda item: (item[0], item[2] is None, item[1]))
    for i, (start, key, end) in enumerate(timed):
        if end is None:
            continue
        for j in range(i + 1, len(timed)):
            next_start, next_key, next_end = timed[j]
            if next_start >= end:
                break
            if next_start == start and next_end is None:
                continue
            add(conflicts, "overlap", f"「{events[key][0]}」与「{events[next_key][0]}」时间重叠", key, next_key)

    pairs = set()
    for leg in rows(plan, "transfers"):
        a, b = text(leg, "from"), text(leg, "to")
        if a == b or a not in events or b not in events or (a, b) in pairs:
            raise ValueError(f"无效或重复的交通段：{a} → {b}")
        pairs.add((a, b))
        source, source_start, source_end = events[a]
        target, target_start, _ = events[b]
        minutes = leg.get("minutes")
        buffer = leg.get("buffer_minutes", 0)
        for field, value in (("minutes", minutes), ("buffer_minutes", buffer)):
            if value is not None and (type(value) is not int or value < 0):
                raise ValueError(f"{a} → {b} 的 {field} 必须是非负整数或 null")
        label = f"「{source}」→「{target}」"
        if isinstance(source_start, datetime) and isinstance(target_start, datetime):
            earliest = source_end if source_end is not None else source_start
            available = (target_start - earliest).total_seconds()
            lower_bound = ((minutes or 0) + (buffer or 0)) * 60
            if available < lower_bound:
                add(conflicts, "transfer_too_short", f"{label} 至少差 {timedelta(seconds=lower_bound - available)}", a, b)
                continue
        if minutes is None or buffer is None or not isinstance(source_end, datetime) or not isinstance(target_start, datetime):
            add(pending, "transfer_unknown", f"待核实 {label} 的出发时间、到达时间或交通与缓冲", a, b)

    budget_summary = None
    if "budget" in plan:
        budget = plan["budget"]
        if not isinstance(budget, dict):
            raise ValueError("budget 必须是对象")
        currency = text(budget, "currency")
        limit = amount(budget.get("limit"), "budget.limit")
        costs = rows(budget, "costs", required=True)
        if not costs:
            raise ValueError("budget.costs 至少需要一个费用项")
        known = Decimal(0)
        unknown = []
        for cost in costs:
            label = text(cost, "label")
            if cost.get("amount") is None:
                unknown.append(label)
            else:
                known += amount(cost["amount"], f"{label} 的费用")
        budget_summary = {"currency": currency, "limit": str(limit), "known_total": str(known), "unknown": unknown}
        if known > limit:
            add(conflicts, "over_budget", f"已知必付费用 {known} {currency} 超出硬预算 {limit} {currency}")
        if unknown:
            add(pending, "cost_unknown", "待核实必付费用：" + "、".join(unknown))

    return {"conflicts": conflicts, "pending": pending, "budget": budget_summary}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    args = parser.parse_args()
    try:
        raw = args.input.read_bytes()
        result = check(json.loads(raw.decode("utf-8-sig"), parse_float=Decimal))
        result["sha256"] = sha256(raw).hexdigest()
        # Escape the JSON on non-UTF-8 consoles as well, including Windows redirected output.
        print(json.dumps(result, indent=2))
    except (OSError, ValueError, OverflowError) as error:
        parser.exit(1, f"error: {error}\n")
    return 2 if result["conflicts"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
