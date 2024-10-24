import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Bot settings
COMMAND_PREFIX = '!'
TOKEN = os.getenv('DISCORD_TOKEN')
YOUTUBE_OAUTH_TOKEN = os.getenv('YOUTUBE_OAUTH_TOKEN')
FFMPEG_PATH = os.getenv('FFMPEG_PATH')

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
    'extract_flat': False,
    
    # Authentication options
    'username': 'oauth',  # Use OAuth authentication
    'password': '',       # Password should be empty for OAuth
    'oauth_token': YOUTUBE_OAUTH_TOKEN,
}

# INITIAL_PLAYLIST_YTDL_FORMAT_OPTIONS = {
#     'format': 'bestaudio/best',
#     'extract_flat': 'playlist',  # Only extract basic info for playlist items
#     'quiet': True,
#     'no_warnings': True,
#     'ignoreerrors': True,  # Don't stop on errors
#     'nocheckcertificate': True,
#     'skip_download': True,
#     'lazy_playlist': False,  # Load full playlist
#     'extract_flat': True,  # Only get basic info first
#     'force_generic_extractor': False,
#     # 'extract_flat': 'playlist',  # Get playlist info without downloading
#     'extractor_args': {
#         'youtube': {
#             'skip': ['dash', 'hls'],
#             'player_skip': ['webpage', 'js'],
#             'player_client': ['android', 'web'],
#         }
#     }
# }


INITIAL_PLAYLIST_YTDL_FORMAT_OPTIONS = {
    **YTDL_FORMAT_OPTIONS,
    'extract_flat': 'playlist',
    'playlist_items': '1-100',
    'ignore_no_formats_error': True,
    'ignoreerrors': True,
    'skip_download': True,
    'lazy_playlist': False,  # Load full playlist
    'force_generic_extractor': False,
    'extractor_args': {
        'youtube': {
            'skip': ['dash', 'hls'],
            'player_skip': ['webpage', 'js'],
            'player_client': ['android', 'web'],
        }
    }
}


FFMPEG_OPTIONS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn'
}

# Playlist processing settings
MAX_WORKERS = 5
CHUNK_SIZE = 5
MAX_SEARCH_RESULTS = 5