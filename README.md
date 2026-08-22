# PPOS — Personalized Product Outbound System

Programmatic personalized demos for outbound sales to Iranian SMBs.

## Current MVP

Core flow: lead database → personalized vertical demo → SMS/call → engagement tracking → presenter follow-up → checkout intent.

The first optimized vertical is **real estate**. Each agency gets a personalized `d/<slug>` page containing a three-step property finder, simulated matched listings, a live lead-preview showing what the agency receives, and a one-click activation CTA.

## Real-estate 100-lead test

1. Open `/admin` and complete first-run password setup.
2. Use **ساخت ۱۰۰ لید تستی A/B** to QA the campaign without inventing real phone numbers.
3. Import the real prospect list as CSV. Supported columns:
   `business_name,vertical,phone,city,address,instagram,logo_url,campaign,variant,source`
4. Use `realestate` as the vertical. If `variant` is omitted, imports alternate A/B automatically.
5. Open each lead to copy its personalized SMS. Presenter priority is based on Hot Score.

Real contact lists are intentionally kept out of Git because this repository is public. They live only in the production SQLite database after admin CSV import.

Initial secondary verticals: beauty salons, auto galleries, aesthetic clinics, auto repair.