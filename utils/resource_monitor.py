import psutil
import threading
import time
import logging

logger = logging.getLogger('music_bot')

class ResourceMonitor:
    def __init__(self, warning_cpu_percent=70, warning_memory_percent=70):
        self.warning_cpu_percent = warning_cpu_percent
        self.warning_memory_percent = warning_memory_percent
        self._stop_event = threading.Event()
        self._monitor_thread = None

    def start(self):
        """Start monitoring resources."""
        self._monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._monitor_thread.start()

    def stop(self):
        """Stop monitoring resources."""
        self._stop_event.set()
        if self._monitor_thread:
            self._monitor_thread.join()

    def _monitor_loop(self):
        """Monitor system resources."""
        while not self._stop_event.is_set():
            try:
                cpu_percent = psutil.cpu_percent(interval=1)
                memory_percent = psutil.virtual_memory().percent

                if cpu_percent > self.warning_cpu_percent:
                    logger.warning(f"High CPU usage detected: {cpu_percent}%")

                if memory_percent > self.warning_memory_percent:
                    logger.warning(f"High memory usage detected: {memory_percent}%")

                # Check for specific process resources
                process = psutil.Process()
                with process.oneshot():
                    cpu_percent = process.cpu_percent()
                    memory_info = process.memory_info()
                    
                    if cpu_percent > self.warning_cpu_percent:
                        logger.warning(f"Process CPU usage high: {cpu_percent}%")
                    
                    if memory_info.rss > 500 * 1024 * 1024:  # 500MB
                        logger.warning(f"Process memory usage high: {memory_info.rss / 1024 / 1024:.2f}MB")

            except Exception as e:
                logger.error(f"Error in resource monitor: {e}")

            time.sleep(5)  # Check every 5 seconds