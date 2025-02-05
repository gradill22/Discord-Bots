import math
import json
import string
import discord
import pandas as pd
from random_word import Wordnik
from datetime import datetime, timezone


class InputLetterGuess(discord.ui.Modal):
    def __init__(self, game, view: discord.ui.View):
        super().__init__(title="Guess a letter")
        self.game = game
        self.view = view
        self.user_input = discord.ui.TextInput(label="Letter", min_length=1, max_length=1)
        self.add_item(self.user_input)

    async def on_submit(self, interaction: discord.Interaction):
        content = self.game.push_guess(self.user_input.value)
        self.view = self.view if not self.game.is_done() else None
        if content:
            return await interaction.response.edit_message(content=content, view=self.view)
        return await interaction.response.defer(ephemeral=True)


class InputWordGuess(discord.ui.Modal):
    def __init__(self, game, view: discord.ui.View):
        super().__init__(title="Solve the puzzle")
        self.game = game
        self.word_length = len(self.game.word)
        self.view = view
        self.user_input = discord.ui.TextInput(label="Puzzle Solution", min_length=self.word_length,
                                               max_length=self.word_length,
                                               placeholder=f"{self.word_length} characters required...")
        self.add_item(self.user_input)

    async def on_submit(self, interaction: discord.Interaction):
        content = self.game.push_guess(self.user_input.value)
        self.view = self.view if not self.game.is_done() else None
        if content:
            return await interaction.response.edit_message(content=content, view=self.view)
        return await interaction.response.defer(ephemeral=True)


class HangmanButtonView(discord.ui.View):
    def __init__(self, game):
        super().__init__()
        self.game = game

    @discord.ui.button(label="Guess Letter", style=discord.ButtonStyle.primary)
    async def guess_letter(self, interaction: discord.Interaction, button: discord.Button):
        return await interaction.response.send_modal(InputLetterGuess(self.game, view=self))

    @discord.ui.button(label="Solve Puzzle", style=discord.ButtonStyle.primary)
    async def solve_puzzle(self, interaction: discord.Interaction, button: discord.Button):
        return await interaction.response.send_modal(InputWordGuess(self.game, view=self))

    @discord.ui.button(label="Quit", style=discord.ButtonStyle.danger)
    async def quit_game(self, interaction: discord.Interaction, button: discord.Button):
        self.game.quit_game()
        return await interaction.response.edit_message(content="You quit.", view=None, delete_after=5)


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

    def has_active_game(self) -> bool:
        return len(self.games) > 0 and not self.games[-1].is_done()  # is the most recent game still active?

    def points(self, days: int = 0) -> int:
        if days > 0:
            now = datetime.now(timezone.utc)
            return sum(game.points for game in self.games if (now - game.datetime).days <= days)

        return sum(game.points for game in self.games)

    def num_games_since_days(self, days: int):
        now = datetime.now(timezone.utc)
        return sum((now - game.datetime).days <= days for game in self.games)

    def last_n_games(self, n: int = 5) -> pd.DataFrame:
        n = min(n, len(self.games))
        df = pd.DataFrame(columns=["Word", "Result", "Points"])
        for game in self.games[-n::]:
            word = game.word.title()
            result = "Win" if game.is_win() else "Loss"
            points = game.points
            df.loc[len(df), :] = (word, result, points)

        return df


class Hangman:
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
        "WOTD": 1.5
    }
    VOWELS: str = "AEIOU"

    def __init__(self, player: Player, channel: discord.TextChannel, lives: int = 5):
        self.player = player
        self.channel = channel
        self.user = self.player.user
        self.word, self.definitions, self.is_wotd = self.get_word()
        self.guessed_letters = list()
        self.guessed_words = list()
        self.wrong_letters = list()
        self.lives = lives
        self.lives_emoji = ":heart:"
        self.missing_letter = ":x:"
        self.progress = " ".join([self.missing_letter if letter in string.ascii_uppercase else letter
                                  for letter in self.word])
        self.title = "**H_NGM_N**\n__WORD OF THE DAY__" if self.is_wotd else "**H_NGM_N**"
        self.points = 0
        self.datetime = datetime.now(timezone.utc)
        self.player.games.append(self)

    @staticmethod
    def process_word(word: str) -> str:
        return str(word).strip().upper()

    def get_word(self) -> tuple[str, list, bool]:
        wordnik = Wordnik()
        do_wotd = not self.player.has_done_wotd()
        if do_wotd:
            wotd = json.loads(wordnik.word_of_the_day())
            word = Hangman.process_word(wotd["word"])
            definitions = wotd["definitions"]
            return word, definitions, do_wotd
        word = Hangman.process_word(wordnik.get_random_word())
        return word, list(), do_wotd

    def is_done(self):
        return self.lives == 0 or self.word in self.guessed_words or self.missing_letter not in self.progress

    def format_definitions(self) -> str:
        def format_definition(definition: dict) -> str:
            return f"*{definition['partOfSpeech']}.* {definition['text']}"

        if len(self.definitions) == 0:
            return ""
        if len(self.definitions) == 1:
            return f"Definition:\n{format_definition(self.definitions[0])}"

        return "\n".join([f"Definitions:"] + [f"{i+1}) {format_definition(d)}" for i, d in enumerate(self.definitions)])

    def quit_game(self) -> None:
        self.player.games.remove(self)
        del self

    def start_game(self):
        content = [self.title + "\n", self.progress + "\n",
                   " ".join([self.lives_emoji] * self.lives),
                   "\nGuess a letter by replying to this message!"]
        content = "\n".join(content)
        view = HangmanButtonView(self)

        return content, view

    def update_progress(self, guess: str) -> str:
        if len(guess) == 1:
            is_vowel = guess in self.VOWELS if sum(self.word.count(v) for v in self.VOWELS) > 0 else guess == "Y"
            self.guessed_letters.append(guess)
            if guess not in self.word:
                self.wrong_letters.append(guess)
                self.points += self.POINTS["LETTER"]["VOWEL" if is_vowel else "CONSONANT"]["INCORRECT"]
                self.lives -= 1
                if self.lives == 0:
                    return self.lose()
            else:
                self.points += self.POINTS["LETTER"]["VOWEL" if is_vowel else "CONSONANT"]["CORRECT"] * self.word.count(guess)
            self.progress = " ".join([letter if letter in self.guessed_letters or letter not in string.ascii_uppercase
                                      else self.missing_letter for letter in self.word])
            if not self.progress.count(self.missing_letter):
                return self.win()
        else:
            self.guessed_words.append(guess)
            if guess == self.word:
                self.points += self.POINTS["WORD"]["CORRECT"]
                return self.win()
            self.points += self.POINTS["WORD"]["INCORRECT"]
            self.lives -= 1
            if self.lives == 0:
                return self.lose()

        content = [self.title + "\n", self.progress + "\n",
                   " ".join([self.lives_emoji] * self.lives),
                   f"Used letters: {', '.join(sorted(self.wrong_letters))}",
                   f"Used words: {', '.join(word.title() for word in sorted(self.guessed_words))}"]
        if len(self.wrong_letters) == 0:
            content.pop(-2)
        if len(self.guessed_words) == 0:
            content.pop(-1)

        return "\n".join(content)

    def win(self) -> str:
        self.points += self.POINTS["WIN"]
        self.points += self.POINTS["LIVES"] * self.lives
        self.points *= self.POINTS["WOTD"] if self.is_wotd else 1
        word = self.word.title()
        definitions = self.format_definitions()
        is_int = int(self.points) == float(self.points)
        content = (f"🎉 **You Won!** The word{' of the day' if self.is_wotd else ''} was **{word}**!\n\n"
                   f"You got **{self.points:.{'0' if is_int else '1'}f}** points!\n\n{definitions}")
        return content.strip()

    def lose(self):
        self.points += self.POINTS["LOSS"]
        self.points *= self.POINTS["WOTD"] if self.is_wotd else 1
        word = self.word.title()
        definitions = self.format_definitions()
        is_int = int(self.points) == float(self.points)
        content = (f"💀 **Game Over!** The word{' of the day' if self.is_wotd else ''} was **{word}.**\n\n"
                   f"You got **{self.points:.{'0' if is_int else '1'}f}** points.\n\n{definitions}")
        return content.strip()

    def push_guess(self, guess: str):
        guess = Hangman.process_word(guess)

        if len(guess) == 1 and guess in self.guessed_letters:
            return
        if guess in self.guessed_words:
            return

        return self.update_progress(guess)

    def is_win(self):
        return self.is_done() and self.lives > 0

    def __str__(self):
        return "\n".join([f"Player: {self.user.name}",
                          f"Server: {self.channel.guild.name}",
                          f"Channel: {self.channel.name}",
                          f"Word: {self.word.title()}",
                          f"Is Word of the Day: {self.is_wotd}",
                          f"Points: {self.points}",
                          f"UTC Datetime: {self.datetime}",
                          f"Is Done: {self.is_done()}"]
                         )
