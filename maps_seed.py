import json
import os
import re
import secrets
import sqlite3
from datetime import datetime
from functools import wraps

import requests
from flask import flash, jsonify, redirect, render_template, request, session, url_for

from verticals import CAMPAIGN_ORDER, VERTICALS, get_vertical

PLACES_URL = 'https://places.googleapis.com/v1/places:searchText'
FIELD_MASK = ','.join([
    'places.id', 'places.displayName', 'places.formattedAddress',
    'places.nationalPhoneNumber', 'places.internationalPhoneNumber',
    'places.rating', 'places.userRatingCount', 'places.googleMapsUri',
    'places.websiteUri', 'places.location', 'places.primaryTypeDisplayName',
    'places.businessStatus', 'nextPageToken',
])

# Weighted toward the largest and most commercially active urban markets.
CITY_PLAN = [
    ('تهران', 35), ('کرج', 15), ('مشهد', 15), ('اصفهان', 10),
    ('شیراز', 10), ('تبریز', 5), ('قم', 5), ('اهواز', 5),
]

SEARCH_TERMS = {
    'realestate': ['مشاور املاک', 'بنگاه املاک'],
    'beauty': ['سالن زیبایی زنانه', 'آرایشگاه زنانه'],
    'barber': ['آرایشگاه مردانه', 'پیرایش مردانه'],
    'auto': ['اتوگالری', 'نمایشگاه خودرو'],
    'aesthetic': ['کلینیک زیبایی', 'کلینیک پوست و مو'],
    'dentist': ['دندانپزشکی', 'کلینیک دندانپزشکی'],
    'gym': ['باشگاه بدنسازی', 'باشگاه ورزشی'],
    'trainer': ['مربی شخصی بدنسازی', 'پرسونال ترینر'],
    'language': ['آموزشگاه زبان', 'موسسه زبان'],
    'education': ['آموزشگاه کنکور', 'مرکز مشاوره تحصیلی'],
    'repair': ['تعمیرگاه خودرو', 'اتو سرویس'],
    'parts': ['فروشگاه لوازم یدکی خودرو', 'قطعات خودرو'],
    'carwash': ['کارواش', 'دیتیلینگ خودرو'],
    'fashion': ['مزون لباس', 'مزون زنانه'],
    'gold': ['طلافروشی', 'طلا و جواهر'],
    'furniture': ['فروشگاه مبلمان', 'مبل فروشی'],
    'cabinet': ['کابینت سازی', 'کابینت آشپزخانه'],
    'restaurant': ['رستوران', 'کافه رستوران'],
    'pet': ['پت شاپ', 'کلینیک دامپزشکی'],
    'mobile': ['فروشگاه موبایل', 'موبایل فروشی'],
    'immigration': ['موسسه مهاجرتی', 'خدمات مهاجرتی'],
    'travel': ['آژانس مسافرتی', 'خدمات مسافرتی'],
    'insurance': ['نمایندگی بیمه', 'بیمه'],
    'legal': ['موسسه حقوقی', 'دفتر وکالت'],
    'home_services': ['خدمات ساختمان', 'تعمیرات منزل'],
    'hvac': ['تعمیر پکیج و کولر', 'تاسیسات ساختمان'],
    'carpet': ['قالیشویی'],
    'laundry': ['خشکشویی'],
    'studio': ['آتلیه عکاسی', 'استودیو عکاسی'],
    'venue': ['تالار عروسی', 'باغ تالار'],
}


def _now():
    return datetime.now().isoformat(timespec='seconds')


def _mobile(value):
    raw = re.sub(r'\D', '', str(value or ''))
    if raw.startswith('0098'):
        raw = '0' + raw[4:]
    elif raw.startswith('98') and len(raw) == 12:
        raw = '0' + raw[2:]
    elif raw.startswith('9') and len(raw) == 10:
        raw = '0' + raw
    return raw if re.fullmatch(r'09\d{9}', raw) else ''


def _phone(value):
    raw = re.sub(r'\D', '', str(value or ''))
    if raw.startswith('0098'):
        raw = '0' + raw[4:]
    elif raw.startswith('98') and len(raw) >= 11:
        raw = '0' + raw[2:]
    return raw[:15]


def _slug(name):
    base = re.sub(r'[^a-z0-9\u0600-\u06ff]+', '-', (name or '').lower()).strip('-')[:42] or 'business'
    return f'{base}-{secrets.token_hex(2)}'


def _extract_name(place):
    display = place.get('displayName') or {}
    return (display.get('text') if isinstance(display, dict) else str(display or '')).strip()


def register_maps_seed(app, db_path):
    def db():
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA busy_timeout=10000')
        return conn

    def admin_only(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            if not session.get('admin'):
                return redirect(url_for('login', next=request.path))
            return fn(*args, **kwargs)
        return wrapped

    def api_key():
        return (os.environ.get('GOOGLE_MAPS_API_KEY') or '').strip()

    def text_search(query, page_token=None):
        key = api_key()
        if not key:
            raise RuntimeError('GOOGLE_MAPS_API_KEY is not configured')
        payload = {'textQuery': query, 'pageSize': 20, 'languageCode': 'fa', 'regionCode': 'IR'}
        if page_token:
            payload['pageToken'] = page_token
        r = requests.post(
            PLACES_URL,
            headers={
                'Content-Type': 'application/json',
                'X-Goog-Api-Key': key,
                'X-Goog-FieldMask': FIELD_MASK,
            },
            json=payload,
            timeout=30,
        )
        r.raise_for_status()
        return r.json()

    def import_place(conn, place, vertical, city, campaign, variant):
        place_id = str(place.get('id') or '').strip()
        name = _extract_name(place)
        if not place_id or not name:
            return 'invalid'
        if conn.execute('SELECT 1 FROM lead_external_ids WHERE provider=? AND external_id=?', ('google_maps', place_id)).fetchone():
            return 'duplicate'

        national = place.get('nationalPhoneNumber') or ''
        international = place.get('internationalPhoneNumber') or ''
        mobile = _mobile(national) or _mobile(international)
        landline = _phone(national) or _phone(international)
        if mobile and landline == mobile:
            landline = ''
        primary = mobile or landline
        if not primary:
            return 'no_contact'

        address = str(place.get('formattedAddress') or '').strip()
        duplicate = conn.execute(
            '''SELECT id FROM leads WHERE vertical=? AND (phone=? OR (business_name=? AND COALESCE(address,'')=?)) LIMIT 1''',
            (vertical, primary, name, address),
        ).fetchone()
        if duplicate:
            conn.execute('INSERT OR IGNORE INTO lead_external_ids(provider,external_id,lead_id,created_at) VALUES(?,?,?,?)', ('google_maps', place_id, duplicate['id'], _now()))
            return 'duplicate'

        loc = place.get('location') or {}
        ptype = place.get('primaryTypeDisplayName') or {}
        category = ptype.get('text') if isinstance(ptype, dict) else str(ptype or '')
        meta = {
            'campaign': campaign,
            'variant': variant,
            'source': 'google_places_api',
            'raw_category': category,
            'mobile': mobile,
            'landline': landline,
            'sms_eligible': bool(mobile),
            'website': str(place.get('websiteUri') or ''),
            'google_maps_url': str(place.get('googleMapsUri') or ''),
            'place_id': place_id,
            'rating': place.get('rating'),
            'reviews': place.get('userRatingCount'),
            'latitude': loc.get('latitude'),
            'longitude': loc.get('longitude'),
            'business_status': place.get('businessStatus'),
            'seed_city': city,
        }
        cur = conn.execute(
            '''INSERT INTO leads(slug,business_name,vertical,phone,city,address,accent,meta_json,status,created_at)
               VALUES(?,?,?,?,?,?,?,?,?,?)''',
            (_slug(name), name, vertical, primary, city, address, '#5b4df5', json.dumps(meta, ensure_ascii=False), 'new', _now()),
        )
        conn.execute('INSERT OR IGNORE INTO lead_external_ids(provider,external_id,lead_id,created_at) VALUES(?,?,?,?)', ('google_maps', place_id, cur.lastrowid, _now()))
        return 'imported_mobile' if mobile else 'imported_landline'

    def seed_vertical(vertical, target=100):
        info = get_vertical(vertical)
        if not info:
            raise ValueError('vertical not found')
        target = min(max(int(target), 1), 100)
        terms = SEARCH_TERMS.get(vertical) or [info['label']]
        campaign = f'GMAPS-{vertical.upper()}-{datetime.now().strftime("%Y%m%d")}'
        stats = {'imported': 0, 'mobile': 0, 'landline': 0, 'duplicates': 0, 'no_contact': 0, 'invalid': 0, 'api_calls': 0}
        conn = db()
        try:
            variant_index = 0
            for city, base_quota in CITY_PLAN:
                if stats['imported'] >= target:
                    break
                # Scale city quotas when a smaller target is requested.
                city_quota = min(base_quota, target - stats['imported'])
                city_imported = 0
                for term in terms:
                    if city_imported >= city_quota or stats['imported'] >= target:
                        break
                    token = None
                    pages = 0
                    while pages < 3 and city_imported < city_quota and stats['imported'] < target:
                        data = text_search(f'{term} در {city}', token)
                        stats['api_calls'] += 1
                        pages += 1
                        for place in data.get('places') or []:
                            variant = 'A' if variant_index % 2 == 0 else 'B'
                            result = import_place(conn, place, vertical, city, campaign, variant)
                            if result.startswith('imported'):
                                variant_index += 1
                                stats['imported'] += 1
                                city_imported += 1
                                if result == 'imported_mobile':
                                    stats['mobile'] += 1
                                else:
                                    stats['landline'] += 1
                            elif result == 'duplicate':
                                stats['duplicates'] += 1
                            elif result == 'no_contact':
                                stats['no_contact'] += 1
                            else:
                                stats['invalid'] += 1
                            if city_imported >= city_quota or stats['imported'] >= target:
                                break
                        conn.commit()
                        token = data.get('nextPageToken')
                        if not token:
                            break
            return stats
        finally:
            conn.commit(); conn.close()

    @app.get('/admin/maps')
    @admin_only
    def maps_dashboard():
        conn = db()
        rows = conn.execute("SELECT vertical,COUNT(*) c FROM leads WHERE meta_json LIKE '%google_%' GROUP BY vertical").fetchall()
        counts = {r['vertical']: r['c'] for r in rows}
        conn.close()
        return render_template('maps.html', configured=bool(api_key()), verticals=VERTICALS, order=CAMPAIGN_ORDER, counts=counts, cities=CITY_PLAN)

    @app.post('/admin/maps/seed')
    @admin_only
    def maps_seed_one():
        vertical = (request.form.get('vertical') or '').strip()
        target = min(max(int(request.form.get('target') or 100), 1), 100)
        if not api_key():
            flash('اول Secret با نام GOOGLE_MAPS_API_KEY را تنظیم کنید.', 'error')
            return redirect(url_for('maps_dashboard'))
        if vertical not in VERTICALS:
            flash('صنف معتبر نیست.', 'error')
            return redirect(url_for('maps_dashboard'))
        try:
            s = seed_vertical(vertical, target)
            flash(f"{s['imported']} کسب‌وکار {VERTICALS[vertical]['label']} وارد شد؛ {s['mobile']} موبایل، {s['landline']} تلفن ثابت، {s['duplicates']} تکراری، {s['api_calls']} درخواست Google.", 'success')
        except Exception as exc:
            flash(f'Google Places خطا داد: {str(exc)[:300]}', 'error')
        return redirect(url_for('maps_dashboard'))

    @app.post('/admin/maps/seed-all')
    @admin_only
    def maps_seed_all():
        if not api_key():
            flash('GOOGLE_MAPS_API_KEY تنظیم نشده.', 'error')
            return redirect(url_for('maps_dashboard'))
        target = min(max(int(request.form.get('target') or 100), 1), 100)
        totals = {'imported': 0, 'api_calls': 0, 'failed': 0}
        for vertical in CAMPAIGN_ORDER:
            try:
                s = seed_vertical(vertical, target)
                totals['imported'] += s['imported']
                totals['api_calls'] += s['api_calls']
            except Exception:
                totals['failed'] += 1
        flash(f"Seed همه اصناف تمام شد: {totals['imported']} کسب‌وکار وارد شد، {totals['api_calls']} درخواست Google، {totals['failed']} صنف خطا.", 'success' if not totals['failed'] else 'error')
        return redirect(url_for('maps_dashboard'))

    @app.get('/health/maps')
    def maps_health():
        return jsonify({'ok': True, 'configured': bool(api_key()), 'verticals': len(CAMPAIGN_ORDER), 'target_per_vertical': 100, 'cities': [x[0] for x in CITY_PLAN]})
