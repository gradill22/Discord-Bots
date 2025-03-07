import os
import mysql
from mysql.connector import Error
from fractions import Fraction

ACTIVE_GAMES_UPDATE: int = 30  # minutes
NUM_LIVES: int = 5
LIVES_EMOJI: str = ":heart:"
MISSING_LETTER_EMOJI: str = ":x:"
CREDIT_EMOJI: str = ":coin:"
START_CREDITS: int = 500
POINTS_TO_CREDITS: Fraction = Fraction(1.0)
POINTS: dict = {
    "LETTER": {"VOWEL": {"CORRECT": 5,
                         "INCORRECT": -5},
               "CONSONANT": {"CORRECT": 10,
                             "INCORRECT": -5}},
    "WORD": {"CORRECT": 50,
             "INCORRECT": -10},
    "WIN": 100,
    "LOSS": -50,
    "LIVES": 50,
    "WOTD": 2
}
VOWELS: str = "AEIOU"
CONSONANTS: str = "BCDFGHJKLMNPQRSTVWXYZ"
MIN_LEADERBOARD_PLAYERS: int = 1
DEFAULT_NUM_TOP_PLAYERS: int = 10
LEADERBOARD_PERIODS: dict[str, int] = {"Today": 1,
                                       "This Week": 7,
                                       "This Month": 30,
                                       "All Time": 0}
DEFAULT_LEADERBOARD_PERIOD: str = "This Week"
LEADERBOARD_PLACES: dict[int, str] = {1: ":first_place:",
                                      2: ":second_place:",
                                      3: ":third_place:",
                                      4: ":four:",
                                      5: ":five:",
                                      6: ":six:",
                                      7: ":seven:",
                                      8: ":eight:",
                                      9: ":nine:",
                                      10: ":keycap_ten:"}
VOWEL_COST: int = 100
CONSONENT_COST: int = 50
BUY_CREDITS: dict[int, float] = {1_000: 1.0,
                                 10_000: 5.0,
                                 50_000: 10.0}


def get_db_connection():
    try:
        return mysql.connector.connect(
            host=os.environ.get("MYSQLHOST"),
            user=os.environ.get("MYSQLUSER"),
            password=os.environ.get("MYSQLPASSWORD"),
            database=os.environ.get("MYSQLDATABASE"),
            port=os.environ.get("MYSQLPORT")
        )
    except Error as e:
        print(f"Error connecting to MySQL: {e}")
        return None
