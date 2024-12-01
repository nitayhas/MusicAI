import os
import pylast
from dotenv import load_dotenv
from utils.youtube_cookie_manager import YoutubeCookieManager

# Load environment variables
load_dotenv()

# Bot settings
COMMAND_PREFIX = '!'
TOKEN = os.getenv('DISCORD_TOKEN')
YOUTUBE_OAUTH_TOKEN = os.getenv('YOUTUBE_OAUTH_TOKEN')
FFMPEG_PATH = os.getenv('FFMPEG_PATH')
LASTFM_API_KEY = os.getenv('LASTFM_API_KEY')
LASTFM_API_SECRET = os.getenv('LASTFM_API_SECRET')
LASTFM_USERNAME = os.getenv('LASTFM_USERNAME')
LASTFM_PASSWORD = pylast.md5(os.getenv('LASTFM_PASSWORD'))

youtube_cookie_manager = YoutubeCookieManager()

YTDL_FORMAT_OPTIONS = {
    'outtmpl': '%(extractor)s-%(id)s-%(title)s.%(ext)s',
    'restrictfilenames': True,
    'noplaylist': True,
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'logtostderr': False,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'ytsearch2',
    'extract_flat': False,
    # Network and quality options
    'source_address': '0.0.0.0',
    'preferredcodec': 'opus',
    'preferredquality': '192',
    # # Added for stability
    # 'retries': 5,
    # 'fragment_retries': 5,
    # 'skip_unavailable_fragments': True,
    # 'postprocessor_args': ['-threads', '1'],  # Single thread for stability
    
    # # Authentication options
    # 'username': 'oauth',  # Use OAuth authentication
    # 'password': '',       # Password should be empty for OAuth
    # 'oauth_token': YOUTUBE_OAUTH_TOKEN,
    
    'cookiefile': youtube_cookie_manager.get_cookie_file()
}

INITIAL_PLAYLIST_YTDL_FORMAT_OPTIONS = {
    'format': 'bestaudio/best',
    'quiet': True,
    'no_warnings': True,
    'ignoreerrors': True,  # Don't stop on errors
    'nocheckcertificate': True,
    'skip_download': True,
    'lazy_playlist': False,  # Load full playlist
    'extract_flat': True,  # Only get basic info first
    'force_generic_extractor': False,
    'flat_playlist': True,
    # 'verbose': True,

    # Network and quality options
    'source_address': '0.0.0.0',
    'preferredcodec': 'opus',
    'preferredquality': '192',
    
    # Authentication options
    'username': 'oauth',  # Use OAuth authentication
    'password': '',       # Password should be empty for OAuth
    'oauth_token': YOUTUBE_OAUTH_TOKEN,

    'extractor_args': {
        'youtube': {
            'skip': ['dash', 'hls'],
            'player_skip': ['webpage', 'js'],
            'player_client': ['android', 'web'],
        }
    }
}



# INITIAL_PLAYLIST_YTDL_FORMAT_OPTIONS = {
#     **YTDL_FORMAT_OPTIONS,
#     'extract_flat': 'playlist',
#     'playlist_items': '1-100',
#     'ignore_no_formats_error': True,
#     'ignoreerrors': True,
#     'skip_download': True,
#     'lazy_playlist': False,  # Load full playlist
#     'force_generic_extractor': False,
#     'extractor_args': {
#         'youtube': {
#             'skip': ['dash', 'hls'],
#             'player_skip': ['webpage', 'js'],
#             'player_client': ['android', 'web'],
#         }
#     }
# }


# Simplified FFmpeg options focusing on reliable audio playback
FFMPEG_OPTIONS = {
    'before_options': (
        '-reconnect 1 '              # Auto-reconnect if disconnected
        '-reconnect_streamed 1 '     # Reconnect streamed resources
        '-reconnect_delay_max 5 '    # Maximum delay before reconnect
        '-nostdin '                  # Disable interaction
        '-thread_queue_size 4096 '   # Increase buffer queue size
        '-fflags +nobuffer '         # Avoid buffering (low-latency)
    ),
    'options': (
        '-vn '                       # No video
        '-ac 2 '                     # Stereo audio channels
        '-b:a 192k '                 # Set a good audio bitrate (192kbps for music)
        '-ar 48000 '                 # 48kHz sample rate (Discord standard)
        '-loglevel error '           # Show only errors to reduce log noise
    )
}

MAX_WORKERS = 5
CHUNK_SIZE = 5
MAX_SEARCH_RESULTS = 5