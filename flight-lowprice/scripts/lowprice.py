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

# Candidate domestic leisure destinations: code -> (name, category)
DEST_POOL = {
    "SYX": ("三亚", "海岛"), "HAK": ("海口", "海岛"), "BHY": ("北海", "海岛"),
    "KMG": ("昆明", "山岳"), "DLU": ("大理", "山岳"), "LJG": ("丽江", "山岳"),
    "JHG": ("西双版纳", "山岳"), "JZH": ("九寨沟", "山岳"), "DYG": ("张家界", "山岳"),
    "ENH": ("恩施", "山岳"), "XMN": ("厦门", "古城"),
    "KWL": ("桂林", "山岳"), "NNG": ("南宁", "都市"), "KWE": ("贵阳", "都市"),
    "CTU": ("成都", "都市"), "CKG": ("重庆", "都市"), "XIY": ("西安", "古城"),
    "CSX": ("长沙", "都市"), "WUH": ("武汉", "都市"), "TAO": ("青岛", "海岛"),
    "DLC": ("大连", "海岛"), "HRB": ("哈尔滨", "山岳"), "SHE": ("沈阳", "都市"),
    "BJS": ("北京", "古城"), "SHA": ("上海", "都市"), "CAN": ("广州", "都市"),
    "SZX": ("深圳", "都市"), "HGH": ("杭州", "都市"), "NKG": ("南京", "古城"),
    "TSN": ("天津", "都市"), "CGO": ("郑州", "都市"), "TYN": ("太原", "古城"),
    "TNA": ("济南", "都市"), "FOC": ("福州", "都市"), "JJN": ("泉州", "古城"),
    "WNZ": ("温州", "都市"), "NGB": ("宁波", "都市"), "HFE": ("合肥", "都市"),
    "KHN": ("南昌", "都市"), "LHW": ("兰州", "山岳"), "XNN": ("西宁", "山岳"),
    "URC": ("乌鲁木齐", "山岳"), "LXA": ("拉萨", "山岳"), "HET": ("呼和浩特", "山岳"),
    "INC": ("银川", "古城"), "YNZ": ("扬州", "古城"), "YIH": ("宜昌", "山岳"),
    "LZO": ("泸州", "都市"), "MIG": ("绵阳", "都市"), "ZYI": ("遵义", "古城"),
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
    ap.add_argument("--json", action="store_true", help="output JSON")
    ap.add_argument("--by-date", action="store_true", help="include all quoted dates per route in JSON")
    ap.add_argument("--top", type=int, default=0, help="limit output to top N cheapest")
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
    if not dests:
        ap.error("no destination codes remain")

    start = min(dates)
    results, errors = [], []
    with ThreadPoolExecutor(max_workers=4) as pool:
        futs = {pool.submit(fetch_route, args.depart, d, start, dates): d for d in dests}
        for fut in as_completed(futs):
            r = fut.result()
            (errors if "error" in r else results).append(r)

    results.sort(key=lambda r: (r["price"], r["date"], r["dest"]))
    errors.sort(key=lambda r: r["dest"])
    if args.top:
        results = results[: args.top]
    exit_code = int(len(errors) == len(dests) and all(e["status"] == "request_failed" for e in errors))

    if args.json:
        if not args.by_date:
            for r in results:
                r.pop("prices")
        print(json.dumps({"from": args.depart, "dates": sorted(dates), "checked": len(dests),
                          "routes": results, "errors": errors},
                         ensure_ascii=False, indent=2))
        return exit_code

    name_of = lambda code: DEST_POOL.get(code, (code, ""))[0]
    cat_of = lambda code: DEST_POOL.get(code, ("", ""))[1]
    print(f"\n== {args.depart} 出发 | 候选日期 {', '.join(sorted(dates))} | 含税日历价，以实时页面为准 ==")
    print(f"{'排名':<4}{'目的地':<10}{'类别':<6}{'最低价':>8}  {'日期':<12}")
    for i, r in enumerate(results, 1):
        code = r["dest"]
        print(f"{i:<4}{name_of(code):<10}{cat_of(code):<6}¥{r['price']:<7.0f} {r['date']}")
    if errors:
        print(f"\n[未获报价 {len(errors)}/{len(dests)}] " + ", ".join(
            f"{e['dest']}({e['error']})" for e in errors), file=sys.stderr)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
