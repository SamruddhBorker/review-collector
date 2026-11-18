import copy
import csv
import json
import sqlite3
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

import collect
import engine
from store import Store

CFG = json.loads((Path(__file__).parent / "config.json").read_text(encoding="utf-8"))
CFG["google_place_id"] = "ChIJN1t_tDeuEmsRUsoyG83frY4"   # a made-up-looking id for tests
VISIT = "2026-11-18 13:00"


def at(s):
    return datetime.strptime(s, "%Y-%m-%d %H:%M")


class Sink:
    def __init__(self, ok=True):
        self.sent, self.ok = [], ok

    def __call__(self, channel, c, text):
        self.sent.append((c["id"], text))
        return self.ok, "test"


def store_with(visit=VISIT):
    s = Store()
    cid = s.add("Priya Naik", "919876543210", None, at(visit))
    return s, cid


class ConfigTests(unittest.TestCase):
    def test_link_uses_place_id(self):
        self.assertIn("placeid=ChIJN1t_tDeuEmsRUsoyG83frY4", engine.review_link(CFG))

    def test_placeholder_or_missing_place_id_refused(self):
        with self.assertRaises(ValueError):
            engine.review_link({"google_place_id": "ChIJ_REPLACE_WITH_YOUR_PLACE_ID"})
        with self.assertRaises(ValueError):
            engine.review_link({})
        with self.assertRaises(ValueError):
            engine.review_link({"google_place_id": "bad id!"})

    def test_templates_must_have_stop_and_link(self):
        bad = copy.deepcopy(CFG)
        bad["templates"]["first"] = "Review us: $link"
        with self.assertRaisesRegex(ValueError, "STOP"):
            engine.check_config(bad)
        bad["templates"]["first"] = "Reply STOP to opt out"
        with self.assertRaisesRegex(ValueError, r"\$link"):
            engine.check_config(bad)


class ConsentTests(unittest.TestCase):
    def test_database_itself_refuses_non_consent(self):
        s = Store()
        with self.assertRaises(sqlite3.IntegrityError):
            s.db.execute("INSERT INTO customers(name,phone,visit_at,consent,created) VALUES('x','1','2026-01-01 10:00',0,'x')")

    def test_add_requires_consent_flag(self):
        s = Store()
        with self.assertRaisesRegex(ValueError, "consent"):
            collect.add_one(s, CFG, "Sam", "9876543210", None, VISIT, False)


class SchedulingTests(unittest.TestCase):
    def test_nothing_before_delay(self):
        s, _ = store_with()
        r = engine.run(s, CFG, at("2026-11-18 15:59"), Sink())   # < 3h and also quiet-free
        self.assertEqual(r["sent"], 0)

    def test_first_ask_after_delay_everyone_gets_same_message_with_link(self):
        s = Store()
        ids = [s.add(n, "9198765432%02d" % i, None, at("2026-11-18 11:00")) for i, n in enumerate(["Ann", "Bob"])]
        sink = Sink()
        engine.run(s, CFG, at("2026-11-18 15:00"), sink)
        texts = {t.split(",", 1)[1] for _, t in sink.sent}
        self.assertEqual(len(sink.sent), 2)
        self.assertEqual(len(texts), 1, "message must be identical regardless of the customer")
        self.assertIn("search.google.com/local/writereview", sink.sent[0][1])
        self.assertIn("STOP", sink.sent[0][1])

    def test_exactly_one_followup_then_never_again(self):
        s, cid = store_with("2026-11-18 11:00")
        sink = Sink()
        engine.run(s, CFG, at("2026-11-18 15:00"), sink)       # ask 1
        engine.run(s, CFG, at("2026-11-19 15:00"), sink)       # too soon for follow-up
        self.assertEqual(len(sink.sent), 1)
        engine.run(s, CFG, at("2026-11-21 15:00"), sink)       # 3 days later: follow-up
        self.assertEqual(len(sink.sent), 2)
        engine.run(s, CFG, at("2026-11-25 15:00"), sink)       # never a third
        self.assertEqual(len(sink.sent), 2)

    def test_no_double_send_same_day(self):
        s, _ = store_with("2026-11-18 11:00")
        sink = Sink()
        engine.run(s, CFG, at("2026-11-18 15:00"), sink)
        engine.run(s, CFG, at("2026-11-18 15:30"), sink)
        self.assertEqual(len(sink.sent), 1)

    def test_opted_out_and_reviewed_are_skipped(self):
        s = Store()
        a = s.add("Opt", "919876543210", None, at("2026-11-18 11:00"))
        b = s.add("Done", "919876543211", None, at("2026-11-18 11:00"))
        c = s.add("Keep", "919876543212", None, at("2026-11-18 11:00"))
        self.assertEqual(s.opt_out("919876543210"), 1)
        s.mark_reviewed(b)
        sink = Sink()
        engine.run(s, CFG, at("2026-11-18 15:00"), sink)
        self.assertEqual([i for i, _ in sink.sent], [c])

    def test_optout_by_id_and_email(self):
        s = Store()
        i = s.add("A", None, "a@b.co", at("2026-11-18 11:00"))
        self.assertEqual(s.opt_out(str(i)), 1)
        j = s.add("B", None, "b@b.co", at("2026-11-18 11:00"))
        self.assertEqual(s.opt_out("b@b.co"), 1)
        self.assertEqual(s.opt_out("nobody@x.y"), 0)

    def test_quiet_hours(self):
        s, _ = store_with("2026-11-18 11:00")
        sink = Sink()
        engine.run(s, CFG, at("2026-11-18 21:00"), sink)   # after 20:00
        engine.run(s, CFG, at("2026-11-19 09:00"), sink)   # before 10:00
        self.assertEqual(sink.sent, [])
        engine.run(s, CFG, at("2026-11-19 10:00"), sink)
        self.assertEqual(len(sink.sent), 1)

    def test_too_old_visits_not_contacted(self):
        s, _ = store_with("2026-10-01 11:00")
        sink = Sink()
        engine.run(s, CFG, at("2026-11-18 15:00"), sink)
        self.assertEqual(sink.sent, [])

    def test_failed_send_is_retried(self):
        s, cid = store_with("2026-11-18 11:00")
        engine.run(s, CFG, at("2026-11-18 15:00"), Sink(ok=False))
        good = Sink()
        engine.run(s, CFG, at("2026-11-18 15:30"), good)
        self.assertEqual(len(good.sent), 1)

    def test_dry_run_changes_nothing(self):
        s, cid = store_with("2026-11-18 11:00")
        sink = Sink()
        r = engine.run(s, CFG, at("2026-11-18 15:00"), sink, dry_run=True)
        self.assertEqual(len(r["preview"]), 1)
        self.assertEqual(sink.sent, [])
        self.assertEqual(s.asks_for(cid), [])


class ReportTests(unittest.TestCase):
    def test_conversion(self):
        s = Store()
        ids = [s.add(f"C{i}", f"91987654321{i}", None, at("2026-11-18 11:00")) for i in range(4)]
        engine.run(s, CFG, at("2026-11-18 15:00"), Sink())
        s.mark_reviewed(ids[0])
        s.add_feedback(ids[1], "Slow service", at("2026-11-18 16:00"))
        rep = engine.report(s)
        self.assertEqual((rep["asked"], rep["reviewed_after_ask"], rep["feedback"]), (4, 1, 1))
        self.assertAlmostEqual(rep["conversion"], 0.25)


class CliTests(unittest.TestCase):
    def test_import_rejects_rows_without_consent(self):
        with tempfile.TemporaryDirectory() as t:
            cfg = Path(t) / "c.json"
            cfg.write_text(json.dumps(CFG), encoding="utf-8")
            db = str(Path(t) / "r.db")
            f = Path(t) / "v.csv"
            with open(f, "w", newline="", encoding="utf-8") as fh:
                w = csv.writer(fh)
                w.writerow(["name", "phone", "email", "visit", "consent"])
                w.writerow(["Yes One", "9876543210", "", VISIT, "yes"])
                w.writerow(["No Consent", "9876543211", "", VISIT, "no"])
                w.writerow(["Blank", "9876543212", "", VISIT, ""])
            base = ["--db", db, "--config", str(cfg)]
            self.assertEqual(collect.main(base + ["import", str(f)]), 0)
            s = Store(db)
            self.assertEqual([r["name"] for r in s.all()], ["Yes One"])
            s.close()

    def test_run_refuses_unconfigured_place_id(self):
        with tempfile.TemporaryDirectory() as t:
            self.assertEqual(collect.main(["--db", str(Path(t) / "r.db"), "run", "--dry-run"]), 1)

    def test_add_without_consent_flag_fails(self):
        with tempfile.TemporaryDirectory() as t:
            self.assertEqual(collect.main(["--db", str(Path(t) / "r.db"), "add", "--name", "Sam",
                                           "--phone", "9876543210", "--visit", VISIT]), 1)


if __name__ == "__main__":
    unittest.main()
