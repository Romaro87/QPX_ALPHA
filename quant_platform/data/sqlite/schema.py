
def create_tables(db):

    tables = [

    """
    CREATE TABLE IF NOT EXISTS market_data(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        symbol TEXT,
        timestamp TEXT,
        open REAL,
        high REAL,
        low REAL,
        close REAL,
        volume REAL
    )
    """,

    """
    CREATE TABLE IF NOT EXISTS trades(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        symbol TEXT,
        entry_price REAL,
        exit_price REAL,
        quantity REAL,
        side TEXT,
        pnl REAL,
        timestamp TEXT
    )
    """,

    """
    CREATE TABLE IF NOT EXISTS portfolio_snapshots(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT,
        cash REAL,
        equity REAL,
        exposure REAL,
        drawdown REAL
    )
    """
    ]


    for table in tables:
        db.execute(table)
