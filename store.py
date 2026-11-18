"""SQLite storage for the review collector. Standard library only."""
from __future__ import annotations

import sqlite3
import threading
from datetime import datetime
from typing import Optional

FMT = "%Y-%m-%d %H:%M"

SCHEMA = """
CREATE TABLE IF NOT EXISTS customers (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  phone TEXT,
  email TEXT,
  visit_at TEXT NOT NULL,
  consent INTEGER NOT NULL CHECK (consent = 1),   -- we only store people who agreed to be contacted
  opted_out INTEGER NOT NULL DEFAULT 0,
  reviewed INTEGER NOT NULL DEFAULT 0,
  created TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS asks (
  customer_id INTEGER NOT NULL,
  n INTEGER NOT NULL,                              -- 1 = first request, 2 = one polite follow-up
  channel TEXT,
  at TEXT NOT NULL,
  status TEXT NOT NULL,                            -- sent | failed
  detail TEXT NOT NULL DEFAULT '',
  PRIMARY KEY (customer_id, n)
);
CREATE TABLE IF NOT EXISTS feedback (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  customer_id INTEGER NOT NULL,
  text TEXT NOT NULL,
  at TEXT NOT NULL
);
"""


class Store:
    def __init__(self, path: str = ":memory:") -> None:
        self.db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.lock = threading.Lock()
        self.db.executescript(SCHEMA)

    def close(self) -> None:
        self.db.close()

    def add(self, name: str, phone: Optional[str], email: Optional[str], visit_at: datetime,
            now: Optional[datetime] = None) -> int:
        with self.lock:
            cur = self.db.execute(
                "INSERT INTO customers(name,phone,email,visit_at,consent,created) VALUES(?,?,?,?,1,?)",
                (name, phone, email, visit_at.strftime(FMT), (now or datetime.now()).strftime(FMT)))
            return cur.lastrowid

    def get(self, cid: int):
        with self.lock:
            return self.db.execute("SELECT * FROM customers WHERE id=?", (cid,)).fetchone()

    def all(self):
        with self.lock:
            return self.db.execute("SELECT * FROM customers ORDER BY visit_at").fetchall()

    def candidates(self):
        """Customers who could still be asked: not opted out, not already reviewed."""
        with self.lock:
            return self.db.execute(
                "SELECT * FROM customers WHERE opted_out=0 AND reviewed=0 ORDER BY visit_at").fetchall()

    def asks_for(self, cid: int):
        with self.lock:
            return self.db.execute("SELECT * FROM asks WHERE customer_id=? ORDER BY n", (cid,)).fetchall()

    def record_ask(self, cid: int, n: int, channel: str, at: datetime, status: str, detail: str = "") -> None:
        with self.lock:
            self.db.execute("INSERT OR REPLACE INTO asks(customer_id,n,channel,at,status,detail) VALUES(?,?,?,?,?,?)",
                            (cid, n, channel, at.strftime(FMT), status, detail[:300]))

    def mark_reviewed(self, cid: int) -> bool:
        with self.lock:
            return self.db.execute("UPDATE customers SET reviewed=1 WHERE id=?", (cid,)).rowcount == 1

    def opt_out(self, key: str) -> int:
        """Opt out by customer id or phone number. Returns how many customers were updated."""
        with self.lock:
            if key.isdigit() and len(key) < 8:
                return self.db.execute("UPDATE customers SET opted_out=1 WHERE id=?", (int(key),)).rowcount
            return self.db.execute("UPDATE customers SET opted_out=1 WHERE phone=? OR email=?",
                                   (key, key)).rowcount

    def add_feedback(self, cid: int, text: str, at: datetime) -> None:
        with self.lock:
            self.db.execute("INSERT INTO feedback(customer_id,text,at) VALUES(?,?,?)",
                            (cid, text, at.strftime(FMT)))

    def feedback(self):
        with self.lock:
            return self.db.execute(
                "SELECT f.*, c.name FROM feedback f JOIN customers c ON c.id=f.customer_id ORDER BY f.at").fetchall()
