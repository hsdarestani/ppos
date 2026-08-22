import csv
import io
from functools import wraps

from flask import Response, jsonify, redirect, request, session, url_for

from verticals import CAMPAIGN_ORDER, VERTICALS


def register_campaign_tools(app):
    def admin_only(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            if not session.get('admin'):
                return redirect(url_for('login', next=request.path))
            return fn(*args, **kwargs)
        return wrapped

    @app.get('/health/campaigns')
    def campaigns_public_health():
        return jsonify({
            'ok': True,
            'engine': 'ppos-all-vertical',
            'vertical_count': len(VERTICALS),
            'ab_ready': all(len(v.get('hooks') or []) >= 2 for v in VERTICALS.values()),
            'demo_ready': all(len(v.get('questions') or []) == 3 for v in VERTICALS.values()),
        })

    @app.get('/admin/campaigns/template.csv')
    @admin_only
    def campaigns_template_csv():
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(['business_name','phone','city','address','instagram','logo_url','vertical','variant','source','campaign'])
        for key in CAMPAIGN_ORDER:
            label = VERTICALS[key]['label']
            w.writerow([f'نمونه {label}','09xxxxxxxxx','تهران','','','',key,'A','manual','OUTBOUND-MVP'])
        return Response('\ufeff'+buf.getvalue(), mimetype='text/csv; charset=utf-8', headers={'Content-Disposition':'attachment; filename=ppos-campaign-import-template.csv'})

    @app.get('/api/campaigns/readiness')
    @admin_only
    def campaigns_readiness():
        return jsonify({
            'ready': True,
            'vertical_count': len(VERTICALS),
            'verticals': [
                {
                    'key': key,
                    'label': VERTICALS[key]['label'],
                    'product': VERTICALS[key]['product'],
                    'price': VERTICALS[key]['price'],
                    'variants': len(VERTICALS[key].get('hooks') or []),
                    'questions': len(VERTICALS[key].get('questions') or []),
                }
                for key in CAMPAIGN_ORDER
            ],
        })
