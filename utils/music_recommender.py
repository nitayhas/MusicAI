import pylast
from typing import List, Dict, Optional
import re
from difflib import SequenceMatcher
import logging

logger = logging.getLogger('music_bot')

class MusicRecommender:
    def __init__(self, api_key: str, api_secret: str, username: str = None, password_hash: str = None):
        """
        Initialize the Last.fm recommender system.
        
        Args:
            api_key: Your Last.fm API key
            api_secret: Your Last.fm API secret
            username: Optional Last.fm username
            password_hash: Optional Last.fm password hash
        """
        self.network = pylast.LastFMNetwork(
            api_key=api_key,
            api_secret=api_secret,
            username=username,
            password_hash=password_hash
        )
        
    def clean_title(self, title: str) -> tuple[str, str]:
        """
        Clean YouTube title to extract artist and track name.
        
        Args:
            title: YouTube video title
            
        Returns:
            Tuple of (artist, track_name)
        """
        # Remove common YouTube music title patterns
        title = re.sub(r'\(Official.*?\)', '', title)
        title = re.sub(r'\[Official.*?\]', '', title)
        title = re.sub(r'\(Lyrics.*?\)', '', title)
        title = re.sub(r'\[Lyrics.*?\]', '', title)
        title = re.sub(r'\(Audio.*?\)', '', title)
        title = re.sub(r'\[Audio.*?\]', '', title)
        title = re.sub(r'\(Official Music Video\)', '', title)
        title = re.sub(r'\(Official Video\)', '', title)
        title = re.sub(r'\(Video.*?\)', '', title)
        title = re.sub(r'\[Video.*?\]', '', title)
        
        # Try to split by common separators
        for separator in [' - ', ' – ', ' — ']:
            if separator in title:
                artist, track = title.split(separator, 1)
                return artist.strip(), track.strip()
        
        # If no separator found, return the whole title as track name
        return "", title.strip()
    
    def get_similar_tracks(self, 
                          youtube_title: str, 
                          limit: int = 5, 
                          min_similarity: float = 0.1) -> List[Dict[str, str]]:
        """
        Get similar tracks based on a YouTube video title.
        
        Args:
            youtube_title: Title of the YouTube video
            limit: Maximum number of recommendations to return
            min_similarity: Minimum similarity score (0-1) for track matching
            
        Returns:
            List of dictionaries containing similar tracks with artist and title
        """
        logger.info(f"Starting get_similar_tracks")
        try:
            # Clean the YouTube title
            track_info = self.get_track_info(youtube_title)
            logger.info(f"Finding similar to artist: {track_info['artist']} and with title: {track_info['title']}")
            
            # If we couldn't extract artist, try to find the track directly
            if len(track_info['artist'])==0:
                search_results = self.network.search_for_track("", track_info['title'])
                search_results = search_results.get_next_page()
                
                if search_results:
                    # Use the first search result
                    track = search_results[0]
                else:
                    return []
            else:
                # If we have artist and track, get the track directly
                track = self.network.get_track(track_info['artist'], track_info['title'])
            
            # Get similar tracks
            similar_tracks = track.get_similar(limit=limit)
            
            recommendations = []
            for similar in similar_tracks:
                # Calculate similarity score between original and recommendation
                similarity = SequenceMatcher(
                    None,
                    f"{track_info['artist']} {track_info['title']}".lower(),
                    f"{similar.item.artist.name} {similar.item.title}".lower()
                ).ratio()
                
                # Only include recommendations with sufficient similarity
                if similarity >= min_similarity:
                    recommendations.append({
                        'artist': similar.item.artist.name,
                        'title': similar.item.title,
                        'similarity_score': similarity,
                        'search_query': f"{similar.item.artist.name} - {similar.item.title}"
                    })
            
            return sorted(recommendations, key=lambda x: x['similarity_score'], reverse=True)
            
        except pylast.WSError as e:
            print(f"Last.fm API error: {e}")
            return []
        except Exception as e:
            print(f"Error getting recommendations: {e}")
            return []

    def get_track_info(self, youtube_title: str) -> Optional[Dict]:
        """
        Get additional track information from Last.fm.
        
        Args:
            youtube_title: Title of the YouTube video
            
        Returns:
            Dictionary containing track information or None if not found
        """
        try:
            artist, track_name = self.clean_title(youtube_title)
            
            if len(artist)==0:
                search_results = self.network.search_for_track("", track_name)
                search_results = search_results.get_next_page()
                if search_results:
                    track = search_results[0]
                else:
                    return None
            else:
                track = self.network.get_track(artist, track_name)
            
            return {
                'artist': track.artist.name,
                'title': track.title,
                'listeners': track.get_listener_count(),
                'playcount': track.get_playcount(),
                'tags': [tag.item.name for tag in track.get_top_tags(limit=5)],
                'wiki': track.get_wiki_content() if track.get_wiki_content() else None
            }
            
        except Exception as e:
            print(f"Error getting track info: {e}")
            return None