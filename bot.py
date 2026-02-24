import discord
from discord.ext import commands
import requests
import os
from discord.ui import Select, View

DISCOGS_TOKEN = os.getenv("DISCOGS_TOKEN")
SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")

if not DISCOGS_TOKEN or not DISCORD_TOKEN:
    raise RuntimeError("토큰 환경변수 없음")

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!lp ", intents=intents)


def get_spotify_token():
    url = "https://accounts.spotify.com/api/token"
    data = {"grant_type": "client_credentials"}
    response = requests.post(
        url,
        data=data,
        auth=(SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET)
    )
    return response.json().get("access_token")


def search_youtube(query):
    if not YOUTUBE_API_KEY:
        return None
    url = "https://www.googleapis.com/youtube/v3/search"
    params = {
        "part": "snippet",
        "q": query,
        "key": YOUTUBE_API_KEY,
        "maxResults": 1,
        "type": "video"
    }
    r = requests.get(url, params=params).json()
    items = r.get("items")
    if items:
        video_id = items[0]["id"]["videoId"]
        return f"https://youtu.be/{video_id}"
    return None


def get_album_tracks_spotify(artist, album):
    if not SPOTIFY_CLIENT_ID or not SPOTIFY_CLIENT_SECRET:
        return None

    token = get_spotify_token()
    headers = {"Authorization": f"Bearer {token}"}

    search_url = "https://api.spotify.com/v1/search"
    params = {
        "q": f"album:{album} artist:{artist}",
        "type": "album",
        "limit": 1
    }
    res = requests.get(search_url, headers=headers, params=params).json()
    albums = res.get("albums", {}).get("items", [])

    if not albums:
        return None

    album_id = albums[0]["id"]
    tracks_url = f"https://api.spotify.com/v1/albums/{album_id}/tracks"
    tracks_res = requests.get(tracks_url, headers=headers).json()

    tracks = []
    for t in tracks_res.get("items", []):
        tracks.append(t["name"])

    return tracks


def search_discogs(query):
    url = "https://api.discogs.com/database/search"
    params = {
        "q": query,
        "type": "release",
        "per_page": 5,
        "token": DISCOGS_TOKEN
    }
    r = requests.get(url, params=params).json()
    return r.get("results", [])


class AlbumSelect(Select):
    def __init__(self, albums, original_message):
        options = []
        for i, album in enumerate(albums):
            title = album.get("title", "Unknown")
            year = album.get("year", "N/A")
            options.append(
                discord.SelectOption(
                    label=f"{title[:90]}",
                    description=f"{year}",
                    value=str(i)
                )
            )

        super().__init__(placeholder="앨범 선택", options=options)
        self.albums = albums
        self.original_message = original_message

    async def callback(self, interaction: discord.Interaction):
        index = int(self.values[0])
        album = self.albums[index]

        title = album.get("title", "Unknown")
        year = album.get("year", "N/A")
        country = album.get("country", "Unknown")
        cover = album.get("cover_image")

        artist, album_name = title.split(" - ", 1) if " - " in title else ("Unknown", title)

        tracks = get_album_tracks_spotify(artist, album_name)
        if not tracks:
            tracks = ["트랙 정보 없음"]

        track_text = ""
        for i, track in enumerate(tracks, 1):
            yt = search_youtube(f"{artist} {track}")
            if yt:
                track_text += f"{i:02d} {track} · [YouTube]({yt})\n"
            else:
                track_text += f"{i:02d} {track}\n"

        embed = discord.Embed(
            title=artist,
            description=f"{album_name}\n\n앨범 정보\n{year} / {country}\n\n수록곡\n{track_text}",
            color=0x2b2d31
        )

        if cover:
            embed.set_image(url=cover)

        # 선택창 + 드롭다운 삭제하고 결과만 남김 (중복 출력 방지 핵심)
        await interaction.response.edit_message(embed=embed, view=None)

        # !lp 명령어 메시지도 삭제 (관리자 권한 필요)
        try:
            await self.original_message.delete()
        except:
            pass


class AlbumView(View):
    def __init__(self, albums, original_message):
        super().__init__(timeout=60)
        self.add_item(AlbumSelect(albums, original_message))


@bot.command(name="lp")
async def lp(ctx, *, query):
    albums = search_discogs(query)

    if not albums:
        await ctx.send("없음")
        return

    # 선택창 메시지 (이게 나중에 결과로 덮어씌워짐)
    view = AlbumView(albums, ctx.message)
    msg = await ctx.send("고르시오", view=view)
    view.message = msg


bot.run(DISCORD_TOKEN)
