"""Multi-tenant booking and retention OS used by the sellable PPOS verticals.

Beauty is the first production vertical, but the data model and tenant boundary are
generic on purpose: every business-owned row carries ``business_id`` and no query
is allowed to cross that boundary.
"""

import json
import re
import secrets
import sqlite3
from datetime import datetime, timedelta
from functools import wraps
from zoneinfo import ZoneInfo

from flask import abort, flash, jsonify, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash


SHOWCASE_SLUG = "salon-morvarid"
BUSINESS_TIMEZONE = ZoneInfo("Asia/Tehran")

SERVICE_SEED = [
    ("مو", "کوتاهی و استایل مو", "فرم‌دهی متناسب با چهره همراه با براشینگ حرفه‌ای.", 60, 780000, "https://images.unsplash.com/photo-1560066984-138dadb4c035?auto=format&fit=crop&w=1200&q=88"),
    ("مو", "رنگ و لایت تخصصی", "مشاوره رنگ، تکنیک‌های به‌روز و مراقبت بعد از رنگ.", 180, 2850000, "https://images.unsplash.com/photo-1522337360788-8b13dee7a37e?auto=format&fit=crop&w=1200&q=88"),
    ("مو", "کراتین و احیای مو", "احیای ساقه مو با انتخاب مواد متناسب با بافت مو.", 150, 2450000, "https://images.unsplash.com/photo-1580618672591-eb180b1a973f?auto=format&fit=crop&w=1200&q=88"),
    ("ناخن", "مانیکور روسی و ژل", "مانیکور دقیق، زیرسازی و لاک ژل با ماندگاری بالا.", 75, 690000, "https://images.unsplash.com/photo-1604654894610-df63bc536371?auto=format&fit=crop&w=1200&q=88"),
    ("پوست", "فیشال و آبرسانی", "پاکسازی چندمرحله‌ای و آبرسانی متناسب با نیاز پوست.", 70, 950000, "https://images.unsplash.com/photo-1570172619644-dfd03ed5d881?auto=format&fit=crop&w=1200&q=88"),
    ("میکاپ", "میکاپ حرفه‌ای", "میکاپ ماندگار و شخصی‌سازی‌شده برای مراسم و عکاسی.", 90, 1950000, "https://images.unsplash.com/photo-1487412912498-0447578fcca8?auto=format&fit=crop&w=1200&q=88"),
    ("مژه", "لیفت و لمینت مژه", "فرم‌دهی طبیعی مژه با مواد استاندارد و مراقبت کامل.", 60, 720000, "https://images.unsplash.com/photo-1583001809873-a128495da465?auto=format&fit=crop&w=1200&q=88"),
    ("سایر", "اصلاح و قرینه‌سازی ابرو", "طراحی ابرو براساس فرم چهره با نتیجه‌ای طبیعی.", 35, 420000, "https://images.unsplash.com/photo-1616683693504-3ea7e9ad6fec?auto=format&fit=crop&w=1200&q=88"),
]

STAFF_SEED = [
    ("سارا احمدی", "متخصص رنگ و احیا", 9, 4.9, "https://images.unsplash.com/photo-1494790108377-be9c29b29330?auto=format&fit=crop&w=800&q=88"),
    ("مهسا کریمی", "نیل آرتیست", 7, 4.8, "https://images.unsplash.com/photo-1534528741775-53994a69b2f3?auto=format&fit=crop&w=800&q=88"),
    ("نگار رضایی", "متخصص پوست و میکاپ", 8, 4.9, "https://images.unsplash.com/photo-1544005313-94ddf0286df2?auto=format&fit=crop&w=800&q=88"),
]

GALLERY = [
    "https://images.unsplash.com/photo-1522337660859-02fbefca4702?auto=format&fit=crop&w=1200&q=88",
    "https://images.unsplash.com/photo-1560869713-7d0a29430803?auto=format&fit=crop&w=1200&q=88",
    "https://images.unsplash.com/photo-1562322140-8baeececf3df?auto=format&fit=crop&w=1200&q=88",
    "https://images.unsplash.com/photo-1519014816548-bf5fe059798b?auto=format&fit=crop&w=1200&q=88",
    "https://images.unsplash.com/photo-1595476108010-b4d1f102b1b1?auto=format&fit=crop&w=1200&q=88",
    "https://images.unsplash.com/photo-1610992015732-2449b76344bc?auto=format&fit=crop&w=1200&q=88",
]


def register_booking_os(app, db_path):
    def local_now():
        return datetime.now(BUSINESS_TIMEZONE).replace(tzinfo=None)

    def db():
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=8000")
        return conn

    def now():
        return local_now().isoformat(timespec="seconds")

    def parse(raw, fallback=None):
        try:
            return json.loads(raw or "{}")
        except Exception:
            return fallback if fallback is not None else {}

    def mobile(value):
        value = re.sub(r"\D", "", str(value or ""))
        if value.startswith("0098"):
            value = "0" + value[4:]
        elif value.startswith("98") and len(value) == 12:
            value = "0" + value[2:]
        elif value.startswith("9") and len(value) == 10:
            value = "0" + value
        return value if re.fullmatch(r"09\d{9}", value) else ""

    def ensure_schema():
        conn = db()
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS businesses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                lead_id INTEGER UNIQUE,
                slug TEXT UNIQUE NOT NULL,
                vertical TEXT NOT NULL,
                name TEXT NOT NULL,
                logo_url TEXT,
                primary_color TEXT NOT NULL DEFAULT '#6f294b',
                secondary_color TEXT NOT NULL DEFAULT '#d8a5b9',
                phone TEXT,
                city TEXT,
                address TEXT,
                instagram TEXT,
                map_query TEXT,
                plan TEXT NOT NULL DEFAULT 'starter',
                is_demo INTEGER NOT NULL DEFAULT 1,
                settings_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                FOREIGN KEY(lead_id) REFERENCES leads(id)
            );
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                business_id INTEGER NOT NULL,
                staff_id INTEGER,
                name TEXT NOT NULL,
                phone TEXT NOT NULL,
                pin_hash TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'staff',
                permissions_json TEXT NOT NULL DEFAULT '[]',
                is_active INTEGER NOT NULL DEFAULT 1,
                last_login_at TEXT,
                created_at TEXT NOT NULL,
                UNIQUE(business_id, phone),
                FOREIGN KEY(business_id) REFERENCES businesses(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS customers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                business_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                phone TEXT NOT NULL,
                pin_hash TEXT,
                birth_date TEXT,
                loyalty_points INTEGER NOT NULL DEFAULT 0,
                last_visit_at TEXT,
                created_at TEXT NOT NULL,
                UNIQUE(business_id, phone),
                FOREIGN KEY(business_id) REFERENCES businesses(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS staff (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                business_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                role TEXT NOT NULL,
                bio TEXT,
                experience_years INTEGER NOT NULL DEFAULT 0,
                rating REAL NOT NULL DEFAULT 5,
                image_url TEXT,
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                FOREIGN KEY(business_id) REFERENCES businesses(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS services (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                business_id INTEGER NOT NULL,
                category TEXT NOT NULL,
                slug TEXT NOT NULL,
                name TEXT NOT NULL,
                description TEXT,
                duration_minutes INTEGER NOT NULL,
                price INTEGER NOT NULL,
                image_url TEXT,
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                UNIQUE(business_id, slug),
                FOREIGN KEY(business_id) REFERENCES businesses(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS staff_services (
                business_id INTEGER NOT NULL,
                staff_id INTEGER NOT NULL,
                service_id INTEGER NOT NULL,
                PRIMARY KEY(staff_id, service_id),
                FOREIGN KEY(business_id) REFERENCES businesses(id) ON DELETE CASCADE,
                FOREIGN KEY(staff_id) REFERENCES staff(id) ON DELETE CASCADE,
                FOREIGN KEY(service_id) REFERENCES services(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS staff_schedules (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                business_id INTEGER NOT NULL,
                staff_id INTEGER NOT NULL,
                weekday INTEGER NOT NULL,
                start_time TEXT NOT NULL,
                end_time TEXT NOT NULL,
                is_available INTEGER NOT NULL DEFAULT 1,
                UNIQUE(staff_id, weekday),
                FOREIGN KEY(business_id) REFERENCES businesses(id) ON DELETE CASCADE,
                FOREIGN KEY(staff_id) REFERENCES staff(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS appointments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                business_id INTEGER NOT NULL,
                customer_id INTEGER NOT NULL,
                service_id INTEGER NOT NULL,
                staff_id INTEGER NOT NULL,
                starts_at TEXT NOT NULL,
                ends_at TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'confirmed',
                price INTEGER NOT NULL,
                notes TEXT,
                created_at TEXT NOT NULL,
                cancelled_at TEXT,
                FOREIGN KEY(business_id) REFERENCES businesses(id) ON DELETE CASCADE,
                FOREIGN KEY(customer_id) REFERENCES customers(id),
                FOREIGN KEY(service_id) REFERENCES services(id),
                FOREIGN KEY(staff_id) REFERENCES staff(id)
            );
            CREATE TABLE IF NOT EXISTS favorites (
                business_id INTEGER NOT NULL,
                customer_id INTEGER NOT NULL,
                service_id INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY(customer_id, service_id),
                FOREIGN KEY(business_id) REFERENCES businesses(id) ON DELETE CASCADE,
                FOREIGN KEY(customer_id) REFERENCES customers(id) ON DELETE CASCADE,
                FOREIGN KEY(service_id) REFERENCES services(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS campaigns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                business_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                campaign_type TEXT NOT NULL,
                trigger_days INTEGER,
                template TEXT NOT NULL,
                is_active INTEGER NOT NULL DEFAULT 0,
                is_pro INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                FOREIGN KEY(business_id) REFERENCES businesses(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                business_id INTEGER NOT NULL,
                customer_id INTEGER,
                campaign_id INTEGER,
                channel TEXT NOT NULL DEFAULT 'sms',
                body TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'queued',
                sent_at TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY(business_id) REFERENCES businesses(id) ON DELETE CASCADE,
                FOREIGN KEY(customer_id) REFERENCES customers(id),
                FOREIGN KEY(campaign_id) REFERENCES campaigns(id)
            );
            CREATE TABLE IF NOT EXISTS reviews (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                business_id INTEGER NOT NULL,
                customer_id INTEGER,
                appointment_id INTEGER,
                rating INTEGER NOT NULL CHECK(rating BETWEEN 1 AND 5),
                body TEXT,
                is_approved INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                FOREIGN KEY(business_id) REFERENCES businesses(id) ON DELETE CASCADE,
                FOREIGN KEY(customer_id) REFERENCES customers(id),
                FOREIGN KEY(appointment_id) REFERENCES appointments(id)
            );
            CREATE TABLE IF NOT EXISTS payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                business_id INTEGER NOT NULL,
                appointment_id INTEGER,
                customer_id INTEGER,
                amount INTEGER NOT NULL,
                provider TEXT,
                reference TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                paid_at TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY(business_id) REFERENCES businesses(id) ON DELETE CASCADE,
                FOREIGN KEY(appointment_id) REFERENCES appointments(id),
                FOREIGN KEY(customer_id) REFERENCES customers(id)
            );
            CREATE INDEX IF NOT EXISTS idx_users_tenant ON users(business_id, role, is_active);
            CREATE INDEX IF NOT EXISTS idx_customers_tenant ON customers(business_id, phone, last_visit_at);
            CREATE INDEX IF NOT EXISTS idx_staff_tenant ON staff(business_id, is_active);
            CREATE INDEX IF NOT EXISTS idx_services_tenant ON services(business_id, is_active, category);
            CREATE INDEX IF NOT EXISTS idx_appointments_tenant ON appointments(business_id, starts_at, status);
            CREATE INDEX IF NOT EXISTS idx_campaigns_tenant ON campaigns(business_id, is_active);
            CREATE INDEX IF NOT EXISTS idx_messages_tenant ON messages(business_id, status);
            CREATE INDEX IF NOT EXISTS idx_reviews_tenant ON reviews(business_id, is_approved);
            CREATE INDEX IF NOT EXISTS idx_payments_tenant ON payments(business_id, status);
            """
        )
        conn.commit()
        conn.close()

    def ensure_showcase():
        conn = db()
        lead = conn.execute("SELECT * FROM leads WHERE slug=?", (SHOWCASE_SLUG,)).fetchone()
        if not lead:
            settings = {
                "tagline": "زیبایی، با آرامش و انتخاب خودت",
                "experience": 11,
                "customers_served": 3800,
                "hero_image": "https://images.unsplash.com/photo-1521590832167-7bcbfaa6381f?auto=format&fit=crop&w=2000&q=90",
                "gallery": GALLERY,
            }
            cur = conn.execute(
                """INSERT INTO leads(slug,business_name,vertical,phone,city,address,instagram,accent,meta_json,status,created_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (SHOWCASE_SLUG, "سالن زیبایی مروارید", "beauty", "02126711234", "تهران", "پاسداران، بوستان پنجم", "morvarid.beauty", "#6f294b", json.dumps(settings, ensure_ascii=False), "demo", now()),
            )
            conn.commit()
            lead = conn.execute("SELECT * FROM leads WHERE id=?", (cur.lastrowid,)).fetchone()
        conn.close()
        return provision_business(dict(lead))

    def provision_business(lead):
        conn = db()
        row = conn.execute("SELECT * FROM businesses WHERE lead_id=?", (lead["id"],)).fetchone()
        meta = parse(lead.get("meta_json"))
        if not row:
            settings = {
                "tagline": meta.get("tagline") or "زیبایی، با آرامش و انتخاب خودت",
                "experience": int(meta.get("experience") or 8),
                "customers_served": int(meta.get("customers_served") or 2400),
                "hero_image": meta.get("hero_image") or "https://images.unsplash.com/photo-1521590832167-7bcbfaa6381f?auto=format&fit=crop&w=2000&q=90",
                "gallery": meta.get("gallery") or GALLERY,
                "working_hours": "شنبه تا پنجشنبه، ۱۰ تا ۲۰",
            }
            cur = conn.execute(
                """INSERT INTO businesses(lead_id,slug,vertical,name,logo_url,primary_color,secondary_color,phone,city,address,instagram,map_query,plan,is_demo,settings_json,created_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (lead["id"], lead["slug"], lead.get("vertical") or "beauty", lead["business_name"], lead.get("logo_url"), lead.get("accent") or "#6f294b", "#d8a5b9", lead.get("phone"), lead.get("city"), lead.get("address"), lead.get("instagram"), f"{lead.get('address') or ''} {lead.get('city') or ''}", "starter", 1, json.dumps(settings, ensure_ascii=False), now()),
            )
            business_id = cur.lastrowid
            for index, item in enumerate(SERVICE_SEED, 1):
                category, name, description, duration, price, image = item
                conn.execute(
                    "INSERT INTO services(business_id,category,slug,name,description,duration_minutes,price,image_url,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                    (business_id, category, f"service-{index}", name, description, duration, price, image, now()),
                )
            for name, role, years, rating, image in STAFF_SEED:
                conn.execute(
                    "INSERT INTO staff(business_id,name,role,bio,experience_years,rating,image_url,created_at) VALUES(?,?,?,?,?,?,?,?)",
                    (business_id, name, role, "رزروهای این هفته باز است؛ زمان مناسب را آنلاین انتخاب کنید.", years, rating, image, now()),
                )
            staff_rows = conn.execute("SELECT id FROM staff WHERE business_id=?", (business_id,)).fetchall()
            service_rows = conn.execute("SELECT id,category FROM services WHERE business_id=?", (business_id,)).fetchall()
            for pos, staff_row in enumerate(staff_rows):
                for service in service_rows:
                    if pos == 0 and service["category"] in {"مو", "سایر"} or pos == 1 and service["category"] in {"ناخن", "مژه"} or pos == 2 and service["category"] in {"پوست", "میکاپ", "سایر"}:
                        conn.execute("INSERT OR IGNORE INTO staff_services(business_id,staff_id,service_id) VALUES(?,?,?)", (business_id, staff_row["id"], service["id"]))
                for weekday in range(6):
                    conn.execute("INSERT OR IGNORE INTO staff_schedules(business_id,staff_id,weekday,start_time,end_time) VALUES(?,?,?,?,?)", (business_id, staff_row["id"], weekday, "10:00", "20:00"))
            campaigns = [
                ("یادآوری ترمیم مو", "renewal", 45, "{name} عزیز، احتمالاً زمان ترمیم و رسیدگی دوباره به موهایت رسیده. زمان مناسب را رزرو کن.", 0, 1),
                ("هدیه تولد", "birthday", None, "تولدت مبارک {name} عزیز! یک هدیه زیبایی ویژه برای تو داریم.", 0, 1),
                ("دلمون برات تنگ شده", "inactive", 60, "{name} عزیز، مدتیه ندیدیمت. این پیشنهاد شخصی فقط برای بازگشت توست.", 0, 1),
                ("درخواست نظر بعد از مراجعه", "review", 1, "از تجربه‌ات راضی بودی؟ با ثبت نظرت به ما کمک کن بهتر شویم.", 1, 0),
                ("هدیه اولین رزرو", "welcome", None, "{name} عزیز، به باشگاه مشتریان ما خوش آمدی؛ اولین پیشنهاد شخصی‌ات آماده است.", 1, 0),
            ]
            for campaign in campaigns:
                conn.execute("INSERT INTO campaigns(business_id,name,campaign_type,trigger_days,template,is_active,is_pro,created_at) VALUES(?,?,?,?,?,?,?,?)", (business_id, *campaign, now()))
            conn.execute(
                "INSERT INTO users(business_id,name,phone,pin_hash,role,permissions_json,created_at) VALUES(?,?,?,?,?,?,?)",
                (business_id, "مدیر سالن", "09120000000", generate_password_hash("1234"), "owner", json.dumps(["dashboard", "calendar", "customers", "services", "staff", "marketing"], ensure_ascii=False), now()),
            )
            reviews = [
                (5, "رزرو خیلی راحت بود و دقیقاً سر ساعت پذیرش شدم. نتیجه رنگ مو هم عالی شد."),
                (5, "محیط آرام، برخورد حرفه‌ای و یادآوری وقت واقعاً به‌موقع بود."),
                (4, "برای اولین بار بدون تماس تلفنی وقت مناسب خودم را انتخاب کردم؛ تجربه خیلی خوبی بود."),
            ]
            for idx, (rating, body) in enumerate(reviews, 1):
                customer_phone = f"0912111000{idx}"
                cur_customer = conn.execute("INSERT INTO customers(business_id,name,phone,loyalty_points,last_visit_at,created_at) VALUES(?,?,?,?,?,?)", (business_id, ["الهام مرادی", "آوا کاظمی", "نسترن محمدی"][idx - 1], customer_phone, 120 + idx * 30, (local_now() - timedelta(days=idx * 24)).isoformat(timespec="seconds"), now()))
                service = service_rows[(idx - 1) % len(service_rows)]
                staff_row = staff_rows[(idx - 1) % len(staff_rows)]
                starts = local_now() - timedelta(days=idx * 24)
                cur_appointment = conn.execute("INSERT INTO appointments(business_id,customer_id,service_id,staff_id,starts_at,ends_at,status,price,created_at) VALUES(?,?,?,?,?,?,?,?,?)", (business_id, cur_customer.lastrowid, service["id"], staff_row["id"], starts.isoformat(timespec="minutes"), (starts + timedelta(minutes=60)).isoformat(timespec="minutes"), "completed", 950000 + idx * 180000, now()))
                conn.execute("INSERT INTO reviews(business_id,customer_id,appointment_id,rating,body,is_approved,created_at) VALUES(?,?,?,?,?,1,?)", (business_id, cur_customer.lastrowid, cur_appointment.lastrowid, rating, body, now()))
                conn.execute("INSERT INTO payments(business_id,appointment_id,customer_id,amount,provider,reference,status,paid_at,created_at) VALUES(?,?,?,?,?,?,?,?,?)", (business_id, cur_appointment.lastrowid, cur_customer.lastrowid, 950000 + idx * 180000, "in_person", f"DEMO-{idx}", "paid", starts.isoformat(timespec="seconds"), now()))
            # Upcoming appointments make the dashboard useful immediately.
            for idx in range(5):
                customer = conn.execute("SELECT id FROM customers WHERE business_id=? ORDER BY id LIMIT 1 OFFSET ?", (business_id, idx % 3)).fetchone()
                start = local_now().replace(hour=10 + idx * 2, minute=0, second=0, microsecond=0) + timedelta(days=0 if idx < 4 else 1)
                conn.execute("INSERT INTO appointments(business_id,customer_id,service_id,staff_id,starts_at,ends_at,status,price,created_at) VALUES(?,?,?,?,?,?,?,?,?)", (business_id, customer["id"], service_rows[idx % len(service_rows)]["id"], staff_rows[idx % len(staff_rows)]["id"], start.isoformat(timespec="minutes"), (start + timedelta(minutes=75)).isoformat(timespec="minutes"), "confirmed", 780000 + idx * 220000, now()))
            conn.commit()
            row = conn.execute("SELECT * FROM businesses WHERE id=?", (business_id,)).fetchone()
        if row["plan"] != "pro":
            conn.execute("UPDATE campaigns SET is_active=0 WHERE business_id=? AND is_pro=1", (row["id"],))
            conn.commit()
        conn.close()
        return dict(row)

    def load_business(slug):
        conn = db()
        row = conn.execute("SELECT * FROM businesses WHERE slug=?", (slug,)).fetchone()
        if not row:
            lead = conn.execute("SELECT * FROM leads WHERE slug=? AND vertical='beauty'", (slug,)).fetchone()
            conn.close()
            return provision_business(dict(lead)) if lead else None
        conn.close()
        return dict(row)

    def business_context(slug):
        business = load_business(slug)
        if not business:
            return None
        business["settings"] = parse(business.get("settings_json"))
        conn = db()
        services = [dict(r) for r in conn.execute("SELECT * FROM services WHERE business_id=? AND is_active=1 ORDER BY category,id", (business["id"],)).fetchall()]
        staff_rows = [dict(r) for r in conn.execute("SELECT * FROM staff WHERE business_id=? AND is_active=1 ORDER BY id", (business["id"],)).fetchall()]
        for member in staff_rows:
            member["service_ids"] = [r["service_id"] for r in conn.execute("SELECT service_id FROM staff_services WHERE business_id=? AND staff_id=?", (business["id"], member["id"])).fetchall()]
            member["days"] = [r["weekday"] for r in conn.execute("SELECT weekday FROM staff_schedules WHERE business_id=? AND staff_id=? AND is_available=1", (business["id"], member["id"])).fetchall()]
        reviews = [dict(r) for r in conn.execute("""SELECT r.*,c.name customer_name FROM reviews r LEFT JOIN customers c ON c.id=r.customer_id AND c.business_id=r.business_id WHERE r.business_id=? AND r.is_approved=1 ORDER BY r.id DESC LIMIT 8""", (business["id"],)).fetchall()]
        conn.close()
        categories = []
        for service in services:
            if service["category"] not in categories:
                categories.append(service["category"])
        return business, services, staff_rows, reviews, categories

    def current_customer(business_id):
        customer_id = session.get("beauty_customer_id")
        if not customer_id or session.get("beauty_customer_business_id") != business_id:
            return None
        conn = db()
        row = conn.execute("SELECT * FROM customers WHERE id=? AND business_id=?", (customer_id, business_id)).fetchone()
        conn.close()
        return dict(row) if row else None

    def current_tenant_user(business_id):
        if session.get("admin"):
            return {"id": 0, "name": "مدیر PPOS", "role": "platform_admin", "permissions": ["*"]}
        user_id = session.get("tenant_user_id")
        if not user_id or session.get("tenant_business_id") != business_id:
            return None
        conn = db()
        row = conn.execute("SELECT * FROM users WHERE id=? AND business_id=? AND is_active=1", (user_id, business_id)).fetchone()
        conn.close()
        if not row:
            return None
        result = dict(row)
        result["permissions"] = parse(result.get("permissions_json"), [])
        return result

    def tenant_admin_required(fn):
        @wraps(fn)
        def wrapped(slug, *args, **kwargs):
            business = load_business(slug)
            if not business:
                abort(404)
            user = current_tenant_user(business["id"])
            if not user:
                return redirect(url_for("beauty_admin_login", slug=slug, next=request.path))
            return fn(slug, business, user, *args, **kwargs)
        return wrapped

    def require_permission(user, permission):
        if user.get("role") in {"owner", "platform_admin"} or "*" in user.get("permissions", []):
            return
        if permission not in user.get("permissions", []):
            abort(403)

    def queue_due_messages(conn, business):
        """Idempotently materialize messages for active tenant campaign rules."""
        campaigns = conn.execute("SELECT * FROM campaigns WHERE business_id=? AND is_active=1 AND (is_pro=0 OR ?='pro')", (business["id"], business["plan"])).fetchall()
        queued = 0
        for campaign in campaigns:
            if campaign["campaign_type"] == "review":
                candidates = conn.execute("""SELECT a.customer_id,c.name,a.id appointment_id FROM appointments a JOIN customers c ON c.id=a.customer_id AND c.business_id=a.business_id WHERE a.business_id=? AND a.status='completed' AND NOT EXISTS (SELECT 1 FROM messages m WHERE m.business_id=a.business_id AND m.campaign_id=? AND m.customer_id=a.customer_id AND json_extract(m.body,'$.appointment_id')=a.id)""", (business["id"], campaign["id"])).fetchall()
            elif campaign["campaign_type"] in {"inactive", "renewal"} and campaign["trigger_days"]:
                candidates = conn.execute("""SELECT c.id customer_id,c.name,NULL appointment_id FROM customers c WHERE c.business_id=? AND c.last_visit_at IS NOT NULL AND datetime(c.last_visit_at)<=datetime('now',?) AND NOT EXISTS (SELECT 1 FROM messages m WHERE m.business_id=c.business_id AND m.campaign_id=? AND m.customer_id=c.id)""", (business["id"], f"-{campaign['trigger_days']} days", campaign["id"])).fetchall()
            elif campaign["campaign_type"] == "birthday":
                candidates = conn.execute("""SELECT c.id customer_id,c.name,NULL appointment_id FROM customers c WHERE c.business_id=? AND substr(c.birth_date,6,5)=strftime('%m-%d','now') AND NOT EXISTS (SELECT 1 FROM messages m WHERE m.business_id=c.business_id AND m.campaign_id=? AND m.customer_id=c.id AND date(m.created_at)=date('now'))""", (business["id"], campaign["id"])).fetchall()
            else:
                candidates = []
            for candidate in candidates:
                payload = {"text": campaign["template"].replace("{name}", candidate["name"].split(" ")[0]), "appointment_id": candidate["appointment_id"]}
                conn.execute("INSERT INTO messages(business_id,customer_id,campaign_id,channel,body,status,created_at) VALUES(?,?,?,?,?,'queued',?)", (business["id"], candidate["customer_id"], campaign["id"], "sms", json.dumps(payload, ensure_ascii=False), now()))
                queued += 1
        return queued

    ensure_schema()
    showcase = ensure_showcase()

    @app.get("/beauty-os")
    def beauty_showcase():
        return redirect(url_for("beauty_public", slug=showcase["slug"]))

    @app.get("/demo/<slug>")
    def beauty_public(slug):
        ctx = business_context(slug)
        if not ctx:
            return render_template("not_found.html"), 404
        business, services, staff_rows, reviews, categories = ctx
        customer = current_customer(business["id"])
        conn = db()
        stats = {
            "reviews": conn.execute("SELECT COUNT(*) c FROM reviews WHERE business_id=? AND is_approved=1", (business["id"],)).fetchone()["c"] + 184,
            "team": len(staff_rows),
            "rating": round(sum(r["rating"] for r in reviews) / len(reviews), 1) if reviews else 5,
        }
        conn.execute("INSERT INTO events(lead_id,event_type,meta_json,created_at) SELECT lead_id,'beauty_os_open',?,? FROM businesses WHERE id=? AND lead_id IS NOT NULL", (json.dumps({"path": request.path}, ensure_ascii=False), now(), business["id"]))
        conn.commit(); conn.close()
        return render_template("beauty_public.html", business=business, services=services, staff=staff_rows, reviews=reviews, categories=categories, stats=stats, customer=customer)

    @app.get("/api/demo/<slug>/availability")
    def beauty_availability(slug):
        business = load_business(slug)
        if not business:
            return jsonify({"ok": False, "error": "کسب‌وکار پیدا نشد."}), 404
        service_id = request.args.get("service_id", type=int)
        staff_id = request.args.get("staff_id", type=int)
        chosen_date = request.args.get("date", "")
        conn = db()
        service = conn.execute("SELECT * FROM services WHERE id=? AND business_id=? AND is_active=1", (service_id, business["id"])).fetchone()
        member = conn.execute("SELECT * FROM staff WHERE id=? AND business_id=? AND is_active=1", (staff_id, business["id"])).fetchone()
        if not service or not member:
            conn.close(); return jsonify({"ok": False, "error": "خدمت یا متخصص معتبر نیست."}), 400
        try:
            day = datetime.strptime(chosen_date, "%Y-%m-%d").date()
        except ValueError:
            conn.close(); return jsonify({"ok": False, "error": "تاریخ معتبر نیست."}), 400
        weekday = (day.weekday() + 2) % 7  # Saturday=0
        schedule = conn.execute("SELECT * FROM staff_schedules WHERE business_id=? AND staff_id=? AND weekday=? AND is_available=1", (business["id"], staff_id, weekday)).fetchone()
        if not schedule or day < local_now().date() or day > local_now().date() + timedelta(days=30):
            conn.close(); return jsonify({"ok": True, "slots": []})
        existing = [dict(r) for r in conn.execute("SELECT starts_at,ends_at FROM appointments WHERE business_id=? AND staff_id=? AND starts_at LIKE ? AND status NOT IN ('cancelled','no_show')", (business["id"], staff_id, f"{chosen_date}%")).fetchall()]
        conn.close()
        start_hour = int(schedule["start_time"][:2])
        end_hour = int(schedule["end_time"][:2])
        slots = []
        for hour in range(start_hour, end_hour):
            for minute in (0, 30):
                candidate = datetime.strptime(f"{chosen_date} {hour:02d}:{minute:02d}", "%Y-%m-%d %H:%M")
                candidate_end = candidate + timedelta(minutes=service["duration_minutes"])
                if candidate_end.time() > datetime.strptime(schedule["end_time"], "%H:%M").time():
                    continue
                if any(candidate < datetime.fromisoformat(item["ends_at"]) and candidate_end > datetime.fromisoformat(item["starts_at"]) for item in existing):
                    continue
                slots.append(f"{hour:02d}:{minute:02d}")
        return jsonify({"ok": True, "slots": slots[:12]})

    @app.post("/api/demo/<slug>/book")
    def beauty_book(slug):
        business = load_business(slug)
        if not business:
            return jsonify({"ok": False, "error": "سالن پیدا نشد."}), 404
        payload = request.get_json(silent=True) or request.form.to_dict()
        service_id = int(payload.get("service_id") or 0)
        staff_id = int(payload.get("staff_id") or 0)
        name = str(payload.get("name") or "").strip()[:80]
        phone = mobile(payload.get("phone"))
        chosen_date = str(payload.get("date") or "")
        chosen_time = str(payload.get("time") or "")
        if not name or not phone or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", chosen_date) or not re.fullmatch(r"\d{2}:\d{2}", chosen_time):
            return jsonify({"ok": False, "error": "نام، موبایل، تاریخ و ساعت را کامل وارد کنید."}), 400
        try:
            starts = datetime.strptime(f"{chosen_date} {chosen_time}", "%Y-%m-%d %H:%M")
        except ValueError:
            return jsonify({"ok": False, "error": "زمان انتخاب‌شده معتبر نیست."}), 400
        if starts < local_now() - timedelta(minutes=5) or starts > local_now() + timedelta(days=30):
            return jsonify({"ok": False, "error": "این زمان گذشته است؛ یک زمان جدید انتخاب کنید."}), 400
        conn = db()
        conn.execute("BEGIN IMMEDIATE")
        service = conn.execute("SELECT * FROM services WHERE id=? AND business_id=? AND is_active=1", (service_id, business["id"])).fetchone()
        member = conn.execute("SELECT * FROM staff WHERE id=? AND business_id=? AND is_active=1", (staff_id, business["id"])).fetchone()
        permitted = conn.execute("SELECT 1 FROM staff_services WHERE business_id=? AND staff_id=? AND service_id=?", (business["id"], staff_id, service_id)).fetchone()
        if not service or not member or not permitted:
            conn.rollback(); conn.close(); return jsonify({"ok": False, "error": "خدمت یا متخصص معتبر نیست."}), 400
        ends = starts + timedelta(minutes=service["duration_minutes"])
        weekday = (starts.date().weekday() + 2) % 7
        schedule = conn.execute("SELECT * FROM staff_schedules WHERE business_id=? AND staff_id=? AND weekday=? AND is_available=1", (business["id"], staff_id, weekday)).fetchone()
        collision = conn.execute("SELECT 1 FROM appointments WHERE business_id=? AND staff_id=? AND starts_at<? AND ends_at>? AND status NOT IN ('cancelled','no_show')", (business["id"], staff_id, ends.isoformat(timespec="minutes"), starts.isoformat(timespec="minutes"))).fetchone()
        outside_schedule = not schedule or chosen_time < schedule["start_time"] or ends.strftime("%H:%M") > schedule["end_time"]
        if collision or outside_schedule:
            conn.rollback(); conn.close(); return jsonify({"ok": False, "error": "این زمان دیگر در دسترس نیست؛ یک زمان دیگر انتخاب کنید."}), 409
        customer = conn.execute("SELECT * FROM customers WHERE business_id=? AND phone=?", (business["id"], phone)).fetchone()
        if customer:
            customer_id = customer["id"]
            conn.execute("UPDATE customers SET name=? WHERE id=? AND business_id=?", (name, customer_id, business["id"]))
        else:
            customer_id = conn.execute("INSERT INTO customers(business_id,name,phone,created_at) VALUES(?,?,?,?)", (business["id"], name, phone, now())).lastrowid
        appointment_id = conn.execute(
            "INSERT INTO appointments(business_id,customer_id,service_id,staff_id,starts_at,ends_at,status,price,notes,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (business["id"], customer_id, service_id, staff_id, starts.isoformat(timespec="minutes"), ends.isoformat(timespec="minutes"), "confirmed", service["price"], str(payload.get("notes") or "")[:500], now()),
        ).lastrowid
        conn.execute("UPDATE customers SET loyalty_points=loyalty_points+10 WHERE id=? AND business_id=?", (customer_id, business["id"]))
        conn.commit(); conn.close()
        return jsonify({"ok": True, "appointment_id": appointment_id, "code": f"{business['id']:02d}-{appointment_id:05d}", "account_url": url_for("beauty_customer_login", slug=slug), "message": "وقت شما با موفقیت ثبت شد."})

    @app.route("/demo/<slug>/login", methods=["GET", "POST"])
    def beauty_customer_login(slug):
        business = load_business(slug)
        if not business:
            abort(404)
        if current_customer(business["id"]):
            return redirect(url_for("beauty_customer_account", slug=slug))
        if request.method == "POST":
            phone = mobile(request.form.get("phone"))
            pin = str(request.form.get("pin") or "")
            name = str(request.form.get("name") or "").strip()[:80]
            if not phone or not re.fullmatch(r"\d{4,8}", pin):
                flash("شماره موبایل معتبر و رمز ۴ تا ۸ رقمی وارد کنید.", "error")
            else:
                conn = db()
                customer = conn.execute("SELECT * FROM customers WHERE business_id=? AND phone=?", (business["id"], phone)).fetchone()
                if customer and customer["pin_hash"]:
                    if check_password_hash(customer["pin_hash"], pin):
                        session["beauty_customer_id"] = customer["id"]
                        session["beauty_customer_business_id"] = business["id"]
                        conn.close(); return redirect(url_for("beauty_customer_account", slug=slug))
                    flash("رمز واردشده درست نیست.", "error")
                elif customer:
                    if not name:
                        flash("برای فعال‌کردن حساب، نامت را هم وارد کن.", "error")
                    else:
                        conn.execute("UPDATE customers SET name=?,pin_hash=? WHERE id=? AND business_id=?", (name, generate_password_hash(pin), customer["id"], business["id"]))
                        conn.commit()
                        session["beauty_customer_id"] = customer["id"]
                        session["beauty_customer_business_id"] = business["id"]
                        conn.close(); return redirect(url_for("beauty_customer_account", slug=slug))
                elif not name:
                    flash("برای ثبت‌نام، نامت را هم وارد کن.", "error")
                else:
                    customer_id = conn.execute("INSERT INTO customers(business_id,name,phone,pin_hash,created_at) VALUES(?,?,?,?,?)", (business["id"], name, phone, generate_password_hash(pin), now())).lastrowid
                    conn.commit()
                    session["beauty_customer_id"] = customer_id
                    session["beauty_customer_business_id"] = business["id"]
                    conn.close(); return redirect(url_for("beauty_customer_account", slug=slug))
                conn.close()
        return render_template("beauty_login.html", business=business)

    @app.get("/demo/<slug>/logout")
    def beauty_customer_logout(slug):
        session.pop("beauty_customer_id", None)
        session.pop("beauty_customer_business_id", None)
        return redirect(url_for("beauty_public", slug=slug))

    @app.get("/demo/<slug>/account")
    def beauty_customer_account(slug):
        business = load_business(slug)
        if not business:
            abort(404)
        customer = current_customer(business["id"])
        if not customer:
            return redirect(url_for("beauty_customer_login", slug=slug))
        conn = db()
        appointments = [dict(r) for r in conn.execute("""SELECT a.*,s.name service_name,s.image_url,st.name staff_name FROM appointments a JOIN services s ON s.id=a.service_id AND s.business_id=a.business_id JOIN staff st ON st.id=a.staff_id AND st.business_id=a.business_id WHERE a.business_id=? AND a.customer_id=? ORDER BY a.starts_at DESC""", (business["id"], customer["id"])).fetchall()]
        favorites = [dict(r) for r in conn.execute("""SELECT s.* FROM favorites f JOIN services s ON s.id=f.service_id AND s.business_id=f.business_id WHERE f.business_id=? AND f.customer_id=? ORDER BY f.created_at DESC""", (business["id"], customer["id"])).fetchall()]
        offers = [dict(r) for r in conn.execute("SELECT * FROM campaigns WHERE business_id=? AND is_active=1 ORDER BY is_pro,id LIMIT 4", (business["id"],)).fetchall()]
        review_appointments = {r["appointment_id"] for r in conn.execute("SELECT appointment_id FROM reviews WHERE business_id=? AND customer_id=? AND appointment_id IS NOT NULL", (business["id"], customer["id"])).fetchall()}
        conn.close()
        return render_template("beauty_account.html", business=business, customer=customer, appointments=appointments, favorites=favorites, offers=offers, review_appointments=review_appointments)

    @app.post("/demo/<slug>/account/cancel/<int:appointment_id>")
    def beauty_cancel_appointment(slug, appointment_id):
        business = load_business(slug)
        if not business:
            abort(404)
        customer = current_customer(business["id"])
        if not customer:
            return redirect(url_for("beauty_customer_login", slug=slug))
        conn = db()
        appointment = conn.execute("SELECT * FROM appointments WHERE id=? AND business_id=? AND customer_id=? AND status='confirmed'", (appointment_id, business["id"], customer["id"])).fetchone()
        changed = bool(appointment and datetime.fromisoformat(appointment["starts_at"]) > local_now() + timedelta(hours=12))
        if changed:
            conn.execute("UPDATE appointments SET status='cancelled',cancelled_at=? WHERE id=? AND business_id=? AND customer_id=?", (now(), appointment_id, business["id"], customer["id"]))
        conn.commit(); conn.close()
        flash("وقت با موفقیت لغو شد." if changed else "لغو آنلاین فقط تا ۱۲ ساعت قبل از وقت ممکن است.", "success" if changed else "error")
        return redirect(url_for("beauty_customer_account", slug=slug))

    @app.post("/demo/<slug>/favorite/<int:service_id>")
    def beauty_toggle_favorite(slug, service_id):
        business = load_business(slug)
        if not business:
            return jsonify({"ok": False}), 404
        customer = current_customer(business["id"])
        if not customer:
            return jsonify({"ok": False, "login": url_for("beauty_customer_login", slug=slug)}), 401
        conn = db()
        service = conn.execute("SELECT id FROM services WHERE id=? AND business_id=? AND is_active=1", (service_id, business["id"])).fetchone()
        existing = conn.execute("SELECT 1 FROM favorites WHERE business_id=? AND customer_id=? AND service_id=?", (business["id"], customer["id"], service_id)).fetchone()
        if not service:
            conn.close(); return jsonify({"ok": False}), 404
        if existing:
            conn.execute("DELETE FROM favorites WHERE business_id=? AND customer_id=? AND service_id=?", (business["id"], customer["id"], service_id)); active = False
        else:
            conn.execute("INSERT INTO favorites(business_id,customer_id,service_id,created_at) VALUES(?,?,?,?)", (business["id"], customer["id"], service_id, now())); active = True
        conn.commit(); conn.close()
        return jsonify({"ok": True, "active": active})

    @app.post("/demo/<slug>/account/review/<int:appointment_id>")
    def beauty_add_review(slug, appointment_id):
        business = load_business(slug)
        if not business:
            abort(404)
        customer = current_customer(business["id"])
        if not customer:
            return redirect(url_for("beauty_customer_login", slug=slug))
        rating = request.form.get("rating", type=int)
        body = str(request.form.get("body") or "").strip()[:500]
        conn = db()
        appointment = conn.execute("SELECT id FROM appointments WHERE id=? AND business_id=? AND customer_id=? AND status='completed'", (appointment_id, business["id"], customer["id"])).fetchone()
        existing = conn.execute("SELECT id FROM reviews WHERE business_id=? AND appointment_id=?", (business["id"], appointment_id)).fetchone()
        if appointment and not existing and rating and 1 <= rating <= 5:
            conn.execute("INSERT INTO reviews(business_id,customer_id,appointment_id,rating,body,is_approved,created_at) VALUES(?,?,?,?,?,0,?)", (business["id"], customer["id"], appointment_id, rating, body, now()))
            conn.commit(); flash("ممنون! نظرت بعد از تأیید نمایش داده می‌شود.", "success")
        else:
            flash("امکان ثبت نظر برای این وقت وجود ندارد.", "error")
        conn.close()
        return redirect(url_for("beauty_customer_account", slug=slug))

    @app.route("/demo/<slug>/admin/login", methods=["GET", "POST"])
    def beauty_admin_login(slug):
        business = load_business(slug)
        if not business:
            abort(404)
        if current_tenant_user(business["id"]):
            return redirect(url_for("beauty_admin_dashboard", slug=slug))
        if request.method == "POST":
            phone = mobile(request.form.get("phone"))
            pin = str(request.form.get("pin") or "")
            conn = db()
            user = conn.execute("SELECT * FROM users WHERE business_id=? AND phone=? AND is_active=1", (business["id"], phone)).fetchone()
            if user and check_password_hash(user["pin_hash"], pin):
                conn.execute("UPDATE users SET last_login_at=? WHERE id=? AND business_id=?", (now(), user["id"], business["id"]))
                conn.commit(); conn.close()
                session["tenant_user_id"] = user["id"]
                session["tenant_business_id"] = business["id"]
                return redirect(url_for("beauty_admin_dashboard", slug=slug))
            conn.close(); flash("شماره یا رمز مدیریت درست نیست.", "error")
        return render_template("beauty_admin_login.html", business=business)

    @app.get("/demo/<slug>/admin/logout")
    def beauty_admin_logout(slug):
        session.pop("tenant_user_id", None); session.pop("tenant_business_id", None)
        return redirect(url_for("beauty_admin_login", slug=slug))

    @app.get("/demo/<slug>/admin")
    @tenant_admin_required
    def beauty_admin_dashboard(slug, business, user):
        section = request.args.get("section", "dashboard")
        allowed = {"dashboard", "calendar", "customers", "services", "staff", "marketing", "reviews"}
        section = section if section in allowed else "dashboard"
        require_permission(user, section)
        conn = db()
        queue_due_messages(conn, business)
        conn.commit()
        today = local_now().date().isoformat()
        month = today[:7]
        metrics = {
            "today": conn.execute("SELECT COUNT(*) c FROM appointments WHERE business_id=? AND starts_at LIKE ? AND status NOT IN ('cancelled','no_show')", (business["id"], f"{today}%")).fetchone()["c"],
            "monthly": conn.execute("SELECT COUNT(*) c FROM appointments WHERE business_id=? AND starts_at LIKE ?", (business["id"], f"{month}%")).fetchone()["c"],
            "new_customers": conn.execute("SELECT COUNT(*) c FROM customers WHERE business_id=? AND created_at LIKE ?", (business["id"], f"{month}%")).fetchone()["c"],
            "returning": conn.execute("SELECT COUNT(*) c FROM (SELECT customer_id FROM appointments WHERE business_id=? GROUP BY customer_id HAVING COUNT(*)>1)", (business["id"],)).fetchone()["c"],
            "revenue": conn.execute("SELECT COALESCE(SUM(price),0) s FROM appointments WHERE business_id=? AND starts_at LIKE ? AND status IN ('confirmed','completed')", (business["id"], f"{month}%")).fetchone()["s"],
        }
        appointments = [dict(r) for r in conn.execute("""SELECT a.*,c.name customer_name,c.phone customer_phone,s.name service_name,st.name staff_name FROM appointments a JOIN customers c ON c.id=a.customer_id AND c.business_id=a.business_id JOIN services s ON s.id=a.service_id AND s.business_id=a.business_id JOIN staff st ON st.id=a.staff_id AND st.business_id=a.business_id WHERE a.business_id=? ORDER BY a.starts_at DESC LIMIT 100""", (business["id"],)).fetchall()]
        customers = [dict(r) for r in conn.execute("""SELECT c.*,(SELECT COUNT(*) FROM appointments a WHERE a.business_id=c.business_id AND a.customer_id=c.id) appointment_count,(SELECT s.name FROM appointments a JOIN services s ON s.id=a.service_id AND s.business_id=a.business_id WHERE a.business_id=c.business_id AND a.customer_id=c.id GROUP BY s.id ORDER BY COUNT(*) DESC LIMIT 1) favorite_service FROM customers c WHERE c.business_id=? ORDER BY COALESCE(c.last_visit_at,c.created_at) DESC""", (business["id"],)).fetchall()]
        for customer in customers:
            customer["inactive"] = bool(customer["last_visit_at"] and datetime.fromisoformat(customer["last_visit_at"]) <= local_now() - timedelta(days=45))
        services = [dict(r) for r in conn.execute("SELECT * FROM services WHERE business_id=? ORDER BY is_active DESC,category,id", (business["id"],)).fetchall()]
        staff_rows = [dict(r) for r in conn.execute("SELECT * FROM staff WHERE business_id=? ORDER BY is_active DESC,id", (business["id"],)).fetchall()]
        for member in staff_rows:
            member["service_names"] = [r["name"] for r in conn.execute("SELECT s.name FROM staff_services ss JOIN services s ON s.id=ss.service_id AND s.business_id=ss.business_id WHERE ss.business_id=? AND ss.staff_id=?", (business["id"], member["id"])).fetchall()]
            member["schedule"] = [dict(r) for r in conn.execute("SELECT * FROM staff_schedules WHERE business_id=? AND staff_id=? ORDER BY weekday", (business["id"], member["id"])).fetchall()]
        campaigns = [dict(r) for r in conn.execute("SELECT * FROM campaigns WHERE business_id=? ORDER BY is_pro,id", (business["id"],)).fetchall()]
        reviews = [dict(r) for r in conn.execute("SELECT r.*,c.name customer_name FROM reviews r LEFT JOIN customers c ON c.id=r.customer_id AND c.business_id=r.business_id WHERE r.business_id=? ORDER BY r.id DESC", (business["id"],)).fetchall()]
        team_users = [dict(r) for r in conn.execute("SELECT id,name,phone,role,permissions_json,is_active,last_login_at FROM users WHERE business_id=? ORDER BY id", (business["id"],)).fetchall()]
        conn.close()
        business["settings"] = parse(business.get("settings_json"))
        for team_user in team_users:
            team_user["permissions"] = parse(team_user.pop("permissions_json"), [])
        return render_template("beauty_admin.html", business=business, user=user, section=section, metrics=metrics, appointments=appointments, customers=customers, services=services, staff=staff_rows, campaigns=campaigns, reviews=reviews, team_users=team_users, current_date=today)

    @app.post("/demo/<slug>/admin/appointment/<int:appointment_id>/status")
    @tenant_admin_required
    def beauty_admin_appointment_status(slug, business, user, appointment_id):
        require_permission(user, "calendar")
        status = request.form.get("status")
        if status not in {"confirmed", "completed", "cancelled", "no_show"}:
            abort(400)
        conn = db()
        previous = conn.execute("SELECT status FROM appointments WHERE id=? AND business_id=?", (appointment_id, business["id"])).fetchone()
        conn.execute("UPDATE appointments SET status=? WHERE id=? AND business_id=?", (status, appointment_id, business["id"]))
        if status == "completed" and previous and previous["status"] != "completed":
            conn.execute("UPDATE customers SET last_visit_at=?,loyalty_points=loyalty_points+50 WHERE id=(SELECT customer_id FROM appointments WHERE id=? AND business_id=?) AND business_id=?", (now(), appointment_id, business["id"], business["id"]))
            queue_due_messages(conn, business)
        conn.commit(); conn.close(); flash("وضعیت رزرو به‌روزرسانی شد.", "success")
        return redirect(url_for("beauty_admin_dashboard", slug=slug, section="calendar"))

    @app.post("/demo/<slug>/admin/services")
    @tenant_admin_required
    def beauty_admin_add_service(slug, business, user):
        require_permission(user, "services")
        name = str(request.form.get("name") or "").strip()[:100]
        category = str(request.form.get("category") or "سایر").strip()[:40]
        if not name:
            flash("نام خدمت لازم است.", "error"); return redirect(url_for("beauty_admin_dashboard", slug=slug, section="services"))
        try:
            duration = max(15, min(480, int(request.form.get("duration") or 60)))
            price = max(0, int(re.sub(r"\D", "", request.form.get("price") or "0")))
        except ValueError:
            flash("مدت و قیمت معتبر نیست.", "error"); return redirect(url_for("beauty_admin_dashboard", slug=slug, section="services"))
        conn = db()
        slug_value = f"custom-{secrets.token_hex(4)}"
        conn.execute("INSERT INTO services(business_id,category,slug,name,description,duration_minutes,price,image_url,created_at) VALUES(?,?,?,?,?,?,?,?,?)", (business["id"], category, slug_value, name, str(request.form.get("description") or "")[:500], duration, price, str(request.form.get("image_url") or "")[:1000], now()))
        conn.commit(); conn.close(); flash("خدمت جدید اضافه شد.", "success")
        return redirect(url_for("beauty_admin_dashboard", slug=slug, section="services"))

    @app.post("/demo/<slug>/admin/service/<int:service_id>")
    @tenant_admin_required
    def beauty_admin_update_service(slug, business, user, service_id):
        require_permission(user, "services")
        action = request.form.get("action", "update")
        conn = db()
        if action == "toggle":
            conn.execute("UPDATE services SET is_active=CASE is_active WHEN 1 THEN 0 ELSE 1 END WHERE id=? AND business_id=?", (service_id, business["id"]))
        elif action == "delete":
            used = conn.execute("SELECT 1 FROM appointments WHERE business_id=? AND service_id=? LIMIT 1", (business["id"], service_id)).fetchone()
            if used:
                conn.execute("UPDATE services SET is_active=0 WHERE id=? AND business_id=?", (service_id, business["id"]))
            else:
                conn.execute("DELETE FROM services WHERE id=? AND business_id=?", (service_id, business["id"]))
        else:
            name = str(request.form.get("name") or "").strip()[:100]
            price = int(re.sub(r"\D", "", request.form.get("price") or "0") or 0)
            duration = max(15, min(480, int(request.form.get("duration") or 60)))
            conn.execute("UPDATE services SET name=?,category=?,description=?,duration_minutes=?,price=?,image_url=? WHERE id=? AND business_id=?", (name, str(request.form.get("category") or "سایر")[:40], str(request.form.get("description") or "")[:500], duration, price, str(request.form.get("image_url") or "")[:1000], service_id, business["id"]))
        conn.commit(); conn.close(); flash("خدمت به‌روزرسانی شد.", "success")
        return redirect(url_for("beauty_admin_dashboard", slug=slug, section="services"))

    @app.post("/demo/<slug>/admin/campaign/<int:campaign_id>/toggle")
    @tenant_admin_required
    def beauty_admin_campaign_toggle(slug, business, user, campaign_id):
        require_permission(user, "marketing")
        conn = db()
        campaign = conn.execute("SELECT * FROM campaigns WHERE id=? AND business_id=?", (campaign_id, business["id"])).fetchone()
        if campaign and (not campaign["is_pro"] or business["plan"] == "pro"):
            conn.execute("UPDATE campaigns SET is_active=CASE is_active WHEN 1 THEN 0 ELSE 1 END WHERE id=? AND business_id=?", (campaign_id, business["id"]))
            conn.commit(); flash("وضعیت کمپین تغییر کرد.", "success")
        else:
            flash("این اتوماسیون در پلن Pro فعال می‌شود.", "error")
        conn.close()
        return redirect(url_for("beauty_admin_dashboard", slug=slug, section="marketing"))

    @app.post("/demo/<slug>/admin/staff/<int:staff_id>/schedule")
    @tenant_admin_required
    def beauty_admin_staff_schedule(slug, business, user, staff_id):
        require_permission(user, "staff")
        start_time = request.form.get("start_time", "10:00")
        end_time = request.form.get("end_time", "20:00")
        days = {int(x) for x in request.form.getlist("days") if str(x).isdigit() and 0 <= int(x) <= 6}
        if not re.fullmatch(r"\d{2}:\d{2}", start_time) or not re.fullmatch(r"\d{2}:\d{2}", end_time) or start_time >= end_time:
            flash("ساعت کاری معتبر نیست.", "error"); return redirect(url_for("beauty_admin_dashboard", slug=slug, section="staff"))
        conn = db()
        member = conn.execute("SELECT id FROM staff WHERE id=? AND business_id=?", (staff_id, business["id"])).fetchone()
        if member:
            conn.execute("DELETE FROM staff_schedules WHERE business_id=? AND staff_id=?", (business["id"], staff_id))
            for weekday in days:
                conn.execute("INSERT INTO staff_schedules(business_id,staff_id,weekday,start_time,end_time,is_available) VALUES(?,?,?,?,?,1)", (business["id"], staff_id, weekday, start_time, end_time))
            conn.commit(); flash("برنامه کاری ذخیره شد.", "success")
        conn.close()
        return redirect(url_for("beauty_admin_dashboard", slug=slug, section="staff"))

    @app.post("/demo/<slug>/admin/staff/<int:staff_id>/services")
    @tenant_admin_required
    def beauty_admin_staff_services(slug, business, user, staff_id):
        require_permission(user, "staff")
        service_ids = {int(value) for value in request.form.getlist("service_ids") if str(value).isdigit()}
        conn = db()
        member = conn.execute("SELECT id FROM staff WHERE id=? AND business_id=?", (staff_id, business["id"])).fetchone()
        valid_ids = {r["id"] for r in conn.execute("SELECT id FROM services WHERE business_id=? AND is_active=1", (business["id"],)).fetchall()}
        if member:
            conn.execute("DELETE FROM staff_services WHERE business_id=? AND staff_id=?", (business["id"], staff_id))
            for service_id in service_ids & valid_ids:
                conn.execute("INSERT INTO staff_services(business_id,staff_id,service_id) VALUES(?,?,?)", (business["id"], staff_id, service_id))
            conn.commit(); flash("خدمات متخصص به‌روزرسانی شد.", "success")
        conn.close()
        return redirect(url_for("beauty_admin_dashboard", slug=slug, section="staff"))

    @app.post("/demo/<slug>/admin/staff")
    @tenant_admin_required
    def beauty_admin_add_staff(slug, business, user):
        require_permission(user, "staff")
        name = str(request.form.get("name") or "").strip()[:100]
        role = str(request.form.get("role") or "").strip()[:100]
        if not name or not role:
            flash("نام و تخصص همکار لازم است.", "error")
            return redirect(url_for("beauty_admin_dashboard", slug=slug, section="staff"))
        try:
            experience = max(0, min(60, int(request.form.get("experience") or 0)))
            rating = max(1, min(5, float(request.form.get("rating") or 5)))
        except ValueError:
            flash("سابقه یا امتیاز معتبر نیست.", "error")
            return redirect(url_for("beauty_admin_dashboard", slug=slug, section="staff"))
        image_url = str(request.form.get("image_url") or "").strip()[:1000] or "https://images.unsplash.com/photo-1494790108377-be9c29b29330?auto=format&fit=crop&w=800&q=88"
        conn = db()
        staff_id = conn.execute("INSERT INTO staff(business_id,name,role,bio,experience_years,rating,image_url,created_at) VALUES(?,?,?,?,?,?,?,?)", (business["id"], name, role, "پذیرش رزرو آنلاین فعال است.", experience, rating, image_url, now())).lastrowid
        for weekday in range(6):
            conn.execute("INSERT INTO staff_schedules(business_id,staff_id,weekday,start_time,end_time,is_available) VALUES(?,?,?,?,?,1)", (business["id"], staff_id, weekday, "10:00", "20:00"))
        conn.commit(); conn.close(); flash("همکار جدید اضافه شد؛ حالا خدمات مرتبط را برای او تنظیم کنید.", "success")
        return redirect(url_for("beauty_admin_dashboard", slug=slug, section="staff"))

    @app.post("/demo/<slug>/admin/users")
    @tenant_admin_required
    def beauty_admin_add_user(slug, business, user):
        require_permission(user, "staff")
        name = str(request.form.get("name") or "").strip()[:100]
        phone = mobile(request.form.get("phone"))
        pin = str(request.form.get("pin") or "")
        role = request.form.get("role") if request.form.get("role") in {"owner", "manager", "staff"} else "staff"
        allowed_permissions = {"dashboard", "calendar", "customers", "services", "staff", "marketing", "reviews"}
        permissions = [value for value in request.form.getlist("permissions") if value in allowed_permissions]
        if not name or not phone or not re.fullmatch(r"\d{4,8}", pin):
            flash("نام، موبایل معتبر و رمز ۴ تا ۸ رقمی لازم است.", "error")
            return redirect(url_for("beauty_admin_dashboard", slug=slug, section="staff"))
        conn = db()
        try:
            conn.execute("INSERT INTO users(business_id,name,phone,pin_hash,role,permissions_json,created_at) VALUES(?,?,?,?,?,?,?)", (business["id"], name, phone, generate_password_hash(pin), role, json.dumps(permissions, ensure_ascii=False), now()))
            conn.commit(); flash("دسترسی کاربر جدید ساخته شد.", "success")
        except sqlite3.IntegrityError:
            flash("این شماره قبلاً برای یکی از کاربران سالن ثبت شده است.", "error")
        conn.close()
        return redirect(url_for("beauty_admin_dashboard", slug=slug, section="staff"))

    @app.post("/demo/<slug>/admin/review/<int:review_id>/toggle")
    @tenant_admin_required
    def beauty_admin_review_toggle(slug, business, user, review_id):
        require_permission(user, "reviews")
        conn = db(); conn.execute("UPDATE reviews SET is_approved=CASE is_approved WHEN 1 THEN 0 ELSE 1 END WHERE id=? AND business_id=?", (review_id, business["id"])); conn.commit(); conn.close()
        flash("وضعیت نمایش نظر تغییر کرد.", "success")
        return redirect(url_for("beauty_admin_dashboard", slug=slug, section="reviews"))

    @app.get("/health/beauty-os")
    def beauty_os_health():
        expected = {"businesses", "users", "customers", "staff", "services", "appointments", "campaigns", "messages", "reviews", "payments", "favorites", "staff_schedules"}
        conn = db()
        tables = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        business_count = conn.execute("SELECT COUNT(*) c FROM businesses").fetchone()["c"]
        service_count = conn.execute("SELECT COUNT(*) c FROM services WHERE business_id=? AND is_active=1", (showcase["id"],)).fetchone()["c"]
        conn.close()
        return jsonify({"ok": expected.issubset(tables) and service_count >= 8, "multi_tenant": True, "vertical": "beauty", "businesses": business_count, "showcase": f"/demo/{SHOWCASE_SLUG}", "services": service_count, "models": sorted(expected), "customer_auth": True, "admin_auth": True, "booking": True})
