import time
from typing import Optional
import discord
from discord.ext import commands
import asyncio
from services.music_queue import QueueManager, Track
from services.youtube import YouTubeService
from utils.ytdl_source import YTDLSource, auto_reconnect
from utils.music_recommender import MusicRecommender
from config.settings import CHUNK_SIZE, LASTFM_API_KEY, LASTFM_API_SECRET, LASTFM_USERNAME, LASTFM_PASSWORD
import logging

logger = logging.getLogger('music_bot')

class Music(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.queue_manager = QueueManager()
        self.youtube_service = YouTubeService(bot=bot)
        # Initialize the recommender
        self.recommender = MusicRecommender(
            api_key=LASTFM_API_KEY,
            api_secret=LASTFM_API_SECRET,
            username=LASTFM_USERNAME,
            password_hash=LASTFM_PASSWORD
        )
        self.search_results = {}
        self._lock = asyncio.Lock()  # Add lock for thread safety
        self._playback_locks = {}  # Dict to store per-guild playback locks
        self._current_players = {}  # Dict to store currently playing sources
        self._cleanup_events = {}

    def _get_playback_lock(self, guild_id: int) -> asyncio.Lock:
        """Get or create a playback lock for a specific guild."""
        if guild_id not in self._playback_locks:
            self._playback_locks[guild_id] = asyncio.Lock()
        return self._playback_locks[guild_id]
    
    def schedule_callback(self, coro):
        """Schedule a coroutine to run in the bot's event loop."""
        asyncio.run_coroutine_threadsafe(coro, self.bot.loop)

    async def ensure_voice_client(self, ctx):
        """Ensure voice client is properly connected."""
        if not ctx.voice_client or not ctx.voice_client.is_connected():
            if ctx.author.voice:
                await ctx.author.voice.channel.connect()
            else:
                raise ValueError("Not connected to a voice channel")

    async def create_player(self, ctx, track) -> Optional[discord.PCMVolumeTransformer]:
        """Create a player in a thread-safe manner."""
        guild_id = ctx.guild.id
        playback_lock = self._get_playback_lock(guild_id)
        
        async with playback_lock:
            try:
                # Clean up existing player if any
                if guild_id in self._current_players:
                    try:
                        self._current_players[guild_id].cleanup()
                    except Exception as e:
                        logger.error(f"Error cleaning up old player: {e}")

                # Create new player
                logger.info(f"Creating new player for track: {track.title}")
                player = await YTDLSource.from_track(track, loop=self.bot.loop)
                self._current_players[guild_id] = player
                return player

            except Exception as e:
                logger.error(f"Error creating player: {e}")
                if guild_id in self._current_players:
                    del self._current_players[guild_id]
                return None

    async def cleanup_player(self, guild_id: int):
        """Clean up player resources."""
        playback_lock = self._get_playback_lock(guild_id)
        async with playback_lock:
            if guild_id in self._current_players:
                try:
                    self._current_players[guild_id].cleanup()
                except Exception as e:
                    logger.error(f"Error during player cleanup: {e}")
                finally:
                    del self._current_players[guild_id]

    async def _handle_playback_complete(self, ctx, error):
        """Handle completion of track playback."""
        logger.info("Playback complete handler triggered")
        should_play_next = False

        async with self._lock:
            try:
                if error:
                    logger.error(f"Playback completed with error: {str(error)}")
                    await ctx.send(f"❌ An error occurred while playing: {str(error)}")
                else:
                    logger.info("Playback completed successfully")

                queue = self.queue_manager.get_queue(ctx.guild.id)
                
                if queue.queue:
                    logger.info("More tracks in queue")
                    should_play_next = True
                else:
                    logger.info("Queue is empty")
                    queue.is_playing = False
                    queue.current_track = None

            except Exception as e:
                logger.error(f"Error in playback complete handler: {str(e)}")
                should_play_next = False

        if should_play_next:
            await self.play_next(ctx)
                
    async def play_next(self, ctx):
        """Play the next track in queue."""
        logger.info("Entering play_next method")
        next_track = None
        guild_id = ctx.guild.id
        
        async with self._lock:
            try:
                queue = self.queue_manager.get_queue(guild_id)
                
                # Check voice client
                if not ctx.voice_client or not ctx.voice_client.is_connected():
                    logger.error("Voice client is not properly connected")
                    # Try to reconnect
                    if not await auto_reconnect(ctx.voice_client, ctx.author.voice.channel):
                        queue.is_playing = False
                        return

                if not queue.queue:
                    logger.info("Queue is empty")
                    queue.is_playing = False
                    queue.current_track = None
                    return

                next_track = queue.get_next_track()
                queue.current_track = next_track
                logger.info(f"Preparing to play: {next_track.title}")

            except Exception as e:
                logger.error(f'Error preparing playback: {str(e)}')
                return

        # Create player and start playback outside the lock
        if next_track:
            try:
                # Create player
                player = await YTDLSource.from_track(next_track, loop=self.bot.loop)
                if not player:
                    raise Exception("Failed to create player")

                def after_playing(error):
                    if error:
                        logger.error(f"Playback error: {str(error)}")
                    # Schedule cleanup and next track
                    asyncio.run_coroutine_threadsafe(
                        self._handle_playback_complete(ctx, error),
                        self.bot.loop
                    )

                # Set appropriate volume
                player.volume = 1.0  # Ensure volume is at max

                # Start playback
                ctx.voice_client.play(player, after=after_playing)
                await ctx.send(f'🎵 Now playing: {player.title}')
                logger.info(f"Successfully started playing: {player.title}")
                
            except Exception as e:
                logger.error(f'Error during playback: {str(e)}')
                await ctx.send(f'❌ Error playing track: {str(e)}')
                await asyncio.sleep(1)
                await self.play_next(ctx)

    async def _handle_playback_error(self, ctx, guild_id: int):
        """Handle playback error with proper cleanup."""
        await self.cleanup_player(guild_id)
        await asyncio.sleep(1)
        await self.play_next(ctx)

    async def process_playlist(self, ctx, playlist_url: str):
        try:
            
            queue = self.queue_manager.get_queue(ctx.guild.id)
            queue.playlist_processing = True
            start_time = time.time()
            
            await ctx.send("🎵 Extracting playlist information...")
            
            # Get playlist information
            try:
                video_entries, total_tracks = await self.youtube_service.get_playlist_info(playlist_url)
                if not video_entries:
                    await ctx.send("❌ Could not find playlist entries. Make sure the playlist is public.")
                    return

                await ctx.send(f"Found {total_tracks} tracks in playlist. Starting processing...")

                # Create a semaphore to limit concurrent downloads
                semaphore = asyncio.Semaphore(3)
                
                # Process first video immediately
                first_track = await self.youtube_service.extract_video_info(video_entries[0]['url'], semaphore)
                if first_track:
                    queue.add_track(Track(**first_track))
                    if not queue.is_playing:
                        queue.is_playing = True
                        await self.play_next(ctx)
                        await ctx.send(f"🎵 Starting playback: {first_track['title']}")
                
                # Process remaining videos in chunks
                remaining_entries = video_entries[1:]
                chunks = [remaining_entries[i:i + CHUNK_SIZE] 
                         for i in range(0, len(remaining_entries), CHUNK_SIZE)]

                added_tracks = 1 if first_track else 0
                skipped_tracks = 0

                # Process each chunk
                for chunk_index, chunk in enumerate(chunks):
                    tasks = [
                        self.youtube_service.extract_video_info(entry['url'], semaphore)
                        for entry in chunk
                    ]
                    chunk_results = await asyncio.gather(*tasks, return_exceptions=True)
                    
                    for result in chunk_results:
                        if isinstance(result, Exception):
                            skipped_tracks += 1
                            continue
                            
                        if result:
                            queue.add_track(Track(**result))
                            added_tracks += 1
                        else:
                            skipped_tracks += 1

                    # Progress update
                    if (chunk_index + 1) % 2 == 0 or chunk_index == len(chunks) - 1:
                        await ctx.send(f"✅ Progress: {added_tracks}/{total_tracks} tracks added")

                processing_time = time.time() - start_time
                await ctx.send(
                    f"✅ Finished processing playlist!\n"
                    f"Added: {added_tracks} tracks\n"
                    f"Skipped: {skipped_tracks} tracks\n"
                    f"Time taken: {processing_time:.2f} seconds"
                )

            except Exception as e:
                await ctx.send(f"❌ Error processing playlist: {str(e)}")
                logger.error(f"Error processing playlist: {str(e)}")

        finally:
            queue.playlist_processing = False


    @commands.command(name='play')
    async def play(self, ctx, *, query: str):
        """Play a song by URL, search result number, or playlist URL"""
        logger.info(f"Play command received with query: {query}")

        # Check voice channel first
        if not ctx.message.author.voice:
            await ctx.send("❌ You must be in a voice channel to play music!")
            return

        # Handle voice connection first
        try:
            if ctx.voice_client is None:
                await ctx.message.author.voice.channel.connect()
                logger.info("Connected to voice channel")
            elif ctx.voice_client.channel != ctx.message.author.voice.channel:
                await ctx.voice_client.move_to(ctx.message.author.voice.channel)
                logger.info("Moved to voice channel")
        except Exception as e:
            logger.error(f"Voice connection error: {str(e)}")
            await ctx.send("❌ Could not connect to voice channel!")
            return

        try:
            # Handle search result selection
            if query.isdigit():
                index = int(query) - 1
                if ctx.guild.id in self.search_results and 0 <= index < len(self.search_results[ctx.guild.id]):
                    selected_video = self.search_results[ctx.guild.id][index]
                    query = selected_video['url']  # Use the URL from search results
                else:
                    await ctx.send("❌ Invalid search result number or no recent search results!")
                    return

            # Check if this is a playlist URL
            if "playlist" in query or "list=" in query:
                logger.info("Playlist URL detected, processing playlist...")
                await self.process_playlist(ctx, query)
                return

            # Handle single track
            should_start_playing = False
            track_added = False

            # Handle queue operations with lock
            async with self._lock:
                try:
                    queue = self.queue_manager.get_queue(ctx.guild.id)
                    logger.info(f"Current queue length: {len(queue.queue)}")

                    # Process the track
                    track_info = await self.youtube_service.process_url(query)
                    queue.add_track(Track(**track_info))
                    track_added = True
                    await ctx.send(f"Added to queue: {track_info['title']}")
                    logger.info(f"Added track to queue: {track_info['title']}")

                    # Check if we should start playing
                    should_start_playing = not queue.is_playing
                    if should_start_playing:
                        queue.is_playing = True
                        logger.info("Will start playback")

                except Exception as e:
                    logger.error(f"Error processing track: {str(e)}")
                    await ctx.send(f"❌ Error: {str(e)}")
                    return

            # Start playback outside the lock if needed
            if track_added and should_start_playing:
                logger.info("Starting playback process")
                await self.play_next(ctx)
            elif track_added:
                logger.info("Track added to queue (already playing)")

        except Exception as e:
            logger.error(f"Error in play command: {str(e)}")
            await ctx.send(f'❌ Error: {str(e)}')

    @commands.command(name='similar')
    async def find_similar(self, ctx, *, limit=5):
        # Get the currently playing track
        queue = self.queue_manager.get_queue(ctx.guild.id)
        current_track = queue.current_track.title
        logger.info(f"Find similar track to {current_track}")
        try:
            limit = int(limit)
        except:
            pass
        
        similar_tracks = self.recommender.get_similar_tracks(current_track, limit=limit)        
        # Create an embed with recommendations
        embed = discord.Embed(title="Similar Tracks")
        # Handle queue operations with lock
        async with self._lock:
            await ctx.send(f"Start adding {len(similar_tracks)} similar tracks")
            for track in similar_tracks:
                try:
                    embed.add_field(
                        name=f"{track['artist']} - {track['title']}", 
                        value=f"Similarity: {track['similarity_score']:.2f}", 
                        inline=False
                    )
                    track_info = await self.youtube_service.process_url(f"{track['artist']} - {track['title']}")
                    queue.add_track(Track(**track_info))
                    logger.info(f"Added track to queue: {track_info['title']}")
                except Exception as e:
                    logger.error(f"Error processing track: {str(e)}")
                    await ctx.send(f"❌ Error: {str(e)}")
                    return
                    
        await ctx.send(embed=embed)

    @commands.command(name='search')
    async def search(self, ctx, *, query):
        """Search for videos on YouTube and display results"""
        try:
            results = await self.youtube_service.parallel_search(query)
            
            if not results:
                await ctx.send("❌ No results found.")
                return

            # Store search results for this server
            server_id = ctx.guild.id
            self.search_results[server_id] = results

            embed = discord.Embed(title="🔎 Search Results", color=discord.Color.blue())
            
            for i, entry in enumerate(results, 1):
                duration = entry.get('duration', 0)
                embed.add_field(
                    name=f"{i}. {entry['title']}",
                    value=f"Duration: {int(duration // 60)}:{int(duration % 60):02d}",
                    inline=False
                )

            await ctx.send(embed=embed)
            await ctx.send("Use !play <number> to play a song from the search results")

        except Exception as e:
            await ctx.send(f'❌ Error: {str(e)}')


    @commands.command(name='queue')
    async def queue(self, ctx):
        """Display the current queue"""
        server_id = ctx.guild.id
        queue = self.queue_manager.get_queue(server_id)
        
        if not queue.queue and not queue.current_track:
            await ctx.send("📪 The queue is empty!")
            return

        embed = discord.Embed(title="🎵 Music Queue", color=discord.Color.blue())
        
        # Add current track
        if queue.current_track:
            embed.add_field(
                name="▶️ Currently Playing:",
                value=queue.current_track.title,
                inline=False
            )

        # Add queued tracks (up to 10)
        queue_list = list(queue.queue)
        for i, track in enumerate(queue_list[:10], 1):
            duration_min = int(track.duration // 60)
            duration_sec = int(track.duration % 60)
            embed.add_field(
                name=f"{i}. {track.title}",
                value=f"Duration: {duration_min}:{duration_sec:02d}",
                inline=False
            )

        # Add total number of tracks in queue
        total_tracks = len(queue_list)
        if total_tracks > 10:
            embed.add_field(
                name="And more...",
                value=f"{total_tracks - 10} additional tracks in queue",
                inline=False
            )

        # Add playlist processing status
        if queue.playlist_processing:
            embed.add_field(
                name="ℹ️ Notice",
                value="A playlist is currently being processed in the background.",
                inline=False
            )

        await ctx.send(embed=embed)

    @commands.command(name='stop')
    async def stop(self, ctx):
        """Stop playing and clear the queue."""
        guild_id = ctx.guild.id
        
        async with self._lock:
            queue = self.queue_manager.get_queue(guild_id)
            if queue:
                queue.clear()

        # Clean up player
        await self.cleanup_player(guild_id)

        if ctx.voice_client and ctx.voice_client.is_playing():
            ctx.voice_client.stop()
            await ctx.voice_client.disconnect()
            await ctx.send("⏹️ Playback stopped and queue cleared.")
        else:
            await ctx.send("❌ Nothing is playing!")

    @commands.command(name='next')
    async def next(self, ctx):
        """Skip to the next song in the queue"""
        if ctx.voice_client and ctx.voice_client.is_playing():
            ctx.voice_client.stop()  # This will trigger the after callback and play the next song
            await ctx.send("⏭️ Skipped to next song.")
        else:
            await ctx.send("❌ Nothing is playing!")

    @commands.command(name='join')
    async def join(self, ctx):
        """Join the user's voice channel"""
        if not ctx.message.author.voice:
            await ctx.send('❌ You must be in a voice channel to use this command.')
            return

        channel = ctx.message.author.voice.channel
        if ctx.voice_client is None:
            await channel.connect()
            await ctx.send(f'👋 Joined {channel.name}')
        else:
            await ctx.voice_client.move_to(channel)
            await ctx.send(f'👋 Moved to {channel.name}')

    @commands.command(name='leave')
    async def leave(self, ctx):
        """Leave the voice channel and clear the queue"""
        queue = self.queue_manager.get_queue(ctx.guild.id)
        if queue:
            queue.clear()

        if ctx.voice_client:
            await ctx.voice_client.disconnect()
            await ctx.send("👋 Left the voice channel.")
        else:
            await ctx.send("❌ I'm not in a voice channel!")
            
async def setup(bot):
    await bot.add_cog(Music(bot))