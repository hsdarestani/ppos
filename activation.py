import json
import sqlite3
from datetime import datetime

from flask import render_template

from verticals import get_vertical


def register_activation(app, db_path):
    def db():
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        return conn

    @app.get('/activate/<slug>')
    def activate_vertical(slug):
        conn = db()
        row = conn.execute('SELECT * FROM leads WHERE slug=?', (slug,)).fetchone()
        if not row:
            conn.close()
            return 'Not found', 404
        lead = dict(row)
        info = get_vertical(lead['vertical'])
        if not info:
            conn.close()
            return 'Not found', 404
        now = datetime.now().isoformat(timespec='seconds')
        conn.execute("INSERT INTO events(lead_id,event_type,meta_json,created_at) VALUES(?,?,?,?)", (lead['id'], 'checkout', json.dumps({'source':'universal_activation'}, ensure_ascii=False), now))
        conn.execute('UPDATE leads SET checkout_clicks=checkout_clicks+1 WHERE id=?', (lead['id'],))
        conn.commit()
        conn.close()
        return render_template('activation_vertical.html', lead=lead, info=info)
