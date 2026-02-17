"""
startup_profiler.py
PURPOSE: Track startup timing to identify PyInstaller bottlenecks
FIXED: Handle all encoding issues for Windows console
"""

import sys
import time

class StartupProfiler:
    def __init__(self):
        self.start_time = time.time()
        self.checkpoints = []
        self.enabled = True

        is_frozen = getattr(sys, 'frozen', False)
        mode = "FROZEN EXE" if is_frozen else "DEVELOPMENT"
        self.log(f"=== PROFILER ACTIVE ({mode}) ===")

    def _safe_print(self, text):
        """Print text safely, handling encoding errors."""
        try:
            print(text)
        except UnicodeEncodeError:
            # If print fails, encode to ASCII and replace problematic chars
            safe_text = text.encode('ascii', errors='replace').decode('ascii')
            print(safe_text)
        sys.stdout.flush()

    def log(self, event):
        if not self.enabled:
            return
        elapsed = (time.time() - self.start_time) * 1000
        # Sanitize event string to ASCII-safe characters
        safe_event = str(event).encode('ascii', errors='replace').decode('ascii')
        self.checkpoints.append((safe_event, elapsed))
        self._safe_print(f"[{elapsed:7.1f}ms] {safe_event}")

    def summary(self):
        if not self.enabled or not self.checkpoints:
            return

        self._safe_print("\n" + "="*80)
        self._safe_print("STARTUP PERFORMANCE SUMMARY")
        self._safe_print("="*80)

        total = self.checkpoints[-1][1] if self.checkpoints else 0

        for i, (event, elapsed) in enumerate(self.checkpoints):
            if i > 0:
                delta = elapsed - self.checkpoints[i-1][1]
                pct = (delta / total * 100) if total > 0 else 0

                # ASCII-safe flag indicators
                if delta > 1000:
                    flag = " [SLOW]"
                elif delta > 500:
                    flag = " [WARN]"
                else:
                    flag = ""

                line = f"{elapsed:7.1f}ms (+{delta:6.1f}ms {pct:5.1f}%) | {event}{flag}"
                self._safe_print(line)
            else:
                line = f"{elapsed:7.1f}ms                  | {event}"
                self._safe_print(line)

        self._safe_print("="*80)
        self._safe_print(f"Total: {total:.1f}ms ({total/1000:.2f}s)")
        self._safe_print("="*80 + "\n")

    def disable(self):
        self.enabled = False

profiler = StartupProfiler()