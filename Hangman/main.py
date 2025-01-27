import os
import discord
from discord.ext import commands, tasks
from discord import app_commands
from hangman import Hangman, Player, leaderboard_string

# Bot setup
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="/", intents=intents)

# Game variables
ACTIVE_GAMES: list[Hangman] = []
PLAYERS: list[Player] = []
MIN_LEADERBOARD_PLAYERS: int = 1


# Update the list of active games to remove inactive games every 5 minutes
@tasks.loop(minutes=5)
async def update_active_games() -> None:
    global ACTIVE_GAMES

    prune = [game for game in ACTIVE_GAMES if game.is_done()]
    for game in prune:
        ACTIVE_GAMES.remove(game)
        del game

    print(f"Removed {len(prune):,} inactive game(s) from the active games list!")
    del prune


@bot.event
async def on_ready():
    print(f"Bot is ready as {bot.user}!")
    update_active_games.start()
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
        if not player.has_active_game():
            game_players.append(player)

    if len(game_players) == 0:
        return

    new_game = Hangman(interaction, channel=channel, users=game_players)
    ACTIVE_GAMES.append(new_game)

    return await new_game.start_game()


@bot.tree.command(name="leaderboard", description="A leaderboard for all Hangman players in your server!")
@app_commands.describe(number_of_top_players="[Default 10] The number of players to include in the leaderboard",
                       period="[Default \"This Week\"] How far back the leaderboard should be calculated")
@app_commands.choices(period=[
    app_commands.Choice(name="Today", value="day"),
    app_commands.Choice(name="This Week", value="week"),
    app_commands.Choice(name="This Month", value="month"),
])
async def leaderboard(interaction: discord.Interaction, number_of_top_players: int = 10,
                      period: app_commands.Choice[str] = "week"):
    n_days = 1 if period == "day" else 7 if period == "week" else 30

    await interaction.response.defer()

    server = interaction.guild
    players = [player for player in PLAYERS if player.user in server.members]
    board = leaderboard_string(players, number_of_top_players, n_days)
    num_players = board.count("\n") + int(len(board) > 0)

    if num_players < MIN_LEADERBOARD_PLAYERS:
        return await interaction.message.reply(content=f"Sorry {interaction.user.mention}, but there aren't enough "
                                                       f"players in {server.name} to compile a leaderboard.\n\n"
                                                       f"Minimum number of players: {MIN_LEADERBOARD_PLAYERS}\n"
                                                       f"Number of {server.name}'s players this {period}: {num_players}"
                                               )

    board = f"**{server.name} Top {number_of_top_players:,} Leaderboard**\n\n" + board

    return await interaction.channel.send(content=board, silent=True)


@bot.event
async def on_message(message: discord.Message):
    global ACTIVE_GAMES

    if message.author.bot:
        return  # Ignore bot messages

    if not message.channel.guild:  # Decline DMs
        return message.channel.send(content=f"I only work in Discord server's at the moment. Use me in one of your "
                                            f"server's text channels!")

    # Check if this message is a reply to a game message
    if message.reference and message.reference.cached_message:
        original_message = message.reference.cached_message
        if original_message.author != bot.user:  # Reply to our own messages only
            return

        for game in ACTIVE_GAMES:
            if game.is_game(message):
                return await game.push_guess(message)

        response = await message.reply(content=f"Sorry {message.author.mention}, but I couldn't find an active game of "
                                               f"yours. Try doing `/hangman` in your server's text channel!")
        await message.delete()
        return await response.delete(delay=10)


def main():
    bot.run(os.environ["DISCORD_TOKEN"])


if __name__ == "__main__":
    main()
