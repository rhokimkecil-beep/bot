import discord
from discord.ext import commands
import aiohttp
import aiofiles
import os
import json
import tempfile
import asyncio
from aiohttp import web

# ══════════════════════════════════════════════════════
#  CONFIG — isi via Render Environment Variables
#  DISCORD_TOKEN   = token bot Discord
#  ROBLOSECURITY   = cookie .ROBLOSECURITY akun Roblox
#  UPLOAD_GROUP_ID = ID grup Roblox (kosongin kalau personal)
# ══════════════════════════════════════════════════════
DISCORD_TOKEN   = os.environ.get("DISCORD_TOKEN")
ROBLOSECURITY   = os.environ.get("ROBLOSECURITY")
UPLOAD_GROUP_ID = os.environ.get("UPLOAD_GROUP_ID", None)

# ══════════════════════════════════════════════════════
#  BOT SETUP
# ══════════════════════════════════════════════════════
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# ══════════════════════════════════════════════════════
#  ANTI-SLEEP WEB SERVER (biar Render gak sleep)
# ══════════════════════════════════════════════════════
async def handle_ping(request):
    return web.Response(text="Bot is alive!")

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", int(os.environ.get("PORT", 8080)))
    await site.start()
    print("🌐 Web server aktif (anti-sleep)")

# ══════════════════════════════════════════════════════
#  HELPERS
# ══════════════════════════════════════════════════════
async def get_csrf_token(session: aiohttp.ClientSession) -> str:
    async with session.post(
        "https://auth.roblox.com/v2/logout",
        cookies={".ROBLOSECURITY": ROBLOSECURITY}
    ) as resp:
        return resp.headers.get("x-csrf-token", "")


async def get_authenticated_user(session: aiohttp.ClientSession, cookies: dict) -> dict:
    async with session.get(
        "https://users.roblox.com/v1/users/authenticated",
        cookies=cookies
    ) as resp:
        return await resp.json()


async def upload_audio_to_roblox(file_path: str, audio_name: str) -> dict:
    cookies = {".ROBLOSECURITY": ROBLOSECURITY}

    async with aiohttp.ClientSession() as session:
        csrf = await get_csrf_token(session)
        user_data = await get_authenticated_user(session, cookies)
        user_id   = user_data.get("id")
        username  = user_data.get("name", "Unknown")

        if UPLOAD_GROUP_ID:
            creator_payload = {"groupId": int(UPLOAD_GROUP_ID)}
        else:
            creator_payload = {"userId": user_id}

        async with aiofiles.open(file_path, "rb") as f:
            audio_bytes = await f.read()

        file_size = len(audio_bytes)

        form = aiohttp.FormData()
        form.add_field(
            "request",
            json.dumps({
                "assetType": "Audio",
                "displayName": audio_name,
                "description": "Uploaded via Spoof Bot",
                "creationContext": {
                    "creator": creator_payload
                }
            }),
            content_type="application/json"
        )
        form.add_field(
            "fileContent",
            audio_bytes,
            filename=f"{audio_name}.mp3",
            content_type="audio/mpeg"
        )

        headers = {
            "x-csrf-token": csrf,
            "User-Agent": "Mozilla/5.0"
        }

        async with session.post(
            "https://apis.roblox.com/assets/v1/assets",
            headers=headers,
            cookies=cookies,
            data=form
        ) as resp:
            result = await resp.json()

    asset_id = result.get("assetId") or result.get("id") or result.get("operationId")

    return {
        "asset_id": asset_id,
        "name": audio_name,
        "size_kb": round(file_size / 1024, 2),
        "creator": username,
        "raw": result
    }


async def process_single_attachment(attachment, processing_msg):
    """Upload 1 file audio dan return embed hasil"""
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as tmp:
            tmp_path = tmp.name

        async with aiohttp.ClientSession() as dl_session:
            async with dl_session.get(attachment.url) as resp:
                async with aiofiles.open(tmp_path, "wb") as f:
                    await f.write(await resp.read())

        audio_name = os.path.splitext(attachment.filename)[0]
        result = await upload_audio_to_roblox(tmp_path, audio_name)
        asset_id = result.get("asset_id")

        if not asset_id:
            raise Exception(str(result.get("raw", "Response kosong dari Roblox")))

        embed = discord.Embed(
            title="✅ Audio Spoof Berhasil!",
            color=0x00FF88
        )
        embed.add_field(name="🎵 Audio Name", value=audio_name,                    inline=False)
        embed.add_field(name="🆔 Asset ID",   value=f"`{asset_id}`",               inline=True)
        embed.add_field(name="📦 Size",       value=f"{result['size_kb']} KB",     inline=True)
        embed.add_field(
            name="🔗 Sound ID",
            value=f"`rbxassetid://{asset_id}`",
            inline=False
        )
        embed.add_field(
            name="📋 Luau Script",
            value=f"```lua\nSound.SoundId = \"rbxassetid://{asset_id}\"\n```",
            inline=False
        )
        embed.set_footer(text=f"Uploaded by {result['creator']} • Spoof Bot")
        return embed

    except Exception as e:
        embed = discord.Embed(
            title=f"❌ Gagal: {attachment.filename}",
            description=f"```{str(e)[:800]}```",
            color=0xFF0000
        )
        return embed

    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)


# ══════════════════════════════════════════════════════
#  EVENTS
# ══════════════════════════════════════════════════════
@bot.event
async def on_ready():
    print(f"✅ Spoof Bot online: {bot.user}")
    print(f"   Upload target: {'Group ' + UPLOAD_GROUP_ID if UPLOAD_GROUP_ID else 'Personal Account'}")


@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    # Filter hanya attachment audio
    audio_attachments = [
        a for a in message.attachments
        if a.filename.lower().endswith((".mp3", ".ogg", ".wav"))
    ]

    if not audio_attachments:
        await bot.process_commands(message)
        return

    total = len(audio_attachments)

    # Kalau lebih dari 1 file
    if total > 1:
        processing_embed = discord.Embed(
            description=f"⏳ Lagi upload **{total} audio** ke Roblox...",
            color=0xFFA500
        )
        processing_msg = await message.reply(embed=processing_embed)

        results = []
        for i, attachment in enumerate(audio_attachments, 1):
            # Update progress
            await processing_msg.edit(embed=discord.Embed(
                description=f"⏳ Upload **{i}/{total}**: `{attachment.filename}`...",
                color=0xFFA500
            ))
            embed = await process_single_attachment(attachment, processing_msg)
            results.append((attachment.filename, embed))
            await asyncio.sleep(1)  # Jeda antar upload

        # Kirim semua hasil
        await processing_msg.delete()
        summary_embed = discord.Embed(
            title=f"🎵 Batch Spoof Selesai ({total} audio)",
            color=0x00FF88
        )
        await message.reply(embed=summary_embed)

        for filename, embed in results:
            await message.channel.send(embed=embed)

    # Kalau cuma 1 file
    else:
        processing_msg = await message.reply(embed=discord.Embed(
            description="⏳ Lagi upload audio ke Roblox...",
            color=0xFFA500
        ))
        embed = await process_single_attachment(audio_attachments[0], processing_msg)
        await processing_msg.edit(embed=embed)

    await bot.process_commands(message)


# ══════════════════════════════════════════════════════
#  COMMANDS
# ══════════════════════════════════════════════════════
@bot.command(name="ping")
async def ping(ctx):
    await ctx.reply("🏓 Pong! Bot aktif.")


# ══════════════════════════════════════════════════════
#  MAIN — jalanin bot + web server bersamaan
# ══════════════════════════════════════════════════════
async def main():
    await start_web_server()
    await bot.start(DISCORD_TOKEN)

asyncio.run(main())
