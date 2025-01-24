import json
import string
import discord
from random_word import Wordnik


class Player:
    def __init__(self, user: discord.User):
        self.user = user
        self.wordnik = Wordnik()
        self.games: list[Hangman] = []

    def has_done_wotd(self) -> bool:
        wotd = json.loads(self.wordnik.word_of_the_day())
        wotd = wotd["word"]
        for game in self.games:
            if game.is_wotd and game.word == wotd:
                return True
        return False

    def __eq__(self, other: discord.User):
        if type(other) is Player:
            return self.user.id == other.user.id
        return self.user.id == other.id


class Hangman:
    def __init__(self, interaction: discord.Interaction, users: list[Player] | Player,
                 channel: discord.TextChannel = None, lives: int = 5):
        self.players: list[Player] = list()
        self.n_players: int = -1
        self.channel = channel
        self.mentions = ""
        self.set_users(users)
        self.word, self.definitions, self.is_wotd = self.get_word()
        self.guessed_letters = list()
        self.wrong_letters = list()
        self.guessed_words = list()
        self.lives = lives
        self.lives_emoji = ":heart:"
        self.progress = " ".join([self.lives_emoji] * self.lives)
        self.game_message = interaction
        self.title = "**Hangman**"
        self.missing_letter: str = ":regional_indicator_x:"

    def set_users(self, users: list[Player] | Player):
        self.players = users if type(users) is list else [users]
        self.n_players = len(users)
        if self.n_players == 1 and self.channel is None:
            self.channel = self.players[0].user.dm_channel
        self.mentions = "".join(player.user.mention for player in self.players)
        for player in self.players:
            player.games.append(self)

    def get_word(self) -> tuple[str, list, bool]:
        wordnik = Wordnik()
        new_users = [user for user in self.players if not user.has_done_wotd()]
        do_wotd = len(new_users) > 0
        self.set_users(new_users)
        if do_wotd:
            wotd = json.loads(wordnik.word_of_the_day())
            word = str(wotd["word"]).strip().upper()
            definitions = wotd["definitions"]
            return word, definitions, do_wotd
        return wordnik.get_random_word(), list(), do_wotd

    def is_done(self):
        if self.lives == 0 or self.word in self.guessed_words:
            return True
        word = self.word
        for letter in self.guessed_letters:
            word = word.replace(letter, "")
        return len(word) == 0

    def format_definitions(self) -> str:
        def format_definition(definition: dict) -> str:
            return f"*{definition['partOfSpeech']}.* {definition['text']}"

        if len(self.definitions) == 0:
            return ""
        if len(self.definitions) == 1:
            return f"Definition:\n{format_definition(self.definitions[0])}"

        return "\n".join([f"Definitions:"] + [f"{i+1}) {format_definition(d)}" for i, d in enumerate(self.definitions)])

    async def update_progress(self, guess: str):
        if len(guess) == 1:
            self.guessed_letters.append(guess)
            if guess not in self.word:
                self.wrong_letters.append(guess)
        else:
            self.guessed_words.append(guess)

        if self.is_done():
            return await self.win()
        else:
            self.lives -= 1
            if self.is_done():
                return await self.lose()

        self.progress = " ".join([letter if letter in self.guessed_letters or letter not in string.ascii_uppercase
                                  else self.missing_letter for letter in self.word])

        content = [self.mentions, self.title + "\n", self.progress + "\n",
                   " ".join([self.lives_emoji] * self.lives),
                   f"Used letters: {', '.join(sorted(self.wrong_letters))}",
                   f"Used words: {', '.join(sorted(self.guessed_words))}",
                   "\nGuess a letter by replying to this message!"]
        if len(self.wrong_letters) == 0:
            content.pop(-3)
        if len(self.guessed_words) == 0:
            content.pop(-2)

        return self.game_message.edit_original_response(content="\n".join(content))

    async def win(self):
        word = self.word.title()
        definitions = self.format_definitions()
        content = f"{self.mentions}\n🎉 **You Won!** The word was **{word}**!\n\n{definitions}"
        return await self.game_message.edit_original_response(content=content)

    async def lose(self):
        word = self.word.title()
        definitions = self.format_definitions()
        content = f"{self.mentions}\n💀 **Game Over!** The word was **{word}.**\n\n{definitions}"
        return await self.game_message.edit_original_response(content=content)

    async def push_guess(self, message: discord.Message):
        if self.is_done():
            return await message.delete()

        channel = message.channel
        user = message.author

        if self.channel != channel:
            return await message.reply(f"Excuse me, do you know where **#{channel.name}** is? I seem to be lost...")

        if user not in self.players:
            response = await message.reply(f"**Start your own damn game, {user.mention}!**\n\nYou can do so by doing "
                                           f"**`/hangman`** in one of your server's text channels or in a private DM!")
            return await response.delete(delay=10)

        guess = message.content.strip().upper()
        await message.delete()

        if len(guess) == 1 and guess in self.guessed_letters:
            return
        if guess in self.guessed_words:
            return

        return await self.update_progress(guess)

    def is_game(self, message: discord.Message) -> bool:
        return self.game_message.id == message.id
