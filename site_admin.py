import sqlite3
from functools import wraps

from flask import flash, redirect, render_template, request, session, url_for

from site_blueprints import get_blueprint
from verticals import get_vertical


def register_site_admin(app, db_path):
    def db():
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def admin_only(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            if not session.get('admin'):
                return redirect(url_for('login', next=request.path))
            return fn(*args, **kwargs)
        return wrapped

    @app.get('/admin/sites')
    @admin_only
    def site_admin_index():
        conn = db()
        rows = conn.execute('''
            SELECT l.*,
              (SELECT COUNT(*) FROM site_customers c WHERE c.lead_id=l.id) customer_count,
              (SELECT COUNT(*) FROM site_requests r WHERE r.lead_id=l.id) request_count,
              (SELECT COUNT(*) FROM site_catalog_items i WHERE i.lead_id=l.id AND i.is_active=1) catalog_count
            FROM leads l ORDER BY l.id DESC LIMIT 500
        ''').fetchall()
        conn.close()
        return render_template('site_admin_index.html', rows=rows)

    @app.get('/admin/site/<int:lead_id>')
    @admin_only
    def site_admin_detail(lead_id):
        conn = db()
        lead = conn.execute('SELECT * FROM leads WHERE id=?', (lead_id,)).fetchone()
        if not lead:
            conn.close(); return 'Not found', 404
        info = get_vertical(lead['vertical']) or {'label':lead['vertical'],'product':'سایت اختصاصی'}
        bp = get_blueprint(lead['vertical'], info)
        customers = conn.execute('SELECT id,name,phone,created_at,last_login_at FROM site_customers WHERE lead_id=? ORDER BY id DESC LIMIT 100', (lead_id,)).fetchall()
        requests = conn.execute('SELECT r.*,c.name customer_name,c.phone customer_phone FROM site_requests r LEFT JOIN site_customers c ON c.id=r.customer_id WHERE r.lead_id=? ORDER BY r.id DESC LIMIT 150', (lead_id,)).fetchall()
        catalog = conn.execute('SELECT * FROM site_catalog_items WHERE lead_id=? ORDER BY position,id', (lead_id,)).fetchall()
        conn.close()
        return render_template('site_admin_detail.html', lead=lead, info=info, bp=bp, customers=customers, requests=requests, catalog=catalog)

    @app.post('/admin/site/<int:lead_id>/request/<int:req_id>/status')
    @admin_only
    def site_admin_request_status(lead_id, req_id):
        status = (request.form.get('status') or '').strip()
        if status not in {'new','contacted','done','cancel_requested'}:
            flash('وضعیت معتبر نیست.', 'error')
            return redirect(url_for('site_admin_detail', lead_id=lead_id))
        conn = db(); conn.execute("UPDATE site_requests SET status=?,updated_at=datetime('now') WHERE id=? AND lead_id=?", (status, req_id, lead_id)); conn.commit(); conn.close()
        flash('وضعیت درخواست تغییر کرد.', 'success')
        return redirect(url_for('site_admin_detail', lead_id=lead_id))

    @app.post('/admin/site/<int:lead_id>/catalog/add')
    @admin_only
    def site_admin_catalog_add(lead_id):
        title = (request.form.get('title') or '').strip()[:120]
        if not title:
            flash('عنوان لازم است.', 'error'); return redirect(url_for('site_admin_detail', lead_id=lead_id))
        subtitle = (request.form.get('subtitle') or '').strip()[:240]
        image_url = (request.form.get('image_url') or '').strip()[:1000]
        badge = (request.form.get('badge') or '').strip()[:40]
        conn = db()
        pos = conn.execute('SELECT COALESCE(MAX(position),0)+1 n FROM site_catalog_items WHERE lead_id=?', (lead_id,)).fetchone()['n']
        conn.execute("INSERT INTO site_catalog_items(lead_id,title,subtitle,image_url,badge,position,is_active,created_at) VALUES(?,?,?,?,?,?,1,datetime('now'))", (lead_id,title,subtitle,image_url,badge,pos))
        conn.commit(); conn.close(); flash('آیتم جدید اضافه شد.', 'success')
        return redirect(url_for('site_admin_detail', lead_id=lead_id))

    @app.post('/admin/site/<int:lead_id>/catalog/<int:item_id>/toggle')
    @admin_only
    def site_admin_catalog_toggle(lead_id, item_id):
        conn = db(); conn.execute('UPDATE site_catalog_items SET is_active=CASE is_active WHEN 1 THEN 0 ELSE 1 END WHERE id=? AND lead_id=?', (item_id,lead_id)); conn.commit(); conn.close()
        return redirect(url_for('site_admin_detail', lead_id=lead_id))
