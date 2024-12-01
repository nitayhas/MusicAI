import os
import stat
import asyncio
import discord
from pytubefix import YouTube
import logging
import time
from typing import Optional, Dict
import subprocess
from urllib.parse import urlparse, parse_qs

logger = logging.getLogger('music_bot')

class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data, volume=0.5):
        super().__init__(source, volume)
        self.data = data
        self.title = data.get('title', 'Unknown Title')
        self.url = data.get('url', '')
        self.duration = data.get('duration', 0)
        self.thumbnail = data.get('thumbnail', '')
        self.stream_url = None
        self._ffmpeg_process = None
        self._volume = volume

    @classmethod
    async def from_url(cls, url, *, loop=None, stream=True):
        """Create a YTDLSource from a URL."""
        loop = loop or asyncio.get_event_loop()
        
        try:
            # Extract info using pytubefix
            logger.info(f"Extracting info for URL: {url}")
            yt = await loop.run_in_executor(
                None,
                lambda: YouTube(url, use_oauth=True, allow_oauth_cache=True)
            )

            if not yt:
                raise ValueError("Could not extract video information")

            # Format data similar to previous structure
            data = {
                'title': yt.title,
                'url': url,
                'duration': yt.length,
                'thumbnail': yt.thumbnail_url,
            }

            # Get best audio stream
            streams = yt.streams.filter(only_audio=True)
            
            # Try to find highest quality audio stream
            best_audio = None
            
            # First try to find Opus format if available
            for stream in streams:
                if 'opus' in stream.audio_codec.lower():
                    best_audio = stream
                    break
            
            # If no Opus, get highest quality audio stream
            if not best_audio:
                best_audio = streams.order_by('abr').desc().first()

            if not best_audio:
                raise ValueError("No suitable audio stream found")

            stream_url = best_audio.url
            logger.info(f"Using audio format: {best_audio.audio_codec} "
                      f"(bitrate: {best_audio.abr})")

            # Create FFmpeg audio source
            source = await cls._create_audio_source(stream_url, loop)
            if not source:
                raise ValueError("Could not create audio source")

            instance = cls(source, data=data)
            instance.stream_url = stream_url
            return instance

        except Exception as e:
            logger.error(f"Error creating source: {e}")
            raise

    @classmethod
    async def _create_audio_source(cls, url: str, loop) -> Optional[discord.FFmpegPCMAudio]:
        """Create an audio source with verification."""
        try:
            # Test the audio stream
            logger.info("Testing audio stream...")
            test_command = [
                'ffmpeg',
                '-v', 'error',
                '-i', url,
                '-t', '1',  # Test first second only
                '-f', 'null',
                '-'
            ]
            
            process = await loop.run_in_executor(
                None,
                lambda: subprocess.run(test_command, 
                                     stderr=subprocess.PIPE,
                                     timeout=5)
            )

            if process.stderr:
                logger.warning(f"Stream test warning: {process.stderr.decode()}")

            logger.info("Creating FFmpeg audio source...")
            ffmpeg_options = {
                'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
                'options': '-vn'
            }
            return discord.FFmpegPCMAudio(
                url,
                **ffmpeg_options
            )

        except Exception as e:
            logger.error(f"Error creating audio source: {e}")
            return None

    @classmethod
    async def from_track(cls, track, *, loop=None):
        """Create a YTDLSource from a Track object."""
        return await cls.from_url(track.url, loop=loop, stream=True)

    def cleanup(self):
        """Clean up resources."""
        try:
            if hasattr(self, 'original'):
                if hasattr(self.original, 'cleanup'):
                    self.original.cleanup()
                if hasattr(self.original, 'kill'):
                    self.original.kill()
                if hasattr(self.original, '_process'):
                    try:
                        self.original._process.kill()
                    except:
                        pass
        except Exception as e:
            logger.error(f"Error during cleanup: {e}")

# Auto-reconnect feature for the music cog
async def auto_reconnect(voice_client, channel, attempts=5):
    """Attempt to reconnect to voice channel if disconnected."""
    for i in range(attempts):
        try:
            if not voice_client.is_connected():
                await channel.connect()
                logger.info("Successfully reconnected to voice channel")
                return True
            return True
        except Exception as e:
            logger.error(f"Reconnection attempt {i+1} failed: {e}")
            await asyncio.sleep(1)
    return False