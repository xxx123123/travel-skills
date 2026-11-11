"""Build a travel calendar from UTF-8 JSON. Python 3.10+, standard library only."""
import argparse
from datetime import date, datetime, timezone
import json
from pathlib import Path
import re
import uuid


def required(obj, key):
    value = obj.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} must be a non-empty string")
    return value.strip()


def escape(value):
    if not isinstance(value, str) or re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", value):
        raise ValueError("calendar text must be a string without control characters")
    return (value.replace("\\", "\\\\").replace("\r\n", "\n").replace("\r", "\n")
            .replace("\n", "\\n").replace(";", "\\;").replace(",", "\\,"))


def parse_time(value):
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return date.fromisoformat(value)
    match = re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2})?(Z|[+-](?:[01]\d|2[0-3]):[0-5]\d)", value)
    if match and match[1] != "-00:00":
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    raise ValueError("use YYYY-MM-DD or an ISO timestamp with a known UTC offset")


def stamp(value):
    return value.isoformat(timespec="seconds").replace("-", "").replace(":", "").removesuffix("+0000") + "Z"


def time_line(key, value):
    if isinstance(value, datetime):
        return key + ":" + stamp(value)
    return key + ";VALUE=DATE:" + value.isoformat().replace("-", "")


def fold(line):
    current = bytearray()
    parts = []
    for char in line:
        chunk = char.encode("utf-8")
        if len(current) + len(chunk) > 75:
            parts.append(bytes(current))
            current = bytearray(b" ")
        current.extend(chunk)
    parts.append(bytes(current))
    return b"\r\n".join(parts)


def build(spec):
    if not isinstance(spec, dict):
        raise ValueError("input must be a JSON object")
    name, trip_id = required(spec, "calendar"), required(spec, "trip_id")
    events = spec.get("events")
    if not isinstance(events, list) or not events:
        raise ValueError("events must be a non-empty array")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//travel-skills//travel-to-ics//EN",
             "CALSCALE:GREGORIAN", "X-WR-CALNAME:" + escape(name)]
    dtstamp = stamp(datetime.now(timezone.utc))
    seen, count = set(), 0
    namespace = uuid.uuid5(uuid.NAMESPACE_URL, "travel-skills/travel-to-ics/" + trip_id)
    for index, event in enumerate(events, 1):
        try:
            if not isinstance(event, dict):
                raise ValueError("expected an object")
            event_id, title = required(event, "id"), required(event, "title")
            if event_id in seen:
                raise ValueError("duplicate event id: " + event_id)
            seen.add(event_id)
            start = parse_time(required(event, "start"))
            end = parse_time(required(event, "end")) if "end" in event else None
            if end is not None and (type(start) is not type(end) or end <= start):
                raise ValueError("end must be after start and use the same date/time type")
            tentative = event.get("tentative", False)
            if not isinstance(tentative, bool):
                raise ValueError("tentative must be true or false")
            alarms = event.get("alarm_minutes", [])
            if not isinstance(alarms, list) or any(type(n) is not int or n < 0 for n in alarms):
                raise ValueError("alarm_minutes must be an array of non-negative integers")
            uid = f"{uuid.uuid5(namespace, event_id)}@travel-to-ics"
            lines += ["BEGIN:VEVENT", "UID:" + uid, "DTSTAMP:" + dtstamp,
                      time_line("DTSTART", start), "SUMMARY:" + escape(title)]
            if end is not None:
                lines.append(time_line("DTEND", end))
            for field, prop in (("location", "LOCATION"), ("notes", "DESCRIPTION")):
                if field in event:
                    lines.append(prop + ":" + escape(event[field]))
            if tentative:
                lines.append("STATUS:TENTATIVE")
            for minutes in dict.fromkeys(alarms):
                trigger = f"-PT{minutes}M" if minutes else "PT0M"
                lines += ["BEGIN:VALARM", "ACTION:DISPLAY", "TRIGGER:" + trigger,
                          "DESCRIPTION:" + escape(title), "END:VALARM"]
                count += 1
            lines.append("END:VEVENT")
        except (ValueError, OverflowError) as error:
            raise ValueError(f"events[{index}]: {error}") from error
    lines.append("END:VCALENDAR")
    return b"\r\n".join(map(fold, lines)) + b"\r\n", len(events), count


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    if args.output.suffix.lower() != ".ics" or args.input.resolve() == args.output.resolve():
        parser.error("output must be a separate .ics file")
    try:
        spec = json.loads(args.input.read_text(encoding="utf-8-sig"))
        content, events, alarms = build(spec)
        args.output.write_bytes(content)
    except (ValueError, OSError, OverflowError) as error:
        parser.exit(1, f"error: {error}\n")
    print(f"Wrote {events} events and {alarms} alarms to {args.output}")


if __name__ == "__main__":
    main()
