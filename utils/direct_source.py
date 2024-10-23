import discord
import asyncio
from yt_dlp import YoutubeDL
import logging

logger = logging.getLogger('music_bot')

# Configure YTDL for direct streaming
STREAM_OPTIONS = {
    'format': 'bestaudio/best',
    'noplaylist': True,
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'auto',
    'source_address': '0.0.0.0',
    'force-ipv4': True,
    # Prefer direct streaming formats
    'format_sort': [
        'acodec:opus',  # Discord uses Opus
        'acodec:aac',
        'asr:48000',    # Discord preferred sample rate
        'abr:160',
        'filesize'
    ],
    'extractor_args': {
        'youtube': {
            'skip': ['dash', 'hls'],
            'player_client': ['android', 'web']
        }
    }
}

class DirectAudioSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data, volume=0.5):
        super().__init__(discord.FFmpegOpusAudio(source), volume)
        self.data = data
        self.title = data.get('title')
        self.url = data.get('url')
        self.duration = data.get('duration')
        self.thumbnail = data.get('thumbnail')

    @classmethod
    async def from_url(cls, url, *, loop=None, stream=True):
        loop = loop or asyncio.get_event_loop()
        ytdl = YoutubeDL(STREAM_OPTIONS)

        try:
            data = await loop.run_in_executor(None, lambda: ytdl.extract_info(url, download=not stream))
            
            if 'entries' in data:
                data = data['entries'][0]

            # Try to find the best opus format (Discord's native format)
            formats = data.get('formats', [])
            best_format = None
            
            # First try to find opus format
            for f in formats:
                if f.get('acodec') == 'opus':
                    best_format = f
                    break
            
            # If no opus, try to find any audio-only format
            if not best_format:
                audio_formats = [
                    f for f in formats
                    if f.get('acodec') != 'none' and f.get('vcodec') in ['none', None]
                ]
                if audio_formats:
                    best_format = max(
                        audio_formats,
                        key=lambda x: (
                            x.get('abr', 0),
                            x.get('asr', 0),
                            -x.get('filesize', float('inf'))
                        )
                    )

            stream_url = best_format['url'] if best_format else data['url']
            logger.info(f"Selected format: {best_format.get('format_id')} "
                       f"(codec: {best_format.get('acodec')})")

            # Create audio source using Discord's native audio system
            audio_source = await discord.FFmpegOpusAudio.from_probe(
                stream_url,
                # Minimal FFmpeg options for format conversion only
                method='fallback'
            )

            return cls(audio_source, data=data)

        except Exception as e:
            logger.error(f"Error creating direct audio source: {str(e)}")
            raise

    @staticmethod
    def prepare_stream_url(url):
        """Prepare a stream URL for direct playback."""
        try:
            ytdl = YoutubeDL(STREAM_OPTIONS)
            info = ytdl.extract_info(url, download=False)
            
            if 'entries' in info:
                info = info['entries'][0]
                
            return info.get('url'), info
        except Exception as e:
            logger.error(f"Error preparing stream URL: {str(e)}")
            raise