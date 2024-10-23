import os
import stat
import asyncio
import discord
from yt_dlp import YoutubeDL
from config.settings import YTDL_FORMAT_OPTIONS, FFMPEG_OPTIONS, FFMPEG_PATH
from services.music_queue import Track

ytdl = YoutubeDL(YTDL_FORMAT_OPTIONS)

def check_file_permissions(filepath: str) -> bool:
    """Check if we have read and write permissions for the file."""
    return os.access(filepath, os.R_OK | os.W_OK)

class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data, volume=1.0):
        super().__init__(source, volume)
        self.data = data
        self.title = data.get('title')
        self.url = data.get('url')
        self.duration = data.get('duration')
        self.thumbnail = data.get('thumbnail')

    @classmethod
    async def from_url(cls, url: str, *, loop=None, stream=False):
        """Creates a YTDLSource from a URL."""
        loop = loop or asyncio.get_event_loop()
        data = await loop.run_in_executor(None, lambda: ytdl.extract_info(url, download=not stream))

        if 'entries' in data:
            data = data['entries'][0]

        if stream:
            filename = data['url']
        else:
            filename = ytdl.prepare_filename(data)
            wav_filename = filename.rsplit('.', 1)[0] + '.wav'
            
            if os.path.exists(wav_filename):
                filename = wav_filename
                
            if not check_file_permissions(filename):
                os.chmod(filename, stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH)

        return cls(
            discord.FFmpegPCMAudio(
                source=filename,
                **FFMPEG_OPTIONS,
                executable=FFMPEG_PATH
            ),
            data=data
        )

    @classmethod
    async def from_track(cls, track: Track, *, loop=None):
        """Creates a YTDLSource from a Track object."""
        return cls(
            discord.FFmpegPCMAudio(
                source=track.stream_url,
                **FFMPEG_OPTIONS,
                executable=FFMPEG_PATH
            ),
            data={
                'title': track.title,
                'url': track.url,
                'duration': track.duration,
                'thumbnail': track.thumbnail
            }
        )