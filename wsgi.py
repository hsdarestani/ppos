from app import app, DB_PATH
from capture import register_capture
from exports import register_exports

register_capture(app, DB_PATH)
register_exports(app, DB_PATH)
