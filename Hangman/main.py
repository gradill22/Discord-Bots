import os
import math
import discord
import options
from tabulate import tabulate
from discord import app_commands
from discord.ext import commands, tasks
from hangman import Hangman, Player


intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix="/", intents=intents)

# Game variables
ACTIVE_GAMES: list[Hangman] = []
PLAYERS: list[Player] = []


def find_player(user: discord.User) -> Player | None:
    global PLAYERS

    for player in PLAYERS:
        if user == player.user:
            return player


def get_player(user: discord.User) -> Player:
    global PLAYERS

    player = find_player(user)
    if player:
        return player

    new_player = Player(user)
    PLAYERS.append(new_player)
    return new_player


def leaderboard_string(players: list[Player], num_players: int = options.DEFAULT_NUM_TOP_PLAYERS,
                       n_days: int = 0) -> tuple[int, str]:
    players = [player for player in players if player.num_games_since_days(n_days) > 0]
    players = sorted(players, key=lambda p: p.points(n_days), reverse=True)
    num_players = min(len(players), num_players)

    board = ""
    m = math.floor(math.log10(max(len(players), 1))) + 1
    for i, player in enumerate(players[:num_players]):
        place = options.LEADERBOARD_PLACES.get(i + 1, f"{i+1:{m}d}")
        mention = player.user.mention
        points = player.points(n_days)
        points = format(points, f".{'0' if int(points) == float(points) else '1'}f") + " points"
        board += "* " + " | ".join(map(str, (place, mention, points)))
        if i < num_players - 1:
            board += "\n"

    return num_players, board


# Update the list of active games to remove inactive games every 30 minutes
@tasks.loop(minutes=options.ACTIVE_GAMES_UPDATE)
async def update_active_games() -> None:
    global ACTIVE_GAMES

    prune = [game for game in ACTIVE_GAMES if game.is_done]
    for game in prune:
        ACTIVE_GAMES.remove(game)

    if len(prune) > 0:
        print(f"Removed {len(prune):,} inactive game(s) from the active games list!")

    del prune


@bot.event
async def on_ready():
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} command(s)")
    except Exception as e:
        print(e)

    print(f"Bot is ready as {bot.user}!")
    update_active_games.start()
    await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.competing,
                                                        name="/hangman"))


@bot.tree.command(name="hangman", description="Let's play Hangman!")
async def hangman(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)

    player = get_player(interaction.user)
    if player.has_active_game():
        active_game = player.games[-1]
        if active_game.channel == interaction.channel:
            content, view = active_game.current_progress()
            return await interaction.followup.send(content=content, view=view, ephemeral=True)
        game_channel = active_game.channel
        game_server = game_channel.guild
        content = f"You already have an active game in {game_server.name}'s {game_channel.jump_url}."
        return await interaction.followup.send(content=content, ephemeral=True)

    new_game = Hangman(player=player, channel=interaction.channel)
    ACTIVE_GAMES.append(new_game)

    content, view = new_game.start_game()
    return await interaction.followup.send(content=content, view=view, ephemeral=True)


@bot.tree.command(name="leaderboard", description="A leaderboard for all Hangman players in your server!")
@app_commands.describe(number_of_top_players="[Default 10] The number of players to include in the leaderboard",
                       period="[Default \"This Week\"] How far back the leaderboard should be calculated")
@app_commands.choices(period=[app_commands.Choice(name=k, value=v) for k, v in options.LEADERBOARD_PERIODS.items()])
async def leaderboard(interaction: discord.Interaction, number_of_top_players: int = options.DEFAULT_NUM_TOP_PLAYERS,
                      period: app_commands.Choice[str] = options.DEFAULT_LEADERBOARD_PERIOD):
    await interaction.response.defer(ephemeral=True)
    if interaction.guild is None:
        return await interaction.followup.send(content=f"Sorry {interaction.user.mention}, but `/leaderboard` is only "
                                                       f"available for server text channels.", silent=True)

    period = str(period.name if type(period) is app_commands.Choice else period)
    n_days = options.LEADERBOARD_PERIODS[period]

    server = interaction.guild
    players = [player for player in PLAYERS if player.user in server.members]
    num_players, board = leaderboard_string(players, number_of_top_players, n_days)

    if num_players < options.MIN_LEADERBOARD_PLAYERS:
        return await interaction.followup.send(content=f"Sorry {interaction.user.mention}, but there aren't enough "
                                                       f"players in {server.name} to compile a leaderboard.\n\n"
                                                       f"Minimum number of players: {options.MIN_LEADERBOARD_PLAYERS}\n"
                                                       f"Number of {server.name}'s players {period.lower()}: "
                                                       f"{num_players}"
                                               )

    board = f"**{server.name} Top {num_players:,} Leaderboard of {period.title()}**\n\n" + board

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


@bot.tree.command(name="profile", description="See an overview of your Hangman profile!")
async def profile(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)

    player = find_player(interaction.user)
    if player is None:
        return await interaction.followup.send(content=f"You are not an active Hangman player. You can become one by "
                                                       f"playing your first game with `/hangman`!", ephemeral=True)

    content = "\n".join([
        f"Games played: {len(player.games)}",
        f"Points: {player.points}",
        f"Credits: {player.credits}{options.CREDIT_EMOJI}"
    ])

    return await interaction.followup.send(content=content, ephemeral=True)


@bot.tree.command(name="exchange", description=f"Exchange your points for credits "
                                               f"{options.POINTS_TO_CREDITS.numerator:,}:"
                                               f"{options.POINTS_TO_CREDITS.denominator:,}!")
@app_commands.describe(amount=f"[Optional] The number of points you want to exchange for credits")
async def exchange(interaction: discord.Interaction, amount: int = None):
    await interaction.response.defer(ephemeral=True)

    player = find_player(interaction.user)
    if player is None:
        return await interaction.followup.send(content=f"You are not an active player. Please start a game using "
                                                       f"`/hangman` to claim your free {options.START_CREDITS:,}"
                                                       f"{options.CREDIT_EMOJI}", ephemeral=True)

    player.exchange(amount)
    return await interaction.followup.send(content=f"You exchanged your points for credits!\n\n"
                                                   f"Points: {player.points:,}\n"
                                                   f"Credits: {player.credits:,}{options.CREDIT_EMOJI}", ephemeral=True)


@bot.tree.command(name="buy", description="Purchase your Hangman credits!")
@app_commands.describe(num_credits="The number of credits to purchase with its corresponding price")
@app_commands.choices(num_credits=[app_commands.Choice(name=f"{k:,}{options.CREDIT_EMOJI} (${v:,.2f})", value=k)
                                   for k, v in options.BUY_CREDITS.items()])
async def buy_credits(interaction: discord.Interaction, num_credits: app_commands.Choice[float]):
    await interaction.response.defer(ephemeral=True)

    player = find_player(interaction.user)
    if player is None:
        return await interaction.followup.send(content=f"You are not an active player. Please start a game using "
                                                       f"`/hangman` to claim your free {options.START_CREDITS:,}"
                                                       f"{options.CREDIT_EMOJI}", ephemeral=True)

    player.credits += num_credits.value
    return await interaction.followup.send(content=f"You successfully purchased {num_credits.name}!\n\n"
                                                   f"You now have {player.credits:,}{options.CREDIT_EMOJI}!",
                                           ephemeral=True)


def main():
    bot.run(os.environ["DISCORD_TOKEN"])


if __name__ == "__main__":
    main()
