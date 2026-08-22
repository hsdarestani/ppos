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
    'business_name': [
        'business_name','name','title','place_name','نام کسب و کار','نام کسب‌وکار','نام فروشگاه','نام مرکز',
        'نام فروشگاه یا مرکز','نام واحد','واحد صنفی','نام واحد صنفی'
    ],
    'mobile': ['mobile','mobile_phone','cellphone','موبایل','موبايل','شماره موبایل','شماره موبايل','شماره همراه','تلفن همراه'],
    'phone_any': ['phone','phone_number','contact_phone','formatted_phone_number','international_phone_number','شماره تماس'],
    'landline': ['landline','fixed_phone','telephone','tel','تلفن','تلفن ثابت','شماره ثابت'],
    'city': ['city','municipality','locality','شهر','شهرستان'],
    'address': ['address','full_address','formatted_address','street_address','آدرس','ادرس','آدرس پستی','نشانی'],
    'category': ['category','categories','type','types','subtype','subtypes','guild','vertical','صنف','نوع صنف','تفکیک صنف','رسته','دسته بندی','دسته‌بندی','گروه شغلی'],
    'owner': ['owner','owner_name','نام مسئول','نام فرد مسئول','مدیر','نام مدیر'],
    'instagram': ['instagram','instagram_url','اینستاگرام','اینستا'],
    'logo_url': ['logo_url','logo','image','photo','thumbnail','لوگو'],
    'website': ['website','site','web_site','domain','وبسایت','وب سایت','سایت'],
    'maps_url': ['google_maps_url','google_url','maps_url','place_url','google_maps_link','map_link','link'],
    'place_id': ['place_id','google_place_id','google_id','google_maps_id','cid'],
    'rating': ['rating','stars','score','امتیاز'],
    'reviews': ['reviews','reviews_count','review_count','user_ratings_total','number_of_reviews','تعداد نظر','تعداد نظرات'],
    'latitude': ['latitude','lat','عرض جغرافیایی'],
    'longitude': ['longitude','lng','lon','long','طول جغرافیایی'],
    'opening_hours': ['opening_hours','working_hours','hours','business_hours','ساعات کاری'],
    'status': ['business_status','status','وضعیت'],
}

CATEGORY_KEYWORDS = {
    'realestate': ['املاک','مشاور املاک','بنگاه','مسکن','real estate','real estate agency','property'],
    'beauty': ['آرایش زنانه','آرایشگاه زنانه','سالن زیبایی','زیبایی زنانه','beauty salon','hair salon','nail salon'],
    'barber': ['آرایش مردانه','آرایشگاه مردانه','پیرایش مردانه','barber','barber shop'],
    'auto': ['اتوگالری','نمایشگاه اتومبیل','نمایشگاه خودرو','خرید و فروش خودرو','car dealer','used car dealer'],
    'aesthetic': ['کلینیک زیبایی','مرکز زیبایی','پوست و مو','aesthetic clinic','skin care clinic','laser hair removal service'],
    'dentist': ['دندانپزشک','دندانپزشکی','کلینیک دندان','dentist','dental clinic'],
    'gym': ['باشگاه بدنسازی','باشگاه ورزشی','فیتنس','بدنسازی','gym','fitness center','pilates studio'],
    'trainer': ['مربی خصوصی','مربی شخصی','پرسونال ترینر','personal trainer'],
    'language': ['آموزشگاه زبان','موسسه زبان','language school','english language school'],
    'education': ['آموزشگاه','کنکور','مشاوره تحصیلی','education center','training center','tutoring service'],
    'repair': ['تعمیرگاه خودرو','مکانیکی','اتو سرویس','تعمیر اتومبیل','auto repair shop','car repair','mechanic'],
    'parts': ['لوازم یدکی','قطعات خودرو','یدکی اتومبیل','auto parts store','car parts'],
    'carwash': ['کارواش','دیتیلینگ','صفرشویی','car wash','car detailing service'],
    'fashion': ['مزون','لباس مجلسی','پوشاک زنانه','clothing store','dress store','boutique'],
    'gold': ['طلافروشی','طلا و جواهر','جواهرفروشی','jewelry store','jeweler','gold dealer'],
    'furniture': ['مبلمان','مبل فروشی','فروش مبلمان','furniture store'],
    'cabinet': ['کابینت','کابینت سازی','کابینت‌سازی','cabinet maker','kitchen remodeler'],
    'restaurant': ['رستوران','کافه','کافی شاپ','فست فود','restaurant','cafe','coffee shop','fast food restaurant'],
    'pet': ['پت شاپ','پت‌شاپ','دامپزشکی','کلینیک دامپزشکی','pet store','veterinarian','animal hospital'],
    'mobile': ['موبایل فروشی','فروش موبایل','گوشی موبایل','cell phone store','mobile phone shop'],
    'immigration': ['مهاجرت','موسسه مهاجرتی','خدمات مهاجرتی','immigration consultant','visa consultant'],
    'travel': ['آژانس مسافرتی','خدمات مسافرتی','تور و گردشگری','travel agency','tour agency'],
    'insurance': ['بیمه','نمایندگی بیمه','insurance agency','insurance broker'],
    'legal': ['دفتر حقوقی','وکالت','وکیل','موسسه حقوقی','law firm','lawyer','legal services'],
    'home_services': ['خدمات ساختمان','تعمیرات ساختمان','تعمیرات منزل','home services','handyman','home improvement'],
    'hvac': ['تاسیسات','تأسیسات','پکیج','کولر','آبگرمکن','hvac contractor','air conditioning repair service','heating contractor'],
    'carpet': ['قالیشویی','قالی شویی','carpet cleaning service'],
    'laundry': ['خشکشویی','خشک شویی','dry cleaner','laundry service'],
    'studio': ['آتلیه','استودیو عکاسی','عکاسی','photography studio','photographer'],
    'venue': ['تالار','باغ تالار','تشریفات مجالس','wedding venue','banquet hall','event venue'],
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
    if raw.startswith('0098'):
        raw = '0' + raw[4:]
    elif raw.startswith('98') and len(raw) >= 11:
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


def _cell(row, hm, key):
    header = hm.get(key)
    return row.get(header) if header else ''


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
            flash('ستون نام کسب‌وکار پیدا نشد. ستون‌هایی مثل name / title / نام فروشگاه پشتیبانی می‌شوند.', 'error')
            return redirect(url_for('campaigns_hub'))

        looks_like_google = bool(hm.get('place_id') or hm.get('maps_url') or hm.get('rating'))
        if source == 'business_database' and looks_like_google:
            source = 'google_maps'

        conn = db()
        imported = skipped = no_mobile = auto_mapped = place_duplicates = no_contact = 0
        for row in chain([first], iterator):
            name = str(_cell(row, hm, 'business_name') or '').strip()
            category = str(_cell(row, hm, 'category') or '').strip()
            vertical = default_vertical or detect_vertical(category, name)
            if not name or vertical not in VERTICALS:
                skipped += 1
                continue
            if not default_vertical:
                auto_mapped += 1

            generic_phone = _cell(row, hm, 'phone_any')
            raw_mobile = _cell(row, hm, 'mobile') or generic_phone
            raw_landline = _cell(row, hm, 'landline') or generic_phone
            mobile = _normalize_mobile(raw_mobile)
            landline = _normalize_phone(raw_landline)
            if mobile and landline == mobile:
                landline = ''
            primary = mobile or landline
            if not mobile:
                no_mobile += 1
            if not primary:
                no_contact += 1
                skipped += 1
                continue

            address = str(_cell(row, hm, 'address') or '').strip()
            city = str(_cell(row, hm, 'city') or '').strip()
            place_id = str(_cell(row, hm, 'place_id') or '').strip()

            if place_id and conn.execute(
                'SELECT 1 FROM lead_external_ids WHERE provider=? AND external_id=? LIMIT 1',
                ('google_maps', place_id),
            ).fetchone():
                place_duplicates += 1
                skipped += 1
                continue

            duplicate = conn.execute(
                '''SELECT id FROM leads
                   WHERE vertical=? AND (
                       phone=? OR
                       (business_name=? AND COALESCE(address,'')=? AND ?!='') OR
                       (business_name=? AND COALESCE(city,'')=? AND COALESCE(address,'')='' AND ?!='')
                   ) LIMIT 1''',
                (vertical, primary, name, address, address, name, city, city),
            ).fetchone()
            if duplicate:
                skipped += 1
                if place_id:
                    try:
                        conn.execute(
                            'INSERT OR IGNORE INTO lead_external_ids(provider,external_id,lead_id,created_at) VALUES(?,?,?,?)',
                            ('google_maps', place_id, duplicate['id'], datetime.now().isoformat(timespec='seconds')),
                        )
                    except Exception:
                        pass
                continue

            meta = {
                'campaign': campaign,
                'variant': 'A' if imported % 2 == 0 else 'B',
                'source': source,
                'raw_category': category,
                'owner': str(_cell(row, hm, 'owner') or '').strip(),
                'mobile': mobile,
                'landline': landline,
                'sms_eligible': bool(mobile),
                'website': str(_cell(row, hm, 'website') or '').strip(),
                'google_maps_url': str(_cell(row, hm, 'maps_url') or '').strip(),
                'place_id': place_id,
                'rating': str(_cell(row, hm, 'rating') or '').strip(),
                'reviews': str(_cell(row, hm, 'reviews') or '').strip(),
                'latitude': str(_cell(row, hm, 'latitude') or '').strip(),
                'longitude': str(_cell(row, hm, 'longitude') or '').strip(),
                'opening_hours': str(_cell(row, hm, 'opening_hours') or '').strip(),
                'business_status': str(_cell(row, hm, 'status') or '').strip(),
            }
            slugbase = re.sub(r'[^a-z0-9\u0600-\u06ff]+', '-', name.lower()).strip('-')[:42] or 'business'
            slug = f'{slugbase}-{secrets.token_hex(2)}'
            cur = conn.execute(
                '''INSERT INTO leads(slug,business_name,vertical,phone,city,address,instagram,logo_url,accent,meta_json,status,created_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?)''',
                (
                    slug, name, vertical, primary, city, address,
                    str(_cell(row, hm, 'instagram') or '').strip(),
                    str(_cell(row, hm, 'logo_url') or '').strip(),
                    '#5b4df5', json.dumps(meta, ensure_ascii=False), 'new', datetime.now().isoformat(timespec='seconds')
                )
            )
            lead_id = cur.lastrowid
            if place_id:
                conn.execute(
                    'INSERT OR IGNORE INTO lead_external_ids(provider,external_id,lead_id,created_at) VALUES(?,?,?,?)',
                    ('google_maps', place_id, lead_id, datetime.now().isoformat(timespec='seconds')),
                )
            imported += 1
            if imported % 1000 == 0:
                conn.commit()
        conn.commit(); conn.close()

        source_label = 'Google Maps' if source == 'google_maps' else source
        flash(
            f'{imported} لید از {source_label} وارد شد؛ {skipped} رد/تکراری؛ '
            f'{no_mobile} مورد فقط تماس تلفنی؛ {place_duplicates} Place ID تکراری؛ '
            f'{no_contact} مورد بدون شماره؛ {auto_mapped} مورد صنف خودکار تشخیص داده شد.',
            'success'
        )
        return redirect(url_for('campaigns_hub'))
