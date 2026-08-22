from app import app, DB_PATH
from capture import register_capture

register_capture(app, DB_PATH)
