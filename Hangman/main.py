import os
import math
import discord
import options
from tabulate import tabulate
from discord import app_commands
from discord.ext import commands
from hangman import Hangman, Player
import mysql
from mysql.connector import Error


intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix="/", intents=intents)


def find_player(user: discord.User) -> Player | None:
    conn = options.get_db_connection()
    if conn:
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT discord_id FROM players WHERE discord_id = %s", (user.id,))
            return Player(user) if cursor.fetchone() else None
        finally:
            cursor.close()
            conn.close()
    return None


def get_player(user: discord.User) -> Player:
    return Player(user)


def leaderboard_string(players: list[Player], num_players: int = options.DEFAULT_NUM_TOP_PLAYERS,
                       n_days: int = 0) -> tuple[int, str]:
    players = [player for player in players if player.num_games_since_days(n_days) > 0]
    players = sorted(players, key=lambda p: p.points(n_days), reverse=True)
    num_players = min(len(players), num_players)

    board = ""
    m = math.floor(math.log10(max(len(players), 1))) + 1
    for i, player in enumerate(players[:num_players]):
        place = options.LEADERBOARD_PLACES.get(i + 1, f"{i + 1:{m}d}")
        mention = player.user.mention
        points = player.points(n_days)
        points = format(points, f".{'0' if int(points) == float(points) else '1'}f") + " points"
        board += "* " + " | ".join(map(str, (place, mention, points)))
        if i < num_players - 1:
            board += "\n"

    return num_players, board


@bot.event
async def on_ready():
    # Add tables to SQL database
    conn = options.get_db_connection()
    if conn:
        cursor = conn.cursor()
        try:
            cursor.execute("CREATE TABLE players (id INT AUTO_INCREMENT PRIMARY KEY, discord_id BIGINT UNIQUE NOT "
                           "NULL, points DECIMAL(10,1) DEFAULT 0, credits INT DEFAULT 500);")
            cursor.execute("CREATE TABLE games (id INT AUTO_INCREMENT PRIMARY KEY, player_id INT, channel_id BIGINT "
                           "NOT NULL, word VARCHAR(255) NOT NULL, is_wotd BOOLEAN DEFAULT FALSE, points DECIMAL(10,"
                           "1) DEFAULT 0, lives INT DEFAULT 5, is_done BOOLEAN DEFAULT FALSE, progress VARCHAR(255) "
                           "NOT NULL, guessed_letters JSON, guessed_words JSON, wrong_letters JSON, definitions JSON, "
                           "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY (player_id) REFERENCES "
                           "players(id));")
            cursor.execute("CREATE TABLE guild_members (guild_id BIGINT NOT NULL, user_id BIGINT NOT NULL, PRIMARY "
                           "KEY (guild_id, user_id));")
            conn.commit()
        finally:
            cursor.close()
            conn.close()

    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} command(s)")
    except Exception as e:
        print(e)

    print(f"Bot is ready as {bot.user}!")
    await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.competing,
                                                        name="/hangman"))


@bot.tree.command(name="hangman", description="Let's play Hangman!")
async def hangman(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    player = get_player(interaction.user)

    conn = options.get_db_connection()
    if conn:
        cursor = conn.cursor()
        try:
            cursor.execute(
                "SELECT id, channel_id FROM games WHERE player_id = %s AND is_done = FALSE",
                (player.id,)
            )
            result = cursor.fetchone()
            if result:
                game_id, active_channel_id = result
                if active_channel_id == interaction.channel.id:
                    game = Hangman(player, interaction.channel)
                    game.id = game_id
                    content, view = game.current_progress()
                    return await interaction.followup.send(content=content, view=view, ephemeral=True)
                game_channel = bot.get_channel(active_channel_id)
                game_server = game_channel.guild
                content = f"You already have an active game in {game_server.name}'s {game_channel.jump_url}."
                return await interaction.followup.send(content=content, ephemeral=True)

            new_game = Hangman(player, interaction.channel)
            content, view = new_game.start_game()
            return await interaction.followup.send(content=content, view=view, ephemeral=True)
        finally:
            cursor.close()
            conn.close()


@bot.tree.command(name="leaderboard", description="A leaderboard for all Hangman players in your server!")
@app_commands.describe(number_of_top_players="[Default 10] The number of players to include in the leaderboard",
                       period="[Default \"This Week\"] How far back the leaderboard should be calculated")
@app_commands.choices(period=[app_commands.Choice(name=k, value=k) for k in options.LEADERBOARD_PERIODS.keys()])
async def leaderboard(interaction: discord.Interaction, number_of_top_players: int = options.DEFAULT_NUM_TOP_PLAYERS,
                      period: app_commands.Choice[str] = options.DEFAULT_LEADERBOARD_PERIOD):
    await interaction.response.defer(ephemeral=True)
    if interaction.guild is None:
        return await interaction.followup.send(content=f"Sorry {interaction.user.mention}, but `/leaderboard` is only "
                                                       f"available for server text channels.", silent=True)

    period = str(period.name if type(period) is app_commands.Choice else period)
    n_days = options.LEADERBOARD_PERIODS[period]

    conn = options.get_db_connection()
    if conn:
        cursor = conn.cursor()
        try:
            query = """
                SELECT p.discord_id, SUM(g.points) as total_points
                FROM players p
                LEFT JOIN games g ON p.id = g.player_id
                WHERE p.discord_id IN (
                    SELECT user_id FROM guild_members WHERE guild_id = %s
                )
            """
            params = [interaction.guild.id]
            if n_days > 0:
                query += " AND g.created_at >= DATE_SUB(NOW(), INTERVAL %s DAY)"
                params.append(n_days)
            query += " GROUP BY p.discord_id ORDER BY total_points DESC LIMIT %s"
            params.append(number_of_top_players)

            cursor.execute(query, params)
            players_data = cursor.fetchall()
            num_players, board = leaderboard_string(players_data, number_of_top_players)

            if num_players < options.MIN_LEADERBOARD_PLAYERS:
                return await interaction.followup.send(
                    content=f"Sorry {interaction.user.mention}, but there aren't enough "
                            f"players in {interaction.guild.name} to compile a leaderboard.\n\n"
                            f"Minimum number of players: {options.MIN_LEADERBOARD_PLAYERS}\n"
                            f"Number of {interaction.guild.name}'s players {period.lower()}: "
                            f"{num_players}"
                    )

            board = f"**{interaction.guild.name} Top {num_players:,} Leaderboard of {period.title()}**\n\n" + board
            return await interaction.followup.send(content=board, silent=True)
        finally:
            cursor.close()
            conn.close()


@bot.tree.command(name="history", description="A general history of your Hangman games!")
@app_commands.describe(num_games="[Default 5] The last number of games to show a history of")
async def history(interaction: discord.Interaction, num_games: int = 5):
    await interaction.response.defer(ephemeral=True)
    player = find_player(interaction.user)
    if player is None:
        return await interaction.followup.send(
            f"You haven't played a single game yet, {interaction.user.mention}. Try using "
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
        f"Credits: {player.credits} {options.CREDIT_EMOJI}"
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
                                                   f"Credits: {player.credits:,} {options.CREDIT_EMOJI}",
                                           ephemeral=True)


if __name__ == "__main__":
    bot.run(os.environ["DISCORD_TOKEN"])
