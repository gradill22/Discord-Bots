import json
import query
import string
import discord
import options
import pandas as pd
from random_word import Wordnik


class InputLetterGuess(discord.ui.Modal):
    def __init__(self, game, view: discord.ui.View):
        super().__init__(title="Guess a letter")
        self.game = game
        self.view = view
        self.user_input = discord.ui.TextInput(label="Letter", min_length=1, max_length=1)
        self.add_item(self.user_input)

    async def on_submit(self, interaction: discord.Interaction):
        image, embed = self.game.push_guess(self.user_input.value)
        self.view = self.view if not self.game.is_done else None
        if embed:
            return await interaction.response.edit_message(attachments=[image], embed=embed, view=self.view)
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
        image, embed = self.game.push_guess(self.user_input.value)
        self.view = self.view if not self.game.is_done else None
        if embed:
            return await interaction.response.edit_message(attachments=[image], embed=embed, view=self.view)
        return await interaction.response.defer(ephemeral=True)


class HangmanButtonView(discord.ui.View):
    def __init__(self, game):
        super().__init__()
        self.game = game

    @discord.ui.button(label="Guess Letter", style=discord.ButtonStyle.primary, row=1)
    async def guess_letter(self, interaction: discord.Interaction, button: discord.Button):
        if interaction.user == self.game.user:
            return await interaction.response.send_modal(InputLetterGuess(self.game, view=self))
        return await interaction.response.send_message(content=f"Play your own game by using `/hangman`",
                                                       delete_after=10, ephemeral=True)

    @discord.ui.button(label="Solve Puzzle", style=discord.ButtonStyle.primary, row=1)
    async def solve_puzzle(self, interaction: discord.Interaction, button: discord.Button):
        if interaction.user == self.game.user:
            return await interaction.response.send_modal(InputWordGuess(self.game, view=self))
        return await interaction.response.send_message(content=f"Play your own game by using `/hangman`",
                                                       delete_after=10, ephemeral=True)

    @discord.ui.button(label=f"Buy Vowel", row=2, style=discord.ButtonStyle.green, custom_id="vowel_button")
    async def buy_vowel(self, interaction: discord.Interaction, button: discord.Button):
        if interaction.user == self.game.user:
            image, embed, is_active = self.game.buy_vowel()
            button.disabled = not is_active
            view = None if self.game.is_done else self
            if self.game.player.credits <= options.VOWEL_COST or self.game.vowels_left() == 0:
                self.children[3].disabled = True
            if is_active:
                return await interaction.response.edit_message(attachments=[image], embed=embed, view=view)
        return await interaction.response.send_message(content=f"Play your own game by using `/hangman`",
                                                       delete_after=10, ephemeral=True)

    @discord.ui.button(label=f"Buy Consonant", row=2, style=discord.ButtonStyle.green, custom_id="consonant_button")
    async def buy_consonant(self, interaction: discord.Interaction, button: discord.Button):
        if interaction.user == self.game.user:
            image, embed, is_active = self.game.buy_consonant()
            button.disabled = not is_active
            view = None if self.game.is_done else self
            if self.game.player.credits <= options.CONSONANT_COST:
                self.children[2].disabled = True
            if is_active:
                return await interaction.response.edit_message(attachments=[image], embed=embed, view=view)
        return await interaction.response.send_message(content=f"Play your own game by using `/hangman`",
                                                       delete_after=10, ephemeral=True)

    @discord.ui.button(label="Quit", style=discord.ButtonStyle.danger, row=3)
    async def quit_game(self, interaction: discord.Interaction, button: discord.Button):
        if interaction.user != self.game.user:
            return await interaction.response.send_message(content=f"Play your own game by using `/hangman`",
                                                           delete_after=10, ephemeral=True)
        self.game.quit_game()
        return await interaction.response.edit_message(content="You quit.", attachments=[], embed=None, view=None,
                                                       delete_after=5)


class Player:
    def __init__(self, interaction: discord.Interaction):
        self.user = interaction.user
        self.discord_id = self.user.id
        self._load_or_create_player()

    def _load_or_create_player(self):
        result = query.execute("SELECT id, points, credits FROM players WHERE discord_id = ?",
                               (self.discord_id,), fetch=True)
        if result:
            self.id, self.points, self.credits = result
            return

        with query.get_db_connection() as conn:
            cursor = conn.cursor()
            self.points = 0
            self.credits = options.START_CREDITS
            cursor.execute(
                "INSERT INTO players (discord_id, points, credits) VALUES (?, ?, ?)",
                (self.discord_id, self.points, self.credits)
            )
            self.id = cursor.lastrowid
            mutual_guilds = self.user.mutual_guilds
            for guild in mutual_guilds:
                cursor.execute("INSERT INTO guild_members (guild_id, user_id) VALUES (?, ?)",
                               (guild.id, self.id))
            conn.commit()

    def has_done_wotd(self) -> bool:
        wotd = json.loads(Wordnik().word_of_the_day())["word"]
        wotd = self.process_word(wotd)
        result = query.execute("SELECT COUNT(*) FROM games WHERE player_id = ? AND word = ? AND is_wotd = 1",
                               (self.id, wotd), fetch=True)
        return result[0] if result else False

    def has_active_game(self) -> bool:
        result = query.execute("SELECT COUNT(*) FROM games WHERE player_id = ? AND is_done = 0",
                               (self.id,), fetch=True)
        return result[0] > 0 if result else False

    def points(self, days: int = 0) -> float:
        if days > 0:
            result = query.execute(
                "SELECT SUM(points) FROM games WHERE player_id = ? AND created_at >= datetime('now', ?)",
                (self.id, f"-{days} days"), fetch=True)
        else:
            result = query.execute("SELECT points FROM players WHERE id = ?", (self.id,), fetch=True)
        return result[0] if result else 0

    def record(self, days: int = 0) -> tuple[int, int]:
        self._load_or_create_player()
        if days > 0:
            results = query.execute(
                "SELECT lives FROM games WHERE player_id = ? AND is_done = 1 AND "
                "created_at >= datetime('now', ?)",
                (self.id, days), fetch_one=False
            )
        else:
            results = query.execute("SELECT lives FROM games WHERE player_id = ? AND is_done = 1",
                                    (self.id,), fetch_one=False)
        wins = sum(result[0] > 0 for result in results)
        losses = len(results) - wins
        return wins, losses

    def num_games_since_days(self, days: int) -> int:
        result = query.execute("SELECT COUNT(*) FROM games WHERE player_id = ? AND created_at >= datetime('now', ?)",
                               (self.id, f"-{days} days"), fetch=True)
        return result[0] if result else 0

    def num_games(self) -> int:
        result = query.execute("SELECT COUNT(*) FROM games WHERE player_id = ?", (self.id,), fetch=True)
        return result[0] if result else 0

    def last_n_games(self, n: int = 5) -> pd.DataFrame:
        games = query.execute(
            "SELECT word, is_done, lives, points FROM games WHERE player_id = ? ORDER BY created_at DESC LIMIT ?",
            (self.id, n), fetch=True, fetch_one=False)
        if games:
            df = pd.DataFrame(columns=["Word", "Result", "Points"])
            for i, (word, is_done, lives, points) in enumerate(games):
                result = "Win" if is_done and lives > 0 else "Loss"
                df.loc[i] = (word.title(), result, points)
            return df
        return pd.DataFrame(columns=["Word", "Result", "Points"])

    @staticmethod
    def process_word(word: str) -> str:
        return str(word).strip().upper()


class Hangman:
    def __init__(self, player: Player, channel: discord.TextChannel, id_: int = None):
        self.player = player
        self.channel = channel
        self.user = player.user

        if id_:
            self.id = id_
            self._load_game_state()
        else:
            self.word, self.definitions, self.is_wotd = self.get_word()
            self.progress = " ".join([options.MISSING_LETTER_EMOJI if letter in string.ascii_uppercase
                                      else "\n" if letter == " " else letter for letter in self.word])
            self.lives = options.NUM_LIVES
            self.points = 0
            self.is_done = False
            self._save_new_game()

        self.view = HangmanButtonView(self)

    def _save_new_game(self):
        self.guessed_letters = []
        self.guessed_words = []
        self.wrong_letters = []

        with query.get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO games (player_id, channel_id, word, is_wotd, lives, progress, guessed_letters, guessed_words, wrong_letters, definitions) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (self.player.id, self.channel.id, self.word, int(self.is_wotd), self.lives, self.progress,
                 json.dumps(self.guessed_letters), json.dumps(self.guessed_words), json.dumps(self.wrong_letters),
                 json.dumps(self.definitions))
            )
            conn.commit()
            self.id = cursor.lastrowid

    def _load_game_state(self):
        result = query.execute(
            "SELECT word, lives, is_done, progress, guessed_letters, guessed_words, wrong_letters, definitions, "
            "points, is_wotd FROM games WHERE id = ?", (self.id,), fetch=True)
        if result:
            (self.word, self.lives, self.is_done, self.progress, guessed_letters,
             guessed_words, wrong_letters, definitions, self.points, self.is_wotd) = result
            self.guessed_letters = json.loads(guessed_letters)
            self.guessed_words = json.loads(guessed_words)
            self.wrong_letters = json.loads(wrong_letters)
            self.definitions = json.loads(definitions)
            return

        print("Failed to load game state...")

    def _update_game_state(self):
        query.execute(
            "UPDATE games SET lives = ?, is_done = ?, progress = ?, guessed_letters = ?, guessed_words = ?, wrong_letters = ?, points = ? WHERE id = ?",
            (self.lives, int(self.is_done), self.progress, json.dumps(self.guessed_letters),
             json.dumps(self.guessed_words), json.dumps(self.wrong_letters), self.points, self.id),
            commit=True
        )

    def get_word(self) -> tuple[str, list, bool]:
        wordnik = Wordnik()
        do_wotd = not self.player.has_done_wotd()
        if do_wotd:
            wotd = json.loads(wordnik.word_of_the_day())
            word = self.player.process_word(wotd["word"])
            definitions = wotd["definitions"]
            return word, definitions, do_wotd
        word = self.player.process_word(wordnik.get_random_word())
        return word, list(), do_wotd

    def vowels_left(self) -> int:
        num_vowels = sum(vowel in self.word for vowel in options.VOWELS)
        if num_vowels == 0:
            return "Y" not in self.progress
        num_vowels -= sum(letter in options.VOWELS for letter in self.guessed_letters)
        return num_vowels

    def buy_vowel(self) -> tuple[discord.File | None, discord.Embed | None, bool]:
        if self.vowels_left() == 0:
            image, embed, view = self.current_progress()
            return image, embed, False
        self.player.credits -= options.VOWEL_COST
        query.execute("UPDATE players SET credits = ? WHERE id = ?", (self.player.credits, self.player.id), commit=True)

        temp = "@"
        progress = self.progress.replace(options.MISSING_LETTER_EMOJI, temp)
        for i, letter in enumerate(progress.split()):
            if letter == temp and self.word[i] in options.VOWELS:
                image, embed = self.update_progress(self.word[i], options.POINTS["LETTER"]["VOWEL"]["CORRECT"])
                return image, embed, self.vowels_left() > 0 and self.player.credits >= options.VOWEL_COST
        return None, None, False

    def consonants_left(self) -> int:
        num_consonants = sum(c in options.CONSONANTS for c in set(self.word) if c not in self.progress)
        num_vowels = self.vowels_left()
        return num_consonants - int(num_vowels == 0)

    def buy_consonant(self) -> tuple[discord.File | None, discord.Embed | None, bool]:
        if self.consonants_left() == 0:
            image, embed, view = self.current_progress()
            return image, embed, False
        self.player.credits -= options.CONSONANT_COST
        query.execute("UPDATE players SET credits = ? WHERE id = ?", (self.player.credits, self.player.id), commit=True)

        temp = "@"
        progress = self.progress.replace(options.MISSING_LETTER_EMOJI, temp)
        for i, letter in enumerate(progress.split()):
            if letter == temp and self.word[i] in options.CONSONANTS:
                image, embed = self.update_progress(self.word[i], options.POINTS["LETTER"]["CONSONANT"]["CORRECT"])
                return image, embed, self.consonants_left() > 0 and self.player.credits >= options.CONSONANT_COST
        return None, None, False

    def format_definitions(self) -> str:
        def format_definition(definition: dict) -> str:
            return f"*{definition['partOfSpeech']}.* {definition['text']}"

        if len(self.definitions) == 0:
            return ""
        if len(self.definitions) == 1:
            return f"Definition:\n{format_definition(self.definitions[0])}"
        return "\n".join(
            [f"Definitions:"] + [f"{i + 1}) {format_definition(d)}" for i, d in enumerate(self.definitions)])

    def quit_game(self) -> None:
        # remove points from player profile
        query.execute("UPDATE players SET points = points - ? WHERE id = ?", params=(self.points, self.player.id),
                      commit=True)
        query.execute("DELETE FROM games WHERE id = ?", (self.id,), commit=True)
        del self

    def start_game(self) -> tuple[discord.File, discord.Embed, discord.ui.View]:
        title = "H_NGM_N\n__WORD OF THE DAY__" if self.is_wotd else "H_NGM_N"
        content = f"{self.progress}\n\n{' '.join([options.LIVES_EMOJI] * self.lives)}"
        image = discord.File(fp=f"assets/hangman_{self.lives}.jpg", filename="image.jpg")
        embed = discord.Embed(title=title, description=content.strip(),
                              color=discord.Color.from_rgb(*options.LIVES_LEFT[self.lives]))
        embed.set_image(url="attachment://image.jpg")
        return image, embed, self.view

    def update_progress(self, guess: str, price: int = 0) -> tuple[discord.File, discord.Embed]:
        if len(guess) == 1:
            is_vowel = guess in options.VOWELS if sum(self.word.count(v) for v in options.VOWELS) else guess == "Y"
            self.guessed_letters.append(guess)
            if guess not in self.word:
                self.wrong_letters.append(guess)
                if price == 0:
                    self.points += options.POINTS["LETTER"]["VOWEL" if is_vowel else "CONSONANT"]["INCORRECT"]
                self.lives -= 1
                if self.lives == 0:
                    return self.lose(price)
            elif price == 0:
                self.points += options.POINTS["LETTER"]["VOWEL" if is_vowel else "CONSONANT"][
                                   "CORRECT"] * self.word.count(guess)
            self.progress = " ".join(["\n" if letter == " " else options.MISSING_LETTER_EMOJI
                                      if letter not in self.guessed_letters and letter in string.ascii_uppercase
                                      else letter for letter in self.word])
            if self.progress.count(options.MISSING_LETTER_EMOJI) == 0:
                return self.win(price)
        else:
            self.guessed_words.append(guess)
            if guess == self.word:
                self.points += options.POINTS["WORD"]["CORRECT"]
                return self.win(price)
            self.points += options.POINTS["WORD"]["INCORRECT"]
            self.lives -= 1
            if self.lives == 0:
                return self.lose(price)

        content = [
            self.progress + "\n",
            " ".join([options.LIVES_EMOJI] * self.lives),
            f"Used letters: {', '.join(sorted(self.wrong_letters))}",
            f"Used words: {', '.join(word.title() for word in sorted(self.guessed_words))}"
        ]
        if len(self.wrong_letters) == 0:
            content.pop(-2)
        if len(self.guessed_words) == 0:
            content.pop(-1)
        if price > 0:
            content.append(f"You have {self.player.credits} {options.CREDIT_EMOJI} remaining!")

        embed = discord.Embed(title="H_NGM_N\n__WORD OF THE DAY__" if self.is_wotd else "H_NGM_N",
                              description="\n".join(content),
                              color=discord.Color.from_rgb(*options.LIVES_LEFT[self.lives]))
        image = discord.File(fp=f"assets/hangman_{self.lives}.jpg", filename="image.jpg")
        embed.set_image(url="attachment://image.jpg")

        self._update_game_state()
        return image, embed

    def win(self, price: int = 0) -> tuple[discord.File, discord.Embed]:
        word = self.word.title()
        definitions = self.format_definitions()

        self.is_done = True
        self.points += options.POINTS["WIN"]
        self.points += options.POINTS["LIVES"] * self.lives
        self.points *= options.POINTS["WOTD"] if self.is_wotd else 1
        self.player.points += self.points

        query.execute("UPDATE players SET points = points + ? WHERE id = ?",
                      (self.points, self.player.id), commit=True)

        is_int = int(self.points) == float(self.points)
        content = (f"🎉 **You Won!** The word{' of the day' if self.is_wotd else ''} was **{word}**!\n\n"
                   f"You got **{self.points:.{'0' if is_int else '1'}f}** points!\n\n{definitions}")
        if price > 0:
            content += f"\n\nYou have {self.player.credits} {options.CREDIT_EMOJI} remaining!"

        image = discord.File(fp=f"assets/hangman_{self.lives}_win.jpg", filename="win.jpg")
        embed = discord.Embed(title="💀 Game Over!", description=content.strip(), color=discord.Color.green())
        embed.set_image(url="attachment://win.jpg")

        self._update_game_state()
        return image, embed

    def lose(self, price: int = 0) -> tuple[discord.File, discord.Embed]:
        word = self.word.title()
        definitions = self.format_definitions()

        self.lives = 0
        self.is_done = True
        self.points += options.POINTS["LOSS"]
        self.points *= options.POINTS["WOTD"] if self.is_wotd else 1
        self.player.points += self.points

        query.execute("UPDATE players SET points = points + ? WHERE id = ?", (self.points, self.player.id), commit=True)

        is_int = int(self.points) == float(self.points)
        content = (f"The word{' of the day' if self.is_wotd else ''} was **{word}.**\n\n"
                   f"You got **{self.points:.{'0' if is_int else '1'}f}** points.\n\n{definitions}")
        if price > 0:
            content += f"\n\nYou have {self.player.credits} {options.CREDIT_EMOJI} remaining."

        image = discord.File(fp="assets/hangman_0.jpg", filename="lose.jpg")
        embed = discord.Embed(title="💀 Game Over!", description=content.strip(), color=discord.Color.red())
        embed.set_image(url="attachment://lose.jpg")

        self._update_game_state()
        return image, embed

    def push_guess(self, guess: str):
        guess = self.player.process_word(guess)
        if len(guess) == 1 and guess in self.guessed_letters:
            return
        if guess in self.guessed_words:
            return
        return self.update_progress(guess)

    def current_progress(self) -> tuple[discord.File, discord.Embed, discord.ui.View | None]:
        if self.is_win():
            image, embed = self.win(self.points)
            return image, embed, None
        if self.lives == 0:
            image, embed = self.win(self.points)
            return image, embed, None

        content = [
            self.progress + "\n",
            " ".join([options.LIVES_EMOJI] * self.lives),
            f"Used letters: {', '.join(sorted(self.wrong_letters))}",
            f"Used words: {', '.join(word.title() for word in sorted(self.guessed_words))}"
        ]
        if len(self.wrong_letters) == 0:
            content.pop(-2)
        if len(self.guessed_words) == 0:
            content.pop(-1)

        embed = discord.Embed(title="H_NGM_N\n__WORD OF THE DAY__" if self.is_wotd else "H_NGM_N",
                              description="\n".join(content),
                              color=discord.Color.from_rgb(*options.LIVES_LEFT[self.lives]))
        image = discord.File(fp=f"assets/hangman_{self.lives}{'_win' if self.is_win() else ''}.jpg",
                             filename="image.jpg")
        embed.set_image(url="attachment://image.jpg")

        return image, embed, self.view

    def is_win(self):
        return self.is_done and self.lives > 0

    def __str__(self):
        return "\n".join([
            f"Player: {self.user.name}",
            f"Server: {self.channel.guild.name}",
            f"Channel: {self.channel.name}",
            f"Word: {self.word.title()}",
            f"Is Word of the Day: {self.is_wotd}",
            f"Points: {self.points}",
            f"Is Done: {self.is_done}"
        ])
