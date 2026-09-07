import os
import random
import sqlite3
import asyncio
from datetime import datetime, timedelta

import discord
from discord.ext import commands
from discord import app_commands


# ============================================================
# putang ina configuration nato
# ============================================================

TOKEN = os.getenv("DISCORD_TOKEN")

BOT_VERSION = "1.5V"
CREATOR = "jestre.py"
DB_NAME = "roulette.db"

PREFIX = "buck"

STARTING_BUCKS = 0

STEAL_COOLDOWN = 30 * 60
STEAL_MIN = 500
STEAL_MAX = 100_000

ROULETTE_REWARD = 50_000
MULTIPLIER_REWARD = 2

MAX_ARMOR_SOLO = 3
MAX_ARMOR_BUCKSHOT = 4

GAME_JOIN_TIME = 30


# ============================================================
# baby buckshot joe
# ============================================================

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(
    command_prefix=PREFIX,
    intents=intents
)


# ============================================================
# random data and shit
# ============================================================

db = sqlite3.connect(DB_NAME, check_same_thread=False)
cursor = db.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    bucks INTEGER DEFAULT 0,
    kills INTEGER DEFAULT 0,
    deaths INTEGER DEFAULT 0,
    multiplier INTEGER DEFAULT 0,
    handgun INTEGER DEFAULT 0,
    diamonds INTEGER DEFAULT 0,
    emeralds INTEGER DEFAULT 0,
    rubies INTEGER DEFAULT 0,
    sapphires INTEGER DEFAULT 0,
    last_steal REAL DEFAULT 0
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS guild_settings (
    guild_id INTEGER PRIMARY KEY,
    game_channel_id INTEGER
)
""")

db.commit()


# ============================================================
# helping main database
# ============================================================

def ensure_user(user_id: int):
    cursor.execute(
        "INSERT OR IGNORE INTO users (user_id) VALUES (?)",
        (user_id,)
    )
    db.commit()


def get_user(user_id: int):
    ensure_user(user_id)

    cursor.execute(
        "SELECT * FROM users WHERE user_id = ?",
        (user_id,)
    )

    return cursor.fetchone()


def get_bucks(user_id: int):
    ensure_user(user_id)

    cursor.execute(
        "SELECT bucks FROM users WHERE user_id = ?",
        (user_id,)
    )

    return cursor.fetchone()[0]


def add_bucks(user_id: int, amount: int):
    ensure_user(user_id)

    cursor.execute(
        "UPDATE users SET bucks = bucks + ? WHERE user_id = ?",
        (amount, user_id)
    )

    db.commit()


def remove_bucks(user_id: int, amount: int):
    ensure_user(user_id)

    cursor.execute(
        "UPDATE users SET bucks = MAX(0, bucks - ?) WHERE user_id = ?",
        (amount, user_id)
    )

    db.commit()


def add_kill(user_id: int):
    ensure_user(user_id)

    cursor.execute(
        "UPDATE users SET kills = kills + 1 WHERE user_id = ?",
        (user_id,)
    )

    db.commit()


def add_death(user_id: int):
    ensure_user(user_id)

    cursor.execute(
        "UPDATE users SET deaths = deaths + 1 WHERE user_id = ?",
        (user_id,)
    )

    db.commit()


def owns_item(user_id: int, item: str):
    ensure_user(user_id)

    cursor.execute(
        f"SELECT {item} FROM users WHERE user_id = ?",
        (user_id,)
    )

    result = cursor.fetchone()

    return result and result[0] > 0


def give_item(user_id: int, item: str):
    ensure_user(user_id)

    cursor.execute(
        f"UPDATE users SET {item} = {item} + 1 WHERE user_id = ?",
        (user_id,)
    )

    db.commit()


def get_game_channel(guild_id: int):
    cursor.execute(
        "SELECT game_channel_id FROM guild_settings WHERE guild_id = ?",
        (guild_id,)
    )

    result = cursor.fetchone()

    return result[0] if result else None


# ============================================================
# EMBEDS
# ============================================================

def black_embed(title: str, description: str = ""):
    embed = discord.Embed(
        title=title,
        description=description,
        color=discord.Color.dark_grey()
    )

    embed.set_footer(text=f"Roulette Bot • Version {BOT_VERSION}")

    return embed


# ============================================================
# THE GAME BRO LETS GOOOO
# ============================================================

active_normal_games = {}
active_solo_games = {}
active_buckshot_games = {}


# ============================================================
# check channel testeet
# ============================================================

async def check_game_channel(interaction: discord.Interaction):
    configured = get_game_channel(interaction.guild.id)

    if configured is None:
        await interaction.response.send_message(
            "No game channel has been configured. An administrator must use `/setchannelgm` first.",
            ephemeral=True
        )
        return False

    if interaction.channel.id != configured:
        await interaction.response.send_message(
            f"Games can only be played in <#{configured}>.",
            ephemeral=True
        )
        return False

    return True


# ============================================================
# perms config
# ============================================================

async def mute_player(channel, member):
    try:
        overwrite = channel.overwrites_for(member)
        overwrite.send_messages = False

        await channel.set_permissions(
            member,
            overwrite=overwrite,
            reason="Roulette player eliminated"
        )
    except discord.Forbidden:
        pass


async def unmute_player(channel, member):
    try:
        overwrite = channel.overwrites_for(member)
        overwrite.send_messages = None

        await channel.set_permissions(
            member,
            overwrite=overwrite,
            reason="Roulette game finished"
        )
    except discord.Forbidden:
        pass


# ============================================================
# CHAMBER HELPERS
# ============================================================

def create_revolver(filled: int, blank: int):
    chambers = ["filled"] * filled + ["blank"] * blank
    random.shuffle(chambers)
    return chambers


def chamber_text(chambers):
    parts = []

    for i, chamber in enumerate(chambers, 1):
        parts.append(
            f"{'filled' if chamber == 'filled' else 'blank'} on chamber {i}"
        )

    return ", ".join(parts)


def shot_result(chambers):
    if not chambers:
        return None

    return chambers.pop(0)


# ============================================================
# NORMAL ROULETTE
# ============================================================

normal_group = app_commands.Group(
    name="normal",
    description="Normal Roulette commands."
)


@normal_group.command(
    name="roulette",
    description="Start a multiplayer Normal Roulette game."
)
async def normal_roulette(interaction: discord.Interaction):

    if not await check_game_channel(interaction):
        return

    guild_id = interaction.guild.id

    if guild_id in active_normal_games:
        await interaction.response.send_message(
            "There is already an active Normal Roulette game.",
            ephemeral=True
        )
        return

    game = {
        "players": [],
        "channel": interaction.channel,
        "filled": 1,
        "blank": 5,
        "chambers": create_revolver(1, 5),
        "running": False,
        "message": None
    }

    active_normal_games[guild_id] = game

    embed = black_embed(
        "🎰 Normal Roulette",
        "React with ☑️ within **30 seconds** to join the game."
    )

    await interaction.response.send_message(embed=embed)

    message = await interaction.original_response()

    game["message"] = message

    await message.add_reaction("☑️")

    await asyncio.sleep(GAME_JOIN_TIME)

    try:
        message = await interaction.channel.fetch_message(message.id)
    except discord.NotFound:
        active_normal_games.pop(guild_id, None)
        return

    joined = []

    for reaction in message.reactions:
        if str(reaction.emoji) == "☑️":
            async for user in reaction.users():
                if not user.bot:
                    joined.append(user)

    # Remove duplicates
    unique_players = {}

    for user in joined:
        unique_players[user.id] = user

    players = list(unique_players.values())

    if len(players) < 2:
        await interaction.channel.send(
            "Not enough players joined the game. At least **2 players** are required."
        )

        active_normal_games.pop(guild_id, None)
        return

    game["players"] = players
    game["running"] = True

    await interaction.channel.send(
        "Putting ammo in the revolver..."
    )

    await asyncio.sleep(1)

    spinning = await interaction.channel.send(
        "Spinning the chamber..."
    )

    await asyncio.sleep(1)

    await spinning.edit(
        content="1 filled chamber and 5 blank chambers, Goodluck."
    )

    await normal_turn(guild_id)


async def normal_turn(guild_id: int):

    game = active_normal_games.get(guild_id)

    if not game or not game["running"]:
        return

    players = game["players"]

    if len(players) <= 1:
        await finish_normal_game(guild_id)
        return

    player = random.choice(players)

    await game["channel"].send(
        f"**{player.display_name}**, two choices: "
        f"shoot yourself, or shoot someone..."
    )

    game["current_player"] = player.id

    def check(message):
        return (
            message.channel.id == game["channel"].id
            and message.author.id == player.id
            and message.content.lower().startswith("buck shoot")
        )

    try:
        message = await bot.wait_for(
            "message",
            timeout=60,
            check=check
        )
    except asyncio.TimeoutError:
        await game["channel"].send(
            f"{player.mention} took too long. The turn is skipped."
        )
        return await normal_turn(guild_id)

    content = message.content.split()

    if len(content) < 3:
        return await normal_turn(guild_id)

    target_id = None

    if message.mentions:
        target_id = message.mentions[0].id

    if target_id is None:
        await game["channel"].send(
            "You need to mention a player to shoot."
        )
        return await normal_turn(guild_id)

    target = next(
        (p for p in players if p.id == target_id),
        None
    )

    if target is None:
        await game["channel"].send(
            "That player isn't in the active game."
        )
        return await normal_turn(guild_id)

    if not game["chambers"]:
        game["chambers"] = create_revolver(
            game["filled"],
            game["blank"]
        )

    result = shot_result(game["chambers"])

    if result == "filled":
        await game["channel"].send("*Boom*")

        players.remove(target)

        add_kill(player.id)
        add_death(target.id)

        await mute_player(game["channel"], target)

        await game["channel"].send(
            f"**{target.display_name} was eliminated by "
            f"{player.display_name}.**"
        )

        if game["blank"] > 0:
            game["blank"] -= 1
            game["filled"] += 1

        if len(players) <= 1:
            await finish_normal_game(guild_id)
            return

    else:
        await game["channel"].send("*Click*")

    await asyncio.sleep(1)

    await normal_turn(guild_id)


async def finish_normal_game(guild_id):

    game = active_normal_games.get(guild_id)

    if not game:
        return

    game["running"] = False

    channel = game["channel"]

    if game["players"]:
        winner = game["players"][0]

        add_bucks(
            winner.id,
            ROULETTE_REWARD * (
                MULTIPLIER_REWARD
                if owns_item(winner.id, "multiplier")
                else 1
            )
        )

        reward = (
            ROULETTE_REWARD * 2
            if owns_item(winner.id, "multiplier")
            else ROULETTE_REWARD
        )

        await channel.send(
            f"🏆 **{winner.display_name} wins Normal Roulette!**\n"
            f"💰 Reward: **{reward:,} Bucks**"
        )

    for member in game["players"]:
        await unmute_player(channel, member)

    # Restore every player that participated
    active_normal_games.pop(guild_id, None)


# ============================================================
# SOLO ROULETTE
# ============================================================

solo_group = app_commands.Group(
    name="solo",
    description="Solo Roulette commands."
)


@solo_group.command(
    name="roulette",
    description="Play Solo Roulette against the bot."
)
async def solo_roulette(interaction: discord.Interaction):

    if not await check_game_channel(interaction):
        return

    guild_id = interaction.guild.id
    user = interaction.user

    if guild_id in active_solo_games:
        await interaction.response.send_message(
            "There is already an active Solo Roulette game.",
            ephemeral=True
        )
        return

    game = {
        "player": user,
        "channel": interaction.channel,
        "player_armor": 3,
        "bot_armor": 3,
        "chambers": create_revolver(1, 5),
        "filled": 1,
        "blank": 5,
        "inspect": 2,
        "alcohol": 1,
        "battery": False,
        "adrenaline": False,
        "running": True,
        "turn": "player"
    }

    active_solo_games[guild_id] = game

    await interaction.response.send_message(
        "Putting ammo in the revolver..."
    )

    await asyncio.sleep(1)

    msg = await interaction.channel.send(
        "Spinning the chamber..."
    )

    await asyncio.sleep(1)

    await msg.edit(
        content="1 filled chamber and 5 blank chambers, Goodluck."
    )

    await solo_turn(guild_id)


async def solo_turn(guild_id):

    game = active_solo_games.get(guild_id)

    if not game or not game["running"]:
        return

    player = game["player"]
    channel = game["channel"]

    if game["player_armor"] <= 0 and game["bot_armor"] <= 0:
        return await finish_solo_game(guild_id, None)

    if game["player_armor"] <= 0:
        return await finish_solo_game(guild_id, "bot")

    if game["bot_armor"] <= 0:
        return await finish_solo_game(guild_id, "player")

    if not game["chambers"]:
        game["chambers"] = create_revolver(
            game["filled"],
            game["blank"]
        )

    if game["turn"] == "player":

        await channel.send(
            f"**{player.display_name}**, two choices: "
            f"shoot yourself, or shoot the bot..."
        )

        def check(message):
            if message.author.id != player.id:
                return False

            if message.channel.id != channel.id:
                return False

            text = message.content.lower()

            return (
                text.startswith("buck s shoot")
                or text.startswith("buck solo shoot")
            )

        try:
            message = await bot.wait_for(
                "message",
                timeout=60,
                check=check
            )
        except asyncio.TimeoutError:
            await channel.send(
                "You took too long. Turn skipped."
            )
            game["turn"] = "bot"
            return await solo_turn(guild_id)

        text = message.content.lower()

        target_self = (
            "yourself" in text
            or "self" in text
        )

        result = shot_result(game["chambers"])

        if result == "blank":
            await channel.send("*Click*")
        else:
            await channel.send("*Boom*")

            target = (
                "player"
                if target_self
                else "bot"
            )

            if target == "player":
                if game["adrenaline"]:
                    await channel.send(
                        "The adrenaline rush protected you!"
                    )
                else:
                    game["player_armor"] -= 1
                    await channel.send(
                        f"🛡️ Your armor: "
                        f"**{max(game['player_armor'], 0)}/3**"
                    )
            else:
                game["bot_armor"] -= 1
                await channel.send(
                    f"🤖 Bot armor: "
                    f"**{max(game['bot_armor'], 0)}/3**"
                )

        game["adrenaline"] = False
        game["turn"] = "bot"

        return await solo_turn(guild_id)

    # ========================================================
    # BOT TURN
    # ========================================================

    await asyncio.sleep(random.uniform(1, 2))

    lines = [
        "Do you want to see the light?",
        "This may be your last day.",
        "I'm sorry.",
        "I'm taking the risk.",
        "I don't know what to expect."
    ]

    await channel.send(
        f"*{random.choice(lines)}*"
    )

    await asyncio.sleep(1)

    shoot_self = random.choice([True, False])

    result = shot_result(game["chambers"])

    if result == "blank":
        await channel.send("*Click*")
    else:
        await channel.send("*Boom*")

        if shoot_self:
            game["bot_armor"] -= 1

            await channel.send(
                f"🤖 Bot armor: "
                f"**{max(game['bot_armor'], 0)}/3**"
            )
        else:
            if game["adrenaline"]:
                await channel.send(
                    "Your adrenaline rush protected you!"
                )
            else:
                game["player_armor"] -= 1

                await channel.send(
                    f"🛡️ Your armor: "
                    f"**{max(game['player_armor'], 0)}/3**"
                )

    game["adrenaline"] = False
    game["turn"] = "player"

    await solo_turn(guild_id)


async def finish_solo_game(guild_id, winner):

    game = active_solo_games.get(guild_id)

    if not game:
        return

    game["running"] = False

    channel = game["channel"]
    player = game["player"]

    if winner == "player":

        add_kill(player.id)

        reward = (
            ROULETTE_REWARD * 2
            if owns_item(player.id, "multiplier")
            else ROULETTE_REWARD
        )

        add_bucks(player.id, reward)

        await channel.send(
            f"🏆 **{player.display_name} defeated the bot!**\n"
            f"💰 Reward: **{reward:,} Bucks**"
        )

    elif winner == "bot":

        add_death(player.id)

        await channel.send(
            f"💀 **{player.display_name} was eliminated.**"
        )

    active_solo_games.pop(guild_id, None)


# ============================================================
# BUCKSHOT ROULETTE
# ============================================================

buckshot_group = app_commands.Group(
    name="buckshot",
    description="Buckshot Roulette commands."
)


@buckshot_group.command(
    name="roulette",
    description="Challenge another player to Buckshot Roulette."
)
@app_commands.describe(user="The second player.")
async def buckshot_roulette(
    interaction: discord.Interaction,
    user: discord.Member
):

    if not await check_game_channel(interaction):
        return

    guild_id = interaction.guild.id

    if guild_id in active_buckshot_games:
        await interaction.response.send_message(
            "There is already an active Buckshot Roulette game.",
            ephemeral=True
        )
        return

    if user.bot:
        await interaction.response.send_message(
            "You cannot challenge a bot.",
            ephemeral=True
        )
        return

    if user.id == interaction.user.id:
        await interaction.response.send_message(
            "You need to choose another player.",
            ephemeral=True
        )
        return

    game = {
        "players": [
            interaction.user,
            user
        ],
        "channel": interaction.channel,
        "armor": {
            interaction.user.id: 4,
            user.id: 4
        },
        "running": True,
        "turn": random.choice([
            interaction.user.id,
            user.id
        ]),
        "chambers": [],
        "filled": 0,
        "blank": 0
    }

    active_buckshot_games[guild_id] = game

    await interaction.response.send_message(
        f"🔫 **Buckshot Roulette**\n"
        f"{interaction.user.mention} vs {user.mention}"
    )

    await buckshot_round(guild_id)


async def buckshot_round(guild_id):

    game = active_buckshot_games.get(guild_id)

    if not game or not game["running"]:
        return

    channel = game["channel"]

    alive = [
        p for p in game["players"]
        if game["armor"][p.id] > 0
    ]

    if len(alive) <= 1:

        winner = alive[0] if alive else None

        if winner:
            reward = (
                ROULETTE_REWARD * 2
                if owns_item(winner.id, "multiplier")
                else ROULETTE_REWARD
            )

            add_bucks(winner.id, reward)

            await channel.send(
                f"🏆 **{winner.display_name} wins Buckshot Roulette!**\n"
                f"💰 Reward: **{reward:,} Bucks**"
            )

        for p in game["players"]:
            await unmute_player(channel, p)

        active_buckshot_games.pop(guild_id, None)
        return

    # Randomly determine ammunition
    total_ammo = random.randint(1, 6)

    filled = random.randint(0, total_ammo)

    # Ensure there is at least one filled and one blank
    if total_ammo >= 2:
        if filled == 0:
            filled = 1
        if filled == total_ammo:
            filled = total_ammo - 1
    else:
        filled = random.choice([0, 1])

    blank = total_ammo - filled

    game["filled"] = filled
    game["blank"] = blank

    game["chambers"] = (
        ["filled"] * filled
        + ["blank"] * blank
    )

    random.shuffle(game["chambers"])

    await channel.send(
        f"🔫 Inserting ammunition...\n"
        f"**{filled} filled ammo and {blank} blanks.**"
    )

    await asyncio.sleep(1)

    await channel.send(
        f"*{random.choice(['Goodluck to you two.', 'Only one can survive.'])}*"
    )

    await asyncio.sleep(1)

    await buckshot_turn(guild_id)


async def buckshot_turn(guild_id):

    game = active_buckshot_games.get(guild_id)

    if not game or not game["running"]:
        return

    channel = game["channel"]

    alive = [
        p for p in game["players"]
        if game["armor"][p.id] > 0
    ]

    if len(alive) <= 1:
        return await buckshot_round(guild_id)

    current = next(
        p for p in alive
        if p.id == game["turn"]
    )

    other = next(
        p for p in alive
        if p.id != current.id
    )

    await channel.send(
        f"**{current.display_name}**, "
        f"choose: shoot yourself or shoot {other.display_name}."
    )

    def check(message):
        return (
            message.author.id == current.id
            and message.channel.id == channel.id
            and (
                message.content.lower().startswith("buck s shoot")
                or message.content.lower().startswith("buck solo shoot")
                or message.content.lower().startswith("buck shoot")
            )
        )

    try:
        message = await bot.wait_for(
            "message",
            timeout=60,
            check=check
        )
    except asyncio.TimeoutError:

        await channel.send(
            f"{current.mention} took too long. Turn skipped."
        )

        game["turn"] = other.id
        return await buckshot_turn(guild_id)

    text = message.content.lower()

    target = current

    if message.mentions:
        mentioned = message.mentions[0]

        if mentioned.id == other.id:
            target = other
        elif mentioned.id == current.id:
            target = current

    elif "yourself" not in text:
        target = other

    if not game["chambers"]:
        await buckshot_round(guild_id)
        return

    result = game["chambers"].pop(0)

    if result == "filled":

        await channel.send("*Boom*")

        game["armor"][target.id] -= 1

        add_kill(current.id)
        add_death(target.id)

        await channel.send(
            f"🛡️ **{target.display_name}'s armor:** "
            f"{max(game['armor'][target.id], 0)}/4"
        )

        if game["armor"][target.id] <= 0:

            await mute_player(channel, target)

            await channel.send(
                f"💀 **{target.display_name} was eliminated by "
                f"{current.display_name}.**"
            )

    else:
        await channel.send("*Click*")

    # Change turn
    game["turn"] = other.id

    await asyncio.sleep(1)

    if not game["chambers"]:
        return await buckshot_round(guild_id)

    await buckshot_turn(guild_id)


# ============================================================
# SOLO ITEMS
# ============================================================

async def solo_command_restriction(ctx):
    guild_id = ctx.guild.id

    game = active_solo_games.get(guild_id)

    if not game:
        await ctx.send(
            "Required to be in game to use this command."
        )
        return None

    if game["player"].id != ctx.author.id:
        await ctx.send(
            "Required to be in game to use this command."
        )
        return None

    return game


@bot.command(name="s")
async def buck_s(ctx, action=None, item=None):

    if action is None:
        return

    game = await solo_command_restriction(ctx)

    if not game:
        return

    if action.lower() == "action" and item:
        if item.lower() == "inspect":
            await inspect_action(ctx, game)
            return

    if action.lower() == "item" and item:
        if item.lower() == "battery":
            await battery_action(ctx, game)
            return

        if item.lower() == "alcohol":
            await alcohol_action(ctx, game)
            return


@bot.command(name="solo")
async def buck_solo(ctx, action=None, item=None):

    game = await solo_command_restriction(ctx)

    if not game:
        return

    if action is None:
        return

    if action.lower() == "action" and item:
        if item.lower() == "inspect":
            await inspect_action(ctx, game)
            return

    if action.lower() == "item" and item:
        if item.lower() == "battery":
            await battery_action(ctx, game)
            return

        if item.lower() == "alcohol":
            await alcohol_action(ctx, game)
            return


async def inspect_action(ctx, game):

    if game["turn"] != "player":
        await ctx.send(
            "It isn't your turn."
        )
        return

    if game["inspect"] <= 0:

        responses = [
            "You trying to cheat?",
            "Oi, i wont do that if i were you."
        ]

        await ctx.send(random.choice(responses))
        return

    game["inspect"] -= 1

    await ctx.send(
        f"*({chamber_text(game['chambers'])})*"
    )


async def battery_action(ctx, game):

    if game["turn"] != "player":
        await ctx.send(
            "It isn't your turn."
        )
        return

    if game["battery"] is False:
        await ctx.send(
            random.choice([
                "Are you trying to fix that thing?",
                "What are you, a technician?"
            ])
        )
        return

    if game["player_armor"] not in (0, 1):
        await ctx.send(
            random.choice([
                "Are you trying to fix that thing?",
                "What are you, a technician?"
            ])
        )
        return

    game["battery"] = False

    # 2% malfunction
    if random.random() < 0.02:

        game["player_armor"] = 0

        await ctx.send(
            "💥 The armor machine exploded!"
        )

        await finish_solo_game(
            ctx.guild.id,
            "bot"
        )

        return

    game["player_armor"] += 1

    await ctx.send(
        f"🔋 Battery used.\n"
        f"🛡️ Armor restored to **{game['player_armor']}/3**."
    )


async def alcohol_action(ctx, game):

    if game["turn"] != "player":
        await ctx.send(
            "It isn't your turn."
        )
        return

    if game["alcohol"] <= 0:
        await ctx.send(
            random.choice([
                "Want a refill? kill me first.",
                "Too bad, you better win this if you want to drink more."
            ])
        )
        return

    if game["player_armor"] != 0:
        await ctx.send(
            random.choice([
                "Want a refill? kill me first.",
                "Too bad, you better win this if you want to drink more."
            ])
        )
        return

    game["alcohol"] -= 1
    game["adrenaline"] = True

    await ctx.send(
        "🍺 **Adrenaline rush activated.**\n"
        "You are invincible on your next turn."
    )


# ============================================================
# INFORMATION
# ============================================================

@bot.tree.command(
    name="information",
    description="Display information about the bot."
)
async def information(interaction: discord.Interaction):

    latency = round(bot.latency * 1000)

    embed = black_embed(
        "ℹ️ Bot Information",
        f"**Current Version:** {BOT_VERSION}\n"
        f"**Creator:** {CREATOR}\n"
        f"**Latency:** {latency}ms"
    )

    await interaction.response.send_message(
        embed=embed
    )


# ============================================================
# SET GAME CHANNEL
# ============================================================

@bot.tree.command(
    name="setchannelgm",
    description="Set the channel where roulette games are played."
)
@app_commands.describe(channel="The game channel.")
@app_commands.checks.has_permissions(manage_channels=True)
async def setchannelgm(
    interaction: discord.Interaction,
    channel: discord.TextChannel
):

    cursor.execute("""
    INSERT INTO guild_settings (guild_id, game_channel_id)
    VALUES (?, ?)
    ON CONFLICT(guild_id)
    DO UPDATE SET game_channel_id = excluded.game_channel_id
    """, (
        interaction.guild.id,
        channel.id
    ))

    db.commit()

    await interaction.response.send_message(
        f"🎰 Game channel successfully set to {channel.mention}."
    )


# ============================================================
# SHOP
# ============================================================

SHOP_ITEMS = {
    "rewards multiplier": {
        "price": 250_000,
        "database": "multiplier"
    },

    "handgun": {
        "price": 300_000,
        "database": "handgun"
    },

    "diamond": {
        "price": 50_000,
        "database": "diamonds"
    },

    "emerald": {
        "price": 50_000,
        "database": "emeralds"
    },

    "ruby": {
        "price": 50_000,
        "database": "rubies"
    },

    "sapphire": {
        "price": 50_000,
        "database": "sapphires"
    }
}


@bot.tree.command(
    name="shop",
    description="View the Bucks shop."
)
async def shop(interaction: discord.Interaction):

    embed = black_embed(
        "🛒 Bucks Shop",
        "Use `buck buy (item)` to purchase an item."
    )

    embed.add_field(
        name="Rewards Multiplier (2×)",
        value="250,000 Bucks",
        inline=False
    )

    embed.add_field(
        name="Handgun",
        value="300,000 Bucks",
        inline=False
    )

    embed.add_field(
        name="💎 Gems",
        value=(
            "Diamond — 50,000 Bucks\n"
            "Emerald — 50,000 Bucks\n"
            "Ruby — 50,000 Bucks\n"
            "Sapphire — 50,000 Bucks\n"
            "Gem prices can be expanded up to 5,000,000 Bucks."
        ),
        inline=False
    )

    await interaction.response.send_message(
        embed=embed
    )


@bot.command(name="buy")
async def buy(ctx, *, item_name=None):

    if not item_name:
        await ctx.send(
            "Please specify an item to purchase."
        )
        return

    item_name = item_name.lower().strip()

    item = SHOP_ITEMS.get(item_name)

    if not item:
        await ctx.send(
            "That item isn't available in the shop."
        )
        return

    balance = get_bucks(ctx.author.id)

    if balance < item["price"]:

        responses = [
            "Get rich before you buy something mate.",
            "Poor ass, get a job or something",
            "Sorry, we dont have a dollar to spare to you",
            "Get money first, poor idiot."
        ]

        await ctx.send(random.choice(responses))
        return

    # Prevent duplicate permanent items
    if item["database"] in [
        "multiplier",
        "handgun"
    ] and owns_item(
        ctx.author.id,
        item["database"]
    ):
        await ctx.send(
            "You already own this item."
        )
        return

    remove_bucks(
        ctx.author.id,
        item["price"]
    )

    give_item(
        ctx.author.id,
        item["database"]
    )

    await ctx.send(
        "Successful purchase, pleasure doing business.\n"
        f"*You have now {get_bucks(ctx.author.id):,} Bucks left in your wallet*"
    )


# ============================================================
# CURRENCY
# ============================================================

@bot.command(name="currency")
async def currency(ctx):

    balance = get_bucks(ctx.author.id)

    await ctx.send(
        f"💰 **{ctx.author.display_name}'s Wallet**\n"
        f"**{balance:,} Bucks**"
    )


# ============================================================
# GIVE
# ============================================================

@bot.command(name="give")
async def give(ctx, amount: int = None, user: discord.Member = None):

    if amount is None or user is None:
        await ctx.send(
            "Usage: `buck give (amount) (user)`"
        )
        return

    if amount <= 0:
        await ctx.send(
            "Amount must be greater than 0."
        )
        return

    if user.bot:
        await ctx.send(
            "You cannot give Bucks to a bot."
        )
        return

    if user.id == ctx.author.id:
        await ctx.send(
            "You cannot give Bucks to yourself."
        )
        return

    balance = get_bucks(ctx.author.id)

    if balance < amount:
        await ctx.send(
            "You don't have enough Bucks."
        )
        return

    remove_bucks(ctx.author.id, amount)
    add_bucks(user.id, amount)

    await ctx.send(
        f"💸 {ctx.author.mention} gave **{amount:,} Bucks** "
        f"to {user.mention}."
    )


# ============================================================
# COINFLIP
# ============================================================

@bot.command(name="coinflip")
async def coinflip(ctx, first=None, second=None):

    # Supports:
    # buck coinflip h 100
    # buck coinflip 100 h

    if first is None or second is None:
        await ctx.send(
            "Usage: `buck coinflip h (amount)` or "
            "`buck coinflip t (amount)`"
        )
        return

    choice = None
    amount = None

    if first.lower() in ("h", "t"):
        choice = first.lower()

        try:
            amount = int(second)
        except ValueError:
            pass

    else:
        try:
            amount = int(first)
        except ValueError:
            pass

        if second.lower() in ("h", "t"):
            choice = second.lower()

    if choice not in ("h", "t") or amount is None:
        await ctx.send(
            "Usage: `buck coinflip h (amount)`"
        )
        return

    if amount <= 0:
        await ctx.send(
            "Your wager must be greater than 0."
        )
        return

    balance = get_bucks(ctx.author.id)

    if balance < amount:
        await ctx.send(
            "You don't have enough Bucks."
        )
        return

    remove_bucks(ctx.author.id, amount)

    result = random.choice(["h", "t"])

    if result == choice:

        add_bucks(ctx.author.id, amount * 2)

        await ctx.send(
            f"🪙 **{result.upper()}**\n"
            f"🎉 You won **{amount * 2:,} Bucks**!"
        )

    else:

        responses = [
            "Better luck next time idiot.",
            "Imagine losing all your money from a single coinflip.",
            "Pathetic, even no one would try and do that stupid thing."
        ]

        await ctx.send(
            f"🪙 **{result.upper()}**\n"
            f"*{random.choice(responses)}*"
        )


# ============================================================
# MINES
# ============================================================

class MinesButton(discord.ui.Button):

    def __init__(self, index):
        super().__init__(
            label="?",
            style=discord.ButtonStyle.secondary,
            row=index // 5
        )

        self.index = index

    async def callback(self, interaction: discord.Interaction):

        view = self.view

        if interaction.user.id != view.player_id:
            await interaction.response.send_message(
                "This isn't your Mines game.",
                ephemeral=True
            )
            return

        if view.finished:
            await interaction.response.send_message(
                "This game has already ended.",
                ephemeral=True
            )
            return

        tile = view.board[self.index]

        if tile == "bomb":

            view.finished = True

            for child in view.children:
                child.disabled = True

            await interaction.response.edit_message(
                content="💣 **BOOM! You hit a bomb and lost everything!**",
                view=view
            )

            return

        view.multiplier *= 1.2

        self.label = "✓"
        self.disabled = True

        view.safe_tiles += 1

        await interaction.response.edit_message(
            content=(
                f"💣 **Mines**\n"
                f"Multiplier: **{view.multiplier:.2f}×**\n"
                f"Safe tiles: **{view.safe_tiles}**\n\n"
                f"Keep clicking or cash out by using the button below."
            ),
            view=view
        )


class MinesView(discord.ui.View):

    def __init__(self, player_id, amount):

        super().__init__(timeout=300)

        self.player_id = player_id
        self.amount = amount
        self.multiplier = 1.0
        self.safe_tiles = 0
        self.finished = False

        # 5x5 board, 5 bombs
        self.board = (
            ["bomb"] * 5
            + ["safe"] * 20
        )

        random.shuffle(self.board)

        for i in range(25):
            self.add_item(MinesButton(i))

        cashout = discord.ui.Button(
            label="Cash Out",
            style=discord.ButtonStyle.success,
            row=4
        )

        async def cashout_callback(interaction):

            if interaction.user.id != self.player_id:
                await interaction.response.send_message(
                    "This isn't your Mines game.",
                    ephemeral=True
                )
                return

            if self.finished:
                await interaction.response.send_message(
                    "This game has already ended.",
                    ephemeral=True
                )
                return

            self.finished = True

            winnings = int(
                self.amount * self.multiplier
            )

            add_bucks(
                self.player_id,
                winnings
            )

            for child in self.children:
                child.disabled = True

            await interaction.response.edit_message(
                content=(
                    f"💰 **Cashed out!**\n"
                    f"Multiplier: **{self.multiplier:.2f}×**\n"
                    f"Winnings: **{winnings:,} Bucks**"
                ),
                view=self
            )

        cashout.callback = cashout_callback

        self.add_item(cashout)


@bot.command(name="mines")
async def mines(ctx, amount: int = None):

    if amount is None:
        await ctx.send(
            "Usage: `buck mines (amount)`"
        )
        return

    if amount <= 0:
        await ctx.send(
            "Your wager must be greater than 0."
        )
        return

    balance = get_bucks(ctx.author.id)

    if balance < amount:
        await ctx.send(
            "You don't have enough Bucks."
        )
        return

    remove_bucks(ctx.author.id, amount)

    view = MinesView(
        ctx.author.id,
        amount
    )

    await ctx.send(
        f"💣 **Mines — 5×5**\n"
        f"Wager: **{amount:,} Bucks**\n"
        f"Every safe tile adds **1.2×**.",
        view=view
    )


# ============================================================
# STEAL
# ============================================================

@bot.command(name="steal")
async def steal(ctx, user: discord.Member = None):

    if user is None:
        await ctx.send(
            "Usage: `buck steal (user)`"
        )
        return

    if user.id == ctx.author.id:
        await ctx.send(
            "You cannot rob yourself."
        )
        return

    if user.bot:
        await ctx.send(
            "You cannot rob a bot."
        )
        return

    if not owns_item(ctx.author.id, "handgun"):
        await ctx.send(
            "You need the **Handgun** from the shop to steal."
        )
        return

    ensure_user(ctx.author.id)

    cursor.execute(
        "SELECT last_steal FROM users WHERE user_id = ?",
        (ctx.author.id,)
    )

    last_steal = cursor.fetchone()[0]

    now = datetime.now().timestamp()

    if now - last_steal < STEAL_COOLDOWN:

        remaining = int(
            STEAL_COOLDOWN - (now - last_steal)
        )

        minutes = remaining // 60
        seconds = remaining % 60

        responses = [
            f"Nope, you need to wait {minutes}m {seconds}s to steal again.",
            f"Your greedy as hell, wait for {minutes}m {seconds}s to steal again you greedy imbecile."
        ]

        await ctx.send(
            random.choice(responses)
        )
        return

    cursor.execute(
        "UPDATE users SET last_steal = ? WHERE user_id = ?",
        (now, ctx.author.id)
    )

    db.commit()

    success = random.random() < 0.30

    if not success:

        responses = [
            "Well that is a pathetic attempt to rob someone.",
            "I feel second-hand embarrassment for you.",
            "Sucks to be you."
        ]

        await ctx.send(
            f"*{random.choice(responses)}*"
        )
        return

    victim_balance = get_bucks(user.id)

    if victim_balance <= 0:
        await ctx.send(
            "That player doesn't have any Bucks to steal."
        )
        return

    amount = random.randint(
        STEAL_MIN,
        min(STEAL_MAX, victim_balance)
    )

    remove_bucks(user.id, amount)
    add_bucks(ctx.author.id, amount)

    await ctx.send(
        f"🔫 **Robbery successful!**\n"
        f"{ctx.author.mention} stole **{amount:,} Bucks** "
        f"from {user.mention}."
    )


# ============================================================
# LEADERBOARDS
# ============================================================

@bot.tree.command(
    name="leaderboard",
    description="View a local or global leaderboard."
)
@app_commands.describe(
    leaderboard_type="kills, deaths, or bucks",
    scope="local or global"
)
@app_commands.choices(
    leaderboard_type=[
        app_commands.Choice(name="Kills", value="kills"),
        app_commands.Choice(name="Deaths", value="deaths"),
        app_commands.Choice(name="Bucks", value="bucks")
    ],
    scope=[
        app_commands.Choice(name="Local", value="local"),
        app_commands.Choice(name="Global", value="global")
    ]
)
async def leaderboard(
    interaction: discord.Interaction,
    leaderboard_type: app_commands.Choice[str],
    scope: app_commands.Choice[str]
):

    stat = leaderboard_type.value
    selected_scope = scope.value

    if stat not in ("kills", "deaths", "bucks"):
        await interaction.response.send_message(
            "Invalid leaderboard type.",
            ephemeral=True
        )
        return

    if selected_scope == "local":

        # Discord users in this server
        member_ids = [
            member.id
            for member in interaction.guild.members
            if not member.bot
        ]

        if not member_ids:
            await interaction.response.send_message(
                "No players found.",
                ephemeral=True
            )
            return

        placeholders = ",".join(
            "?" for _ in member_ids
        )

        query = f"""
        SELECT user_id, {stat}
        FROM users
        WHERE user_id IN ({placeholders})
        ORDER BY {stat} DESC
        LIMIT 10
        """

        cursor.execute(
            query,
            member_ids
        )

    else:

        cursor.execute(
            f"""
            SELECT user_id, {stat}
            FROM users
            ORDER BY {stat} DESC
            LIMIT 10
            """
        )

    rows = cursor.fetchall()

    if not rows:
        await interaction.response.send_message(
            "No leaderboard data yet."
        )
        return

    lines = []

    for position, (user_id, value) in enumerate(rows, 1):

        member = interaction.guild.get_member(user_id)

        if member:
            name = member.display_name
        else:
            try:
                fetched = await bot.fetch_user(user_id)
                name = fetched.name
            except:
                name = f"User {user_id}"

        if stat == "bucks":
            display = f"{value:,} Bucks"
        else:
            display = f"{value:,}"

        lines.append(
            f"**{position}.** {name} — {display}"
        )

    title = (
        f"🏆 {stat.title()} Leaderboard "
        f"({selected_scope.title()})"
    )

    embed = black_embed(
        title,
        "\n".join(lines)
    )

    await interaction.response.send_message(
        embed=embed
    )


# ============================================================
# HELP
# ============================================================

@bot.tree.command(
    name="help",
    description="View all bot commands."
)
async def help_command(interaction: discord.Interaction):

    embed = black_embed(
        "📖 Roulette Bot Help",
        "Here are all available commands."
    )

    embed.add_field(
        name="🎰 Roulette",
        value=(
            "`/normal roulette`\n"
            "`/solo roulette`\n"
            "`/buckshot roulette (user)`"
        ),
        inline=False
    )

    embed.add_field(
        name="🎒 Solo Actions & Items",
        value=(
            "`buck s action inspect`\n"
            "`buck solo action inspect`\n"
            "`buck s item battery`\n"
            "`buck solo item battery`\n"
            "`buck s item alcohol`\n"
            "`buck solo item alcohol`"
        ),
        inline=False
    )

    embed.add_field(
        name="💰 Economy",
        value=(
            "`buck currency`\n"
            "`buck buy (item)`\n"
            "`buck give (amount) (user)`\n"
            "`buck mines (amount)`\n"
            "`buck coinflip h (amount)`\n"
            "`buck coinflip t (amount)`\n"
            "`buck steal (user)`\n"
            "`/shop`"
        ),
        inline=False
    )

    embed.add_field(
        name="🏆 Leaderboards",
        value=(
            "`/leaderboard kills local/global`\n"
            "`/leaderboard deaths local/global`\n"
            "`/leaderboard bucks local/global`"
        ),
        inline=False
    )

    embed.add_field(
        name="⚙️ Bot",
        value=(
            "`/information`\n"
            "`/setchannelgm (channel)`\n"
            "`/help`"
        ),
        inline=False
    )

    await interaction.response.send_message(
        embed=embed
    )


# ============================================================
# PREFIX SHOOT COMMAND
# ============================================================

@bot.command(name="shoot")
async def shoot(ctx, user: discord.Member = None):

    # Normal Roulette
    normal = active_normal_games.get(ctx.guild.id)

    if normal and normal["running"]:

        if ctx.author.id != normal.get("current_player"):
            await ctx.send(
                "Required to be in game to use this command."
            )
            return

        if user is None:
            await ctx.send(
                "Usage: `buck shoot (user)`"
            )
            return

        # The actual normal turn waits for buck shoot.
        # This command exists so the command is recognized.
        return

    # Otherwise
    await ctx.send(
        "Required to be in game to use this command."
    )


# ============================================================
# BOT READY
# ============================================================

@bot.event
async def on_ready():

    # Sync slash commands
    try:
        synced = await bot.tree.sync()

        print(
            f"Logged in as {bot.user}."
        )

        print(
            f"Synced {len(synced)} slash commands."
        )

    except Exception as e:
        print(
            f"Command sync error: {e}"
        )

    print(
        f"Version: {BOT_VERSION}"
    )

    print(
        f"Latency: {round(bot.latency * 1000)}ms"
    )


# ============================================================
# ERROR HANDLING
# ============================================================

@bot.tree.error
async def on_app_command_error(
    interaction: discord.Interaction,
    error
):

    if isinstance(
        error,
        app_commands.errors.MissingPermissions
    ):
        if not interaction.response.is_done():
            await interaction.response.send_message(
                "You don't have permission to use this command.",
                ephemeral=True
            )
        return

    if not interaction.response.is_done():
        await interaction.response.send_message(
            "An error occurred while processing the command.",
            ephemeral=True
        )

    print(
        f"Slash command error: {error}"
    )


# ============================================================
# le start bot
# ============================================================

if not TOKEN:
    raise RuntimeError(
        "DISCORD_TOKEN environment variable is missing."
    )

bot.run(TOKEN)
