import discord
from discord.ext import commands
import yt_dlp
import asyncio
import os
from pymongo import MongoClient

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix='!', intents=intents)

# اتصال MongoDB
MONGO_URI = os.environ.get('MONGO_URI')
client = MongoClient(MONGO_URI)
db = client['musicbot']
playlists_col = db['playlists']

FFMPEG_OPTIONS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn -filter:a "volume=0.5"'
}

YDL_OPTIONS = {
    'format': 'bestaudio/best',
    'noplaylist': True,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'ytsearch',
}

queues = {}

def get_queue(guild_id):
    if guild_id not in queues:
        queues[guild_id] = []
    return queues[guild_id]

async def play_next(ctx):
    queue = get_queue(ctx.guild.id)
    if queue:
        url, title = queue.pop(0)
        source = discord.FFmpegPCMAudio(url, **FFMPEG_OPTIONS)
        ctx.voice_client.play(
            source,
            after=lambda e: asyncio.run_coroutine_threadsafe(play_next(ctx), bot.loop)
        )
        await ctx.send(f'🎵 **يشغل الآن:** {title}')
    else:
        await ctx.send('✅ انتهت القائمة!')

@bot.event
async def on_ready():
    print(f'✅ البوت شغال: {bot.user}')

@bot.command(name='شغل', aliases=['غني'])
async def play(ctx, *, query):
    if not ctx.author.voice:
        return await ctx.send('❌ لازم تكون في روم صوتي!')
    if not ctx.voice_client:
        await ctx.author.voice.channel.connect()
    elif ctx.voice_client.channel != ctx.author.voice.channel:
        await ctx.voice_client.move_to(ctx.author.voice.channel)
    async with ctx.typing():
        with yt_dlp.YoutubeDL(YDL_OPTIONS) as ydl:
            info = ydl.extract_info(f"ytsearch:{query}", download=False)
            if 'entries' in info:
                info = info['entries'][0]
            url = info['url']
            title = info['title']
    if ctx.voice_client.is_playing():
        get_queue(ctx.guild.id).append((url, title))
        await ctx.send(f'➕ **أضيف للقائمة:** {title}')
    else:
        source = discord.FFmpegPCMAudio(url, **FFMPEG_OPTIONS)
        ctx.voice_client.play(
            source,
            after=lambda e: asyncio.run_coroutine_threadsafe(play_next(ctx), bot.loop)
        )
        await ctx.send(f'🎵 **يشغل الآن:** {title}')

@bot.command(name='تخطى', aliases=['سكب'])
async def skip(ctx):
    if ctx.voice_client and ctx.voice_client.is_playing():
        ctx.voice_client.stop()
        await ctx.send('⏭️ تم التخطي!')
    else:
        await ctx.send('❌ ما في شي يشتغل!')

@bot.command(name='قائمة')
async def queue_cmd(ctx):
    queue = get_queue(ctx.guild.id)
    if not queue:
        return await ctx.send('📭 القائمة فارغة!')
    msg = '**📋 قائمة الانتظار:**\n'
    for i, (_, title) in enumerate(queue, 1):
        msg += f'`{i}.` {title}\n'
    await ctx.send(msg)

@bot.command(name='وقف')
async def stop(ctx):
    if ctx.voice_client:
        queues[ctx.guild.id] = []
        ctx.voice_client.stop()
        await ctx.send('⏹️ وقف التشغيل وتم مسح القائمة')

@bot.command(name='مسح')
async def clear_queue(ctx):
    queue = get_queue(ctx.guild.id)
    if queue:
        queue.clear()
        await ctx.send('🗑️ تم مسح القائمة والأغنية الحالية تكمل!')
    else:
        await ctx.send('📭 القائمة فارغة أصلاً!')

@bot.command(name='اخرج')
async def leave(ctx):
    if ctx.voice_client:
        await ctx.voice_client.disconnect()
        queues[ctx.guild.id] = []
        await ctx.send('👋 خرجت!')

@bot.command(name='توقف')
async def pause(ctx):
    if ctx.voice_client and ctx.voice_client.is_playing():
        ctx.voice_client.pause()
        await ctx.send('⏸️ تم الإيقاف المؤقت')

@bot.command(name='كمل')
async def resume(ctx):
    if ctx.voice_client and ctx.voice_client.is_paused():
        ctx.voice_client.resume()
        await ctx.send('▶️ استمر التشغيل')

@bot.command(name='حفظ')
async def save_song(ctx, playlist_name: str, *, song: str):
    playlists_col.update_one(
        {'guild_id': str(ctx.guild.id), 'name': playlist_name},
        {'$push': {'songs': song}},
        upsert=True
    )
    await ctx.send(f'✅ تم حفظ **{song}** في قائمة **{playlist_name}**')

@bot.command(name='شغل_قائمة')
async def play_playlist(ctx, playlist_name: str):
    data = playlists_col.find_one({'guild_id': str(ctx.guild.id), 'name': playlist_name})
    if not data or not data.get('songs'):
        return await ctx.send(f'❌ ما لقيت قائمة باسم **{playlist_name}**')
    if not ctx.author.voice:
        return await ctx.send('❌ لازم تكون في روم صوتي!')
    if not ctx.voice_client:
        await ctx.author.voice.channel.connect()
    await ctx.send(f'📋 جاري تحميل قائمة **{playlist_name}** ({len(data["songs"])} أغاني)')
    for song in data['songs']:
        with yt_dlp.YoutubeDL(YDL_OPTIONS) as ydl:
            info = ydl.extract_info(f"ytsearch:{song}", download=False)
            if 'entries' in info:
                info = info['entries'][0]
            url = info['url']
            title = info['title']
        get_queue(ctx.guild.id).append((url, title))
    if not ctx.voice_client.is_playing():
        await play_next(ctx)

@bot.command(name='عرض_قائمة')
async def show_playlist(ctx, playlist_name: str):
    data = playlists_col.find_one({'guild_id': str(ctx.guild.id), 'name': playlist_name})
    if not data or not data.get('songs'):
        return await ctx.send(f'❌ ما لقيت قائمة باسم **{playlist_name}**')
    msg = f'**📋 قائمة {playlist_name}:**\n'
    for i, song in enumerate(data['songs'], 1):
        msg += f'`{i}.` {song}\n'
    await ctx.send(msg)

@bot.command(name='قوائمي')
async def my_playlists(ctx):
    data = list(playlists_col.find({'guild_id': str(ctx.guild.id)}))
    if not data:
        return await ctx.send('📭 ما عندك أي قوائم محفوظة!')
    msg = '**📋 قوائمك المحفوظة:**\n'
    for p in data:
        msg += f'• **{p["name"]}** — {len(p.get("songs", []))} أغاني\n'
    await ctx.send(msg)

@bot.command(name='حذف_قائمة')
async def delete_playlist(ctx, playlist_name: str):
    result = playlists_col.delete_one({'guild_id': str(ctx.guild.id), 'name': playlist_name})
    if result.deleted_count:
        await ctx.send(f'🗑️ تم حذف قائمة **{playlist_name}**')
    else:
        await ctx.send(f'❌ ما لقيت قائمة باسم **{playlist_name}**')

@bot.command(name='اوامر')
async def commands_list(ctx):
    msg = """
🎵 **أوامر المغني جود:**

**تشغيل:**
`!شغل [أغنية]` — شغّل أغنية
`!تخطى` — تخطى
`!توقف` — إيقاف مؤقت
`!كمل` — استمر
`!وقف` — وقف ومسح
`!مسح` — امسح القائمة بدون وقف
`!اخرج` — أخرج البوت
`!قائمة` — قائمة الانتظار

**القوائم المحفوظة:**
`!حفظ [اسم] [أغنية]` — احفظ أغنية
`!شغل_قائمة [اسم]` — شغّل قائمة
`!عرض_قائمة [اسم]` — عرض القائمة
`!قوائمي` — كل قوائمك
`!حذف_قائمة [اسم]` — احذف قائمة
"""
    await ctx.send(msg)

TOKEN = os.environ.get('DISCORD_TOKEN')
bot.run(TOKEN)
