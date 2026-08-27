# PPOS

Personalized outbound + vertical SaaS platform for local businesses.

## Production

- Platform: https://ppos.smarbiz.sbs
- Campaign hub: `/admin/campaigns`
- Outbound ops: `/admin/outreach`
- Call desk: `/admin/calls`
- Beauty OS: `/beauty-os`

## Google Maps / business database import

The campaign hub accepts CSV/XLSX exports and normalizes common Persian and Google Maps column names.

The XLSX importer is resilient to exporter metadata before the real table header. It scans the first rows, detects the most likely business-data header, then parses the rows below it. Upload bytes are copied into a seekable in-memory buffer before `openpyxl` reads them, so Werkzeug `SpooledTemporaryFile` uploads work consistently in production.

Mobile numbers are normalized for SMS eligibility; valid landlines are retained for Call Desk instead of being discarded. Duplicate businesses are filtered by the existing lead identity rules.

## Safety

Outbound SMS remains dry-run unless the production SMS settings explicitly enable live sending.
