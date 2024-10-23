import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Bot settings
COMMAND_PREFIX = '!'
TOKEN = os.getenv('DISCORD_TOKEN')
FFMPEG_PATH = os.getenv('FFMPEG_PATH')

# # YouTube DL options
# YTDL_FORMAT_OPTIONS = {
#     'format': 'bestaudio/best',
#     'outtmpl': '%(extractor)s-%(id)s-%(title)s.%(ext)s',
#     'restrictfilenames': True,
#     'noplaylist': True,
#     'nocheckcertificate': True,
#     'ignoreerrors': False,
#     'logtostderr': False,
#     'quiet': True,
#     'no_warnings': True,
#     'default_search': 'auto',
#     'source_address': '0.0.0.0',
#     'force-ipv4': True,
#     'preferredcodec': 'mp3',
#     'cachedir': False,
#     # Use specific audio format selection
#     'format_sort': [
#         'acodec:mp3',
#         'acodec:aac',
#         'asr:44100',
#         'abr:192',
#         'filesize'
#     ],
#     # Ensure we get a working audio stream
#     'extract_flat': False,
#     'extractor_args': {
#         'youtube': {
#             'skip': ['dash', 'hls'],  # Skip DASH and HLS formats
#             'player_skip': ['webpage', 'js'],  # Skip unnecessary data
#             'player_client': ['android', 'web'],  # Try multiple clients
#         }
#     }
# }


YTDL_FORMAT_OPTIONS = {
    'format': 'bestaudio/best',
    'outtmpl': '%(extractor)s-%(id)s-%(title)s.%(ext)s',
    'restrictfilenames': True,
    'noplaylist': True,
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'logtostderr': False,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'auto',
    'source_address': '0.0.0.0',
    'extract_flat': False
}

INITIAL_PLAYLIST_YTDL_FORMAT_OPTIONS = {
    'quiet': True,
    'extract_flat': 'in_playlist',
    'force_generic_extractor': False,
    'no_warnings': True,
    'ignoreerrors': True,
    'age_limit': None,
    'nocheckcertificate': True,
    'extractor_args': {
        'youtube': {
            'player_skip': ['webpage', 'js'],
            'player_client': ['android', 'web'],
            'skip': ['dash', 'hls'],
        }
    }
}

# FFMPEG_OPTIONS = {
#     'before_options': (
#         # Handle network interruptions
#         '-reconnect 1 '
#         '-reconnect_streamed 1 '
#         '-reconnect_delay_max 5 '
#         # Better buffering
#         '-analyzeduration 0 '
#         '-probesize 32768'
#     ),
#     'options': (
#         # Audio specific options
#         '-vn '  # No video
#         '-bufsize 64k '  # Buffer size
#         '-ar 44100 '  # Audio sample rate
#         '-ac 2 '  # Stereo
#         '-b:a 192k '  # Audio bitrate
#         '-loglevel warning'  # Reduce FFmpeg logging
#     )
# }


FFMPEG_OPTIONS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn'
}

# Playlist processing settings
MAX_WORKERS = 25
CHUNK_SIZE = 5
MAX_SEARCH_RESULTS = 5