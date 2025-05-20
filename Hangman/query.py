import os
import options
import sqlite3
import pandas as pd
import mysql.connector

# Path to the SQLite database file (stored in the same directory as the script)
DB_PATH = os.path.join(os.path.dirname(__file__), "hangman.db")
if not os.path.exists(DB_PATH):
    with open(DB_PATH, "x"):  # create the new file
        pass


def get_db_connection() -> sqlite3.Connection | None:
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row  # Allows fetching rows as dictionaries
        return conn
    except sqlite3.Error as e:
        print("Error connecting to SQLite:", e, sep="\n")


async def get_backup_db_connection() -> (mysql.connector.pooling.PooledMySQLConnection |
                                         mysql.connector.connection.MySQLConnectionAbstract | None):
    try:
        print("Connecting to backup SQL server...")
        conn = mysql.connector.connect(
            host=os.environ.get("MYSQLHOST"),
            user=os.environ.get("MYSQLUSER"),
            password=os.environ.get("MYSQLPASSWORD"),
            database=os.environ.get("MYSQLDATABASE"),
            port=os.environ.get("MYSQLPORT")
        )
        print("Successfully connected!")
        return conn
    except mysql.connector.Error as e:
        print("Error connecting to backup MySQL server:", e, sep="\n")


def execute(statement: str, params: tuple = (), commit: bool = False, fetch: bool = True, fetch_one: bool = True):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(statement.strip(), params)
        if commit:
            conn.commit()
            return
        if fetch:
            return cursor.fetchone() if fetch_one else cursor.fetchall()


async def initialize_db(include_backup: bool = True):
    with get_db_connection() as conn:
        cursor = conn.cursor()
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
    if include_backup:
        await initialize_backup_db()


async def initialize_backup_db():
    backup_conn = await get_backup_db_connection()

    with backup_conn as conn:
        cursor = conn.cursor()
        # Create players table
        cursor.execute(f"""
            CREATE TABLE IF NOT EXISTS players (
                id INTEGER PRIMARY KEY AUTO_INCREMENT,
                discord_id INTEGER UNIQUE,
                points INTEGER DEFAULT 0,
                credits INTEGER DEFAULT {options.START_CREDITS}
            )
        """.strip())
        # Create games table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS games (
                id INTEGER PRIMARY KEY AUTO_INCREMENT,
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
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP(),
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


async def main_to_backup_etl():
    main_conn = get_db_connection()
    backup_conn = await get_backup_db_connection()

    # Extract main
    main_players = pd.read_sql_table("players", con=main_conn)
    main_games = pd.read_sql_table("games", con=main_conn)
    main_guild_members = pd.read_sql_table("guild_members", con=main_conn)

    # Extract backup
    backup_players = pd.read_sql_table("players", con=backup_conn)
    backup_games = pd.read_sql_table("games", con=backup_conn)
    backup_guild_members = pd.read_sql_table("guild_members", con=backup_conn)

    # Transform (merge databases)
    merge_players = pd.merge(main_players, backup_players, on="id", how="outer")
    merge_games = pd.merge(main_games, backup_games, on="id", how="outer")
    merge_guild_members = pd.merge(main_guild_members, backup_guild_members, on=main_guild_members.columns.names,
                                   how="outer")

    # Load
    merge_players.to_sql("players", con=backup_conn, if_exists="replace", index=False)
    merge_games.to_sql("games", con=backup_conn, if_exists="replace", index=False)
    merge_guild_members.to_sql("guild_members", con=backup_conn, if_exists="replace", index=False)


async def backup_to_main_etl():
    main_conn = get_db_connection()
    backup_conn = await get_backup_db_connection()

    # Extract backup
    backup_players = pd.read_sql_table("players", con=backup_conn)
    backup_games = pd.read_sql_table("games", con=backup_conn)
    backup_guild_members = pd.read_sql_table("guild_members", con=backup_conn)

    # Load to main tables
    backup_players.to_sql("players", con=main_conn, if_exists="replace", index=False)
    backup_games.to_sql("games", con=main_conn, if_exists="replace", index=False)
    backup_guild_members.to_sql("guild_members", con=main_conn, if_exists="replace", index=False)
