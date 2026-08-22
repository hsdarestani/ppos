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
    conn.execute('''
        CREATE TABLE IF NOT EXISTS lead_external_ids (
            provider TEXT NOT NULL,
            external_id TEXT NOT NULL,
            lead_id INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY(provider, external_id),
            FOREIGN KEY(lead_id) REFERENCES leads(id)
        )
    ''')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_external_lead ON lead_external_ids(lead_id)')
    conn.commit()
    conn.close()
