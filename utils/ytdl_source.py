import os
import stat
import asyncio
import discord
from yt_dlp import YoutubeDL
from config.settings import YTDL_FORMAT_OPTIONS, FFMPEG_OPTIONS, FFMPEG_PATH
from services.music_queue import Track
import logging
import time
from typing import Optional, Dict
import subprocess


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
            # Extract info
            with YoutubeDL(YTDL_FORMAT_OPTIONS) as ytdl:
                logger.info(f"Extracting info for URL: {url}")
                data = await loop.run_in_executor(
                    None,
                    lambda: ytdl.extract_info(url, download=not stream)
                )

            if not data:
                raise ValueError("Could not extract video information")

            if 'entries' in data:
                data = data['entries'][0]

            # Get best audio format
            formats = data.get('formats', [])
            best_audio = None
            
            # First try to find Opus format
            for f in formats:
                if (f.get('acodec') == 'opus' and 
                    (not f.get('vcodec') or f.get('vcodec') == 'none')):
                    best_audio = f
                    break

            # If no Opus, try any audio format
            if not best_audio:
                for f in formats:
                    if (f.get('acodec') and f.get('acodec') != 'none' and 
                        (not f.get('vcodec') or f.get('vcodec') == 'none')):
                        best_audio = f
                        break

            # If still no format found, use the default URL
            if best_audio:
                stream_url = best_audio['url']
                logger.info(f"Using audio format: {best_audio.get('format_id')} "
                          f"(codec: {best_audio.get('acodec')})")
            else:
                stream_url = data['url']
                logger.info("Using default stream URL")

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
            return discord.FFmpegPCMAudio(
                url,
                **FFMPEG_OPTIONS
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