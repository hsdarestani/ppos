import csv
import io
import json
import re
import secrets
import sqlite3
from datetime import datetime
from functools import wraps
from itertools import chain

from flask import flash, redirect, request, session, url_for
from openpyxl import load_workbook

from verticals import VERTICALS

PERSIAN_DIGITS = str.maketrans('۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩', '01234567890123456789')

HEADER_ALIASES = {
    'business_name': ['business_name','name','نام کسب و کار','نام کسب‌وکار','نام فروشگاه','نام مرکز','نام فروشگاه یا مرکز','نام واحد','واحد صنفی','نام واحد صنفی'],
    'mobile': ['mobile','phone','موبایل','موبايل','شماره موبایل','شماره موبايل','شماره همراه','تلفن همراه'],
    'landline': ['landline','fixed_phone','telephone','تلفن','تلفن ثابت','شماره ثابت'],
    'city': ['city','شهر','شهرستان'],
    'address': ['address','آدرس','ادرس','آدرس پستی','نشانی'],
    'category': ['category','guild','vertical','صنف','نوع صنف','تفکیک صنف','رسته','دسته بندی','دسته‌بندی','گروه شغلی'],
    'owner': ['owner','owner_name','نام مسئول','نام فرد مسئول','مدیر','نام مدیر'],
    'instagram': ['instagram','اینستاگرام','اینستا'],
    'logo_url': ['logo_url','logo','لوگو'],
}

CATEGORY_KEYWORDS = {
    'realestate': ['املاک','مشاور املاک','بنگاه','مسکن'],
    'beauty': ['آرایش زنانه','آرایشگاه زنانه','سالن زیبایی','زیبایی زنانه'],
    'barber': ['آرایش مردانه','آرایشگاه مردانه','پیرایش مردانه'],
    'auto': ['اتوگالری','نمایشگاه اتومبیل','نمایشگاه خودرو','خرید و فروش خودرو'],
    'aesthetic': ['کلینیک زیبایی','مرکز زیبایی','پوست و مو'],
    'dentist': ['دندانپزشک','دندانپزشکی','کلینیک دندان'],
    'gym': ['باشگاه بدنسازی','باشگاه ورزشی','فیتنس','بدنسازی'],
    'trainer': ['مربی خصوصی','مربی شخصی','پرسونال ترینر'],
    'language': ['آموزشگاه زبان','موسسه زبان'],
    'education': ['آموزشگاه','کنکور','مشاوره تحصیلی'],
    'repair': ['تعمیرگاه خودرو','مکانیکی','اتو سرویس','تعمیر اتومبیل'],
    'parts': ['لوازم یدکی','قطعات خودرو','یدکی اتومبیل'],
    'carwash': ['کارواش','دیتیلینگ','صفرشویی'],
    'fashion': ['مزون','لباس مجلسی','پوشاک زنانه'],
    'gold': ['طلافروشی','طلا و جواهر','جواهرفروشی'],
    'furniture': ['مبلمان','مبل فروشی','فروش مبلمان'],
    'cabinet': ['کابینت','کابینت سازی','کابینت‌سازی'],
    'restaurant': ['رستوران','کافه','کافی شاپ','فست فود'],
    'pet': ['پت شاپ','پت‌شاپ','دامپزشکی','کلینیک دامپزشکی'],
    'mobile': ['موبایل فروشی','فروش موبایل','گوشی موبایل'],
    'immigration': ['مهاجرت','موسسه مهاجرتی','خدمات مهاجرتی'],
    'travel': ['آژانس مسافرتی','خدمات مسافرتی','تور و گردشگری'],
    'insurance': ['بیمه','نمایندگی بیمه'],
    'legal': ['دفتر حقوقی','وکالت','وکیل','موسسه حقوقی'],
    'home_services': ['خدمات ساختمان','تعمیرات ساختمان','تعمیرات منزل'],
    'hvac': ['تاسیسات','تأسیسات','پکیج','کولر','آبگرمکن'],
    'carpet': ['قالیشویی','قالی شویی'],
    'laundry': ['خشکشویی','خشک شویی'],
    'studio': ['آتلیه','استودیو عکاسی','عکاسی'],
    'venue': ['تالار','باغ تالار','تشریفات مجالس'],
}


def _canon(value):
    return re.sub(r'\s+', ' ', str(value or '').translate(PERSIAN_DIGITS).replace('\u200c',' ').strip().lower())


def _normalize_mobile(value):
    raw = re.sub(r'\D', '', str(value or '').translate(PERSIAN_DIGITS))
    if raw.startswith('0098'):
        raw = '0' + raw[4:]
    elif raw.startswith('98') and len(raw) == 12:
        raw = '0' + raw[2:]
    elif raw.startswith('9') and len(raw) == 10:
        raw = '0' + raw
    return raw if re.fullmatch(r'09\d{9}', raw) else ''


def _normalize_phone(value):
    raw = re.sub(r'\D', '', str(value or '').translate(PERSIAN_DIGITS))
    if raw.startswith('98') and len(raw) >= 11:
        raw = '0' + raw[2:]
    return raw[:15]


def _header_map(headers):
    normalized = {_canon(h): h for h in headers if h is not None}
    out = {}
    for target, aliases in HEADER_ALIASES.items():
        for alias in aliases:
            key = _canon(alias)
            if key in normalized:
                out[target] = normalized[key]
                break
    return out


def detect_vertical(category, name=''):
    hay = _canon(f'{category} {name}')
    order = ['realestate','beauty','barber','auto','aesthetic','dentist','gym','trainer','language','repair','parts','carwash','fashion','gold','furniture','cabinet','restaurant','pet','mobile','immigration','travel','insurance','legal','home_services','hvac','carpet','laundry','studio','venue','education']
    for key in order:
        if any(_canon(word) in hay for word in CATEGORY_KEYWORDS.get(key, [])):
            return key
    return ''


def _rows_from_upload(file_storage):
    filename = (file_storage.filename or '').lower()
    file_storage.stream.seek(0)
    if filename.endswith('.xlsx'):
        wb = load_workbook(file_storage.stream, read_only=True, data_only=True)
        ws = wb.active
        iterator = ws.iter_rows(values_only=True)
        headers = [str(x or '').strip() for x in next(iterator, [])]
        for values in iterator:
            yield {headers[i]: values[i] if i < len(values) else '' for i in range(len(headers))}
        return
    wrapper = io.TextIOWrapper(file_storage.stream, encoding='utf-8-sig', errors='ignore', newline='')
    yield from csv.DictReader(wrapper)


def register_data_ingest(app, db_path):
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

    @app.post('/admin/data/import-raw')
    @admin_only
    def import_raw_business_database():
        upload = request.files.get('file')
        default_vertical = (request.form.get('vertical') or '').strip()
        campaign = (request.form.get('campaign') or 'OUTBOUND-LIVE').strip()
        source = (request.form.get('source') or 'business_database').strip()
        if not upload:
            flash('فایل CSV/XLSX انتخاب نشده.', 'error')
            return redirect(url_for('campaigns_hub'))

        iterator = iter(_rows_from_upload(upload))
        first = next(iterator, None)
        if not first:
            flash('فایل خالی است.', 'error')
            return redirect(url_for('campaigns_hub'))
        hm = _header_map(list(first.keys()))
        if 'business_name' not in hm:
            flash('ستون نام کسب‌وکار پیدا نشد.', 'error')
            return redirect(url_for('campaigns_hub'))

        conn = db()
        imported = skipped = no_mobile = auto_mapped = 0
        for row in chain([first], iterator):
            name = str(row.get(hm['business_name']) or '').strip()
            category = str(row.get(hm.get('category','')) or '').strip() if hm.get('category') else ''
            vertical = default_vertical or detect_vertical(category, name)
            if not name or vertical not in VERTICALS:
                skipped += 1
                continue
            if not default_vertical:
                auto_mapped += 1
            mobile = _normalize_mobile(row.get(hm.get('mobile',''))) if hm.get('mobile') else ''
            landline = _normalize_phone(row.get(hm.get('landline',''))) if hm.get('landline') else ''
            primary = mobile or landline
            if not mobile:
                no_mobile += 1
            if not primary:
                skipped += 1
                continue
            duplicate = conn.execute('SELECT id FROM leads WHERE vertical=? AND (phone=? OR business_name=?) LIMIT 1', (vertical, primary, name)).fetchone()
            if duplicate:
                skipped += 1
                continue
            meta = {
                'campaign': campaign,
                'variant': 'A' if imported % 2 == 0 else 'B',
                'source': source,
                'raw_category': category,
                'owner': str(row.get(hm.get('owner','')) or '').strip() if hm.get('owner') else '',
                'mobile': mobile,
                'landline': landline,
                'sms_eligible': bool(mobile),
            }
            slugbase = re.sub(r'[^a-z0-9\u0600-\u06ff]+', '-', name.lower()).strip('-')[:42] or 'business'
            slug = f'{slugbase}-{secrets.token_hex(2)}'
            conn.execute(
                '''INSERT INTO leads(slug,business_name,vertical,phone,city,address,instagram,logo_url,accent,meta_json,status,created_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?)''',
                (
                    slug, name, vertical, primary,
                    str(row.get(hm.get('city','')) or '').strip() if hm.get('city') else '',
                    str(row.get(hm.get('address','')) or '').strip() if hm.get('address') else '',
                    str(row.get(hm.get('instagram','')) or '').strip() if hm.get('instagram') else '',
                    str(row.get(hm.get('logo_url','')) or '').strip() if hm.get('logo_url') else '',
                    '#5b4df5', json.dumps(meta, ensure_ascii=False), 'new', datetime.now().isoformat(timespec='seconds')
                )
            )
            imported += 1
            if imported % 1000 == 0:
                conn.commit()
        conn.commit(); conn.close()
        flash(f'{imported} لید وارد شد؛ {skipped} رد/تکراری؛ {no_mobile} مورد فقط تماس تلفنی؛ {auto_mapped} مورد صنف خودکار تشخیص داده شد.', 'success')
        return redirect(url_for('campaigns_hub'))
