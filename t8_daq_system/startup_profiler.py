"""
startup_profiler.py
PURPOSE: Track startup timing to identify PyInstaller bottlenecks
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

    def log(self, event):
        if not self.enabled:
            return
        elapsed = (time.time() - self.start_time) * 1000
        self.checkpoints.append((event, elapsed))
        print(f"[{elapsed:7.1f}ms] {event}")
        sys.stdout.flush()

    def summary(self):
        if not self.enabled or not self.checkpoints:
            return

        print("\n" + "="*80)
        print("STARTUP PERFORMANCE SUMMARY")
        print("="*80)

        total = self.checkpoints[-1][1]
        for i, (event, elapsed) in enumerate(self.checkpoints):
            if i > 0:
                delta = elapsed - self.checkpoints[i-1][1]
                pct = (delta / total * 100) if total > 0 else 0
                flag = " ⚠️ SLOW!" if delta > 1000 else (" ⚠️" if delta > 500 else "")
                print(f"{elapsed:7.1f}ms (+{delta:6.1f}ms {pct:5.1f}%) | {event}{flag}")
            else:
                print(f"{elapsed:7.1f}ms                  | {event}")

        print("="*80)
        print(f"Total: {total:.1f}ms ({total/1000:.2f}s)")
        print("="*80 + "\n")

    def disable(self):
        self.enabled = False

profiler = StartupProfiler()
