import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest


ROOT = Path(__file__).resolve().parents[1]
CHECK = ROOT / "trip-planner/scripts/check_itinerary.py"
EXPORT = ROOT / "travel-to-ics/scripts/build_ics.py"


def event(id, start, end=None, **fields):
    return {"id": id, "title": id, "start": start, **({"end": end} if end else {}), **fields}


class ItineraryWorkflowTest(unittest.TestCase):
    def setUp(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.source = Path(tmp.name) / "itinerary.json"
        self.calendar = Path(tmp.name) / "travel.ics"
        self.plan = {"trip_id": "trip", "calendar": "家庭旅行", "events": []}

    def write_plan(self):
        self.source.write_text(json.dumps(self.plan, ensure_ascii=False), encoding="utf-8")

    def run_cli(self, script, *args):
        return subprocess.run([sys.executable, str(script), str(self.source), *map(str, args)], capture_output=True)

    def check_plan(self, code):
        self.write_plan()
        result = self.run_cli(CHECK)
        self.assertEqual(result.returncode, code, result.stderr)
        return json.loads(result.stdout)

    def test_early_return_flags_airport_transfer_and_invalidates_old_confirmation(self):
        self.plan["events"] = [
            event("checkout", "2027-01-02T09:40+08:00", "2027-01-02T10:00+08:00"),
            event("flight", "2027-01-02T15:00+08:00", alarm_minutes=[180]),
        ]
        self.plan["transfers"] = [{"from": "checkout", "to": "flight", "minutes": 50, "buffer_minutes": 90}]
        old = self.check_plan(0)["sha256"]
        self.plan["events"][1]["start"] = "2027-01-02T12:00+08:00"
        result = self.check_plan(2)
        self.assertEqual([x["code"] for x in result["conflicts"]], ["transfer_too_short"])

        self.plan["events"][0].update(start="2027-01-02T09:00+08:00", end="2027-01-02T09:30+08:00")
        new = self.check_plan(0)["sha256"]
        rejected = self.run_cli(EXPORT, self.calendar, "--expect-sha256", old)
        self.assertNotEqual(rejected.returncode, 0)
        self.assertFalse(self.calendar.exists())
        exported = self.run_cli(EXPORT, self.calendar, "--expect-sha256", new)
        self.assertEqual(exported.returncode, 0, exported.stderr)
        content = self.calendar.read_bytes()
        self.assertIn(b"DTSTART:20270102T040000Z", content)
        self.assertIn(b"TRIGGER:-PT180M", content)
        self.assertNotIn(b"DTSTART:20270102T070000Z", content)

    def test_drive_to_park_checks_walk_to_gate_and_last_entry(self):
        self.plan["events"] = [
            event("parking", "2026-11-14T15:30+08:00", "2026-11-14T15:45+08:00"),
            event("zoo", "2026-11-14T16:05+08:00", last_entry="2026-11-14T16:00+08:00"),
        ]
        self.plan["transfers"] = [{"from": "parking", "to": "zoo", "minutes": 20}]
        result = self.check_plan(2)
        self.assertEqual([x["code"] for x in result["conflicts"]], ["late_entry"])
        self.plan["events"][1]["start"] = "2026-11-14T16:00+08:00"
        result = self.check_plan(2)
        self.assertEqual([x["code"] for x in result["conflicts"]], ["transfer_too_short"])

    def test_unknowns_stay_pending_but_known_cost_can_already_exceed_budget(self):
        self.plan["events"] = [
            event("start", "2026-11-14T09:00+08:00", "2026-11-14T09:10+08:00"),
            event("visit", "2026-11-14T11:00+08:00", last_entry=None),
        ]
        self.plan["transfers"] = [{"from": "start", "to": "visit", "minutes": None}]
        self.plan["budget"] = {
            "currency": "CNY", "limit": 800,
            "costs": [{"label": "酒店房券未核库存", "amount": None}, {"label": "已付机票", "amount": 799.99}],
        }
        result = self.check_plan(0)
        self.assertEqual({x["code"] for x in result["pending"]}, {"transfer_unknown", "entry_unknown", "cost_unknown"})
        self.assertEqual(result["budget"]["known_total"], "799.99")
        self.plan["budget"]["costs"].append({"label": "必付税费", "amount": 0.02})
        result = self.check_plan(2)
        self.assertEqual([x["code"] for x in result["conflicts"]], ["over_budget"])

    def test_overlap_uses_actual_instants_and_ignores_all_day_stay(self):
        self.plan["events"] = [
            event("hotel", "2026-11-14", "2026-11-16"),
            event("visit", "2026-11-14T09:00+08:00", "2026-11-14T10:00+08:00"),
            event("show", "2026-11-14T01:30Z", "2026-11-14T03:00Z"),
        ]
        result = self.check_plan(2)
        self.assertEqual([(x["code"], x["event_ids"]) for x in result["conflicts"]], [("overlap", ["visit", "show"])])
        self.plan["events"][2]["start"] = "2026-11-14T02:00Z"
        self.check_plan(0)

    def test_existing_standalone_calendar_input_still_exports(self):
        self.plan["events"] = [event("hotel", "2026-11-14", "2026-11-16")]
        self.write_plan()
        result = self.run_cli(EXPORT, self.calendar)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(b"DTEND;VALUE=DATE:20261116", self.calendar.read_bytes())


if __name__ == "__main__":
    unittest.main()
