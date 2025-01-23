import os
import json
import string
import discord
from discord.ext import commands
from random_word import Wordnik

# Bot setup
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="/", intents=intents)

# Random word generator
wordnik = Wordnik()

# Game variables
games = {}  # Store game state for each channel {(channel_id, user_id): {word, guessed, lives, progress}}

# Hangman visual states
LIVES_EMOJI = ":heart:"

UNDERSCORE = ":regional_indicator_x:"
HEADER = "{0}\n**Hangman**"


async def continue_game(message: discord.Message):
    channel = message.channel
    user = message.author
    game = games.get((channel.id, user.id), dict())
    if len(game) == 0:
        content = f"**{user.mention}, start your own damn game!**\n\nYou can do so by mentioning me!"
        return await message.channel.send(content)

    guess = message.content.strip().upper()
    await message.delete()
    if len(guess) == 1 and guess in game["guessed_letters"]:
        return
    elif len(guess) == len(game["word"]["word"]) and guess in game["guessed_words"]:
        return

    word = game["word"]
    winning_word = str(word["word"]).upper()
    definitions = "\n".join(f"{i + 1}) *{str(d['partOfSpeech']).lower()}*. {d['text']}"
                            for i, d in enumerate(word["definitions"]))
    definitions = f"Definition{'s' if len(word['definitions']) > 1 else ''}:\n{definitions}"
    content = None
    game["guessed_letters" if len(guess) == 1 else "guessed_words"].append(guess)
    if len(guess) == 1 and guess in winning_word:
        # Update progress
        game["progress"] = " ".join(
            [letter if letter in game["guessed_letters"] or letter not in string.ascii_uppercase else UNDERSCORE
             for letter in winning_word]
        )
        if UNDERSCORE not in game["progress"]:
            content = f"{user.mention}\n🎉 **You Won!** The word was **{str(word['word']).title()}**!\n\n{definitions}"
    elif guess == winning_word:
        content = f"{user.mention}\n🎉 **You Won!** The word was **{str(word['word']).title()}**!\n\n{definitions}"
    else:
        # Wrong guess
        game["lives"] -= 1
        game["wrong_letters"] = game.get("wrong_letters", list()) + [guess]
        if game["lives"] == 0:
            content = f"{user.mention}\n💀 **Game Over!** The word was **{str(word['word']).title()}.**\n\n{definitions}"

    if not content:
        content = [f"{HEADER.format(user.mention)}\n",
                   game["progress"] + "\n",
                   ' '.join([LIVES_EMOJI] * game['lives']),
                   f"Used letters: {', '.join(sorted(game.get('wrong_letters', list())))}",
                   f"Used words: {', '.join(sorted(game['guessed_words']))}",
                   "Guess a letter!"]
        if len(game.get("wrong_letters", list())) == 0:
            content.pop(3)
        if len(game["guessed_words"]) == 0:
            content.pop(-2)
        content = "\n".join(content)
    return await game["game_message"].edit(content=content)


@bot.event
async def on_ready():
    print(f"Bot is ready as {bot.user}!")
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} command(s)")
    except Exception as e:
        print(e)


@bot.tree.command(name="hangman", description="Let's play Hangman!")
async def hangman(interaction: discord.Interaction):
    await interaction.response.defer()

    channel = interaction.channel
    user = interaction.user
    word = json.loads(wordnik.word_of_the_day())  # Replace with a word generator

    game = games.get((channel.id, user.id), None)
    if game and game["word"]["word"] == word["word"]:
        new_message = await interaction.followup.send(f"{user.mention}\nThe word of the day hasn't updated yet. Try "
                                                      f"again later.")
        return await new_message.delete(delay=5)

    lives = 5
    progress = " ".join(UNDERSCORE if letter.upper() in string.ascii_uppercase else letter for letter in word["word"])

    content = f"{HEADER.format(user.mention)}\n\n{progress}\n\n{' '.join([LIVES_EMOJI] * lives)}\nGuess a letter!"
    game_message = await interaction.followup.send(content)

    games[(channel.id, user.id)] = {
        "word": word,
        "guessed_letters": list(),
        "guessed_words": list(),
        "lives": lives,
        "progress": progress.strip(),
        "game_message": game_message
    }


@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return  # Ignore bot messages

    # Check if this message is a reply to a game message
    if message.reference and message.reference.cached_message:
        original_message = message.reference.cached_message
        for _, game in games.items():
            if game["game_message"].id == original_message.id:
                await continue_game(message)
                return


def main():
    bot.run(os.environ["DISCORD_TOKEN"])


if __name__ == "__main__":
    main()
