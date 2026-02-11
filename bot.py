import discord
from discord import app_commands
from discord.ext import commands, tasks
import os
import math
from dotenv import load_dotenv
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from keep_alive import keep_alive
from database import *
from anilist import *


# ---------------- CONFIGURATION ----------------
load_dotenv()
TOKEN=os.getenv("DISCORD_TOKEN")
GUILD_ID=int(os.getenv("GUILD_ID"))
ALERT_ROLE_ID=int(os.getenv("ALERT_ROLE_ID") or 0) or None
TIMEZONE=os.getenv("TIMEZONE","America/New_York"); ITEMS_PER_PAGE=10


GENRE_EMOJIS = {
    "Action": "⚔️", "Adventure": "🗺️", "Comedy": "😂", "Drama": "🎭",
    "Fantasy": "🧙", "Romance": "💖", "Slice of Life": "🏠", "Sci-Fi": "🤖",
    "Horror": "👻", "Mystery": "🕵️"
}

SEASONS = ["WINTER", "SPRING", "SUMMER", "FALL"]

# Cache AniList lookups for 10 minutes to reduce API latency
anime_cache = {}
CACHE_TTL = 600 

async def cached_search_id(anime_id):
    now=datetime.now().timestamp()
    if (c:=anime_cache.get(anime_id)) and now-c[1]<CACHE_TTL:
        return c[0]
    data=await search_anime_by_id(anime_id)
    anime_cache[anime_id]=(data,now)
    return data

def current_season_year():
    now=datetime.now(ZoneInfo(TIMEZONE))
    m,y=now.month,now.year
    return ("WINTER",y) if m<=3 else ("SPRING",y) if m<=6 else ("SUMMER",y) if m<=9 else ("FALL",y)

def format_genres(genres): return " ".join(GENRE_EMOJIS[g] for g in genres if g in GENRE_EMOJIS)


# ---------------- BOT SETUP ----------------
class MyBot(commands.Bot):
    def __init__(self):
        intents=discord.Intents.default()
        intents.members=intents.message_content=True
        super().__init__(command_prefix="!",intents=intents)

    async def setup_hook(self):
        guild=discord.Object(id=GUILD_ID)
        self.tree.copy_global_to(guild=guild)
        for name in ("watched", "mark", "untrack", "change_alias", "progress"):
            cmd = self.tree.get_command(name)
            if cmd:
                cmd.autocomplete("identifier")(alias_autocomplete)
        await self.tree.sync(guild=guild)
        if not check_new_episodes.is_running(): check_new_episodes.start()
        print("✅ Bot synced.")

bot = MyBot()

@bot.event
async def on_ready():
    await init_db_pool()
    print(f"Logged in as {bot.user}")

GOJO_GIF_URL = "https://giphy.com/gifs/jujutsu-kaisen-kilianirl-WDH0KOD68mVzqTrfFr"

@bot.event
async def on_message(message):
    if message.author==bot.user: return
    c=message.content.lower()
    if "gojo" in c: await message.channel.send(f"I'm right here bbg\n{GOJO_GIF_URL}")
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
        prog = await get_progress(self.owner.id, alias)
        if not prog:
            return discord.Embed(title="Preview", description=f"Not tracking {name}.", color=0x9b59b6)

        # Use cached ID search for speed
        data = await cached_search_id(prog[3])
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

async def seasonal(interaction: discord.Interaction, year:int=None):
    season, d_year = current_season_year()
    data = await get_seasonal_anime(season, year or d_year)
    
    all_tracked = await get_all_tracked()
    tracked_ids = {uid[1] for uid in all_tracked if uid[0] == interaction.user.id}

    view = SeasonalView(interaction.user.id, season, year or d_year, data, tracked_ids)
    await interaction.followup.send(embed=view.build_list_embed(), view=view)

class SeasonalView(discord.ui.View):
    def __init__(self, user_id, season, year, data, tracked_ids):
        super().__init__(timeout=180)
        self.user_id = user_id
        self.season = season
        self.year = year
        self.page = 0
        self.preview_mode = False
        self.preview_index = 0
        self.data = data
        self.tracked_ids = tracked_ids
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
        self.data = await get_seasonal_anime(self.season, self.year)
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
async def list_cmd(interaction: discord.Interaction, user: discord.User=None):
    await interaction.response.defer()
    target=user or interaction.user
    if not (rows:=await list_tracked(target.id)):
        return await interaction.followup.send("No tracked anime.")
    view=ListView(target,rows)
    await interaction.followup.send(embed=view.build_list_embed(),view=view)


@bot.tree.command(name="progress", description="Check detailed progress for an anime")
async def progress(interaction: discord.Interaction, identifier:str):
    await interaction.response.defer()
    if not (prog:=await get_progress(interaction.user.id,identifier)):
        return await interaction.followup.send(f"❌ Not tracking '{identifier}'.",ephemeral=True)
    name,alias,last_watched,anime_id,status=prog
    if not (data:=await cached_search_id(anime_id)):
        return await interaction.followup.send("❌ AniList error.",ephemeral=True)
    embed=discord.Embed(
        title=f"📺 {name} ({alias})",
        description=(data.get("description") or "No description.")[:1000],
        color=0x3498db
    )
    embed.add_field(name="Progress",value=f"**Status:** {status.title()}\n**Watched:** Ep {last_watched}",inline=False)
    if eps:=data.get("episodes"): embed.add_field(name="Total",value=str(eps),inline=True)
    if genres:=format_genres(data.get("genres",[])): embed.add_field(name="Genres",value=genres,inline=True)
    if next_ep:=data.get("nextAiringEpisode"):
        ts=datetime.fromtimestamp(next_ep["airingAt"],tz=timezone.utc).astimezone(ZoneInfo(TIMEZONE))
        embed.add_field(name="Next Episode",value=f"Ep {next_ep['episode']} — {ts.strftime('%Y-%m-%d %H:%M')}",inline=False)
    if thumb:=data.get("coverImage",{}).get("large"): embed.set_thumbnail(url=thumb)
    await interaction.followup.send(embed=embed)


@bot.tree.command(name="track", description="Start tracking a new anime")
async def track(interaction: discord.Interaction, anime:str, alias:str=None, episode:int=0):
    await interaction.response.defer()
    if not (data:=await search_anime(anime)):
        return await interaction.followup.send("❌ Anime not found.",ephemeral=True)
    title=data["title"]["romaji"]
    final_alias=alias or "".join(w[0] for w in title.split() if w).upper()
    await add_anime(interaction.user.id,data["id"],title,final_alias,episode,"watching")
    embed=discord.Embed(title=f"✅ Tracking {title}",color=0x1abc9c)
    embed.add_field(name="Alias",value=f"`{final_alias}`",inline=True)
    if thumb:=data.get("coverImage",{}).get("large"): embed.set_thumbnail(url=thumb)
    await interaction.followup.send(embed=embed)


@bot.tree.command(name="watched", description="Update episode progress")
async def watched(interaction: discord.Interaction, identifier: str, episode: int | None = None):
    prog = await get_progress(interaction.user.id, identifier)
    if not prog:
        return await interaction.response.send_message("❌ Not tracking this anime.", ephemeral=True)
    name, _, last, anime_id, _ = prog
    new_ep = episode or (last + 1)
    await update_progress(interaction.user.id, anime_id, new_ep)
    await interaction.response.send_message(f"✅ `{name}` → Episode {new_ep}.")

@bot.tree.command(name="mark", description="Change watching status")
async def mark(interaction: discord.Interaction, identifier:str, status:str):
    if status.lower() not in ("watching","completed","paused","dropped"):
        return await interaction.response.send_message("❌ Invalid status.",ephemeral=True)
    if not await get_progress(interaction.user.id,identifier):
        return await interaction.response.send_message("❌ Not tracking this anime.",ephemeral=True)
    await update_status(interaction.user.id,identifier,status.lower())
    await interaction.response.send_message(f"✅ `{identifier}` marked as **{status.title()}**.")


@bot.tree.command(name="untrack", description="Stop tracking an anime")
async def untrack(interaction: discord.Interaction, identifier:str):
    if not await get_progress(interaction.user.id,identifier):
        return await interaction.response.send_message("❌ Not tracking this anime.",ephemeral=True)
    await remove_anime(interaction.user.id,identifier)
    await interaction.response.send_message(f"🗑️ Stopped tracking `{identifier}`.")


@bot.tree.command(name="seasonal", description="Browse seasonal anime")
async def seasonal(interaction: discord.Interaction, year: int = None):
    await interaction.response.defer()
    season, d_year = current_season_year()
    data = await get_seasonal_anime(season, year or d_year)
    all_tracked = await get_all_tracked()
    tracked_ids = {anime_id for uid, anime_id, _, _ in all_tracked if uid == interaction.user.id}
    view = SeasonalView(interaction.user.id, season, year or d_year, data, tracked_ids)
    await interaction.followup.send(embed=view.build_list_embed(), view=view)


@bot.tree.command(name="alias", description="Change the alias for a tracked anime")
async def change_alias(interaction: discord.Interaction, identifier:str, new_alias:str):
    if not (prog:=await get_progress(interaction.user.id,identifier)):
        return await interaction.response.send_message("❌ Not tracking.",ephemeral=True)
    await update_alias(interaction.user.id,prog[3],new_alias)
    await interaction.response.send_message(f"✏️ **{prog[0]}** alias: `{prog[1]}` → `{new_alias}`")

# ---------------- AUTOCOMPLETE ----------------
async def alias_autocomplete(interaction: discord.Interaction, current: str):
    return [
        app_commands.Choice(name=a, value=a)
        for a in get_aliases(interaction.user.id)
        if current.lower() in a.lower()
    ][:25]

# ---------------- BACKGROUND TASK ----------------
@tasks.loop(minutes=10)
async def check_new_episodes():
    try:
        now=datetime.now(timezone.utc)
        if not (guild:=bot.get_guild(GUILD_ID)): return
        channel=next((c for c in guild.text_channels if c.permissions_for(guild.me).send_messages),None)

        for user_id,anime_id,_,last_notified in await get_all_tracked():
            if not (data:=await cached_search_id(anime_id)): continue
            if not (ep:=data.get("nextAiringEpisode")): continue
            if ep["episode"] <= (last_notified or 0): continue

            airing=datetime.fromtimestamp(ep["airingAt"],tz=timezone.utc)
            if now+timedelta(minutes=30) < airing: continue
            if not (member:=guild.get_member(user_id)): continue
            if ALERT_ROLE_ID and (not (role:=guild.get_role(ALERT_ROLE_ID)) or role not in member.roles): continue

            title=data["title"]["romaji"]
            msg=f"{member.mention} 🎉 **{title}** Ep **{ep['episode']}** is out!"
            if channel: await channel.send(msg)
            try: await member.send(f"🎉 {title} Ep {ep['episode']} is out!")
            except: pass
            await update_last_notified(user_id,anime_id,ep["episode"])
    except Exception as e:
        print(f"Loop Error: {e}")


keep_alive()
bot.run(TOKEN)