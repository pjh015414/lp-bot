import os
import requests
import discord
from discord.ext import commands

# ================== ENV ==================
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
DISCOGS_TOKEN = os.getenv("DISCOGS_TOKEN")
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")  # optional

if not DISCORD_TOKEN or not DISCOGS_TOKEN:
    raise RuntimeError("DISCORD_TOKEN / DISCOGS_TOKEN 환경변수 없음")

# ================== DISCORD ==================
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# ================== DISCOGS ==================
DISCOGS_BASE = "https://api.discogs.com"
DISCOGS_HEADERS = {
    "User-Agent": "lp-bot/final",
}

def discogs_search_vinyl(query: str, limit: int = 10):
    url = f"{DISCOGS_BASE}/database/search"
    params = {
        "q": query,
        "type": "release",
        "format": "vinyl",
        "per_page": limit,
        "token": DISCOGS_TOKEN,
    }
    r = requests.get(url, params=params, headers=DISCOGS_HEADERS, timeout=20)
    r.raise_for_status()
    return r.json().get("results", [])

def discogs_release(release_id: int):
    url = f"{DISCOGS_BASE}/releases/{release_id}"
    params = {"token": DISCOGS_TOKEN}
    r = requests.get(url, params=params, headers=DISCOGS_HEADERS, timeout=20)
    r.raise_for_status()
    return r.json()

def discogs_tracks(release_json: dict):
    tracks = []
    for t in release_json.get("tracklist", []):
        if t.get("type_") == "track":
            title = (t.get("title") or "").strip()
            if title:
                tracks.append(title)
    return tracks

def pick_cover(release_json: dict) -> str | None:
    imgs = release_json.get("images") or []
    if imgs and imgs[0].get("uri"):
        return imgs[0]["uri"]
    thumb = release_json.get("thumb")
    return thumb if thumb else None

# ================== YOUTUBE ==================
YOUTUBE_SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"
yt_cache: dict[str, str | None] = {}

def youtube_enabled() -> bool:
    return bool(YOUTUBE_API_KEY)

def youtube_link(artist: str, track: str, album: str) -> str | None:
    """검색 정확도 강화 버전. 없으면 None."""
    if not youtube_enabled():
        return None

    key = f"{artist}|{track}|{album}"
    if key in yt_cache:
        return yt_cache[key]

    # 흔한 곡명(Everything, Cherry, August 등) 대응:
    # - 앨범명 포함
    # - Official Audio / Topic / audio 순으로 재시도
    queries = [
        f'"{track}" "{artist}" "{album}" official audio',
        f'"{track}" "{artist}" topic',
        f'{artist} {track} "{album}" official audio',
        f'{artist} {track} audio',
    ]

    for q in queries:
        try:
            params = {
                "part": "snippet",
                "q": q,
                "key": YOUTUBE_API_KEY,
                "maxResults": 1,
                "type": "video",
                "videoCategoryId": "10",  # Music
                "safeSearch": "none",
            }
            r = requests.get(YOUTUBE_SEARCH_URL, params=params, timeout=20)
            r.raise_for_status()
            items = r.json().get("items") or []
            if items:
                vid = items[0]["id"]["videoId"]
                link = f"https://youtu.be/{vid}"
                yt_cache[key] = link
                return link
        except Exception:
            continue

    yt_cache[key] = None
    return None

# ================== EMBED HELPERS ==================
def make_track_lines(artist: str, album: str, tracks: list[str]) -> list[str]:
    lines = []
    for i, t in enumerate(tracks, 1):
        num = f"{i:02}"
        yt = youtube_link(artist, t, album)
        if yt:
            lines.append(f"`{num}` {t} · [YouTube]({yt})")
        else:
            lines.append(f"`{num}` {t}")
    return lines

def chunk_to_fields(lines: list[str], max_chars: int = 1000) -> list[str]:
    """discord embed field value limit(1024) 근처로 분할"""
    chunks = []
    cur = ""
    for line in lines:
        add = (line if not cur else "\n" + line)
        if len(cur) + len(add) > max_chars:
            if cur:
                chunks.append(cur)
                cur = line
            else:
                chunks.append(line[:max_chars])
                cur = ""
        else:
            cur += add
    if cur:
        chunks.append(cur)
    return chunks

def build_result_embeds(title: str, artist: str, year, country, cover_url: str | None, track_lines: list[str]) -> list[discord.Embed]:
    footer = "LP Bot • " + ("YouTube 있음" if youtube_enabled() else "YouTube 키 없음")

    base = discord.Embed(
        title=title,
        description=f"{artist}",
        color=0x2b2d31,
    )

    info_bits = []
    if year:
        info_bits.append(str(year))
    if country:
        info_bits.append(str(country))
    if info_bits:
        base.add_field(name="앨범 정보", value=" / ".join(info_bits), inline=False)

    if cover_url:
        base.set_image(url=cover_url)

    base.set_footer(text=footer)

    chunks = chunk_to_fields(track_lines, max_chars=1000)

    embeds: list[discord.Embed] = []
    cur = base
    fields_used = len(cur.fields)

    for idx, chunk in enumerate(chunks):
        field_name = "수록곡" if idx == 0 else "수록곡 (계속)"
        # embed field는 최대 25개라 안전하게 분리
        if fields_used >= 24:
            embeds.append(cur)
            cur = discord.Embed(title=title, description=f"{artist}", color=0x2b2d31)
            cur.set_footer(text=footer)
            fields_used = 0

        cur.add_field(name=field_name, value=chunk, inline=False)
        fields_used += 1

    embeds.append(cur)
    return embeds

# ================== UI ==================
class LPSelect(discord.ui.Select):
    def __init__(self, results: list[dict], author_id: int, origin_message: discord.Message):
        self.author_id = author_id
        self.origin_message = origin_message

        options = []
        for item in results[:10]:
            rid = item.get("id")
            if not rid:
                continue
            title = (item.get("title") or "Unknown").strip()
            year = item.get("year")
            country = item.get("country")
            desc_parts = []
            if year:
                desc_parts.append(str(year))
            if country:
                desc_parts.append(str(country))
            desc = " / ".join(desc_parts) if desc_parts else "release"

            options.append(
                discord.SelectOption(
                    label=title[:100],
                    description=desc[:100],
                    value=str(rid),
                )
            )

        super().__init__(placeholder="원하는 LP 선택", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        # 본인만 선택 가능
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

        title = rel.get("title") or "Unknown"
        artists = ", ".join([a.get("name", "").strip() for a in (rel.get("artists") or []) if a.get("name")]) or "Unknown"
        year = rel.get("year")
        country = rel.get("country")
        cover = pick_cover(rel)

        tracks = discogs_tracks(rel)
        track_lines = make_track_lines(artists, title, tracks) if tracks else ["트랙 정보 없음"]

        embeds = build_result_embeds(title, artists, year, country, cover, track_lines)

        # 1) 드롭다운 메시지 자체를 "결과"로 교체 + 드롭다운 제거
        await interaction.message.edit(content=None, embed=embeds[0], view=None)

        # 2) 트랙이 너무 길면 나머지 embed만 추가 전송
        if len(embeds) > 1:
            for e in embeds[1:]:
                await interaction.channel.send(embed=e)

        # 3) !lp 쓴 사람 메시지 삭제 (봇에 Manage Messages 권한 필요)
        try:
            await self.origin_message.delete()
        except Exception:
            pass

        await interaction.followup.send("완료", ephemeral=True)

class LPView(discord.ui.View):
    def __init__(self, results: list[dict], author_id: int, origin_message: discord.Message):
        super().__init__(timeout=60)
        self.add_item(LPSelect(results, author_id, origin_message))

    async def on_timeout(self):
        # 시간 지나면 선택창만 깔끔히 제거
        for item in self.children:
            item.disabled = True

@bot.event
async def on_ready():
    print(f"로그인 완료: {bot.user}")

@bot.command()
async def lp(ctx, *, query: str):
    # 결과 여러개면 드롭다운 1개만 띄움
    try:
        results = discogs_search_vinyl(query, limit=10)
    except Exception as e:
        await ctx.send(f"검색 실패: {e}")
        return

    if not results:
        await ctx.send("없음")
        return

    view = LPView(results, author_id=ctx.author.id, origin_message=ctx.message)
    await ctx.send("고르시오", view=view)

bot.run(DISCORD_TOKEN)
