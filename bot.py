import os
import discord
from discord.ext import commands
import requests

DISCOGS_TOKEN = os.getenv("DISCOGS_TOKEN")
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f"{bot.user} 로그인 완료")

@bot.command()
async def lp(ctx, *, query):
    url = "https://api.discogs.com/database/search"
    params = {
        "q": query,
        "type": "release",
        "format": "vinyl",
        "token": DISCOGS_TOKEN
    }

    response = requests.get(url, params=params)
    data = response.json()

    if data.get("results"):
        album = data["results"][0]
        title = album["title"]
        cover = album["cover_image"]

        embed = discord.Embed(
            title=title,
            description=f"검색어: {query}",
            color=0x8B4513
        )
        embed.set_image(url=cover)

        await ctx.send(embed=embed)
    else:
        await ctx.send("검색 결과 없음")

bot.run(DISCORD_TOKEN)