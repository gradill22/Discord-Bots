import os
import options
import sqlite3

# Path to the SQLite database file (stored in the same directory as the script)
DB_PATH = os.path.join(os.path.dirname(__file__), "hangman.db")


def get_db_connection():
    try:
        print("Connecting to SQLite database...")
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row  # Allows fetching rows as dictionaries
        print(f"Successfully connected!")
        return conn
    except sqlite3.Error as e:
        print("Error connecting to SQLite:", e, sep="\n")
        return None


def execute(statement: str, params: tuple = (), commit: bool = False, fetch: bool = True, fetch_one: bool = True):
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(statement, params)
            if commit:
                conn.commit()
            if fetch:
                return cursor.fetchone() if fetch_one else cursor.fetchall()


async def initialize_db():
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            # Create players table
            cursor.execute(f"""
                CREATE TABLE IF NOT EXISTS players (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    discord_id INTEGER UNIQUE,
                    points INTEGER DEFAULT 0,
                    credits INTEGER DEFAULT {options.START_CREDITS}
                )
            """.strip())
            # Create games table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS games (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    player_id INTEGER,
                    channel_id INTEGER,
                    word TEXT,
                    is_wotd INTEGER,
                    lives INTEGER,
                    progress TEXT,
                    guessed_letters TEXT,
                    guessed_words TEXT,
                    wrong_letters TEXT,
                    definitions TEXT,
                    points INTEGER DEFAULT 0,
                    is_done INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (player_id) REFERENCES players(id)
                )
            """.strip())
            # Create guild_members table (for leaderboard)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS guild_members (
                    guild_id INTEGER,
                    user_id INTEGER,
                    PRIMARY KEY (guild_id, user_id)
                )
            """.strip())
            conn.commit()
