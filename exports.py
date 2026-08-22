import csv
import io
import json
import sqlite3

from flask import Response, redirect, request, session, url_for


def register_exports(app, db_path):
    def db():
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def meta(raw):
        try:
            return json.loads(raw or '{}')
        except Exception:
            return {}

    def admin_guard():
        if not session.get('admin'):
            return redirect(url_for('login', next=request.path))
        return None

    def sms_for(row, demo_url):
        m = meta(row['meta_json'])
        if (m.get('variant') or 'A') == 'B':
            return f"{row['business_name']}، یک صفحه جذب مشتری ملکی با نام خودتون آماده کردیم؛ مشتری بودجه و منطقه رو وارد می‌کنه و لید مستقیم برای شما میاد: {demo_url}"
        return f"{row['business_name']}، فایل‌یاب اختصاصی شما با نام و اطلاعات خودتون آماده‌ست. قبل از فعال‌سازی ببینید مشتری چطور درخواست ملک ثبت می‌کنه: {demo_url}"

    @app.get('/admin/campaign/realestate/sms.csv')
    def realestate_sms_export():
        denied = admin_guard()
        if denied:
            return denied
        conn = db()
        rows = conn.execute("SELECT * FROM leads WHERE vertical='realestate' AND COALESCE(phone,'')<>'' ORDER BY id").fetchall()
        conn.close()
        root = request.url_root.rstrip('/')
        out = io.StringIO()
        w = csv.writer(out)
        w.writerow(['business_name','phone','variant','campaign','demo_url','sms_text'])
        for row in rows:
            m = meta(row['meta_json'])
            demo_url = f"{root}/d/{row['slug']}"
            w.writerow([row['business_name'],row['phone'],m.get('variant','A'),m.get('campaign',''),demo_url,sms_for(row,demo_url)])
        return Response('\ufeff'+out.getvalue(),mimetype='text/csv; charset=utf-8',headers={'Content-Disposition':'attachment; filename=ppos-realestate-sms.csv'})

    @app.get('/admin/campaign/realestate/calls.csv')
    def realestate_calls_export():
        denied = admin_guard()
        if denied:
            return denied
        conn = db()
        rows = conn.execute("SELECT * FROM leads WHERE vertical='realestate' ORDER BY COALESCE(last_opened_at,created_at) DESC").fetchall()
        conn.close()
        scored=[]
        for r in rows:
            x=dict(r)
            score=min((x.get('opens') or 0)*8+(x.get('cta_clicks') or 0)*24+(x.get('checkout_clicks') or 0)*45,100)
            x['score']=score
            scored.append(x)
        scored.sort(key=lambda x:x['score'],reverse=True)
        out=io.StringIO(); w=csv.writer(out)
        w.writerow(['priority','business_name','phone','city','score','opens','engagement','checkout','status','recommended_call'])
        for i,x in enumerate(scored,1):
            if x['checkout_clicks']:
                call='HOT: قیمت/فعال‌سازی را دیده؛ مستقیم برای نهایی‌کردن تماس بگیر.'
            elif x['cta_clicks']:
                call='WARM: دمو را تست کرده؛ روی لیدگیری و آماده‌بودن نسخه تاکید کن.'
            elif x['opens']:
                call='OPENED: بپرس دمو را دید و فایل‌یاب برایش کاربرد دارد یا نه.'
            else:
                call='COLD: فعلاً بعد از بازدیدکننده‌ها تماس بگیر.'
            w.writerow([i,x['business_name'],x['phone'],x['city'],x['score'],x['opens'],x['cta_clicks'],x['checkout_clicks'],x['status'],call])
        return Response('\ufeff'+out.getvalue(),mimetype='text/csv; charset=utf-8',headers={'Content-Disposition':'attachment; filename=ppos-realestate-call-queue.csv'})
