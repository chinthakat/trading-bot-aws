
import sqlite3
import os
import platform
import logging
import json
from decimal import Decimal
from datetime import datetime
from typing import List, Dict, Optional

class DecimalEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, Decimal):
            return float(obj)
        if isinstance(obj, datetime):
            return obj.isoformat()
        return super(DecimalEncoder, self).default(obj)

logger = logging.getLogger(__name__)

class SharedDbService:
    def __init__(self, db_name="trading_bot.db"):
        self.db_path = self._get_db_path(db_name)
        self.conn = None
        self._init_db()

    def _get_db_path(self, db_name):
        system = platform.system()
        if system == "Linux":
            # Use Shared Memory
            path = os.path.join("/dev/shm", db_name)
        else:
            # Fallback for Windows/Mac
            path = db_name # Local file
        logger.info(f"Using Shared DB at: {path}")
        return path

    def _init_db(self):
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        
        # Enable WAL Mode for concurrency
        self.conn.execute("PRAGMA journal_mode=WAL;")
        self.conn.execute("PRAGMA synchronous=NORMAL;")
        
        self._create_tables()

    def _create_tables(self):
        cursor = self.conn.cursor()
        
        # Market Data
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS market_data (
                symbol TEXT,
                interval TEXT,
                timestamp INTEGER,
                open REAL,
                high REAL,
                low REAL,
                close REAL,
                volume REAL,
                PRIMARY KEY (symbol, interval, timestamp)
            )
        """)
        
        # Signals
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS signals (
                signal_id TEXT PRIMARY KEY,
                strategy_name TEXT,
                symbol TEXT,
                side TEXT,
                price REAL,
                timestamp INTEGER,
                status TEXT DEFAULT 'NEW',
                metadata TEXT
            )
        """)
        
        # Positions
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS positions (
                position_id TEXT PRIMARY KEY,
                strategy_name TEXT,
                symbol TEXT,
                side TEXT,
                quantity REAL,
                entry_price REAL,
                current_price REAL,
                pnl REAL,
                status TEXT,
                entry_time INTEGER,
                exit_time INTEGER,
                metadata TEXT
            )
        """)
        
        # Account
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS account (
                account_id TEXT PRIMARY KEY,
                balance REAL,
                equity REAL,
                pnl REAL,
                updated_at INTEGER
            )
        """)
        
        self.conn.commit()

    def close(self):
        if self.conn:
            self.conn.close()

    # --- Market Data Methods ---
    
    def write_candle(self, candle: Dict):
        # Insert or Replace
        query = """
            INSERT OR REPLACE INTO market_data (symbol, interval, timestamp, open, high, low, close, volume)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """
        try:
            self.conn.execute(query, (
                candle['symbol'], candle.get('interval', '1m'), candle['timestamp'],
                candle['open'], candle['high'], candle['low'], candle['close'], candle['volume']
            ))
            self.conn.commit()
        except Exception as e:
            logger.error(f"DB Write Candle Error: {e}")

    def get_recent_candles(self, symbol: str, limit: int = 100) -> List[Dict]:
        query = """
            SELECT * FROM market_data 
            WHERE symbol = ? 
            ORDER BY timestamp DESC 
            LIMIT ?
        """
        cursor = self.conn.execute(query, (symbol, limit))
        rows = cursor.fetchall()
        # Sort ASC for analysis
        return [dict(row) for row in rows][::-1]

    # --- Signal Methods ---

    def write_signal(self, signal: Dict):
        query = """
            INSERT OR REPLACE INTO signals (signal_id, strategy_name, symbol, side, price, timestamp, status, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """
        meta = json.dumps(signal.get('metadata', {}), cls=DecimalEncoder)
        self.conn.execute(query, (
            signal['signal_id'], signal['strategy_name'], signal['symbol'], 
            signal['side'], signal['price'], signal['timestamp'], 
            signal.get('status', 'NEW'), meta
        ))
        self.conn.commit()

    def get_new_signals(self) -> List[Dict]:
        query = "SELECT * FROM signals WHERE status = 'NEW' ORDER BY timestamp ASC"
        cursor = self.conn.execute(query)
        return [dict(row) for row in cursor.fetchall()]

    def get_recent_signals(self, limit: int = 50) -> List[Dict]:
        query = "SELECT * FROM signals ORDER BY timestamp DESC LIMIT ?"
        cursor = self.conn.execute(query, (limit,))
        return [dict(row) for row in cursor.fetchall()]

    def mark_signal_processed(self, signal_id: str):
        self.conn.execute("UPDATE signals SET status = 'PROCESSED' WHERE signal_id = ?", (signal_id,))
        self.conn.commit()

    # --- Position Methods ---
    
    def update_position(self, pos: Dict):
        query = """
            INSERT OR REPLACE INTO positions (position_id, strategy_name, symbol, side, quantity, entry_price, current_price, pnl, status, entry_time, exit_time, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        # Handle Timestamps
        entry_t = int(pos['entry_time'].timestamp()*1000) if isinstance(pos.get('entry_time'), datetime) else pos.get('entry_time')
        exit_t = int(pos['exit_time'].timestamp()*1000) if isinstance(pos.get('exit_time'), datetime) and pos.get('exit_time') else None
        
        # Helper to strict float
        def to_float(x):
            if x is None: return None
            return float(x)

        self.conn.execute(query, (
            pos['position_id'], pos.get('strategy_name', 'manual'), pos['symbol'],
            pos['side'], to_float(pos['quantity']), to_float(pos['entry_price']), to_float(pos.get('current_price')),
            to_float(pos.get('pnl', 0)), pos['status'], entry_t, exit_t, json.dumps(pos, cls=DecimalEncoder)
        ))
        self.conn.commit()

    def get_active_positions(self) -> List[Dict]:
        query = "SELECT * FROM positions WHERE status = 'open'"
        cursor = self.conn.execute(query)
        return [dict(row) for row in cursor.fetchall()]

    # --- Account Methods ---
    
    def update_account(self, balance, equity, pnl):
        ts = int(datetime.now().timestamp() * 1000)
        self.conn.execute("""
            INSERT OR REPLACE INTO account (account_id, balance, equity, pnl, updated_at)
            VALUES ('main', ?, ?, ?, ?)
        """, (balance, equity, pnl, ts))
        self.conn.commit()
        
    def get_account(self):
        cursor = self.conn.execute("SELECT * FROM account WHERE account_id = 'main'")
        row = cursor.fetchone()
        return dict(row) if row else None
