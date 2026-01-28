import discord
from discord import app_commands
from discord.ext import commands, tasks
import os
import math
from dotenv import load_dotenv
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from database import (
    add_anime, update_progress, update_status, get_progress, 
    list_tracked, get_aliases, get_all_tracked, 
    update_last_notified, remove_anime, conn
)
from anilist import search_anime, search_anime_by_id

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
        self.owner = owner  # The User object whose list this is
        self.rows = rows 
        self.status = status
        self.page = page
        self.update_buttons()

    def get_filtered(self):
        return [f"**{n}** (`{a}`) → Ep {e}" for n, a, e, s in self.rows if s == self.status]

    def max_pages(self):
        return max(1, math.ceil(len(self.get_filtered()) / ITEMS_PER_PAGE))

    def build_embed(self):
        items = self.get_filtered()
        start = self.page * ITEMS_PER_PAGE
        page_items = items[start:start + ITEMS_PER_PAGE]
        
        embed = discord.Embed(
            title=f"📺 {self.owner.display_name}'s {self.status.replace('_', ' ').title()} List",
            description="\n".join(page_items) if page_items else "No anime in this category.",
            color=0x9b59b6
        )
        embed.set_footer(text=f"Page {self.page + 1}/{self.max_pages()}")
        return embed

    def update_buttons(self):
        max_p = self.max_pages()
        self.prev.disabled = self.page == 0
        self.next.disabled = self.page >= max_p - 1

    @discord.ui.select(
        placeholder="Filter by status",
        options=[
            discord.SelectOption(label="Watching", value="watching", emoji="📺"),
            discord.SelectOption(label="Watched", value="watched", emoji="✅"),
            discord.SelectOption(label="Want to Watch", value="want_to_watch", emoji="⭐"),
        ]
    )
    async def select_status(self, interaction: discord.Interaction, select: discord.ui.Select):
        self.status = select.values[0]
        self.page = 0
        self.update_buttons()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @discord.ui.button(label="Previous", style=discord.ButtonStyle.gray)
    async def prev(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page -= 1
        self.update_buttons()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @discord.ui.button(label="Next", style=discord.ButtonStyle.gray)
    async def next(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page += 1
        self.update_buttons()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

# ---------------- COMMANDS ----------------

@bot.tree.command(name="list", description="View a user's tracked anime")
@app_commands.describe(user="The user whose list you want to see (optional)")
async def list_cmd(interaction: discord.Interaction, user: discord.User = None):
    target_user = user or interaction.user
    rows = list_tracked(target_user.id)
    
    if not rows:
        message = "❌ This user is not tracking any anime." if user else "❌ You are not tracking any anime."
        return await interaction.response.send_message(message)
    
    view = ListView(target_user, rows)
    await interaction.response.send_message(embed=view.build_embed(), view=view)

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

@bot.tree.command(name="watched", description="Update progress")
async def watched(interaction: discord.Interaction, identifier: str, episode: int):
    prog = get_progress(interaction.user.id, identifier)
    if not prog:
        return await interaction.response.send_message("❌ Not tracking this anime.", ephemeral=True)

    update_progress(interaction.user.id, prog[3], episode)
    await interaction.response.send_message(f"✅ **{prog[0]}** updated to episode {episode}.")

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

# ---------------- AUTOCOMPLETE ----------------

@watched.autocomplete("identifier")
@mark.autocomplete("identifier")
@untrack.autocomplete("identifier")
@progress.autocomplete("identifier")
async def autocomplete(interaction: discord.Interaction, current: str):
    aliases = get_aliases(interaction.user.id)
    return [app_commands.Choice(name=a, value=a) for a in aliases if current.lower() in a.lower()][:25]

# ---------------- BACKGROUND TASK ----------------
@tasks.loop(minutes=10)
async def check_new_episodes():
    await bot.wait_until_ready()
    now_utc = datetime.now(timezone.utc)
    
    for user_id, anime_id, last_watched, last_notified in get_all_tracked():
        data = search_anime_by_id(anime_id)
        if not data or not data.get("nextAiringEpisode"):
            continue

        ep_info = data["nextAiringEpisode"]
        if ep_info["episode"] <= last_notified:
            continue

        airing_at_utc = datetime.fromtimestamp(ep_info["airingAt"], tz=timezone.utc)

        if now_utc >= airing_at_utc:
            user = bot.get_user(user_id)
            msg = f"🎉 **{data['title']['romaji']}** Episode {ep_info['episode']} just aired!"
            
            guild = bot.get_guild(GUILD_ID)
            if guild and ALERT_ROLE_ID:
                role = guild.get_role(ALERT_ROLE_ID)
                if role: msg = f"{role.mention} {msg}"

            if user:
                try: await user.send(msg)
                except: pass
            
            if guild and guild.text_channels:
                await guild.text_channels[0].send(msg)

            update_last_notified(user_id, anime_id, ep_info["episode"])

bot.run(TOKEN)