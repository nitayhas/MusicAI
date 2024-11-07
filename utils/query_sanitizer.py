import re
from urllib.parse import urlparse
import html
import logging

logger = logging.getLogger('music_bot')

class QuerySanitizer:
    def __init__(self):
        # Common patterns that might indicate malicious input
        self.suspicious_patterns = [
            r'(?i);.*?(?:DROP|DELETE|UPDATE|INSERT|SELECT)\s+.*',  # SQL injection attempts
            r'(?i)<script[\s\S]*?>[\s\S]*?</script>',  # XSS attempts
            r'(?i)javascript:',  # JavaScript injection
            r'(?i)\b(select|insert|update|delete|drop|truncate|alter|exec)\b.*?(?:from|into|table)',  # SQL keywords
            r'(?i)system\([^)]*\)',  # System command execution attempts
            r'(?i)(?:\/\.\.\/|\.\.\/|\.\.\%2f|\.\.%5c)',  # Directory traversal attempts
            r'(?i)(<|>|&lt;|&gt;|&#x3C;|&#x3E;)',  # HTML tags
            r'(?i)\b(union\s+select|union\s+all\s+select)\b',  # SQL UNION attacks
            r'(?i)\b(and|or)\b.+?\b(true|false)\b',  # SQL logical operations
            r'(?i)(\%27|\'|\-\-|\#|\%23)\s*$'  # SQL comment attacks
        ]
        
        # Allowed URL schemes for music
        self.allowed_schemes = ['http', 'https', 'youtube', 'youtu.be']
        
        # Maximum query length
        self.MAX_QUERY_LENGTH = 200

    def sanitize_query(self, query: str, user_id: str = "Unknown") -> tuple[bool, str, str]:
        """
        Sanitizes the input query and checks for potential security issues.
        
        Args:
            query (str): The input query to sanitize
            user_id (str): The Discord user ID for logging purposes
            
        Returns:
            tuple: (is_safe: bool, sanitized_query: str, error_message: str)
        """
        logger.info(f"Starting query sanitization for user {user_id}. Query: {query}")

        # Check if query is None or empty
        if not query or not query.strip():
            logger.warning(f"Empty query received from user {user_id}")
            return False, "", "Query cannot be empty"

        # Check query length
        if len(query) > self.MAX_QUERY_LENGTH:
            logger.warning(f"Query length exceeded maximum ({len(query)} > {self.MAX_QUERY_LENGTH}) from user {user_id}")
            return False, "", f"Query too long (max {self.MAX_QUERY_LENGTH} characters)"

        # Basic sanitization
        sanitized = query.strip()
        sanitized = html.escape(sanitized)  # Convert HTML special characters
        logger.debug(f"Basic sanitization complete. Original: '{query}' -> Sanitized: '{sanitized}'")
        
        # Check for suspicious patterns
        for pattern in self.suspicious_patterns:
            if re.search(pattern, sanitized):
                logger.warning(f"Suspicious pattern detected in query from user {user_id}. Pattern: {pattern}")
                logger.warning(f"Original query: {query}")
                return False, "", "Potentially malicious pattern detected"

        # If it's a URL, validate it
        if any(scheme in sanitized.lower() for scheme in ['http:', 'https:', 'www.']):
            try:
                parsed_url = urlparse(sanitized)
                logger.debug(f"URL validation - Scheme: {parsed_url.scheme}, NetLoc: {parsed_url.netloc}")
                
                if parsed_url.scheme.lower() not in self.allowed_schemes:
                    logger.warning(f"Invalid URL scheme attempted by user {user_id}: {parsed_url.scheme}")
                    return False, "", f"URL scheme not allowed. Allowed schemes: {', '.join(self.allowed_schemes)}"
            except Exception as e:
                logger.error(f"URL parsing error for user {user_id}: {str(e)}")
                return False, "", f"Invalid URL format: {str(e)}"

        # Additional YouTube-specific validation
        if 'youtube.com' in sanitized.lower() or 'youtu.be' in sanitized.lower():
            if not self.is_valid_youtube_url(sanitized):
                logger.warning(f"Invalid YouTube URL format from user {user_id}: {sanitized}")
                return False, "", "Invalid YouTube URL format"
            else:
                logger.info(f"Valid YouTube URL detected: {sanitized}")

        logger.info(f"Query sanitization successful for user {user_id}")
        return True, sanitized, ""

    def is_valid_youtube_url(self, url: str) -> bool:
        """
        Validates if the URL is a proper YouTube URL.
        
        Args:
            url (str): The URL to validate
            
        Returns:
            bool: True if valid YouTube URL, False otherwise
        """
        youtube_patterns = [
            r'^(https?://)?(www\.)?(youtube\.com/watch\?v=[\w-]+)',
            r'^(https?://)?(www\.)?(youtu\.be/[\w-]+)',
            r'^(https?://)?(www\.)?(youtube\.com/playlist\?list=[\w-]+)'
        ]
        
        is_valid = any(re.match(pattern, url) for pattern in youtube_patterns)
        logger.debug(f"YouTube URL validation: {url} -> {'Valid' if is_valid else 'Invalid'}")
        return is_valid
    
query_sanitizer = QuerySanitizer()

# Export the main function to be used by other files
async def sanitize_play_query(query: str, user_id: str) -> tuple[bool, str, str]:
    """
    Wrapper function to sanitize play command queries.
    
    Args:
        query (str): The query to sanitize
        user_id (str): The Discord user ID for logging purposes
        
    Returns:
        tuple: (is_safe: bool, sanitized_query: str, error_message: str)
    """
    return query_sanitizer.sanitize_query(query, user_id)