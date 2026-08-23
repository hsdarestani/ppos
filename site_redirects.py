import json
import re
import sqlite3
from datetime import datetime

from flask import redirect, request


def register_site_redirects(app, db_path):
    @app.before_request
    def promote_full_site():
        # Preserve all existing SMS/campaign links while upgrading their destination
        # from the old one-page demo to the new multi-page site.
        match = re.fullmatch(r'/(?:v|d)/([^/]+)', request.path)
        if not match or request.method != 'GET':
            return None
        slug = match.group(1)
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute('SELECT id FROM leads WHERE slug=?', (slug,)).fetchone()
        if not row:
            conn.close(); return None
        now = datetime.now().isoformat(timespec='seconds')
        conn.execute('UPDATE leads SET opens=opens+1,last_opened_at=? WHERE id=?', (now, row['id']))
        conn.execute('INSERT INTO events(lead_id,event_type,meta_json,created_at) VALUES(?,?,?,?)', (row['id'], 'open', json.dumps({'destination':'full_site'}, ensure_ascii=False), now))
        conn.commit(); conn.close()
        return redirect(f'/s/{slug}', code=302)
