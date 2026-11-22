"""SQLite ledger with customer profiles, payment safeguards and audit history.

Schema changes are additive. Existing entries are never deleted or rewritten.
"""
import csv
import difflib
import io
import math
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

DB_PATH = Path(__file__).with_name("ledger.db")
SEED = [("Ramesh", 500, "credit"), ("Ramesh", 50, "payment"),
        ("Suresh", 120, "credit"), ("Lakshmi", 800, "credit"),
        ("Mohan", 300, "credit"), ("Mohan", 300, "payment"), ("Ramu", 90, "credit")]


@contextmanager
def _conn():
    c = sqlite3.connect(DB_PATH, timeout=10)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys=ON")
    try:
        yield c
        c.commit()
    except Exception:
        c.rollback()
        raise
    finally:
        c.close()


def init(seed=False):
    """Create missing tables only; never seed or reset an existing ledger."""
    with _conn() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS entries(
            id INTEGER PRIMARY KEY AUTOINCREMENT, person TEXT NOT NULL,
            amount REAL NOT NULL CHECK(amount > 0),
            entry_type TEXT NOT NULL CHECK(entry_type IN ('credit','payment')),
            note TEXT DEFAULT '', ts REAL NOT NULL)""")
        c.execute("""CREATE TABLE IF NOT EXISTS customer_profiles(
            person TEXT PRIMARY KEY COLLATE NOCASE, phone TEXT NOT NULL DEFAULT '',
            notes TEXT NOT NULL DEFAULT '', updated_at REAL NOT NULL)""")
        c.execute("""CREATE TABLE IF NOT EXISTS audit_log(
            id INTEGER PRIMARY KEY AUTOINCREMENT, action TEXT NOT NULL,
            entry_id INTEGER, person TEXT, details TEXT NOT NULL DEFAULT '', ts REAL NOT NULL)""")
        # Migrate old entries tables without changing any existing rows.
        cols = {r[1] for r in c.execute("PRAGMA table_info(entries)")}
        if "reverses_id" not in cols:
            c.execute("ALTER TABLE entries ADD COLUMN reverses_id INTEGER")
        c.execute("CREATE INDEX IF NOT EXISTS idx_entries_person_id ON entries(person, id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_entries_ts ON entries(ts)")


def reset():
    raise RuntimeError("Reset is disabled to protect ledger records. Use an explicit database backup workflow.")


def customers():
    with _conn() as c:
        rows = c.execute("SELECT person FROM customer_profiles UNION SELECT DISTINCT person FROM entries ORDER BY person COLLATE NOCASE").fetchall()
    return [r[0] for r in rows]


def canonical(name):
    name = (name or "").strip()
    if not name: return None
    existing = customers()
    lower = {p.casefold(): p for p in existing}
    if name.casefold() in lower: return lower[name.casefold()]
    close = difflib.get_close_matches(name.casefold(), list(lower), n=1, cutoff=.9)
    return lower[close[0]] if close else None


def add_entry(person, amount, entry_type, note=""):
    person = (person or "").strip()
    amount = float(amount)
    if not person or not math.isfinite(amount) or not amount > 0 or entry_type not in ("credit", "payment"):
        raise ValueError("Enter a customer, a positive amount, and a valid transaction type.")
    with _conn() as c:
        c.execute("BEGIN IMMEDIATE")
        bal = c.execute("SELECT COALESCE(SUM(CASE entry_type WHEN 'credit' THEN amount ELSE -amount END),0) FROM entries WHERE person=?", (person,)).fetchone()[0]
        if entry_type == "payment" and amount > bal + 1e-9:
            raise ValueError(f"Payment exceeds {person}'s outstanding balance of ₹{max(0, bal):,.2f}.")
        now = time.time()
        cur = c.execute("INSERT INTO entries(person,amount,entry_type,note,ts) VALUES(?,?,?,?,?)", (person, amount, entry_type, (note or "").strip(), now))
        c.execute("INSERT OR IGNORE INTO customer_profiles(person,updated_at) VALUES(?,?)", (person, now))
        c.execute("INSERT INTO audit_log(action,entry_id,person,details,ts) VALUES('add',?,?,?,?)", (cur.lastrowid, person, f"{entry_type} ₹{amount:.2f}; {(note or '').strip()}", now))
        return cur.lastrowid


def balance(person):
    with _conn() as c:
        return c.execute("SELECT COALESCE(SUM(CASE entry_type WHEN 'credit' THEN amount ELSE -amount END),0) FROM entries WHERE person=?", (person,)).fetchone()[0]


def balances():
    with _conn() as c:
        rows = c.execute("SELECT person,SUM(CASE entry_type WHEN 'credit' THEN amount ELSE -amount END) bal FROM entries GROUP BY person ORDER BY bal DESC").fetchall()
    return {r["person"]: r["bal"] for r in rows}


def top_debtors(limit=3): return [(p,b) for p,b in balances().items() if b > 0][:max(0, min(int(limit),100))]


def recent(limit=10):
    with _conn() as c: return c.execute("SELECT * FROM entries ORDER BY id DESC LIMIT ?", (max(0,int(limit)),)).fetchall()


def customer_profile(person):
    with _conn() as c:
        row=c.execute("SELECT * FROM customer_profiles WHERE person=? COLLATE NOCASE",(person,)).fetchone()
    return dict(row) if row else {"person":person,"phone":"","notes":""}


def save_customer_profile(person, phone="", notes=""):
    person=(person or "").strip()
    if not person: raise ValueError("Customer name is required.")
    now=time.time()
    with _conn() as c:
        c.execute("INSERT INTO customer_profiles(person,phone,notes,updated_at) VALUES(?,?,?,?) ON CONFLICT(person) DO UPDATE SET phone=excluded.phone,notes=excluded.notes,updated_at=excluded.updated_at",(person,(phone or "").strip(),(notes or "").strip(),now))
        c.execute("INSERT INTO audit_log(action,person,details,ts) VALUES('profile_update',?,?,?)",(person,"Customer profile updated",now))


def customer_entries(person, limit=100):
    with _conn() as c: return c.execute("SELECT * FROM entries WHERE person=? ORDER BY id DESC LIMIT ?",(person,max(0,int(limit)))).fetchall()


def analytics():
    with _conn() as c:
        row=c.execute("SELECT COALESCE(SUM(CASE WHEN entry_type='credit' THEN amount ELSE 0 END),0) credits, COALESCE(SUM(CASE WHEN entry_type='payment' THEN amount ELSE 0 END),0) payments, COUNT(*) count FROM entries").fetchone()
        month=c.execute("SELECT COALESCE(SUM(CASE WHEN entry_type='credit' THEN amount ELSE 0 END),0), COALESCE(SUM(CASE WHEN entry_type='payment' THEN amount ELSE 0 END),0) FROM entries WHERE ts>=?",(time.time()-30*86400,)).fetchone()
    return {"credits":row["credits"],"payments":row["payments"],"count":row["count"],"outstanding":row["credits"]-row["payments"],"recent_credits":month[0],"recent_payments":month[1]}


def undo_last():
    """Append a compensating entry for the latest entry; retain original row."""
    with _conn() as c:
        c.execute("BEGIN IMMEDIATE")
        row=c.execute("SELECT e.* FROM entries e WHERE e.reverses_id IS NULL AND NOT EXISTS(SELECT 1 FROM entries r WHERE r.reverses_id=e.id) ORDER BY e.id DESC LIMIT 1").fetchone()
        if not row: return None
        opposite="payment" if row["entry_type"]=="credit" else "credit"
        now=time.time()
        cur=c.execute("INSERT INTO entries(person,amount,entry_type,note,ts,reverses_id) VALUES(?,?,?,?,?,?)",(row["person"],row["amount"],opposite,f"Undo of entry #{row['id']}",now,row["id"]))
        c.execute("INSERT INTO audit_log(action,entry_id,person,details,ts) VALUES('undo',?,?,?,?)",(cur.lastrowid,row["person"],f"Reversed entry #{row['id']} ({row['entry_type']} ₹{row['amount']:.2f})",now))
        return dict(row)


def audit_recent(limit=20):
    with _conn() as c: return c.execute("SELECT * FROM audit_log ORDER BY id DESC LIMIT ?",(max(0,int(limit)),)).fetchall()


def export_csv():
    out=io.StringIO(newline="")
    writer=csv.writer(out)
    writer.writerow(["Entry ID","Date","Customer","Type","Amount (INR)","Note","Reverses entry"])
    with _conn() as c: rows=c.execute("SELECT * FROM entries ORDER BY id").fetchall()
    for r in rows: writer.writerow([r["id"],time.strftime("%Y-%m-%d %H:%M:%S",time.localtime(r["ts"])),r["person"],r["entry_type"],f"{r['amount']:.2f}",r["note"],r["reverses_id"] or ""])
    return out.getvalue().encode("utf-8-sig")
