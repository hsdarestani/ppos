import sqlite3


def optimize_database(db_path):
    conn = sqlite3.connect(db_path)
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA synchronous=NORMAL')
    conn.execute('PRAGMA busy_timeout=5000')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_leads_vertical_phone ON leads(vertical, phone)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_leads_vertical_name ON leads(vertical, business_name)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_leads_status ON leads(status)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_events_lead_type ON events(lead_id, event_type)')
    conn.commit()
    conn.close()
