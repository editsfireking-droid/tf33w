import os
import sqlite3
import asyncio
from datetime import datetime, timedelta, timezone

import discord
from discord.ext import commands

# ============================================================
# BLOXY PLAZA - simple Discord invite rewards bot
# Python + discord.py
# ============================================================

TOKEN = os.getenv("DISCORD_TOKEN", "")
PREFIX = os.getenv("PREFIX", "!")

# Put the IDs from your server into Railway Variables.
GUILD_ID = int(os.getenv("GUILD_ID", "0"))

INVITE_LOG_CHANNEL_ID = int(os.getenv("INVITE_LOG_CHANNEL_ID", "0"))
INVITE_CHECK_CHANNEL_ID = int(os.getenv("INVITE_CHECK_CHANNEL_ID", "0"))
CLAIM_CHANNEL_ID = int(os.getenv("CLAIM_CHANNEL_ID", "0"))
GUIDE_CHANNEL_ID = int(os.getenv("GUIDE_CHANNEL_ID", "0"))
BOOST_CHANNEL_ID = int(os.getenv("BOOST_CHANNEL_ID", "0"))
REWARDS_CHANNEL_ID = int(os.getenv("REWARDS_CHANNEL_ID", "0"))

VERIFIED_ROLE_ID = int(os.getenv("VERIFIED_ROLE_ID", "0"))
ADMIN_ROLE_ID = int(os.getenv("ADMIN_ROLE_ID", "0"))

# Persistent SQLite database.
# On Railway, use a Volume mounted at /data so this survives redeploys.
DB_PATH = os.getenv("DB_PATH", "/data/bloxy_plaza.db")

# Custom emojis supplied by you.
ROB_EMOJI = "<:rob:1546469221184311336>"
BOX_EMOJI = "<:box:1546469835163041792>"

VERIFY_URL = "https://bloxlink.gr/verify?server=4072224305994532"

# Reward tiers from your screenshot.
INVITE_REWARDS = {
    3: 2500,
    5: 5000,
    7: 7500,
    9: 10000,
}

BOOST_REWARDS = {
    1: 1250,
    2: 3000,
}

MIN_ACCOUNT_AGE = timedelta(days=30)


# -------------------- DATABASE --------------------

def db():
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS invite_counts (
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            invites INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (guild_id, user_id)
        );

        CREATE TABLE IF NOT EXISTS claims (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            tier INTEGER NOT NULL,
            reward INTEGER NOT NULL,
            claimed_at TEXT NOT NULL,
            UNIQUE(guild_id, user_id, tier)
        );
    """)
    conn.commit()
    conn.close()


def get_invites(guild_id, user_id):
    conn = db()
    row = conn.execute(
        "SELECT invites FROM invite_counts WHERE guild_id=? AND user_id=?",
        (guild_id, user_id)
    ).fetchone()
    conn.close()
    return row["invites"] if row else 0


def add_invite(guild_id, user_id):
    conn = db()
    conn.execute("""
        INSERT INTO invite_counts (guild_id, user_id, invites)
        VALUES (?, ?, 1)
        ON CONFLICT(guild_id, user_id)
        DO UPDATE SET invites = invites + 1
    """, (guild_id, user_id))
    conn.commit()
    conn.close()


def has_claimed(guild_id, user_id, tier):
    conn = db()
    row = conn.execute(
        "SELECT 1 FROM claims WHERE guild_id=? AND user_id=? AND tier=?",
        (guild_id, user_id, tier)
    ).fetchone()
    conn.close()
    return row is not None


def add_claim(guild_id, user_id, tier, reward):
    conn = db()
    try:
        conn.execute(
            """INSERT INTO claims
               (guild_id, user_id, tier, reward, claimed_at)
               VALUES (?, ?, ?, ?, ?)""",
            (
                guild_id,
                user_id,
                tier,
                reward,
                datetime.now(timezone.utc).isoformat()
            )
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()


def get_claims(guild_id, user_id):
    conn = db()
    rows = conn.execute(
        """SELECT tier, reward, claimed_at
           FROM claims
           WHERE guild_id=? AND user_id=?
           ORDER BY id DESC""",
        (guild_id, user_id)
    ).fetchall()
    conn.close()
    return rows


# -------------------- EMBEDS --------------------

def make_embed(title, description="", color=discord.Color.blurple()):
    return discord.Embed(
        title=title,
        description=description,
        color=color,
        timestamp=datetime.now(timezone.utc)
    )


def reward_text(invites):
    if invites >= 9:
        return f"{BOX_EMOJI} **10,000** {ROB_EMOJI}"
    if invites >= 7:
        return f"{BOX_EMOJI} **7,500** {ROB_EMOJI}"
    if invites >= 5:
        return f"{BOX_EMOJI} **5,000** {ROB_EMOJI}"
    if invites >= 3:
        return f"{BOX_EMOJI} **2,500** {ROB_EMOJI}"
    return "No reward unlocked yet."


def verified(member):
    if VERIFIED_ROLE_ID == 0:
        return True
    return any(role.id == VERIFIED_ROLE_ID for role in member.roles)


# -------------------- BOT --------------------

intents = discord.Intents.default()
intents.members = True
intents.guilds = True
intents.message_content = True

bot = commands.Bot(
    command_prefix=PREFIX,
    intents=intents,
    help_command=None,
    case_insensitive=True
)

# invite code -> uses / inviter id
invite_cache = {}


async def refresh_invites(guild):
    try:
        invites = await guild.invites()
        invite_cache[guild.id] = {
            invite.code: {
                "uses": invite.uses or 0,
                "inviter_id": invite.inviter.id if invite.inviter else None,
            }
            for invite in invites
        }
    except (discord.Forbidden, discord.HTTPException):
        invite_cache[guild.id] = {}


async def find_used_invite(guild):
    """Return (invite_code, inviter_id) for the invite whose use count rose."""
    try:
        current = await guild.invites()
    except (discord.Forbidden, discord.HTTPException):
        return None, None

    old = invite_cache.get(guild.id, {})
    found = None

    for invite in current:
        old_uses = old.get(invite.code, {}).get("uses", 0)
        new_uses = invite.uses or 0

        if new_uses > old_uses:
            inviter_id = invite.inviter.id if invite.inviter else None
            found = (invite.code, inviter_id)
            break

    # Update cache immediately.
    invite_cache[guild.id] = {
        invite.code: {
            "uses": invite.uses or 0,
            "inviter_id": invite.inviter.id if invite.inviter else None,
        }
        for invite in current
    }

    return found if found else (None, None)


@bot.event
async def on_ready():
    init_db()

    # Persistent buttons survive bot restarts.
    if not getattr(bot, "_bloxy_panel_added", False):
        bot.add_view(InvitePanel())
        bot._bloxy_panel_added = True

    for guild in bot.guilds:
        await refresh_invites(guild)

    print(f"Logged in as {bot.user} | Bloxy Plaza is online.")


@bot.event
async def on_guild_join(guild):
    await refresh_invites(guild)


@bot.event
async def on_member_join(member):
    if member.bot:
        return

    # Give Discord a moment to update invite usage before checking.
    await asyncio.sleep(1.5)

    code, inviter_id = await find_used_invite(member.guild)

    log_channel = bot.get_channel(INVITE_LOG_CHANNEL_ID)

    # Could not identify an invite.
    if inviter_id is None:
        if log_channel:
            embed = make_embed(
                "📥 Invite detected",
                f"{member.mention} joined, but I **couldn't identify the invite** used.",
                discord.Color.orange()
            )
            await log_channel.send(embed=embed)
        return

    inviter = member.guild.get_member(inviter_id)

    # Never count self/bot invites.
    if inviter is None or inviter.bot or inviter.id == member.id:
        return

    account_age = datetime.now(timezone.utc) - member.created_at

    if account_age < MIN_ACCOUNT_AGE:
        if log_channel:
            embed = make_embed(
                "🚫 Invite not counted",
                (
                    f"{member.mention} was invited by {inviter.mention}, "
                    f"but the account is **less than 1 month old**.\n\n"
                    "This invite **does not count** toward rewards."
                ),
                discord.Color.red()
            )
            await log_channel.send(embed=embed)
        return

    add_invite(member.guild.id, inviter.id)
    total = get_invites(member.guild.id, inviter.id)

    if log_channel:
        embed = make_embed(
            "📨 New valid invite",
            (
                f"{member.mention} has been invited by {inviter.mention}\n\n"
                f"**Valid invites:** `{total}`\n"
                f"**Next reward:** {reward_text(total)}"
            ),
            discord.Color.green()
        )
        await log_channel.send(embed=embed)


# -------------------- USER COMMANDS --------------------

@bot.command(name="verify")
async def verify_cmd(ctx):
    embed = make_embed(
        "✅ Verify with Bloxlink",
        (
            "**Verification is required to claim rewards.**\n\n"
            "Verification helps us confirm that you are a real member and "
            "keeps the reward system safer from fake accounts and abuse.\n\n"
            "**How to verify:**\n"
            "1. Press the **Verify** button below.\n"
            "2. Complete the Bloxlink verification.\n"
            "3. Return to **Bloxy Plaza**.\n"
            "4. You can then use the reward system.\n\n"
            "*Never give your Discord password or token to anyone.*"
        ),
        discord.Color.blurple()
    )

    view = discord.ui.View(timeout=None)
    view.add_item(discord.ui.Button(
        label="Verify",
        style=discord.ButtonStyle.link,
        url=VERIFY_URL,
        emoji="✅"
    ))

    await ctx.send(embed=embed, view=view)


@bot.command(name="claim")
async def claim_cmd(ctx, tier: int = 0):
    if CLAIM_CHANNEL_ID and ctx.channel.id != CLAIM_CHANNEL_ID:
        embed = make_embed(
            "📦 Use the claim channel",
            f"Please use <#{CLAIM_CHANNEL_ID}> to claim your reward.",
            discord.Color.orange()
        )
        await ctx.send(embed=embed)
        return

    if tier not in INVITE_REWARDS:
        embed = make_embed(
            "❌ Invalid reward",
            (
                f"Use `{PREFIX}claim 3`, `{PREFIX}claim 5`, "
                f"`{PREFIX}claim 7`, or `{PREFIX}claim 9`."
            ),
            discord.Color.red()
        )
        await ctx.send(embed=embed)
        return

    if not isinstance(ctx.author, discord.Member):
        return

    if not verified(ctx.author):
        embed = make_embed(
            "🔒 Verification required",
            f"Please run `{PREFIX}verify` and complete verification before claiming.",
            discord.Color.red()
        )
        await ctx.send(embed=embed)
        return

    invites = get_invites(ctx.guild.id, ctx.author.id)

    if invites < tier:
        reward = INVITE_REWARDS[tier]
        embed = make_embed(
            "❌ Not enough invites",
            (
                f"You need **{tier} valid invites** for this reward.\n"
                f"You currently have **{invites} valid invites**.\n\n"
                f"Reward: **{reward:,}** {ROB_EMOJI}"
            ),
            discord.Color.red()
        )
        await ctx.send(embed=embed)
        return

    if has_claimed(ctx.guild.id, ctx.author.id, tier):
        embed = make_embed(
            "⚠️ Already claimed",
            f"You have already claimed the **{tier}-invite** reward.",
            discord.Color.orange()
        )
        await ctx.send(embed=embed)
        return

    reward = INVITE_REWARDS[tier]

    if not add_claim(ctx.guild.id, ctx.author.id, tier, reward):
        embed = make_embed(
            "⚠️ Already claimed",
            "That reward was already claimed.",
            discord.Color.orange()
        )
        await ctx.send(embed=embed)
        return

    embed = make_embed(
        "🎉 Reward claim submitted",
        (
            f"**{ctx.author.mention}**, your claim has been recorded!\n\n"
            f"**Tier:** {tier} valid invites\n"
            f"**Reward:** **{reward:,}** {ROB_EMOJI}\n\n"
            "*Staff can now process your reward.*"
        ),
        discord.Color.green()
    )
    await ctx.send(embed=embed)


# -------------------- PANEL BUTTONS --------------------

class InvitePanel(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="My Stats",
        style=discord.ButtonStyle.secondary,
        custom_id="bloxy:my_stats"
    )
    async def my_stats(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.guild:
            return

        invites = get_invites(interaction.guild.id, interaction.user.id)

        next_tier = next((tier for tier in INVITE_REWARDS if invites < tier), None)
        if next_tier:
            progress = f"**{invites}/{next_tier}** valid invites"
        else:
            progress = "**All invite tiers unlocked** 🎉"

        embed = make_embed(
            "📊 Your Invite Stats",
            (
                f"**Member:** {interaction.user.mention}\n\n"
                f"**Valid invites:** `{invites}`\n"
                f"**Progress:** {progress}\n"
                f"**Best unlocked reward:** {reward_text(invites)}\n\n"
                f"Go to <#{CLAIM_CHANNEL_ID}> and use `{PREFIX}claim <tier>` to claim."
            ),
            discord.Color.blurple()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(
        label="Claims History",
        style=discord.ButtonStyle.secondary,
        custom_id="bloxy:claims_history"
    )
    async def claims_history(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.guild:
            return

        rows = get_claims(interaction.guild.id, interaction.user.id)

        if not rows:
            description = "**No claims yet.**\n\nYour completed claims will appear here."
        else:
            lines = []
            for row in rows[:10]:
                date = row["claimed_at"].replace("T", " ")[:16]
                lines.append(
                    f"• **{row['tier']} invites** — **{row['reward']:,}** {ROB_EMOJI} — `{date} UTC`"
                )
            description = "\n".join(lines)

        embed = make_embed(
            "📜 Claims History",
            description,
            discord.Color.blurple()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


# -------------------- ADMIN POST COMMANDS --------------------

def admin_only():
    async def predicate(ctx):
        if ctx.author.guild_permissions.administrator:
            return True
        if ADMIN_ROLE_ID and any(role.id == ADMIN_ROLE_ID for role in ctx.author.roles):
            return True
        raise commands.CheckFailure
    return commands.check(predicate)


@bot.command(name="postpanel")
@admin_only()
async def postpanel(ctx):
    embed = make_embed(
        "🎁 Invite Rewards",
        (
            "Invite friends, grow the community, and unlock **Robux rewards**.\n\n"
            "**How to earn invites**\n"
            "1. Create your Discord invite link.\n"
            "2. Share it with your friends or social media.\n"
            "3. When someone joins through your invite, the bot checks the account.\n"
            "4. Track your progress with **My Stats** below.\n\n"
            "**Rules**\n"
            "• **No bots or alts.**\n"
            "• The invited account must be **at least 1 month old**.\n"
            "• Fake/invalid invites will not count.\n"
            "• Leave-and-rejoin abuse may be removed from the system.\n\n"
            "**Claiming**\n"
            f"Go to <#{CLAIM_CHANNEL_ID}> and use `{PREFIX}claim <tier>`.\n"
            f"Example: `{PREFIX}claim 3`"
        ),
        discord.Color.blurple()
    )

    embed.add_field(
        name="🎁 Invite Rewards",
        value=(
            f"**3 Invites** → **2,500** {ROB_EMOJI} {BOX_EMOJI}\n"
            f"**5 Invites** → **5,000** {ROB_EMOJI} {BOX_EMOJI}\n"
            f"**7 Invites** → **7,500** {ROB_EMOJI} {BOX_EMOJI}\n"
            f"**9 Invites** → **10,000** {ROB_EMOJI} {BOX_EMOJI}"
        ),
        inline=False
    )

    target = bot.get_channel(INVITE_CHECK_CHANNEL_ID) or ctx.channel
    await target.send(embed=embed, view=InvitePanel())


@bot.command(name="postboost")
@admin_only()
async def postboost(ctx):
    embed = make_embed(
        "🚀 Boost Rewards",
        (
            "Support **Bloxy Plaza** by boosting the server and unlock "
            "special Robux rewards!\n\n"
            f"**1 Boost** → **1,250** {ROB_EMOJI}\n"
            f"**2 Boosts** → **3,000** {ROB_EMOJI}\n\n"
            "*Boost rewards are subject to staff verification.*"
        ),
        discord.Color.purple()
    )
    target = bot.get_channel(BOOST_CHANNEL_ID) or ctx.channel
    await target.send(embed=embed)


@bot.command(name="postrewards")
@admin_only()
async def postrewards(ctx):
    embed = make_embed(
        "🎁 Roblox Rewards",
        (
            f"**3 Invites** → **2,500** {ROB_EMOJI} {BOX_EMOJI}\n"
            f"**5 Invites** → **5,000** {ROB_EMOJI} {BOX_EMOJI}\n"
            f"**7 Invites** → **7,500** {ROB_EMOJI} {BOX_EMOJI}\n"
            f"**9 Invites** → **10,000** {ROB_EMOJI} {BOX_EMOJI}"
        ),
        discord.Color.blurple()
    )
    target = bot.get_channel(REWARDS_CHANNEL_ID) or ctx.channel
    await target.send(embed=embed)


@bot.command(name="postguide")
@admin_only()
async def postguide(ctx):
    embed = make_embed(
        "📖 Bloxy Plaza Invite Guide",
        (
            "**How to invite people**\n"
            "1. Right-click the **Bloxy Plaza** server icon.\n"
            "2. Select **Invite People**.\n"
            "3. Create your invite link.\n"
            "4. Share it with your friends or social media.\n"
            "5. When they join, the bot automatically checks the invite.\n\n"
            "**How to claim**\n"
            f"1. Make sure you are verified with `{PREFIX}verify`.\n"
            f"2. Check your progress using **My Stats** in the invite panel.\n"
            f"3. Go to <#{CLAIM_CHANNEL_ID}>.\n"
            f"4. Use `{PREFIX}claim 3`, `{PREFIX}claim 5`, `{PREFIX}claim 7`, or `{PREFIX}claim 9`.\n\n"
            "**Important rules**\n"
            "• **No alts.**\n"
            "• The account you invite must be **1 month old or older**.\n"
            "• **Bots do not count.**\n"
            "• Fake/invalid invites do not count.\n"
            "• Invite tracking is automatic.\n\n"
            "*Trying to abuse the system may result in your invites being removed.*"
        ),
        discord.Color.blurple()
    )
    target = bot.get_channel(GUIDE_CHANNEL_ID) or ctx.channel
    await target.send(embed=embed)


# -------------------- ERRORS --------------------

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return

    if isinstance(error, commands.CheckFailure):
        embed = make_embed(
            "🔒 No permission",
            "You do not have permission to use this command.",
            discord.Color.red()
        )
        await ctx.send(embed=embed)
        return

    if isinstance(error, commands.MissingRequiredArgument):
        embed = make_embed(
            "❌ Missing information",
            f"Usage: `{PREFIX}{ctx.command.name} {ctx.command.signature}`",
            discord.Color.red()
        )
        await ctx.send(embed=embed)
        return

    if isinstance(error, commands.BadArgument):
        embed = make_embed(
            "❌ Invalid input",
            "Please check the command and try again.",
            discord.Color.red()
        )
        await ctx.send(embed=embed)
        return

    print(f"[COMMAND ERROR] {repr(error)}")


# -------------------- START --------------------

if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN is missing. Add it to Railway Variables.")

init_db()
bot.run(TOKEN)
