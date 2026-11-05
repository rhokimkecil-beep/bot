import discord
from discord.ext import commands
import aiohttp
import aiofiles
import os
import json
import tempfile

# ══════════════════════════════════════════════════════
#  CONFIG — isi via Railway Environment Variables
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

    for attachment in message.attachments:
        if not attachment.filename.lower().endswith((".mp3", ".ogg", ".wav")):
            continue

        processing_embed = discord.Embed(
            description="⏳ Lagi upload audio ke Roblox...",
            color=0xFFA500
        )
        processing_msg = await message.reply(embed=processing_embed)

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
            embed.add_field(name="🎵 Audio Name",  value=audio_name,                      inline=False)
            embed.add_field(name="🆔 Asset ID",    value=f"`{asset_id}`",                 inline=True)
            embed.add_field(name="📦 Size",        value=f"{result['size_kb']} KB",       inline=True)
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

            await processing_msg.edit(embed=embed)

        except Exception as e:
            error_embed = discord.Embed(
                title="❌ Upload Gagal",
                description=f"```{str(e)[:1000]}```",
                color=0xFF0000
            )
            await processing_msg.edit(embed=error_embed)

        finally:
            if tmp_path and os.path.exists(tmp_path):
                os.unlink(tmp_path)

    await bot.process_commands(message)


# ══════════════════════════════════════════════════════
#  RUN
# ══════════════════════════════════════════════════════
bot.run(DISCORD_TOKEN)
