import os
import tempfile
import time
from http.cookiejar import MozillaCookieJar, Cookie

class YoutubeCookieManager:
    def __init__(self):
        self.temp_dir = tempfile.gettempdir()
        self.cookie_file = None
        self.cookie_jar = None
        self.last_creation_time = 0
        self.cookie_lifetime = 3600  # 1 hour in seconds

    def _create_cookie_jar(self) -> MozillaCookieJar:
        """Create a new cookie jar with YouTube cookies"""
        current_time = int(time.time())
        future_time = current_time + 365 * 24 * 60 * 60  # 1 year from now
        
        cookies = [
            {
                'name': 'CONSENT',
                'value': f'YES+yt.452525252.en+FX+{current_time}',
                'domain': '.youtube.com'
            },
            {
                'name': 'VISITOR_INFO1_LIVE',
                'value': 'xH_GYVxNCl0',
                'domain': '.youtube.com'
            },
            {
                'name': 'PREF',
                'value': 'hl=en&tz=UTC',
                'domain': '.youtube.com'
            },
            {
                'name': 'GPS',
                'value': '1',
                'domain': '.youtube.com'
            }
        ]
        
        cookie_jar = MozillaCookieJar(self.cookie_file)
        
        for cookie_data in cookies:
            cookie = Cookie(
                version=0,
                name=cookie_data['name'],
                value=cookie_data['value'],
                port=None,
                port_specified=False,
                domain=cookie_data['domain'],
                domain_specified=True,
                domain_initial_dot=True,
                path='/',
                path_specified=True,
                secure=True,
                expires=future_time,
                discard=False,
                comment=None,
                comment_url=None,
                rest={},
                rfc2109=False
            )
            cookie_jar._cookies.setdefault(cookie_data['domain'], {}).setdefault('/', {})[cookie_data['name']] = cookie
        
        return cookie_jar

    def get_cookie_file(self) -> str:
        """Get the path to a valid cookie file, creating new one if needed"""
        current_time = time.time()
        
        # Check if we need to create new cookies
        if (self.cookie_file is None or 
            not os.path.exists(self.cookie_file) or 
            current_time - self.last_creation_time > self.cookie_lifetime):
            
            # Clean up old cookie file if it exists
            self.cleanup()
            
            # Create new cookie file
            self.cookie_file = os.path.join(
                self.temp_dir, 
                f'youtube_cookies_{int(current_time)}.txt'
            )
            self.cookie_jar = self._create_cookie_jar()
            self.cookie_jar.save()
            self.last_creation_time = current_time
            
        return self.cookie_file

    def cleanup(self) -> None:
        """Remove the temporary cookie file if it exists"""
        if self.cookie_file and os.path.exists(self.cookie_file):
            try:
                os.remove(self.cookie_file)
                self.cookie_file = None
                self.cookie_jar = None
            except Exception as e:
                print(f"Error cleaning up cookie file: {e}")

    def get_yt_dlp_options(self) -> dict:
        """Get yt-dlp options with cookie configuration"""
        return {
            'quiet': False,
            'no_warnings': False,
            'cookiefile': self.get_cookie_file(),
            'extract_flat': True,
            'format': 'bestaudio/best',
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'en-us,en;q=0.5',
                'Sec-Fetch-Mode': 'navigate'
            }
        }

    def __del__(self):
        """Cleanup when the object is destroyed"""
        self.cleanup()