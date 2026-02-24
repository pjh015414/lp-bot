import os
import time
import requests
import discord
from discord.ext import commands

# ===== ENV =====
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
DISCOGS_TOKEN = os.getenv("DISCOGS_TOKEN")
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")

if not DISCORD_TOKEN or not DISCOGS_TOKEN:
    raise RuntimeError("DISCORD_TOKEN / DISCOGS_TOKEN 환경변수 없음")

# ===== Discord =====
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# ===== Anti-duplicate guard (배포 꼬여도 1번만 반응) =====
processed_ids = set()
def already_processed(message_id: int) -> bool:
    if message_id in processed_ids:
        return True
    processed_ids.add(message_id)
    if len(processed_ids) > 5000:
        processed_ids.clear()
    return False

# ===== Discogs =====
DISCOGS_BASE = "https://api.discogs.com"
DISCOGS_HEADERS = {"User-Agent": "lp-bot/final-onefile"}

def discogs_search(query: str, limit: int = 10):
    url = f"{DISCOGS_BASE}/database/search"
    params = {
        "q": query,
        "type": "release",
        "format": "vinyl",
        "per_page": limit,
        "token": DISCOGS_TOKEN,
    }
    r = requests.get(url, params=params, headers=DISCOGS_HEADERS, timeout=15)
    r.raise_for_status()
    return r.json().get("results", [])

def discogs_release(release_id: int):
    url = f"{DISCOGS_BASE}/releases/{release_id}"
    params = {"token": DISCOGS_TOKEN}
    r = requests.get(url, params=params, headers=DISCOGS_HEADERS, timeout=15)
    r.raise_for_status()
    return r.json()

def discogs_all_tracks(release_json: dict):
    tracks = []
    for t in release_json.get("tracklist", []):
        if t.get("type_") == "track":
            title = (t.get("title") or "").strip()
            if title:
                tracks.append(title)
    return tracks

# ===== YouTube =====
YOUTUBE_SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"
yt_cache: dict[str, str | None] = {}

def youtube_enabled() -> bool:
    return bool(YOUTUBE_API_KEY)

def youtube_link(q: str) -> str | None:
    if q in yt_cache:
        return yt_cache[q]
    if not youtube_enabled():
        yt_cache[q] = None
        return None

    params = {
        "part": "snippet",
        "q": q,
        "key": YOUTUBE_API_KEY,
        "maxResults": 1,
        "type": "video",
    }
    try:
        r = requests.get(YOUTUBE_SEARCH_URL, params=params, timeout=15)
        r.raise_for_status()
        items = (r.json().get("items") or [])
        if not items:
            yt_cache[q] = None
            return None
        vid = items[0]["id"]["videoId"]
        link = f"https://youtu.be/{vid}"
        yt_cache[q] = link
        return link
    except Exception:
        yt_cache[q] = None
        return None

# ===== Formatting =====
def chunk_lines(lines: list[str], limit: int = 1000) -> list[str]:
    chunks = []
    cur = ""
    for line in lines:
        add = line if not cur else "\n" + line
        if len(cur) + len(add) > limit:
            if cur:
                chunks.append(cur)
                cur = line
            else:
                chunks.append(line[:limit])
                cur = ""
        else:
            cur += add
    if cur:
        chunks.append(cur)
    return chunks

def build_embeds(album_title: str, artists: str, year, country, cover_url: str | None, track_chunks: list[str]):
    footer = "LP Bot • " + ("YouTube 있음" if youtube_enabled() else "YouTube 키 없음")

    base = discord.Embed(
        title=album_title,
        description=f"🎧 {artists}",
        color=0x2b2d31
    )

    info = []
    if year:
        info.append(f" {year}")
    if country:
        info.append(f" {country}")
    if info:
        base.add_field(name=" 앨범 정보", value=" / ".join(info), inline=False)

    if cover_url:
        base.set_image(url=cover_url)

    base.set_footer(text=footer)

    embeds = []
    cur = base
    field_count = len(cur.fields)

    for i, chunk in enumerate(track_chunks):
        name = " 수록곡" if i == 0 else " 수록곡 (계속)"
        if field_count >= 24:
            embeds.append(cur)
            cur = discord.Embed(title=album_title, description=f"🎧 {artists}", color=0x2b2d31)
            cur.set_footer(text=footer)
            field_count = 0
        cur.add_field(name=name, value=chunk, inline=False)
        field_count += 1

    embeds.append(cur)
    return embeds

# ===== UI =====
class ReleaseSelect(discord.ui.Select):
    def __init__(self, results, author_id: int, origin_message: discord.Message):
        self.author_id = author_id
        self.origin_message = origin_message

        options = []
        for item in results:
            rid = item.get("id")
            title = (item.get("title") or "Unknown").strip()
            year = item.get("year")
            label = f"{title} ({year})" if year else title
            options.append(discord.SelectOption(label=label[:100], value=str(rid)))

        super().__init__(
            placeholder="원하는 LP 선택",
            min_values=1,
            max_values=1,
            options=options
        )

    async def callback(self, interaction: discord.Interaction):
        # 배포 꼬여서 여러 인스턴스 떠도 "선택"은 한번만 처리
        if already_processed(interaction.message.id):
            await interaction.response.send_message("이미 처리됨", ephemeral=True)
            return

        if interaction.user.id != self.author_id:
            await interaction.response.send_message("니가 검색한 거 아님", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        rid = int(self.values[0])
        try:
            rel = discogs_release(rid)
        except Exception as e:
            await interaction.followup.send(f"Discogs 조회 실패: {e}", ephemeral=True)
            return

        album_title = rel.get("title") or "Unknown"
        artists = ", ".join([a.get("name", "").strip() for a in rel.get("artists", []) if a.get("name")]) or "Unknown"
        year = rel.get("year")
        country = rel.get("country")

        cover = None
        imgs = rel.get("images") or []
        if imgs:
            cover = imgs[0].get("uri")
        if not cover:
            cover = rel.get("thumb")

        tracks = discogs_all_tracks(rel)

        lines = []
        for i, t in enumerate(tracks, 1):
            q = f"{artists} {t} audio"
            yt = youtube_link(q)
            if yt:
                lines.append(f"`{i:02}` {t} • [YouTube]({yt})")
            else:
                lines.append(f"`{i:02}` {t}")

        if not lines:
            lines = ["트랙 정보 없음"]

        track_chunks = chunk_lines(lines, limit=1000)
        embeds = build_embeds(album_title, artists, year, country, cover, track_chunks)

        # 결과를 새로 보내지 말고, 선택창 메시지를 "결과"로 교체 + 선택창 제거
        await interaction.message.edit(content=None, embed=embeds[0], view=None)

        # 트랙이 너무 길어서 embed 여러 개면 나머지만 추가로 전송
        if len(embeds) > 1:
            for e in embeds[1:]:
                await interaction.channel.send(embed=e)

        # !lp 쓴 사람 메시지도 삭제 (Manage Messages 필요)
        try:
            await self.origin_message.delete()
        except Exception:
            pass

        await interaction.followup.send("완료", ephemeral=True)

class ReleaseSelectView(discord.ui.View):
    def __init__(self, results, author_id: int, origin_message: discord.Message):
        super().__init__(timeout=60)
        self.add_item(ReleaseSelect(results, author_id, origin_message))

@bot.event
async def on_ready():
    print(f"로그인 완료: {bot.user}")

@bot.command()
async def lp(ctx, *, query: str):
    # 배포 꼬여서 여러 인스턴스 떠도 "검색"은 한번만 처리
    if already_processed(ctx.message.id):
        return

    try:
        results = discogs_search(query, limit=10)
    except Exception as e:
        await ctx.send(f"검색 실패: {e}")
        return

    if not results:
        await ctx.send("검색 결과 없음")
        return

    view = ReleaseSelectView(results, author_id=ctx.author.id, origin_message=ctx.message)
    await ctx.send("고르시오", view=view)

bot.run(DISCORD_TOKEN)
