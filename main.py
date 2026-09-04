import os
import re
import random
import sqlite3
import time

import discord
from discord.ext import commands
from discord import app_commands


# =========================================================
# CONFIG
# =========================================================

TOKEN = os.getenv("DISCORD_TOKEN")
DB_NAME = "wallahi.db"

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)


# =========================================================
# DATABASE
# =========================================================

db = sqlite3.connect(DB_NAME)
cursor = db.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    wallahis INTEGER NOT NULL
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS guild_settings (
    guild_id INTEGER PRIMARY KEY,
    wallahi_enabled INTEGER NOT NULL DEFAULT 1
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS daily (
    user_id INTEGER PRIMARY KEY,
    last_claim INTEGER NOT NULL
)
""")

db.commit()


# =========================================================
# DATABASE FUNCTIONS
# =========================================================

def get_user(user_id):
    cursor.execute(
        "SELECT wallahis FROM users WHERE user_id = ?",
        (user_id,)
    )

    result = cursor.fetchone()

    if result is None:
        amount = random.randint(1, 1000)

        cursor.execute(
            "INSERT INTO users (user_id, wallahis) VALUES (?, ?)",
            (user_id, amount)
        )

        db.commit()
        return amount

    return result[0]


def set_wallahi(user_id, amount):
    cursor.execute(
        "UPDATE users SET wallahis = ? WHERE user_id = ?",
        (amount, user_id)
    )
    db.commit()


def get_guild_setting(guild_id):
    cursor.execute(
        "SELECT wallahi_enabled FROM guild_settings WHERE guild_id = ?",
        (guild_id,)
    )

    result = cursor.fetchone()

    if result is None:
        cursor.execute(
            "INSERT INTO guild_settings (guild_id, wallahi_enabled) VALUES (?, 1)",
            (guild_id,)
        )
        db.commit()
        return True

    return bool(result[0])


def set_guild_setting(guild_id, enabled):
    cursor.execute(
        """
        INSERT INTO guild_settings (guild_id, wallahi_enabled)
        VALUES (?, ?)
        ON CONFLICT(guild_id)
        DO UPDATE SET wallahi_enabled = excluded.wallahi_enabled
        """,
        (guild_id, int(enabled))
    )

    db.commit()


# =========================================================
# BOT READY
# =========================================================

@bot.event
async def on_ready():
    await bot.tree.sync()

    print(f"Logged in as {bot.user}")
    print("Wallahi System Online.")
    print("Slash commands synced.")


# =========================================================
# WALLAHI DETECTION
# =========================================================

@bot.event
async def on_message(message):

    if message.author.bot:
        return

    if message.guild is None:
        await bot.process_commands(message)
        return

    # Check if Wallahi system is enabled
    if not get_guild_setting(message.guild.id):
        await bot.process_commands(message)
        return

    # Detect "wallahi" as a whole word
    if not re.search(r"\bwallahi\b", message.content, re.IGNORECASE):
        await bot.process_commands(message)
        return

    user_id = message.author.id
    balance = get_user(user_id)

    # User has no Wallahis
    if balance <= 0:

        try:
            await message.delete()
        except discord.Forbidden:
            pass

        await message.channel.send(
            f"{message.author.mention} lmfao, you have no wallahis left",
            delete_after=5
        )

        return

    # Remove 1 Wallahi
    balance -= 1
    set_wallahi(user_id, balance)

    await bot.process_commands(message)


# =========================================================
# /daily wallahi
# =========================================================

@bot.tree.command(
    name="daily",
    description="Claim your daily Wallahis."
)
@app_commands.describe(
    reward_type="The type of daily reward to claim."
)
@app_commands.choices(
    reward_type=[
        app_commands.Choice(
            name="wallahi",
            value="wallahi"
        )
    ]
)
async def daily(
    interaction: discord.Interaction,
    reward_type: app_commands.Choice[str]
):

    if reward_type.value != "wallahi":
        return

    user_id = interaction.user.id

    # 24 hours
    cooldown = 86400
    now = int(time.time())

    cursor.execute(
        "SELECT last_claim FROM daily WHERE user_id = ?",
        (user_id,)
    )

    result = cursor.fetchone()

    if result:
        last_claim = result[0]
        remaining = cooldown - (now - last_claim)

        if remaining > 0:
            hours = remaining // 3600
            minutes = (remaining % 3600) // 60

            await interaction.response.send_message(
                f"⏳ You already claimed your Wallahis!\n"
                f"Come back in **{hours}h {minutes}m**.",
                ephemeral=True
            )
            return

    reward = random.randint(1, 15)

    balance = get_user(user_id)
    new_balance = balance + reward

    set_wallahi(user_id, new_balance)

    cursor.execute(
        """
        INSERT INTO daily (user_id, last_claim)
        VALUES (?, ?)
        ON CONFLICT(user_id)
        DO UPDATE SET last_claim = excluded.last_claim
        """,
        (user_id, now)
    )

    db.commit()

    await interaction.response.send_message(
        f"🙏 You received **{reward} Wallahi(s)**!\n"
        f"You now have **{new_balance:,} Wallahis**."
    )


# =========================================================
# /toggle wallahi
# =========================================================

@bot.tree.command(
    name="toggle",
    description="Toggle the Wallahi system."
)
@app_commands.describe(
    system="The system to toggle.",
    state="Turn the system on or off."
)
@app_commands.choices(
    system=[
        app_commands.Choice(
            name="wallahi",
            value="wallahi"
        )
    ],
    state=[
        app_commands.Choice(
            name="on",
            value="on"
        ),
        app_commands.Choice(
            name="off",
            value="off"
        )
    ]
)
@app_commands.checks.has_permissions(manage_guild=True)
async def toggle(
    interaction: discord.Interaction,
    system: app_commands.Choice[str],
    state: app_commands.Choice[str]
):

    if system.value != "wallahi":
        return

    enabled = state.value == "on"

    set_guild_setting(
        interaction.guild.id,
        enabled
    )

    if enabled:
        await interaction.response.send_message(
            "✅ The **Wallahi System** has been enabled."
        )
    else:
        await interaction.response.send_message(
            "🔴 The **Wallahi System** has been disabled."
        )


# =========================================================
# /leaderboard
# =========================================================

@bot.tree.command(
    name="leaderboard",
    description="View the Wallahi leaderboard."
)
@app_commands.describe(
    leaderboard_type="Choose local or global leaderboard."
)
@app_commands.choices(
    leaderboard_type=[
        app_commands.Choice(
            name="local",
            value="local"
        ),
        app_commands.Choice(
            name="global",
            value="global"
        )
    ]
)
async def leaderboard(
    interaction: discord.Interaction,
    leaderboard_type: app_commands.Choice[str]
):

    # -----------------------------------------------------
    # LOCAL LEADERBOARD
    # -----------------------------------------------------

    if leaderboard_type.value == "local":

        members = interaction.guild.members

        user_ids = [member.id for member in members]

        if not user_ids:
            await interaction.response.send_message(
                "No users found."
            )
            return

        placeholders = ",".join("?" * len(user_ids))

        cursor.execute(
            f"""
            SELECT user_id, wallahis
            FROM users
            WHERE user_id IN ({placeholders})
            ORDER BY wallahis DESC
            LIMIT 10
            """,
            user_ids
        )

        results = cursor.fetchall()

        title = f"🏆 {interaction.guild.name} — Wallahi Leaderboard"

    # -----------------------------------------------------
    # GLOBAL LEADERBOARD
    # -----------------------------------------------------

    else:

        cursor.execute("""
            SELECT user_id, wallahis
            FROM users
            ORDER BY wallahis DESC
            LIMIT 10
        """)

        results = cursor.fetchall()

        title = "🌎 Global Wallahi Leaderboard"

    if not results:
        await interaction.response.send_message(
            "There isn't enough data yet."
        )
        return

    embed = discord.Embed(
        title=title,
        description="Top Wallahi holders.",
        color=discord.Color.dark_gray()
    )

    medals = ["🥇", "🥈", "🥉"]

    lines = []

    for index, (user_id, amount) in enumerate(results):

        member = interaction.guild.get_member(user_id)

        if member:
            name = member.display_name
        else:
            try:
                user = await bot.fetch_user(user_id)
                name = user.name
            except:
                name = f"User {user_id}"

        if index < 3:
            prefix = medals[index]
        else:
            prefix = f"`#{index + 1}`"

        lines.append(
            f"{prefix} **{name}** — `{amount:,} Wallahis`"
        )

    embed.description = "\n".join(lines)

    await interaction.response.send_message(
        embed=embed
    )


# =========================================================
# ERROR HANDLER
# =========================================================

@toggle.error
async def toggle_error(
    interaction: discord.Interaction,
    error
):

    if isinstance(
        error,
        app_commands.errors.MissingPermissions
    ):
        await interaction.response.send_message(
            "❌ You need **Manage Server** permission to use this.",
            ephemeral=True
        )


# =========================================================
# START BOT
# =========================================================

if not TOKEN:
    raise RuntimeError(
        "DISCORD_TOKEN environment variable is missing."
    )

bot.run(TOKEN)
