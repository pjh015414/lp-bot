import os
import time
import base64
import requests
import discord
from discord.ext import commands

# ===== ENV =====
DISCOGS_TOKEN = os.getenv("DISCOGS_TOKEN")
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")

if not DISCOGS_TOKEN or not DISCORD_TOKEN:
    raise RuntimeError("DISCOGS_TOKEN / DISCORD_TOKEN 환경변수 없음")

# ===== Discord =====
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# ===== Discogs =====
DISCOGS_BASE = "https://api.discogs.com"
DISCOGS_HEADERS = {"User-Agent": "lp-bot/final-youtube (discord bot)"}

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
            name = (t.get("title") or "").strip()
            if name:
                tracks.append(name)
    return tracks

# ===== Spotify (optional, not required for full tracklist mode) =====
SPOTIFY_TOKEN_URL = "https://accounts.spotify.com/api/token"
SPOTIFY_API = "https://api.spotify.com/v1"
_spotify_token = None
_spotify_token_exp = 0

def spotify_enabled() -> bool:
    return bool(SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET)

def spotify_get_token() -> str:
    global _spotify_token, _spotify_token_exp
    now = int(time.time())
    if _spotify_token and now < _spotify_token_exp:
        return _spotify_token

    auth = base64.b64encode(f"{SPOTIFY_CLIENT_ID}:{SPOTIFY_CLIENT_SECRET}".encode()).decode()
    headers = {"Authorization": f"Basic {auth}"}
    data = {"grant_type": "client_credentials"}
    r = requests.post(SPOTIFY_TOKEN_URL, headers=headers, data=data, timeout=15)
    r.raise_for_status()
    js = r.json()
    _spotify_token = js["access_token"]
    _spotify_token_exp = now + int(js.get("expires_in", 3600)) - 60
    return _spotify_token

def spotify_headers():
    return {"Authorization": f"Bearer {spotify_get_token()}"}

def spotify_find_album(artist: str, album: str):
    q = f'album:"{album}" artist:"{artist}"'
    params = {"q": q, "type": "album", "limit": 1}
    r = requests.get(f"{SPOTIFY_API}/search", headers=spotify_headers(), params=params, timeout=15)
    r.raise_for_status()
    items = r.json().get("albums", {}).get("items", [])
    return items[0] if items else None

def spotify_album_top3_tracks(album_id: str):
    r = requests.get(
        f"{SPOTIFY_API}/albums/{album_id}/tracks",
        headers=spotify_headers(),
        params={"limit": 50},
        timeout=15,
    )
    r.raise_for_status()
    items = r.json().get("items", [])
    track_ids = [t.get("id") for t in items if t.get("id")]
    if not track_ids:
        return []

    r2 = requests.get(
        f"{SPOTIFY_API}/tracks",
        headers=spotify_headers(),
        params={"ids": ",".join(track_ids[:50])},
        timeout=15,
    )
    r2.raise_for_status()
    tracks = [t for t in r2.json().get("tracks", []) if t]
    tracks.sort(key=lambda t: t.get("popularity", 0), reverse=True)
    return [t["name"] for t in tracks[:3]]

# ===== YouTube =====
YOUTUBE_SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"
_youtube_cache: dict[str, str | None] = {}

def youtube_enabled() -> bool:
    return bool(YOUTUBE_API_KEY)

def get_youtube_link(query: str) -> str | None:
    # 간단 캐시 (같은 곡 반복 검색 방지)
    if query in _youtube_cache:
        return _youtube_cache[query]

    if not youtube_enabled():
        _youtube_cache[query] = None
        return None

    params = {
        "part": "snippet",
        "q": query,
        "key": YOUTUBE_API_KEY,
        "maxResults": 1,
        "type": "video",
        "safeSearch": "none",
    }

    try:
        r = requests.get(YOUTUBE_SEARCH_URL, params=params, timeout=15)
        r.raise_for_status()
        data = r.json()
        items = data.get("items") or []
        if not items:
            _youtube_cache[query] = None
            return None
        video_id = items[0]["id"]["videoId"]
        link = f"https://youtu.be/{video_id}"
        _youtube_cache[query] = link
        return link
    except Exception:
        _youtube_cache[query] = None
        return None

# ===== Formatting =====
def build_track_lines(tracks: list[str], artists: str):
    lines = []
    for i, t in enumerate(tracks):
        # 검색 품질 좀 올리려고 아티스트 + 곡 + audio 키워드
        yt_query = f"{artists} {t} audio"
        link = get_youtube_link(yt_query)
        if link:
            lines.append(f"`{i+1:02}` {t} • [YouTube]({link})")
        else:
            lines.append(f"`{i+1:02}` {t}")
    return lines

def chunk_text(lines: list[str], limit: int):
    # limit 이하로 줄들을 묶어서 문자열 리스트로 반환
    chunks = []
    cur = ""
    for line in lines:
        add = line if not cur else "\n" + line
        if len(cur) + len(add) > limit:
            if cur:
                chunks.append(cur)
                cur = line
            else:
                # 한 줄이 너무 길면 그냥 잘라서라도 넣기
                chunks.append(line[:limit])
                cur = ""
        else:
            cur += add
    if cur:
        chunks.append(cur)
    return chunks

def make_embeds(album_title: str, artists: str, year, country, cover_url: str | None, track_chunks: list[str]):
    # 디스코드 embed 제한 고려:
    # - description 4096
    # - field value 1024
    # - embed당 field 최대 25
    embeds = []

    header = discord.Embed(
        title=album_title,
        description=f" {artists}",
        color=0x2b2d31
    )

    info = []
    if year:
        info.append(f" {year}")
    if country:
        info.append(f" {country}")
    if info:
        header.add_field(name="앨범 정보", value=" / ".join(info), inline=False)

    if cover_url:
        header.set_image(url=cover_url)

    footer_bits = []
    if youtube_enabled():
        footer_bits.append("YouTube 링크 포함")
    else:
        footer_bits.append("YouTube 키 없음")
    if spotify_enabled():
        footer_bits.append("Spotify 있음")
    header.set_footer(text="LP Bot • " + " / ".join(footer_bits))

    # 트랙은 여러 embed로 나눠도 됨
    # 첫 embed에 트랙 일부 붙이고, 넘치면 계속 embed 생성
    current = header
    field_count = 1 if info else 0  # info field 유무
    for idx, chunk in enumerate(track_chunks):
        name = "수록곡 " if idx == 0 else " 수록곡 "
        if field_count >= 24:  # 여유 하나 남기고 새 embed
            embeds.append(current)
            current = discord.Embed(title=album_title, description=f"🎧 {artists}", color=0x2b2d31)
            field_count = 0
        current.add_field(name=name, value=chunk, inline=False)
        field_count += 1

    embeds.append(current)
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

        super().__init__(placeholder="원하는 LP 선택", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("니가 검색한 거 아님", ephemeral=True)
            return

        # 오래 걸릴 수 있으니 타임아웃 방지
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
        lines = build_track_lines(tracks, artists)

        # 트랙 텍스트는 필드 1024 제한 때문에 쪼갬
        track_chunks = chunk_text(lines, limit=1000)

        embeds = make_embeds(album_title, artists, year, country, cover, track_chunks)

        # 선택창(드롭다운) 메시지 삭제 + 원본 !lp 메시지 삭제
        try:
            await interaction.message.delete()
        except Exception:
            pass
        try:
            await self.origin_message.delete()
        except Exception:
            pass

        # 결과는 새 메시지로 출력 (답장 아님)
        for e in embeds:
            await interaction.channel.send(embed=e)

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
    try:
        results = discogs_search(query, limit=10)
    except Exception as e:
        await ctx.send(f"검색 실패: {e}")
        return

    if not results:
        await ctx.send("없음")
        return

    view = ReleaseSelectView(results, author_id=ctx.author.id, origin_message=ctx.message)
    await ctx.send("골라", view=view)

bot.run(DISCORD_TOKEN)
