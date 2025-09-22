import discord
from discord.ext import commands
import yt_dlp
import asyncio
from discord.ui import View, Button
import random
import os

# -------------------- Bot 設定 --------------------
intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True
bot = commands.Bot(command_prefix="!", intents=intents)

# -------------------- 歌曲隊列 --------------------
queues = {}  # key=guild.id, value=list of {"url":..., "title":...}
current_song = {}  # key=guild.id, value=current song index

# -------------------- YouTube 解析 --------------------
cookies_file = os.path.join(os.getcwd(), "cookies.txt")

def get_audio_url(query):
    ydl_opts = {
        'format': 'bestaudio/best',
        'quiet': True,
        'noplaylist': True,
        'default_search': 'ytsearch',
    }
    if os.path.isfile(cookies_file):
        ydl_opts['cookiefile'] = cookies_file
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(query, download=False)
            if 'entries' in info:
                info = info['entries'][0]
            return info['url'], info['title']
    except Exception as e:
        print(f"[錯誤] 影片解析失敗: {query} -> {e}")
        return None, None

# -------------------- 播放音樂 --------------------
async def play_queue(guild_id):
    if guild_id not in queues or not queues[guild_id]:
        current_song[guild_id] = None
        return

    vc = bot.get_guild(guild_id).voice_client
    if not vc:
        return

    FFMPEG_OPTIONS = {
        'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
        'options': '-vn'
    }

    while queues[guild_id]:
        index = current_song.get(guild_id, 0)
        song = queues[guild_id][index]
        if song['url'] is None:
            # 跳過解析失敗的歌曲
            if current_song[guild_id] + 1 < len(queues[guild_id]):
                current_song[guild_id] += 1
            else:
                queues[guild_id] = []
                current_song[guild_id] = None
            continue
        source = discord.FFmpegPCMAudio(song['url'], **FFMPEG_OPTIONS)
        vc.play(source)
        while vc.is_playing() or vc.is_paused():
            await asyncio.sleep(1)
        # 下一首
        if current_song[guild_id] + 1 < len(queues[guild_id]):
            current_song[guild_id] += 1
        else:
            queues[guild_id] = []
            current_song[guild_id] = None

# -------------------- 語音操作 --------------------
async def join_vc(user, guild):
    if not user.voice or not user.voice.channel:
        return None, "你不在語音頻道！"
    channel = user.voice.channel
    try:
        if guild.voice_client:
            await guild.voice_client.move_to(channel)
        else:
            await channel.connect()
        return guild.voice_client, f"已加入 {channel.name}"
    except Exception as e:
        return None, f"加入語音頻道失敗: {e}"

async def leave_vc(vc_client, guild_id):
    if vc_client:
        await vc_client.disconnect()
        queues[guild_id] = []
        current_song[guild_id] = None
        return "已離開語音頻道"
    return "我不在語音頻道！"

async def stop_audio(vc_client, guild_id):
    if vc_client and vc_client.is_playing():
        vc_client.stop()
        queues[guild_id] = []
        current_song[guild_id] = None
        return "已停止播放"
    return "目前沒有音樂播放"

async def skip_song(vc_client, guild_id):
    if vc_client and vc_client.is_playing():
        vc_client.stop()
        if current_song[guild_id] + 1 < len(queues[guild_id]):
            current_song[guild_id] += 1
        return "已跳到下一首"
    return "目前沒有音樂播放"

async def prev_song(vc_client, guild_id):
    if vc_client and vc_client.is_playing():
        vc_client.stop()
        if current_song[guild_id] > 0:
            current_song[guild_id] -= 1
        return "已跳到上一首"
    return "目前沒有音樂播放"

async def shuffle_queue(guild_id):
    if guild_id in queues and queues[guild_id]:
        random.shuffle(queues[guild_id])
        current_song[guild_id] = 0
        return "已隨機播放隊列"
    return "目前隊列是空的"

async def add_song(guild_id, query):
    url, title = get_audio_url(query)
    if guild_id not in queues:
        queues[guild_id] = []
        current_song[guild_id] = 0
    queues[guild_id].append({"url": url, "title": title})
    return title if title else "解析失敗的歌曲"

# -------------------- 按鈕介面 --------------------
class MusicControls(View):
    def __init__(self, guild_id):
        super().__init__(timeout=None)
        self.guild_id = guild_id

    @discord.ui.button(label="播放/暫停", style=discord.ButtonStyle.primary)
    async def play_pause(self, interaction: discord.Interaction, button: Button):
        vc = interaction.guild.voice_client
        if not vc or current_song.get(self.guild_id) is None:
            await interaction.response.send_message("目前沒有音樂", ephemeral=True)
            return
        if vc.is_playing():
            vc.pause()
            await interaction.response.send_message("已暫停", ephemeral=True)
        elif vc.is_paused():
            vc.resume()
            await interaction.response.send_message("已恢復播放", ephemeral=True)

    @discord.ui.button(label="上一首", style=discord.ButtonStyle.secondary)
    async def previous(self, interaction: discord.Interaction, button: Button):
        vc = interaction.guild.voice_client
        msg = await prev_song(vc, self.guild_id)
        await interaction.response.send_message(msg, ephemeral=True)
        await play_queue(self.guild_id)

    @discord.ui.button(label="下一首", style=discord.ButtonStyle.success)
    async def next(self, interaction: discord.Interaction, button: Button):
        vc = interaction.guild.voice_client
        msg = await skip_song(vc, self.guild_id)
        await interaction.response.send_message(msg, ephemeral=True)
        await play_queue(self.guild_id)

    @discord.ui.button(label="停止播放", style=discord.ButtonStyle.danger)
    async def stop_btn(self, interaction: discord.Interaction, button: Button):
        vc = interaction.guild.voice_client
        msg = await stop_audio(vc, self.guild_id)
        await interaction.response.send_message(msg, ephemeral=True)

    @discord.ui.button(label="清空隊列", style=discord.ButtonStyle.secondary)
    async def clear(self, interaction: discord.Interaction, button: Button):
        queues[self.guild_id] = []
        current_song[self.guild_id] = None
        await interaction.response.send_message("已清空隊列", ephemeral=True)

    @discord.ui.button(label="隨機播放", style=discord.ButtonStyle.secondary)
    async def shuffle(self, interaction: discord.Interaction, button: Button):
        msg = await shuffle_queue(self.guild_id)
        await interaction.response.send_message(msg, ephemeral=True)
        await play_queue(self.guild_id)

    @discord.ui.button(label="查看隊列", style=discord.ButtonStyle.secondary)
    async def view_queue(self, interaction: discord.Interaction, button: Button):
        if self.guild_id not in queues or not queues[self.guild_id]:
            await interaction.response.send_message("目前隊列是空的", ephemeral=True)
            return
        queue_list = "\n".join(f"{i+1}. {song['title']}" for i, song in enumerate(queues[self.guild_id]))
        await interaction.response.send_message(f"當前隊列:\n{queue_list}", ephemeral=True)

# -------------------- 指令 --------------------
@bot.command()
async def vcjoin(ctx):
    vc, msg = await join_vc(ctx.author, ctx.guild)
    await ctx.send(msg)

@bot.command()
async def vcleave(ctx):
    msg = await leave_vc(ctx.guild.voice_client, ctx.guild.id)
    await ctx.send(msg)

@bot.command()
async def play(ctx, *, query: str):
    vc = ctx.guild.voice_client
    if not vc:
        await ctx.send("我還沒加入語音頻道!")
        return
    title = await add_song(ctx.guild.id, query)
    view = MusicControls(ctx.guild.id)
    await ctx.send(f"已加入隊列: {title}", view=view)
    await play_queue(ctx.guild.id)

@bot.command()
async def queue(ctx):
    guild_id = ctx.guild.id
    if guild_id not in queues or not queues[guild_id]:
        await ctx.send("目前隊列是空的")
        return
    queue_list = "\n".join(f"{i+1}. {song['title']}" for i, song in enumerate(queues[guild_id]))
    await ctx.send(f"當前隊列:\n{queue_list}")

@bot.command()
async def stop(ctx):
    vc = ctx.guild.voice_client
    msg = await stop_audio(vc, ctx.guild.id)
    await ctx.send(msg)

# -------------------- 啟動 Bot --------------------
bot.run(os.getenv("DISCORD_TOKEN"))