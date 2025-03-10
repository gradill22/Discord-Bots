import os
import mysql.connector
from mysql.connector import Error


def get_db_connection():
    try:
        print("Connecting to SQL server...")
        conn = mysql.connector.connect(
            host=os.environ.get("MYSQLHOST"),
            user=os.environ.get("MYSQLUSER"),
            password=os.environ.get("MYSQLPASSWORD"),
            database=os.environ.get("MYSQLDATABASE"),
            port=os.environ.get("MYSQLPORT")
        )
        print("Successfully connected!")
        return conn
    except Error as e:
        print("Error connecting to MySQL:", e, sep="\n")
        return None


def execute(statement: str, commit: bool = False, fetch: bool = True, fetch_one: bool = True):
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(statement)
            if commit:
                conn.commit()
            if fetch:
                return cursor.fetchone() if fetch_one else cursor.fetchall()
