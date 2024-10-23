from collections import deque
from dataclasses import dataclass
from typing import Optional, Dict

@dataclass
class Track:
    title: str
    url: str  # webpage URL
    duration: int
    thumbnail: Optional[str] = None
    stream_url: Optional[str] = None  # Direct audio stream URL

class MusicQueue:
    def __init__(self):
        self.queue: deque[Track] = deque()
        self.current_track: Optional[Track] = None
        self.is_playing: bool = False
        self.playlist_processing: bool = False

    def add_track(self, track: Track) -> None:
        self.queue.append(track)

    def get_next_track(self) -> Optional[Track]:
        return self.queue.popleft() if self.queue else None

    def clear(self) -> None:
        self.queue.clear()
        self.current_track = None
        self.is_playing = False

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