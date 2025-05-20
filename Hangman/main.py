import os
import query
import discord
import options
import datetime
import pandas as pd
from tabulate import tabulate
from discord import app_commands
from discord.ext import commands, tasks
from hangman import Hangman, Player


intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix=options.PREFIX, intents=intents)


@bot.event
async def on_ready():
    """
    Initializes databases and syncs commands when the bot starts up.
    """
    await query.initialize_db()
    await query.backup_to_main_etl()
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} command(s)")
    except Exception as e:
        print(e)

    await update_server_count()
    print(f"Bot is ready as {bot.user}!")


@bot.event
async def on_guild_join(guild: discord.Guild):
    """
    Creates the hangman text channel in the guild the bot just joined and sends a welcome message to that very channel.

    Then, the bot will update the "guild_members" SQL table to include known players in this new guild.

    :param guild: The guild the bot joins
    """
    channel = None
    for c in guild.text_channels:
        if c.name.lower() == "hangman":
            channel = c
    channel = channel or await guild.create_text_channel("hangman",
                                                         reason="Primary text channel for interacting with Hangman Bot")

    embed = discord.Embed(title="Thanks for inviting me!",
                          description=f"Thank you for inviting me to \"{guild.name}\"!\n"
                                      f"For more information about how I work, use the `/help` command!\n"
                                      f"To play your first game, use the `/hangman` command!",
                          color=discord.Color.blue())
    embed.set_thumbnail(url=bot.user.avatar.url)
    await channel.send(embed=embed)

    player_ids = pd.read_sql("SELECT players.id, players.discord_id, guild_members.guild_id FROM players "
                             "JOIN guild_members ON players.id = guild_members.user_id", con=query.get_db_connection())
    # Columns: [id, discord_id, guild_id]
    players_to_add = []
    for member in guild.members:
        id_ = player_ids[player_ids["discord_id"] == member.id]["id"]
        if len(id_) > 0:
            players_to_add.append(id_.iloc[0])

    if len(players_to_add) > 0:
        values = [f"({guild.id}, {player_id})" for player_id in players_to_add]
        query.execute(f"INSERT INTO guild_members (guild_id, user_id) VALUES {', '.join(values)}", commit=True,
                      fetch=False)

    await update_server_count()


@bot.event
async def on_guild_remove(guild: discord.Guild):
    """
    Removes all guild data from the `guild_members` SQL table and updates the server count.

    :param guild: The guild the bot was removed from
    """
    query.execute(f"DELETE FROM guild_members WHERE guild_id = {guild.id}", commit=True, fetch=False)
    await update_server_count()


async def update_server_count():
    num_servers = len(bot.guilds)
    await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.playing,
                                                        name=f"/hangman in {num_servers:,} servers"))


@tasks.loop(time=datetime.time(tzinfo=options.TZ))  # update at midnight in preferred timezone
async def backup_db() -> None:
    """
    Backs up the main database to the backup database every 24 hours at midnight in the preferred timezone.

    :return: None
    """
    await query.main_to_backup_etl()


@bot.tree.command(name="hangman", description="Simulates the Hangman game!")
async def hangman(interaction: discord.Interaction):
    """
    Simulates the Hangman game!

    :param interaction: The user's interaction with the bot
    :return: Followup to the initial interaction
    """
    await interaction.response.defer(ephemeral=True)
    player = Player(interaction)

    result = query.execute("SELECT id, channel_id FROM games WHERE player_id = ? AND is_done = ?",
                           (player.id, 0), fetch=True)
    if result:
        game_id, active_channel_id = result
        if active_channel_id == interaction.channel.id:
            game = Hangman(player, interaction.channel, game_id)
            image, embed, view = game.current_progress()
            return await interaction.followup.send(file=image, embed=embed, view=view, ephemeral=True)
        game_channel = bot.get_channel(active_channel_id)
        game_server = game_channel.guild
        content = f"You already have an active game in {game_server.name}'s {game_channel.jump_url}."
        embed = discord.Embed(title=f"You can't play here, {player.user.mention}...",
                              description=content, color=discord.Color.red())
        embed.set_thumbnail(url=bot.user.avatar.url)
        return await interaction.followup.send(embed=embed, ephemeral=True)

    new_game = Hangman(player, interaction.channel)
    image, embed, view = new_game.start_game()
    return await interaction.followup.send(file=image, embed=embed, view=view, ephemeral=True)


@bot.tree.command(name="leaderboard", description="A leaderboard for all Hangman players in your server!",
                  extras={"examples": ["/leaderboard", "/leaderboard 20 This Week", "/leaderboard 50 All Time"]})
@app_commands.describe(number_of_top_players=f"[Default {options.DEFAULT_NUM_TOP_PLAYERS}] The number of players to "
                                             "include in the leaderboard",
                       period=f"[Default \"{options.DEFAULT_LEADERBOARD_PERIOD}\"] How far back the leaderboard "
                              "should be calculated")
@app_commands.choices(period=[app_commands.Choice(name=k, value=k) for k in options.LEADERBOARD_PERIODS.keys()])
async def leaderboard(interaction: discord.Interaction, number_of_top_players: int = options.DEFAULT_NUM_TOP_PLAYERS,
                      period: app_commands.Choice[str] = options.DEFAULT_LEADERBOARD_PERIOD):
    """
    Creates a custom leaderboard for your server! See who the top players in your server are!

    :param interaction: The user's interaction with the bot
    :param number_of_top_players: The number of top players to include in the leaderboard
    :param period: The period of time for the leaderboard
    :return: The leaderboard
    """
    await interaction.response.defer(ephemeral=False)
    if interaction.guild is None:
        return await interaction.followup.send(content=f"Sorry {interaction.user.mention}, but `/leaderboard` is only "
                                                       f"available for server text channels.", silent=True)

    period = str(period.name if type(period) is app_commands.Choice else period)
    n_days = options.LEADERBOARD_PERIODS[period]

    with query.get_db_connection() as conn:
        query_ = """
            SELECT p.discord_id, SUM(g.points) as total_points, p.credits
            FROM players p
            LEFT JOIN games g ON p.id = g.player_id
            WHERE p.id IN (
                SELECT user_id FROM guild_members WHERE guild_id = ?
            )
        """
        params = [interaction.guild.id]
        if n_days > 0:
            query_ += " AND g.created_at >= datetime('now', ?)"
            params.append(f"-{n_days} days")
        query_ += " GROUP BY p.discord_id ORDER BY total_points DESC LIMIT ?"
        params.append(number_of_top_players)

        players_data = pd.read_sql(query_.strip(), con=conn, params=params)

    if len(players_data) < options.MIN_LEADERBOARD_PLAYERS:
        e = discord.Embed(title="No leaderboard players yet...",
                          description="There are not enough players to create a leaderboard.\nTry `/hangman`!",
                          color=discord.Color.red())
        return await interaction.followup.send(embed=e)

    players_data.index = pd.Index(name="Place", data=list(range(1, len(players_data) + 1)), dtype=int)
    players_data = players_data.rename(columns={"total_points": "Points", "credits": "Credits"}).dropna()
    members = [interaction.guild.get_member(id_) for id_ in players_data["discord_id"]]
    players_data["Player"] = [member.nick or member.name for member in members]
    players_data = players_data[["Player", "Points", "Credits", "discord_id"]]

    try:
        user_place = players_data[players_data["discord_id"] == interaction.user.id].index[0]
        user_points = players_data.loc[user_place, "Points"]
        placement = f"You are in **{options.make_ordinal(user_place)}**, {interaction.user.mention}!"
        post_board = []
        if user_place > 1:
            behind_member, behind_points = players_data.loc[user_place - 1, ["discord_id", "Points"]]
            post_board.append(f"You are {behind_points - user_points} points behind {members[user_place - 2].mention}!")
        if user_place < players_data.index[-1]:
            ahead_member, ahead_points = players_data.loc[2, ["discord_id", "Points"]]
            post_board.append(f"You are {user_points - ahead_points} points ahead of {members[user_place].mention}!")
    except IndexError:
        placement = f"You are not placed, {interaction.user.mention}."
        post_board = []

    players_data["Points"] = players_data["Points"].apply(
        lambda points: format(points, f",.{'0' if int(points) == float(points) else '1'}f")
    )
    players_data["Credits"] = players_data["Credits"].apply(lambda points: format(points, ",d"))
    table = tabulate(players_data.drop(columns=["discord_id"]), headers="keys", tablefmt="simple_outline",
                     showindex=True)
    post_board = "\n".join(post_board) if len(post_board) > 0 else "You are the lone champion!"
    embed = discord.Embed(title=f"Top {number_of_top_players} Players {period}",
                          description=f"{placement}\n```\n{table}\n```\n{post_board}",
                          color=discord.Color.green() if interaction.user in members else discord.Color.red(),
                          timestamp=datetime.datetime.now(tz=options.TZ))

    return await interaction.followup.send(embed=embed, silent=True)


@bot.tree.command(name="history", description="A general history of your Hangman games!")
@app_commands.describe(num_games=f"[Default {options.NUM_GAMES_HISTORY}] The last number of games to show a history of")
async def history(interaction: discord.Interaction, num_games: int = options.NUM_GAMES_HISTORY):
    """
    Shows your hangman game history! See your wins, losses, and points!

    :param interaction: The user's interaction with the bot
    :param num_games: The most recent number of games to include in the history
    :return: The game history as a table
    """
    await interaction.response.defer(ephemeral=True)
    player = Player(interaction)

    df = player.last_n_games(num_games)
    if len(df) == 0:
        return await interaction.followup.send(
            f"You haven't played a single game yet, {interaction.user.mention}. Try using "
            f"`/hangman` in one of your server's channels!", ephemeral=True)

    table = tabulate(df, headers="keys", showindex=False, tablefmt="presto")
    num_games = len(df)
    wins = sum(val == "Win" for val in df.loc[:, "Result"])
    total_points = df["Points"].sum()
    total_points = format(total_points, f",.{'0' if int(total_points) == float(total_points) else '1'}f")

    embed = discord.Embed(title=f"Your last {num_games:,} Hangman games",
                          description=f"```\n{table}\n```\nRecord: {wins:,}-{num_games - wins:,}\n"
                                      f"Total points: {total_points}",
                          color=discord.Color.green(),
                          timestamp=discord.utils.utcnow())

    return await interaction.followup.send(embed=embed, ephemeral=True)


@bot.tree.command(name="profile", description="See an overview of your Hangman profile!")
async def profile(interaction: discord.Interaction):
    """
    See your summarized profile! See your wins, losses, overall record, points, and number of credits!

    :param interaction: The user's interaction with the bot
    :return: The user's summarized profile
    """
    await interaction.response.defer(ephemeral=True)
    player = Player(interaction)
    if player is None:
        return await interaction.followup.send(content=f"You are not an active Hangman player. You can become one by "
                                                       f"playing your first game with `/hangman`!", ephemeral=True)

    content = "\n".join([
        f"Games played: {player.num_games()}",
        f"Record: {'-'.join(map(str, player.record()))}",
        f"Points: {player.points:,}",
        f"Credits: {player.credits:,} {options.CREDIT_EMOJI}"
    ])

    embed = discord.Embed(title=(player.user.nick or player.user.name), description=content,
                          color=discord.Color.og_blurple(), timestamp=discord.utils.utcnow())

    return await interaction.followup.send(embed=embed, ephemeral=True)


class Help(commands.MinimalHelpCommand):
    def __init__(self):
        super().__init__()
        # Configure settings for slash commands
        self.no_category = "Commands"
        self.sort_commands = True
        self.verify_checks = False
        self.command_attrs = {"hidden": False}

    async def command_callback(self, ctx, *, command=None):
        """
        Handles the /help command input and routes to the appropriate help method.

        :param ctx: The command context
        :param command: The command name provided (e.g., "leaderboard" for /help leaderboard)
        """
        if command is None:
            # No command specified, show general help
            return await self.send_bot_help({})

        # Look up the command in the bot's tree
        cmd = self.context.bot.tree.get_command(command)

        if cmd is None:
            # Command not found, send error
            return await self.send_error_message(f'No command called "{command}" found.')

        if isinstance(cmd, app_commands.Group):
            # Handle group commands
            return await self.send_group_help(cmd)

        # Handle regular slash commands
        return await self.send_command_help(cmd)

    async def send_bot_help(self, mapping):
        """
        Sends a general help page listing all available slash commands from the bot's tree.

        :param mapping: Ignored (used for prefix commands, not slash commands)
        """
        destination = self.get_destination()

        embed = discord.Embed(
            title="Hangman Bot Help",
            description="Welcome to Hangman Bot! Below are the available slash commands. "
                        f"Use `{options.PREFIX}help <command>` for more details.",
            color=discord.Color.blue(),
            timestamp=discord.utils.utcnow()
        )
        embed.set_thumbnail(url=self.context.bot.user.avatar.url if self.context.bot.user.avatar else None)
        embed.set_footer(text="Hangman Bot | Use /help <command> for more info")

        commands_ = self.context.bot.tree.get_commands()
        for command in sorted(commands_, key=lambda c: c.name):
            description = command.description or "No description available."
            embed.add_field(
                name=embed.title,
                value=description.split('\n')[0],
                inline=False
            )

        await destination.send(embed=embed)

    async def send_command_help(self, command):
        """
        Sends a detailed help page for a specific slash command.

        :param command: The app_commands.Command to display help for
        """
        destination = self.get_destination()

        embed = discord.Embed(
            title=f"/{command.name}",
            description=command.description or "No description available.",
            color=discord.Color.green(),
            timestamp=discord.utils.utcnow()
        )
        embed.set_footer(text=f"Hangman Bot | {embed.title} Details")

        usage = f"/{command.name}"
        if command.parameters:
            usage += " " + " ".join(
                f"<{param.name}>" if param.required else f"[{param.name}]"
                for param in command.parameters
            )
        embed.add_field(
            name="Usage",
            value=f"`{usage}`",
            inline=False
        )

        if command.parameters:
            params = []
            for param in command.parameters:
                param_desc = param.description or "No description."
                params.append(f"**{param.name}** ({'Required' if param.required else 'Optional'}): {param_desc}")
            embed.add_field(
                name="Parameters",
                value="\n".join(params),
                inline=False
            )

        if hasattr(command, "extras") and command.extras.get("examples"):
            embed.add_field(
                name="Examples",
                value="\n".join(f"`{example}`" for example in command.extras["examples"]),
                inline=False
            )

        await destination.send(embed=embed)

    async def send_error_message(self, error):
        """
        Handles invalid help queries.

        :param error: The error message
        """
        destination = self.get_destination()
        embed = discord.Embed(
            title="Error",
            description=error,
            color=discord.Color.red(),
            timestamp=discord.utils.utcnow()
        )
        embed.set_footer(text="Hangman Bot | Try /help")
        await destination.send(embed=embed)

    async def send_cog_help(self, cog):
        """
        Handles cog help (not used in this bot).
        """
        await self.send_bot_help({})

    async def send_group_help(self, group):
        """
        Handles group command help (if any exist in the tree).

        :param group: The app_commands.Group to display help for
        """
        destination = self.get_destination()

        embed = discord.Embed(
            title=f"/{group.name}",
            description=group.description or "No description available.",
            color=discord.Color.green(),
            timestamp=discord.utils.utcnow()
        )
        embed.set_footer(text="Hangman Bot | Group Command Details")

        if hasattr(group, "commands") and group.commands:
            subcommands = []
            for subcommand in sorted(group.commands, key=lambda c: c.name):
                subcommands.append(f"`/{group.name} {subcommand.name}`: {subcommand.description or 'No description.'}")
            embed.add_field(
                name="Subcommands",
                value="\n".join(subcommands),
                inline=False
            )

        await destination.send(embed=embed)

    async def send_pages(self):
        """
        Sends paginated help messages as embeds.
        """
        destination = self.get_destination()
        for page in self.paginator.pages:
            embed = discord.Embed(description=page, color=discord.Color.blue())
            await destination.send(embed=embed)

    async def filter_commands(self, commands_, *args, sort=False):
        """
        Filters and sorts slash commands from the bot's tree.

        :param commands_: List of app_commands.Command objects
        :param sort: Whether to sort commands by name
        :return: Filtered list of commands
        """
        if sort:
            return sorted(commands_, key=lambda c: c.name)
        return list(commands_)

    async def get_command_signature(self, command):
        """
        Returns the signature for a slash command.

        :param command: The app_commands.Command
        :return: String representing the command signature
        """
        signature = f"/{command.name}"
        if command.parameters:
            signature += " " + " ".join(
                f"<{param.name}>" if param.required else f"[{param.name}]"
                for param in command.parameters
            )
        return signature


if __name__ == "__main__":
    bot.help_command = Help()
    bot.run(os.environ["DISCORD_TOKEN"])
