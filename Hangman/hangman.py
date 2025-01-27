import math
import json
import string
import discord
from random_word import Wordnik
from datetime import datetime, timezone


class Player:
    def __init__(self, user: discord.User):
        self.user = user
        self.games: list[Hangman] = []

    def has_done_wotd(self) -> bool:
        wotd = json.loads(Wordnik().word_of_the_day())
        wotd = Hangman.process_word(wotd["word"])
        for game in self.games:
            if game.word == wotd and game.is_wotd:
                return True
        return False

    async def has_active_game(self) -> bool:
        return not await self.games[-1].is_done()  # is the most recent game still active?

    def points(self, days: int = 0) -> int:
        if days > 0:
            now = datetime.now(timezone.utc)
            return sum(game.points for game in self.games if (now - game.datetime).days <= days)

        return sum(game.points for game in self.games)

    def num_games_since_days(self, days: int):
        now = datetime.now(timezone.utc)
        return sum((now - game.datetime).days <= days for game in self.games)


class Hangman:
    POINTS: dict = {
        "LETTER": {"CORRECT": 10,
                   "INCORRECT": -5},
        "WORD": {"CORRECT": 50,
                 "INCORRECT": -10},
        "WIN": 100,
        "LOSS": -50,
        "LIVES": 50
    }

    def __init__(self, interaction: discord.Interaction, users: list[Player] | Player,
                 channel: discord.TextChannel = None, lives: int = 5):
        self.players: list[Player] = users
        self.n_players: int = len(self.players)
        self.channel = channel
        self.users = [player.user for player in self.players]
        self.mentions = " ".join(user.mention for user in self.users)
        self.word, self.definitions, self.is_wotd = self.get_word()
        self.guessed_letters = list()
        self.wrong_letters = list()
        self.guessed_words = list()
        self.lives = lives
        self.lives_emoji = ":heart:"
        self.missing_letter: str = ":regional_indicator_x:"
        self.progress = " ".join([self.missing_letter if letter in string.ascii_uppercase else letter
                                  for letter in self.word])
        self.game_message = interaction
        self.title = "**Hangman**"
        self.points = 0
        self.datetime = datetime.now(timezone.utc)

    @staticmethod
    def process_word(word) -> str:
        return str(word).strip().split()[0].upper()

    def set_users(self, users: list[Player] | Player):
        self.players = users if type(users) is list else [users]
        self.n_players = len(users)
        if self.n_players == 1 and self.channel is None:
            self.channel = self.players[0].user.dm_channel
        self.mentions = " ".join(player.user.mention for player in self.players)
        for player in self.players:
            player.games.append(self)
        self.users = [player.user for player in self.players]

    def get_word(self) -> tuple[str, list, bool]:
        wordnik = Wordnik()
        new_users = [user for user in self.players if not user.has_done_wotd()]
        do_wotd = len(new_users) > 0
        if do_wotd:
            self.set_users(new_users)
            wotd = json.loads(wordnik.word_of_the_day())
            word = Hangman.process_word(wotd["word"])
            definitions = wotd["definitions"]
            return word, definitions, do_wotd
        word = Hangman.process_word(wordnik.get_random_word())
        return word, list(), do_wotd

    async def is_done(self):
        try:
            await self.game_message.original_response()
        except discord.errors.NotFound:
            print("This message was probably deleted.")
            return True

        if self.lives == 0 or self.word in self.guessed_words:
            return True
        return self.missing_letter not in self.progress

    def format_definitions(self) -> str:
        def format_definition(definition: dict) -> str:
            return f"*{definition['partOfSpeech']}.* {definition['text']}"

        if len(self.definitions) == 0:
            return ""
        if len(self.definitions) == 1:
            return f"Definition:\n{format_definition(self.definitions[0])}"

        return "\n".join([f"Definitions:"] + [f"{i+1}) {format_definition(d)}" for i, d in enumerate(self.definitions)])

    async def start_game(self):
        content = [self.mentions, self.title + "\n", self.progress + "\n",
                   " ".join([self.lives_emoji] * self.lives),
                   "\nGuess a letter by replying to this message!"]

        return await self.game_message.edit_original_response(content="\n".join(content))

    async def update_progress(self, guess: str):
        if len(guess) == 1:
            self.guessed_letters.append(guess)
            if guess not in self.word:
                self.wrong_letters.append(guess)
                self.points += self.POINTS["LETTER"]["INCORRECT"]
                self.lives -= 1
                if self.lives == 0:
                    return await self.lose()
            else:
                self.points += self.POINTS["LETTER"]["CORRECT"] * self.word.count(guess)
            self.progress = " ".join([letter if letter in self.guessed_letters or letter not in string.ascii_uppercase
                                      else self.missing_letter for letter in self.word])
            if not self.progress.count(self.missing_letter):
                return await self.win()
        else:
            self.guessed_words.append(guess)
            if guess == self.word:
                self.points += self.POINTS["WORD"]["CORRECT"]
                return await self.win()
            self.points += self.POINTS["WORD"]["INCORRECT"]
            self.lives -= 1
            if self.lives == 0:
                return await self.lose()

        content = [self.mentions, self.title + "\n", self.progress + "\n",
                   " ".join([self.lives_emoji] * self.lives),
                   f"Score: {self.points:,}",
                   f"Used letters: {', '.join(sorted(self.wrong_letters))}",
                   f"Used words: {', '.join(word.title() for word in sorted(self.guessed_words))}",
                   "\nGuess a letter by replying to this message!"]
        if len(self.wrong_letters) == 0:
            content.pop(-3)
        if len(self.guessed_words) == 0:
            content.pop(-2)

        return await self.game_message.edit_original_response(content="\n".join(content))

    async def win(self):
        self.points += self.POINTS["WIN"]
        self.points += self.POINTS["LIVES"] * self.lives
        word = self.word.title()
        definitions = self.format_definitions()
        content = (f"{self.mentions}\n🎉 **You Won!** The word was **{word}**!\n\n"
                   f"You won **{self.points}** points!\n\n{definitions}")
        return await self.game_message.edit_original_response(content=content)

    async def lose(self):
        self.points += self.POINTS["LOSS"]
        self.points += self.POINTS["LIVES"] * self.lives
        word = self.word.title()
        definitions = self.format_definitions()
        content = (f"{self.mentions}\n💀 **Game Over!** The word was **{word}.**\n\n"
                   f"You got **{self.points}** points.\n\n{definitions}")
        return await self.game_message.edit_original_response(content=content)

    async def push_guess(self, message: discord.Message):
        channel = message.channel
        if self.channel != channel:
            return await message.reply(f"Excuse me, do you know where **#{channel.name}** is? I seem to be lost...")

        user = message.author
        if user not in self.users:
            response = await message.reply(f"**Start your own damn game, {user.mention}!**\n\nYou can do so by doing "
                                           f"`/hangman` in one of your server's text channels!")
            return await response.delete(delay=10)

        guess = Hangman.process_word(message.content)
        await message.delete()

        if len(guess) != 1 or len(guess) != len(self.word):
            return
        if len(guess) == 1 and guess in self.guessed_letters:
            return
        if guess in self.guessed_words:
            return

        return await self.update_progress(guess)

    async def is_game(self, message: discord.Message) -> bool:
        return message.author in self.users and message.channel == self.channel and not (await self.is_done())

    def __str__(self):
        return "\n".join([f"Player(s): {', '.join(user.name for user in self.users)}",
                          f"Server: {self.channel.guild.name}",
                          f"Channel: {self.channel.name}",
                          f"Word: {self.word.title()}",
                          f"Is Word of the Day: {self.is_wotd}",
                          f"Points: {self.points}",
                          f"UTC Datetime: {self.datetime}"]
                         )


def leaderboard_string(players: list[Player], num_players: int = 10, n_days: int = 0) -> str:
    players = [player for player in players if player.num_games_since_days(n_days) > 0]
    players = sorted(players, key=lambda p: p.points(n_days), reverse=True)[:max(num_players, len(players))]
    m = math.floor(math.log10(len(players))) + 1
    s = "\n".join([" - ".join((f"{i+1:{m}d}", player.user.mention, player.points))
                   for i, player in enumerate(players)])
    return s
