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
@app_commands.describe(other_player="[Optional] An additional player you can play Hangman with!")
async def hangman(interaction: discord.Interaction, other_player: discord.Member = None):
    await interaction.response.defer()

    channel = interaction.channel or interaction.user.dm_channel
    users = [interaction.user]
    if other_player is not None and interaction.channel is not None:
        users.append(other_player)

    game_players = []
    player_users = [player.user for player in PLAYERS]
    for user in users:
        if user not in player_users:
            new_player = Player(user)
            PLAYERS.append(new_player)
            game_players.append(new_player)
            continue

        player = PLAYERS[player_users.index(user)]
        game_players.append(player)

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
        if original_message.author != bot.user:
            return
        for game in GAMES:
            if game.is_game(message):
                return await game.push_guess(message)

        response = await message.reply(content=f"Sorry {message.author.mention}, but I couldn't find an active game of "
                                               f"yours. Try doing `/hangman` in your server's text channel or in a "
                                               f"private DM with me!")
        if message.channel.guild:
            await message.delete()
            return await response.delete(delay=10)


def main():
    bot.run(os.environ["DISCORD_TOKEN"])


if __name__ == "__main__":
    main()
