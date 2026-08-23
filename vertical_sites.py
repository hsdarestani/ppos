import json
import re
import sqlite3
from datetime import datetime
from functools import wraps

from flask import flash, jsonify, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from site_blueprints import get_blueprint
from verticals import VERTICALS, get_vertical

PAGES = {"home", "services", "catalog", "about", "contact"}


def register_vertical_sites(app, db_path):
    def db():
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=8000")
        return conn

    def now():
        return datetime.now().isoformat(timespec="seconds")

    def parse(raw):
        try:
            return json.loads(raw or "{}")
        except Exception:
            return {}

    def normalize_mobile(value):
        raw = re.sub(r"\D", "", str(value or ""))
        if raw.startswith("0098"):
            raw = "0" + raw[4:]
        elif raw.startswith("98") and len(raw) == 12:
            raw = "0" + raw[2:]
        elif raw.startswith("9") and len(raw) == 10:
            raw = "0" + raw
        return raw if re.fullmatch(r"09\d{9}", raw) else ""

    def ensure_schema():
        conn = db()
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS site_customers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lead_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            phone TEXT NOT NULL,
            pin_hash TEXT NOT NULL,
            created_at TEXT NOT NULL,
            last_login_at TEXT,
            UNIQUE(lead_id, phone),
            FOREIGN KEY(lead_id) REFERENCES leads(id)
        );
        CREATE TABLE IF NOT EXISTS site_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lead_id INTEGER NOT NULL,
            customer_id INTEGER,
            request_type TEXT NOT NULL DEFAULT 'general',
            payload_json TEXT DEFAULT '{}',
            status TEXT NOT NULL DEFAULT 'new',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(lead_id) REFERENCES leads(id),
            FOREIGN KEY(customer_id) REFERENCES site_customers(id)
        );
        CREATE TABLE IF NOT EXISTS site_catalog_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lead_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            subtitle TEXT,
            image_url TEXT,
            badge TEXT,
            position INTEGER DEFAULT 0,
            is_active INTEGER DEFAULT 1,
            created_at TEXT NOT NULL,
            FOREIGN KEY(lead_id) REFERENCES leads(id)
        );
        CREATE TABLE IF NOT EXISTS site_favorites (
            lead_id INTEGER NOT NULL,
            customer_id INTEGER NOT NULL,
            item_id INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY(customer_id, item_id),
            FOREIGN KEY(lead_id) REFERENCES leads(id),
            FOREIGN KEY(customer_id) REFERENCES site_customers(id),
            FOREIGN KEY(item_id) REFERENCES site_catalog_items(id)
        );
        CREATE TABLE IF NOT EXISTS site_page_overrides (
            lead_id INTEGER NOT NULL,
            page_key TEXT NOT NULL,
            content_json TEXT DEFAULT '{}',
            updated_at TEXT NOT NULL,
            PRIMARY KEY(lead_id, page_key),
            FOREIGN KEY(lead_id) REFERENCES leads(id)
        );
        CREATE INDEX IF NOT EXISTS idx_site_customers_lead ON site_customers(lead_id);
        CREATE INDEX IF NOT EXISTS idx_site_requests_lead ON site_requests(lead_id, status);
        CREATE INDEX IF NOT EXISTS idx_site_catalog_lead ON site_catalog_items(lead_id, is_active, position);
        CREATE INDEX IF NOT EXISTS idx_site_favorites_lead ON site_favorites(lead_id, customer_id);
        """)
        conn.commit(); conn.close()

    ensure_schema()

    def load_site(slug):
        conn = db()
        row = conn.execute("SELECT * FROM leads WHERE slug=?", (slug,)).fetchone()
        conn.close()
        if not row:
            return None
        lead = dict(row)
        info = get_vertical(lead["vertical"])
        if not info:
            return None
        lead["meta"] = parse(lead.get("meta_json"))
        bp = get_blueprint(lead["vertical"], info)
        lead["rating"] = lead["meta"].get("rating") or lead["meta"].get("google_rating")
        lead["reviews"] = lead["meta"].get("reviews") or lead["meta"].get("google_reviews")
        lead["place_id"] = lead["meta"].get("place_id") or lead["meta"].get("google_place_id")
        return lead, info, bp

    def seed_catalog(lead, bp):
        conn = db()
        count = conn.execute("SELECT COUNT(*) c FROM site_catalog_items WHERE lead_id=?", (lead["id"],)).fetchone()["c"]
        if count == 0:
            for pos, item in enumerate(bp.get("catalog") or [], 1):
                conn.execute(
                    "INSERT INTO site_catalog_items(lead_id,title,subtitle,image_url,badge,position,created_at) VALUES(?,?,?,?,?,?,?)",
                    (lead["id"], item.get("title"), item.get("subtitle"), item.get("image"), item.get("badge"), pos, now()),
                )
            conn.commit()
        rows = conn.execute("SELECT * FROM site_catalog_items WHERE lead_id=? AND is_active=1 ORDER BY position,id", (lead["id"],)).fetchall()
        conn.close()
        return [dict(x) for x in rows]

    def current_customer(lead_id):
        cid = session.get("site_customer_id")
        lid = session.get("site_lead_id")
        if not cid or lid != lead_id:
            return None
        conn = db()
        row = conn.execute("SELECT id,lead_id,name,phone,created_at,last_login_at FROM site_customers WHERE id=? AND lead_id=?", (cid, lead_id)).fetchone()
        conn.close()
        return dict(row) if row else None

    def site_context(slug, page="home"):
        loaded = load_site(slug)
        if not loaded:
            return None
        lead, info, bp = loaded
        items = seed_catalog(lead, bp)
        customer = current_customer(lead["id"])
        favorite_ids = set()
        if customer:
            conn = db()
            favorite_ids = {r["item_id"] for r in conn.execute("SELECT item_id FROM site_favorites WHERE lead_id=? AND customer_id=?", (lead["id"], customer["id"])).fetchall()}
            conn.close()
        hero_image = (bp.get("images") or [None])[0]
        # presentation.py gives a curated stock photo per vertical; prefer it when present.
        hero_url = info.get("hero_image")
        return {"lead":lead,"info":info,"bp":bp,"items":items,"page":page,"customer":customer,"favorite_ids":favorite_ids,"hero_url":hero_url}

    @app.get("/s/<slug>")
    def vertical_site_home(slug):
        ctx = site_context(slug, "home")
        if not ctx:
            return render_template("not_found.html"), 404
        return render_template("vertical_site.html", **ctx)

    @app.get("/s/<slug>/<page>")
    def vertical_site_page(slug, page):
        if page not in PAGES - {"home"}:
            return render_template("not_found.html"), 404
        ctx = site_context(slug, page)
        if not ctx:
            return render_template("not_found.html"), 404
        return render_template("vertical_site.html", **ctx)

    @app.post("/s/<slug>/request")
    def vertical_site_request(slug):
        loaded = load_site(slug)
        if not loaded:
            return jsonify({"ok":False,"error":"سایت پیدا نشد."}), 404
        lead, info, bp = loaded
        customer = current_customer(lead["id"])
        payload = request.get_json(silent=True) if request.is_json else request.form.to_dict(flat=True)
        payload = payload or {}
        phone = normalize_mobile(payload.get("phone"))
        name = str(payload.get("name") or "").strip()[:80]
        request_type = str(payload.get("request_type") or info.get("mode") or "general")[:40]
        if not customer and not phone:
            msg = "شماره موبایل را وارد کنید."
            if request.is_json: return jsonify({"ok":False,"error":msg}), 400
            flash(msg, "error"); return redirect(url_for("vertical_site_page", slug=slug, page="contact"))
        clean_payload = {k:str(v)[:500] for k,v in payload.items() if k not in {"pin"}}
        if customer:
            clean_payload.setdefault("name", customer["name"])
            clean_payload.setdefault("phone", customer["phone"])
        conn = db()
        cur = conn.execute(
            "INSERT INTO site_requests(lead_id,customer_id,request_type,payload_json,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
            (lead["id"], customer["id"] if customer else None, request_type, json.dumps(clean_payload, ensure_ascii=False), "new", now(), now()),
        )
        conn.execute("INSERT INTO events(lead_id,event_type,meta_json,created_at) VALUES(?,?,?,?)", (lead["id"], "site_request", json.dumps({"request_id":cur.lastrowid,"type":request_type}, ensure_ascii=False), now()))
        conn.execute("UPDATE leads SET cta_clicks=cta_clicks+1 WHERE id=?", (lead["id"],))
        conn.commit(); conn.close()
        if request.is_json:
            return jsonify({"ok":True,"request_id":cur.lastrowid,"account_url":url_for("vertical_site_account", slug=slug) if customer else url_for("vertical_site_login", slug=slug)})
        flash("درخواست شما ثبت شد. برای پیگیری می‌توانید وارد پنل کاربری شوید.", "success")
        return redirect(url_for("vertical_site_account", slug=slug) if customer else url_for("vertical_site_login", slug=slug))

    @app.route("/s/<slug>/account/login", methods=["GET","POST"])
    def vertical_site_login(slug):
        loaded = load_site(slug)
        if not loaded:
            return render_template("not_found.html"), 404
        lead, info, bp = loaded
        if current_customer(lead["id"]):
            return redirect(url_for("vertical_site_account", slug=slug))
        if request.method == "POST":
            phone = normalize_mobile(request.form.get("phone"))
            pin = str(request.form.get("pin") or "")
            name = str(request.form.get("name") or "").strip()[:80]
            if not phone or len(pin) < 4:
                flash("موبایل معتبر و رمز حداقل ۴ رقمی وارد کنید.", "error")
            else:
                conn = db()
                row = conn.execute("SELECT * FROM site_customers WHERE lead_id=? AND phone=?", (lead["id"], phone)).fetchone()
                if row:
                    if check_password_hash(row["pin_hash"], pin):
                        conn.execute("UPDATE site_customers SET last_login_at=? WHERE id=?", (now(), row["id"]))
                        conn.commit(); conn.close()
                        session["site_customer_id"] = row["id"]
                        session["site_lead_id"] = lead["id"]
                        return redirect(url_for("vertical_site_account", slug=slug))
                    conn.close(); flash("رمز این شماره درست نیست.", "error")
                elif not name:
                    conn.close(); flash("برای ساخت حساب جدید، نام را هم وارد کنید.", "error")
                else:
                    cur = conn.execute("INSERT INTO site_customers(lead_id,name,phone,pin_hash,created_at,last_login_at) VALUES(?,?,?,?,?,?)", (lead["id"], name, phone, generate_password_hash(pin), now(), now()))
                    conn.commit(); conn.close()
                    session["site_customer_id"] = cur.lastrowid
                    session["site_lead_id"] = lead["id"]
                    return redirect(url_for("vertical_site_account", slug=slug))
        return render_template("vertical_site_login.html", lead=lead, info=info, bp=bp)

    @app.get("/s/<slug>/account/logout")
    def vertical_site_logout(slug):
        session.pop("site_customer_id", None); session.pop("site_lead_id", None)
        return redirect(url_for("vertical_site_home", slug=slug))

    @app.get("/s/<slug>/account")
    def vertical_site_account(slug):
        loaded = load_site(slug)
        if not loaded:
            return render_template("not_found.html"), 404
        lead, info, bp = loaded
        customer = current_customer(lead["id"])
        if not customer:
            return redirect(url_for("vertical_site_login", slug=slug))
        seed_catalog(lead, bp)
        conn = db()
        reqs = []
        for row in conn.execute("SELECT * FROM site_requests WHERE lead_id=? AND customer_id=? ORDER BY id DESC LIMIT 50", (lead["id"], customer["id"])).fetchall():
            x = dict(row); x["payload"] = parse(x.get("payload_json")); reqs.append(x)
        favorites = [dict(x) for x in conn.execute("""SELECT i.* FROM site_favorites f JOIN site_catalog_items i ON i.id=f.item_id WHERE f.lead_id=? AND f.customer_id=? ORDER BY f.created_at DESC""", (lead["id"], customer["id"])).fetchall()]
        conn.close()
        return render_template("vertical_site_account.html", lead=lead, info=info, bp=bp, customer=customer, requests=reqs, favorites=favorites)

    @app.post("/s/<slug>/favorite/<int:item_id>")
    def vertical_site_favorite(slug, item_id):
        loaded = load_site(slug)
        if not loaded:
            return jsonify({"ok":False}), 404
        lead, info, bp = loaded
        customer = current_customer(lead["id"])
        if not customer:
            return jsonify({"ok":False,"login":url_for("vertical_site_login", slug=slug)}), 401
        conn = db()
        item = conn.execute("SELECT id FROM site_catalog_items WHERE id=? AND lead_id=? AND is_active=1", (item_id, lead["id"])).fetchone()
        if not item:
            conn.close(); return jsonify({"ok":False}), 404
        exists = conn.execute("SELECT 1 FROM site_favorites WHERE customer_id=? AND item_id=?", (customer["id"], item_id)).fetchone()
        if exists:
            conn.execute("DELETE FROM site_favorites WHERE customer_id=? AND item_id=?", (customer["id"], item_id)); active=False
        else:
            conn.execute("INSERT INTO site_favorites(lead_id,customer_id,item_id,created_at) VALUES(?,?,?,?)", (lead["id"], customer["id"], item_id, now())); active=True
        conn.commit(); conn.close()
        return jsonify({"ok":True,"active":active})

    @app.post("/s/<slug>/account/request/<int:req_id>/cancel")
    def vertical_site_cancel_request(slug, req_id):
        loaded = load_site(slug)
        if not loaded:
            return redirect(url_for("home"))
        lead, info, bp = loaded
        customer = current_customer(lead["id"])
        if not customer:
            return redirect(url_for("vertical_site_login", slug=slug))
        conn = db()
        conn.execute("UPDATE site_requests SET status='cancel_requested',updated_at=? WHERE id=? AND lead_id=? AND customer_id=? AND status IN ('new','contacted')", (now(), req_id, lead["id"], customer["id"]))
        conn.commit(); conn.close()
        flash("درخواست لغو/تغییر ثبت شد.", "success")
        return redirect(url_for("vertical_site_account", slug=slug))

    @app.get("/health/sites")
    def vertical_sites_health():
        conn = db()
        tables = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'site_%'").fetchall()}
        conn.close()
        expected = {"site_customers","site_requests","site_catalog_items","site_favorites","site_page_overrides"}
        return jsonify({"ok":expected.issubset(tables),"verticals":len(VERTICALS),"pages":["home","services","catalog","about","contact","account"],"db_tables":sorted(tables)})
