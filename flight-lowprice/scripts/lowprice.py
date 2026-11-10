#!/usr/bin/env python3
"""flight-lowprice: batch query Ctrip lowest-price calendar for candidate routes.

Queries POST https://m.ctrip.com/restapi/soa2/15380/bjjson/FlightIntlAndInlandLowestPriceSearch
for departure x destinations, filters candidate departure dates, prints cheapest routes.

Usage:
  python lowprice.py --from SHA --dates 2026-11-14,2026-11-15
  python lowprice.py --from SHA --dates 2026-11-14 --dests SYX,KMG --json
"""
import argparse
import datetime as dt
import http.client
import json
import math
import re
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

API = "https://m.ctrip.com/restapi/soa2/15380/bjjson/FlightIntlAndInlandLowestPriceSearch"
CHINA_TIME = dt.timezone(dt.timedelta(hours=8))

# Candidate cities by geographic region: (code, city name, travel category).
REGIONS = {
    "东北": (
        ("DLC", "大连", "海岛"), ("HRB", "哈尔滨", "山岳"), ("SHE", "沈阳", "都市"),
    ),
    "华北": (
        ("BJS", "北京", "古城"), ("TSN", "天津", "都市"), ("TYN", "太原", "古城"),
        ("HET", "呼和浩特", "山岳"),
    ),
    "华东": (
        ("SHA", "上海", "都市"), ("XMN", "厦门", "古城"), ("TAO", "青岛", "海岛"),
        ("HGH", "杭州", "都市"), ("NKG", "南京", "古城"), ("TNA", "济南", "都市"),
        ("FOC", "福州", "都市"), ("JJN", "泉州", "古城"), ("WNZ", "温州", "都市"),
        ("NGB", "宁波", "都市"), ("HFE", "合肥", "都市"), ("KHN", "南昌", "都市"),
        ("YNZ", "扬州", "古城"),
    ),
    "华中": (
        ("DYG", "张家界", "山岳"), ("ENH", "恩施", "山岳"), ("CSX", "长沙", "都市"),
        ("WUH", "武汉", "都市"), ("CGO", "郑州", "都市"), ("YIH", "宜昌", "山岳"),
    ),
    "华南": (
        ("SYX", "三亚", "海岛"), ("HAK", "海口", "海岛"), ("BHY", "北海", "海岛"),
        ("KWL", "桂林", "山岳"), ("NNG", "南宁", "都市"), ("CAN", "广州", "都市"),
        ("SZX", "深圳", "都市"),
    ),
    "西南": (
        ("KMG", "昆明", "山岳"), ("DLU", "大理", "山岳"), ("LJG", "丽江", "山岳"),
        ("JHG", "西双版纳", "山岳"), ("JZH", "九寨沟", "山岳"), ("KWE", "贵阳", "都市"),
        ("CTU", "成都", "都市"), ("CKG", "重庆", "都市"), ("LXA", "拉萨", "山岳"),
        ("LZO", "泸州", "都市"), ("MIG", "绵阳", "都市"), ("ZYI", "遵义", "古城"),
    ),
    "西北": (
        ("XIY", "西安", "古城"), ("LHW", "兰州", "山岳"), ("XNN", "西宁", "山岳"),
        ("URC", "乌鲁木齐", "山岳"), ("INC", "银川", "古城"),
    ),
}
DEST_POOL = {
    code: (city, category, region)
    for region, cities in REGIONS.items()
    for code, city, category in cities
}

HEADERS = {
    "Content-Type": "application/json",
    "Accept": "*/*",
    "Origin": "https://flights.ctrip.com",
    "Referer": "https://flights.ctrip.com/",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    ),
}


def build_payload(depart: str, arrive: str, start_date: str) -> dict:
    return {
        "departNewCityCode": depart,
        "arriveNewCityCode": arrive,
        "startDate": start_date,
        "grade": 1,
        "flag": 0,
        "channelName": "FlightOnline",
        "searchType": 1,
        "passengerList": [{"passengercount": 1, "passengertype": "Adult"}],
        "calendarSelections": [{"selectionType": 8, "selectionContent": ["1"]}],
    }


def parse_dotnet_date(value):
    if not isinstance(value, str):
        return None
    m = re.fullmatch(r"/Date\((-?\d+)(?:[+-]\d{4})?\)/", value)
    if not m:
        return None
    try:
        return dt.datetime.fromtimestamp(int(m.group(1)) / 1000, CHINA_TIME).date().isoformat()
    except (OverflowError, ValueError, OSError):
        return None


def route_error(arrive, status, error):
    return {"dest": arrive, "status": status, "error": error}


def fetch_route(depart: str, arrive: str, start_date: str, dates: set) -> dict:
    payload = json.dumps(build_payload(depart, arrive, start_date)).encode("utf-8")
    req = urllib.request.Request(API, data=payload, headers=HEADERS, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return route_error(arrive, "request_failed", f"HTTP {exc.code}")
    except (OSError, http.client.HTTPException) as exc:
        return route_error(arrive, "request_failed", f"{type(exc).__name__}: {exc}")
    except (UnicodeDecodeError, json.JSONDecodeError):
        return route_error(arrive, "request_failed", "invalid JSON response")

    status = body.get("responseStatus") if isinstance(body, dict) else None
    ack = status.get("Ack") if isinstance(status, dict) else None
    if ack != "Success":
        return route_error(arrive, "request_failed", f"Ack={ack}")
    items = body.get("priceList")
    if items is not None and not isinstance(items, list):
        return route_error(arrive, "request_failed", "invalid priceList response")

    by_date = {}
    for item in items or []:
        if not isinstance(item, dict):
            continue
        d = parse_dotnet_date(item.get("departDate"))
        total = item.get("totalPrice")
        if d not in dates or type(total) not in (int, float) or not (0 < total < math.inf):
            continue
        if d not in by_date or total < by_date[d]["price"]:
            by_date[d] = {"date": d, "price": total, "fare": item.get("price")}
    if not by_date:
        return route_error(arrive, "no_quote", "no price in window")
    prices = [by_date[d] for d in sorted(by_date)]
    best = min(prices, key=lambda row: row["price"])
    return {"dest": arrive, **best, "prices": prices}


def csv_values(value):
    return [part.strip() for part in value.split(",") if part.strip()]


def city_code(value):
    code = value.strip().upper()
    if not re.fullmatch(r"[A-Z]{3}", code):
        raise argparse.ArgumentTypeError(f"invalid city code: {value!r}")
    return code


def price_limit(value):
    try:
        price = float(value)
    except ValueError:
        raise argparse.ArgumentTypeError("expected a positive price in CNY")
    if not math.isfinite(price) or price <= 0:
        raise argparse.ArgumentTypeError("expected a positive price in CNY")
    return price


def destination_info(code):
    city, category, region = DEST_POOL.get(code, (code, "", "未分类"))
    return {"city": city, "category": category, "region": region}


def print_table(routes):
    print(f"{'排名':<4}{'目的地':<10}{'类别':<6}{'最低价':>8}  {'日期':<12}")
    for i, r in enumerate(routes, 1):
        price = f"¥{r['price']:g}"
        print(f"{i:<4}{r['city']:<10}{r['category']:<6}{price:<8} {r['date']}")


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="depart", required=True, type=city_code, help="departure city code")
    ap.add_argument("--dates", required=True, help="comma-separated candidate departure dates YYYY-MM-DD")
    ap.add_argument("--dests", help="replace the default pool with these comma-separated codes")
    ap.add_argument("--add-dests", default="", help="add comma-separated codes to the candidate pool")
    ap.add_argument("--exclude-dests", default="", help="remove comma-separated codes from the candidate pool")
    ap.add_argument("--region", help="comma-separated regions: " + ", ".join(REGIONS))
    ap.add_argument("--group-by-region", action="store_true", help="group matching results by region")
    budget_args = ap.add_mutually_exclusive_group()
    budget_args.add_argument("--max-price", type=price_limit, help="inclusive one-way total price limit, in CNY")
    budget_args.add_argument("--under-price", type=price_limit, help="exclusive one-way total price limit, in CNY")
    ap.add_argument("--json", action="store_true", help="output JSON")
    ap.add_argument("--by-date", action="store_true", help="include matching quoted dates per route in JSON")
    ap.add_argument("--top", type=int, default=0, help="limit output to top N cheapest across all regions")
    args = ap.parse_args()

    if args.top < 0:
        ap.error("--top must be non-negative")
    if args.by_date and not args.json:
        ap.error("--by-date requires --json")
    dates = set(csv_values(args.dates))
    if not dates:
        ap.error("--dates must contain at least one date")
    for date in sorted(dates):
        try:
            if dt.date.fromisoformat(date).isoformat() != date:
                raise ValueError
        except ValueError:
            ap.error(f"invalid date {date!r}; expected YYYY-MM-DD")

    try:
        dests = list(DEST_POOL) if args.dests is None else [city_code(d) for d in csv_values(args.dests)]
        dests.extend(city_code(d) for d in csv_values(args.add_dests))
        excluded = {args.depart, *(city_code(d) for d in csv_values(args.exclude_dests))}
    except argparse.ArgumentTypeError as exc:
        ap.error(str(exc))
    dests = [d for d in dict.fromkeys(dests) if d not in excluded]
    if args.region is not None:
        regions = set(csv_values(args.region.replace("，", ",").replace("、", ",")))
        if not regions or regions - REGIONS.keys():
            ap.error("choose one or more regions from: " + ", ".join(REGIONS))
        dests = [d for d in dests if destination_info(d)["region"] in regions]
    if not dests:
        ap.error("no destination codes remain")

    budget = None
    if args.max_price is not None:
        budget = {"limit": args.max_price, "inclusive": True}
    elif args.under_price is not None:
        budget = {"limit": args.under_price, "inclusive": False}

    def within_budget(price):
        if budget is None:
            return True
        return price < budget["limit"] or (budget["inclusive"] and price == budget["limit"])

    start = min(dates)
    results, errors = [], []
    with ThreadPoolExecutor(max_workers=4) as pool:
        futs = {pool.submit(fetch_route, args.depart, d, start, dates): d for d in dests}
        for fut in as_completed(futs):
            r = fut.result()
            (errors if "error" in r else results).append(r)

    quoted = len(results)
    results = [r for r in results if within_budget(r["price"])]
    for r in results:
        r.update(destination_info(r["dest"]))
        if args.by_date:
            r["prices"] = [p for p in r["prices"] if within_budget(p["price"])]
        else:
            del r["prices"]
    results.sort(key=lambda r: (r["price"], r["date"], r["dest"]))
    errors.sort(key=lambda r: r["dest"])
    matched = len(results)
    if args.top:
        results = results[: args.top]
    exit_code = int(len(errors) == len(dests) and all(e["status"] == "request_failed" for e in errors))

    groups = {}
    if args.group_by_region:
        for r in results:
            groups.setdefault(r["region"], []).append(r)

    if args.json:
        data = {"from": args.depart, "dates": sorted(dates), "checked": len(dests),
                "quoted": quoted, "matched": matched, "routes": results, "errors": errors}
        if budget is not None:
            data["budget"] = budget
        if args.group_by_region:
            data["groups"] = {region: [r["dest"] for r in rows] for region, rows in groups.items()}
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return exit_code

    print(f"\n== {args.depart} 出发 | 候选日期 {', '.join(sorted(dates))} | 含税日历价，以实时页面为准 ==")
    print(f"查询 {len(dests)} 条｜有报价 {quoted} 条｜符合条件 {matched} 条｜展示 {len(results)} 条")
    if budget is not None:
        operator = "≤" if budget["inclusive"] else "<"
        print(f"预算：单程 {operator} ¥{budget['limit']:g}")
    if not results:
        print("有报价的航线均超出预算。" if quoted else "没有取得日历报价。")
    elif args.group_by_region:
        for region, rows in groups.items():
            print(f"\n{region}")
            print_table(rows)
    else:
        print_table(results)
    if errors:
        print(f"\n[未获报价 {len(errors)}/{len(dests)}] " + ", ".join(
            f"{e['dest']}({e['error']})" for e in errors), file=sys.stderr)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
