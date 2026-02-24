import os
import time
import base64
import requests
import discord
from discord.ext import commands

DISCOGS_TOKEN = os.getenv("DISCOGS_TOKEN")
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")

if not DISCOGS_TOKEN or not DISCORD_TOKEN:
    raise RuntimeError("DISCOGS_TOKEN / DISCORD_TOKEN 환경변수 없음")

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# ===== Discogs =====
DISCOGS_BASE = "https://api.discogs.com"
DISCOGS_HEADERS = {"User-Agent": "lp-bot/final (discord bot)"}

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

# ===== Spotify (optional, just for footer info) =====
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

def spotify_album_track_ids(album_id: str):
    r = requests.get(
        f"{SPOTIFY_API}/albums/{album_id}/tracks",
        headers=spotify_headers(),
        params={"limit": 50},
        timeout=15,
    )
    r.raise_for_status()
    items = r.json().get("items", [])
    return [t.get("id") for t in items if t.get("id")]

def spotify_get_popularity_map(track_ids: list[str]):
    # returns {track_name: popularity}
    if not track_ids:
        return {}
    r = requests.get(
        f"{SPOTIFY_API}/tracks",
        headers=spotify_headers(),
        params={"ids": ",".join(track_ids[:50])},
        timeout=15,
    )
    r.raise_for_status()
    tracks = [t for t in r.json().get("tracks", []) if t]
    return {t["name"]: t.get("popularity", 0) for t in tracks}

# ===== YouTube =====
YOUTUBE_SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"
_yt_cache: dict[str, str | None] = {}

def youtube_enabled() -> bool:
    return bool(YOUTUBE_API_KEY)

def youtube_link(q: str) -> str | None:
    if q in _yt_cache:
        return _yt_cache[q]
    if not youtube_enabled():
        _yt_cache[q] = None
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
            _yt_cache[q] = None
            return None
        vid = items[0]["id"]["videoId"]
        link = f"https://youtu.be/{vid}"
        _yt_cache[q] = link
        return link
    except Exception:
        _yt_cache[q] = None
        return None

# ===== Formatting helpers =====
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

def build_embeds(album_title: str, artists: str, year, country, cover_url: str | None, track_chunks: list[str], footer: str):
    embeds = []

    base = discord.Embed(
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
        base.add_field(name=" 앨범 정보", value=" / ".join(info), inline=False)

    if cover_url:
        base.set_image(url=cover_url)

    base.set_footer(text=footer)

    # 첫 embed에 트랙 필드들 채우고, 25개 넘으면 새 embed
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

        super().__init__(placeholder="원하는 LP 선택", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("니가 검색한 거 아님", ephemeral=True)
            return

        # 타임아웃 방지 (유튜브/스포티파이 때문에 오래 걸림)
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

        # Spotify popularity (있으면 참고용으로 쓴다)
        pop_map = {}
        if spotify_enabled():
            try:
                alb = spotify_find_album(artists, album_title)
                if alb and alb.get("id"):
                    ids = spotify_album_track_ids(alb["id"])
                    pop_map = spotify_get_popularity_map(ids)
            except Exception:
                pop_map = {}

        lines = []
        for i, t in enumerate(tracks, 1):
            q = f"{artists} {t} audio"
            yt = youtube_link(q)
            # popularity 표시(있으면)
            pop = pop_map.get(t)
            pop_txt = f" ({pop})" if isinstance(pop, int) and pop > 0 else ""

            if yt:
                lines.append(f"`{i:02}` {t}{pop_txt} • [YouTube]({yt})")
            else:
                lines.append(f"`{i:02}` {t}{pop_txt}")

        if not lines:
            lines = ["트랙 정보 없음"]

        track_chunks = chunk_lines(lines, limit=1000)

        footer_bits = []
        footer_bits.append("YouTube 있음" if youtube_enabled() else "YouTube 키 없음")
        footer_bits.append("Spotify 있음" if spotify_enabled() else "Spotify 없음")
        footer = "LP Bot • " + " / ".join(footer_bits)

        embeds = build_embeds(album_title, artists, year, country, cover, track_chunks, footer)

        # 핵심: 결과를 “새로 보내지 말고”, 선택창 메시지를 결과로 교체
        # 1) 선택창에 최종 결과 embed 1개만 박고(view=None로 선택창 제거)
        try:
            await interaction.message.edit(embed=embeds[0], view=None, content=None)
        except Exception as e:
            await interaction.followup.send(f"메시지 수정 실패: {e}", ephemeral=True)
            return

        # 2) 나머지 embed가 있으면 추가로 보내기(트랙이 너무 길 때만)
        if len(embeds) > 1:
            for e in embeds[1:]:
                await interaction.channel.send(embed=e)

        # !lp 원본 메시지 삭제 (Manage Messages 필요)
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
    try:
        results = discogs_search(query, limit=10)
    except Exception as e:
        await ctx.send(f"검색 실패: {e}")
        return

    if not results:
        await ctx.send("없음")
        return

    view = ReleaseSelectView(results, author_id=ctx.author.id, origin_message=ctx.message)
    await ctx.send("고르시오", view=view)

bot.run(DISCORD_TOKEN)
