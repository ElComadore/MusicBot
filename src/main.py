import os
import discord
from discord.ext import commands
from dotenv import load_dotenv
import asyncio
from async_timeout import timeout
from functools import partial
from youtube_dlc import *
import youtube_dlc
from youtubesearchpython import VideosSearch, ResultMode, Playlist
import time

load_dotenv()

ytdlopts = {
    'format': '256/140/139',
    'default_search': 'auto',
    'novideo': True,
    'source_address': '0.0.0.0',
    'quiet': True,
    'noplaylist': True
}

# ffmpegopts = {
#  'before_options': '-nostdin',
#  'options': '-vn -sn -dn -ignore_unknown'
# }

intent = discord.Intents.all()

TOKEN = os.getenv('DISCORD_TOKEN')
client = commands.Bot(command_prefix='!', intents=intent)
ytdl = YoutubeDL(ytdlopts)
youtube_dlc.utils.bug_reports_message = lambda: ''


async def setup(bot):
    await bot.add_cog(Music(bot))


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

        to_run = partial(ytdl.extract_info, url=search, download=download)
        data = await loop.run_in_executor(None, to_run)

        if 'entries' in data:
            data = data['entries'][0]

        option = '-vn -sn -dn -ss ' + str(start_time)

        if download:
            source = ytdl.prepare_filename(data)
        else:
            return {'webpage_url': data['webpage_url'],
                    'requester': ctx.author,
                    'title': data['title'],
                    'start_time': 0}

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

    __slots__ = ('bot', '_guild', '_channel', '_cog', 'queue', 'next', 'current', 'np', 'volume', 'broken',
                 'say_playing', 'skipping', 'song_list', 'repeat', 'song_to_repeat')

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
        self.song_list = list()
        self.repeat = False
        self.song_to_repeat = None

        ctx.bot.loop.create_task(self.player_loop())

    async def player_loop(self):
        """The unending loop of trying to get music from the Queues"""
        await self.bot.wait_until_ready()
        await self.bot.change_presence(activity=discord.Game(name="playlists! Only bangers ofc ofc"))
        duration_played = 0     # This is the janky fix

        while not self.bot.is_closed():
            self.next.clear()
            source_sound = None

            try:
                async with timeout(0.1):
                    source = await self.broken.get()    # Get the dropped audio stream
                    print("Saved!")
            except asyncio.TimeoutError:
                if self.repeat:                         # Repeat the current song!
                    source = self.song_to_repeat
                    self.say_playing = False
                else:
                    try:
                        async with timeout(180):
                            source = await self.queue.get()     # Get the next song, given no dropped sources
                            self.song_to_repeat = source
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

            t = time.time()     # Time for later reference

            self._guild.voice_client.play(source_sound,
                                          after=lambda _: self.bot.loop.call_soon_threadsafe(self.next.set()))

            if self.say_playing:    # Says what is currently playing, if connection was not drop
                embed = discord.Embed(title="Now playing", description=source_sound.title)
                self.np = await self._channel.send(embed=embed)
            await self.next.wait()

            """Catching if we dropped from the socket below"""
            duration_played = duration_played + (time.time() - t)
            if duration_played < int(source_sound.data['duration']) - 5 and not self.skipping:
                source['start_time'] = int(duration_played)
                await self.broken.put(source)
                self.say_playing = False
                self._guild.voice_client.stop()
                source_sound.cleanup()
                print(duration_played)

            elif self.repeat:
                duration_played = 0

            else:
                duration_played = 0
                self.say_playing = True
                self.np = None
                self.current = None
                self.skipping = False
                self.song_list.pop(0)

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

    @commands.command(name='ping', description="returns a ping")
    async def ping_(self, ctx: discord.ext.commands.Context):
        await ctx.send("Ping")

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
                await ctx.send(channel.name + " joined!")
            except Exception as e:
                await ctx.send('Cannae connect in time capn')
                print(e)

    @commands.command(name='play', aliases=['p'], description="Searches for query and plays first result!")
    async def play_(self, ctx: discord.ext.commands.Context, *, search: str):
        await ctx.typing()

        vc = ctx.voice_client

        if not vc:
            try:
                await ctx.invoke(self.connect_)
            except AttributeError:
                return

        player = self.get_player(ctx)
        video_list = await self.search_(ctx, search)

        if isinstance(video_list, list):
            if len(video_list) < 30:
                embed = discord.Embed(title="Queueing " + str(len(video_list)) + " songs!")
                thumb = video_list[0]['thumbnails'][0]['url']

            else:
                embed = discord.Embed(title="Queueing " + str(len(video_list)) + " songs!",
                                      description="""Now, you have just queued a rather large number of songs and I am 
                                                  going to write a blog explaining that this was a horrible idea and 
                                                  may cause unknown side-effects. Please realise this is not an 
                                                  instant process, and that just because you are hearing music does 
                                                  not mean that all the songs have been added to the queue. Also 
                                                  there is currently no way to skip all songs in a playlist so you're 
                                                  gonna have to dc the bot:)""")
                thumb = video_list[0]['thumbnails'][0]['url']

            embed.set_thumbnail(url=thumb)
            await ctx.send(embed=embed)

            for videos in video_list:
                source = await YTDLSource.create_source(ctx, videos['link'], loop=self.bot.loop, download=False)
                player.song_list.append(source)
                await player.queue.put(source)

        elif video_list is not None:    # Requester made a choice of a video
            source = None

            embed = discord.Embed(title="Queued", description=video_list['title'])
            thumb = video_list['thumbnails'][0]['url']
            embed.set_thumbnail(url=thumb)

            try:
                source = await YTDLSource.create_source(ctx, video_list['link'], loop=self.bot.loop, download=False)
            except Exception as e:
                await ctx.send("There was an issue trying to queue this song; it may be age restricted!")

            if source is not None:
                player.song_list.append(source)
                await player.queue.put(source)

                await ctx.send(embed=embed)
        else:
            return

    @staticmethod
    async def search_(ctx, search):
        """The actual search for videos/playlists function"""

        playlist_id = '?list=PL'        # all playlists have this I'm pretty sure
        channel_id = 'ab_channel'

        print("searching")

        if playlist_id in search:
            playlist = Playlist(search)
            try:
                while playlist.hasMoreVideos:
                    playlist.getNextVideos()
            except TypeError as t:
                await ctx.send("Something went wrong with getting the playlist\n" + str(t))
                return None
            return playlist.videos
        else:
            results = VideosSearch(search, limit=5).result(mode=ResultMode.dict)      # Getting candidate videos
            if len(results['result']) == 0:
                await ctx.send("Got no search results there for you chief")
                if channel_id in search:
                    await ctx.send('Try searching without the channel portion of the url')
                return None
            elif results['result'][0]['link'] in search:          # Checking if we searched a link
                return results['result'][0]

            else:
                """Creating the embed for choices"""
                search_embed = discord.Embed(title="Top 5 Results for " + search,
                                             description="Just message the number of the result you want")
                thumb = results['result'][0]['thumbnails'][0]['url']
                search_embed.set_thumbnail(url=thumb)

            for i in range(0, len(results['result'])):
                search_embed.add_field(name=str(i+1) + ') ' + results['result'][i]['title'] + ' ' + results['result'][i]['duration'],
                                       value=results['result'][i]['link'], inline=False)
            await ctx.send(embed=search_embed)

            """Getting selection from user"""
            try:
                choice = await client.wait_for('message', timeout=30)
                try:
                    choice_number = int(choice.content)
                    return results['result'][choice_number - 1]
                except ValueError:
                    await ctx.send("Choice terminated - that's not a number dumbass")
                    return None
                except IndexError:
                    await ctx.send("Choice terminated - that's not a valid choice dumbass")
                    return None
            except asyncio.TimeoutError:
                await ctx.send("Choice timed out")
                return None

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

    @commands.command(name='disconnect', aliases=['d', 'disc', 'leave'],
                      description="Leaves current channel, destroying the queue!")
    async def disconnect_(self, ctx: discord.ext.commands.Context):
        vc = ctx.voice_client

        if not vc:
            return await ctx.send("Bruh._., I'm not even fucking connected. "
                                  "Like come the fuck on this isn't funny. Stop it, get some help")

        await vc.disconnect(force=True)
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
            await client.close()
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

    @commands.command(name='songlist', aliases=['sl', 'queue', 'q'])
    async def song_list_(self, ctx: discord.ext.commands.Context):
        queue_embed = discord.Embed(title='Song Queue', description='Songs coming up')
        player = self.get_player(ctx)

        if len(player.song_list) == 0:
            await ctx.send("There's nothing in the song list you nonce")
            return

        num_songs = 10
        if num_songs > len(player.song_list):
            num_songs = len(player.song_list)

        for i in range(0, num_songs):
            queue_embed.add_field(name=str(i+1) + ') ' + player.song_list[i]['title'],
                                  value=player.song_list[i]['webpage_url'], inline=False)

        if len(player.song_list) > 10:
            queue_embed.add_field(name="There are " + str(len(player.song_list) - 10) + " more songs!",
                                  value="Omg so many songs!", inline=False)

        await ctx.send(embed=queue_embed)

    @commands.command(name='repeat', aliases=['r', 'playitagainsam'],
                      description='Repeats the current song using magic!')
    async def repeat_(self, ctx: discord.ext.commands.Context):
        player = self.get_player(ctx)
        player.repeat = ~player.repeat
        if player.repeat:
            await ctx.send('Now repeating current song!')
        else:
            await ctx.send('No longer repeating')


asyncio.run(setup(client))
asyncio.run(client.start(TOKEN))
exit(1)
