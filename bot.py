import os
import requests
import discord
from discord.ext import commands

DISCOGS_TOKEN = os.getenv("DISCOGS_TOKEN")
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")

if not DISCOGS_TOKEN or not DISCORD_TOKEN:
    raise RuntimeError("환경변수 DISCOGS_TOKEN / DISCORD_TOKEN 설정 안 됨")

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

DISCOGS_BASE = "https://api.discogs.com"
HEADERS = {
    # Discogs는 User-Agent 요구하는 편이라 넣어두는 게 안전함
    "User-Agent": "lp-bot/1.0 (discord bot)"
}

def discogs_search(query: str, limit: int = 10):
    url = f"{DISCOGS_BASE}/database/search"
    params = {
        "q": query,
        "type": "release",
        "format": "vinyl",
        "per_page": limit,
        "token": DISCOGS_TOKEN,
    }
    r = requests.get(url, params=params, headers=HEADERS, timeout=15)
    r.raise_for_status()
    return r.json().get("results", [])

def discogs_release(release_id: int):
    url = f"{DISCOGS_BASE}/releases/{release_id}"
    params = {"token": DISCOGS_TOKEN}
    r = requests.get(url, params=params, headers=HEADERS, timeout=15)
    r.raise_for_status()
    return r.json()

def pick_top3_tracks(release_json: dict):
    tracks = []
    for t in release_json.get("tracklist", []):
        if t.get("type_") == "track":
            title = t.get("title", "").strip()
            if title:
                tracks.append(title)
    return tracks[:3]

class ReleaseSelect(discord.ui.Select):
    def __init__(self, results):
        options = []
        for item in results:
            rid = item.get("id")
            title = (item.get("title") or "Unknown").strip()
            year = item.get("year")
            label = f"{title}"
            if year:
                label = f"{title} ({year})"
            # Discord 옵션 라벨 길이 제한 대비
            label = label[:100]
            options.append(discord.SelectOption(label=label, value=str(rid)))
        super().__init__(
            placeholder="원하는 릴리즈 선택",
            min_values=1,
            max_values=1,
            options=options
        )

    async def callback(self, interaction: discord.Interaction):
        rid = int(self.values[0])
        try:
            rel = discogs_release(rid)
        except Exception as e:
            await interaction.response.send_message(f"릴리즈 조회 실패: {e}", ephemeral=True)
            return

        title = rel.get("title") or "Unknown"
        artists = ", ".join([a.get("name", "").replace(" (", " (").strip() for a in rel.get("artists", []) if a.get("name")]) or "Unknown"
        year = rel.get("year")
        country = rel.get("country")
        cover = None
        images = rel.get("images") or []
        if images:
            cover = images[0].get("uri")
        if not cover:
            cover = rel.get("thumb")

        top3 = pick_top3_tracks(rel)
        track_text = "\n".join([f"{i+1}. {t}" for i, t in enumerate(top3)]) if top3 else "트랙 정보 없음"

        embed = discord.Embed(title=f"{artists} - {title}")
        if year or country:
            embed.description = " / ".join([str(x) for x in [year, country] if x])
        embed.add_field(name="수록곡 3개", value=track_text, inline=False)
        if cover:
            embed.set_image(url=cover)

        await interaction.response.send_message(embed=embed)

class ReleaseSelectView(discord.ui.View):
    def __init__(self, results, author_id: int):
        super().__init__(timeout=60)
        self.author_id = author_id
        self.add_item(ReleaseSelect(results))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        # 검색한 사람만 선택하게 잠금(원하면 제거 가능)
        return interaction.user.id == self.author_id

@bot.command()
async def lp(ctx, *, query: str):
    try:
        results = discogs_search(query, limit=10)
    except Exception as e:
        await ctx.send(f"검색 실패: {e}")
        return

    if not results:
        await ctx.send("검색 결과 없음")
        return

    view = ReleaseSelectView(results, author_id=ctx.author.id)
    await ctx.send("골라라 게이야", view=view)

bot.run(DISCORD_TOKEN)
