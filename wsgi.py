from app import app, DB_PATH
from capture import register_capture
from exports import register_exports
from campaigns import register_campaigns
from activation import register_activation

register_capture(app, DB_PATH)
register_exports(app, DB_PATH)
register_campaigns(app, DB_PATH)
register_activation(app, DB_PATH)
