"""
Detailed profiler for MainWindow initialization debugging.
Tracks every major operation to identify bottlenecks.
"""

import time
import sys
import os

class DetailedProfiler:
    def __init__(self, name="ProfilerSession"):
        self.name = name
        self.start_time = time.time()
        self.last_time = self.start_time
        self.enabled = True
        self.logs = []

    def checkpoint(self, message: str):
        """Log a timing checkpoint"""
        if not self.enabled:
            return

        current_time = time.time()
        elapsed_ms = (current_time - self.start_time) * 1000
        delta_ms = (current_time - self.last_time) * 1000

        # Flag operations over 100ms as potentially slow
        is_slow = delta_ms > 100.0
        slow_marker = "[SLOW!] " if is_slow else ""

        log_line = f"{slow_marker}{elapsed_ms:.1f}ms (+{delta_ms:.1f}ms) {message}"
        print(log_line)
        sys.stdout.flush()

        self.logs.append({
            'message': message,
            'elapsed_ms': elapsed_ms,
            'delta_ms': delta_ms,
            'is_slow': is_slow
        })

        self.last_time = current_time

    def section(self, section_name: str):
        """Mark a section boundary"""
        self.checkpoint(f"{'='*60}")
        self.checkpoint(f"SECTION: {section_name}")
        self.checkpoint(f"{'='*60}")

    def summary(self):
        """Print summary of slowest operations"""
        if not self.logs:
            return

        print("\n" + "="*80)
        print("DETAILED PROFILER SUMMARY - TOP 10 SLOWEST OPERATIONS")
        print("="*80)

        sorted_logs = sorted(self.logs, key=lambda x: x['delta_ms'], reverse=True)[:10]
        for i, log in enumerate(sorted_logs, 1):
            print(f"{i}. {log['delta_ms']:.1f}ms - {log['message']}")

        print("="*80)

        # Save to file
        self._save_to_file()

    def _save_to_file(self):
        """Save detailed log to file for analysis"""
        try:
            if getattr(sys, 'frozen', False):
                base_dir = os.path.dirname(sys.executable)
            else:
                base_dir = os.getcwd()

            log_path = os.path.join(base_dir, "detailed_startup_profile.txt")

            with open(log_path, 'w') as f:
                f.write(f"DETAILED PROFILER: {self.name}\n")
                f.write("="*80 + "\n\n")

                for log in self.logs:
                    marker = "[SLOW!] " if log['is_slow'] else ""
                    f.write(f"{marker}{log['elapsed_ms']:.1f}ms "
                           f"(+{log['delta_ms']:.1f}ms) {log['message']}\n")

            print(f"\n[PROFILER] Detailed log saved to: {log_path}\n")
        except Exception as e:
            print(f"[PROFILER] Warning: Could not save log file: {e}")

# Global instance for MainWindow profiling
mainwindow_profiler = DetailedProfiler("MainWindow Initialization")
