import os
import time
import random
import asyncio
import sqlite3

import discord
from discord import app_commands
from discord.ext import commands

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DB_PATH = "roulette.db"
PREFIX = "%"
BOT_VERSION = "1.5V"
BOT_CREATOR = "jestre.py"

STARTING_BUCKS = 0

NORMAL_WIN_REWARD = 50000
NORMAL_WIN_REWARD_MULT = 100000
BUCKSHOT_WIN_REWARD = 50000
BUCKSHOT_WIN_REWARD_MULT = 100000

STEAL_COOLDOWN_SECONDS = 30 * 60
STEAL_CHANCE = 0.30
STEAL_MIN = 500
STEAL_MAX = 100000

TURN_TIMEOUT = 30  # seconds, applies to Normal / Solo / Buckshot turns

MINES_MODES = {
    "easy":   {"size": 3, "bombs": 3},
    "medium": {"size": 5, "bombs": 5},
    "hard":   {"size": 8, "bombs": 8},
}

SHOP_ITEMS = {
    "rewards multiplier": {"price": 250000, "type": "flag", "column": "rewards_multiplier", "emoji": "✨"},
    "handgun": {"price": 300000, "type": "flag", "column": "handgun", "emoji": "🔫"},
    "topaz": {"price": 50000, "type": "gem", "emoji": "🟡"},
    "amethyst": {"price": 100000, "type": "gem", "emoji": "🟣"},
    "sapphire": {"price": 250000, "type": "gem", "emoji": "🔵"},
    "ruby": {"price": 500000, "type": "gem", "emoji": "🔴"},
    "emerald": {"price": 1000000, "type": "gem", "emoji": "🟢"},
    "diamond": {"price": 5000000, "type": "gem", "emoji": "💎"},
}

BOT_SHOOT_MESSAGES = [
    "Do you want to see the light?",
    "This may be your last day.",
    "Im sorry.",
    "Im talking the risk.",
    "I dont know what to expect.",
]

INSPECT_NO_USES_MESSAGES = [
    "You trying to cheat?",
    "Oi, i wont do that if i were you.",
]

BATTERY_INVALID_MESSAGES = [
    "Are you trying to fix that thing?",
    "What are you, a technician?",
]

ALCOHOL_INVALID_MESSAGES = [
    "Want a refill? kill me first.",
    "Too bad, you better win this if you want to drink more.",
]

BUY_INSUFFICIENT_MESSAGES = [
    "Get rich before you buy something mate.",
    "Poor ass, get a job or something",
    "Sorry, we dont have a dollar to spare to you",
    "Get money first, poor idiot.",
]

COINFLIP_LOSS_MESSAGES = [
    "Better luck next time idiot.",
    "Imagine losing all your money from a single coinflip.",
    "Pathetic, even no one would try and do that stupid thing.",
]

STEAL_FAIL_MESSAGES = [
    "Well that is a pathetic attempt to rob someone.",
    "I feel second-hand embarrassment for you.",
    "Sucks to be you.",
]

BUCKSHOT_INSERT_MESSAGES = [
    "Goodluck to you two.",
    "Only one can survive.",
]

INTRO_GIF_URL = "https://klipy.com/gifs/buckshot-roulette-dealer-4"

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            bucks INTEGER NOT NULL DEFAULT 0,
            kills INTEGER NOT NULL DEFAULT 0,
            deaths INTEGER NOT NULL DEFAULT 0,
            rewards_multiplier INTEGER NOT NULL DEFAULT 0,
            handgun INTEGER NOT NULL DEFAULT 0,
            last_steal REAL NOT NULL DEFAULT 0
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS inventory (
            user_id INTEGER NOT NULL,
            item_name TEXT NOT NULL,
            quantity INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (user_id, item_name)
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS guild_settings (
            guild_id INTEGER PRIMARY KEY,
            game_channel INTEGER
        )
    """)
    conn.commit()
    conn.close()


def get_conn():
    return sqlite3.connect(DB_PATH)


def ensure_user(user_id: int):
    conn = get_conn()
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO users (user_id, bucks) VALUES (?, ?)", (user_id, STARTING_BUCKS))
    conn.commit()
    conn.close()


def get_user(user_id: int):
    ensure_user(user_id)
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        "SELECT user_id, bucks, kills, deaths, rewards_multiplier, handgun, last_steal "
        "FROM users WHERE user_id = ?",
        (user_id,),
    )
    row = c.fetchone()
    conn.close()
    return row


def get_bucks(user_id: int) -> int:
    return get_user(user_id)[1]


def add_bucks(user_id: int, amount: int):
    ensure_user(user_id)
    conn = get_conn()
    c = conn.cursor()
    c.execute("UPDATE users SET bucks = MAX(0, bucks + ?) WHERE user_id = ?", (amount, user_id))
    conn.commit()
    conn.close()


def add_kill(user_id: int):
    ensure_user(user_id)
    conn = get_conn()
    c = conn.cursor()
    c.execute("UPDATE users SET kills = kills + 1 WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()


def add_death(user_id: int):
    ensure_user(user_id)
    conn = get_conn()
    c = conn.cursor()
    c.execute("UPDATE users SET deaths = deaths + 1 WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()


def has_rewards_multiplier(user_id: int) -> bool:
    return bool(get_user(user_id)[4])


def has_handgun(user_id: int) -> bool:
    return bool(get_user(user_id)[5])


def set_flag(user_id: int, column: str):
    ensure_user(user_id)
    conn = get_conn()
    c = conn.cursor()
    c.execute(f"UPDATE users SET {column} = 1 WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()


def add_inventory_item(user_id: int, item_name: str):
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        "INSERT INTO inventory (user_id, item_name, quantity) VALUES (?, ?, 1) "
        "ON CONFLICT(user_id, item_name) DO UPDATE SET quantity = quantity + 1",
        (user_id, item_name),
    )
    conn.commit()
    conn.close()


def get_last_steal(user_id: int) -> float:
    return get_user(user_id)[6]


def set_last_steal(user_id: int, ts: float):
    ensure_user(user_id)
    conn = get_conn()
    c = conn.cursor()
    c.execute("UPDATE users SET last_steal = ? WHERE user_id = ?", (ts, user_id))
    conn.commit()
    conn.close()


def get_game_channel(guild_id: int):
    if guild_id is None:
        return None
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT game_channel FROM guild_settings WHERE guild_id = ?", (guild_id,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else None


def set_game_channel(guild_id: int, channel_id: int):
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        "INSERT INTO guild_settings (guild_id, game_channel) VALUES (?, ?) "
        "ON CONFLICT(guild_id) DO UPDATE SET game_channel = ?",
        (guild_id, channel_id, channel_id),
    )
    conn.commit()
    conn.close()


def get_leaderboard(column: str, member_ids=None, limit: int = 10):
    conn = get_conn()
    c = conn.cursor()
    if member_ids is not None:
        if not member_ids:
            conn.close()
            return []
        placeholders = ",".join("?" * len(member_ids))
        c.execute(
            f"SELECT user_id, {column} FROM users WHERE user_id IN ({placeholders}) "
            f"ORDER BY {column} DESC LIMIT ?",
            (*member_ids, limit),
        )
    else:
        c.execute(f"SELECT user_id, {column} FROM users ORDER BY {column} DESC LIMIT ?", (limit,))
    rows = c.fetchall()
    conn.close()
    return rows


# ---------------------------------------------------------------------------
# Bot setup
# ---------------------------------------------------------------------------

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(
    command_prefix=PREFIX,
    intents=intents,
    help_command=None,
    allowed_mentions=discord.AllowedMentions.none(),  # never pings anyone
)

active_games = {}   # guild_id -> game state dict
active_mines = {}   # user_id -> mines state dict


def require_game_channel(guild_id: int, channel_id: int) -> bool:
    gc = get_game_channel(guild_id)
    return gc is not None and gc == channel_id


def safe_name(guild: discord.Guild, user_id: int) -> str:
    member = guild.get_member(user_id) if guild else None
    return member.display_name if member else "Unknown Player"


async def disable_player_messages(guild: discord.Guild, channel_id: int, user_id: int):
    channel = guild.get_channel(channel_id)
    member = guild.get_member(user_id)
    if channel is None or member is None:
        return
    try:
        await channel.set_permissions(member, send_messages=False)
    except discord.Forbidden:
        pass


async def restore_all_permissions(guild: discord.Guild, channel_id: int, participant_ids):
    channel = guild.get_channel(channel_id)
    if channel is None:
        return
    for user_id in participant_ids:
        member = guild.get_member(user_id)
        if member is None:
            continue
        try:
            await channel.set_permissions(member, overwrite=None)
        except discord.Forbidden:
            pass


# ---------------------------------------------------------------------------
# Shared cylinder ("chamber system") logic
# ---------------------------------------------------------------------------

def new_full_cylinder(size: int = 6, min_filled: int = 1) -> list:
    """A cylinder where ALL `size` chambers are loaded (filled or blank)."""
    filled_count = random.randint(min_filled, size)
    layout = [True] * filled_count + [False] * (size - filled_count)
    random.shuffle(layout)
    return layout


def new_buckshot_cylinder() -> list:
    """Buckshot uses a variable total (1-6), filled/blank both optional."""
    total = random.randint(1, 6)
    filled_count = random.randint(0, total)
    layout = [True] * filled_count + [False] * (total - filled_count)
    random.shuffle(layout)
    return layout


def cylinder_counts(cylinder: list):
    filled = sum(1 for shell in cylinder if shell)
    blank = len(cylinder) - filled
    return filled, blank


def pop_shell(game: dict, refill_func, refill_message_prefix: str = None):
    """Pops the next shell from the game's cylinder, reloading if empty."""
    if not game["cylinder"]:
        game["cylinder"] = refill_func()
    return game["cylinder"].pop(0)


def bump_turn(game: dict) -> int:
    game["turn_token"] = game.get("turn_token", 0) + 1
    return game["turn_token"]


async def turn_watchdog(guild_id: int, token: int, resolver):
    await asyncio.sleep(TURN_TIMEOUT)
    game = active_games.get(guild_id)
    if not game or game.get("turn_token") != token:
        return
    await resolver()


def armor_line(*pairs) -> str:
    """pairs: sequence of (label, value) tuples."""
    parts = [f"🛡️ **{label}:** {value}" for label, value in pairs]
    return " | ".join(parts)


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------

@bot.event
async def on_ready():
    init_db()
    try:
        await bot.tree.sync()
    except Exception as exc:
        print(f"Slash command sync failed: {exc}")
    print(f"Logged in as {bot.user} (v{BOT_VERSION})")


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return
    if isinstance(error, (commands.MissingRequiredArgument, commands.BadArgument)):
        await ctx.send("Invalid arguments provided.")
        return
    print(f"Command error: {error}")


@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error):
    try:
        if interaction.response.is_done():
            await interaction.followup.send("An error occurred while processing this command.", ephemeral=True)
        else:
            await interaction.response.send_message("An error occurred while processing this command.", ephemeral=True)
    except Exception:
        pass
    print(f"App command error: {error}")


# ---------------------------------------------------------------------------
# /information
# ---------------------------------------------------------------------------

@bot.tree.command(name="information", description="Shows bot information.")
async def information(interaction: discord.Interaction):
    embed = discord.Embed(title="Bot Information", color=discord.Color.dark_red())
    embed.add_field(name="Current Version", value=BOT_VERSION, inline=True)
    embed.add_field(name="Creator", value=BOT_CREATOR, inline=True)
    embed.add_field(name="Ping", value=f"{round(bot.latency * 1000)}ms", inline=True)
    embed.add_field(name="Status", value="Online", inline=True)
    await interaction.response.send_message(embed=embed)


# ---------------------------------------------------------------------------
# /intro
# ---------------------------------------------------------------------------

@bot.tree.command(name="intro", description="Meet the dealer.")
async def intro(interaction: discord.Interaction):
    await interaction.response.send_message(INTRO_GIF_URL)
    channel = interaction.channel
    await channel.send("Risk your life with a single gun.")
    await channel.send("Bot made by: Jestre.py")
    await channel.send("Inspired by the game: Buckshot Roulette - A computer game")


# ---------------------------------------------------------------------------
# /setchannelgm
# ---------------------------------------------------------------------------

@bot.tree.command(name="setchannelgm", description="Set the designated game channel.")
@app_commands.checks.has_permissions(manage_channels=True)
async def setchannelgm(interaction: discord.Interaction, channel: discord.TextChannel):
    set_game_channel(interaction.guild_id, channel.id)
    await interaction.response.send_message(f"Game channel set to {channel.mention}.")


# ---------------------------------------------------------------------------
# /shop (OwO-style embed)
# ---------------------------------------------------------------------------

@bot.tree.command(name="shop", description="View the shop.")
async def shop(interaction: discord.Interaction):
    embed = discord.Embed(
        title="🛒 Roulette Shop",
        description="Use `%buy (item)` to purchase.",
        color=discord.Color.gold(),
    )

    upgrades = ""
    for key in ("rewards multiplier", "handgun"):
        item = SHOP_ITEMS[key]
        upgrades += f"{item['emoji']} **{key.title()}** — {item['price']:,} Bucks\n"
    embed.add_field(name="⚙️ Upgrades", value=upgrades, inline=False)

    gems = ""
    for key in ("topaz", "amethyst", "sapphire", "ruby", "emerald", "diamond"):
        item = SHOP_ITEMS[key]
        gems += f"{item['emoji']} **{key.title()}** — {item['price']:,} Bucks\n"
    embed.add_field(name="💠 Gems", value=gems, inline=False)

    embed.set_footer(text="Roulette Bot Shop")
    await interaction.response.send_message(embed=embed)


# ---------------------------------------------------------------------------
# /leaderboard
# ---------------------------------------------------------------------------

@bot.tree.command(name="leaderboard", description="View the leaderboard.")
@app_commands.describe(type="Leaderboard type", scope="Local or global scope")
@app_commands.choices(
    type=[
        app_commands.Choice(name="kills", value="kills"),
        app_commands.Choice(name="deaths", value="deaths"),
        app_commands.Choice(name="bucks", value="bucks"),
    ],
    scope=[
        app_commands.Choice(name="local", value="local"),
        app_commands.Choice(name="global", value="global"),
    ],
)
async def leaderboard(interaction: discord.Interaction, type: app_commands.Choice[str], scope: app_commands.Choice[str]):
    await interaction.response.defer()
    column = type.value

    if scope.value == "local":
        if interaction.guild is None:
            await interaction.followup.send("This can only be used in a server.")
            return
        member_ids = [m.id for m in interaction.guild.members if not m.bot]
        rows = get_leaderboard(column, member_ids=member_ids)
    else:
        rows = get_leaderboard(column)

    if not rows:
        await interaction.followup.send("No data available.")
        return

    lines = []
    for i, (uid, value) in enumerate(rows, start=1):
        name = safe_name(interaction.guild, uid) if interaction.guild else f"User {uid}"
        lines.append(f"**{i}.** {name} - {value:,}")

    embed = discord.Embed(
        title=f"Leaderboard - {column.capitalize()} ({scope.value})",
        description="\n".join(lines),
        color=discord.Color.blue(),
    )
    await interaction.followup.send(embed=embed)


# ---------------------------------------------------------------------------
# /help
# ---------------------------------------------------------------------------

@bot.tree.command(name="help", description="Show the help menu.")
async def help_command(interaction: discord.Interaction):
    embed = discord.Embed(title="Help", color=discord.Color.dark_gold())
    embed.add_field(
        name="Roulette",
        value="/normalroulette\n/soloroulette\n/buckshotroulette @user",
        inline=False,
    )
    embed.add_field(
        name="Solo",
        value=(
            "%s action inspect\n%solo action inspect\n"
            "%s item battery\n%solo item battery\n"
            "%s item alcohol\n%solo item alcohol"
        ),
        inline=False,
    )
    embed.add_field(
        name="Economy",
        value=(
            "%currency\n%buy (item)\n%give (amount) @user\n"
            "%mines (amount) (easy/medium/hard)\n%coinflip h/t (amount)\n%steal @user\n/shop"
        ),
        inline=False,
    )
    embed.add_field(
        name="Leaderboards",
        value="/leaderboard kills local/global\n/leaderboard deaths local/global\n/leaderboard bucks local/global",
        inline=False,
    )
    embed.add_field(name="Bot", value="/information\n/setchannelgm #channel\n/intro\n/help", inline=False)
    await interaction.response.send_message(embed=embed)


# ---------------------------------------------------------------------------
# Normal Roulette
# ---------------------------------------------------------------------------

async def announce_normal_turn(guild_id: int):
    game = active_games.get(guild_id)
    if not game or game["type"] != "normal":
        return
    channel = bot.get_channel(game["channel_id"])
    if channel is None:
        return
    guild = channel.guild
    player_id = game["alive"][game["turn_index"] % len(game["alive"])]
    name = safe_name(guild, player_id)

    token = bump_turn(game)
    await channel.send(f"{name} two choices, shoot yourself, or shoot someone...")

    async def resolver():
        g = active_games.get(guild_id)
        if not g or g["type"] != "normal":
            return
        cid = g["alive"][g["turn_index"] % len(g["alive"])]
        cname = safe_name(guild, cid)
        await channel.send(f"Time's up! {cname} hesitated and shoots themselves.")
        await resolve_normal_shot(guild, channel, cid, cid)

    asyncio.create_task(turn_watchdog(guild_id, token, resolver))


async def end_normal_game(guild: discord.Guild, game: dict):
    winner_id = game["alive"][0]
    reward = NORMAL_WIN_REWARD_MULT if has_rewards_multiplier(winner_id) else NORMAL_WIN_REWARD
    add_bucks(winner_id, reward)

    channel = bot.get_channel(game["channel_id"])
    winner_name = safe_name(guild, winner_id)

    if channel is not None:
        await channel.send(f"{winner_name} wins the game and receives {reward:,} Bucks!")

    await restore_all_permissions(guild, game["channel_id"], game["participants"])
    del active_games[guild.id]


@bot.tree.command(name="normalroulette", description="Start a multiplayer roulette game.")
async def normalroulette(interaction: discord.Interaction):
    guild_id = interaction.guild_id
    channel = interaction.channel

    if interaction.guild is None:
        await interaction.response.send_message("This can only be used in a server.", ephemeral=True)
        return

    if not require_game_channel(guild_id, channel.id):
        await interaction.response.send_message("This command can only be used in the designated game channel.", ephemeral=True)
        return

    if guild_id in active_games:
        await interaction.response.send_message("A game is already active in this server.", ephemeral=True)
        return

    active_games[guild_id] = {"type": "pending"}

    await interaction.response.send_message("Putting ammo in the revolver...")
    msg = await interaction.original_response()
    await asyncio.sleep(2)
    await msg.edit(content="Spinning the chamber...")
    await asyncio.sleep(2)

    join_msg = await channel.send("React with ✅ to join! You have 30 seconds.")
    await join_msg.add_reaction("✅")
    await asyncio.sleep(30)

    join_msg = await channel.fetch_message(join_msg.id)
    participants = []
    for reaction in join_msg.reactions:
        if str(reaction.emoji) == "✅":
            async for user in reaction.users():
                if not user.bot and user.id not in participants:
                    participants.append(user.id)

    if len(participants) < 2:
        await channel.send("Not enough players joined. Game cancelled.")
        del active_games[guild_id]
        return

    cylinder = new_full_cylinder(size=6, min_filled=1)
    filled, blank = cylinder_counts(cylinder)

    active_games[guild_id] = {
        "type": "normal",
        "channel_id": channel.id,
        "participants": participants,
        "alive": participants.copy(),
        "turn_index": random.randrange(len(participants)),
        "cylinder": cylinder,
        "turn_token": 0,
    }

    await channel.send(f"{filled} and {blank}, Goodluck.")
    await announce_normal_turn(guild_id)


async def resolve_normal_shot(guild: discord.Guild, channel: discord.abc.Messageable, actor_id: int, target_id: int):
    game = active_games.get(guild.id)
    if not game or game["type"] != "normal":
        return

    alive = game["alive"]
    idx = game["turn_index"] % len(alive)

    if target_id not in alive:
        return

    is_boom = pop_shell(game, lambda: new_full_cylinder(size=6, min_filled=1))

    if is_boom:
        await channel.send("*Boom*")
        if target_id != actor_id:
            add_kill(actor_id)
        add_death(target_id)

        await disable_player_messages(guild, game["channel_id"], target_id)
        target_name = safe_name(guild, target_id)
        actor_name = safe_name(guild, actor_id)
        alive.remove(target_id)
        await channel.send(f"{target_name} was eliminated by {actor_name}")

        if len(alive) <= 1:
            await end_normal_game(guild, game)
            return

        game["turn_index"] = idx % len(alive)
    else:
        await channel.send("*Click*")
        game["turn_index"] = (idx + 1) % len(alive)

    await announce_normal_turn(guild.id)


# ---------------------------------------------------------------------------
# Buckshot Roulette
# ---------------------------------------------------------------------------

async def announce_buckshot_turn(guild_id: int):
    game = active_games.get(guild_id)
    if not game or game["type"] != "buckshot":
        return
    channel = bot.get_channel(game["channel_id"])
    if channel is None:
        return
    guild = channel.guild
    player_id = game["alive"][game["turn_index"] % len(game["alive"])]
    name = safe_name(guild, player_id)

    token = bump_turn(game)
    await channel.send(f"{name} two choices, shoot yourself, or shoot someone...")

    p1, p2 = game["participants"]
    await channel.send(armor_line(
        (safe_name(guild, p1), game["armor"].get(p1, 0)),
        (safe_name(guild, p2), game["armor"].get(p2, 0)),
    ))

    async def resolver():
        g = active_games.get(guild_id)
        if not g or g["type"] != "buckshot":
            return
        cid = g["alive"][g["turn_index"] % len(g["alive"])]
        cname = safe_name(guild, cid)
        await channel.send(f"Time's up! {cname} hesitated and shoots themselves.")
        await resolve_buckshot_shot(guild, channel, cid, cid)

    asyncio.create_task(turn_watchdog(guild_id, token, resolver))


async def end_buckshot_game(guild: discord.Guild, game: dict):
    winner_id = game["alive"][0]
    reward = BUCKSHOT_WIN_REWARD_MULT if has_rewards_multiplier(winner_id) else BUCKSHOT_WIN_REWARD
    add_bucks(winner_id, reward)

    channel = bot.get_channel(game["channel_id"])
    winner_name = safe_name(guild, winner_id)

    if channel is not None:
        await channel.send(f"{winner_name} wins the duel and receives {reward:,} Bucks!")

    await restore_all_permissions(guild, game["channel_id"], game["participants"])
    del active_games[guild.id]


@bot.tree.command(name="buckshotroulette", description="Challenge another user to Buckshot Roulette.")
async def buckshotroulette(interaction: discord.Interaction, user: discord.Member):
    guild_id = interaction.guild_id
    channel = interaction.channel

    if interaction.guild is None:
        await interaction.response.send_message("This can only be used in a server.", ephemeral=True)
        return

    if not require_game_channel(guild_id, channel.id):
        await interaction.response.send_message("This command can only be used in the designated game channel.", ephemeral=True)
        return

    if guild_id in active_games:
        await interaction.response.send_message("A game is already active in this server.", ephemeral=True)
        return

    if user.bot:
        await interaction.response.send_message("You cannot challenge a bot.", ephemeral=True)
        return

    if user.id == interaction.user.id:
        await interaction.response.send_message("You cannot challenge yourself.", ephemeral=True)
        return

    p1, p2 = interaction.user.id, user.id
    cylinder = new_buckshot_cylinder()

    active_games[guild_id] = {
        "type": "buckshot",
        "channel_id": channel.id,
        "participants": [p1, p2],
        "alive": [p1, p2],
        "armor": {p1: 4, p2: 4},
        "turn_index": random.randrange(2),
        "cylinder": cylinder,
        "turn_token": 0,
    }

    await interaction.response.send_message(random.choice(BUCKSHOT_INSERT_MESSAGES))
    await announce_buckshot_turn(guild_id)


async def resolve_buckshot_shot(guild: discord.Guild, channel: discord.abc.Messageable, actor_id: int, target_id: int):
    game = active_games.get(guild.id)
    if not game or game["type"] != "buckshot":
        return

    alive = game["alive"]
    idx = game["turn_index"] % len(alive)

    if target_id not in game["participants"] or target_id not in alive:
        return

    is_boom = pop_shell(game, new_buckshot_cylinder)

    if is_boom:
        await channel.send("*Boom*")
        game["armor"][target_id] -= 1

        if game["armor"][target_id] <= 0:
            add_death(target_id)
            if target_id != actor_id:
                add_kill(actor_id)

            await disable_player_messages(guild, game["channel_id"], target_id)
            target_name = safe_name(guild, target_id)
            actor_name = safe_name(guild, actor_id)
            alive.remove(target_id)
            await channel.send(f"{target_name} was eliminated by {actor_name}")
            await end_buckshot_game(guild, game)
            return
    else:
        await channel.send("*Click*")

    game["turn_index"] = (idx + 1) % len(alive)
    await announce_buckshot_turn(guild.id)


# ---------------------------------------------------------------------------
# %shoot (shared by Normal and Buckshot roulette)
# ---------------------------------------------------------------------------

@bot.command(name="shoot")
async def shoot(ctx: commands.Context, target: discord.Member = None):
    if ctx.guild is None:
        return
    guild_id = ctx.guild.id
    if guild_id not in active_games:
        return

    game = active_games[guild_id]
    if game["type"] not in ("normal", "buckshot"):
        return
    if ctx.channel.id != game["channel_id"]:
        return
    if target is None:
        await ctx.send("You must specify a target to shoot.")
        return
    if target.bot:
        await ctx.send("You cannot shoot a bot in this mode.")
        return

    alive = game["alive"]
    idx = game["turn_index"] % len(alive)
    current_id = alive[idx]

    if ctx.author.id != current_id:
        return
    if target.id not in alive:
        await ctx.send("That player is not in the game or is already eliminated.")
        return

    if game["type"] == "normal":
        await resolve_normal_shot(ctx.guild, ctx.channel, ctx.author.id, target.id)
    else:
        await resolve_buckshot_shot(ctx.guild, ctx.channel, ctx.author.id, target.id)


# ---------------------------------------------------------------------------
# Solo Roulette
# ---------------------------------------------------------------------------

async def check_solo_game_over(guild: discord.Guild, channel: discord.abc.Messageable, game: dict) -> bool:
    guild_id = guild.id
    player_name = safe_name(guild, game["player_id"])

    if game["player_armor"] <= 0:
        await channel.send(f"{player_name} was eliminated. The bot wins.")
        add_death(game["player_id"])
        del active_games[guild_id]
        return True

    if game["bot_armor"] <= 0:
        await channel.send(f"The bot was eliminated. {player_name} wins!")
        del active_games[guild_id]
        return True

    return False


def maybe_spawn_battery(game: dict):
    """Battery spawn is a silent 20% roll, never announced (per fix #5)."""
    if game["player_armor"] <= 1 and random.random() < 0.20:
        game["battery_available"] = True


async def announce_solo_player_turn(guild_id: int):
    game = active_games.get(guild_id)
    if not game or game["type"] != "solo":
        return
    channel = bot.get_channel(game["channel_id"])
    if channel is None:
        return
    guild = channel.guild
    player_name = safe_name(guild, game["player_id"])

    token = bump_turn(game)
    await channel.send(armor_line(("Your Armor", game["player_armor"]), ("Bot Armor", game["bot_armor"])))
    await channel.send(f"{player_name} two choices, shoot yourself, or shoot someone...")

    async def resolver():
        g = active_games.get(guild_id)
        if not g or g["type"] != "solo" or g["turn"] != "player":
            return
        await channel.send(f"Time's up! {player_name} hesitated and shoots themselves.")
        await resolve_solo_player_shot(guild, channel, g, shoot_bot=False)

    asyncio.create_task(turn_watchdog(guild_id, token, resolver))


async def run_bot_turn(guild: discord.Guild, channel: discord.abc.Messageable, game: dict):
    guild_id = guild.id

    await channel.send(random.choice(BOT_SHOOT_MESSAGES))
    await asyncio.sleep(1.5)

    shoot_bot_self = random.random() < 0.5
    await channel.send(f"The bot points the gun at {'itself' if shoot_bot_self else 'you'}...")
    await asyncio.sleep(1.5)

    is_boom = pop_shell(game, lambda: new_full_cylinder(size=6, min_filled=1))

    if is_boom:
        await channel.send("*Boom*")
        if shoot_bot_self:
            game["bot_armor"] -= 1
        else:
            if game["player_invincible"]:
                game["player_invincible"] = False
                await channel.send("The adrenaline rush saved you from the shot.")
            else:
                game["player_armor"] -= 1
    else:
        await channel.send("*Click*")

    if guild_id not in active_games:
        return

    maybe_spawn_battery(game)

    if await check_solo_game_over(guild, channel, game):
        return

    game["turn"] = "player"
    await announce_solo_player_turn(guild_id)


async def resolve_solo_player_shot(guild: discord.Guild, channel: discord.abc.Messageable, game: dict, shoot_bot: bool):
    guild_id = guild.id
    is_boom = pop_shell(game, lambda: new_full_cylinder(size=6, min_filled=1))

    if is_boom:
        await channel.send("*Boom*")
        if shoot_bot:
            game["bot_armor"] -= 1
        else:
            game["player_armor"] -= 1
    else:
        await channel.send("*Click*")

    maybe_spawn_battery(game)

    if await check_solo_game_over(guild, channel, game):
        return

    game["turn"] = "bot"
    await asyncio.sleep(1.5)
    await run_bot_turn(guild, channel, game)


@bot.tree.command(name="soloroulette", description="Play Roulette against the bot.")
async def soloroulette(interaction: discord.Interaction):
    guild_id = interaction.guild_id
    channel = interaction.channel

    if interaction.guild is None:
        await interaction.response.send_message("This can only be used in a server.", ephemeral=True)
        return

    if not require_game_channel(guild_id, channel.id):
        await interaction.response.send_message("This command can only be used in the designated game channel.", ephemeral=True)
        return

    if guild_id in active_games:
        await interaction.response.send_message("A game is already active in this server.", ephemeral=True)
        return

    cylinder = new_full_cylinder(size=6, min_filled=1)
    filled, blank = cylinder_counts(cylinder)

    active_games[guild_id] = {
        "type": "solo",
        "channel_id": channel.id,
        "player_id": interaction.user.id,
        "player_armor": 3,
        "bot_armor": 3,
        "cylinder": cylinder,
        "inspect_uses": 2,
        "alcohol_used": False,
        "player_invincible": False,
        "battery_available": False,
        "turn": "player",
        "turn_token": 0,
    }

    await interaction.response.send_message("Putting ammo in the revolver...")
    msg = await interaction.original_response()
    await asyncio.sleep(2)
    await msg.edit(content="Spinning the chamber...")
    await asyncio.sleep(2)

    await channel.send(f"{filled} and {blank}, Goodluck.")
    await announce_solo_player_turn(guild_id)


@bot.group(name="s", aliases=["solo"], invoke_without_command=True)
async def solo_group(ctx: commands.Context):
    pass


@solo_group.command(name="shoot")
async def solo_shoot(ctx: commands.Context, *, target: str = None):
    if ctx.guild is None:
        return
    guild_id = ctx.guild.id
    if guild_id not in active_games:
        return

    game = active_games[guild_id]
    if game["type"] != "solo" or ctx.channel.id != game["channel_id"]:
        return
    if ctx.author.id != game["player_id"]:
        return
    if game["turn"] != "player":
        return
    if target is None:
        await ctx.send("You must specify a target: yourself, bot, or a mention.")
        return

    cleaned = target.strip().lower()
    shoot_bot = False
    shoot_self = False

    if cleaned == "bot":
        shoot_bot = True
    elif cleaned in ("yourself", "self", "me"):
        shoot_self = True
    elif ctx.message.mentions:
        mentioned = ctx.message.mentions[0]
        if mentioned.id == bot.user.id:
            shoot_bot = True
        elif mentioned.id == ctx.author.id:
            shoot_self = True
        else:
            await ctx.send("You can only shoot yourself or the bot in this game.")
            return
    else:
        await ctx.send("You can only shoot yourself or the bot in this game.")
        return

    await resolve_solo_player_shot(ctx.guild, ctx.channel, game, shoot_bot)


@solo_group.group(name="action", invoke_without_command=True)
async def solo_action(ctx: commands.Context):
    pass


@solo_action.command(name="inspect")
async def solo_action_inspect(ctx: commands.Context):
    if ctx.guild is None:
        return
    guild_id = ctx.guild.id
    if guild_id not in active_games:
        return

    game = active_games[guild_id]
    if game["type"] != "solo" or ctx.channel.id != game["channel_id"]:
        return
    if ctx.author.id != game["player_id"]:
        return

    if game["inspect_uses"] <= 0:
        await ctx.send(random.choice(INSPECT_NO_USES_MESSAGES))
        return

    if not game["cylinder"]:
        game["cylinder"] = new_full_cylinder(size=6, min_filled=1)

    game["inspect_uses"] -= 1
    parts = [f"{'filled' if v else 'blank'} in chamber {i}" for i, v in enumerate(game["cylinder"], start=1)]
    await ctx.send(f"*({', '.join(parts)})*")


@solo_group.group(name="item", invoke_without_command=True)
async def solo_item(ctx: commands.Context):
    pass


@solo_item.command(name="battery")
async def solo_item_battery(ctx: commands.Context):
    if ctx.guild is None:
        return
    guild_id = ctx.guild.id
    if guild_id not in active_games:
        return

    game = active_games[guild_id]
    if game["type"] != "solo" or ctx.channel.id != game["channel_id"]:
        return
    if ctx.author.id != game["player_id"]:
        return

    if game["player_armor"] > 1 or not game.get("battery_available"):
        await ctx.send(random.choice(BATTERY_INVALID_MESSAGES))
        return

    game["battery_available"] = False

    if random.random() < 0.02:
        await ctx.send("The armor machine explodes, instantly killing you.")
        add_death(game["player_id"])
        del active_games[guild_id]
        return

    game["player_armor"] += 1
    await ctx.send("You used the Battery and gained 1 armor.")
    await ctx.send(armor_line(("Your Armor", game["player_armor"]), ("Bot Armor", game["bot_armor"])))


@solo_item.command(name="alcohol")
async def solo_item_alcohol(ctx: commands.Context):
    if ctx.guild is None:
        return
    guild_id = ctx.guild.id
    if guild_id not in active_games:
        return

    game = active_games[guild_id]
    if game["type"] != "solo" or ctx.channel.id != game["channel_id"]:
        return
    if ctx.author.id != game["player_id"]:
        return

    if game["player_armor"] != 0 or game["alcohol_used"]:
        await ctx.send(random.choice(ALCOHOL_INVALID_MESSAGES))
        return

    game["alcohol_used"] = True
    game["player_invincible"] = True
    await ctx.send("You drink the Alcohol and feel an adrenaline rush.")


# ---------------------------------------------------------------------------
# Economy: %currency, %buy, %give
# ---------------------------------------------------------------------------

@bot.command(name="currency")
async def currency(ctx: commands.Context):
    bucks = get_bucks(ctx.author.id)
    await ctx.send(f"{ctx.author.display_name}, you have {bucks:,} Bucks.")


@bot.command(name="buy")
async def buy(ctx: commands.Context, *, item: str = None):
    if item is None:
        await ctx.send("Usage: %buy (item)")
        return

    key = item.strip().lower()
    if key not in SHOP_ITEMS:
        await ctx.send("That item does not exist in the shop.")
        return

    info = SHOP_ITEMS[key]
    price = info["price"]
    balance = get_bucks(ctx.author.id)

    if balance < price:
        await ctx.send(random.choice(BUY_INSUFFICIENT_MESSAGES))
        return

    add_bucks(ctx.author.id, -price)

    if info["type"] == "flag":
        set_flag(ctx.author.id, info["column"])
    else:
        add_inventory_item(ctx.author.id, key)

    await ctx.send("Successful purchase, pleasure doing business.")
    new_balance = get_bucks(ctx.author.id)
    await ctx.send(f"*You have now {new_balance:,} left in your wallet*")


@bot.command(name="give")
async def give(ctx: commands.Context, amount: int = None, member: discord.Member = None):
    if amount is None or member is None:
        await ctx.send("Usage: %give (amount) @user")
        return
    if amount <= 0:
        await ctx.send("You must give a positive amount.")
        return
    if member.id == ctx.author.id:
        await ctx.send("You cannot give Bucks to yourself.")
        return
    if member.bot:
        await ctx.send("You cannot give Bucks to a bot.")
        return

    balance = get_bucks(ctx.author.id)
    if balance < amount:
        await ctx.send("You do not have enough Bucks.")
        return

    add_bucks(ctx.author.id, -amount)
    add_bucks(member.id, amount)
    await ctx.send(f"{ctx.author.display_name} gave {amount:,} Bucks to {member.display_name}.")


# ---------------------------------------------------------------------------
# %mines (with modes + embed board)
# ---------------------------------------------------------------------------

HIDDEN_EMOJI = "⬜"
SAFE_EMOJI = "💎"
BOMB_EMOJI = "💥"


def build_mines_embed(user: discord.abc.User, game: dict, final: bool = False) -> discord.Embed:
    size = game["size"]
    board = game["board"]
    revealed = game["revealed"]

    rows = []
    for r in range(size):
        row_tiles = []
        for c in range(size):
            index = r * size + c
            if index in revealed:
                row_tiles.append(BOMB_EMOJI if board[index] else SAFE_EMOJI)
            elif final and board[index]:
                row_tiles.append(BOMB_EMOJI)
            else:
                row_tiles.append(HIDDEN_EMOJI)
        rows.append("".join(row_tiles))

    winnings = int(game["wager"] * game["multiplier"])
    color = discord.Color.red() if final else discord.Color.green()

    embed = discord.Embed(title=f"💣 Mines - {game['mode'].title()}", description="\n".join(rows), color=color)
    embed.add_field(name="Wager", value=f"{game['wager']:,} Bucks", inline=True)
    embed.add_field(name="Multiplier", value=f"{game['multiplier']:.3f}x", inline=True)
    embed.add_field(name="Potential Winnings", value=f"{winnings:,} Bucks", inline=True)
    if not final:
        embed.set_footer(text=f"{user.display_name} • %reveal (tile) or %cashout")
    return embed


@bot.command(name="mines")
async def mines(ctx: commands.Context, amount: int = None, mode: str = None):
    if amount is None or amount <= 0 or mode is None:
        await ctx.send("Usage: %mines (amount) (easy/medium/hard)")
        return

    mode = mode.strip().lower()
    if mode not in MINES_MODES:
        await ctx.send("Invalid mode. Choose easy, medium, or hard.")
        return

    if ctx.author.id in active_mines:
        await ctx.send("You already have an active Mines game. Use %reveal (tile) or %cashout.")
        return

    balance = get_bucks(ctx.author.id)
    if balance < amount:
        await ctx.send("You do not have enough Bucks to wager that amount.")
        return

    add_bucks(ctx.author.id, -amount)

    config = MINES_MODES[mode]
    size = config["size"]
    bomb_count = config["bombs"]
    total_tiles = size * size

    board = [False] * total_tiles
    for pos in random.sample(range(total_tiles), bomb_count):
        board[pos] = True

    game = {
        "wager": amount,
        "mode": mode,
        "size": size,
        "board": board,
        "revealed": set(),
        "multiplier": 1.0,
        "channel_id": ctx.channel.id,
        "message_id": None,
    }
    active_mines[ctx.author.id] = game

    embed = build_mines_embed(ctx.author, game)
    msg = await ctx.send(embed=embed)
    game["message_id"] = msg.id


async def update_mines_message(ctx_or_channel, user: discord.abc.User, game: dict, final: bool = False):
    channel = ctx_or_channel
    embed = build_mines_embed(user, game, final=final)
    try:
        msg = await channel.fetch_message(game["message_id"])
        await msg.edit(embed=embed)
    except (discord.NotFound, discord.HTTPException):
        await channel.send(embed=embed)


@bot.command(name="reveal")
async def reveal(ctx: commands.Context, tile: int = None):
    if ctx.author.id not in active_mines:
        return

    game = active_mines[ctx.author.id]
    if ctx.channel.id != game["channel_id"]:
        return

    total_tiles = game["size"] * game["size"]
    if tile is None or tile < 1 or tile > total_tiles:
        await ctx.send(f"Please choose a tile between 1 and {total_tiles}.")
        return

    index = tile - 1
    if index in game["revealed"]:
        await ctx.send("That tile has already been revealed.")
        return

    if game["board"][index]:
        game["revealed"].add(index)
        await update_mines_message(ctx.channel, ctx.author, game, final=True)
        await ctx.send(f"That tile was a bomb. You lost your wager of {game['wager']:,} Bucks.")
        del active_mines[ctx.author.id]
        return

    game["revealed"].add(index)
    game["multiplier"] *= 1.2
    await update_mines_message(ctx.channel, ctx.author, game)


@bot.command(name="cashout")
async def cashout(ctx: commands.Context):
    if ctx.author.id not in active_mines:
        await ctx.send("You do not have an active Mines game.")
        return

    game = active_mines[ctx.author.id]
    if ctx.channel.id != game["channel_id"]:
        return

    winnings = int(game["wager"] * game["multiplier"])
    add_bucks(ctx.author.id, winnings)
    await update_mines_message(ctx.channel, ctx.author, game, final=True)
    await ctx.send(f"You cashed out and received {winnings:,} Bucks.")
    del active_mines[ctx.author.id]


# ---------------------------------------------------------------------------
# %coinflip
# ---------------------------------------------------------------------------

@bot.command(name="coinflip")
async def coinflip(ctx: commands.Context, side: str = None, amount: int = None):
    if side is None or amount is None:
        await ctx.send("Usage: %coinflip h/t (amount)")
        return

    side = side.lower()
    if side not in ("h", "t"):
        await ctx.send("Usage: %coinflip h/t (amount)")
        return
    if amount <= 0:
        await ctx.send("You must wager a positive amount.")
        return

    balance = get_bucks(ctx.author.id)
    if balance < amount:
        await ctx.send("You do not have enough Bucks to wager that amount.")
        return

    result = random.choice(("h", "t"))
    if result == side:
        add_bucks(ctx.author.id, amount)
        await ctx.send(f"The coin landed on {'heads' if result == 'h' else 'tails'}. You won {amount:,} Bucks!")
    else:
        add_bucks(ctx.author.id, -amount)
        await ctx.send(random.choice(COINFLIP_LOSS_MESSAGES))


# ---------------------------------------------------------------------------
# %steal
# ---------------------------------------------------------------------------

@bot.command(name="steal")
async def steal(ctx: commands.Context, member: discord.Member = None):
    if member is None:
        await ctx.send("Usage: %steal @user")
        return
    if member.id == ctx.author.id:
        await ctx.send("You cannot steal from yourself.")
        return
    if member.bot:
        await ctx.send("You cannot steal from a bot.")
        return
    if not has_handgun(ctx.author.id):
        await ctx.send("You need to own a Handgun to steal.")
        return

    last_steal = get_last_steal(ctx.author.id)
    now = time.time()
    elapsed = now - last_steal

    if elapsed < STEAL_COOLDOWN_SECONDS:
        remaining = int(STEAL_COOLDOWN_SECONDS - elapsed)
        minutes, seconds = divmod(remaining, 60)
        time_left = f"{minutes}m {seconds}s"
        message = random.choice([
            f"Nope, you need to wait {time_left} to steal again.",
            f"Your greedy as hell, wait for {time_left} to steal again you greedy imbecile.",
        ])
        await ctx.send(message)
        return

    set_last_steal(ctx.author.id, now)

    if random.random() < STEAL_CHANCE:
        victim_balance = get_bucks(member.id)
        if victim_balance <= 0:
            await ctx.send(f"{member.display_name} has nothing worth stealing.")
            return
        stolen = random.randint(STEAL_MIN, min(STEAL_MAX, victim_balance))
        add_bucks(member.id, -stolen)
        add_bucks(ctx.author.id, stolen)
        await ctx.send(f"You successfully stole {stolen:,} Bucks from {member.display_name}!")
    else:
        await ctx.send(random.choice(STEAL_FAIL_MESSAGES))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    TOKEN = os.getenv("DISCORD_TOKEN")
    if not TOKEN:
        raise RuntimeError("DISCORD_TOKEN environment variable is not set.")
    bot.run(TOKEN)
