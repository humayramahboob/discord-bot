import discord
from discord import app_commands
from discord.ext import commands, tasks
import os
import math
from dotenv import load_dotenv
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from keep_alive import keep_alive

from database import (
    add_anime, update_progress, update_status, get_progress, 
    list_tracked, get_aliases, get_all_tracked, 
    update_last_notified, remove_anime, update_alias, conn
)
from anilist import search_anime, search_anime_by_id, get_seasonal_anime

# ---------------- CONFIGURATION ----------------
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = int(os.getenv("GUILD_ID"))
ALERT_ROLE_ID = os.getenv("ALERT_ROLE_ID")
ALERT_ROLE_ID = int(ALERT_ROLE_ID) if ALERT_ROLE_ID else None
TIMEZONE = os.getenv("TIMEZONE", "America/New_York")
ITEMS_PER_PAGE = 10

GENRE_EMOJIS = {
    "Action": "⚔️", "Adventure": "🗺️", "Comedy": "😂", "Drama": "🎭",
    "Fantasy": "🧙", "Romance": "💖", "Slice of Life": "🏠", "Sci-Fi": "🤖",
    "Horror": "👻", "Mystery": "🕵️"
}

SEASONS = ["WINTER", "SPRING", "SUMMER", "FALL"]

def current_season_year():
    now = datetime.now(ZoneInfo(TIMEZONE))
    m = now.month
    if m <= 3:
        return "WINTER", now.year
    elif m <= 6:
        return "SPRING", now.year
    elif m <= 9:
        return "SUMMER", now.year
    else:
        return "FALL", now.year


def format_genres(genres):
    return " ".join([GENRE_EMOJIS[g] for g in genres if g in GENRE_EMOJIS])

# ---------------- BOT SETUP ----------------
class MyBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.members = True 
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        guild = discord.Object(id=GUILD_ID)
        self.tree.copy_global_to(guild=guild)
        await self.tree.sync(guild=guild)
        check_new_episodes.start()
        print(f"✅ Bot is synced and background tasks started.")

bot = MyBot()

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")

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
        return [(n, a, e, s) for n, a, e, s in self.rows if s == self.status]

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

    def build_preview_embed(self):
        rows = self.page_rows()
        if not rows:
            desc = "No anime to preview."
            embed = discord.Embed(title="Preview", description=desc, color=0x9b59b6)
            return embed

        name, alias, ep, _ = rows[self.preview_index]
        prog = get_progress(self.owner.id, alias)
        if not prog:
            desc = f"Not tracking {name}."
            embed = discord.Embed(title="Preview", description=desc, color=0x9b59b6)
            return embed

        data = search_anime_by_id(prog[3])
        embed = discord.Embed(
            title=f"📺 {name}",
            description=f"Episode {ep}",
            color=0x5865F2,
        )
        if data and data.get("coverImage") and data["coverImage"].get("large"):
            embed.set_image(url=data["coverImage"]["large"])
        embed.set_footer(
            text=f"Preview {self.preview_index + 1}/{len(rows)} - Page {self.page + 1}/{self.max_pages()}"
        )
        return embed

    def update_controls(self):
        if self.preview_mode:
            self.prev.disabled = self.preview_index == 0
            self.next.disabled = self.preview_index >= len(self.page_rows()) - 1
        else:
            self.prev.disabled = self.page == 0
            self.next.disabled = self.page >= self.max_pages() - 1

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
        self.preview_index = 0
        self.update_controls()
        await interaction.response.edit_message(embed=self.build_list_embed(), view=self)

    @discord.ui.button(label="◀", style=discord.ButtonStyle.gray)
    async def prev(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.preview_mode:
            if self.preview_index > 0:
                self.preview_index -= 1
        else:
            if self.page > 0:
                self.page -= 1
        self.update_controls()
        embed = self.build_preview_embed() if self.preview_mode else self.build_list_embed()
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="▶", style=discord.ButtonStyle.gray)
    async def next(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.preview_mode:
            if self.preview_index < len(self.page_rows()) - 1:
                self.preview_index += 1
        else:
            if self.page < self.max_pages() - 1:
                self.page += 1
        self.update_controls()
        embed = self.build_preview_embed() if self.preview_mode else self.build_list_embed()
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="🔍", style=discord.ButtonStyle.blurple)
    async def zoom(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.page_rows():
            return await interaction.response.send_message("No anime to preview.", ephemeral=True)

        self.preview_mode = not self.preview_mode
        self.preview_index = 0 
        self.update_controls()
        embed = self.build_preview_embed() if self.preview_mode else self.build_list_embed()
        await interaction.response.edit_message(embed=embed, view=self)


class SeasonalView(discord.ui.View):
    def __init__(self, user_id, season, year, page=0):
        super().__init__(timeout=180)
        self.user_id = user_id
        self.season = season
        self.year = year
        self.page = page
        self.preview_mode = False
        self.preview_index = 0
        self.data = get_seasonal_anime(season, year)

        self.tracked_ids = {
            anime_id for uid, anime_id, *_ in get_all_tracked() if uid == user_id
        }

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
            title=f"📡 {self.season.title()} {self.year} Seasonal Anime",
            description="\n".join(lines) if lines else "No anime found.",
            color=0xF39C12,
        )
        embed.set_footer(text=f"Page {self.page + 1}/{self.max_pages()}")
        return embed

    def build_preview_embed(self):
        page = self.page_slice()
        if not page:
            embed = discord.Embed(title="Preview", description="No anime to preview.", color=0xF39C12)
            return embed

        a = page[self.preview_index]

        embed = discord.Embed(
            title=f"📡 {a['title']['romaji']}",
            color=0x5865F2,
        )
        if a.get("coverImage") and a["coverImage"].get("medium"):
            embed.set_image(url=a["coverImage"]["medium"])

        embed.set_footer(
            text=f"Preview {self.preview_index + 1}/{len(page)} - Page {self.page + 1}/{self.max_pages()}"
        )
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
        self.preview_index = 0
        self.data = get_seasonal_anime(self.season, self.year)
        self.update_controls()
        await interaction.response.edit_message(embed=self.build_list_embed(), view=self)

    @discord.ui.button(label="◀", style=discord.ButtonStyle.gray)
    async def prev(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.preview_mode:
            if self.preview_index > 0:
                self.preview_index -= 1
        else:
            if self.page > 0:
                self.page -= 1
        self.update_controls()
        embed = self.build_preview_embed() if self.preview_mode else self.build_list_embed()
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="▶", style=discord.ButtonStyle.gray)
    async def next(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.preview_mode:
            if self.preview_index < len(self.page_slice()) - 1:
                self.preview_index += 1
        else:
            if self.page < self.max_pages() - 1:
                self.page += 1
        self.update_controls()
        embed = self.build_preview_embed() if self.preview_mode else self.build_list_embed()
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="🔍", style=discord.ButtonStyle.blurple)
    async def zoom(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.page_slice():
            return await interaction.response.send_message("No anime to preview.", ephemeral=True)

        self.preview_mode = not self.preview_mode
        self.preview_index = 0
        self.update_controls()
        embed = self.build_preview_embed() if self.preview_mode else self.build_list_embed()
        await interaction.response.edit_message(embed=embed, view=self)




# ---------------- COMMANDS ----------------

#shows the list of anime you are tracking
@bot.tree.command(name="list", description="View a user's tracked anime")
@app_commands.describe(user="User to view (optional)")
async def list_cmd(interaction: discord.Interaction, user: discord.User = None):
    target = user or interaction.user
    rows = list_tracked(target.id)

    if not rows:
        return await interaction.response.send_message("No tracked anime.")

    view = ListView(target, rows)
    await interaction.response.send_message(embed=view.build_list_embed(), view=view)

#shows the anime and information about it including next air date and where you left off
@bot.tree.command(name="progress", description="Check detailed progress for an anime")
@app_commands.describe(identifier="Anime name or alias")
async def progress(interaction: discord.Interaction, identifier: str):
    prog = get_progress(interaction.user.id, identifier)
    if not prog:
        return await interaction.response.send_message(f"❌ You are not tracking '{identifier}'.", ephemeral=True)
    
    anime_name, alias, last_watched, anime_id, status = prog
    data = search_anime_by_id(anime_id)
    
    if not data:
        return await interaction.response.send_message("❌ Could not retrieve data from AniList.")

    embed = discord.Embed(
        title=f"📺 {anime_name} ({alias})",
        description=f"Status: {status}\nLast watched episode: {last_watched}",
        color=0x3498db
    )
    
    total_eps = data.get("episodes")
    if total_eps:
        embed.description += f"\nTotal episodes: {total_eps}"

    embed.set_thumbnail(url=data.get("coverImage", {}).get("large"))

    next_ep = data.get("nextAiringEpisode")
    if next_ep:
        airing_ts = datetime.fromtimestamp(next_ep['airingAt'], tz=timezone.utc).astimezone(ZoneInfo(TIMEZONE))
        embed.add_field(name="Next Episode", value=f"Airs at {airing_ts.strftime('%Y-%m-%d %H:%M %Z')}", inline=True)
    else:
        embed.add_field(name="Next Episode", value="Completed or Not Airing", inline=True)

    embed.add_field(name="\u200b", value="\u200b", inline=True)

    genres_str = format_genres(data.get("genres", []))
    if genres_str:
        embed.add_field(name="Genres", value=genres_str, inline=True)

    await interaction.response.send_message(embed=embed)

#starts adding a new anime to put on your tracking list
@bot.tree.command(name="track", description="Start tracking a new anime")
async def track(interaction: discord.Interaction, anime: str, alias: str = None, episode: int = 0):
    data = search_anime(anime)
    if not data:
        return await interaction.response.send_message("❌ Anime not found.")

    title = data["title"]["romaji"]
    alias = alias or "".join([w[0] for w in title.split()]).upper()
    add_anime(interaction.user.id, data["id"], title, alias, episode, "watching")

    embed = discord.Embed(title=f"✅ Tracking {title}", color=0x1abc9c)
    embed.add_field(name="Alias", value=f"`{alias}`", inline=True)
    embed.add_field(name="Episode", value=episode, inline=True)
    embed.set_thumbnail(url=data.get("coverImage", {}).get("large"))
    
    await interaction.response.send_message(embed=embed)

# Can mark down the episode you watched 
@bot.tree.command(name="watched", description="Update progress")
async def watched(interaction: discord.Interaction, identifier: str, episode: int):
    prog = get_progress(interaction.user.id, identifier)
    if not prog:
        return await interaction.response.send_message("❌ Not tracking this anime.", ephemeral=True)

    update_progress(interaction.user.id, prog[3], episode)
    await interaction.response.send_message(f"✅ **{prog[0]}** updated to episode {episode}.")

#can change status of the aniime to watched, watching or want to watch
@bot.tree.command(name="mark", description="Update status")
@app_commands.choices(status=[
    app_commands.Choice(name="Watching", value="watching"),
    app_commands.Choice(name="Watched", value="watched"),
    app_commands.Choice(name="Want to Watch", value="want_to_watch"),
])
async def mark(interaction: discord.Interaction, identifier: str, status: app_commands.Choice[str]):
    prog = get_progress(interaction.user.id, identifier)
    if not prog:
        return await interaction.response.send_message("❌ Not tracking this anime.", ephemeral=True)

    update_status(interaction.user.id, prog[3], status.value)
    await interaction.response.send_message(f"✅ **{prog[0]}** marked as **{status.name}**.")

@bot.tree.command(name="untrack", description="Remove an anime")
async def untrack(interaction: discord.Interaction, identifier: str):
    prog = get_progress(interaction.user.id, identifier)
    if not prog:
        return await interaction.response.send_message("❌ Not tracking this anime.", ephemeral=True)

    remove_anime(interaction.user.id, prog[3])
    await interaction.response.send_message(f"🗑️ Removed **{prog[0]}**.")

@bot.tree.command(name="seasonal", description="Browse seasonal anime")
@app_commands.describe(year="Season year (optional)")
async def seasonal(interaction: discord.Interaction, year: int = None):
    season, default_year = current_season_year()
    year = year or default_year

    view = SeasonalView(interaction.user.id, season, year)

    await interaction.response.send_message(embed=view.build_list_embed(), view=view)

@bot.tree.command(name="alias", description="Change the alias for a tracked anime")
@app_commands.describe(
    identifier="Current alias or anime name",
    new_alias="New alias to use"
)
async def change_alias(
    interaction: discord.Interaction,
    identifier: str,
    new_alias: str
):
    prog = get_progress(interaction.user.id, identifier)
    if not prog:
        return await interaction.response.send_message(
            "❌ Not tracking this anime.",
            ephemeral=True
        )

    anime_name, old_alias, _, anime_id, _ = prog

    update_alias(interaction.user.id, anime_id, new_alias)

    await interaction.response.send_message(
        f"✏️ **{anime_name}** alias changed from `{old_alias}` → `{new_alias}`"
    )



# ---------------- AUTOCOMPLETE ----------------

@watched.autocomplete("identifier")
@mark.autocomplete("identifier")
@untrack.autocomplete("identifier")
@change_alias.autocomplete("identifier")
async def autocomplete_untrack(interaction: discord.Interaction, current: str):
    try:
        aliases = get_aliases(interaction.user.id)  # should be fast!
        choices = [app_commands.Choice(name=a, value=a) for a in aliases if current.lower() in a.lower()]
        await interaction.response.autocomplete(choices[:25])
    except Exception as e:
        print(f"Autocomplete error: {e}")
        # Do NOT respond here, because interaction may already be responded to

@progress.autocomplete("identifier")
async def autocomplete(interaction: discord.Interaction, current: str):
    aliases = get_aliases(interaction.user.id)
    return [app_commands.Choice(name=a, value=a) for a in aliases if current.lower() in a.lower()][:25]

# ---------------- BACKGROUND TASK ----------------
@tasks.loop(minutes=10)
async def check_new_episodes():
    await bot.wait_until_ready()
    now_utc = datetime.now(timezone.utc)

    guild = bot.get_guild(GUILD_ID)
    if not guild:
        return

    target_channel = None
    for ch in guild.text_channels:
        if ch.permissions_for(guild.me).send_messages:
            target_channel = ch
            break

    for user_id, anime_id, last_watched, last_notified in get_all_tracked():
        data = search_anime_by_id(anime_id)
        if not data or not data.get("nextAiringEpisode"):
            continue

        ep_info = data["nextAiringEpisode"]

        if ep_info["episode"] <= last_notified:
            continue

        airing_at_utc = datetime.fromtimestamp(
            ep_info["airingAt"], tz=timezone.utc
        )

        if now_utc >= airing_at_utc:

            user_mention = f"<@{user_id}>"
            title = data["title"]["romaji"]

            msg = f"{user_mention} 🎉 **{title}** Episode **{ep_info['episode']}** is now out!"

            if ALERT_ROLE_ID:
                role = guild.get_role(ALERT_ROLE_ID)
                if role:
                    msg = f"{role.mention} {msg}"

            if target_channel:
                try:
                    await target_channel.send(msg)
                except Exception as e:
                    print("Channel send failed:", e)

            user = bot.get_user(user_id)
            if user:
                try:
                    await user.send(f"🎉 {title} Episode {ep_info['episode']} is now out!")
                except:
                    pass

            update_last_notified(user_id, anime_id, ep_info["episode"])
keep_alive()
bot.run(TOKEN)