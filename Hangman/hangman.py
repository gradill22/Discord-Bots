import json
import string
import discord
from random_word import Wordnik


def process_word(word) -> str:
    return str(word).strip().upper()


class Player:
    def __init__(self, user: discord.User):
        self.user = user
        self.games: list[Hangman] = []

    def has_done_wotd(self) -> bool:
        wotd = json.loads(Wordnik().word_of_the_day())
        wotd = process_word(wotd["word"])
        for game in self.games:
            if game.word == wotd and game.is_wotd:
                return True
        return False


class Hangman:
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
            word = process_word(wotd["word"])
            definitions = wotd["definitions"]
            return word, definitions, do_wotd
        word = process_word(wordnik.get_random_word())
        return word, list(), do_wotd

    def is_done(self):
        if self.lives == 0 or self.word in self.guessed_words:
            return True
        return self.missing_letter in self.progress

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
        wrong_guess = False
        if len(guess) == 1:
            self.guessed_letters.append(guess)
            if guess not in self.word:
                self.wrong_letters.append(guess)
                wrong_guess = True
            self.progress = " ".join([letter if letter in self.guessed_letters or letter not in string.ascii_uppercase
                                      else self.missing_letter for letter in self.word])
        else:
            self.guessed_words.append(guess)

        if self.is_done():
            return await self.win()
        else:
            self.lives -= int(wrong_guess)
            if self.is_done():
                return await self.lose()

        content = [self.mentions, self.title + "\n", self.progress + "\n",
                   " ".join([self.lives_emoji] * self.lives),
                   f"Used letters: {', '.join(sorted(self.wrong_letters))}",
                   f"Used words: {', '.join(word.title() for word in sorted(self.guessed_words))}",
                   "\nGuess a letter by replying to this message!"]
        if len(self.wrong_letters) == 0:
            content.pop(-3)
        if len(self.guessed_words) == 0:
            content.pop(-2)

        return await self.game_message.edit_original_response(content="\n".join(content))

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
        channel = message.channel
        user = message.author

        if self.channel != channel:
            return await message.reply(f"Excuse me, do you know where **#{channel.name}** is? I seem to be lost...")

        if user not in self.users:
            response = await message.reply(f"**Start your own damn game, {user.mention}!**\n\nYou can do so by doing "
                                           f"**`/hangman`** in one of your server's text channels!")
            return await response.delete(delay=10)

        guess = message.content.strip().upper()
        await message.delete()

        if len(guess) == 1 and guess in self.guessed_letters:
            return
        if guess in self.guessed_words:
            return

        return await self.update_progress(guess)

    def is_game(self, message: discord.Message) -> bool:
        return message.author in self.users and not self.is_done()
