# PPOS — Campaign Launch Runbook

PPOS is designed so a raw Iranian business database can go directly from upload to personalized outbound.

## 1. Source the business database

Preferred input is a categorized CSV/XLSX with as many of these fields as possible:

- نام فروشگاه یا مرکز / نام کسب و کار
- تفکیک صنف / نوع صنف
- شماره موبایل
- تلفن ثابت
- آدرس پستی
- شهر
- نام فرد مسئول

The raw importer understands these Persian headers and maps recognized guild names into the 30 PPOS verticals. Use only contact data you are entitled to use for business outreach and keep suppression/opt-out requests in PPOS.

## 2. Import

Open `/admin/campaigns` → **ورود دیتابیس خام**.

- CSV and XLSX supported.
- Up to 100 MB per upload.
- Persian/Arabic digits normalized.
- Mobile and landline separated internally.
- Duplicate business/phone records skipped.
- A/B variants assigned automatically.
- Unknown categories are skipped instead of being guessed into a wrong vertical.

For very large databases, split by city or category when practical so campaign results stay measurable.

## 3. QA before sending

Open a vertical campaign and inspect several personalized demos. Confirm:

- business name is correct;
- phone/address are correct;
- product/CTA matches the vertical;
- SMS A/B copy reads naturally;
- demo capture and activation work.

## 4. Prepare outbound

Open `/admin/outreach`.

PPOS only queues valid Iranian mobile numbers and excludes the Do-Not-Contact list. Landline-only records remain available in Call Queue exports but are not sent SMS.

## 5. SMS provider

Supported providers:

- `ippanel`
- `kavenegar`

Add these GitHub repository secrets:

- `SMS_PROVIDER` — `ippanel` or `kavenegar`
- `SMS_API_KEY`
- `SMS_SENDER`
- `SMS_LIVE` — keep `0` during QA; set to `1` only when ready to send real messages

Deployment copies these values into the protected production environment file. The UI never displays the API key.

## 6. Safe launch sequence

1. Import 100–500 prospects from one vertical/city.
2. Queue 25–50 SMS.
3. Keep `SMS_LIVE=0` and run Dry Run.
4. Inspect message copy and demo links.
5. Set `SMS_LIVE=1` only after QA.
6. Send a small batch first.
7. Watch Demo Open, Complete, Checkout and Won.
8. Presenter calls Hot Leads first.
9. Add every opt-out / do-not-contact number to suppression immediately.
10. Scale only the winning A/B variant and vertical.

## 7. Production URLs

- Campaign Hub: `https://ppos.smarbiz.sbs/admin/campaigns`
- Outbound Ops: `https://ppos.smarbiz.sbs/admin/outreach`
- Campaign health: `https://ppos.smarbiz.sbs/health/campaigns`
- Outreach health: `https://ppos.smarbiz.sbs/health/outreach`

The system defaults to Dry Run. No real SMS is sent unless provider credentials exist and `SMS_LIVE=1`.
