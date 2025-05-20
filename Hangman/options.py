import pytz
import datetime
from fractions import Fraction


PREFIX: str = "/"
ACTIVE_GAMES_UPDATE: int = 30  # minutes
NUM_LIVES: int = 5
NUM_GAMES_HISTORY: int = 5
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
TZ: pytz.timezone = pytz.timezone("America/New_York")
VOWELS: str = "AEIOU"
CONSONANTS: str = "BCDFGHJKLMNPQRSTVWXYZ"
MIN_LEADERBOARD_PLAYERS: int = 1
DEFAULT_NUM_TOP_PLAYERS: int = 10
LEADERBOARD_PERIODS: dict[str, int] = {"Today": 1,
                                       "This Week": 7,
                                       "This Month": 30,
                                       "All Time": 0}
DEFAULT_LEADERBOARD_PERIOD: str = "This Month"
VOWEL_COST: int = 100
CONSONANT_COST: int = 50
BUY_CREDITS: dict[int, float] = {1_000: 1.0,
                                 10_000: 5.0,
                                 50_000: 10.0}
LIVES_LEFT = {5: (0, 255, 0),      # 00FF00
              4: (144, 255, 144),  # FFFF00
              3: (255, 255, 0),    # FFAE42
              2: (255, 174, 66),   # FFA500
              1: (255, 128, 0)}    # FF8000


def make_ordinal(n: int) -> str:
    if 11 <= (n % 100) <= 13:
        suffix = 'th'
    else:
        suffix = ['th', 'st', 'nd', 'rd', 'th'][min(n % 10, 4)]
    return str(n) + suffix
