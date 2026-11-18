#!/usr/bin/env python3
"""review-collector: ask happy customers for honest Google reviews, politely and legally.

    python collect.py add --name "Priya Naik" --phone 98765 43210 --visit "2026-11-18 13:00" --consent
    python collect.py import visits.csv       # name,phone,email,visit,consent  (consent must be yes)
    python collect.py run --dry-run           # preview who would be messaged right now
    python collect.py run                     # send (schedule every 30 min)
    python collect.py reviewed 3              # they left a review: stop asking
    python collect.py optout 919876543210     # they replied STOP (by phone, email or id)
    python collect.py feedback 3 "Service was slow"   # log private feedback
    python collect.py report

Everyone gets the same public review link. No review gating. See README.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime
from pathlib import Path

import engine
import senders
from store import Store

HERE = Path(__file__).parent


def add_one(store: Store, cfg: dict, name: str, phone, email, visit: str, consent: bool) -> int:
    if not consent:
        raise ValueError("consent is required: only add customers who agreed to be contacted")
    name = engine.clean_text(name)
    if not name:
        raise ValueError("name is required")
    phone_n = engine.normalize_phone(phone, cfg.get("default_country_code", "91")) if phone else None
    if phone and not phone_n:
        raise ValueError(f"can't use phone number {phone!r}")
    if email and not engine.valid_email(email):
        raise ValueError(f"can't use email {email!r}")
    if not phone_n and not email:
        raise ValueError("need a phone number or an email")
    return store.add(name, phone_n, email or None, engine.parse_dt(visit))


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):  # piped output on Windows defaults to cp1252
        if not stream.isatty():
            stream.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default="reviews.db")
    ap.add_argument("--config", default=str(HERE / "config.json"))
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add")
    a.add_argument("--name", required=True)
    a.add_argument("--phone", nargs="+")
    a.add_argument("--email")
    a.add_argument("--visit", required=True, help="'YYYY-MM-DD HH:MM'")
    a.add_argument("--consent", action="store_true", help="they agreed to be contacted (required)")
    sub.add_parser("import").add_argument("csv_file")
    r = sub.add_parser("run")
    r.add_argument("--dry-run", action="store_true")
    r.add_argument("--now")
    sub.add_parser("reviewed").add_argument("id", type=int)
    sub.add_parser("optout").add_argument("key", help="customer id, phone number or email")
    f = sub.add_parser("feedback")
    f.add_argument("id", type=int)
    f.add_argument("text")
    sub.add_parser("report")
    args = ap.parse_args(argv)

    senders.load_env(HERE / ".env")
    store = Store(args.db)
    try:
        cfg = json.loads(Path(args.config).read_text(encoding="utf-8"))
        if args.cmd == "add":
            phone = " ".join(args.phone) if args.phone else None
            print(f"added #{add_one(store, cfg, args.name, phone, args.email, args.visit, args.consent)}")
        elif args.cmd == "import":
            ok = bad = 0
            with open(args.csv_file, newline="", encoding="utf-8-sig") as fh:
                for n, row in enumerate(csv.DictReader(fh), start=2):
                    row = {(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}
                    try:
                        add_one(store, cfg, row.get("name", ""), row.get("phone"), row.get("email"),
                                row.get("visit", ""), row.get("consent", "").lower() in ("yes", "y", "true", "1"))
                        ok += 1
                    except ValueError as e:
                        bad += 1
                        print(f"line {n}: {e}", file=sys.stderr)
            print(f"imported {ok}, rejected {bad}")
        elif args.cmd == "run":
            now = engine.parse_dt(args.now) if args.now else datetime.now()
            res = engine.run(store, cfg, now, lambda ch, c, t: senders.send(ch, c, t, cfg), args.dry_run)
            for cid, n, text in res["preview"]:
                print(f"[would send #{cid}, message {n}]\n{text}\n")
            print(f"sent={res['sent']} failed={res['failed']}" +
                  (f" would_send={len(res['preview'])}" if args.dry_run else ""))
        elif args.cmd == "reviewed":
            print("updated" if store.mark_reviewed(args.id) else "no such customer")
        elif args.cmd == "optout":
            n = store.opt_out(args.key)
            print(f"opted out {n} customer(s)" if n else "no match")
        elif args.cmd == "feedback":
            if not store.get(args.id):
                raise ValueError("no such customer")
            store.add_feedback(args.id, engine.clean_text(args.text, 1000), datetime.now())
            print("saved")
        elif args.cmd == "report":
            rep = engine.report(store)
            conv = f"{rep['conversion']:.0%}" if rep["conversion"] is not None else "n/a"
            print(f"customers {rep['customers']} | asked {rep['asked']} | reviewed {rep['reviewed']} | "
                  f"opted out {rep['opted_out']} | private feedback {rep['feedback']}")
            print(f"review rate among people asked: {conv}")
            for fb in store.feedback():
                print(f"  feedback from {fb['name']}: {fb['text']}")
    except (ValueError, OSError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    finally:
        store.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
