import os
import sqlite3

# Define the DB path
DB_PATH = os.path.join("db", "perpetuals.db")

def get_connection():
    """Returns a connection object to the SQLite database."""
    return sqlite3.connect(DB_PATH)

def create_monitored_positions_table():
    """Create the monitored_positions table if it doesn't exist."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS monitored_positions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            asset TEXT NOT NULL UNIQUE,
            position_size REAL NOT NULL,
            risk_threshold REAL NOT NULL
        )
    """)
    conn.commit()
    conn.close()

def create_auto_hedge_table():
    """Create the auto_hedges table for dynamic rebalancing support."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS auto_hedges (
            asset TEXT PRIMARY KEY,
            rebalance_interval INTEGER,
            last_hedge_amount REAL DEFAULT 0
        )
    """)
    conn.commit()
    conn.close()

def init_db():
    """Ensure the database and necessary tables are initialized."""
    os.makedirs("db", exist_ok=True)
    create_monitored_positions_table()
    create_auto_hedge_table()
