import os

from app import app, DB_PATH
from capture import register_capture
from exports import register_exports
from campaigns import register_campaigns
from activation import register_activation
from campaign_tools import register_campaign_tools
from data_ingest import register_data_ingest, CATEGORY_KEYWORDS
from outreach import register_outreach
from call_ops import register_call_ops
from db_optimizations import optimize_database
from vendor_compat import apply_vendor_compat
from presentation import apply_presentation
from outbound_copy import apply_outbound_copy
from vertical_sites import register_vertical_sites
from site_redirects import register_site_redirects
from site_admin import register_site_admin
from booking_os import register_booking_os
from verticals import VERTICALS

# Real business-database exports can contain hundreds of thousands of rows.
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024

apply_vendor_compat(CATEGORY_KEYWORDS)
apply_presentation(VERTICALS)
apply_outbound_copy(VERTICALS)
# Use an Embed-key restricted to ppos.smarbiz.sbs when possible. A separate
# GOOGLE_MAPS_API_KEY fallback is kept for existing deployments.
app.jinja_env.globals['maps_embed_key'] = (os.environ.get('GOOGLE_MAPS_EMBED_KEY') or os.environ.get('GOOGLE_MAPS_API_KEY') or '').strip()

optimize_database(DB_PATH)
register_capture(app, DB_PATH)
register_exports(app, DB_PATH)
register_campaigns(app, DB_PATH)
register_activation(app, DB_PATH)
register_campaign_tools(app)
register_data_ingest(app, DB_PATH)
register_outreach(app, DB_PATH)
register_call_ops(app, DB_PATH)
register_vertical_sites(app, DB_PATH)
register_booking_os(app, DB_PATH)
register_site_admin(app, DB_PATH)
register_site_redirects(app, DB_PATH)
