import os
import uuid
import time
import random
import string
import tempfile
from http.cookiejar import MozillaCookieJar, Cookie

class YoutubeCookieManager:
    def __init__(self):
        self.temp_dir = tempfile.gettempdir()
        self.cookie_file = None
        self.cookie_jar = None
        self.last_creation_time = 0
        self.cookie_lifetime = 3600  # 1 hour in seconds
        self.device_id = str(uuid.uuid4())

    def _generate_visitor_id(self) -> str:
        return ''.join(random.choices(string.ascii_letters + string.digits, k=11))

    def _create_cookie_jar(self) -> MozillaCookieJar:
        current_time = int(time.time())
        future_time = current_time + 365 * 24 * 60 * 60
        visitor_id = self._generate_visitor_id()
        
        cookies = [
            {
                'name': 'CONSENT',
                'value': f'YES+cb.20220301-11-p0.en-GB+FX+{current_time}',
                'domain': '.youtube.com'
            },
            {
                'name': 'VISITOR_INFO1_LIVE',
                'value': visitor_id,
                'domain': '.youtube.com'
            },
            {
                'name': 'PREF',
                'value': 'hl=en&gl=US',
                'domain': '.youtube.com'
            },
            {
                'name': '_gcl_au',
                'value': '1.1.548239985.1674856835',
                'domain': '.youtube.com'
            },
            {
                'name': 'DEVICE_INFO',
                'value': self.device_id,
                'domain': '.youtube.com'
            },
            {
                'name': 'VISITOR_PRIVACY_METADATA',
                'value': 'CgJVUxICGgA=',
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
        current_time = time.time()
        
        if (self.cookie_file is None or 
            not os.path.exists(self.cookie_file) or 
            current_time - self.last_creation_time > self.cookie_lifetime):
            
            self.cleanup()
            self.cookie_file = os.path.join(
                self.temp_dir, 
                f'youtube_cookies_{int(current_time)}.txt'
            )
            self.cookie_jar = self._create_cookie_jar()
            self.cookie_jar.save()
            self.last_creation_time = current_time
            
        return self.cookie_file

    def cleanup(self) -> None:
        if self.cookie_file and os.path.exists(self.cookie_file):
            try:
                os.remove(self.cookie_file)
                self.cookie_file = None
                self.cookie_jar = None
            except Exception as e:
                print(f"Error cleaning up cookie file: {e}")

    def get_yt_dlp_options(self) -> dict:
        return {
            'quiet': False,
            'no_warnings': False,
            'cookiefile': self.get_cookie_file(),
            'extract_flat': True,
            'format': 'bestaudio/best',
            'extractor_args': {
                'youtube': {
                    'player_client': ['ios'],
                    'player_skip': ['webpage', 'config', 'js'],
                    'innertube_client': ['ios'],
                    'skip': ['dash', 'hls'],
                }
            },
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 14_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.1.1 Mobile/15E148 Safari/604.1',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'en-us',
                'Accept-Encoding': 'gzip, deflate',
                'Connection': 'keep-alive',
                'X-YouTube-Client-Name': '2',
                'X-YouTube-Client-Version': '17.42.7',
                'Origin': 'https://m.youtube.com',
                'Referer': 'https://m.youtube.com/'
            },
            'ap_muted': True,
            'prefer_insecure': False,
            'geo_bypass': True,
            'geo_bypass_country': 'US',
            'socket_timeout': 30
        }

    def __del__(self):
        self.cleanup()