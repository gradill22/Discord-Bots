import os
import discord
from discord.ext import commands
from discord import app_commands
from hangman import Hangman, Player

# Bot setup
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="/", intents=intents)

# Game variables
GAMES: list[Hangman] = []
PLAYERS: list[Player] = []


@bot.event
async def on_ready():
    print(f"Bot is ready as {bot.user}!")
    await bot.change_presence(activity=discord.Game(name="Hangman | /hangman"))
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} command(s)")
    except Exception as e:
        print(e)


@bot.tree.command(name="hangman", description="Let's play Hangman!")
@app_commands.describe(other_players="[Optional] Other players you'd like to play with "
                                     "(only works in server text channels)")
async def hangman(interaction: discord.Interaction, *other_players):
    await interaction.response.defer()

    users = [interaction.message.author] + [player.user for player in other_players
                                            if type(player) is discord.User.mention]
    game_players = []
    for user in users:
        if user not in PLAYERS:
            new_player = Player(user)
            PLAYERS.append(new_player)
            game_players.append(new_player)
            continue
        for player in PLAYERS:
            if user == player:
                game_players.append(player)
                break

    channel = interaction.channel

    new_game = Hangman(interaction, channel=channel, users=game_players)
    GAMES.append(new_game)
    return await new_game.start_game()


@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return  # Ignore bot messages

    # Check if this message is a reply to a game message
    if message.reference and message.reference.cached_message:
        original_message = message.reference.cached_message
        for game in GAMES:
            if game.is_game(original_message):
                return await game.push_guess(original_message)


def main():
    bot.run(os.environ["DISCORD_TOKEN"])


if __name__ == "__main__":
    main()
