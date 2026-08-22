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

# Real business-database exports can contain hundreds of thousands of rows.
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024

apply_vendor_compat(CATEGORY_KEYWORDS)
optimize_database(DB_PATH)
register_capture(app, DB_PATH)
register_exports(app, DB_PATH)
register_campaigns(app, DB_PATH)
register_activation(app, DB_PATH)
register_campaign_tools(app)
register_data_ingest(app, DB_PATH)
register_outreach(app, DB_PATH)
register_call_ops(app, DB_PATH)
