"""Who to ask, when, and with what words. No network code here.

Design rules (deliberate):
  * Everyone who is asked gets the SAME message with the public review link.
    Sending only happy customers to the review page ("review gating") breaks
    Google's policy and consumer-protection rules, so this tool never does it.
  * Private feedback is offered to everybody, alongside the review link.
  * Consent is required to add a customer, STOP is required in every message,
    and at most two messages are ever sent per customer.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from string import Template
from typing import Callable, Optional

from store import FMT, Store


def parse_dt(text: str) -> datetime:
    t = text.strip().replace("T", " ")
    for fmt in (FMT, "%Y-%m-%d"):
        try:
            return datetime.strptime(t, fmt)
        except ValueError:
            pass
    raise ValueError(f"can't read date/time {text!r}; use 'YYYY-MM-DD HH:MM'")


def clean_text(s: str, limit: int = 80) -> str:
    return re.sub(r"[\x00-\x1f\x7f]", " ", s or "").strip()[:limit]


def normalize_phone(raw: Optional[str], default_cc: str = "91") -> Optional[str]:
    if not raw:
        return None
    d = re.sub(r"\D", "", raw)
    if raw.strip().startswith("00"):
        d = d[2:]
    if len(d) == 10:
        d = default_cc + d
    elif len(d) == 11 and d.startswith("0"):
        d = default_cc + d[1:]
    return d if 11 <= len(d) <= 15 else None


def valid_email(s: Optional[str]) -> bool:
    return bool(s) and re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", s) is not None


def review_link(cfg: dict) -> str:
    """Google's documented 'write a review' link for a business Place ID."""
    pid = cfg.get("google_place_id", "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{10,200}", pid) or "REPLACE" in pid.upper():
        raise ValueError("config.google_place_id is missing or looks wrong "
                         "(find yours with Google's Place ID Finder)")
    return f"https://search.google.com/local/writereview?placeid={pid}"


def check_config(cfg: dict) -> None:
    """Fail early on settings that would make the tool unsafe or useless."""
    review_link(cfg)
    for key in ("first", "followup"):
        t = cfg["templates"].get(key, "")
        if "STOP" not in t:
            raise ValueError(f"templates.{key} must tell people they can reply STOP to opt out")
        if "$link" not in t:
            raise ValueError(f"templates.{key} must include $link, the same review link for everyone")


def in_quiet_hours(now: datetime, cfg: dict) -> bool:
    q = cfg.get("quiet_hours")
    if not q:
        return False
    h1, m1 = map(int, q["start"].split(":"))
    h2, m2 = map(int, q["end"].split(":"))
    start, end, t = time(h1, m1), time(h2, m2), now.time()
    return (start <= t or t < end) if start > end else (start <= t < end)


@dataclass
class Due:
    customer: object
    n: int       # 1 = first ask, 2 = follow-up


def plan(store: Store, cfg: dict, now: datetime) -> list[Due]:
    delay = timedelta(hours=cfg.get("first_delay_hours", 3))
    max_age = timedelta(days=cfg.get("max_age_days", 14))
    gap = timedelta(days=cfg.get("followup_days", 3))
    if in_quiet_hours(now, cfg):
        return []
    out: list[Due] = []
    for c in store.candidates():
        visit = datetime.strptime(c["visit_at"], FMT)
        if now - visit > max_age or now < visit + delay:
            continue
        sent = [a for a in store.asks_for(c["id"]) if a["status"] == "sent"]
        if not sent:
            out.append(Due(c, 1))
        elif len(sent) == 1 and cfg.get("followup_days", 3) and \
                now >= datetime.strptime(sent[0]["at"], FMT) + gap:
            out.append(Due(c, 2))
    return out


SendFn = Callable[[str, object, str], tuple[bool, str]]


def render(cfg: dict, n: int, c) -> str:
    tmpl = cfg["templates"]["first" if n == 1 else "followup"]
    first = c["name"].split()[0] if c["name"].split() else "there"
    return Template(tmpl).safe_substitute(
        first_name=first, business=cfg["business_name"], link=review_link(cfg),
        phone=cfg.get("business_phone", ""))


def run(store: Store, cfg: dict, now: datetime, send: SendFn, dry_run: bool = False) -> dict:
    check_config(cfg)
    res = {"sent": 0, "failed": 0, "preview": []}
    for due in plan(store, cfg, now):
        text = render(cfg, due.n, due.customer)
        if dry_run:
            res["preview"].append((due.customer["id"], due.n, text))
            continue
        ok, channel, detail = False, "", "no usable contact details"
        for ch in cfg.get("channels", ["console"]):
            ok, detail = send(ch, due.customer, text)
            if ok:
                channel = ch
                break
        store.record_ask(due.customer["id"], due.n, channel, now, "sent" if ok else "failed", detail)
        res["sent" if ok else "failed"] += 1
    return res


def report(store: Store) -> dict:
    rows = store.all()
    out = {"customers": len(rows), "asked": 0, "reviewed": 0, "opted_out": 0, "feedback": len(store.feedback()),
           "reviewed_after_ask": 0}
    for r in rows:
        asked = any(a["status"] == "sent" for a in store.asks_for(r["id"]))
        out["asked"] += asked
        out["reviewed"] += r["reviewed"]
        out["opted_out"] += r["opted_out"]
        out["reviewed_after_ask"] += bool(asked and r["reviewed"])
    out["conversion"] = out["reviewed_after_ask"] / out["asked"] if out["asked"] else None
    return out
