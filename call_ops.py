import json
import sqlite3
from datetime import datetime
from functools import wraps

from flask import flash, redirect, render_template, request, session, url_for

from verticals import CAMPAIGN_ORDER, VERTICALS, get_vertical


def register_call_ops(app, db_path):
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

    conn = db()
    conn.executescript('''
    CREATE TABLE IF NOT EXISTS call_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        lead_id INTEGER NOT NULL,
        outcome TEXT NOT NULL,
        note TEXT,
        created_at TEXT NOT NULL,
        FOREIGN KEY(lead_id) REFERENCES leads(id)
    );
    CREATE INDEX IF NOT EXISTS idx_call_logs_lead ON call_logs(lead_id);
    ''')
    conn.commit(); conn.close()

    def meta(raw):
        try:
            return json.loads(raw or '{}')
        except Exception:
            return {}

    def queue(vertical=''):
        conn = db()
        params = []
        where = "WHERE l.vertical IN (%s)" % ','.join('?' for _ in CAMPAIGN_ORDER)
        params.extend(CAMPAIGN_ORDER)
        if vertical in VERTICALS:
            where += ' AND l.vertical=?'
            params.append(vertical)
        rows = conn.execute(f'''
            SELECT l.*,
                   EXISTS(SELECT 1 FROM events e WHERE e.lead_id=l.id AND e.event_type IN ('campaign_completed','finder_completed')) completed,
                   EXISTS(SELECT 1 FROM events e WHERE e.lead_id=l.id AND e.event_type='price_viewed') price_seen,
                   (SELECT COUNT(*) FROM call_logs c WHERE c.lead_id=l.id) call_count,
                   (SELECT c.outcome FROM call_logs c WHERE c.lead_id=l.id ORDER BY c.id DESC LIMIT 1) last_outcome,
                   (SELECT c.note FROM call_logs c WHERE c.lead_id=l.id ORDER BY c.id DESC LIMIT 1) last_note
            FROM leads l {where}
        ''', params).fetchall()
        conn.close()
        items=[]
        for r in rows:
            x=dict(r); m=meta(x.get('meta_json')); info=get_vertical(x['vertical']) or {'label':x['vertical'],'product':'دموی اختصاصی'}
            score=min((x.get('opens') or 0)*8+(x.get('cta_clicks') or 0)*20+(x.get('checkout_clicks') or 0)*45+(28 if x['completed'] else 0)+(12 if x['price_seen'] else 0),100)
            if x.get('status') == 'won': score += 1000
            elif x.get('status') == 'lost': score -= 1000
            x.update(meta=m, info=info, score=score)
            x['demo_path']=f"/d/{x['slug']}" if x['vertical']=='realestate' else f"/v/{x['slug']}"
            if x.get('checkout_clicks'):
                x['script']=f"سلام، دیدم تا فعال‌سازی {info['product']} {x['business_name']} رفتید. اگر اوکیه همین نسخه رو امروز نهایی کنیم."
            elif x['completed']:
                x['script']=f"سلام، دموی {info['product']} {x['business_name']} رو کامل تست کردید؛ دقیقاً همین با برند خودتون فعال میشه. نظرتون چطور بود؟"
            elif x.get('opens'):
                x['script']=f"سلام، لینکی که برای {x['business_name']} فرستادیم رو دیدید؟ همون نسخه برای خودتونه؛ اگر بازش کنید کارشو زیر یک دقیقه می‌بینید."
            else:
                x['script']=f"سلام، برای {x['business_name']} یک {info['product']} اختصاصی آماده کردیم. لینک رو براتون فرستادیم؛ فقط خود نسخه رو ببینید، توضیح اضافه‌ای لازم نیست."
            items.append(x)
        items.sort(key=lambda z:(z['status'] in {'won','lost'}, -z['score'], -(z.get('opens') or 0), z.get('call_count') or 0))
        return items

    @app.get('/admin/calls')
    @admin_only
    def call_desk():
        vertical=(request.args.get('vertical') or '').strip()
        items=queue(vertical)
        active=[x for x in items if x.get('status') not in {'won','lost'}]
        stats={'queue':len(active),'hot':sum(1 for x in active if 50 <= x['score'] < 1000),'called':sum(1 for x in items if x.get('call_count')),'won':sum(1 for x in items if x.get('status')=='won')}
        return render_template('calls.html',items=active[:300],stats=stats,verticals=VERTICALS,order=CAMPAIGN_ORDER,selected=vertical)

    @app.post('/admin/calls/<int:lead_id>/log')
    @admin_only
    def call_log(lead_id):
        outcome=(request.form.get('outcome') or 'contacted').strip()
        allowed={'no_answer','callback','contacted','interested','qualified','won','lost','wrong_number','do_not_call'}
        if outcome not in allowed:
            outcome='contacted'
        note=(request.form.get('note') or '').strip()[:1500]
        conn=db(); lead=conn.execute('SELECT id,phone FROM leads WHERE id=?',(lead_id,)).fetchone()
        if not lead:
            conn.close(); return 'Not found',404
        conn.execute('INSERT INTO call_logs(lead_id,outcome,note,created_at) VALUES(?,?,?,?)',(lead_id,outcome,note,now_iso()))
        status_map={'contacted':'contacted','interested':'qualified','qualified':'qualified','won':'won','lost':'lost','wrong_number':'lost','do_not_call':'lost'}
        if outcome in status_map:
            conn.execute('UPDATE leads SET status=? WHERE id=?',(status_map[outcome],lead_id))
        if outcome=='do_not_call' and lead['phone']:
            # Only valid mobiles are meaningful for SMS suppression; harmless for landlines.
            conn.execute("INSERT OR REPLACE INTO suppressions(recipient,reason,created_at) VALUES(?,?,?)",(lead['phone'],'call_opt_out',now_iso()))
            conn.execute("UPDATE outreach_messages SET status='suppressed' WHERE recipient=? AND status='queued'",(lead['phone'],))
        conn.commit(); conn.close()
        flash('نتیجه تماس ثبت شد.','success')
        return redirect(request.referrer or url_for('call_desk'))
