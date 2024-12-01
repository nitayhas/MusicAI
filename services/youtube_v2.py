import platform
import asyncio
import signal
import psutil
import traceback
import sys
from typing import Optional, Dict, List, Tuple
from pytubefix import YouTube, Playlist, Search
from concurrent.futures import ThreadPoolExecutor
import threading
import logging
from urllib.parse import urlparse, parse_qs

logger = logging.getLogger('music_bot')

class AgeRestrictedError(Exception):
    pass

def set_worker_limits():
    """Set resource limits for worker threads."""
    try:
        process = psutil.Process()
        num_cpus = max(1, psutil.cpu_count() // 2)
        
        if hasattr(process, 'cpu_affinity'):
            try:
                process.cpu_affinity(list(range(num_cpus)))
            except Exception as e:
                logger.warning(f"Could not set CPU affinity: {e}")

        if platform.system() == 'Windows':
            try:
                process.nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
            except Exception as e:
                logger.warning(f"Could not set process priority on Windows: {e}")
        else:
            try:
                process.nice(10)
            except Exception as e:
                logger.warning(f"Could not set process priority on Unix: {e}")

        if hasattr(psutil, 'IOPRIO_CLASS_BE'):
            try:
                process.ionice(psutil.IOPRIO_CLASS_BE)
            except Exception as e:
                logger.warning(f"Could not set IO priority on Linux: {e}")
        elif hasattr(psutil, 'IOPRIO_LOW'):
            try:
                process.ionice(psutil.IOPRIO_LOW)
            except Exception as e:
                logger.warning(f"Could not set IO priority on Windows: {e}")

    except Exception as e:
        logger.warning(f"Could not set all resource limits: {e}")

class ResourceLimitedThreadPoolExecutor(ThreadPoolExecutor):
    """ThreadPoolExecutor with resource limits."""
    def __init__(self, max_workers=None, thread_name_prefix=''):
        super().__init__(max_workers, thread_name_prefix=thread_name_prefix)
        self._active_tasks = 0
        self._lock = threading.Lock()
        self._memory_threshold = 500 * 1024 * 1024  # 500MB
        self._shutdown_event = threading.Event()

    def submit(self, fn, *args, **kwargs):
        with self._lock:
            if self._active_tasks >= self._max_workers:
                logger.warning("Thread pool at maximum capacity")
                raise RuntimeError("Thread pool overwhelmed")
                
            process = psutil.Process()
            memory_use = process.memory_info().rss
            if memory_use > self._memory_threshold:
                logger.warning(f"High memory usage: {memory_use / 1024 / 1024:.2f}MB")
                
            self._active_tasks += 1
        
        future = super().submit(self._wrapped_fn, fn, *args, **kwargs)
        future.add_done_callback(self._task_done)
        return future

    def _wrapped_fn(self, fn, *args, **kwargs):
        set_worker_limits()
        return fn(*args, **kwargs)

    def _task_done(self, future):
        with self._lock:
            self._active_tasks -= 1

    def shutdown(self, wait=True):
        logger.info("Shutting down the thread pool executor")
        self._shutdown_event.set()
        super().shutdown(wait=wait)

def signal_handler(signal, frame, executor):
    logger.info("Caught Ctrl+C! Attempting to shut down gracefully...")
    executor.shutdown(wait=True)
    sys.exit(0)

def on_progress(stream, chunk, bytes_remaining):
    """Callback function for download progress."""
    total_size = stream.filesize
    bytes_downloaded = total_size - bytes_remaining
    percentage = (bytes_downloaded / total_size) * 100
    logger.debug(f"Download Progress: {percentage:.2f}%")

class YouTubeService:
    def __init__(self, bot):
        self.bot = bot
        
        cpu_count = psutil.cpu_count()
        memory_gb = psutil.virtual_memory().total / (1024 ** 3)
        
        max_workers = min(
            10,  # Maximum workers (adjusted from MAX_WORKERS constant)
            max(1, cpu_count // 2),
            max(1, int(memory_gb))
        )
        
        logger.info(f"Initializing YouTube service with {max_workers} workers")
        
        self.thread_pool = ResourceLimitedThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix='yt_worker'
        )
        
        signal.signal(signal.SIGINT, lambda s, f: signal_handler(s, f, self.thread_pool))
        self._extraction_semaphore = asyncio.Semaphore(3)

    def _monitor_resources(self):
        """Monitor system resource usage."""
        process = psutil.Process()
        memory_use = process.memory_info().rss
        cpu_percent = process.cpu_percent()

        if memory_use > 500 * 1024 * 1024:
            logger.warning(f"High memory usage: {memory_use / 1024 / 1024:.2f}MB")
        if cpu_percent > 70:
            logger.warning(f"High CPU usage: {cpu_percent}%")

        return memory_use, cpu_percent

    async def extract_info(self, url, loop):
        """Extract information with resource limits."""
        async with self._extraction_semaphore:
            self._monitor_resources()
            try:
                return await loop.run_in_executor(
                    self.thread_pool,
                    lambda: self._get_video_info(url)
                )
            except Exception as e:
                if "age restricted" in str(e).lower():
                    raise AgeRestrictedError("This video is age-restricted and cannot be played.")
                raise

    def _get_video_info(self, url: str) -> Dict:
        """Get video information using pytubefix."""
        yt = YouTube(url, use_oauth=True, allow_oauth_cache=True, on_progress_callback=on_progress)
        audio_stream = yt.streams.filter(only_audio=True).first()
        
        return {
            'title': yt.title,
            'url': url,
            'duration': yt.length,
            'thumbnail': yt.thumbnail_url,
            'stream_url': audio_stream.url if audio_stream else None
        }

    async def extract_video_info(self, url: str, semaphore: asyncio.Semaphore) -> Optional[Dict]:
        async with semaphore:
            self._monitor_resources()
            tries = 0
            max_tries = 2
            timeout_duration = 5
            
            while tries < max_tries:
                try:
                    info = await asyncio.wait_for(
                        self.bot.loop.run_in_executor(
                            None,
                            lambda: self._get_video_info(url)
                        ),
                        timeout=timeout_duration
                    )

                    if info:
                        return info
                    return None

                except asyncio.TimeoutError:
                    tries += 1
                    logger.error(f"TimeoutError extracting video info for URL: {url}. Attempt {tries} of {max_tries}.")
                    timeout_duration *= 2
                except asyncio.CancelledError:
                    logger.error(f"CancelledError while extracting video info for URL: {url}.")
                    raise
                except Exception as e:
                    tries += 1
                    logger.error(f"Error extracting video info: {str(e)} | for url: {url}")
                    logger.error(f"Full traceback: {traceback.format_exc()}")
                await asyncio.sleep(1)

            return None

    async def process_url(self, query: str) -> Optional[Dict]:
        """Process a single URL or search query."""
        try:
            if not query.startswith('http'):
                search_results = await self.search_videos(query, max_results=1)
                if not search_results:
                    return None
                return search_results[0]
            
            return await asyncio.get_event_loop().run_in_executor(
                self.thread_pool,
                lambda: self._get_video_info(query)
            )
            
        except Exception as e:
            logger.error(f"Error processing URL: {str(e)}")
            raise

    async def get_playlist_info(self, url: str) -> Tuple[List[Dict], int]:
        """Get information about all videos in a playlist."""
        try:
            playlist = await asyncio.get_event_loop().run_in_executor(
                self.thread_pool,
                lambda: Playlist(url)
            )
            
            videos = []
            for video_url in playlist.video_urls:
                try:
                    info = await self.extract_info(video_url, self.bot.loop)
                    if info:
                        videos.append(info)
                except Exception as e:
                    logger.error(f"Error extracting playlist video info: {str(e)}")
                    continue
            
            return videos, len(videos)
            
        except Exception as e:
            logger.error(f"Error getting playlist info: {str(e)}")
            raise

    async def search_videos(self, query: str, max_results: int = 5) -> List[Dict]:
        """Search for videos on YouTube."""
        try:
            search_results = await asyncio.get_event_loop().run_in_executor(
                self.thread_pool,
                lambda: Search(query).results[:max_results]
            )
            
            videos = []
            for video in search_results:
                try:
                    info = self._format_track_info(video)
                    if info:
                        videos.append(info)
                except Exception as e:
                    logger.error(f"Error formatting search result: {str(e)}")
                    continue
                    
            return videos
            
        except Exception as e:
            logger.error(f"Error searching videos: {str(e)}")
            return []

    def _format_track_info(self, video) -> Dict:
        """Format track information consistently."""
        try:
            audio_stream = video.streams.filter(only_audio=True).first()
            return {
                'title': video.title,
                'url': video.watch_url,
                'duration': video.length,
                'thumbnail': video.thumbnail_url,
                'stream_url': audio_stream.url if audio_stream else None
            }
        except Exception as e:
            logger.error(f"Error formatting track info: {str(e)}")
            return None

    def __del__(self):
        """Cleanup resources."""
        try:
            self.thread_pool.shutdown()
        except Exception as e:
            logger.error(f"Error shutting down thread pool: {e}")