import json
import os
import re
import sqlite3
from datetime import datetime
from functools import wraps

import requests
from flask import flash, jsonify, redirect, render_template, request, session, url_for

from verticals import CAMPAIGN_ORDER, VERTICALS, get_vertical


def register_outreach(app, db_path):
    def db():
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def now_iso():
        return datetime.now().isoformat(timespec='seconds')

    def admin_only(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            if not session.get('admin'):
                return redirect(url_for('login', next=request.path))
            return fn(*args, **kwargs)
        return wrapped

    def ensure_schema():
        conn = db()
        conn.executescript('''
        CREATE TABLE IF NOT EXISTS outreach_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lead_id INTEGER NOT NULL,
            campaign TEXT,
            vertical TEXT NOT NULL,
            variant TEXT DEFAULT 'A',
            channel TEXT DEFAULT 'sms',
            recipient TEXT NOT NULL,
            body TEXT NOT NULL,
            status TEXT DEFAULT 'queued',
            provider TEXT,
            provider_id TEXT,
            error TEXT,
            created_at TEXT NOT NULL,
            sent_at TEXT,
            UNIQUE(lead_id, campaign, channel),
            FOREIGN KEY(lead_id) REFERENCES leads(id)
        );
        CREATE TABLE IF NOT EXISTS suppressions (
            recipient TEXT PRIMARY KEY,
            reason TEXT DEFAULT 'manual',
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_outreach_status ON outreach_messages(status);
        ''')
        conn.commit(); conn.close()

    ensure_schema()

    def parse_meta(raw):
        try:
            return json.loads(raw or '{}')
        except Exception:
            return {}

    def normalize_mobile(value):
        raw = re.sub(r'\D','',str(value or ''))
        if raw.startswith('98') and len(raw) == 12:
            raw = '0' + raw[2:]
        return raw if re.fullmatch(r'09\d{9}', raw) else ''

    def e164(mobile):
        return '+98' + mobile[1:] if mobile.startswith('09') else mobile

    def demo_url(lead):
        root = request.url_root.rstrip('/')
        return f"{root}/d/{lead['slug']}" if lead['vertical'] == 'realestate' else f"{root}/v/{lead['slug']}"

    def sms_text(lead, meta):
        info = get_vertical(lead['vertical'])
        hooks = info.get('hooks') or ['{name}، نسخه اختصاصی شما آماده شده: {url}']
        variant = (meta.get('variant') or 'A').upper()
        idx = 1 if variant == 'B' and len(hooks) > 1 else 0
        return hooks[idx].format(name=lead['business_name'], url=demo_url(lead))

    def provider_config():
        return {
            'provider': (os.environ.get('SMS_PROVIDER') or '').strip().lower(),
            'api_key': (os.environ.get('SMS_API_KEY') or '').strip(),
            'sender': (os.environ.get('SMS_SENDER') or '').strip(),
            'live': (os.environ.get('SMS_LIVE') or '0').strip() == '1',
        }

    def send_ippanel(cfg, recipient, body):
        payload = {
            'sending_type': 'webservice',
            'from_number': cfg['sender'],
            'message': body,
            'params': {'recipients': [e164(recipient)]},
        }
        r = requests.post('https://edge.ippanel.com/v1/api/send', headers={'Authorization': cfg['api_key'], 'Content-Type': 'application/json'}, json=payload, timeout=25)
        r.raise_for_status()
        data = r.json()
        return str(data.get('data') or data.get('message_outbox_id') or data.get('id') or '')

    def send_kavenegar(cfg, recipient, body):
        url = f"https://api.kavenegar.com/v1/{cfg['api_key']}/sms/send.json"
        r = requests.post(url, data={'receptor': recipient, 'sender': cfg['sender'], 'message': body}, timeout=25)
        r.raise_for_status()
        data = r.json()
        entries = data.get('entries') or []
        if entries and isinstance(entries, list):
            return str(entries[0].get('messageid') or entries[0].get('id') or '')
        return str(data.get('return', {}).get('message') or '')

    def actually_send(cfg, recipient, body):
        if cfg['provider'] == 'ippanel':
            return send_ippanel(cfg, recipient, body)
        if cfg['provider'] == 'kavenegar':
            return send_kavenegar(cfg, recipient, body)
        raise RuntimeError('SMS_PROVIDER must be ippanel or kavenegar')

    @app.get('/admin/outreach')
    @admin_only
    def outreach_dashboard():
        conn = db()
        counts = {r['status']: r['c'] for r in conn.execute('SELECT status,COUNT(*) c FROM outreach_messages GROUP BY status')}
        recent = conn.execute('''SELECT o.*,l.business_name FROM outreach_messages o JOIN leads l ON l.id=o.lead_id ORDER BY o.id DESC LIMIT 100''').fetchall()
        suppressions = conn.execute('SELECT COUNT(*) c FROM suppressions').fetchone()['c']
        conn.close()
        cfg = provider_config()
        public_cfg = {'provider': cfg['provider'] or 'not configured', 'sender': cfg['sender'] or '—', 'live': cfg['live'], 'configured': bool(cfg['provider'] and cfg['api_key'] and cfg['sender'])}
        return render_template('outreach.html', counts=counts, recent=recent, suppressions=suppressions, config=public_cfg, verticals=VERTICALS, order=CAMPAIGN_ORDER)

    @app.post('/admin/outreach/prepare')
    @admin_only
    def outreach_prepare():
        vertical = (request.form.get('vertical') or '').strip()
        limit = min(max(int(request.form.get('limit') or 100), 1), 5000)
        if vertical not in VERTICALS:
            flash('صنف معتبر نیست.', 'error'); return redirect(url_for('outreach_dashboard'))
        conn = db()
        rows = conn.execute('SELECT * FROM leads WHERE vertical=? ORDER BY id DESC LIMIT ?', (vertical, limit * 3)).fetchall()
        queued = skipped = 0
        for row in rows:
            if queued >= limit:
                break
            lead = dict(row); meta = parse_meta(lead.get('meta_json'))
            mobile = normalize_mobile(meta.get('mobile') or lead.get('phone'))
            if not mobile:
                skipped += 1; continue
            if conn.execute('SELECT 1 FROM suppressions WHERE recipient=?', (mobile,)).fetchone():
                skipped += 1; continue
            campaign = meta.get('campaign') or 'OUTBOUND-LIVE'
            body = sms_text(lead, meta)
            try:
                conn.execute('''INSERT INTO outreach_messages(lead_id,campaign,vertical,variant,recipient,body,status,created_at)
                                VALUES(?,?,?,?,?,?,?,?)''', (lead['id'], campaign, vertical, meta.get('variant') or 'A', mobile, body, 'queued', now_iso()))
                queued += 1
            except sqlite3.IntegrityError:
                skipped += 1
        conn.commit(); conn.close()
        flash(f'{queued} پیام در صف قرار گرفت؛ {skipped} مورد بدون موبایل/تکراری/لغوشده رد شد.', 'success')
        return redirect(url_for('outreach_dashboard'))

    @app.post('/admin/outreach/send')
    @admin_only
    def outreach_send():
        limit = min(max(int(request.form.get('limit') or 25), 1), 200)
        cfg = provider_config()
        conn = db()
        rows = conn.execute("SELECT * FROM outreach_messages WHERE status='queued' ORDER BY id LIMIT ?", (limit,)).fetchall()
        if not cfg['configured']:
            conn.close(); flash('پنل پیامکی هنوز تنظیم نشده؛ صف آماده است ولی ارسال Live غیرفعال است.', 'error'); return redirect(url_for('outreach_dashboard'))
        if not cfg['live']:
            conn.close(); flash(f'Dry Run فعال است؛ {len(rows)} پیام آماده ارسال‌اند. برای ارسال واقعی SMS_LIVE=1 لازم است.', 'success'); return redirect(url_for('outreach_dashboard'))
        sent = failed = 0
        for row in rows:
            try:
                provider_id = actually_send(cfg, row['recipient'], row['body'])
                conn.execute("UPDATE outreach_messages SET status='sent',provider=?,provider_id=?,sent_at=?,error=NULL WHERE id=?", (cfg['provider'], provider_id, now_iso(), row['id']))
                conn.execute("UPDATE leads SET status=CASE WHEN status='new' THEN 'sent' ELSE status END WHERE id=?", (row['lead_id'],))
                sent += 1
            except Exception as exc:
                conn.execute("UPDATE outreach_messages SET status='failed',provider=?,error=? WHERE id=?", (cfg['provider'], str(exc)[:500], row['id']))
                failed += 1
        conn.commit(); conn.close()
        flash(f'{sent} پیام ارسال شد؛ {failed} خطا.', 'success' if not failed else 'error')
        return redirect(url_for('outreach_dashboard'))

    @app.post('/admin/outreach/suppress')
    @admin_only
    def outreach_suppress():
        mobile = normalize_mobile(request.form.get('mobile'))
        if not mobile:
            flash('شماره معتبر نیست.', 'error'); return redirect(url_for('outreach_dashboard'))
        conn = db()
        conn.execute("INSERT OR REPLACE INTO suppressions(recipient,reason,created_at) VALUES(?,?,?)", (mobile, request.form.get('reason') or 'manual', now_iso()))
        conn.execute("UPDATE outreach_messages SET status='suppressed' WHERE recipient=? AND status='queued'", (mobile,))
        conn.commit(); conn.close()
        flash('شماره به لیست عدم تماس اضافه شد.', 'success')
        return redirect(url_for('outreach_dashboard'))

    @app.get('/health/outreach')
    def outreach_health():
        cfg = provider_config()
        return jsonify({'ok': True, 'providers': ['ippanel','kavenegar'], 'configured': bool(cfg['provider'] and cfg['api_key'] and cfg['sender']), 'live': cfg['live']})
