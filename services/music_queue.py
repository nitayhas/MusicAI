import uuid
from collections import deque
from dataclasses import dataclass
from typing import Optional, Dict, Callable

@dataclass
class Track:
    title: str
    url: str  # webpage URL
    duration: int
    thumbnail: Optional[str] = None
    stream_url: Optional[str] = None  # Direct audio stream URL

@dataclass
class PlaylistLoader:
    """Manages the state of playlist loading"""
    current_index: int = 0
    video_entries: list = None
    total_tracks: int = 0
    is_loading: bool = False
    url: str = ""  # Store playlist URL for continued loading

    def __post_init__(self):
        if self.video_entries is None:
            self.video_entries = []


@dataclass
class QueueItem:
    """Wrapper for Track with callback support"""
    track: Track
    callback_id: Optional[str] = None

class MusicQueue:
    def __init__(self):
        self.queue: deque[QueueItem] = deque()
        self.current_track: Optional[Track] = None
        self.is_playing: bool = False
        self.playlist_processing: bool = False
        self.playlist_loader: Optional[PlaylistLoader] = None
        self._callbacks: Dict[str, Callable] = {}

    def add_track(self, track: Track, on_start: Optional[Callable] = None) -> None:
        """
        Add a track to the queue with an optional callback for when it starts playing
        
        Args:
            track (Track): The track to add to the queue
            on_start (Optional[Callable]): Callback function to execute when track starts playing
        """
        callback_id = str(uuid.uuid4()) if on_start else None
        if callback_id:
            self._callbacks[callback_id] = on_start
        
        queue_item = QueueItem(track=track, callback_id=callback_id)
        self.queue.append(queue_item)

    def get_next_track(self) -> Optional[Track]:
        """Get the next track and execute its callback if it exists"""
        if not self.queue:
            return None
            
        queue_item = self.queue.popleft()
        if queue_item.callback_id and queue_item.callback_id in self._callbacks:
            callback = self._callbacks.pop(queue_item.callback_id)
            try:
                callback()
            except Exception as e:
                # Handle or log callback errors
                print(f"Error executing track callback: {e}")
        
        return queue_item.track

    def clear(self) -> None:
        """Clear the queue and reset all states"""
        self.queue.clear()
        self.current_track = None
        self.is_playing = False
        self.playlist_loader = None
        self._callbacks.clear()

    def start_playlist_loading(self, playlist_url: str) -> None:
        """Initialize playlist loading state"""
        self.playlist_loader = PlaylistLoader(url=playlist_url)
        self.playlist_processing = True

    def finish_playlist_loading(self) -> None:
        """Clean up playlist loading state"""
        self.playlist_processing = False

    def is_playlist_complete(self) -> bool:
        """Check if all playlist tracks have been processed"""
        if not self.playlist_loader:
            return True
        return (self.playlist_loader.current_index >= 
                len(self.playlist_loader.video_entries))

    def get_playlist_progress(self) -> tuple[int, int]:
        """Get current playlist loading progress"""
        if not self.playlist_loader:
            return (0, 0)
        return (self.playlist_loader.current_index, 
                self.playlist_loader.total_tracks)

class QueueManager:
    def __init__(self):
        self._queues: Dict[int, MusicQueue] = {}

    def get_queue(self, guild_id: int) -> MusicQueue:
        if guild_id not in self._queues:
            self._queues[guild_id] = MusicQueue()
        return self._queues[guild_id]

    def remove_queue(self, guild_id: int) -> None:
        if guild_id in self._queues:
            del self._queues[guild_id]