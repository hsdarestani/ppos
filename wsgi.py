from app import app, DB_PATH
from capture import register_capture
from exports import register_exports
from campaigns import register_campaigns
from activation import register_activation
from campaign_tools import register_campaign_tools
from data_ingest import register_data_ingest
from outreach import register_outreach
from db_optimizations import optimize_database

# Real business-database exports can contain hundreds of thousands of rows.
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024

optimize_database(DB_PATH)
register_capture(app, DB_PATH)
register_exports(app, DB_PATH)
register_campaigns(app, DB_PATH)
register_activation(app, DB_PATH)
register_campaign_tools(app)
register_data_ingest(app, DB_PATH)
register_outreach(app, DB_PATH)
