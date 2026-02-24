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

if not DISCOGS_TOKEN or not DISCORD_TOKEN:
    raise RuntimeError("DISCOGS_TOKEN / DISCORD_TOKEN 환경변수 없음")

# ===== Discord =====
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# ===== Discogs =====
DISCOGS_BASE = "https://api.discogs.com"
DISCOGS_HEADERS = {"User-Agent": "lp-bot/Final (discord bot)"}

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

def discogs_first3_tracks(release_json: dict):
    tracks = []
    for t in release_json.get("tracklist", []):
        if t.get("type_") == "track":
            name = (t.get("title") or "").strip()
            if name:
                tracks.append(name)
    return tracks[:3]

# ===== Spotify (popularity TOP3) =====
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

# ===== Formatting =====
def format_tracks_010203(tracks):
    if not tracks:
        return "트랙 정보 없음"
    return "\n".join([f"`{i+1:02}` {name}" for i, name in enumerate(tracks)])

def build_embed(album_title: str, artists: str, year, country, cover_url: str | None, top3: list[str]):
    embed = discord.Embed(
        title=album_title,
        description=f"🎧 {artists}",
        color=0x2b2d31
    )

    info = []
    if year:
        info.append(f"📅 {year}")
    if country:
        info.append(f"🌍 {country}")
    if info:
        embed.add_field(name="📀 앨범 정보", value=" / ".join(info), inline=False)

    embed.add_field(
        name="💿 대표 인기 수록곡 TOP3",
        value=format_tracks_010203(top3),
        inline=False
    )

    if cover_url:
        embed.set_image(url=cover_url)

    src = "Spotify(popularity) + Discogs(fallback)" if spotify_enabled() else "Discogs(tracklist 앞 3곡)"
    embed.set_footer(text=f"LP Bot • {src}")
    return embed

# ===== UI =====
class ReleaseSelect(discord.ui.Select):
    def __init__(self, results, author_id: int):
        self.author_id = author_id

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
        # 검색한 사람만 선택 가능
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("니가 검색한 거 아님", ephemeral=True)
            return

        rid = int(self.values[0])

        try:
            rel = discogs_release(rid)
        except Exception as e:
            await interaction.response.send_message(f"Discogs 조회 실패: {e}", ephemeral=True)
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

        # Spotify 인기 TOP3 → 실패시 Discogs 앞 3곡
        top3 = []
        if spotify_enabled():
            try:
                alb = spotify_find_album(artists, album_title)
                if alb and alb.get("id"):
                    top3 = spotify_album_top3_tracks(alb["id"])
            except Exception:
                top3 = []

        if not top3:
            top3 = discogs_first3_tracks(rel)

        embed = build_embed(album_title, artists, year, country, cover, top3)

        # 1) 선택창(드롭다운) 메시지 삭제
        # 2) 결과는 새 메시지로 출력 (답장 아님)
        try:
            await interaction.message.delete()
        except Exception:
            pass

        await interaction.response.send_message("처리됨", ephemeral=True)
        await interaction.channel.send(embed=embed)

class ReleaseSelectView(discord.ui.View):
    def __init__(self, results, author_id: int):
        super().__init__(timeout=60)
        self.add_item(ReleaseSelect(results, author_id))

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
        await ctx.send("검색 결과 없음")
        return

    view = ReleaseSelectView(results, author_id=ctx.author.id)
    await ctx.send("골라.", view=view)

bot.run(DISCORD_TOKEN)
