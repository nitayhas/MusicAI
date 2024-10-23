import aiohttp
import asyncio
from typing import Optional, Dict, List, Tuple
import yt_dlp as youtube_dl
from concurrent.futures import ThreadPoolExecutor
from config.settings import YTDL_FORMAT_OPTIONS, INITIAL_PLAYLIST_YTDL_FORMAT_OPTIONS, MAX_WORKERS
import logging

logger = logging.getLogger('music_bot')

class AgeRestrictedError(Exception):
    pass

class YouTubeService:
    def __init__(self, bot):
        self.bot = bot
        self.thread_pool = ThreadPoolExecutor(max_workers=MAX_WORKERS)
        self.ytdl = youtube_dl.YoutubeDL(YTDL_FORMAT_OPTIONS)

    async def extract_info(self, url, loop):
        try:
            return await loop.run_in_executor(None, lambda: self.ytdl.extract_info(url, download=False))
        except youtube_dl.utils.ExtractorError as e:
            if "age-restricted" in str(e):
                raise AgeRestrictedError("This video is age-restricted and cannot be played.")
            else:
                raise

    async def extract_video_info(self, url: str, semaphore: asyncio.Semaphore) -> Optional[Dict]:
        async with semaphore:
            tries = 0
            max_tries = 2
            while tries < max_tries:
                try:
                    info = await asyncio.wait_for(
                        asyncio.get_event_loop().run_in_executor(
                            self.thread_pool,
                            lambda: self.ytdl.extract_info(url, download=False)
                        ),
                        timeout=10
                    )
                    
                    if info:
                        return self._format_track_info(info)
                    return None
                    
                except (asyncio.TimeoutError, Exception) as e:
                    tries += 1
                    logger.error(f"Error extracting video info: {str(e)}")
                    if tries < max_tries and "age-restricted" not in str(e).lower():
                        await asyncio.sleep(1)
                    else:
                        return None
            
            return None
        
    def _get_best_audio_format(self, formats: List[Dict]) -> Optional[Dict]:
        """Select the best audio format based on specific criteria."""
        audio_formats = []
        
        for f in formats:
            # Check if it's an audio-only format
            if (f.get('acodec', 'none') != 'none' and 
                f.get('vcodec') in ['none', None]):
                
                # Calculate format score
                score = 0
                # Prefer certain codecs
                if f.get('acodec') == 'mp3':
                    score += 100
                elif f.get('acodec') == 'aac':
                    score += 90
                
                # Higher bitrate is better (up to 192kbps)
                abr = f.get('abr', 0)
                if abr <= 192:
                    score += abr / 2
                else:
                    score += 96 - (abr - 192) / 4
                
                # Higher sample rate is better (up to 44100)
                asr = f.get('asr', 0)
                if asr <= 44100:
                    score += asr / 1000
                
                audio_formats.append((f, score))

        if not audio_formats:
            return None

        # Sort by score and return the best format
        return max(audio_formats, key=lambda x: x[1])[0]

    async def process_url(self, query: str) -> Optional[Dict]:
        """Process a URL or search query and return track information."""
        try:
            # Extract info
            info = await asyncio.get_event_loop().run_in_executor(
                self.thread_pool,
                lambda: self.ytdl.extract_info(
                    query if query.startswith('http') else f"ytsearch:{query}",
                    download=False
                )
            )

            if 'entries' in info:
                info = info['entries'][0]

            # Get best audio format
            best_format = self._get_best_audio_format(info.get('formats', []))
            if best_format:
                logger.info(f"Selected audio format: {best_format.get('format_id')} "
                          f"(codec: {best_format.get('acodec')}, "
                          f"bitrate: {best_format.get('abr')}kbps)")
            else:
                logger.warning("No specific audio format found, using default stream URL")

            return {
                'title': info.get('title', 'Unknown Title'),
                'url': info.get('webpage_url', info.get('url')),
                'duration': info.get('duration', 0),
                'thumbnail': info.get('thumbnail'),
                'stream_url': best_format.get('url') if best_format else info.get('url')
            }

        except Exception as e:
            logger.error(f"Error processing URL: {str(e)}")
            raise

    async def get_playlist_info(self, url: str) -> Tuple[List[Dict], int]:
        """Get information about all videos in a playlist."""
        try:
            with youtube_dl.YoutubeDL(INITIAL_PLAYLIST_YTDL_FORMAT_OPTIONS) as local_ydl:
                playlist_info = await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: local_ydl.extract_info(url, download=False)
                )
            
            if not playlist_info or 'entries' not in playlist_info:
                return [], 0
                
            # Filter out None entries
            video_entries = [entry for entry in playlist_info['entries'] if entry is not None]
            return video_entries, len(video_entries)
            
        except Exception as e:
            logger.error(f"Error getting playlist info: {str(e)}")
            raise

    async def search_videos(self, query: str, max_results: int = 5) -> List[Dict]:
        """Search for videos on YouTube."""
        search_url = f"ytsearch{max_results}:{query}"
        try:
            info = await asyncio.get_event_loop().run_in_executor(
                self.thread_pool,
                lambda: self.ytdl.extract_info(search_url, download=False)
            )
            
            if not info or 'entries' not in info:
                return []
                
            return [self._format_track_info(entry) for entry in info['entries'] if entry is not None]
        except Exception as e:
            logger.error(f"Error searching videos: {str(e)}")
            return []
        
    async def parallel_search(self, query, max_results=5):
        search_url = f"ytsearch{max_results}:{query}"
        async with aiohttp.ClientSession() as session:
            async with session.get(search_url) as response:
                html = await response.text()
        
        # Parse the HTML to extract video information
        # This is a simplified example; you may need to use a proper HTML parser
        video_ids = [line.split('watch?v=')[1].split('"')[0] for line in html.split('\n') if 'watch?v=' in line][:max_results]
        
        tasks = [self.extract_info(f"https://www.youtube.com/watch?v={video_id}", self.bot.loop) for video_id in video_ids]
        results = await asyncio.gather(*tasks)
        
        return results

    def _format_track_info(self, info: Dict) -> Dict:
        """Format track information consistently."""
        return {
            'title': info.get('title', 'Unknown Title'),
            'url': info.get('webpage_url', info.get('url')),
            'duration': info.get('duration', 0),
            'thumbnail': info.get('thumbnail'),
            'stream_url': info.get('url')  # Direct audio stream URL
        }