import os
import requests
import discord
from discord.ext import commands

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
DISCOGS_TOKEN = os.getenv("DISCOGS_TOKEN")
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")

if not DISCORD_TOKEN or not DISCOGS_TOKEN:
    raise RuntimeError("DISCORD_TOKEN / DISCOGS_TOKEN 환경변수 없음")

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

DISCOGS_BASE = "https://api.discogs.com"
HEADERS = {"User-Agent": "lp-bot"}

yt_cache = {}

def youtube_enabled():
    return bool(YOUTUBE_API_KEY)

def youtube_search(query):
    url = "https://www.googleapis.com/youtube/v3/search"
    params = {
        "part": "snippet",
        "q": query,
        "key": YOUTUBE_API_KEY,
        "maxResults": 1,
        "type": "video"
    }
    try:
        r = requests.get(url, params=params, timeout=15)
        data = r.json()
        items = data.get("items", [])
        if items:
            vid = items[0]["id"]["videoId"]
            return f"https://youtu.be/{vid}"
    except:
        return None
    return None

def get_youtube_link(artist, track, album):
    if not youtube_enabled():
        return None

    cache_key = f"{artist}-{track}-{album}"
    if cache_key in yt_cache:
        return yt_cache[cache_key]

    queries = [
        f"{artist} {track} official audio",
        f"{artist} {track} audio",
        f"{track} {artist}",
        f"{artist} {track} {album}",
        f"{track} audio"
    ]

    for q in queries:
        link = youtube_search(q)
        if link:
            yt_cache[cache_key] = link
            return link

    yt_cache[cache_key] = None
    return None

def search_lp(query):
    url = f"{DISCOGS_BASE}/database/search"
    params = {
        "q": query,
        "type": "release",
        "format": "vinyl",
        "token": DISCOGS_TOKEN
    }
    r = requests.get(url, params=params, headers=HEADERS)
    return r.json().get("results", [])[:5]

def get_release(release_id):
    url = f"{DISCOGS_BASE}/releases/{release_id}"
    params = {"token": DISCOGS_TOKEN}
    r = requests.get(url, params=params, headers=HEADERS)
    return r.json()

class Select(discord.ui.Select):
    def __init__(self, results, author_id, origin_msg):
        self.results = results
        self.author_id = author_id
        self.origin_msg = origin_msg

        options = []
        for r in results:
            title = r.get("title", "Unknown")
            year = r.get("year", "")
            options.append(discord.SelectOption(
                label=title[:100],
                description=str(year),
                value=str(r["id"])
            ))

        super().__init__(placeholder="원하는 LP 선택", options=options)

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("니가 검색한거 아님", ephemeral=True)
            return

        await interaction.response.defer()

        release = get_release(self.values[0])
        title = release.get("title", "Unknown")
        year = release.get("year", "")
        country = release.get("country", "")
        artist = release.get("artists", [{}])[0].get("name", "Unknown")
        tracklist = release.get("tracklist", [])
        images = release.get("images", [])

        embed = discord.Embed(title=title, description=artist, color=0x2b2d31)
        embed.add_field(name="앨범 정보", value=f"{year} / {country}", inline=False)

        tracks_text = ""
        for i, t in enumerate(tracklist, 1):
            name = t.get("title", "")
            yt = get_youtube_link(artist, name, title)

            if yt:
                tracks_text += f"`{i:02}` {name} · [YouTube]({yt})\n"
            else:
                tracks_text += f"`{i:02}` {name}\n"

        embed.add_field(name="수록곡", value=tracks_text[:1024], inline=False)

        if images:
            embed.set_image(url=images[0]["uri"])

        footer = "LP Bot • YouTube 있음" if youtube_enabled() else "LP Bot • YouTube 키 없음"
        embed.set_footer(text=footer)

        await interaction.message.edit(content=None, embed=embed, view=None)

        try:
            await self.origin_msg.delete()
        except:
            pass

class View(discord.ui.View):
    def __init__(self, results, author_id, origin_msg):
        super().__init__(timeout=60)
        self.add_item(Select(results, author_id, origin_msg))

@bot.command()
async def lp(ctx, *, query: str = None):
    if not query:
        await ctx.send("사용법: !lp 앨범명 또는 아티스트")
        return

    results = search_lp(query)

    if not results:
        await ctx.send("검색 결과 없음")
        return

    view = View(results, ctx.author.id, ctx.message)
    await ctx.send("고르시오", view=view)

bot.run(DISCORD_TOKEN)
