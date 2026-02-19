"""
keysight_background_monitor.py
PURPOSE: Background thread for Keysight power supply communication
FLOW: Run in separate thread -> Poll hardware continuously -> Cache results for GUI thread
BENEFIT: GUI thread gets instant cached data instead of blocking on 400ms hardware reads
"""

import threading
import time


class KeysightBackgroundMonitor:
    """Handles Keysight communication in a separate thread"""

    def __init__(self, keysight_connection):
        self.keysight = keysight_connection
        self.running = False
        self.thread = None

        # Store latest values that GUI can read quickly
        self.latest_voltage = None
        self.latest_current = None
        self.latest_output_state = None
        self.latest_error = None
        self.last_update_time = 0

        # Thread-safe lock for reading/writing data
        self.lock = threading.Lock()

    def start(self):
        """Start the background monitoring thread"""
        self.running = True
        self.thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self.thread.start()

    def stop(self):
        """Stop the background thread"""
        self.running = False
        if self.thread:
            self.thread.join(timeout=2.0)

    def _monitor_loop(self):
        """This runs in the background thread - talks to hardware"""
        backoff = 0.5
        max_backoff = 10.0

        while self.running:
            try:
                # Acquire the VISA lock to prevent interleaving with other threads
                with self.keysight.visa_lock:
                    instrument = self.keysight.get_instrument()
                    if instrument is None:
                        with self.lock:
                            self.latest_error = "Not connected"
                        self.keysight.mark_disconnected()
                        time.sleep(backoff)
                        backoff = min(backoff * 2, max_backoff)
                        continue

                    voltage = float(instrument.query("MEAS:VOLT?").strip())
                    current = float(instrument.query("MEAS:CURR?").strip())
                    output_state = instrument.query("OUTP?").strip() == "1"

                # Update the latest values (thread-safe via data lock)
                with self.lock:
                    self.latest_voltage = voltage
                    self.latest_current = current
                    self.latest_output_state = output_state
                    self.latest_error = None
                    self.last_update_time = time.time()

                # Communication succeeded - mark connected and reset backoff
                self.keysight.mark_connected()
                backoff = 0.5

            except Exception as e:
                with self.lock:
                    self.latest_error = str(e)
                self.keysight.mark_disconnected()
                # Exponential backoff on error
                time.sleep(backoff)
                backoff = min(backoff * 2, max_backoff)
                continue

            # Normal polling interval
            time.sleep(0.5)

    def get_latest_data(self):
        """GUI calls this - returns instantly with cached data"""
        with self.lock:
            return {
                'voltage': self.latest_voltage,
                'current': self.latest_current,
                'output_state': self.latest_output_state,
                'error': self.latest_error,
                'age': time.time() - self.last_update_time
            }
