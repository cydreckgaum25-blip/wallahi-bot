import os
import random
import sqlite3
import asyncio
from datetime import datetime

import discord
from discord.ext import commands
from discord import app_commands


TOKEN = os.getenv("DISCORD_TOKEN")

PREFIX = "%"
BOT_VERSION = "1.5V"
CREATOR = "jestre.py"
DB_NAME = "roulette.db"

ROULETTE_REWARD = 50000
STEAL_COOLDOWN = 1800

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guilds = True
intents.reactions = True

bot = commands.Bot(
    command_prefix=PREFIX,
    intents=intents
)

db = sqlite3.connect(DB_NAME)
db.row_factory = sqlite3.Row
cursor = db.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    bucks INTEGER DEFAULT 0,
    kills INTEGER DEFAULT 0,
    deaths INTEGER DEFAULT 0,
    multiplier INTEGER DEFAULT 0,
    handgun INTEGER DEFAULT 0,
    last_steal INTEGER DEFAULT 0
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS settings (
    guild_id INTEGER PRIMARY KEY,
    game_channel INTEGER
)
""")

db.commit()

active_games = {}
muted_players = {}


def ensure_user(user_id):
    cursor.execute(
        "SELECT user_id FROM users WHERE user_id = ?",
        (user_id,)
    )

    if cursor.fetchone() is None:
        cursor.execute(
            "INSERT INTO users (user_id) VALUES (?)",
            (user_id,)
        )
        db.commit()


def get_user(user_id):
    ensure_user(user_id)

    cursor.execute(
        "SELECT * FROM users WHERE user_id = ?",
        (user_id,)
    )

    return cursor.fetchone()


def get_bucks(user_id):
    return get_user(user_id)["bucks"]


def add_bucks(user_id, amount):
    ensure_user(user_id)

    cursor.execute(
        "UPDATE users SET bucks = bucks + ? WHERE user_id = ?",
        (amount, user_id)
    )

    db.commit()


def remove_bucks(user_id, amount):
    ensure_user(user_id)

    cursor.execute(
        "UPDATE users SET bucks = bucks - ? WHERE user_id = ?",
        (amount, user_id)
    )

    db.commit()


def add_kill(user_id):
    ensure_user(user_id)

    cursor.execute(
        "UPDATE users SET kills = kills + 1 WHERE user_id = ?",
        (user_id,)
    )

    db.commit()


def add_death(user_id):
    ensure_user(user_id)

    cursor.execute(
        "UPDATE users SET deaths = deaths + 1 WHERE user_id = ?",
        (user_id,)
    )

    db.commit()


def has_handgun(user_id):
    return bool(get_user(user_id)["handgun"])


def has_multiplier(user_id):
    return bool(get_user(user_id)["multiplier"])


def reward_for(user_id):
    if has_multiplier(user_id):
        return ROULETTE_REWARD * 2

    return ROULETTE_REWARD


def game_channel_id(guild_id):
    cursor.execute(
        "SELECT game_channel FROM settings WHERE guild_id = ?",
        (guild_id,)
    )

    row = cursor.fetchone()

    if row:
        return row["game_channel"]

    return None


def format_money(amount):
    return f"{amount:,} Bucks"


async def check_game_channel(interaction):
    configured = game_channel_id(interaction.guild.id)

    if configured is None:
        await interaction.response.send_message(
            "No game channel has been configured yet. Use `/setchannelgm` first.",
            ephemeral=True
        )
        return False

    if interaction.channel.id != configured:
        await interaction.response.send_message(
            "Games can only be played in the designated game channel.",
            ephemeral=True
        )
        return False

    return True


async def mute_player(channel, member):
    try:
        overwrite = channel.overwrites_for(member)
        overwrite.send_messages = False

        await channel.set_permissions(
            member,
            overwrite=overwrite
        )

        muted_players[(channel.guild.id, member.id)] = True

    except discord.Forbidden:
        pass


async def unmute_player(channel, member):
    try:
        overwrite = channel.overwrites_for(member)
        overwrite.send_messages = None

        await channel.set_permissions(
            member,
            overwrite=overwrite
        )

        muted_players.pop(
            (channel.guild.id, member.id),
            None
        )

    except discord.Forbidden:
        pass


async def finish_game(channel, guild_id, participants):
    for member in participants:
        await unmute_player(channel, member)

    active_games.pop(guild_id, None)


def make_revolver():
    chambers = [True, False, False, False, False, False]
    random.shuffle(chambers)
    return chambers


def increase_ammo(chambers):
    blanks = [
        index
        for index, chamber in enumerate(chambers)
        if not chamber
    ]

    if blanks:
        chambers[random.choice(blanks)] = True

    return chambers


# =========================================================
# NORMAL ROULETTE
# =========================================================

@bot.tree.command(
    name="normalroulette",
    description="Start Normal Roulette."
)
async def normalroulette(interaction: discord.Interaction):

    if not await check_game_channel(interaction):
        return

    guild_id = interaction.guild.id

    if guild_id in active_games:
        await interaction.response.send_message(
            "A game is already active in this server.",
            ephemeral=True
        )
        return

    await interaction.response.send_message(
        "React with :white_check_mark: within 30 seconds to join the game."
    )

    message = await interaction.original_response()

    await message.add_reaction("✅")

    await asyncio.sleep(30)

    try:
        message = await interaction.channel.fetch_message(
            message.id
        )
    except discord.NotFound:
        return

    reaction = discord.utils.get(
        message.reactions,
        emoji="✅"
    )

    if reaction is None:
        await interaction.channel.send(
            "Not enough players joined."
        )
        return

    players = []

    async for user in reaction.users():
        if not user.bot and user not in players:
            players.append(user)

    if len(players) < 2:
        await interaction.channel.send(
            "At least 2 players are required to start."
        )
        return

    active_games[guild_id] = {
        "type": "normal",
        "participants": players.copy(),
        "alive": players.copy(),
        "chambers": make_revolver(),
        "current": random.choice(players)
    }

    game = active_games[guild_id]

    await interaction.channel.send(
        "Putting ammo in the revolver..."
    )

    await asyncio.sleep(1)

    spinning = await interaction.channel.send(
        "Spinning the chamber..."
    )

    await asyncio.sleep(1)

    filled = sum(game["chambers"])
    blank = 6 - filled

    await spinning.edit(
        content=f"{filled} filled chambers and {blank} blank chambers, Goodluck."
    )

    await normal_turn(
        interaction.channel,
        guild_id
    )


async def normal_turn(channel, guild_id):

    if guild_id not in active_games:
        return

    game = active_games[guild_id]

    if len(game["alive"]) <= 1:

        winner = game["alive"][0]

        reward = reward_for(winner.id)

        add_bucks(
            winner.id,
            reward
        )

        await channel.send(
            f"{winner.display_name} wins and receives {format_money(reward)}."
        )

        await finish_game(
            channel,
            guild_id,
            game["participants"]
        )

        return

    current = game["current"]

    await channel.send(
        f"{current.display_name} two choices, shoot yourself, or shoot someone..."
    )

    def check(message):
        return (
            message.channel.id == channel.id
            and message.author.id == current.id
            and message.content.lower().startswith(
                f"{PREFIX}shoot"
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
            f"{current.display_name} took too long."
        )

        alive = game["alive"]

        if current in alive:
            index = alive.index(current)
            game["current"] = alive[
                (index + 1) % len(alive)
            ]

        await normal_turn(
            channel,
            guild_id
        )
        return

    if not message.mentions:

        await channel.send(
            f"Use `{PREFIX}shoot @user`."
        )

        await normal_turn(
            channel,
            guild_id
        )
        return

    target = message.mentions[0]

    if target not in game["alive"]:

        await channel.send(
            "That player is not in the game."
        )

        await normal_turn(
            channel,
            guild_id
        )
        return

    chamber = game["chambers"].pop(0)

    if chamber:

        await channel.send("*Boom*")

        await channel.send(
            f"{target.display_name} was eliminated by {current.display_name}"
        )

        add_death(target.id)

        if target.id != current.id:
            add_kill(current.id)

        await mute_player(
            channel,
            target
        )

        game["alive"].remove(target)

        if len(game["alive"]) > 1:

            game["chambers"] = increase_ammo(
                game["chambers"]
            )

    else:

        await channel.send("*Click*")

    if len(game["alive"]) <= 1:

        await normal_turn(
            channel,
            guild_id
        )
        return

    if not game["chambers"]:

        filled_count = min(
            6,
            1 + (
                len(game["participants"])
                - len(game["alive"])
            )
        )

        game["chambers"] = (
            [True] * filled_count
            + [False] * (6 - filled_count)
        )

        random.shuffle(
            game["chambers"]
        )

    if current in game["alive"]:

        index = game["alive"].index(current)

        game["current"] = game["alive"][
            (index + 1) % len(game["alive"])
        ]

    else:

        game["current"] = game["alive"][
            game.get("current_index", 0)
            % len(game["alive"])
        ]

    await normal_turn(
        channel,
        guild_id
    )


# =========================================================
# SOLO ROULETTE
# =========================================================

SOLO_BOT_LINES = [
    "Do you want to see the light?",
    "This may be your last day.",
    "Im sorry.",
    "Im taking the risk.",
    "I dont know what to expect."
]

SOLO_INSPECT_LINES = [
    "You trying to cheat?",
    "Oi, i wont do that if i were you."
]

SOLO_BATTERY_LINES = [
    "Are you trying to fix that thing?",
    "What are you, a technician?"
]

SOLO_ALCOHOL_LINES = [
    "Want a refill? kill me first.",
    "Too bad, you better win this if you want to drink more."
]


@bot.tree.command(
    name="soloroulette",
    description="Play Solo Roulette."
)
async def soloroulette(interaction: discord.Interaction):

    if not await check_game_channel(interaction):
        return

    guild_id = interaction.guild.id

    if guild_id in active_games:
        await interaction.response.send_message(
            "A game is already active in this server.",
            ephemeral=True
        )
        return

    player = interaction.user

    active_games[guild_id] = {
        "type": "solo",
        "participants": [player],
        "player": player,
        "player_alive": True,
        "bot_alive": True,
        "player_armor": 3,
        "bot_armor": 3,
        "chambers": make_revolver(),
        "inspect": 2,
        "battery": False,
        "alcohol": True,
        "adrenaline": False,
        "player_turn": True
    }

    await interaction.response.send_message(
        "Putting ammo in the revolver..."
    )

    await asyncio.sleep(1)

    await interaction.channel.send(
        "Spinning the chamber..."
    )

    await asyncio.sleep(1)

    game = active_games[guild_id]

    filled = sum(game["chambers"])
    blank = 6 - filled

    await interaction.channel.send(
        f"{filled} filled chambers and {blank} blank chambers, Goodluck."
    )

    await solo_turn(
        interaction.channel,
        guild_id
    )


async def solo_reload(game):

    filled = random.randint(1, 5)

    game["chambers"] = (
        [True] * filled
        + [False] * (6 - filled)
    )

    random.shuffle(
        game["chambers"]
    )


async def solo_turn(channel, guild_id):

    if guild_id not in active_games:
        return

    game = active_games[guild_id]

    if not game["player_alive"]:

        await channel.send(
            "You were eliminated."
        )

        await finish_game(
            channel,
            guild_id,
            game["participants"]
        )

        return

    if not game["bot_alive"]:

        reward = reward_for(
            game["player"].id
        )

        add_bucks(
            game["player"].id,
            reward
        )

        await channel.send(
            f"You defeated the bot and received {format_money(reward)}."
        )

        await finish_game(
            channel,
            guild_id,
            game["participants"]
        )

        return

    if not game["chambers"]:
        await solo_reload(game)

    if game["player_turn"]:

        if (
            game["player_armor"] <= 1
            and not game["battery"]
            and random.random() <= 0.20
        ):
            game["battery"] = True

        await channel.send(
            f"{game['player'].display_name} your turn.\n"
            f"Armor: {game['player_armor']}\n"
            f"Use `{PREFIX}s shoot @user`, "
            f"`{PREFIX}s action inspect`, "
            f"`{PREFIX}s item battery`, or "
            f"`{PREFIX}s item alcohol`."
        )

        def check(message):
            return (
                message.channel.id == channel.id
                and message.author.id == game["player"].id
                and (
                    message.content.lower().startswith(
                        f"{PREFIX}s"
                    )
                    or message.content.lower().startswith(
                        f"{PREFIX}solo"
                    )
                )
            )

        try:
            message = await bot.wait_for(
                "message",
                timeout=60,
                check=check
            )
        except asyncio.TimeoutError:

            game["player_turn"] = False

            await solo_turn(
                channel,
                guild_id
            )
            return

        content = message.content.lower()

        if "action inspect" in content:

            if game["inspect"] <= 0:

                await channel.send(
                    random.choice(
                        SOLO_INSPECT_LINES
                    )
                )

            else:

                game["inspect"] -= 1

                if not game["chambers"]:
                    await solo_reload(game)

                chamber_text = []

                for index, chamber in enumerate(
                    game["chambers"],
                    start=1
                ):
                    chamber_text.append(
                        f"chamber {index}: "
                        f"{'filled' if chamber else 'blank'}"
                    )

                await channel.send(
                    "*(" +
                    ", ".join(chamber_text) +
                    ")*"
                )

            await solo_turn(
                channel,
                guild_id
            )
            return

        if "item battery" in content:

            if (
                game["battery"]
                and game["player_armor"] <= 1
            ):

                game["battery"] = False

                if random.random() <= 0.02:

                    await channel.send(
                        "The battery exploded."
                    )

                    game["player_alive"] = False

                    add_death(
                        game["player"].id
                    )

                    await solo_turn(
                        channel,
                        guild_id
                    )
                    return

                game["player_armor"] += 1

                await channel.send(
                    f"Armor: {game['player_armor']}"
                )

            else:

                await channel.send(
                    random.choice(
                        SOLO_BATTERY_LINES
                    )
                )

            await solo_turn(
                channel,
                guild_id
            )
            return

        if "item alcohol" in content:

            if (
                game["alcohol"]
                and game["player_armor"] == 0
            ):

                game["alcohol"] = False
                game["adrenaline"] = True

                await channel.send(
                    "You got an adrenaline rush."
                )

            else:

                await channel.send(
                    random.choice(
                        SOLO_ALCOHOL_LINES
                    )
                )

            await solo_turn(
                channel,
                guild_id
            )
            return

        if "shoot" in content:

            target = None

            if message.mentions:
                target = message.mentions[0]

            elif "bot" in content:
                target = bot.user

            elif (
                "yourself" in content
                or "self" in content
            ):
                target = game["player"]

            if target is None:

                await channel.send(
                    f"Use `{PREFIX}s shoot @user`."
                )

                await solo_turn(
                    channel,
                    guild_id
                )
                return

            chamber = game["chambers"].pop(0)

            if chamber:

                await channel.send("*Boom*")

                if target.id == bot.user.id:

                    game["bot_armor"] -= 1

                    await channel.send(
                        f"Bot armor: {game['bot_armor']}"
                    )

                    if game["bot_armor"] <= 0:

                        game["bot_alive"] = False

                        add_kill(
                            game["player"].id
                        )

                else:

                    if game["adrenaline"]:

                        game["adrenaline"] = False

                        await channel.send(
                            "The adrenaline rush protected you."
                        )

                    else:

                        game["player_armor"] -= 1

                        await channel.send(
                            f"Armor: {game['player_armor']}"
                        )

                        if game["player_armor"] <= 0:

                            game["player_alive"] = False

                            add_death(
                                game["player"].id
                            )

                            await solo_turn(
                                channel,
                                guild_id
                            )
                            return

            else:

                await channel.send("*Click*")

            game["player_turn"] = False

            await solo_turn(
                channel,
                guild_id
            )
            return

        await channel.send(
            "Invalid action."
        )

        await solo_turn(
            channel,
            guild_id
        )
        return

    await channel.send(
        random.choice(
            SOLO_BOT_LINES
        )
    )

    await asyncio.sleep(1)

    target_player = random.choice(
        [True, False]
    )

    chamber = game["chambers"].pop(0)

    if chamber:

        await channel.send("*Boom*")

        if target_player:

            if game["adrenaline"]:

                game["adrenaline"] = False

                await channel.send(
                    "The adrenaline rush protected you."
                )

            else:

                game["player_armor"] -= 1

                await channel.send(
                    f"Armor: {game['player_armor']}"
                )

                if game["player_armor"] <= 0:

                    game["player_alive"] = False

                    add_death(
                        game["player"].id
                    )

                    await solo_turn(
                        channel,
                        guild_id
                    )
                    return

        else:

            game["bot_armor"] -= 1

            await channel.send(
                f"Bot armor: {game['bot_armor']}"
            )

            if game["bot_armor"] <= 0:
                game["bot_alive"] = False

    else:

        await channel.send("*Click*")

    game["player_turn"] = True

    await solo_turn(
        channel,
        guild_id
    )


# =========================================================
# BUCKSHOT ROULETTE
# =========================================================

@bot.tree.command(
    name="buckshotroulette",
    description="Play Buckshot Roulette."
)
@app_commands.describe(
    user="The player you want to play against."
)
async def buckshotroulette(
    interaction: discord.Interaction,
    user: discord.Member
):

    if not await check_game_channel(interaction):
        return

    guild_id = interaction.guild.id

    if guild_id in active_games:
        await interaction.response.send_message(
            "A game is already active in this server.",
            ephemeral=True
        )
        return

    if user.bot:

        await interaction.response.send_message(
            "You cannot play against a bot.",
            ephemeral=True
        )
        return

    if user.id == interaction.user.id:

        await interaction.response.send_message(
            "You cannot play against yourself.",
            ephemeral=True
        )
        return

    total = random.randint(
        1,
        6
    )

    filled = random.randint(
        0,
        total
    )

    blank = total - filled

    chambers = (
        [True] * filled
        + [False] * blank
    )

    random.shuffle(
        chambers
    )

    players = [
        interaction.user,
        user
    ]

    active_games[guild_id] = {
        "type": "buckshot",
        "participants": players.copy(),
        "alive": players.copy(),
        "armor": {
            interaction.user.id: 4,
            user.id: 4
        },
        "chambers": chambers,
        "current": random.choice(players)
    }

    await interaction.response.send_message(
        f"{interaction.user.mention} vs {user.mention}"
    )

    await asyncio.sleep(1)

    await interaction.channel.send(
        random.choice([
            "Goodluck to you two.",
            "Only one can survive."
        ])
    )

    await asyncio.sleep(1)

    await interaction.channel.send(
        f"{blank} blanks and {filled} filled ammo."
    )

    await buckshot_turn(
        interaction.channel,
        guild_id
    )


async def buckshot_reload(game):

    total = random.randint(
        1,
        6
    )

    filled = random.randint(
        0,
        total
    )

    blank = total - filled

    game["chambers"] = (
        [True] * filled
        + [False] * blank
    )

    random.shuffle(
        game["chambers"]
    )

    return blank, filled


async def buckshot_turn(channel, guild_id):

    if guild_id not in active_games:
        return

    game = active_games[guild_id]

    if len(game["alive"]) <= 1:

        winner = game["alive"][0]

        reward = reward_for(
            winner.id
        )

        add_bucks(
            winner.id,
            reward
        )

        await channel.send(
            f"{winner.display_name} wins and receives {format_money(reward)}."
        )

        await finish_game(
            channel,
            guild_id,
            game["participants"]
        )

        return

    if not game["chambers"]:

        blank, filled = await buckshot_reload(
            game
        )

        await channel.send(
            f"{blank} blanks and {filled} filled ammo."
        )

    current = game["current"]

    await channel.send(
        f"{current.display_name} two choices, shoot yourself, or shoot someone...\n"
        f"Armor: {game['armor'][current.id]}\n"
        f"Use `{PREFIX}shoot @user`."
    )

    def check(message):
        return (
            message.channel.id == channel.id
            and message.author.id == current.id
            and message.content.lower().startswith(
                f"{PREFIX}shoot"
            )
        )

    try:
        message = await bot.wait_for(
            "message",
            timeout=60,
            check=check
        )
    except asyncio.TimeoutError:

        if current in game["alive"]:

            index = game["alive"].index(
                current
            )

            game["current"] = game["alive"][
                (index + 1) % len(game["alive"])
            ]

        await buckshot_turn(
            channel,
            guild_id
        )
        return

    if not message.mentions:

        await channel.send(
            f"Use `{PREFIX}shoot @user`."
        )

        await buckshot_turn(
            channel,
            guild_id
        )
        return

    target = message.mentions[0]

    if target not in game["alive"]:

        await channel.send(
            "That player is not in the game."
        )

        await buckshot_turn(
            channel,
            guild_id
        )
        return

    chamber = game["chambers"].pop(0)

    if chamber:

        await channel.send("*Boom*")

        game["armor"][target.id] -= 1

        await channel.send(
            f"{target.display_name} armor: "
            f"{game['armor'][target.id]}"
        )

        if game["armor"][target.id] <= 0:

            await channel.send(
                f"{target.display_name} was eliminated by {current.display_name}"
            )

            add_death(
                target.id
            )

            if target.id != current.id:
                add_kill(
                    current.id
                )

            await mute_player(
                channel,
                target
            )

            game["alive"].remove(
                target
            )

            if len(game["alive"]) <= 1:

                await buckshot_turn(
                    channel,
                    guild_id
                )
                return

    else:

        await channel.send("*Click*")

    if current in game["alive"]:

        index = game["alive"].index(
            current
        )

        game["current"] = game["alive"][
            (index + 1) % len(game["alive"])
        ]

    else:

        game["current"] = game["alive"][0]

    await buckshot_turn(
        channel,
        guild_id
    )


# =========================================================
# PREFIX COMMANDS
# =========================================================

@bot.command(name="shoot")
async def shoot(ctx, *args):

    if ctx.guild is None:
        return

    if ctx.guild.id not in active_games:

        await ctx.send(
            "Required to be in game to use this command."
        )


@bot.command(name="s")
async def s(ctx, *args):

    if ctx.guild is None:
        return

    if ctx.guild.id not in active_games:

        await ctx.send(
            "Required to be in game to use this command."
        )


@bot.command(name="solo")
async def solo(ctx, *args):

    if ctx.guild is None:
        return

    if ctx.guild.id not in active_games:

        await ctx.send(
            "Required to be in game to use this command."
        )


@bot.command(name="currency")
async def currency(ctx):

    await ctx.send(
        f"You have {format_money(get_bucks(ctx.author.id))}."
    )


@bot.command(name="give")
async def give(
    ctx,
    amount: int = None,
    user: discord.Member = None
):

    if amount is None or user is None:

        await ctx.send(
            f"Usage: {PREFIX}give <amount> @user"
        )
        return

    if amount <= 0:

        await ctx.send(
            "Amount must be greater than zero."
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

    if get_bucks(ctx.author.id) < amount:

        await ctx.send(
            "You don't have enough Bucks."
        )
        return

    remove_bucks(
        ctx.author.id,
        amount
    )

    add_bucks(
        user.id,
        amount
    )

    await ctx.send(
        f"{ctx.author.mention} gave {format_money(amount)} to {user.mention}."
    )


# =========================================================
# SHOP
# =========================================================

SHOP = {
    "rewards multiplier": 250000,
    "rewards multiplier (2x)": 250000,
    "handgun": 300000,
    "diamond": 5000000,
    "emerald": 1000000,
    "ruby": 500000,
    "sapphire": 250000,
    "amethyst": 100000,
    "topaz": 50000
}


@bot.tree.command(
    name="shop",
    description="View the shop."
)
async def shop(interaction: discord.Interaction):

    text = []

    for name, price in SHOP.items():

        text.append(
            f"**{name.title()}** — {format_money(price)}"
        )

    await interaction.response.send_message(
        "\n".join(text)
    )


@bot.command(name="buy")
async def buy(ctx, *, item_name=None):

    if not item_name:

        await ctx.send(
            f"Usage: {PREFIX}buy <item>"
        )
        return

    item_name = item_name.lower().strip()

    if item_name not in SHOP:

        matches = [
            item
            for item in SHOP
            if item_name in item
        ]

        if not matches:

            await ctx.send(
                "That item does not exist in the shop."
            )
            return

        item_name = matches[0]

    price = SHOP[item_name]

    if get_bucks(ctx.author.id) < price:

        await ctx.send(
            random.choice([
                "Get rich before you buy something mate.",
                "Poor ass, get a job or something",
                "Sorry, we dont have a dollar to spare to you",
                "Get money first, poor idiot."
            ])
        )
        return

    remove_bucks(
        ctx.author.id,
        price
    )

    if item_name.startswith(
        "rewards multiplier"
    ):

        cursor.execute(
            "UPDATE users SET multiplier = 1 WHERE user_id = ?",
            (ctx.author.id,)
        )

    elif item_name == "handgun":

        cursor.execute(
            "UPDATE users SET handgun = 1 WHERE user_id = ?",
            (ctx.author.id,)
        )

    db.commit()

    await ctx.send(
        "Successful purchase, pleasure doing business.\n"
        f"*You have now {format_money(get_bucks(ctx.author.id))} left in your wallet*"
    )


# =========================================================
# STEAL
# =========================================================

@bot.command(name="steal")
async def steal(
    ctx,
    user: discord.Member = None
):

    if user is None:

        await ctx.send(
            f"Usage: {PREFIX}steal @user"
        )
        return

    if not has_handgun(ctx.author.id):

        await ctx.send(
            "You need to buy the Handgun first."
        )
        return

    if user.bot:

        await ctx.send(
            "You cannot steal from a bot."
        )
        return

    if user.id == ctx.author.id:

        await ctx.send(
            "You cannot steal from yourself."
        )
        return

    now = int(
        datetime.now().timestamp()
    )

    data = get_user(
        ctx.author.id
    )

    if (
        data["last_steal"]
        and now - data["last_steal"] < STEAL_COOLDOWN
    ):

        remaining = (
            STEAL_COOLDOWN
            - (now - data["last_steal"])
        )

        minutes = remaining // 60
        seconds = remaining % 60

        time = f"{minutes}m {seconds}s"

        await ctx.send(
            random.choice([
                f"Nope, you need to wait {time} to steal again.",
                f"Your greedy as hell, wait for {time} to steal again you greedy imbecile."
            ])
        )
        return

    cursor.execute(
        "UPDATE users SET last_steal = ? WHERE user_id = ?",
        (now, ctx.author.id)
    )

    db.commit()

    victim_balance = get_bucks(
        user.id
    )

    if victim_balance <= 0:

        await ctx.send(
            random.choice([
                "Well that is a pathetic attempt to rob someone.",
                "I feel second-hand embarrassment for you.",
                "Sucks to be you."
            ])
        )
        return

    if random.random() > 0.30:

        await ctx.send(
            random.choice([
                "Well that is a pathetic attempt to rob someone.",
                "I feel second-hand embarrassment for you.",
                "Sucks to be you."
            ])
        )
        return

    amount = random.randint(
        1,
        min(100000, victim_balance)
    )

    remove_bucks(
        user.id,
        amount
    )

    add_bucks(
        ctx.author.id,
        amount
    )

    await ctx.send(
        f"{ctx.author.mention} stole {format_money(amount)} from {user.mention}."
    )


# =========================================================
# COINFLIP
# =========================================================

@bot.command(name="coinflip")
async def coinflip(
    ctx,
    choice=None,
    amount: int = None
):

    if choice is None or amount is None:

        await ctx.send(
            f"Usage: {PREFIX}coinflip h <amount> or {PREFIX}coinflip t <amount>"
        )
        return

    choice = choice.lower()

    if choice not in [
        "h",
        "t",
        "heads",
        "tails"
    ]:

        await ctx.send(
            "Choose h or t."
        )
        return

    if amount <= 0:

        await ctx.send(
            "Amount must be greater than zero."
        )
        return

    if get_bucks(ctx.author.id) < amount:

        await ctx.send(
            "You don't have enough Bucks."
        )
        return

    result = random.choice([
        "h",
        "t"
    ])

    remove_bucks(
        ctx.author.id,
        amount
    )

    won = (
        choice.startswith("h")
        and result == "h"
    ) or (
        choice.startswith("t")
        and result == "t"
    )

    result_text = (
        "Heads"
        if result == "h"
        else "Tails"
    )

    if won:

        add_bucks(
            ctx.author.id,
            amount * 2
        )

        await ctx.send(
            f"The coin landed on {result_text}.\n"
            f"You won {format_money(amount * 2)}."
        )

    else:

        await ctx.send(
            f"The coin landed on {result_text}.\n"
            f"{random.choice([
                'Better luck next time idiot.',
                'Imagine losing all your money from a single coinflip.',
                'Pathetic, even no one would try and do that stupid thing.'
            ])}"
        )


# =========================================================
# MINES
# =========================================================

@bot.command(name="mines")
async def mines(
    ctx,
    amount: int = None
):

    if amount is None:

        await ctx.send(
            f"Usage: {PREFIX}mines <amount>"
        )
        return

    if amount <= 0:

        await ctx.send(
            "Amount must be greater than zero."
        )
        return

    if get_bucks(ctx.author.id) < amount:

        await ctx.send(
            "You don't have enough Bucks."
        )
        return

    remove_bucks(
        ctx.author.id,
        amount
    )

    bombs = set(
        random.sample(
            range(25),
            5
        )
    )

    clicked = set()
    multiplier = 1.0

    class MineView(discord.ui.View):

        def __init__(self):
            super().__init__(
                timeout=300
            )

            for i in range(25):

                button = discord.ui.Button(
                    label="?",
                    style=discord.ButtonStyle.secondary,
                    row=i // 5
                )

                async def callback(
                    interaction,
                    index=i,
                    button=button
                ):

                    nonlocal multiplier

                    if interaction.user.id != ctx.author.id:

                        await interaction.response.send_message(
                            "This isn't your Mines game.",
                            ephemeral=True
                        )
                        return

                    if index in clicked:

                        await interaction.response.send_message(
                            "You already clicked this tile.",
                            ephemeral=True
                        )
                        return

                    if index in bombs:

                        for child in self.children:
                            child.disabled = True

                        await interaction.response.edit_message(
                            content=(
                                f"BOOM!\n"
                                f"You lost {format_money(amount)}."
                            ),
                            view=self
                        )

                        self.stop()
                        return

                    clicked.add(index)

                    multiplier *= 1.2

                    button.label = "✓"
                    button.disabled = True

                    winnings = int(
                        amount * multiplier
                    )

                    await interaction.response.edit_message(
                        content=(
                            f"Multiplier: {multiplier:.2f}x\n"
                            f"Current value: {format_money(winnings)}"
                        ),
                        view=self
                    )

                button.callback = callback

                self.add_item(
                    button
                )

            cashout = discord.ui.Button(
                label="Cash Out",
                style=discord.ButtonStyle.success,
                row=4
            )

            async def cashout_callback(
                interaction
            ):

                if interaction.user.id != ctx.author.id:

                    await interaction.response.send_message(
                        "This isn't your Mines game.",
                        ephemeral=True
                    )
                    return

                winnings = int(
                    amount * multiplier
                )

                add_bucks(
                    ctx.author.id,
                    winnings
                )

                for child in self.children:
                    child.disabled = True

                await interaction.response.edit_message(
                    content=(
                        f"You received {format_money(winnings)}."
                    ),
                    view=self
                )

                self.stop()

            cashout.callback = cashout_callback

            self.add_item(
                cashout
            )

    await ctx.send(
        f"Multiplier: 1.00x\n"
        f"Current value: {format_money(amount)}",
        view=MineView()
    )


# =========================================================
# LEADERBOARD
# =========================================================

@bot.tree.command(
    name="leaderboard",
    description="View the leaderboard."
)
@app_commands.describe(
    type="kills, deaths, or bucks",
    scope="local or global"
)
@app_commands.choices(
    type=[
        app_commands.Choice(
            name="Kills",
            value="kills"
        ),
        app_commands.Choice(
            name="Deaths",
            value="deaths"
        ),
        app_commands.Choice(
            name="Bucks",
            value="bucks"
        )
    ],
    scope=[
        app_commands.Choice(
            name="Local",
            value="local"
        ),
        app_commands.Choice(
            name="Global",
            value="global"
        )
    ]
)
async def leaderboard(
    interaction: discord.Interaction,
    type: app_commands.Choice[str],
    scope: app_commands.Choice[str]
):

    column = type.value

    cursor.execute(
        f"""
        SELECT user_id, {column}
        FROM users
        ORDER BY {column} DESC
        LIMIT 50
        """
    )

    rows = cursor.fetchall()

    lines = []
    position = 1

    for row in rows:

        if scope.value == "local":

            member = interaction.guild.get_member(
                row["user_id"]
            )

            if member is None:
                continue

        else:

            try:
                member = await bot.fetch_user(
                    row["user_id"]
                )
            except discord.NotFound:
                continue

        value = row[column]

        if column == "bucks":
            value = format_money(value)

        lines.append(
            f"**{position}.** {member.display_name} — **{value}**"
        )

        position += 1

        if position > 10:
            break

    if not lines:

        lines.append(
            "No leaderboard data available."
        )

    await interaction.response.send_message(
        "\n".join(lines)
    )


# =========================================================
# INFORMATION
# =========================================================

@bot.tree.command(
    name="information",
    description="View bot information."
)
async def information(
    interaction: discord.Interaction
):

    ping = round(
        bot.latency * 1000
    )

    await interaction.response.send_message(
        f"Current Version: {BOT_VERSION}\n"
        f"Creator: {CREATOR}\n"
        f"Ping: {ping}ms\n"
        f"Status: Online"
    )


# =========================================================
# SET GAME CHANNEL
# =========================================================

@bot.tree.command(
    name="setchannelgm",
    description="Set the game channel."
)
@app_commands.describe(
    channel="The channel for roulette games."
)
@app_commands.checks.has_permissions(
    manage_channels=True
)
async def setchannelgm(
    interaction: discord.Interaction,
    channel: discord.TextChannel
):

    cursor.execute(
        """
        INSERT INTO settings (
            guild_id,
            game_channel
        )
        VALUES (?, ?)
        ON CONFLICT(guild_id)
        DO UPDATE SET game_channel = excluded.game_channel
        """,
        (
            interaction.guild.id,
            channel.id
        )
    )

    db.commit()

    await interaction.response.send_message(
        f"Game channel set to {channel.mention}."
    )


@setchannelgm.error
async def setchannelgm_error(
    interaction,
    error
):

    if isinstance(
        error,
        app_commands.errors.MissingPermissions
    ):

        if interaction.response.is_done():

            await interaction.followup.send(
                "You need Manage Channels permission.",
                ephemeral=True
            )

        else:

            await interaction.response.send_message(
                "You need Manage Channels permission.",
                ephemeral=True
            )


# =========================================================
# HELP
# =========================================================

@bot.tree.command(
    name="help",
    description="View bot commands."
)
async def help_command(
    interaction: discord.Interaction
):

    await interaction.response.send_message(
        f"""
Roulette

/normalroulette
/soloroulette
/buckshotroulette @user

Game Commands

{PREFIX}shoot @user
{PREFIX}s shoot @user
{PREFIX}s action inspect
{PREFIX}s item battery
{PREFIX}s item alcohol

Economy

{PREFIX}currency
{PREFIX}buy <item>
{PREFIX}give <amount> @user
{PREFIX}mines <amount>
{PREFIX}coinflip h <amount>
{PREFIX}coinflip t <amount>
{PREFIX}steal @user

/shop

Leaderboards

/leaderboard

Bot

/information
/setchannelgm #channel
/help
"""
    )


# =========================================================
# PREFIX ERROR HANDLER
# =========================================================

@bot.event
async def on_command_error(
    ctx,
    error
):

    if isinstance(
        error,
        commands.CommandNotFound
    ):
        return

    if isinstance(
        error,
        commands.MissingRequiredArgument
    ):

        await ctx.send(
            "Missing required argument."
        )
        return

    if isinstance(
        error,
        commands.BadArgument
    ):

        await ctx.send(
            "Invalid argument."
        )
        return

    print(
        f"Command error: {error}"
    )


# =========================================================
# READY
# =========================================================

@bot.event
async def on_ready():

    try:

        synced = await bot.tree.sync()

        print(
            f"Logged in as {bot.user}"
        )

        print(
            f"Synced {len(synced)} slash commands."
        )

    except Exception as error:

        print(
            f"Slash command sync error: {error}"
        )


if not TOKEN:

    raise RuntimeError(
        "DISCORD_TOKEN environment variable is not set."
    )

bot.run(TOKEN)
