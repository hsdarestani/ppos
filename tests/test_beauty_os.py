import os
import sqlite3
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from flask import Flask

from booking_os import register_booking_os


ROOT = Path(__file__).resolve().parents[1]


class BeautyOSProductionFlowTest(unittest.TestCase):
    def setUp(self):
        handle, self.db_path = tempfile.mkstemp(prefix="ppos-beauty-", suffix=".db")
        os.close(handle)
        conn = sqlite3.connect(self.db_path)
        conn.executescript(
            """
            CREATE TABLE leads (
              id INTEGER PRIMARY KEY AUTOINCREMENT, slug TEXT UNIQUE NOT NULL,
              business_name TEXT NOT NULL, vertical TEXT NOT NULL, phone TEXT,
              city TEXT, address TEXT, instagram TEXT, logo_url TEXT,
              accent TEXT DEFAULT '#6f294b', meta_json TEXT DEFAULT '{}',
              status TEXT DEFAULT 'new', created_at TEXT NOT NULL,
              last_opened_at TEXT, opens INTEGER DEFAULT 0,
              cta_clicks INTEGER DEFAULT 0, checkout_clicks INTEGER DEFAULT 0
            );
            CREATE TABLE events (
              id INTEGER PRIMARY KEY AUTOINCREMENT, lead_id INTEGER NOT NULL,
              event_type TEXT NOT NULL, meta_json TEXT DEFAULT '{}', created_at TEXT NOT NULL
            );
            """
        )
        conn.commit(); conn.close()
        self.app = Flask(__name__, template_folder=str(ROOT / "templates"), static_folder=str(ROOT / "static"))
        self.app.secret_key = "beauty-os-test-key"
        self.app.jinja_env.globals["maps_embed_key"] = ""
        register_booking_os(self.app, self.db_path)
        self.client = self.app.test_client()

    def tearDown(self):
        os.unlink(self.db_path)

    def ids(self, business_slug="salon-morvarid"):
        conn = sqlite3.connect(self.db_path); conn.row_factory = sqlite3.Row
        business = conn.execute("SELECT * FROM businesses WHERE slug=?", (business_slug,)).fetchone()
        service = conn.execute("SELECT * FROM services WHERE business_id=? ORDER BY id LIMIT 1", (business["id"],)).fetchone()
        member = conn.execute("SELECT st.* FROM staff st JOIN staff_services ss ON ss.staff_id=st.id AND ss.business_id=st.business_id WHERE ss.business_id=? AND ss.service_id=? LIMIT 1", (business["id"], service["id"])).fetchone()
        conn.close()
        return business, service, member

    def available_day(self):
        chosen = date.today() + timedelta(days=1)
        while chosen.weekday() == 4:
            chosen += timedelta(days=1)
        return chosen.isoformat()

    def test_complete_public_booking_customer_and_admin_flow(self):
        health = self.client.get("/health/beauty-os")
        self.assertEqual(health.status_code, 200)
        self.assertTrue(health.get_json()["ok"])
        public = self.client.get("/demo/salon-morvarid")
        self.assertEqual(public.status_code, 200)
        for anchor in [b'id="services"', b'id="team"', b'id="results"', b'id="booking"', b'id="reviews"', b'id="location"']:
            self.assertIn(anchor, public.data)

        business, service, member = self.ids()
        day = self.available_day()
        availability = self.client.get(f"/api/demo/salon-morvarid/availability?service_id={service['id']}&staff_id={member['id']}&date={day}").get_json()
        self.assertTrue(availability["slots"])
        payload = {"service_id": service["id"], "staff_id": member["id"], "date": day, "time": availability["slots"][0], "name": "مشتری تست", "phone": "09123456789"}
        booking = self.client.post("/api/demo/salon-morvarid/book", json=payload)
        self.assertEqual(booking.status_code, 200)
        self.assertTrue(booking.get_json()["code"])
        self.assertEqual(self.client.post("/api/demo/salon-morvarid/book", json=payload).status_code, 409)

        account = self.client.post("/demo/salon-morvarid/login", data={"phone": "09123456789", "pin": "2468", "name": "مشتری تست"}, follow_redirects=True)
        self.assertEqual(account.status_code, 200)
        self.assertIn("وقت‌ها و سابقه مراجعه".encode(), account.data)
        self.client.get("/demo/salon-morvarid/logout")

        login = self.client.post("/demo/salon-morvarid/admin/login", data={"phone": "09120000000", "pin": "1234"})
        self.assertEqual(login.status_code, 302)
        for section in ["dashboard", "calendar", "customers", "services", "staff", "marketing", "reviews"]:
            response = self.client.get(f"/demo/salon-morvarid/admin?section={section}")
            self.assertEqual(response.status_code, 200, section)

    def test_tenant_isolation_for_personalized_prospect_demo(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute("INSERT INTO leads(slug,business_name,vertical,phone,city,address,instagram,accent,created_at) VALUES(?,?,?,?,?,?,?,?,datetime('now'))", ("salon-niloofar", "سالن نیلوفر", "beauty", "02100000000", "شیراز", "معالی‌آباد", "niloofar", "#4b315e"))
        conn.commit(); conn.close()
        response = self.client.get("/demo/salon-niloofar")
        self.assertEqual(response.status_code, 200)
        self.assertIn("سالن نیلوفر".encode(), response.data)
        first_business, first_service, first_member = self.ids()
        second_business, _, _ = self.ids("salon-niloofar")
        self.assertNotEqual(first_business["id"], second_business["id"])
        cross_tenant = self.client.get(f"/api/demo/salon-niloofar/availability?service_id={first_service['id']}&staff_id={first_member['id']}&date={self.available_day()}")
        self.assertEqual(cross_tenant.status_code, 400)


if __name__ == "__main__":
    unittest.main()
