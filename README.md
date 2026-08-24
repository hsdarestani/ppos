# PPOS — Customer Growth System for Local Businesses

Programmatic personalized demos for outbound sales to Iranian SMBs.

## Current MVP

Core flow: lead database → personalized vertical demo → SMS/call → engagement tracking → presenter follow-up → checkout intent.

The first production vertical is **PPOS Beauty OS**. It is a sellable multi-tenant SaaS product, not a website template.

## Beauty OS

- Premium Persian RTL public salon site with 10+ conversion sections
- Five-step booking: service → specialist → date → time → confirmation
- Phone/PIN customer account, appointment history, cancellation, favorites, offers and loyalty
- Salon dashboard with calendar, customers, services, staff schedules, reviews and marketing automations
- Tenant-isolated models for businesses, users, customers, staff, services, appointments, campaigns, messages, reviews, payments and favorites
- Personalized prospect demos at `/demo/<slug>`
- Showcase at `/beauty-os` (demo admin: `09120000000` / `1234`)

Commercial packaging is prepared for Starter (499,000 toman/month) and future Pro (899,000 toman/month).

The outbound engine and its existing vertical demos remain available for prospecting. The prior real-estate flow continues to use `d/<slug>`.

## Real-estate 100-lead test

1. Open `/admin` and complete first-run password setup.
2. Use **ساخت ۱۰۰ لید تستی A/B** to QA the campaign without inventing real phone numbers.
3. Import the real prospect list as CSV. Supported columns:
   `business_name,vertical,phone,city,address,instagram,logo_url,campaign,variant,source`
4. Use `realestate` as the vertical. If `variant` is omitted, imports alternate A/B automatically.
5. Open each lead to copy its personalized SMS. Presenter priority is based on Hot Score.

Real contact lists are intentionally kept out of Git because this repository is public. They live only in the production SQLite database after admin CSV import.

Initial secondary verticals: beauty salons, auto galleries, aesthetic clinics, auto repair.
