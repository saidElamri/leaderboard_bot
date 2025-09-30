# bot.py
import os
import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

import discord  
from  discord.ext import commands, tasks

import aiosqlite
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
EXERCISE_CHANNEL_ID = int(os.getenv("EXERCISE_CHANNEL_ID"))
SUBMISSIONS_CHANNEL_ID = int(os.getenv("SUBMISSIONS_CHANNEL_ID"))
TRAINER_ROLE_ID = int(os.getenv("TRAINER_ROLE_ID")) if os.getenv("TRAINER_ROLE_ID") else None
TZ_NAME = os.getenv("TZ", "UTC")
FRIDAY_HOUR = int(os.getenv("FRIDAY_HOUR", "20"))
FRIDAY_MINUTE = int(os.getenv("FRIDAY_MINUTE", "0"))

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

# ---------- DB helpers ----------
async def init_db():
    db = await aiosqlite.connect("leaderboard.db")
    db.row_factory = aiosqlite.Row
    await db.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY,
        total_xp INTEGER DEFAULT 0,
        monthly_xp INTEGER DEFAULT 0
    )""")
    await db.execute("""
    CREATE TABLE IF NOT EXISTS challenges (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT,
        content TEXT,
        posted_at TEXT,
        active INTEGER DEFAULT 1
    )""")
    await db.execute("""
    CREATE TABLE IF NOT EXISTS submissions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        challenge_id INTEGER,
        user_id INTEGER,
        content TEXT,
        submitted_at TEXT,
        judged INTEGER DEFAULT 0
    )""")
    await db.execute("""
    CREATE TABLE IF NOT EXISTS hall_of_fame (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        xp INTEGER,
        month TEXT
    )""")
    await db.execute("""
    CREATE TABLE IF NOT EXISTS meta (
        key TEXT PRIMARY KEY,
        value TEXT
    )""")
    await db.commit()
    return db

async def get_meta(key):
    async with bot.db.execute("SELECT value FROM meta WHERE key = ?", (key,)) as cur:
        row = await cur.fetchone()
    return row["value"] if row else None

async def set_meta(key, value):
    await bot.db.execute(
        "INSERT INTO meta (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )
    await bot.db.commit()

async def award_xp(user_id: int, amount: int):
    async with bot.db.execute("SELECT total_xp, monthly_xp FROM users WHERE id = ?", (user_id,)) as cur:
        row = await cur.fetchone()
    if row:
        await bot.db.execute(
            "UPDATE users SET total_xp = total_xp + ?, monthly_xp = monthly_xp + ? WHERE id = ?",
            (amount, amount, user_id),
        )
    else:
        await bot.db.execute(
            "INSERT INTO users (id, total_xp, monthly_xp) VALUES (?, ?, ?)",
            (user_id, amount, amount),
        )
    await bot.db.commit()

# ---------- startup ----------
@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")
    if not hasattr(bot, "db"):
        bot.db = await init_db()
    weekly_poster.start()
    monthly_reset.start()
    print("Tasks started.")

# ---------- posting weekly challenge ----------
async def create_and_post_challenge(title: str, content: str):
    posted_at = datetime.now(ZoneInfo(TZ_NAME)).isoformat()
    async with bot.db.execute(
        "INSERT INTO challenges (title, content, posted_at, active) VALUES (?, ?, ?, 1)",
        (title, content, posted_at),
    ):
        await bot.db.commit()
        async with bot.db.execute("SELECT last_insert_rowid() AS id") as r:
            row = await r.fetchone()
            challenge_id = row["id"] if row else None

    channel = bot.get_channel(EXERCISE_CHANNEL_ID) or await bot.fetch_channel(EXERCISE_CHANNEL_ID)
    embed = discord.Embed(title=title, description=content, color=discord.Color.teal())
    embed.set_footer(text=f"Submit in the submissions channel. Challenge ID: {challenge_id}")
    msg = await channel.send(embed=embed)
    return challenge_id, msg

@tasks.loop(minutes=1)
async def weekly_poster():
    tz = ZoneInfo(TZ_NAME)
    now = datetime.now(tz)
    if now.weekday() != 4:
        return
    if now.hour != FRIDAY_HOUR or now.minute != FRIDAY_MINUTE:
        return

    today_str = now.strftime("%Y-%m-%d")
    last = await get_meta("last_challenge_date")
    if last == today_str:
        return

    title = f"Weekly Coding Challenge — {now.strftime('%d %b %Y')}"
    content = "Post your solution in #code-wars-submissions. Trainers will review and pick top 3. Good luck!"
    challenge_id, _ = await create_and_post_challenge(title, content)
    await set_meta("last_challenge_date", today_str)
    print(f"Posted challenge {challenge_id} for {today_str}")

# ---------- submissions tracking ----------
@bot.event
async def on_message(message):
    if message.author.bot:
        return
    if message.channel.id == SUBMISSIONS_CHANNEL_ID:
        async with bot.db.execute(
            "SELECT id FROM challenges WHERE active = 1 ORDER BY posted_at DESC LIMIT 1"
        ) as cur:
            row = await cur.fetchone()
        if row:
            challenge_id = row["id"]
            submitted_at = datetime.now(ZoneInfo(TZ_NAME)).isoformat()
            content = f"{message.content}\n\nJump: {message.jump_url}"
            await bot.db.execute(
                "INSERT INTO submissions (challenge_id, user_id, content, submitted_at, judged) VALUES (?, ?, ?, ?, 0)",
                (challenge_id, message.author.id, content, submitted_at),
            )
            await bot.db.commit()
            try:
                await message.add_reaction("✅")
            except Exception:
                pass
    await bot.process_commands(message)

# ---------- helper checks ----------
def is_trainer():
    def predicate(ctx):
        print(
            f"DEBUG: ctx.guild={ctx.guild}, "
            f"ctx.author={ctx.author}, "
            f"ctx.author.id={getattr(ctx.author, 'id', None)}, "
            f"type(ctx.author)={type(ctx.author)}"
        )
        if not ctx.guild or not isinstance(ctx.author, discord.Member):
            print("DEBUG: Not in guild or not a Member")
            return False
        # Use your user ID here!
        if ctx.author.id == 490692921507446815:
            print("DEBUG: User ID matched, passing check")
            return True
        if TRAINER_ROLE_ID:
            result = any(r.id == TRAINER_ROLE_ID for r in ctx.author.roles)
            print(f"DEBUG: Trainer role check: {result}")
            return result
        result = ctx.author.guild_permissions.manage_guild
        print(f"DEBUG: manage_guild check: {result}")
        return result
    return commands.check(predicate)

# ---------- commands ----------
@bot.command()
@is_trainer()
async def post_challenge(ctx, title: str, *, content: str):
    """Trainer command to post a manual challenge.
    Usage: !post_challenge "Title here" Content here..."""
    challenge_id, msg = await create_and_post_challenge(title, content)
    await ctx.send(f"✅ Posted challenge #{challenge_id} in <#{EXERCISE_CHANNEL_ID}>")

@post_challenge.error
async def post_challenge_error(ctx, error):
    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.send('❌ Usage: `!post_challenge "Title here" Content here...`')
    else:
        await ctx.send(f"An error occurred: {error}")    

@bot.command()
@is_trainer()
async def close_challenge(ctx):
    """Close active challenge(s) so no more submissions count."""
    await bot.db.execute("UPDATE challenges SET active = 0 WHERE active = 1")
    await bot.db.commit()
    await ctx.send("✅ Closed current active challenge(s).")

@bot.command()
@is_trainer()
async def awardwinners(ctx, first: discord.Member, second: discord.Member = None, third: discord.Member = None):
    """Award top 3 for latest active challenge. Usage: !awardwinners @first @second @third"""
    async with bot.db.execute(
        "SELECT id FROM challenges WHERE active = 1 ORDER BY posted_at DESC LIMIT 1"
    ) as cur:
        row = await cur.fetchone()
    if not row:
        await ctx.send("❌ No active challenge found.")
        return
    challenge_id = row["id"]

    xp_map = {first.id: 10}
    if second:
        xp_map[second.id] = 7
    if third:
        xp_map[third.id] = 5

    for uid, xp in xp_map.items():
        await award_xp(uid, xp)
        await bot.db.execute(
            "UPDATE submissions SET judged = 1 WHERE challenge_id = ? AND user_id = ?",
            (challenge_id, uid),
        )
    await bot.db.commit()

    async with bot.db.execute(
        "SELECT DISTINCT user_id FROM submissions WHERE challenge_id = ? AND judged = 0",
        (challenge_id,),
    ) as cur:
        rows = await cur.fetchall()
    participants = [r["user_id"] for r in rows if r["user_id"] not in xp_map]
    for uid in participants:
        await award_xp(uid, 2)
        await bot.db.execute(
            "UPDATE submissions SET judged = 1 WHERE challenge_id = ? AND user_id = ?",
            (challenge_id, uid),
        )
    await bot.db.commit()

    await bot.db.execute("UPDATE challenges SET active = 0 WHERE id = ?", (challenge_id,))
    await bot.db.commit()

    def uname(uid):
        user = bot.get_user(uid)
        return user.name if user else str(uid)

    msg_lines = [f"🏅 {uname(uid)} +{xp} XP" for uid, xp in xp_map.items()]
    msg_lines += [f"✅ {uname(uid)} +2 XP (participation)" for uid in participants]
    await ctx.send("Awards applied:\n" + "\n".join(msg_lines))

@bot.command()
async def leaderboard(ctx):
    """Show monthly leaderboard (monthly_xp), XP to next rank, and badges."""
    # Fetch all users, ordered by monthly_xp DESC, up to 10 users
    async with bot.db.execute(
        "SELECT id, monthly_xp FROM users ORDER BY monthly_xp DESC, id ASC LIMIT 10"
    ) as cur:
        rows = await cur.fetchall()

    # If no users at all, show a message
    if not rows:
        await ctx.send("No users on the leaderboard yet. Participate in a challenge to earn XP!")
        return

    # Milestone badges
    def badge(xp, rank):
        if rank == 1:
            return "🥇"
        elif rank == 2:
            return "🥈"
        elif rank == 3:
            return "🥉"
        elif xp >= 50:
            return "💎"
        elif xp >= 20:
            return "⭐"
        else:
            return "🔸"

    # Calculate XP to next rank
    xp_list = [r["monthly_xp"] for r in rows]
    xp_list += [0] * (10 - len(xp_list))  # pad to 10 for next-rank calc
    embed = discord.Embed(title="📊 Monthly Leaderboard", color=discord.Color.gold())
    for idx, r in enumerate(rows, start=1):
        user_id = r["id"]
        xp = r["monthly_xp"]
        try:
            user = await bot.fetch_user(user_id)
            name = user.name
        except:
            name = str(user_id)
        # XP to next rank
        if idx < len(rows):
            next_xp = rows[idx]["monthly_xp"]
            xp_to_next = max(0, next_xp - xp + 1)
            next_rank = f"XP to next rank: {xp_to_next}"
        else:
            next_rank = "Top 10!"
        # Badge
        b = badge(xp, idx)
        embed.add_field(
            name=f"{b} {idx}. {name}",
            value=f"XP: {xp} | {next_rank}",
            inline=False
        )

    # Show users with 0 XP if less than 10 users are listed
    if len(rows) < 10:
        async with bot.db.execute(
            "SELECT id FROM users WHERE id NOT IN ({seq}) LIMIT {lim}".format(
                seq=",".join(str(r["id"]) for r in rows) if rows else "0",
                lim=10 - len(rows)
            )
        ) as cur:
            zero_rows = await cur.fetchall()
        for i, r in enumerate(zero_rows, start=len(rows)+1):
            try:
                user = await bot.fetch_user(r["id"])
                name = user.name
            except:
                name = str(r["id"])
            embed.add_field(
                name=f"🔸 {i}. {name}",
                value="XP: 0 | XP to next rank: ?",
                inline=False
            )

    await ctx.send(embed=embed)

@bot.command()
async def halloffame(ctx):
    """Show hall of fame (monthly snapshots accumulated)."""
    async with bot.db.execute(
        "SELECT user_id, SUM(xp) AS total FROM hall_of_fame GROUP BY user_id ORDER BY total DESC LIMIT 10"
    ) as cur:
        rows = await cur.fetchall()
    embed = discord.Embed(title="🏅 Hall of Fame", color=discord.Color.blue())
    for idx, r in enumerate(rows, start=1):
        user_id = r["user_id"]
        total = r["total"]
        try:
            user = await bot.fetch_user(user_id)
            name = user.name
        except:
            name = str(user_id)
        embed.add_field(name=f"{idx}. {name}", value=f"Total XP in Hall: {total}", inline=False)
    await ctx.send(embed=embed)

@bot.command()
@is_trainer()
async def lists(ctx):
    """List submissions for current active challenge."""
    async with bot.db.execute(
        "SELECT id FROM challenges WHERE active = 1 ORDER BY posted_at DESC LIMIT 1"
    ) as cur:
        row = await cur.fetchone()
    if not row:
        await ctx.send("No active challenge.")
        return
    challenge_id = row["id"]
    async with bot.db.execute(
        "SELECT user_id, content, submitted_at, judged FROM submissions WHERE challenge_id = ?",
        (challenge_id,),
    ) as cur:
        rows = await cur.fetchall()
    if not rows:
        await ctx.send("No submissions yet.")
        return
    lines = [
        f"<@{r['user_id']}> — judged: {r['judged']} — {r['submitted_at']}"
        for r in rows
    ]
    for i in range(0, len(lines), 20):
        await ctx.send("\n".join(lines[i:i+20]))

@bot.command()
@is_trainer()
async def list_users(ctx):
    """List all users stored in the XP database."""
    async with bot.db.execute(
        "SELECT id, total_xp, monthly_xp FROM users ORDER BY total_xp DESC"
    ) as cur:
        rows = await cur.fetchall()
    if not rows:
        await ctx.send("No users in database yet.")
        return
    lines = []
    for r in rows:
        user_id = r["id"]
        total = r["total_xp"]
        monthly = r["monthly_xp"]
        try:
            user = await bot.fetch_user(user_id)
            name = user.name
        except:
            name = str(user_id)
        lines.append(f"{name} — Total XP: {total} | Monthly XP: {monthly}")
    for i in range(0, len(lines), 20):
        await ctx.send("\n".join(lines[i:i+20]))

# NEW: List all server members (not just those in the XP database)
@bot.command()
@is_trainer()
async def list_server_members(ctx):
    """List all members in the server (fetches if not cached)."""
    members = []
    async for member in ctx.guild.fetch_members(limit=None):
        members.append(f"{member.name}#{member.discriminator} ({member.id})")
    if not members:
        await ctx.send("No members found.")
        return
    for i in range(0, len(members), 20):
        await ctx.send("\n".join(members[i:i+20]))

# feedback command
@bot.command()
@is_trainer()
async def feedback(ctx, user: discord.Member, *, message: str):
    """Send feedback to a user about their submission. Usage: !feedback @user Your feedback here..."""
    try:
        await user.send(f"📢 Feedback from {ctx.guild.name} formateur:\n{message}")
        await ctx.send(f"✅ Feedback sent to {user.mention} via DM.")
    except Exception as e:
        await ctx.send(f"❌ Could not send DM to {user.mention}. Error: {e}")


# override help
bot.remove_command("help")

@bot.command(name="help")
async def my_help(ctx):
    """Show all commands and how to use them."""
    embed = discord.Embed(title="📖 Bot Commands", color=discord.Color.green())
    for command in bot.commands:
        if command.hidden:
            continue
        desc = command.help or "No description"
        embed.add_field(name=f"!{command.name}", value=desc, inline=False)
    await ctx.send(embed=embed)

# ---------- monthly reset ----------
@tasks.loop(hours=24)
async def monthly_reset():
    tz = ZoneInfo(TZ_NAME)
    now = datetime.now(tz)
    current_month = now.strftime("%Y-%m")
    last_reset = await get_meta("last_monthly_reset")
    if now.day == 1 and last_reset != current_month:
        async with bot.db.execute("SELECT id, monthly_xp FROM users WHERE monthly_xp > 0") as cur:
            rows = await cur.fetchall()
        for r in rows:
            user_id = r["id"]
            xp = r["monthly_xp"]
            await bot.db.execute(
                "INSERT INTO hall_of_fame (user_id, xp, month) VALUES (?, ?, ?)",
                (user_id, xp, now.strftime("%B %Y")),
            )
        await bot.db.execute("UPDATE users SET monthly_xp = 0")
        await bot.db.commit()
        await set_meta("last_monthly_reset", current_month)
        print(f"Monthly reset done for {now.strftime('%B %Y')}")

# ---------- run ----------
if __name__ == "__main__":
    bot.run(BOT_TOKEN)