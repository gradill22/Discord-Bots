import os
import discord
from tabulate import tabulate
from discord import app_commands
from discord.ext import commands, tasks
from hangman import Hangman, Player, leaderboard_string


# Bot setup
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix="/", intents=intents)

# Game variables
ACTIVE_GAMES: list[Hangman] = []
PLAYERS: list[Player] = []
MIN_LEADERBOARD_PLAYERS: int = 1


def get_player(user: discord.User):
    global PLAYERS

    player = find_player(user)
    if player:
        return player

    new_player = Player(user)
    PLAYERS.append(new_player)
    return new_player


def find_player(user: discord.User):
    global PLAYERS

    for player in PLAYERS:
        if user == player.user:
            return player


# Update the list of active games to remove inactive games every 30 minutes
@tasks.loop(minutes=30)
async def update_active_games() -> None:
    global ACTIVE_GAMES

    prune = [game for game in ACTIVE_GAMES if game.is_done()]
    for game in prune:
        ACTIVE_GAMES.remove(game)

    if len(prune) > 0:
        print(f"Removed {len(prune):,} inactive game(s) from the active games list!")
        prune.clear()


@bot.event
async def on_ready():
    print(f"Bot is ready as {bot.user}!")
    update_active_games.start()
    await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.watching,
                                                        name="you lose! | /hangman"))
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} command(s)")
    except Exception as e:
        print(e)


@bot.tree.command(name="hangman", description="Let's play Hangman!")
async def hangman(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)

    player = get_player(interaction.user)
    if player.has_active_game():
        return

    new_game = Hangman(player=player, channel=interaction.channel)
    ACTIVE_GAMES.append(new_game)

    content, view = new_game.start_game()
    return await interaction.followup.send(content=content, view=view, ephemeral=True)


@bot.tree.command(name="leaderboard", description="A leaderboard for all Hangman players in your server!")
@app_commands.describe(number_of_top_players="[Default 10] The number of players to include in the leaderboard",
                       period="[Default \"This Week\"] How far back the leaderboard should be calculated")
@app_commands.choices(period=[
    app_commands.Choice(name="Today", value="Today"),
    app_commands.Choice(name="This Week", value="This Week"),
    app_commands.Choice(name="This Month", value="This Month"),
    app_commands.Choice(name="All Time", value="All Time")
])
async def leaderboard(interaction: discord.Interaction, number_of_top_players: int = 10,
                      period: app_commands.Choice[str] = "This Week"):
    await interaction.response.defer()

    days_dict = {"Today": 1,
                 "This Week": 7,
                 "This Month": 30,
                 "All Time": 0}

    period = str(period.name) if type(period) is app_commands.Choice else str(period)
    n_days = days_dict[period]

    server = interaction.guild
    players = [player for player in PLAYERS if player.user in server.members]
    num_players, board = leaderboard_string(players, number_of_top_players, n_days)

    if num_players < MIN_LEADERBOARD_PLAYERS:
        return await interaction.followup.send(content=f"Sorry {interaction.user.mention}, but there aren't enough "
                                                       f"players in {server.name} to compile a leaderboard.\n\n"
                                                       f"Minimum number of players: {MIN_LEADERBOARD_PLAYERS}\n"
                                                       f"Number of {server.name}'s players {period.lower()}: "
                                                       f"{num_players}"
                                               )

    board = f"**{server.name} Top {num_players:,} Leaderboard for {period.title()}**\n\n" + board

    return await interaction.followup.send(content=board, silent=True)


@bot.tree.command(name="history", description="A general history of your Hangman games!")
@app_commands.describe(num_games="[Default 5] The last number of games to show a history of")
async def history(interaction: discord.Interaction, num_games: int = 5):
    await interaction.response.defer(ephemeral=True)

    user = interaction.user
    player = find_player(user)
    if player is None:
        return await interaction.followup.send(f"You haven't played a single game yet, {user.mention}. Try using "
                                               f"`/hangman` in one of your server's channels!", ephemeral=True)

    df = player.last_n_games(num_games)
    table = tabulate(df, headers="keys", showindex=False, tablefmt="presto")

    num_games = len(df)
    wins = sum(val == "Win" for val in df.loc[:, "Result"])
    total_points = df["Points"].sum()
    total_points = format(total_points, f".{'0' if int(total_points) == float(total_points) else '1'}f")

    return await interaction.followup.send(f"Your last {num_games} games:\n```\n{table}\n```\n"
                                           f"Record: {wins}-{num_games - wins}\n"
                                           f"Total points: {total_points}", ephemeral=True)


def main():
    bot.run(os.environ["DISCORD_TOKEN"])


if __name__ == "__main__":
    main()
