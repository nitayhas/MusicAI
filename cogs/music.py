import time
import difflib
from typing import Optional
import discord
from discord.ext import commands
import asyncio
from services.music_queue import QueueManager, QueueItem, Track
from services.youtube_v2 import YouTubeService
from utils.query_sanitizer import sanitize_play_query
from utils.ytdl_source_v2 import YTDLSource, auto_reconnect
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
                        await self.leave(ctx)
                        # queue.is_playing = False
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
            start_time = time.time()
            
            # Initialize playlist loading if this is the first batch
            if not queue.playlist_loader:
                await ctx.send("🎵 Extracting playlist information...")
                try:
                    video_entries, total_tracks = await self.youtube_service.get_playlist_info(playlist_url)
                    if not video_entries:
                        await ctx.send("❌ Could not find playlist entries. Make sure the playlist is public.")
                        return
                    
                    queue.start_playlist_loading(playlist_url)
                    queue.playlist_loader.video_entries = video_entries
                    queue.playlist_loader.total_tracks = total_tracks
                    await ctx.send(f"Found {total_tracks} tracks in playlist. Starting processing...")
                    
                except Exception as e:
                    await ctx.send(f"❌ Error getting playlist info: {str(e)}")
                    logger.error(f"Error getting playlist info: {str(e)}")
                    return
            
            # Create a semaphore to limit concurrent downloads
            semaphore = asyncio.Semaphore(3)
            
            # Calculate the batch range
            start_idx = queue.playlist_loader.current_index
            end_idx = min(start_idx + 10, len(queue.playlist_loader.video_entries))
            current_batch = queue.playlist_loader.video_entries[start_idx:end_idx]
            
            # Skip if we've reached the end of the playlist
            if not current_batch:
                queue.finish_playlist_loading()
                return
                
            added_tracks = 0
            skipped_tracks = 0
            
            # Process the batch
            tasks = [
                self.youtube_service.extract_video_info(entry['url'], semaphore)
                for entry in current_batch
            ]
            batch_results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Process each result in the batch
            for i, result in enumerate(batch_results):
                if isinstance(result, Exception):
                    skipped_tracks += 1
                    logger.error(f"Error processing track: {str(result)}")
                    continue
                    
                if result:
                    track = Track(**result)
                    
                    # Add callback to the 9th track (if not the last batch)
                    if (added_tracks == 8 and 
                        not queue.is_playlist_complete()):
                        queue.add_track(
                            track,
                            on_start=lambda: asyncio.create_task(
                                self.load_next_batch(ctx, playlist_url)
                            )
                        )
                    else:
                        queue.add_track(track)
                    
                    # Start playback if this is the first track overall
                    if (start_idx == 0 and i == 0 and not queue.is_playing):
                        queue.is_playing = True
                        await self.play_next(ctx)
                        await ctx.send(f"🎵 Starting playback: {result['title']}")
                    
                    added_tracks += 1
                else:
                    skipped_tracks += 1
            
            # Update the current index
            queue.playlist_loader.current_index = end_idx
            
            # Send progress update
            current, total = queue.get_playlist_progress()
            processing_time = time.time() - start_time
            
            # If this is the last batch, send final summary
            if queue.is_playlist_complete():
                await ctx.send(
                    f"✅ Finished processing playlist!\n"
                    f"Progress: {current}/{total} tracks\n"
                    f"Added in this batch: {added_tracks}\n"
                    f"Skipped in this batch: {skipped_tracks}\n"
                    f"Time taken: {processing_time:.2f} seconds"
                )
                queue.finish_playlist_loading()
            else:
                await ctx.send(
                    f"✅ Loaded batch of tracks ({start_idx + 1} to {end_idx})\n"
                    f"Progress: {current}/{total} tracks\n"
                    f"Added: {added_tracks} tracks\n"
                    f"Skipped: {skipped_tracks} tracks\n"
                    f"Time taken: {processing_time:.2f} seconds"
                )
                
        except Exception as e:
            await ctx.send(f"❌ Error processing playlist: {str(e)}")
            logger.error(f"Error processing playlist: {str(e)}")
            queue.finish_playlist_loading()

    async def load_next_batch(self, ctx, playlist_url: str):
        """Helper method to load the next batch of tracks"""
        queue = self.queue_manager.get_queue(ctx.guild.id)
        
        # Check if we need and can load more tracks
        if (not queue.is_playlist_complete() and 
            not queue.playlist_loader.is_loading):
            try:
                queue.playlist_loader.is_loading = True
                await self.process_playlist(ctx, playlist_url)
            finally:
                queue.playlist_loader.is_loading = False


    async def _ensure_voice_connection(self, ctx):
        """Ensure bot is connected to the correct voice channel"""
        if not ctx.message.author.voice:
            await ctx.send("❌ You must be in a voice channel to play music!")
            return False

        try:
            if ctx.voice_client is None:
                await ctx.message.author.voice.channel.connect()
                logger.info("Connected to voice channel")
            elif ctx.voice_client.channel != ctx.message.author.voice.channel:
                await ctx.voice_client.move_to(ctx.message.author.voice.channel)
                logger.info("Moved to voice channel")
            return True
        except Exception as e:
            logger.error(f"Voice connection error: {str(e)}")
            await ctx.send("❌ Could not connect to voice channel!")
            return False

    async def _handle_search_selection(self, ctx, query):
        """Handle selection from search results"""
        if not query.isdigit():
            return query
            
        index = int(query) - 1
        if ctx.guild.id in self.search_results and 0 <= index < len(self.search_results[ctx.guild.id]):
            selected_video = self.search_results[ctx.guild.id][index]
            return selected_video['url']
        
        await ctx.send("❌ Invalid search result number or no recent search results!")
        return None

    async def _process_track(self, ctx, query, position=None):
        """Process a single track and add it to the queue
        
        Args:
            ctx: Context
            query: Search query or URL
            position: Optional position to insert track (None for end of queue)
        
        Returns:
            tuple: (track_info, should_start_playing)
        """
        async with self._lock:
            try:
                queue = self.queue_manager.get_queue(ctx.guild.id)
                logger.info(f"Current queue length: {len(queue.queue)}")

                track_info = await self.youtube_service.process_url(query)
                track = Track(**track_info)

                if position is not None:
                    queue.queue.insert(position, QueueItem(track))
                else:
                    queue.add_track(track)

                # Determine if we should start playing
                should_start_playing = not queue.is_playing
                if should_start_playing:
                    queue.is_playing = True
                    logger.info("Will start playback")

                return track_info, should_start_playing

            except Exception as e:
                logger.error(f"Error processing track: {str(e)}")
                await ctx.send(f"❌ Error: {str(e)}")
                return None, False

    @commands.command(name='play', aliases=['p'])
    async def play(self, ctx, *, query: str):
        """Play a song by URL, search result number, or playlist URL"""
        logger.info(f"Play command received with query: {query}")

        # Sanitize query
        is_safe, sanitized_query, error_message = await sanitize_play_query(query, str(ctx.author.id))
        if not is_safe:
            await ctx.send(f"Sanitizing results: {error_message}")
            return

        # Check voice connection
        if not await self._ensure_voice_connection(ctx):
            return

        try:
            # Handle search result selection
            query = await self._handle_search_selection(ctx, query)
            if query is None:
                return

            # Handle playlist
            if "playlist" in query or "list=" in query:
                logger.info("Playlist URL detected, processing playlist...")
                await self.process_playlist(ctx, query)
                return

            # Process single track
            track_info, should_start_playing = await self._process_track(ctx, query)
            
            if track_info:
                await ctx.send(f"Added to queue: {track_info['title']}")
                if should_start_playing:
                    logger.info("Starting playback process")
                    await self.play_next(ctx)
                else:
                    logger.info("Track added to queue (already playing)")

        except Exception as e:
            logger.error(f"Error in play command: {str(e)}")
            await ctx.send(f'❌ Error: {str(e)}')

    @commands.command(name='playnow', aliases=['pn'])
    async def playnow(self, ctx, *, query: str):
        """Play a song immediately by placing it at the start of the queue"""
        logger.info(f"Play Now command received with query: {query}")

        # Sanitize query
        is_safe, sanitized_query, error_message = await sanitize_play_query(query, str(ctx.author.id))
        if not is_safe:
            await ctx.send(f"Sanitizing results: {error_message}")
            return

        # Check voice connection
        if not await self._ensure_voice_connection(ctx):
            return

        try:
            # Handle search result selection
            query = await self._handle_search_selection(ctx, query)
            if query is None:
                return

            # Don't allow playlists
            if "playlist" in query or "list=" in query:
                await ctx.send("❌ Play Now command doesn't support playlists. Use regular play command instead!")
                return

            # Process track and insert at position 0
            track_info, _ = await self._process_track(ctx, query, position=0)
            
            if track_info:
                await ctx.send(f"Playing now: {track_info['title']}")
                
                # Stop current track if playing
                if ctx.voice_client and ctx.voice_client.is_playing():
                    ctx.voice_client.stop()
                else:
                    await self.play_next(ctx)

        except Exception as e:
            logger.error(f"Error in playnow command: {str(e)}")
            await ctx.send(f'❌ Error: {str(e)}')

    @commands.command(name='radio', aliases=['r'])
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

    @commands.command(name='search', aliases=['s'])
    async def search(self, ctx, *, query: str):
        """Search for videos on YouTube and display results"""
        is_safe, sanitized_query, error_message = await sanitize_play_query(query, str(ctx.author.id))
        if not is_safe:
            await ctx.send(f"Sanitizing results: {error_message}")
            return
        
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


    @commands.command(name='queue', aliases=['q'])
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
        for i, q_item in enumerate(queue_list[:10], 1):
            duration_min = int(q_item.track.duration // 60)
            duration_sec = int(q_item.track.duration % 60)
            embed.add_field(
                name=f"{i}. {q_item.track.title}",
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

    @commands.command(name='skip', aliases=['skipkip'])
    async def next(self, ctx, amount: str = "1"):
        try:
            skip_amount = int(amount)
        except ValueError:
            await ctx.send("❌ Please provide a valid number!")
            return

        if skip_amount < 1:
            await ctx.send("❌ Please provide a positive number!")
            return

        # Get the guild's queue
        queue = self.queue_manager.get_queue(ctx.guild.id)
        
        if not queue.is_playing:
            await ctx.send("❌ Nothing is playing!")
            return

        # Skip tracks and get the result
        tracks_skipped = queue.skip_tracks(skip_amount)
        
        # Stop the current audio
        if ctx.voice_client and ctx.voice_client.is_playing():
            ctx.voice_client.stop()
        
        if tracks_skipped == 1:
            await ctx.send("⏭️ Skipped to next song.")
        else:
            await ctx.send(f"⏭️ Skipped {tracks_skipped} songs.")

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
                 
    @commands.command(name='helpm')
    async def helpm(self, ctx):
        """Display all available music commands and their usage"""
        embed = discord.Embed(
            title="🎵 MusicAI Commands",
            description="Here are all available music commands:",
            color=discord.Color.blue()
        )

        # Main playback commands
        embed.add_field(
            name="▶️ Playback Commands",
            value="""
    `!play` (or `!p`) `<song/URL>`: Play a song or add it to queue
    `!playnow` (or `!pn`) `<song/URL>`: Play a song immediately
    `!skip`: Skip to the next song
    `!stop`: Stop playback and clear queue
    """,
            inline=False
        )

        # Queue management
        embed.add_field(
            name="📋 Queue Management",
            value="""
    `!queue`: Display current queue
    `!radio` (or `!r`) `[number]`: Add radio songs to current track (default: 5)
    """,
            inline=False
        )

        # Search commands
        embed.add_field(
            name="🔎 Search Commands",
            value="""
    `!search` `<query>`: Search for songs
    `!play <number>`: Play a song from search results
    """,
            inline=False
        )

        # Voice channel commands
        embed.add_field(
            name="🎤 Voice Channel Commands",
            value="""
    `!join`: Join your voice channel
    `!leave`: Leave voice channel
    """,
            inline=False
        )

        # Tips section
        embed.add_field(
            name="💡 Tips",
            value="""
    • You can play songs by name, URL, or playlist URL
    • Use `!playnow` to skip the queue
    • Search results are numbered - use the number with !play
    """,
            inline=False
        )

        embed.set_footer(text="Need more help? Ask a moderator!")
        
        await ctx.send(embed=embed)
        
    @commands.Cog.listener('on_voice_state_update')
    async def on_voice_state_update(self, member, before, after):
        """Event handler for voice state updates"""
        # Ignore bot's own voice state updates
        if member == self.bot.user:
            return
        
        # Check if the member left a channel
        if before.channel and not after.channel:
            # Get the voice channel the bot is in
            for voice_client in self.bot.voice_clients:
                # Get current channel members directly from voice_client.channel
                if voice_client.channel == before.channel:
                    current_channel = voice_client.channel
                    # Count remaining members (excluding bots)
                    remaining_members = len([
                        m for m in current_channel.members 
                        if not m.bot
                    ])
                    
                    # If no human members remain, disconnect the bot
                    if remaining_members == 0:
                        await voice_client.disconnect()
                        # Try to find a text channel to send notification
                        if isinstance(current_channel.guild.system_channel, discord.TextChannel):
                            await current_channel.guild.system_channel.send(
                                f"All users left the voice channel. I'm leaving too!"
                            )
        
    @commands.Cog.listener('on_command_error')
    async def error_handler(self, ctx, error):
        if isinstance(error, commands.CommandNotFound):
            # Get the command that was attempted
            attempted_command = ctx.message.content.split()[0][len(ctx.prefix):].lower()
            
            # Get list of all available commands
            available_commands = [cmd.name for cmd in self.bot.commands]
            
            # Find similar commands using difflib
            similar_commands = difflib.get_close_matches(
                attempted_command, 
                available_commands, 
                n=3,  # Number of suggestions
                cutoff=0.6  # Similarity threshold (0-1)
            )
            
            # Create an embedded message
            embed = discord.Embed(
                title="Command Not Found",
                color=discord.Color.orange()
            )
            embed.add_field(
                name="Error",
                value=f"The command `{attempted_command}` was not found.",
                inline=False
            )
            
            # Add suggestions if any were found
            if similar_commands:
                suggestions = "\n".join([f"`{cmd}`" for cmd in similar_commands])
                embed.add_field(
                    name="Did you mean:",
                    value=suggestions,
                    inline=False
                )
            
            # Add help information
            embed.add_field(
                name="Need help?",
                value=f"Type `{ctx.prefix}helpm` to see all available commands.",
                inline=False
            )
            
            # Log the error
            logger.warning(
                f"CommandNotFound: User {ctx.author} ({ctx.author.id}) "
                f"attempted to use unknown command '{attempted_command}' "
                f"in channel #{ctx.channel.name} ({ctx.channel.id})"
            )
            
            await ctx.send(embed=embed)
            
        elif isinstance(error, commands.MissingPermissions):
            embed = discord.Embed(
                title="Permission Error",
                description="You don't have the required permissions to use this command.",
                color=discord.Color.red()
            )
            await ctx.send(embed=embed)
            
        elif isinstance(error, commands.MissingRequiredArgument):
            embed = discord.Embed(
                title="Missing Argument",
                description=f"Missing required argument: {error.param.name}",
                color=discord.Color.red()
            )
            embed.add_field(
                name="Usage",
                value=f"`{ctx.prefix}{ctx.command.name} {ctx.command.signature}`",
                inline=False
            )
            await ctx.send(embed=embed)
            
        else:
            # Log unexpected errors
            logger.error(
                f"Unexpected error in command '{ctx.command}' "
                f"used by {ctx.author} ({ctx.author.id}): {str(error)}",
                exc_info=error
            )
            
            embed = discord.Embed(
                title="An Error Occurred",
                description="An unexpected error occurred. The bot administrator has been notified.",
                color=discord.Color.red()
            )
            await ctx.send(embed=embed)
                
async def setup(bot):
    await bot.add_cog(Music(bot))