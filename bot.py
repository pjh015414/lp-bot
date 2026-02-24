import os
import requests
import discord
from discord.ext import commands

DISCOGS_TOKEN = os.getenv("DISCOGS_TOKEN")
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

DISCOGS_BASE = "https://api.discogs.com"
HEADERS = {
    "User-Agent": "lp-bot/2.0"
}

def discogs_search(query):
    url = f"{DISCOGS_BASE}/database/search"
    params = {
        "q": query,
        "type": "release",
        "format": "vinyl",
        "per_page": 10,
        "token": DISCOGS_TOKEN
    }
    r = requests.get(url, params=params, headers=HEADERS)
    r.raise_for_status()
    return r.json().get("results", [])

def get_release(release_id):
    url = f"{DISCOGS_BASE}/releases/{release_id}"
    params = {"token": DISCOGS_TOKEN}
    r = requests.get(url, params=params, headers=HEADERS)
    r.raise_for_status()
    return r.json()

def get_top3_tracks(release):
    tracks = []
    for t in release.get("tracklist", []):
        if t.get("type_") == "track":
            title = t.get("title")
            if title:
                tracks.append(title)
    return tracks[:3]

def format_tracks(tracks):
    if not tracks:
        return "트랙 정보 없음"
    return "\n".join([f"`{i+1:02}` {track}" for i, track in enumerate(tracks)])

class LPSelect(discord.ui.Select):
    def __init__(self, results):
        options = []
        for r in results:
            title = r.get("title", "Unknown")
            year = r.get("year", "")
            label = f"{title} ({year})" if year else title
            options.append(discord.SelectOption(
                label=label[:100],
                value=str(r["id"])
            ))

        super().__init__(
            placeholder="원하는 LP를 선택",
            min_values=1,
            max_values=1,
            options=options
        )

    async def callback(self, interaction: discord.Interaction):
        release_id = int(self.values[0])
        release = get_release(release_id)

        title = release.get("title", "Unknown")
        year = release.get("year", "Unknown")
        country = release.get("country", "Unknown")

        artists = ", ".join([a["name"] for a in release.get("artists", [])]) or "Unknown"

        cover = None
        if release.get("images"):
            cover = release["images"][0]["uri"]

        top3 = get_top3_tracks(release)
        track_text = format_tracks(top3)

        embed = discord.Embed(
            title=title,
            description=f"🎧 {artists}",
            color=0x2b2d31
        )

        embed.add_field(
            name="📀 앨범 정보",
            value=f"📅 {year} / 🌍 {country}",
            inline=False
        )

        embed.add_field(
            name="💿 수록곡",
            value=track_text,
            inline=False
        )

        if cover:
            embed.set_image(url=cover)

        embed.set_footer(text="LP Bot • Discogs 기반 검색")

        await interaction.response.send_message(embed=embed)

class LPView(discord.ui.View):
    def __init__(self, results):
        super().__init__(timeout=60)
        self.add_item(LPSelect(results))

@bot.command()
async def lp(ctx, *, query):
    results = discogs_search(query)

    if not results:
        await ctx.send("없음")
        return

    view = LPView(results)
    await ctx.send("🎵 골라라 게이야.", view=view)

bot.run(DISCORD_TOKEN)
