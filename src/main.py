import os
import discord
from discord.ext import commands
from dotenv import load_dotenv
import asyncio
from async_timeout import timeout
from functools import partial
from youtube_dlc import *
import youtube_dlc
from youtubesearchpython import VideosSearch, ResultMode
import time
from django.core.validators import URLValidator, ValidationError

load_dotenv()

ytdlopts = {
    'format': '256/140/139',
    'default_search': 'auto',
    'novideo': True,
    'source_address': '0.0.0.0',
    'noplaylist': True,
    'quiet': True
}

# ffmpegopts = {
#  'before_options': '-nostdin',
#  'options': '-vn -sn -dn -ignore_unknown'
# }


TOKEN = os.getenv('DISCORD_TOKEN')
client = commands.Bot(command_prefix='!')
ytdl = YoutubeDL(ytdlopts)
youtube_dlc.utils.bug_reports_message = lambda: ''


def setup(bot):
    bot.add_cog(Music(bot))


@client.event
async def on_ready():
    print(f'{client.user.name} has connected to Discord!')


class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data, requester):
        super().__init__(source)
        self.requester = requester

        self.title = data.get('title')
        self.web_url = data.get('webpage_url')  # all these are fucking temp
        self.duration = data.get('duration')
        self.data = data

    def __getitem__(self, item: str):
        return self.__getattribute__(item)

    @classmethod
    async def create_source(cls, ctx, search: str, *, loop, download=False, start_time="0"):
        loop = loop or asyncio.get_event_loop()
        validate = URLValidator()
        try:
            validate(search)
            pass
        except ValidationError:
            """Searching for what search was put in"""
            results = VideosSearch(search, limit=5).result(mode=ResultMode.dict)
            searchEmbed = discord.Embed(title="Top 5 Results for " + search,
                                        description="Just message then number of the result you want")

            thumb = results['result'][0]['thumbnails'][0]['url']
            searchEmbed.set_thumbnail(url=thumb)

            for i in range(0, len(results['result'])):
                searchEmbed.add_field(name=str(i+1) + ') ' + results['result'][i]['title'] + ' ' + results['result'][i]['duration'],
                                      value=results['result'][i]['link'], inline=False)
            await ctx.send(embed=searchEmbed)

            choice = None
            try:
                choice = await client.wait_for('message', timeout=30)
                if int(choice.content) not in range(1, len(results['result'])):
                    await ctx.send("Choice terminated, number not in list dumbass")
                    raise IndexError
                search = results['result'][int(choice.content) - 1]['link']
            except asyncio.TimeoutError:
                await ctx.send("Choice timed out")
                return

        to_run = partial(ytdl.extract_info, url=search, download=download)
        data = await loop.run_in_executor(None, to_run)

        if 'entries' in data:
            data = data['entries'][0]

        embed = discord.Embed(title="Queued", description=data['title'])
        await ctx.send(embed=embed)
        option = '-vn -sn -dn -ss ' + str(int(start_time))

        if download:
            source = ytdl.prepare_filename(data)
        else:
            return {'webpage_url': data['webpage_url'], 'requester': ctx.author, 'title': data['title'], 'start_time': 0}

        return cls(discord.FFmpegPCMAudio(source, before_options='-nostdin',
                                          options=option),
                   data=data, requester=ctx.author)

    @classmethod
    async def regather_stream(cls, data, *, loop, start_time="0"):
        loop = loop or asyncio.get_event_loop()
        requester = data['requester']

        to_run = partial(ytdl.extract_info, url=data['webpage_url'], download=False)
        data = await loop.run_in_executor(None, to_run)
        option = '-vn -sn -dn -ss ' + str(int(start_time))

        return cls(discord.FFmpegPCMAudio(data['url'],
                                          before_options='-nostdin',
                                          options=option),
                   data=data, requester=requester)


class MusicPlayer:

    """Is what actually contains the music loop and handles which music is playing"""

    __slots__ = ('bot', '_guild', '_channel', '_cog', 'queue', 'next', 'current', 'np', 'volume', 'broken', 'say_playing', 'skipping')

    def __init__(self, ctx):
        """Standard parts of the discord we need to know"""
        self.bot = ctx.bot
        self._guild = ctx.guild
        self._channel = ctx.channel
        self._cog = ctx.cog

        """The music queue and the solution to if connection is dropped to a websocket"""
        self.queue = asyncio.Queue()
        self.broken = asyncio.Queue()

        self.next = asyncio.Event()

        """Music related settings"""
        self.np = None
        self.volume = 0.1
        self.current = None
        self.say_playing = True
        self.skipping = False

        ctx.bot.loop.create_task(self.player_loop())

    async def player_loop(self):
        """The unending loop of trying to get music from the Queue"""
        await self.bot.wait_until_ready()
        await self.bot.change_presence(activity=discord.Game(name="music, hopefully._."))
        duration_played = 0     # This is the janky fix

        while not self.bot.is_closed():
            source_sound = None
            self.next.clear()

            try:
                async with timeout(1):
                    source = await self.broken.get()    # Get the dropped audio stream
            except asyncio.TimeoutError:
                try:
                    async with timeout(180):
                        source = await self.queue.get()     # Get the next song, given no dropped sources
                except asyncio.TimeoutError:
                    return self.destroy(self._guild)

            if not isinstance(source, YTDLSource):
                try:
                    """Create the audio source"""
                    source_sound = await YTDLSource.regather_stream(source,
                                                                    loop=self.bot.loop,
                                                                    start_time=str(source['start_time']))
                except IndexError:
                    continue
                except Exception as e:
                    await self._channel.send('Bit of an error there chief trying to process the song\n' + str(e))
                    continue

            source_sound.volume = self.volume
            self.current = source_sound

            t = time.time()     # Time for reference later

            self._guild.voice_client.play(source_sound,
                                          after=lambda _: self.bot.loop.call_soon_threadsafe(self.next.set()))

            if self.say_playing:    # Says what is currently playing, if connection was not drop
                embed = discord.Embed(title="Now playing", description=source_sound.title)
                self.np = await self._channel.send(embed=embed)

            await self.next.wait()

            """Catching if we dropped from the socket below"""
            duration_played = duration_played + (time.time() - t)
            if duration_played < int(source_sound.data['duration']) - 5 and not self.skipping:
                source['start_time'] = duration_played
                await self.broken.put(source)
                self.say_playing = False
                print(duration_played)
            else:
                duration_played = 0
                self.say_playing = True
                self.np = None
                self.current = None
                self.skipping = False

            source_sound.cleanup()

    def destroy(self, guild):
        return self.bot.loop.create_task(self._cog.cleanup(guild))


class Music(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.players = {}

    async def cleanup(self, guild):
        try:
            await guild.voice_client.disconnect()
        except AttributeError:
            pass

        try:
            del self.players[guild.id]
        except KeyError:
            pass

    def get_player(self, ctx):
        try:
            player = self.players[ctx.guild.id]
        except KeyError:
            player = MusicPlayer(ctx)
            self.players[ctx.guild.id] = player

        return player

    @commands.command(name='join', aliases=['connect', 'j'], description="Joins your channel!")
    async def connect_(self, ctx: discord.ext.commands.Context, *, channel: discord.VoiceChannel = None):
        if not channel:
            try:
                channel = ctx.author.voice.channel
            except AttributeError:
                await ctx.send('Join a fucking channel you moron')
                raise AttributeError

        vc = ctx.voice_client

        if vc:
            if vc.channel.id == channel.id:
                return
            try:
                await vc.move_to(channel)
            except asyncio.TimeoutError:
                await ctx.send('Moving to new channel took a bit long sorry duder')
                return

        else:
            try:
                await channel.connect()
            except asyncio.TimeoutError:
                await ctx.send('Cannae connect in time capn')

        await ctx.send(channel.name + " joined!")

    @commands.command(name='play', aliases=['p'], description="Searches for query and plays first result!")
    async def play_(self, ctx: discord.ext.commands.Context, *, search: str):
        await ctx.trigger_typing()

        vc = ctx.voice_client

        if not vc:
            try:
                await ctx.invoke(self.connect_)
            except AttributeError:
                return

        player = self.get_player(ctx)
        source = await YTDLSource.create_source(ctx, search, loop=self.bot.loop, download=False)
        await player.queue.put(source)

    @commands.command(name='pause', description="Pauses current song!")
    async def pause_(self, ctx: discord.ext.commands.Context):
        vc = ctx.voice_client

        if not vc or not vc.is_connected():
            return await ctx.send("There's nothing fucking playing dumbass")
        elif vc.is_paused():
            return

        vc.pause()
        await ctx.send("_Pawsed!_")

    @commands.command(name="resume", description="Resumes current song!")
    async def resume_(self, ctx: discord.ext.commands.Context):
        vc = ctx.voice_client

        if not vc or not vc.is_connected():
            return await ctx.send("I'm literally not even connected")
        elif not vc.is_paused():
            await ctx.send("I'm not fucking paused")
            return

        vc.resume()
        await ctx.send("Resumed!")

    @commands.command(name='disconnect', aliases=['d', 'disc', 'leave'], description="Leaves current channel, destroying the queue!")
    async def disconnect_(self, ctx: discord.ext.commands.Context):
        vc = ctx.voice_client

        if not vc:
            return await ctx.send("Bruh._., I'm not even fucking connected. Like come the fuck on this isn't funny. Stop it, get some help")

        await vc.disconnect()
        await self.cleanup(ctx.guild)

    @commands.command(name='skip', aliases=['s', 'next'], description="Skips current song!")
    async def skip_(self, ctx: discord.ext.commands.Context):

        vc = ctx.voice_client

        if not vc:
            return await ctx.send("Bruh, I'm not even fucking connected like c'mon")

        np = self.get_player(ctx).np.embeds[0].description
        await ctx.send("Skipping " + str(np))
        self.get_player(ctx).skipping = True
        vc.stop()

    @commands.command(name='kill', aliases=['k', 'gettem'], description="Kills the program!")
    async def kill_(self, ctx: discord.ext.commands.Context):
        if "ElComadore" in ctx.author.name:
            await ctx.send("Arghh, ya got me...")
            await client.logout()
            exit(1)
        else:
            await ctx.send("Implying you have permission to kill me xdd")

    @commands.command(name='commands', aliases=['comlist', 'cl', 'comms', 'cm'], description="The current commands!")
    async def commands_(self, ctx: discord.ext.commands.Context):
        comlist = discord.Embed(title="Commands")
        for coms in self.get_commands():
            comlist.add_field(name=coms.name, value=coms.description, inline=False)
        await ctx.send(embed=comlist)

    @commands.command(name='nowplaying', aliases=['np'], description="The currently playing song")
    async def now_playing_(self, ctx: discord.ext.commands.Context):
        np = self.get_player(ctx).np

        if np:
            await ctx.send(embed=np)
        else:
            await ctx.send("Nothing is playing you monkey")


setup(client)
client.run(TOKEN)
