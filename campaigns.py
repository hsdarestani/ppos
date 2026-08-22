import csv
import io
import json
import re
import secrets
import sqlite3
from datetime import datetime
from functools import wraps

from flask import Response, flash, jsonify, redirect, render_template, request, session, url_for

from verticals import CAMPAIGN_ORDER, VERTICALS, get_vertical


def register_campaigns(app, db_path):
    def db():
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def now_iso():
        return datetime.now().isoformat(timespec="seconds")

    def slugify(value):
        value = (value or "business").strip().lower()
        value = re.sub(r"[^a-z0-9\u0600-\u06ff]+", "-", value, flags=re.I).strip("-")[:42] or "business"
        return f"{value}-{secrets.token_hex(2)}"

    def parse_meta(raw):
        try:
            return json.loads(raw or "{}")
        except Exception:
            return {}

    def admin_only(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            if not session.get("admin"):
                return redirect(url_for("login", next=request.path))
            return fn(*args, **kwargs)
        return wrapped

    def ensure_schema():
        conn = db()
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS campaign_conversions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                prospect_lead_id INTEGER NOT NULL,
                vertical TEXT NOT NULL,
                customer_name TEXT,
                customer_phone TEXT NOT NULL,
                answers_json TEXT DEFAULT '{}',
                source TEXT DEFAULT 'personalized_demo',
                created_at TEXT NOT NULL,
                FOREIGN KEY(prospect_lead_id) REFERENCES leads(id)
            );
            CREATE INDEX IF NOT EXISTS idx_campaign_conversions_prospect ON campaign_conversions(prospect_lead_id);
            CREATE INDEX IF NOT EXISTS idx_campaign_conversions_vertical ON campaign_conversions(vertical);
            """
        )
        conn.commit()
        conn.close()

    ensure_schema()

    def prospect_rows(vertical=None):
        conn = db()
        if vertical:
            prospects = conn.execute("SELECT * FROM leads WHERE vertical=? ORDER BY id DESC", (vertical,)).fetchall()
        else:
            placeholders = ",".join("?" for _ in CAMPAIGN_ORDER)
            prospects = conn.execute(f"SELECT * FROM leads WHERE vertical IN ({placeholders}) ORDER BY id DESC", CAMPAIGN_ORDER).fetchall()
        completed = {r["lead_id"] for r in conn.execute("SELECT DISTINCT lead_id FROM events WHERE event_type IN ('campaign_completed','finder_completed')")}
        price_seen = {r["lead_id"] for r in conn.execute("SELECT DISTINCT lead_id FROM events WHERE event_type='price_viewed'")}
        conversions = {
            r["prospect_lead_id"]: r["c"]
            for r in conn.execute("SELECT prospect_lead_id,COUNT(*) c FROM campaign_conversions GROUP BY prospect_lead_id")
        }
        conn.close()
        rows = []
        for row in prospects:
            item = dict(row)
            meta = parse_meta(item.get("meta_json"))
            item["meta"] = meta
            item["variant"] = meta.get("variant") or "A"
            item["campaign"] = meta.get("campaign") or "—"
            item["source"] = meta.get("source") or "—"
            item["completed"] = item["id"] in completed
            item["price_seen"] = item["id"] in price_seen
            item["conversions"] = conversions.get(item["id"], 0)
            item["vertical_info"] = get_vertical(item["vertical"]) or {"label": item["vertical"], "product": "دموی اختصاصی", "hooks": ["{name}: {url}"]}
            item["hot_score"] = min(
                (item.get("opens") or 0) * 8
                + (item.get("cta_clicks") or 0) * 20
                + (item.get("checkout_clicks") or 0) * 45
                + (28 if item["completed"] else 0)
                + (38 if item["conversions"] else 0)
                + (12 if item["price_seen"] else 0),
                100,
            )
            rows.append(item)
        rows.sort(key=lambda x: (x["hot_score"], x.get("last_opened_at") or ""), reverse=True)
        return rows

    def variants_snapshot(rows):
        groups = {}
        for item in rows:
            g = groups.setdefault(item["variant"], {"variant": item["variant"], "prospects": 0, "opened": 0, "completed": 0, "conversions": 0, "checkout": 0, "won": 0})
            g["prospects"] += 1
            g["opened"] += int((item.get("opens") or 0) > 0)
            g["completed"] += int(item["completed"])
            g["conversions"] += item["conversions"]
            g["checkout"] += int((item.get("checkout_clicks") or 0) > 0)
            g["won"] += int(item.get("status") == "won")
        for g in groups.values():
            n = g["prospects"] or 1
            g["open_rate"] = round(g["opened"] * 100 / n, 1)
            g["complete_rate"] = round(g["completed"] * 100 / n, 1)
            g["checkout_rate"] = round(g["checkout"] * 100 / n, 1)
            g["won_rate"] = round(g["won"] * 100 / n, 1)
        return sorted(groups.values(), key=lambda x: x["variant"])

    def demo_url_for(item):
        if item["vertical"] == "realestate":
            return request.url_root.rstrip("/") + f"/d/{item['slug']}"
        return request.url_root.rstrip("/") + f"/v/{item['slug']}"

    def sms_for(item):
        info = item["vertical_info"]
        hooks = info.get("hooks") or ["{name}، نسخه اختصاصی شما آماده شده: {url}"]
        index = 1 if item["variant"] == "B" and len(hooks) > 1 else 0
        return hooks[index].format(name=item["business_name"], url=demo_url_for(item))

    @app.get("/admin/campaigns")
    @admin_only
    def campaigns_hub():
        all_rows = prospect_rows()
        cards = []
        for key in CAMPAIGN_ORDER:
            info = VERTICALS[key]
            rows = [x for x in all_rows if x["vertical"] == key]
            cards.append({
                "key": key,
                "info": info,
                "prospects": len(rows),
                "opened": sum(1 for x in rows if (x.get("opens") or 0) > 0),
                "hot": sum(1 for x in rows if x["hot_score"] >= 50),
                "won": sum(1 for x in rows if x.get("status") == "won"),
            })
        totals = {
            "verticals": len(CAMPAIGN_ORDER),
            "prospects": len(all_rows),
            "opened": sum(1 for x in all_rows if (x.get("opens") or 0) > 0),
            "hot": sum(1 for x in all_rows if x["hot_score"] >= 50),
        }
        return render_template("campaigns_hub.html", cards=cards, totals=totals)

    @app.post("/admin/campaigns/import")
    @admin_only
    def campaigns_import():
        file = request.files.get("file")
        default_vertical = (request.form.get("vertical") or "").strip()
        campaign = (request.form.get("campaign") or "OUTBOUND-MVP").strip()
        if not file:
            flash("فایل CSV انتخاب نشده.", "error")
            return redirect(url_for("campaigns_hub"))
        text = file.stream.read().decode("utf-8-sig", errors="ignore")
        reader = csv.DictReader(io.StringIO(text))
        conn = db()
        imported = skipped = 0
        for row in reader:
            vertical = (row.get("vertical") or default_vertical).strip()
            name = (row.get("business_name") or row.get("name") or "").strip()
            phone = (row.get("phone") or "").strip()
            if vertical not in VERTICALS or not name:
                skipped += 1
                continue
            duplicate = conn.execute("SELECT id FROM leads WHERE vertical=? AND business_name=? AND COALESCE(phone,'')=? LIMIT 1", (vertical, name, phone)).fetchone()
            if duplicate:
                skipped += 1
                continue
            variant = (row.get("variant") or ("A" if imported % 2 == 0 else "B")).strip().upper()
            if variant not in {"A", "B"}:
                variant = "A"
            meta = {
                "campaign": (row.get("campaign") or campaign),
                "variant": variant,
                "source": (row.get("source") or "csv"),
                "category": VERTICALS[vertical]["label"],
            }
            conn.execute(
                """INSERT INTO leads(slug,business_name,vertical,phone,city,address,instagram,logo_url,accent,meta_json,status,created_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                (slugify(name), name, vertical, phone, row.get("city"), row.get("address"), row.get("instagram"), row.get("logo_url"), row.get("accent") or "#5b4df5", json.dumps(meta, ensure_ascii=False), "new", now_iso()),
            )
            imported += 1
        conn.commit()
        conn.close()
        flash(f"{imported} لید کمپین وارد شد؛ {skipped} ردیف تکراری/نامعتبر رد شد.", "success")
        return redirect(url_for("campaigns_hub"))

    @app.post("/admin/campaign/<vertical>/seed")
    @admin_only
    def seed_vertical_campaign(vertical):
        info = get_vertical(vertical)
        if not info:
            return "Not found", 404
        conn = db()
        existing = conn.execute("SELECT COUNT(*) c FROM leads WHERE vertical=? AND meta_json LIKE '%\"test_campaign\": true%'", (vertical,)).fetchone()["c"]
        if existing >= 20:
            conn.close()
            flash("لیدهای QA این صنف قبلاً ساخته شده‌اند.", "success")
            return redirect(url_for("campaign_vertical", vertical=vertical))
        for i in range(20):
            meta = {"test_campaign": True, "campaign": f"QA-{vertical.upper()}", "variant": "A" if i % 2 == 0 else "B", "source": "qa"}
            conn.execute(
                "INSERT INTO leads(slug,business_name,vertical,phone,city,address,accent,meta_json,status,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (slugify(f"دمو {info['label']} {i+1}"), f"دمو {info['label']} {i+1:02d}", vertical, "", "تهران", "", "#5b4df5", json.dumps(meta, ensure_ascii=False), "new", now_iso()),
            )
        conn.commit()
        conn.close()
        flash("۲۰ لید QA با A/B ساخته شد.", "success")
        return redirect(url_for("campaign_vertical", vertical=vertical))

    @app.get("/admin/campaign/<vertical>")
    @admin_only
    def campaign_vertical(vertical):
        info = get_vertical(vertical)
        if not info:
            return "Not found", 404
        rows = prospect_rows(vertical)
        variants = variants_snapshot(rows)
        metrics = {
            "prospects": len(rows),
            "opened": sum(1 for x in rows if (x.get("opens") or 0) > 0),
            "completed": sum(1 for x in rows if x["completed"]),
            "conversions": sum(x["conversions"] for x in rows),
            "checkout": sum(1 for x in rows if (x.get("checkout_clicks") or 0) > 0),
            "won": sum(1 for x in rows if x.get("status") == "won"),
        }
        for x in rows:
            x["demo_url"] = demo_url_for(x)
            x["sms"] = sms_for(x)
        return render_template("campaign_vertical.html", vertical=vertical, info=info, rows=rows[:200], variants=variants, metrics=metrics)

    @app.get("/admin/campaign/<vertical>/sms.csv")
    @admin_only
    def campaign_sms_csv(vertical):
        if not get_vertical(vertical):
            return "Not found", 404
        rows = prospect_rows(vertical)
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["business_name", "phone", "city", "variant", "demo_url", "sms"])
        for x in rows:
            w.writerow([x["business_name"], x.get("phone"), x.get("city"), x["variant"], demo_url_for(x), sms_for(x)])
        return Response("\ufeff" + buf.getvalue(), mimetype="text/csv; charset=utf-8", headers={"Content-Disposition": f"attachment; filename=ppos-{vertical}-sms.csv"})

    @app.get("/admin/campaign/<vertical>/calls.csv")
    @admin_only
    def campaign_calls_csv(vertical):
        info = get_vertical(vertical)
        if not info:
            return "Not found", 404
        rows = prospect_rows(vertical)
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["priority", "business_name", "phone", "score", "opens", "completed", "price_seen", "checkout", "status", "call_script"])
        priority = 0
        for x in rows:
            if x["hot_score"] < 25:
                continue
            priority += 1
            if x.get("checkout_clicks"):
                script = f"سلام، نسخه {info['product']} {x['business_name']} رو دیدید و تا فعال‌سازی رفتید؛ اگر اوکیه همین نسخه رو براتون نهایی کنیم."
            elif x["completed"]:
                script = f"سلام، دیدم دموی {info['product']} {x['business_name']} رو کامل تست کردید؛ دقیقاً همین با برند خودتون فعال میشه. نظرتون چطور بود؟"
            else:
                script = f"سلام، لینک اختصاصی {x['business_name']} رو دیدید؟ همون نسخه برای خودتونه؛ اگر بازش کنید در کمتر از یک دقیقه کارشو می‌بینید."
            w.writerow([priority, x["business_name"], x.get("phone"), x["hot_score"], x.get("opens"), int(x["completed"]), int(x["price_seen"]), x.get("checkout_clicks"), x.get("status"), script])
        return Response("\ufeff" + buf.getvalue(), mimetype="text/csv; charset=utf-8", headers={"Content-Disposition": f"attachment; filename=ppos-{vertical}-calls.csv"})

    @app.get("/v/<slug>")
    def vertical_demo(slug):
        conn = db()
        row = conn.execute("SELECT * FROM leads WHERE slug=?", (slug,)).fetchone()
        if not row:
            conn.close()
            return "Not found", 404
        lead = dict(row)
        info = get_vertical(lead["vertical"])
        if not info:
            conn.close()
            return "Not found", 404
        conn.execute("UPDATE leads SET opens=opens+1,last_opened_at=? WHERE id=?", (now_iso(), lead["id"]))
        conn.execute("INSERT INTO events(lead_id,event_type,meta_json,created_at) VALUES(?,?,?,?)", (lead["id"], "open", "{}", now_iso()))
        conn.commit()
        conn.close()
        lead["meta"] = parse_meta(lead.get("meta_json"))
        if lead["vertical"] == "realestate":
            return redirect(f"/d/{slug}")
        return render_template("demo_vertical.html", lead=lead, info=info)

    @app.post("/api/v/<slug>/event")
    def vertical_event(slug):
        payload = request.get_json(silent=True) or {}
        event_type = payload.get("type")
        allowed = {"campaign_started", "campaign_completed", "price_viewed", "cta", "engaged_15", "engaged_30"}
        if event_type not in allowed:
            return jsonify({"ok": False}), 400
        conn = db()
        row = conn.execute("SELECT id FROM leads WHERE slug=?", (slug,)).fetchone()
        if not row:
            conn.close()
            return jsonify({"ok": False}), 404
        conn.execute("INSERT INTO events(lead_id,event_type,meta_json,created_at) VALUES(?,?,?,?)", (row["id"], event_type, json.dumps(payload.get("meta") or {}, ensure_ascii=False), now_iso()))
        if event_type in {"campaign_completed", "cta"}:
            conn.execute("UPDATE leads SET cta_clicks=cta_clicks+1 WHERE id=?", (row["id"],))
        conn.commit()
        conn.close()
        return jsonify({"ok": True})

    @app.post("/api/v/<slug>/lead")
    def vertical_capture(slug):
        payload = request.get_json(silent=True) or {}
        phone = re.sub(r"\D", "", str(payload.get("phone") or ""))
        if phone.startswith("98") and len(phone) == 12:
            phone = "0" + phone[2:]
        if not re.fullmatch(r"09\d{9}", phone):
            return jsonify({"ok": False, "error": "شماره موبایل معتبر وارد کنید."}), 400
        conn = db()
        row = conn.execute("SELECT id,vertical FROM leads WHERE slug=?", (slug,)).fetchone()
        if not row or not get_vertical(row["vertical"]):
            conn.close()
            return jsonify({"ok": False, "error": "دمو پیدا نشد."}), 404
        answers = payload.get("answers") if isinstance(payload.get("answers"), dict) else {}
        cur = conn.execute(
            "INSERT INTO campaign_conversions(prospect_lead_id,vertical,customer_name,customer_phone,answers_json,created_at) VALUES(?,?,?,?,?,?)",
            (row["id"], row["vertical"], str(payload.get("name") or "")[:80], phone, json.dumps(answers, ensure_ascii=False), now_iso()),
        )
        conn.execute("INSERT INTO events(lead_id,event_type,meta_json,created_at) VALUES(?,?,?,?)", (row["id"], "customer_lead", json.dumps({"conversion_id": cur.lastrowid}, ensure_ascii=False), now_iso()))
        conn.execute("UPDATE leads SET cta_clicks=cta_clicks+1 WHERE id=?", (row["id"],))
        conn.commit()
        conn.close()
        return jsonify({"ok": True, "preview_url": f"/m/{slug}"})

    @app.get("/m/<slug>")
    def vertical_merchant_preview(slug):
        conn = db()
        row = conn.execute("SELECT * FROM leads WHERE slug=?", (slug,)).fetchone()
        if not row:
            conn.close()
            return "Not found", 404
        lead = dict(row)
        info = get_vertical(lead["vertical"])
        if not info:
            conn.close()
            return "Not found", 404
        conv = conn.execute("SELECT * FROM campaign_conversions WHERE prospect_lead_id=? ORDER BY id DESC LIMIT 20", (lead["id"],)).fetchall()
        conn.close()
        items = []
        for r in conv:
            x = dict(r)
            x["answers"] = parse_meta(x.get("answers_json"))
            p = x.get("customer_phone") or ""
            x["masked_phone"] = (p[:4] + " ••• ••" + p[-2:]) if len(p) >= 6 else "09•• ••• ••••"
            items.append(x)
        return render_template("merchant_vertical.html", lead=lead, info=info, conversions=items)
