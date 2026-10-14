"""
camera_panel.py
PURPOSE: Live webcam feed, snapshot capture, and timelapse recording/export
         for the Camera / IR panel (Row 1, Col 1 in the main 2x2 plot grid).

Hardware: Logitech C920s Pro HD Webcam (UVC plug-and-play, USB-A)
          No special drivers required — OpenCV VideoCapture works out of the box.

Threading model:
  - Background thread (_capture_loop): reads frames from camera continuously,
    stores latest frame under a lock, pushes to a queue for display.
  - Main Tkinter thread: polls queue via after() every 33ms (~30fps) to update
    the video Label. ALL Tkinter calls happen here — never from background threads.
  - Timelapse thread: sleeps 60s between frames, saves JPEG to subfolder.
  - Export thread: stitches frames into MP4 via imageio-ffmpeg after stop.
"""

import importlib.util
import logging
import os
import queue
import threading
import time
import tkinter as tk
from datetime import datetime
from tkinter import messagebox, ttk

logger = logging.getLogger(__name__)


# ── Optional dependency guards ────────────────────────────────────────────────
try:
    import cv2
    CV2_AVAILABLE = True
except ImportError:
    CV2_AVAILABLE = False

try:
    from PIL import Image, ImageTk
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

IMAGEIO_AVAILABLE = bool(
    importlib.util.find_spec("imageio") is not None
    and importlib.util.find_spec("imageio_ffmpeg") is not None
)



class CameraPanel(ttk.Frame):
    """
    Drop-in replacement for the 'Camera / IR — Coming Soon' placeholder in
    main_window._build_plots() (Row 1, Col 1).

    Provides:
      1. Live feed  — 30fps preview displayed in a tk.Label via after() loop
      2. Snapshot   — saves full-resolution JPEG to logs/photos/
      3. Timelapse  — 1 frame/min auto-capture -> MP4 export on stop
    """

    FEED_INTERVAL_MS     = 33    # ~30fps display refresh
    TIMELAPSE_INTERVAL_S = 60    # 1 frame per minute
    CAPTURE_WIDTH        = 1280  # Request 720p from camera (set after open)
    CAPTURE_HEIGHT       = 720

    # ttk style names used for button state animations
    _STYLE_RECORD_DIM      = 'CamRecordDim.TButton'      # timelapse: darker red phase
    _STYLE_RECORD_BRIGHT   = 'CamRecordBright.TButton'   # timelapse: brighter red phase
    _STYLE_SNAP_OK         = 'CamSnapOK.TButton'         # snapshot: success flash (green)
    _STYLE_SNAP_ERR        = 'CamSnapErr.TButton'        # snapshot: error flash (red)
    _PULSE_INTERVAL_MS     = 550                          # ms between timelapse pulse steps
    _SNAP_FLASH_DURATION_MS = 600                         # ms the snapshot flash stays visible

    @classmethod
    def _init_recording_styles(cls):
        """Configure ttk styles used for button animations.
        Safe to call multiple times (ttk.Style is global/idempotent)."""
        try:
            s = ttk.Style()
            # Timelapse: dim phase — deep red
            s.configure(cls._STYLE_RECORD_DIM,
                        background='#b71c1c', foreground='white',
                        bordercolor='#7f0000', darkcolor='#7f0000',
                        lightcolor='#d32f2f')
            s.map(cls._STYLE_RECORD_DIM,
                  background=[('active', '#c62828'), ('pressed', '#7f0000')],
                  foreground=[('active', 'white'), ('pressed', 'white')])
            # Timelapse: bright phase — vivid red
            s.configure(cls._STYLE_RECORD_BRIGHT,
                        background='#ef5350', foreground='white',
                        bordercolor='#b71c1c', darkcolor='#b71c1c',
                        lightcolor='#ff8a80')
            s.map(cls._STYLE_RECORD_BRIGHT,
                  background=[('active', '#e53935'), ('pressed', '#c62828')],
                  foreground=[('active', 'white'), ('pressed', 'white')])
            # Snapshot: success — bright green
            s.configure(cls._STYLE_SNAP_OK,
                        background='#2e7d32', foreground='white',
                        bordercolor='#1b5e20', darkcolor='#1b5e20',
                        lightcolor='#43a047')
            s.map(cls._STYLE_SNAP_OK,
                  background=[('active', '#388e3c'), ('pressed', '#1b5e20')],
                  foreground=[('active', 'white'), ('pressed', 'white')])
            # Snapshot: error — deep red
            s.configure(cls._STYLE_SNAP_ERR,
                        background='#c62828', foreground='white',
                        bordercolor='#7f0000', darkcolor='#7f0000',
                        lightcolor='#ef5350')
            s.map(cls._STYLE_SNAP_ERR,
                  background=[('active', '#b71c1c'), ('pressed', '#7f0000')],
                  foreground=[('active', 'white'), ('pressed', 'white')])
        except Exception as e:
            # Non-clam theme — degrade gracefully without custom active/pressed button map
            logger.debug("Could not configure clam theme styles (%s)", e)


    def __init__(self, parent, log_folder: str, camera_index: int = 0,
                 show_internal_buttons: bool = True, timelapse_interval_s: int = 60,
                 timelapse_export_fps: int = 10,
                 **kwargs):
        super().__init__(parent, **kwargs)

        self._log_folder    = log_folder
        self._camera_index  = camera_index
        self._photos_folder = os.path.join(log_folder, 'photos')
        os.makedirs(self._photos_folder, exist_ok=True)
        self._show_internal_buttons  = show_internal_buttons
        self._timelapse_interval_s   = timelapse_interval_s
        self._timelapse_export_fps   = timelapse_export_fps

        # ── Camera state ──────────────────────────────────────────────────────
        self._cap            = None
        self._capture_thread = None
        self._stop_capture   = threading.Event()
        self._frame_queue    = queue.Queue(maxsize=1)
        self._latest_frame   = None   # numpy BGR array; read with _frame_lock
        self._frame_lock     = threading.Lock()
        self._camera_active  = False
        self._feed_after_id  = None

        # ── Timelapse state ───────────────────────────────────────────────────
        self._timelapse_running     = False
        self._timelapse_folder      = None
        self._timelapse_frame_count = 0
        self._timelapse_start_time  = None
        self._timelapse_thread      = None
        self._timelapse_stop_event  = threading.Event()

        # ── External button refs (status-bar or overlay buttons) ──────────────
        self._ext_snapshot_btn  = None
        self._ext_timelapse_btn = None
        self._overlay_frame     = None

        # ── Recording pulse animation ─────────────────────────────────────────
        self._pulse_after_id = None
        self._pulse_phase    = False   # alternates True/False each tick
        self._init_recording_styles()

        # ── Build UI; camera starts OFF by default ────────────────────────────
        self._build_ui()
        self.grid_propagate(False)  # prevent video frames from resizing the panel
        self._video_label.config(text='Camera off', foreground='gray')

    # ──────────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        """Build video label (fills frame) + optional button row at bottom."""
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)

        # Video display — black background, centred placeholder text
        self._video_label = tk.Label(
            self,
            background='black',
            text='Camera off',
            foreground='gray',
            font=('Arial', 10)
        )
        self._video_label.grid(row=0, column=0, sticky='nsew', padx=2, pady=(2, 1))

        if self._show_internal_buttons:
            self.grid_rowconfigure(1, weight=0)

            btn_frame = ttk.Frame(self)
            btn_frame.grid(row=1, column=0, sticky='ew', padx=2, pady=(0, 2))
            btn_frame.grid_columnconfigure(2, weight=1)

            self._snapshot_btn = ttk.Button(
                btn_frame, text='\U0001f4f7 Snapshot',
                command=self._take_snapshot, state='disabled'
            )
            self._snapshot_btn.grid(row=0, column=0, padx=(0, 4))

            self._timelapse_btn = ttk.Button(
                btn_frame, text='\u23fa Timelapse',
                command=self._toggle_timelapse, state='disabled'
            )
            self._timelapse_btn.grid(row=0, column=1, padx=(0, 4))

            self._status_lbl = ttk.Label(
                btn_frame, text='', foreground='gray', font=('Arial', 8)
            )
            self._status_lbl.grid(row=0, column=2, sticky='w')
        else:
            # Hidden sentinel buttons — never packed; camera logic still
            # calls .config() on them, keeping state for _sync_ext_buttons().
            self._snapshot_btn = ttk.Button(
                self, text='\U0001f4f7 Snapshot',
                command=self._take_snapshot, state='disabled'
            )
            self._timelapse_btn = ttk.Button(
                self, text='\u23fa Timelapse',
                command=self._toggle_timelapse, state='disabled'
            )
            # Status label still attached to the panel but not visible
            self._status_lbl = ttk.Label(
                self, text='', foreground='gray', font=('Arial', 8)
            )

    # ── External button control ────────────────────────────────────────────────

    def register_external_controls(self, snapshot_btn=None, timelapse_btn=None):
        """Register external (status-bar or overlay) buttons to keep in sync."""
        self._ext_snapshot_btn  = snapshot_btn
        self._ext_timelapse_btn = timelapse_btn
        # Immediately sync state in case camera is already ready
        self._sync_ext_buttons()
        # If timelapse is already recording, restart the pulse so the new
        # external button picks up the recording style immediately.
        if self._timelapse_running:
            self._start_recording_pulse()

    def _sync_ext_buttons(self):
        """Mirror internal button state/text onto any registered external buttons."""
        if self._ext_snapshot_btn is not None:
            try:
                self._ext_snapshot_btn.config(state=str(self._snapshot_btn['state']))
            except Exception as e:
                # External snapshot button may be destroyed; sync skipped
                logger.debug("Failed to sync external snapshot button state (%s)", e)
        if self._ext_timelapse_btn is not None:
            try:
                self._ext_timelapse_btn.config(
                    state=str(self._timelapse_btn['state']),
                    text=str(self._timelapse_btn['text'])
                )
            except Exception as e:
                # External timelapse button may be destroyed; sync skipped
                logger.debug("Failed to sync external timelapse button state (%s)", e)

    def _apply_snapshot_btn_style(self, style_name: str):
        """Apply a ttk style to the snapshot button and any registered external counterpart."""
        for btn in (self._snapshot_btn, self._ext_snapshot_btn):
            if btn is not None:
                try:
                    btn.config(style=style_name)
                except Exception as e:
                    # Button style update fallback if widget is destroyed
                    logger.debug("Failed to set snapshot button style (%s)", e)

    def _apply_timelapse_btn_style(self, style_name: str):
        """Apply a ttk style to the timelapse button and any registered external counterpart."""
        for btn in (self._timelapse_btn, self._ext_timelapse_btn):
            if btn is not None:
                try:
                    btn.config(style=style_name)
                except Exception as e:
                    # Button style update fallback if widget is destroyed
                    logger.debug("Failed to set timelapse button style (%s)", e)

    def _start_recording_pulse(self):
        """Start the pulsing red colour animation on the timelapse button."""
        self._stop_recording_pulse()   # cancel any existing pulse first
        self._pulse_phase = False
        self._do_pulse_tick()

    def _do_pulse_tick(self):
        if not self._timelapse_running:
            return
        style = self._STYLE_RECORD_BRIGHT if self._pulse_phase else self._STYLE_RECORD_DIM
        self._pulse_phase = not self._pulse_phase
        self._apply_timelapse_btn_style(style)
        self._pulse_after_id = self.after(self._PULSE_INTERVAL_MS, self._do_pulse_tick)

    def _stop_recording_pulse(self):
        """Cancel the pulse animation and restore the default button style."""
        if self._pulse_after_id is not None:
            try:
                self.after_cancel(self._pulse_after_id)
            except Exception as e:
                # Pulse timer already expired or cancelled
                logger.debug("Failed to cancel pulse timer (%s)", e)
            self._pulse_after_id = None
        self._apply_timelapse_btn_style('TButton')


    def show_overlay_buttons(self):
        """Place snapshot/timelapse buttons as a compact overlay on the panel's bottom-left."""
        if self._overlay_frame is not None:
            return  # already shown
        overlay = ttk.Frame(self)
        self._overlay_snapshot_btn = ttk.Button(
            overlay, text='\U0001f4f7', width=3,
            command=self._take_snapshot, state='disabled'
        )
        self._overlay_snapshot_btn.pack(side=tk.LEFT, padx=(0, 1))
        self._overlay_timelapse_btn = ttk.Button(
            overlay, text='\u23fa', width=3,
            command=self._toggle_timelapse, state='disabled'
        )
        self._overlay_timelapse_btn.pack(side=tk.LEFT)
        overlay.place(relx=0.0, rely=1.0, anchor='sw', x=4, y=-4)
        self._overlay_frame = overlay
        self.register_external_controls(self._overlay_snapshot_btn, self._overlay_timelapse_btn)

    def hide_overlay_buttons(self):
        """Remove overlay buttons if present."""
        if self._overlay_frame is not None:
            self._overlay_frame.place_forget()
            self._overlay_frame.destroy()
            self._overlay_frame = None
            self._ext_snapshot_btn  = None
            self._ext_timelapse_btn = None

    def change_camera_index(self, new_index: int):
        """Stop the current camera and re-open with *new_index*."""
        if new_index == self._camera_index and self._camera_active:
            return
        self._camera_index = new_index
        # Tear down current stream
        self._camera_active = False
        if self._feed_after_id is not None:
            try:
                self.after_cancel(self._feed_after_id)
            except Exception as e:
                # Feed timer already expired or cancelled
                logger.debug("Failed to cancel feed timer (%s)", e)
            self._feed_after_id = None

        self._stop_capture.set()
        if self._capture_thread is not None:
            self._capture_thread.join(timeout=2.0)
            self._capture_thread = None
        if self._cap is not None:
            self._cap.release()
            self._cap = None
        # Disable buttons during re-init
        self._snapshot_btn.config(state='disabled')
        self._timelapse_btn.config(state='disabled')
        self._sync_ext_buttons()
        self._video_label.config(text='Switching camera...', image='', foreground='gray')
        self._stop_capture.clear()
        self.after(200, self._init_camera)

    def _show_dependency_error(self):
        missing = []
        if not CV2_AVAILABLE:
            missing.append('opencv-python')
        if not PIL_AVAILABLE:
            missing.append('pillow')
        self._video_label.config(
            text=f"Camera unavailable.\nMissing: {', '.join(missing)}\n"
                 f"Run: pip install {' '.join(missing)}",
            foreground='red'
        )

    def _init_camera(self):
        """Open the camera device and start the capture thread (main thread)."""
        if not CV2_AVAILABLE or not PIL_AVAILABLE:
            self._show_dependency_error()
            return

        try:
            self._cap = cv2.VideoCapture(self._camera_index, cv2.CAP_DSHOW)
            if not self._cap.isOpened():
                self._video_label.config(
                    text=f'No camera detected (index {self._camera_index}).\n'
                         'Connect the Logitech C920s and restart.',
                    foreground='orange'
                )
                return

            # Resolution MUST be set after open — C920s requirement
            self._cap.set(cv2.CAP_PROP_FRAME_WIDTH,  self.CAPTURE_WIDTH)
            self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.CAPTURE_HEIGHT)

            self._camera_active = True
            self._stop_capture.clear()

            self._capture_thread = threading.Thread(
                target=self._capture_loop, daemon=True, name='CameraCapture'
            )
            self._capture_thread.start()

            self._snapshot_btn.config(state='normal')
            self._timelapse_btn.config(state='normal')
            self._sync_ext_buttons()
            self._schedule_feed_update()

            actual_w = int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            actual_h = int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            logger.info("Camera opened index=%s @ %sx%s", self._camera_index, actual_w, actual_h)

        except Exception as exc:
            self._video_label.config(
                text=f'Camera error:\n{exc}', foreground='red'
            )
            logger.error("Camera init error: %s", exc)

    def _capture_loop(self):
        """
        Background thread: reads frames as fast as the camera produces them.
        Stores the latest frame for snapshot/timelapse; pushes to display queue.
        Never touches Tkinter.
        """
        while not self._stop_capture.is_set():
            if self._cap is None or not self._cap.isOpened():
                time.sleep(0.1)
                continue

            ret, frame = self._cap.read()
            if not ret:
                time.sleep(0.05)
                continue

            with self._frame_lock:
                self._latest_frame = frame  # keep reference, not a copy (fast)

            # Drop old frame if queue is full — display always gets freshest frame
            try:
                self._frame_queue.put_nowait(frame)
            except queue.Full as e:
                # Frame queue full; drop current frame so display thread catches up
                logger.debug("Camera frame queue full; frame dropped (%s)", e)


    def _schedule_feed_update(self):
        if self._camera_active:
            self._feed_after_id = self.after(self.FEED_INTERVAL_MS, self._update_feed)

    def _update_feed(self):
        """Main-thread: pull latest frame from queue and update video label."""
        if not self._camera_active:
            return

        try:
            frame = self._frame_queue.get_nowait()
        except queue.Empty:
            self._schedule_feed_update()
            return

        try:
            w = self._video_label.winfo_width()
            h = self._video_label.winfo_height()
            if w < 10 or h < 10:
                w, h = 320, 240   # fallback before widget is sized

            fh, fw = frame.shape[:2]
            scale  = min(w / fw, h / fh)
            nw     = max(1, int(fw * scale))
            nh     = max(1, int(fh * scale))

            resized  = cv2.resize(frame, (nw, nh), interpolation=cv2.INTER_LINEAR)
            rgb      = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)
            pil_img  = Image.fromarray(rgb)
            tk_img   = ImageTk.PhotoImage(image=pil_img)

            self._video_label.config(image=tk_img, text='')
            self._video_label.image = tk_img   # MUST hold reference to prevent GC

        except Exception as exc:
            logger.error("Camera feed update error: %s", exc)

        self._schedule_feed_update()

    def _take_snapshot(self):
        """Save the current full-resolution frame as a JPEG to photos folder."""
        with self._frame_lock:
            frame = self._latest_frame.copy() if self._latest_frame is not None else None
        if frame is None:
            self._set_status('No frame available', 'red')
            self._apply_snapshot_btn_style(self._STYLE_SNAP_ERR)
            self.after(self._SNAP_FLASH_DURATION_MS,
                       lambda: self._apply_snapshot_btn_style('TButton'))
            return

        # Disable button during write to prevent double-click
        self._snapshot_btn.config(state='disabled')
        if self._ext_snapshot_btn is not None:
            try:
                self._ext_snapshot_btn.config(state='disabled')
            except Exception as e:
                # External snapshot button may be destroyed; state update skipped
                logger.debug("Failed to disable external snapshot button (%s)", e)

        ts   = datetime.now().strftime('%Y%m%d_%H%M%S')
        path = os.path.join(self._photos_folder, f'snapshot_{ts}.jpg')
        try:
            cv2.imwrite(path, frame, [cv2.IMWRITE_JPEG_QUALITY, 95])
            self._set_status(f'Snapshot saved: snapshot_{ts}.jpg', 'green')
            logger.info("Camera snapshot saved: %s", path)
            flash_style = self._STYLE_SNAP_OK
        except Exception as exc:
            self._set_status(f'Snapshot failed: {exc}', 'red')
            logger.error("Camera snapshot error: %s", exc)
            flash_style = self._STYLE_SNAP_ERR

        # Show flash colour, then restore normal state after the flash duration
        self._apply_snapshot_btn_style(flash_style)
        self.after(self._SNAP_FLASH_DURATION_MS, self._revert_snapshot_btn)

    def _revert_snapshot_btn(self):
        """Restore the snapshot button to its normal enabled state after a flash."""
        self._apply_snapshot_btn_style('TButton')
        self._snapshot_btn.config(state='normal')
        if self._ext_snapshot_btn is not None:
            try:
                self._ext_snapshot_btn.config(state='normal')
            except Exception as e:
                # External snapshot button may be destroyed; state update skipped
                logger.debug("Failed to enable external snapshot button (%s)", e)


    def _set_status(self, text: str, color: str = 'gray'):
        self._status_lbl.config(text=text, foreground=color)

    def _toggle_timelapse(self):
        if self._timelapse_running:
            self._stop_timelapse()
        else:
            self._start_timelapse()

    def _start_timelapse(self):
        """Create session folder, take first frame, start timer thread."""
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        self._timelapse_folder      = os.path.join(self._photos_folder, f'timelapse_{ts}')
        self._timelapse_frame_count = 0
        self._timelapse_start_time  = datetime.now()
        self._timelapse_running     = True
        os.makedirs(self._timelapse_folder, exist_ok=True)

        self._timelapse_btn.config(text='\u23f9 Stop & Export')
        self._sync_ext_buttons()
        self._start_recording_pulse()
        ivl = self._timelapse_interval_s
        ivl_str = f'{ivl}s' if ivl < 60 else (f'{ivl // 60}min' if ivl % 60 == 0 else f'{ivl}s')
        self._set_status(f'Timelapse recording... (1 frame/{ivl_str})', 'orange')

        # Capture frame 1 immediately so the folder is not empty on short runs
        self._capture_timelapse_frame()

        # Start timer thread
        self._timelapse_stop_event.clear()
        self._timelapse_thread = threading.Thread(
            target=self._timelapse_loop, daemon=True, name='TimelapseTimer'
        )
        self._timelapse_thread.start()
        logger.info("Camera timelapse started: %s", self._timelapse_folder)

    def _timelapse_loop(self):
        """
        Background thread: wait TIMELAPSE_INTERVAL_S seconds, capture,
        repeat until stop event is set. Uses 0.1s sleep increments so the
        thread responds to stop quickly without polling overhead.
        """
        ticks = self._timelapse_interval_s * 10   # 0.1s increments
        while not self._timelapse_stop_event.is_set():
            for _ in range(ticks):
                if self._timelapse_stop_event.is_set():
                    return
                time.sleep(0.1)
            if self._timelapse_stop_event.is_set():
                return
            self._capture_timelapse_frame()
            count   = self._timelapse_frame_count
            elapsed = int((datetime.now() - self._timelapse_start_time).total_seconds() / 60)
            self.after(0, lambda c=count, e=elapsed:
                       self._set_status(f'Timelapse: {c} frames ({e} min)', 'orange'))

    def _capture_timelapse_frame(self):
        """Save current frame to timelapse folder as zero-padded JPEG."""
        with self._frame_lock:
            frame = self._latest_frame.copy() if self._latest_frame is not None else None
        if frame is None:
            return
        self._timelapse_frame_count += 1
        path = os.path.join(
            self._timelapse_folder,
            f'frame_{self._timelapse_frame_count:04d}.jpg'
        )
        try:
            cv2.imwrite(path, frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
        except Exception as exc:
            logger.error("Camera timelapse frame error: %s", exc)

    def _stop_timelapse(self):
        """Stop recording and launch MP4 export in a background thread."""
        if not self._timelapse_running:
            return
        self._timelapse_running = False
        self._timelapse_stop_event.set()

        self._stop_recording_pulse()
        self._timelapse_btn.config(state='disabled', text='Exporting...')
        self._sync_ext_buttons()
        n = self._timelapse_frame_count
        self._set_status(f'Stitching {n} frames into MP4...', 'blue')

        export_thread = threading.Thread(
            target=self._export_timelapse_thread,
            daemon=True, name='TimelapseExport'
        )
        export_thread.start()

    def _export_timelapse_thread(self):
        """
        Background: sort JPEG frames -> write H.264 MP4 via imageio-ffmpeg.
        10fps gives ~30s video for a 5h run (300 frames), well under 50MB.
        Uses after(0, callback) to update UI on completion.
        """
        try:
            if not IMAGEIO_AVAILABLE:
                raise ImportError(
                    "imageio and imageio-ffmpeg are required.\n"
                    "Run: pip install imageio imageio-ffmpeg"
                )
            import imageio

            frame_files = sorted([
                os.path.join(self._timelapse_folder, f)
                for f in os.listdir(self._timelapse_folder)
                if f.startswith('frame_') and f.endswith('.jpg')
            ])

            if not frame_files:
                raise ValueError("No timelapse frames found in folder.")

            ts_tag   = os.path.basename(self._timelapse_folder).replace('timelapse_', '')
            out_path = os.path.join(self._photos_folder, f'timelapse_{ts_tag}.mp4')
            n_frames = len(frame_files)

            # H.264, yuv420p (required for broad player compatibility),
            # quality=8 (~CRF 20), macro_block_size=16 avoids dimension errors.
            export_fps = max(1, self._timelapse_export_fps)
            with imageio.get_writer(
                out_path,
                fps=export_fps,
                quality=8,
                codec='libx264',
                pixelformat='yuv420p',
                macro_block_size=16
            ) as writer:
                for i, fpath in enumerate(frame_files):
                    writer.append_data(imageio.imread(fpath))
                    if i % 10 == 0:
                        pct = int((i + 1) / n_frames * 100)
                        self.after(0, lambda p=pct:
                                   self._set_status(f'Exporting... {p}%', 'blue'))

            out_name = os.path.basename(out_path)
            self.after(0, lambda: self._on_export_done(out_path, out_name, n_frames, None))

        except Exception as exc:
            self.after(0, lambda e=str(exc): self._on_export_done(None, None, 0, e))

    def _on_export_done(self, out_path, out_name, n_frames, error):
        """Main-thread callback after MP4 export finishes."""
        self._timelapse_btn.config(state='normal', text='\u23fa Timelapse')
        self._sync_ext_buttons()
        if error:
            self._set_status(f'Export failed: {error}', 'red')
            messagebox.showerror('Timelapse Export Error',
                                 f'Failed to create timelapse:\n{error}')
        else:
            self._set_status(f'MP4 saved: {out_name}', 'green')
            logger.info("Camera timelapse exported: %s", out_path)
            export_fps = max(1, self._timelapse_export_fps)
            duration_s = n_frames / export_fps
            messagebox.showinfo(
                'Timelapse Complete',
                f'Timelapse saved to:\n{out_path}\n\n'
                f'Frames captured: {n_frames}\n'
                f'Duration: {duration_s:.0f}s @ {export_fps} fps'
            )

    def toggle_feed(self) -> bool:
        """
        Start or stop the live camera feed without destroying the widget.

        Returns True if the camera is now starting, False if it has been stopped.
        Designed to be called from the main thread (it schedules _init_camera via after()).
        """
        if self._camera_active:
            # --- Stop ---
            if self._timelapse_running:
                self._stop_timelapse()

            self._camera_active = False
            if self._feed_after_id is not None:
                try:
                    self.after_cancel(self._feed_after_id)
                except Exception as e:
                    # Feed timer already cancelled or widget destroyed
                    logger.debug("Failed to cancel feed timer on camera stop (%s)", e)
                self._feed_after_id = None

            self._stop_capture.set()
            if self._capture_thread is not None:
                self._capture_thread.join(timeout=2.0)
                self._capture_thread = None
            if self._cap is not None:
                self._cap.release()
                self._cap = None

            self._snapshot_btn.config(state='disabled')
            self._timelapse_btn.config(state='disabled')
            self._sync_ext_buttons()
            self._video_label.config(text='Camera off', image='', foreground='gray')
            self._stop_capture.clear()
            return False
        else:
            # --- Start ---
            self._video_label.config(text='Starting camera...', image='', foreground='gray')
            self.after(100, self._init_camera)
            return True

    def stop_camera(self):
        """
        Gracefully stop timelapse, display loop, capture thread, and release
        the camera handle. Call from the main thread before destroying the widget
        (e.g. in _on_close).
        """
        # Stop timelapse timer if running
        self._timelapse_running = False
        self._timelapse_stop_event.set()
        self._stop_recording_pulse()

        # Cancel the display loop
        self._camera_active = False
        if self._feed_after_id is not None:
            try:
                self.after_cancel(self._feed_after_id)
            except Exception as e:
                # Feed timer already cancelled or widget destroyed
                logger.debug("Failed to cancel feed timer in stop_camera (%s)", e)
            self._feed_after_id = None


        # Stop capture thread
        self._stop_capture.set()
        if self._capture_thread is not None:
            self._capture_thread.join(timeout=2.0)
            self._capture_thread = None

        # Release camera handle
        if self._cap is not None:
            self._cap.release()
            self._cap = None

        logger.info("Camera stopped and released")
