import discord
from discord import app_commands
from discord.ext import commands, tasks
import os
import math
import asyncio
from functools import lru_cache
from dotenv import load_dotenv
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from keep_alive import keep_alive
from database import init_db

from database import (
    add_anime, update_progress, update_status, get_progress, 
    list_tracked, get_aliases, get_all_tracked, 
    update_last_notified, remove_anime, update_alias
)
from anilist import search_anime, search_anime_by_id, get_seasonal_anime

# ---------------- CONFIGURATION ----------------
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = int(os.getenv("GUILD_ID"))
raw_role_id = os.getenv("ALERT_ROLE_ID")
ALERT_ROLE_ID = int(raw_role_id) if raw_role_id and raw_role_id.strip() else None
TIMEZONE = os.getenv("TIMEZONE", "America/New_York")
ITEMS_PER_PAGE = 10

GENRE_EMOJIS = {
    "Action": "⚔️", "Adventure": "🗺️", "Comedy": "😂", "Drama": "🎭",
    "Fantasy": "🧙", "Romance": "💖", "Slice of Life": "🏠", "Sci-Fi": "🤖",
    "Horror": "👻", "Mystery": "🕵️"
}

SEASONS = ["WINTER", "SPRING", "SUMMER", "FALL"]

# Cache AniList lookups for 10 minutes to reduce API latency
@lru_cache(maxsize=128)
def cached_search_id(anime_id):
    return search_anime_by_id(anime_id)

def current_season_year():
    now = datetime.now(ZoneInfo(TIMEZONE))
    m = now.month
    if m <= 3: return "WINTER", now.year
    elif m <= 6: return "SPRING", now.year
    elif m <= 9: return "SUMMER", now.year
    else: return "FALL", now.year

def format_genres(genres):
    return " ".join([GENRE_EMOJIS[g] for g in genres if g in GENRE_EMOJIS])

# ---------------- BOT SETUP ----------------
class MyBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.members = True 
        intents.message_content = True
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        guild = discord.Object(id=GUILD_ID)
        self.tree.copy_global_to(guild=guild)
        await self.tree.sync(guild=guild)
        if not check_new_episodes.is_running():
            check_new_episodes.start()
        print(f"✅ Bot is synced and background tasks started.")

bot = MyBot()

@bot.event
async def on_ready():
    init_db()
    print(f"Logged in as {bot.user}")

GOJO_GIF_URL = "https://giphy.com/gifs/jujutsu-kaisen-kilianirl-WDH0KOD68mVzqTrfFr"

@bot.event
async def on_message(message):
    if message.author == bot.user:
        return

    content = message.content.lower()
    if "gojo" in content:
        await message.channel.send(f"I'm right here bbg\n{GOJO_GIF_URL}")
    elif bot.user in message.mentions:
        await message.channel.send(f"Yes, {message.author.mention}? You summoned me?")

    await bot.process_commands(message)

# ---------------- UI COMPONENTS ----------------
class ListView(discord.ui.View):
    def __init__(self, owner, rows, status="watching", page=0):
        super().__init__(timeout=180)
        self.owner = owner
        self.rows = rows
        self.status = status
        self.page = page
        self.preview_mode = False
        self.preview_index = 0
        self.update_controls()

    def get_filtered(self):
        return [r for r in self.rows if r[3] == self.status]

    def max_pages(self):
        return max(1, math.ceil(len(self.get_filtered()) / ITEMS_PER_PAGE))

    def page_rows(self):
        start = self.page * ITEMS_PER_PAGE
        return self.get_filtered()[start:start + ITEMS_PER_PAGE]

    def build_list_embed(self):
        items = [f"**{n}** (`{a}`) → Ep {e}" for n, a, e, _ in self.page_rows()]
        embed = discord.Embed(
            title=f"📺 {self.owner.display_name}'s {self.status.replace('_', ' ').title()} List",
            description="\n".join(items) if items else "No anime here.",
            color=0x9b59b6,
        )
        embed.set_footer(text=f"Page {self.page + 1}/{self.max_pages()}")
        return embed

    async def build_preview_embed(self):
        rows = self.page_rows()
        if not rows:
            return discord.Embed(title="Preview", description="No anime to preview.", color=0x9b59b6)

        name, alias, ep, _ = rows[self.preview_index]
        prog = get_progress(self.owner.id, alias)
        if not prog:
            return discord.Embed(title="Preview", description=f"Not tracking {name}.", color=0x9b59b6)

        # Use cached ID search for speed
        data = cached_search_id(prog[3])
        embed = discord.Embed(title=f"📺 {name}", description=f"Episode {ep}", color=0x5865F2)
        if data and data.get("coverImage", {}).get("large"):
            embed.set_image(url=data["coverImage"]["large"])
        embed.set_footer(text=f"Preview {self.preview_index + 1}/{len(rows)} - Page {self.page + 1}/{self.max_pages()}")
        return embed

    def update_controls(self):
        if self.preview_mode:
            self.prev.disabled = (self.preview_index == 0)
            self.next.disabled = (self.preview_index >= len(self.page_rows()) - 1)
        else:
            self.prev.disabled = (self.page == 0)
            self.next.disabled = (self.page >= self.max_pages() - 1)
        self.zoom.label = "↩️" if self.preview_mode else "🔍"

    @discord.ui.select(
        placeholder="Filter status",
        options=[
            discord.SelectOption(label="Watching", value="watching", emoji="📺"),
            discord.SelectOption(label="Watched", value="watched", emoji="✅"),
            discord.SelectOption(label="Want to Watch", value="want_to_watch", emoji="⭐"),
        ],
    )
    async def select_status(self, interaction: discord.Interaction, select: discord.ui.Select):
        self.status = select.values[0]
        self.page = 0
        self.preview_mode = False
        self.update_controls()
        await interaction.response.edit_message(embed=self.build_list_embed(), view=self)

    @discord.ui.button(label="◀", style=discord.ButtonStyle.gray)
    async def prev(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.preview_mode: self.preview_index -= 1
        else: self.page -= 1
        self.update_controls()
        embed = await self.build_preview_embed() if self.preview_mode else self.build_list_embed()
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="▶", style=discord.ButtonStyle.gray)
    async def next(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.preview_mode: self.preview_index += 1
        else: self.page += 1
        self.update_controls()
        embed = await self.build_preview_embed() if self.preview_mode else self.build_list_embed()
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="🔍", style=discord.ButtonStyle.blurple)
    async def zoom(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.page_rows():
            return await interaction.response.send_message("No anime to preview.", ephemeral=True)
        self.preview_mode = not self.preview_mode
        self.preview_index = 0 
        self.update_controls()
        embed = await self.build_preview_embed() if self.preview_mode else self.build_list_embed()
        await interaction.response.edit_message(embed=embed, view=self)

class SeasonalView(discord.ui.View):
    def __init__(self, user_id, season, year):
        super().__init__(timeout=180)
        self.user_id = user_id
        self.season = season
        self.year = year
        self.page = 0
        self.preview_mode = False
        self.preview_index = 0
        self.data = get_seasonal_anime(season, year)
        self.tracked_ids = {uid[1] for uid in get_all_tracked() if uid[0] == user_id}
        self.update_controls()

    def max_pages(self):
        return max(1, math.ceil(len(self.data) / ITEMS_PER_PAGE))

    def page_slice(self):
        start = self.page * ITEMS_PER_PAGE
        return self.data[start : start + ITEMS_PER_PAGE]

    def build_list_embed(self):
        lines = []
        for a in self.page_slice():
            mark = "✅ " if a["id"] in self.tracked_ids else ""
            eps = a.get("episodes") or "?"
            lines.append(f"{mark}**{a['title']['romaji']}** — {eps} eps")

        embed = discord.Embed(
            title=f"📡 {self.season.title()} {self.year} Seasonal",
            description="\n".join(lines) if lines else "No anime found.",
            color=0xF39C12,
        )
        embed.set_footer(text=f"Page {self.page + 1}/{self.max_pages()}")
        return embed

    def build_preview_embed(self):
        page = self.page_slice()
        if not page:
            return discord.Embed(title="Preview", description="No anime found.", color=0xF39C12)

        a = page[self.preview_index]
        embed = discord.Embed(
            title=f"📡 {a['title']['romaji']}",
            description=(a.get("description") or "No description.")[:1000],
            color=0x5865F2,
        )
        if a.get("genres"):
            embed.add_field(name="Genres", value=format_genres(a["genres"]), inline=False)
        if a.get("coverImage", {}).get("medium"):
            embed.set_image(url=a["coverImage"]["medium"])
        embed.set_footer(text=f"Preview {self.preview_index + 1}/{len(page)} - Page {self.page + 1}/{self.max_pages()}")
        return embed

    def update_controls(self):
        if self.preview_mode:
            self.prev.disabled = self.preview_index == 0
            self.next.disabled = self.preview_index >= len(self.page_slice()) - 1
        else:
            self.prev.disabled = self.page == 0
            self.next.disabled = self.page >= self.max_pages() - 1
        self.zoom.label = "↩️" if self.preview_mode else "🔍"

    @discord.ui.select(
        placeholder="Change season",
        options=[discord.SelectOption(label=s.title(), value=s) for s in SEASONS],
    )
    async def season_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        self.season = select.values[0]
        self.page = 0
        self.preview_mode = False
        self.data = get_seasonal_anime(self.season, self.year)
        self.update_controls()
        await interaction.response.edit_message(embed=self.build_list_embed(), view=self)

    @discord.ui.button(label="◀", style=discord.ButtonStyle.gray)
    async def prev(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.preview_mode: self.preview_index -= 1
        else: self.page -= 1
        self.update_controls()
        embed = self.build_preview_embed() if self.preview_mode else self.build_list_embed()
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="▶", style=discord.ButtonStyle.gray)
    async def next(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.preview_mode: self.preview_index += 1
        else: self.page += 1
        self.update_controls()
        embed = self.build_preview_embed() if self.preview_mode else self.build_list_embed()
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="🔍", style=discord.ButtonStyle.blurple)
    async def zoom(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.page_slice(): return
        self.preview_mode = not self.preview_mode
        self.preview_index = 0
        self.update_controls()
        embed = self.build_preview_embed() if self.preview_mode else self.build_list_embed()
        await interaction.response.edit_message(embed=embed, view=self)

# ---------------- COMMANDS ----------------

@bot.tree.command(name="list", description="View a user's tracked anime")
async def list_cmd(interaction: discord.Interaction, user: discord.User = None):
    target = user or interaction.user
    rows = list_tracked(target.id)
    if not rows:
        return await interaction.response.send_message("No tracked anime.")
    view = ListView(target, rows)
    await interaction.response.send_message(embed=view.build_list_embed(), view=view)

@bot.tree.command(name="progress", description="Check detailed progress for an anime")
async def progress(interaction: discord.Interaction, identifier: str):
    prog = get_progress(interaction.user.id, identifier)
    if not prog:
        return await interaction.response.send_message(f"❌ Not tracking '{identifier}'.", ephemeral=True)

    name, alias, last_watched, anime_id, status = prog
    data = cached_search_id(anime_id)
    if not data:
        return await interaction.response.send_message("❌ AniList error.", ephemeral=True)

    embed = discord.Embed(title=f"📺 {name} ({alias})", description=(data.get("description") or "No description.")[:1000], color=0x3498db)
    embed.add_field(name="Progress", value=f"**Status:** {status.title()}\n**Watched:** Ep {last_watched}", inline=False)
    
    if data.get("episodes"):
        embed.add_field(name="Total", value=str(data["episodes"]), inline=True)
    
    genres = format_genres(data.get("genres", []))
    if genres:
        embed.add_field(name="Genres", value=genres, inline=True)

    next_ep = data.get("nextAiringEpisode")
    if next_ep:
        ts = datetime.fromtimestamp(next_ep["airingAt"], tz=timezone.utc).astimezone(ZoneInfo(TIMEZONE))
        embed.add_field(name="Next Episode", value=f"Ep {next_ep['episode']} — {ts.strftime('%Y-%m-%d %H:%M')}", inline=False)

    if data.get("coverImage", {}).get("large"):
        embed.set_thumbnail(url=data["coverImage"]["large"])

    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="track", description="Start tracking a new anime")
async def track(interaction: discord.Interaction, anime: str, alias: str = None, episode: int = 0):
    await interaction.response.defer() # Search takes time
    data = search_anime(anime)
    if not data:
        return await interaction.followup.send("❌ Anime not found.")

    title = data["title"]["romaji"]
    final_alias = alias or "".join([w[0] for w in title.split() if w]).upper()
    add_anime(interaction.user.id, data["id"], title, final_alias, episode, "watching")

    embed = discord.Embed(title=f"✅ Tracking {title}", color=0x1abc9c)
    embed.add_field(name="Alias", value=f"`{final_alias}`", inline=True)
    embed.set_thumbnail(url=data.get("coverImage", {}).get("large"))
    await interaction.followup.send(embed=embed)

@bot.tree.command(name="watched", description="Update progress")
async def watched(interaction: discord.Interaction, identifier: str, episode: int = None):
    prog = get_progress(interaction.user.id, identifier)
    if not prog:
        return await interaction.response.send_message("❌ Not tracking this anime.", ephemeral=True)
    
    new_ep = episode if episode is not None else prog[2] + 1
    update_progress(interaction.user.id, prog[3], new_ep)
    await interaction.response.send_message(f"✅ **{prog[0]}** updated to episode **{new_ep}**.")

@bot.tree.command(name="mark", description="Update status")
@app_commands.choices(status=[
    app_commands.Choice(name="Watching", value="watching"),
    app_commands.Choice(name="Watched", value="watched"),
    app_commands.Choice(name="Want to Watch", value="want_to_watch"),
])
async def mark(interaction: discord.Interaction, identifier: str, status: app_commands.Choice[str]):
    prog = get_progress(interaction.user.id, identifier)
    if not prog: return await interaction.response.send_message("❌ Not tracking.", ephemeral=True)
    update_status(interaction.user.id, prog[3], status.value)
    await interaction.response.send_message(f"✅ **{prog[0]}** marked as **{status.name}**.")

@bot.tree.command(name="untrack", description="Remove an anime")
async def untrack(interaction: discord.Interaction, identifier: str):
    prog = get_progress(interaction.user.id, identifier)
    if not prog: return await interaction.response.send_message("❌ Not tracking.", ephemeral=True)
    remove_anime(interaction.user.id, prog[3])
    await interaction.response.send_message(f"🗑️ Removed **{prog[0]}**.")

@bot.tree.command(name="seasonal", description="Browse seasonal anime")
async def seasonal(interaction: discord.Interaction, year: int = None):
    season, d_year = current_season_year()
    view = SeasonalView(interaction.user.id, season, year or d_year)
    await interaction.response.send_message(embed=view.build_list_embed(), view=view)

@bot.tree.command(name="alias", description="Change the alias for a tracked anime")
async def change_alias(interaction: discord.Interaction, identifier: str, new_alias: str):
    prog = get_progress(interaction.user.id, identifier)
    if not prog: return await interaction.response.send_message("❌ Not tracking.", ephemeral=True)
    update_alias(interaction.user.id, prog[3], new_alias)
    await interaction.response.send_message(f"✏️ **{prog[0]}** alias: `{prog[1]}` → `{new_alias}`")

# ---------------- AUTOCOMPLETE ----------------
async def alias_autocomplete(interaction: discord.Interaction, current: str):
    aliases = get_aliases(interaction.user.id)
    return [app_commands.Choice(name=a, value=a) for a in aliases if current.lower() in a.lower()][:25]

watched.autocomplete("identifier")(alias_autocomplete)
mark.autocomplete("identifier")(alias_autocomplete)
untrack.autocomplete("identifier")(alias_autocomplete)
change_alias.autocomplete("identifier")(alias_autocomplete)
progress.autocomplete("identifier")(alias_autocomplete)

# ---------------- BACKGROUND TASK ----------------
@tasks.loop(minutes=10)
async def check_new_episodes():
    try:
        now_utc = datetime.now(timezone.utc)
        guild = bot.get_guild(GUILD_ID)
        if not guild: return

        # Find first viable channel
        target_channel = next((ch for ch in guild.text_channels if ch.permissions_for(guild.me).send_messages), None)
        tracked = get_all_tracked()

        for user_id, anime_id, _, last_notified in tracked:
            data = cached_search_id(anime_id)
            if not data or not data.get("nextAiringEpisode"): continue
            
            ep_info = data["nextAiringEpisode"]
            if ep_info["episode"] <= (last_notified or 0): continue

            airing_at = datetime.fromtimestamp(ep_info["airingAt"], tz=timezone.utc)
            if now_utc + timedelta(minutes=30) < airing_at: continue

            member = guild.get_member(user_id)
            if not member: continue

            if ALERT_ROLE_ID:
                role = guild.get_role(ALERT_ROLE_ID)
                if not role or role not in member.roles: continue

            title = data["title"]["romaji"]
            msg = f"{member.mention} 🎉 **{title}** Ep **{ep_info['episode']}** is out!"
            
            if target_channel: await target_channel.send(msg)
            try: await member.send(f"🎉 {title} Ep {ep_info['episode']} is out!")
            except: pass

            update_last_notified(user_id, anime_id, ep_info["episode"])
    except Exception as e:
        print(f"Loop Error: {e}")

keep_alive()
bot.run(TOKEN)