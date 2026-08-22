import csv
import io
import json
import os
import re
import secrets
import sqlite3
import time
from datetime import datetime
from functools import wraps
from pathlib import Path

from flask import Flask, flash, jsonify, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)
DB_PATH = DATA_DIR / "ppos.db"

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY") or secrets.token_hex(32)
app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024

VERTICALS = {
    "realestate": {"label": "مشاور املاک", "icon": "⌂", "product": "فایل‌یاب اختصاصی"},
    "beauty": {"label": "سالن زیبایی", "icon": "✦", "product": "رزرو آنلاین اختصاصی"},
    "auto": {"label": "اتوگالری", "icon": "◈", "product": "ماشین‌یاب هوشمند"},
    "clinic": {"label": "کلینیک زیبایی", "icon": "+", "product": "رزرو مشاوره هوشمند"},
    "repair": {"label": "تعمیرگاه خودرو", "icon": "⚙", "product": "ثبت سرویس و برآورد اولیه"},
}


def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def now_iso():
    return datetime.now().isoformat(timespec="seconds")


def slugify(value):
    value = (value or "business").strip().lower()
    value = re.sub(r"[^a-z0-9\u0600-\u06ff]+", "-", value, flags=re.I)
    value = value.strip("-")[:42] or "business"
    return f"{value}-{secrets.token_hex(2)}"


def init_db():
    conn = db()
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS leads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            slug TEXT UNIQUE NOT NULL,
            business_name TEXT NOT NULL,
            vertical TEXT NOT NULL,
            phone TEXT,
            city TEXT,
            address TEXT,
            instagram TEXT,
            logo_url TEXT,
            accent TEXT DEFAULT '#7c5cff',
            meta_json TEXT DEFAULT '{}',
            status TEXT DEFAULT 'new',
            created_at TEXT NOT NULL,
            last_opened_at TEXT,
            opens INTEGER DEFAULT 0,
            cta_clicks INTEGER DEFAULT 0,
            checkout_clicks INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lead_id INTEGER NOT NULL,
            event_type TEXT NOT NULL,
            meta_json TEXT DEFAULT '{}',
            created_at TEXT NOT NULL,
            FOREIGN KEY(lead_id) REFERENCES leads(id)
        );
        """
    )
    conn.commit()
    count = conn.execute("SELECT COUNT(*) c FROM leads").fetchone()["c"]
    if count == 0:
        samples = [
            ("املاک آریا", "realestate", "09121234567", "تهران", "سعادت‌آباد، میدان کاج", "aria_home"),
            ("سالن ژوان", "beauty", "09351234567", "تهران", "پاسداران", "zhoan_beauty"),
            ("اتوگالری سپهر", "auto", "09101234567", "کرج", "مهرشهر", "sepehr_auto"),
            ("کلینیک لیانا", "clinic", "09211234567", "تهران", "جردن", "liana_clinic"),
            ("اتو سرویس پارس", "repair", "09191234567", "تهران", "ستارخان", "pars_service"),
        ]
        for name, vertical, phone, city, address, insta in samples:
            conn.execute(
                "INSERT INTO leads(slug,business_name,vertical,phone,city,address,instagram,created_at) VALUES(?,?,?,?,?,?,?,?)",
                (slugify(name), name, vertical, phone, city, address, insta, now_iso()),
            )
        conn.commit()
    conn.close()


def get_setting(key):
    conn = db()
    row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    conn.close()
    return row["value"] if row else None


def set_setting(key, value):
    conn = db()
    conn.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))
    conn.commit()
    conn.close()


def admin_required(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        if not get_setting("admin_password_hash"):
            return redirect(url_for("setup"))
        if not session.get("admin"):
            return redirect(url_for("login", next=request.path))
        return fn(*args, **kwargs)
    return wrapped


def lead_score(row):
    score = (row["opens"] or 0) * 8 + (row["cta_clicks"] or 0) * 24 + (row["checkout_clicks"] or 0) * 45
    if row["last_opened_at"]:
        try:
            age = time.time() - datetime.fromisoformat(row["last_opened_at"]).timestamp()
            if age < 86400:
                score += 18
        except Exception:
            pass
    return min(score, 100)


def lead_to_dict(row):
    item = dict(row)
    try:
        item["meta"] = json.loads(item.get("meta_json") or "{}")
    except Exception:
        item["meta"] = {}
    item["score"] = lead_score(row)
    item["vertical_info"] = VERTICALS.get(item["vertical"], VERTICALS["realestate"])
    return item


def record_event(lead_id, event_type, meta=None):
    conn = db()
    meta = meta or {}
    conn.execute("INSERT INTO events(lead_id,event_type,meta_json,created_at) VALUES(?,?,?,?)", (lead_id, event_type, json.dumps(meta, ensure_ascii=False), now_iso()))
    if event_type == "open":
        conn.execute("UPDATE leads SET opens=opens+1,last_opened_at=? WHERE id=?", (now_iso(), lead_id))
    elif event_type == "cta":
        conn.execute("UPDATE leads SET cta_clicks=cta_clicks+1 WHERE id=?", (lead_id,))
    elif event_type == "checkout":
        conn.execute("UPDATE leads SET checkout_clicks=checkout_clicks+1 WHERE id=?", (lead_id,))
    conn.commit()
    conn.close()


@app.route("/")
def home():
    conn = db()
    rows = conn.execute("SELECT * FROM leads ORDER BY id LIMIT 5").fetchall()
    conn.close()
    return render_template("home.html", samples=[lead_to_dict(r) for r in rows], verticals=VERTICALS)


@app.route("/setup", methods=["GET", "POST"])
def setup():
    if get_setting("admin_password_hash"):
        return redirect(url_for("login"))
    if request.method == "POST":
        password = request.form.get("password", "")
        if len(password) < 8:
            flash("رمز حداقل ۸ کاراکتر باشد.", "error")
        else:
            set_setting("admin_password_hash", generate_password_hash(password))
            session["admin"] = True
            return redirect(url_for("admin"))
    return render_template("auth.html", mode="setup")


@app.route("/login", methods=["GET", "POST"])
def login():
    password_hash = get_setting("admin_password_hash")
    if not password_hash:
        return redirect(url_for("setup"))
    if request.method == "POST":
        if check_password_hash(password_hash, request.form.get("password", "")):
            session["admin"] = True
            return redirect(request.args.get("next") or url_for("admin"))
        flash("رمز اشتباه است.", "error")
    return render_template("auth.html", mode="login")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/admin")
@admin_required
def admin():
    conn = db()
    rows = conn.execute("SELECT * FROM leads ORDER BY COALESCE(last_opened_at,created_at) DESC").fetchall()
    events_today = conn.execute("SELECT COUNT(*) c FROM events WHERE date(created_at)=date('now','localtime')").fetchone()["c"]
    conn.close()
    leads = [lead_to_dict(r) for r in rows]
    leads.sort(key=lambda x: (x["score"], x["last_opened_at"] or ""), reverse=True)
    stats = {
        "total": len(leads),
        "opened": sum(1 for x in leads if x["opens"]),
        "hot": sum(1 for x in leads if x["score"] >= 50),
        "checkout": sum(x["checkout_clicks"] for x in leads),
        "events_today": events_today,
    }
    return render_template("admin.html", leads=leads, stats=stats, verticals=VERTICALS)


@app.route("/admin/new", methods=["POST"])
@admin_required
def new_lead():
    form = request.form
    name = form.get("business_name", "").strip()
    vertical = form.get("vertical", "realestate")
    if not name or vertical not in VERTICALS:
        flash("نام کسب‌وکار و صنف معتبر لازم است.", "error")
        return redirect(url_for("admin"))
    conn = db()
    conn.execute(
        """INSERT INTO leads(slug,business_name,vertical,phone,city,address,instagram,logo_url,accent,created_at)
           VALUES(?,?,?,?,?,?,?,?,?,?)""",
        (slugify(name), name, vertical, form.get("phone"), form.get("city"), form.get("address"), form.get("instagram"), form.get("logo_url"), form.get("accent") or "#7c5cff", now_iso()),
    )
    conn.commit()
    conn.close()
    flash("دموی اختصاصی ساخته شد.", "success")
    return redirect(url_for("admin"))


@app.route("/admin/import", methods=["POST"])
@admin_required
def import_csv():
    file = request.files.get("file")
    if not file:
        flash("فایل CSV انتخاب نشده.", "error")
        return redirect(url_for("admin"))
    text = file.stream.read().decode("utf-8-sig", errors="ignore")
    reader = csv.DictReader(io.StringIO(text))
    conn = db()
    imported = 0
    for row in reader:
        name = (row.get("business_name") or row.get("name") or "").strip()
        vertical = (row.get("vertical") or "realestate").strip()
        if not name or vertical not in VERTICALS:
            continue
        conn.execute(
            """INSERT INTO leads(slug,business_name,vertical,phone,city,address,instagram,logo_url,created_at)
               VALUES(?,?,?,?,?,?,?,?,?)""",
            (slugify(name), name, vertical, row.get("phone"), row.get("city"), row.get("address"), row.get("instagram"), row.get("logo_url"), now_iso()),
        )
        imported += 1
    conn.commit()
    conn.close()
    flash(f"{imported} لید وارد و دموها ساخته شد.", "success")
    return redirect(url_for("admin"))


@app.route("/admin/lead/<int:lead_id>")
@admin_required
def lead_detail(lead_id):
    conn = db()
    row = conn.execute("SELECT * FROM leads WHERE id=?", (lead_id,)).fetchone()
    events = conn.execute("SELECT * FROM events WHERE lead_id=? ORDER BY id DESC LIMIT 100", (lead_id,)).fetchall()
    conn.close()
    if not row:
        return "Not found", 404
    lead = lead_to_dict(row)
    demo_url = request.url_root.rstrip("/") + url_for("demo", slug=lead["slug"])
    sms = f"{lead['business_name']}، نسخه اختصاصی {lead['vertical_info']['product']} شما آماده شده. با اسم و اطلاعات خودتون ببینید: {demo_url}"
    return render_template("lead.html", lead=lead, events=events, demo_url=demo_url, sms=sms)


@app.route("/d/<slug>")
def demo(slug):
    conn = db()
    row = conn.execute("SELECT * FROM leads WHERE slug=?", (slug,)).fetchone()
    conn.close()
    if not row:
        return render_template("not_found.html"), 404
    lead = lead_to_dict(row)
    record_event(lead["id"], "open", {"ua": request.headers.get("User-Agent", "")[:160]})
    return render_template("demo.html", lead=lead)


@app.route("/checkout/<slug>")
def checkout(slug):
    conn = db()
    row = conn.execute("SELECT * FROM leads WHERE slug=?", (slug,)).fetchone()
    conn.close()
    if not row:
        return "Not found", 404
    lead = lead_to_dict(row)
    record_event(lead["id"], "checkout")
    return render_template("checkout.html", lead=lead)


@app.post("/api/event")
def api_event():
    payload = request.get_json(silent=True) or {}
    slug = payload.get("slug")
    event_type = payload.get("type")
    if event_type not in {"cta", "engaged_15", "engaged_30", "scroll_50", "scroll_90", "finder_used", "booking_used"}:
        return jsonify({"ok": False}), 400
    conn = db()
    row = conn.execute("SELECT id FROM leads WHERE slug=?", (slug,)).fetchone()
    conn.close()
    if not row:
        return jsonify({"ok": False}), 404
    record_event(row["id"], event_type, payload.get("meta") or {})
    return jsonify({"ok": True})


@app.post("/admin/lead/<int:lead_id>/status")
@admin_required
def lead_status(lead_id):
    status = request.form.get("status", "new")
    allowed = {"new", "sent", "contacted", "qualified", "won", "lost"}
    if status not in allowed:
        return redirect(url_for("lead_detail", lead_id=lead_id))
    conn = db()
    conn.execute("UPDATE leads SET status=? WHERE id=?", (status, lead_id))
    conn.commit()
    conn.close()
    return redirect(url_for("lead_detail", lead_id=lead_id))


init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8080")), debug=os.environ.get("FLASK_DEBUG") == "1")
