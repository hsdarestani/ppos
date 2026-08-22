import csv
import io
import json
import re
import sqlite3
from datetime import datetime
from functools import wraps

from flask import jsonify, redirect, render_template, request, session, url_for, Response


def register_capture(app, db_path):
    def db():
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def now_iso():
        return datetime.now().isoformat(timespec="seconds")

    def admin_only(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            if not session.get("admin"):
                return redirect(url_for("login", next=request.path))
            return fn(*args, **kwargs)
        return wrapped

    def ensure_tables():
        conn = db()
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS customer_leads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                prospect_lead_id INTEGER NOT NULL,
                customer_name TEXT,
                customer_phone TEXT NOT NULL,
                intent TEXT,
                area TEXT,
                budget TEXT,
                source TEXT DEFAULT 'demo',
                is_demo INTEGER DEFAULT 1,
                created_at TEXT NOT NULL,
                FOREIGN KEY(prospect_lead_id) REFERENCES leads(id)
            );
            CREATE INDEX IF NOT EXISTS idx_customer_leads_prospect ON customer_leads(prospect_lead_id);
            """
        )
        conn.commit()
        conn.close()

    ensure_tables()

    def parse_meta(raw):
        try:
            return json.loads(raw or "{}")
        except Exception:
            return {}

    @app.post("/api/realestate/<slug>/lead")
    def capture_realestate_lead(slug):
        payload = request.get_json(silent=True) or {}
        phone = re.sub(r"\D", "", str(payload.get("phone") or ""))
        if phone.startswith("98") and len(phone) == 12:
            phone = "0" + phone[2:]
        if not re.fullmatch(r"09\d{9}", phone):
            return jsonify({"ok": False, "error": "شماره موبایل معتبر وارد کنید."}), 400

        conn = db()
        prospect = conn.execute(
            "SELECT id,business_name,slug FROM leads WHERE slug=? AND vertical='realestate'",
            (slug,),
        ).fetchone()
        if not prospect:
            conn.close()
            return jsonify({"ok": False, "error": "دمو پیدا نشد."}), 404

        intent = str(payload.get("intent") or "خرید")[:80]
        area = str(payload.get("area") or "")[:160]
        budget = str(payload.get("budget") or "")[:100]
        name = str(payload.get("name") or "")[:80]

        cur = conn.execute(
            """INSERT INTO customer_leads(
                   prospect_lead_id,customer_name,customer_phone,intent,area,budget,source,is_demo,created_at
               ) VALUES(?,?,?,?,?,?,?,?,?)""",
            (prospect["id"], name, phone, intent, area, budget, "personalized_demo", 1, now_iso()),
        )
        customer_lead_id = cur.lastrowid
        meta = json.dumps(
            {"customer_lead_id": customer_lead_id, "intent": intent, "area": area, "budget": budget},
            ensure_ascii=False,
        )
        conn.execute(
            "INSERT INTO events(lead_id,event_type,meta_json,created_at) VALUES(?,?,?,?)",
            (prospect["id"], "customer_lead", meta, now_iso()),
        )
        conn.execute("UPDATE leads SET cta_clicks=cta_clicks+1 WHERE id=?", (prospect["id"],))
        conn.commit()
        conn.close()

        return jsonify(
            {
                "ok": True,
                "id": customer_lead_id,
                "preview_url": url_for("merchant_preview", slug=slug),
            }
        )

    @app.get("/p/<slug>")
    def merchant_preview(slug):
        conn = db()
        prospect = conn.execute("SELECT * FROM leads WHERE slug=? AND vertical='realestate'", (slug,)).fetchone()
        if not prospect:
            conn.close()
            return "Not found", 404
        rows = conn.execute(
            "SELECT * FROM customer_leads WHERE prospect_lead_id=? ORDER BY id DESC LIMIT 25",
            (prospect["id"],),
        ).fetchall()
        conn.close()
        lead = dict(prospect)
        lead["meta"] = parse_meta(lead.get("meta_json"))
        return render_template("merchant_preview.html", lead=lead, customer_leads=[dict(r) for r in rows])

    def campaign_snapshot():
        conn = db()
        prospects = conn.execute("SELECT * FROM leads WHERE vertical='realestate' ORDER BY id DESC").fetchall()
        completed = {r["lead_id"] for r in conn.execute("SELECT DISTINCT lead_id FROM events WHERE event_type='finder_completed'")}
        price_seen = {r["lead_id"] for r in conn.execute("SELECT DISTINCT lead_id FROM events WHERE event_type='price_viewed'")}
        customer_counts = {
            r["prospect_lead_id"]: r["c"]
            for r in conn.execute("SELECT prospect_lead_id,COUNT(*) c FROM customer_leads GROUP BY prospect_lead_id")
        }
        conn.close()

        groups = {}
        rows = []
        for row in prospects:
            item = dict(row)
            meta = parse_meta(item.get("meta_json"))
            variant = meta.get("variant") or "A"
            item["variant"] = variant
            item["campaign"] = meta.get("campaign") or "—"
            item["source"] = meta.get("source") or "—"
            item["finder_completed"] = item["id"] in completed
            item["price_seen"] = item["id"] in price_seen
            item["customer_leads"] = customer_counts.get(item["id"], 0)
            item["hot_score"] = min(
                (item.get("opens") or 0) * 8
                + (item.get("cta_clicks") or 0) * 24
                + (item.get("checkout_clicks") or 0) * 45
                + (30 if item["finder_completed"] else 0)
                + (35 if item["customer_leads"] else 0),
                100,
            )
            rows.append(item)

            g = groups.setdefault(
                variant,
                {"variant": variant, "prospects": 0, "opened": 0, "finder": 0, "price": 0, "customer_leads": 0, "checkout": 0, "won": 0},
            )
            g["prospects"] += 1
            g["opened"] += int((item.get("opens") or 0) > 0)
            g["finder"] += int(item["finder_completed"])
            g["price"] += int(item["price_seen"])
            g["customer_leads"] += item["customer_leads"]
            g["checkout"] += int((item.get("checkout_clicks") or 0) > 0)
            g["won"] += int(item.get("status") == "won")

        for g in groups.values():
            n = g["prospects"] or 1
            g["open_rate"] = round(g["opened"] * 100 / n, 1)
            g["finder_rate"] = round(g["finder"] * 100 / n, 1)
            g["checkout_rate"] = round(g["checkout"] * 100 / n, 1)
            g["won_rate"] = round(g["won"] * 100 / n, 1)

        rows.sort(key=lambda x: (x["hot_score"], x.get("last_opened_at") or ""), reverse=True)
        return rows, sorted(groups.values(), key=lambda x: x["variant"])

    @app.get("/admin/campaign/realestate")
    @admin_only
    def realestate_campaign():
        rows, variants = campaign_snapshot()
        total = len(rows)
        metrics = {
            "prospects": total,
            "opened": sum(1 for x in rows if (x.get("opens") or 0) > 0),
            "finder": sum(1 for x in rows if x["finder_completed"]),
            "customer_leads": sum(x["customer_leads"] for x in rows),
            "checkout": sum(1 for x in rows if (x.get("checkout_clicks") or 0) > 0),
            "won": sum(1 for x in rows if x.get("status") == "won"),
        }
        return render_template("campaign_realestate.html", rows=rows[:100], variants=variants, metrics=metrics)

    @app.get("/admin/campaign/realestate/export.csv")
    @admin_only
    def export_realestate_campaign():
        rows, _ = campaign_snapshot()
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow([
            "business_name", "phone", "city", "address", "variant", "campaign", "opens", "finder_completed",
            "customer_leads", "checkout", "status", "hot_score", "demo_url"
        ])
        root = request.url_root.rstrip("/")
        for x in rows:
            writer.writerow([
                x.get("business_name"), x.get("phone"), x.get("city"), x.get("address"), x.get("variant"),
                x.get("campaign"), x.get("opens"), int(x.get("finder_completed")), x.get("customer_leads"),
                x.get("checkout_clicks"), x.get("status"), x.get("hot_score"), f"{root}/d/{x.get('slug')}"
            ])
        data = "\ufeff" + buf.getvalue()
        return Response(data, mimetype="text/csv; charset=utf-8", headers={"Content-Disposition": "attachment; filename=ppos-realestate-campaign.csv"})
