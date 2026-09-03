#!/usr/bin/env python3
"""
camera.py -- open a camera and hold its optics still.

    python camera.py                     # list cameras, show a preview
    python camera.py --index 1 --lock    # lock focus+exposure, report what took

Metric vision needs the optics to stop moving. Autofocus changes the intrinsics
continuously, so a calibration taken at one focus is meaningless at another --
the symptom is results that drift for no visible reason, and it is worth a day
of confusion if you do not know to look for it.

The catch is that Windows camera drivers accept a property write, return
success, and silently ignore it. So every setting here is written, read back,
and reported as what the driver *actually* did. Never trust `set()`'s return
value on Windows -- see `Locked.ok`.

RealSense is supported through the same interface (`--realsense`) so the rest
of the pipeline does not care which camera it is looking through.
"""

import argparse
import os
import platform
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass, field

import cv2

# On Windows, DirectShow honours far more property writes than MSMF, which is
# what OpenCV picks by default. MSMF also opens slowly on some laptop webcams.
DEFAULT_BACKEND = cv2.CAP_DSHOW if platform.system() == "Windows" else cv2.CAP_ANY

# DSHOW encodes auto-exposure as 0.75 = auto, 0.25 = manual. This is a
# long-standing OpenCV quirk, not a documented API.
DSHOW_EXPOSURE_AUTO = 0.75
DSHOW_EXPOSURE_MANUAL = 0.25

# DSHOW exposure is log2 seconds: -6 is 1/64 s, -10 is 1/1024 s. Searched
# bright-to-dark when we have to find a working value ourselves.
DSHOW_EXPOSURE_STEPS = [-4, -5, -6, -7, -8, -9, -10, -11]

# Mean grey level below which a frame is too dark to calibrate or detect from.
DARK_MEAN = 40.0
TARGET_MEAN = 110.0

# Sharpness coefficient of variation under which a lens counts as not hunting.
FOCUS_STABLE_CV = 0.06


@dataclass
class Locked:
    """What the driver actually accepted, as opposed to what we asked for."""
    autofocus_off: bool = False
    focus: float | None = None
    autoexposure_off: bool = False
    exposure: float | None = None
    notes: list = field(default_factory=list)

    brightness: float | None = None
    focus_cv: float | None = None      # sharpness variation, when measured

    @property
    def ok(self):
        """True if the camera is usable for metric work.

        This is about **focus only**. Focus changes the intrinsics, so a
        calibration taken at one focus stops being true at another. Exposure
        does not move a single pixel geometrically -- it only affects image
        quality and motion blur, so a well-exposed auto frame is worth more
        than a pinned dark one. Exposure is reported, not required.
        """
        return self.autofocus_off

    def report(self):
        af = "locked" if self.autofocus_off else "STILL AUTO"
        ae = "locked" if self.autoexposure_off else "auto (fine for geometry)"
        lines = [f"  focus:    {af}"
                 + (f" (value {self.focus})" if self.focus is not None else ""),
                 f"  exposure: {ae}"
                 + (f" (value {self.exposure})" if self.exposure is not None else "")]
        if self.brightness is not None:
            flag = "" if self.brightness >= DARK_MEAN else "   <-- TOO DARK"
            lines.append(f"  mean level: {self.brightness:.0f}/255{flag}")
        lines += [f"  ! {n}" for n in self.notes]
        return "\n".join(lines)


class Camera:
    """A camera with optics that hold still, or that says why they do not."""

    def __init__(self, index=0, width=1280, height=720, backend=None,
                 realsense=False):
        self.index, self.realsense = index, realsense
        self.want = (width, height)
        self._rs = None
        if realsense:
            self._open_realsense(width, height)
        else:
            self._open_cv(backend if backend is not None else DEFAULT_BACKEND)

    # ---- opening ----------------------------------------------------
    def _open_cv(self, backend):
        self.cap = cv2.VideoCapture(self.index, backend)
        if not self.cap.isOpened():
            raise RuntimeError(
                f"could not open camera {self.index}. "
                f"Try a different --index, or --backend msmf.")
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.want[0])
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.want[1])

    def _open_realsense(self, width, height):
        try:
            import pyrealsense2 as rs
        except ImportError:
            raise RuntimeError(
                "pyrealsense2 is not installed -- `pip install pyrealsense2`, "
                "or drop --realsense to use a UVC camera")
        self._rs = rs
        self.pipe = rs.pipeline()
        cfg = rs.config()
        cfg.enable_stream(rs.stream.color, width, height, rs.format.bgr8, 30)
        self.pipe.start(cfg)

    # ---- the size the driver actually gave us ------------------------
    @property
    def size(self):
        """Actual (w, h). Drivers substitute a supported mode without saying."""
        if self.realsense:
            return self.want
        return (int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
                int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT)))

    # ---- holding the optics still ------------------------------------
    def lock(self, focus=None, exposure=None):
        """Pin focus and exposure. Returns what the driver actually did."""
        got = Locked()
        if self.realsense:
            # The D4xx colour sensor is fixed-focus, so there is nothing to
            # pin; only auto-exposure can wander.
            got.autofocus_off = True
            got.notes.append("RealSense colour is fixed-focus")
            try:
                s = self.pipe.get_active_profile().get_device() \
                        .query_sensors()[1]
                s.set_option(self._rs.option.enable_auto_exposure, 0)
                got.autoexposure_off = True
                if exposure is not None:
                    s.set_option(self._rs.option.exposure, exposure)
                    got.exposure = exposure
            except Exception as e:                      # noqa: BLE001
                got.notes.append(f"could not lock RS exposure: {e}")
            self._settle(4)
            got.brightness = self.mean_level()
            return got

        # Webcams stream dark for the first few hundred ms after opening, so
        # anything measured immediately describes the ramp, not the camera.
        self._settle(15)

        # --- autofocus. Written, then read back, because a driver that does
        #     not support it still returns True from set().
        self.cap.set(cv2.CAP_PROP_AUTOFOCUS, 0)
        af = self.cap.get(cv2.CAP_PROP_AUTOFOCUS)
        got.autofocus_off = (af == 0)
        if af == -1:
            # Ambiguous: no control exposed. Decide by watching the picture.
            cv = self.focus_stability()
            got.focus_cv = cv
            if cv is None:
                got.notes.append("AUTOFOCUS not exposed and sharpness could "
                                 "not be measured")
            elif cv < FOCUS_STABLE_CV:
                got.autofocus_off = True
                got.notes.append(
                    f"AUTOFOCUS not exposed, but sharpness is steady "
                    f"(cv {cv*100:.1f}%) -- reads as a fixed-focus lens, so "
                    f"there is nothing to pin. Safe to calibrate.")
            else:
                got.notes.append(
                    f"AUTOFOCUS not exposed AND sharpness varies "
                    f"(cv {cv*100:.1f}%) -- the lens is hunting and cannot be "
                    f"stopped. Do not calibrate this camera.")
        if focus is not None:
            self.cap.set(cv2.CAP_PROP_FOCUS, focus)
            got.focus = self.cap.get(cv2.CAP_PROP_FOCUS)

        # --- exposure.
        # Switching to manual without supplying a value leaves the driver on
        # its manual default, which is usually a very short exposure -- the
        # image goes black and it looks like the camera broke. So: let auto
        # settle on this scene, take the value it chose, and pin that.
        if exposure is None:
            self.cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, DSHOW_EXPOSURE_AUTO)
            self._settle(12)
            exposure = self.cap.get(cv2.CAP_PROP_EXPOSURE)

        self.cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, DSHOW_EXPOSURE_MANUAL)
        ae = self.cap.get(cv2.CAP_PROP_AUTO_EXPOSURE)
        got.autoexposure_off = (ae != DSHOW_EXPOSURE_AUTO)
        if exposure is not None:
            self.cap.set(cv2.CAP_PROP_EXPOSURE, exposure)
        self._settle(4)
        got.exposure = self.cap.get(cv2.CAP_PROP_EXPOSURE)
        got.brightness = self.mean_level()

        # Some drivers report a converged value that means nothing in manual
        # mode. Judge the picture, not the property.
        if got.autoexposure_off and got.brightness < DARK_MEAN:
            found, level = self._search_exposure()
            if found is not None:
                self.cap.set(cv2.CAP_PROP_EXPOSURE, found)
                self._settle(3)
                got.exposure, got.brightness = found, self.mean_level()
                got.notes.append(
                    f"driver's manual default was dark; searched and used "
                    f"exposure {found}")
            else:
                # A usable picture beats a pinned one: exposure is not part of
                # the camera model, so leaving it on auto costs no geometry.
                self.cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, DSHOW_EXPOSURE_AUTO)
                self._settle(15)
                got.autoexposure_off = False
                got.exposure = None      # no manual value is in effect
                got.brightness = self.mean_level()
                got.notes.append(
                    "this driver ignores manual exposure -- left on AUTO. "
                    "Geometry is unaffected; only frame-to-frame consistency "
                    "suffers, so avoid changing the lighting mid-calibration.")

        # A locked camera should produce identical frames of a static scene.
        # Cheap empirical check -- believe this over the property values.
        if not self._frames_stable():
            got.notes.append("frames still changing on a static scene -- "
                             "something is still adapting")
        return got

    def _settle(self, n=8):
        """Grab and discard n frames so a property change takes effect."""
        for _ in range(n):
            self.read()
            time.sleep(0.03)

    def mean_level(self, n=3):
        """Mean grey level, 0-255. The honest test of 'is this too dark'."""
        import numpy as np
        vals = []
        for _ in range(n):
            ok, f = self.read()
            if ok:
                vals.append(float(np.mean(cv2.cvtColor(f, cv2.COLOR_BGR2GRAY))))
            time.sleep(0.02)
        return sum(vals) / len(vals) if vals else 0.0

    def _search_exposure(self, target=TARGET_MEAN):
        """Sweep manual exposure for the value closest to a usable level.

        Settles generously between candidates: this webcam streams dark for
        the first few hundred ms after any change, so a short settle measures
        the ramp rather than the setting and reports every value as too dark.
        """
        best, best_level, best_err = None, 0.0, float("inf")
        seen = []
        for e in DSHOW_EXPOSURE_STEPS:
            self.cap.set(cv2.CAP_PROP_EXPOSURE, e)
            self._settle(15)
            level = self.mean_level(3)
            seen.append(level)
            if abs(level - target) < best_err:
                best, best_level, best_err = e, level, abs(level - target)
            if level > target * 1.6:        # already overexposed; darker only
                break
            # If several very different exposures produce the same picture,
            # the driver is ignoring the property. Stop probing it.
            if len(seen) >= 3 and (max(seen) - min(seen)) < 2.0:
                return None, best_level
        return (best, best_level) if best_level >= DARK_MEAN else (None, best_level)

    def focus_stability(self, n=20, gap=0.08):
        """Coefficient of variation of image sharpness, on a STATIC scene.

        The AUTOFOCUS property returning -1 is ambiguous: it means the driver
        does not expose the control, which covers both "fixed-focus lens, so
        there is nothing to control" (fine -- calibrate away) and "autofocus
        that we cannot switch off" (useless for metric work). The property
        cannot distinguish them; the picture can. A lens that hunts changes
        Laplacian variance; a fixed lens does not.

        Only meaningful if nothing in front of the camera moves while it runs.
        """
        import numpy as np
        sharp = []
        for _ in range(n):
            ok, f = self.read()
            if ok:
                g = cv2.cvtColor(f, cv2.COLOR_BGR2GRAY)
                sharp.append(float(cv2.Laplacian(g, cv2.CV_64F).var()))
            time.sleep(gap)
        if len(sharp) < 4:
            return None
        m = sum(sharp) / len(sharp)
        if m <= 0:
            return None
        sd = float(np.std(sharp))
        return sd / m

    def _frames_stable(self, n=8, tol=1.5):
        """Mean abs difference between consecutive frames of a still scene."""
        import numpy as np
        prev, diffs = None, []
        for _ in range(n):
            ok, f = self.read()
            if not ok:
                return True                    # not our problem to report here
            g = cv2.cvtColor(f, cv2.COLOR_BGR2GRAY)
            if prev is not None:
                diffs.append(float(np.mean(cv2.absdiff(g, prev))))
            prev = g
            time.sleep(0.03)
        return bool(diffs) and (sum(diffs) / len(diffs)) < tol

    # ---- frames -------------------------------------------------------
    def read(self):
        if self.realsense:
            frames = self.pipe.wait_for_frames()
            c = frames.get_color_frame()
            if not c:
                return False, None
            import numpy as np
            return True, np.asanyarray(c.get_data())
        return self.cap.read()

    def close(self):
        if self.realsense:
            try:
                self.pipe.stop()
            except Exception:                            # noqa: BLE001
                pass
        else:
            self.cap.release()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


@contextmanager
def _quiet_native_stderr():
    """Silence OpenCV's C++ logging for the duration of the block.

    Probing a camera index that does not exist makes the backend print a
    warning straight to native stderr, which buries the one line you wanted.
    `cv2.setLogLevel` does not exist in every build (it is absent here) and
    OPENCV_LOG_LEVEL is only read at import, so the portable lever is the file
    descriptor itself. Scoped to the scan so real errors still surface.
    """
    try:
        saved = os.dup(2)
    except (AttributeError, OSError):
        yield                                   # no fd to redirect; live with it
        return
    devnull = os.open(os.devnull, os.O_WRONLY)
    try:
        sys.stderr.flush()
        os.dup2(devnull, 2)
        yield
    finally:
        sys.stderr.flush()
        os.dup2(saved, 2)
        os.close(devnull)
        os.close(saved)


def list_cameras(limit=6):
    """Indices that actually yield a frame. Opening alone is not proof."""
    found = []
    with _quiet_native_stderr():
        for i in range(limit):
            cap = cv2.VideoCapture(i, DEFAULT_BACKEND)
            if cap.isOpened():
                ok, _ = cap.read()
                if ok:
                    found.append((i, int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
                                  int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))))
            cap.release()
    return found


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--index", type=int, default=0)
    p.add_argument("--width", type=int, default=1280)
    p.add_argument("--height", type=int, default=720)
    p.add_argument("--realsense", action="store_true")
    p.add_argument("--lock", action="store_true",
                   help="pin focus/exposure and report what the driver did")
    p.add_argument("--focus", type=float, default=None)
    p.add_argument("--exposure", type=float, default=None)
    p.add_argument("--list", action="store_true", help="list cameras and exit")
    args = p.parse_args()

    if args.list:
        for i, w, h in list_cameras():
            print(f"  camera {i}: {w}x{h}")
        return

    with Camera(args.index, args.width, args.height,
                realsense=args.realsense) as cam:
        print(f"opened camera {args.index}: requested {args.width}x{args.height}, "
              f"got {cam.size[0]}x{cam.size[1]}")
        if args.lock:
            got = cam.lock(args.focus, args.exposure)
            print(got.report())
            print("  => focus pinned; safe to calibrate" if got.ok else
                  "  => FOCUS NOT PINNED -- intrinsics will not stay true.\n"
                  "     If this camera hunts focus, use the RealSense instead.")
            if got.brightness is not None and got.brightness < DARK_MEAN:
                print(f"     Image is dark ({got.brightness:.0f}/255). Try "
                      f"--exposure -5 (brighter) .. -9 (darker), or add light.")
        print("q or Esc to quit")
        while True:
            ok, frame = cam.read()
            if not ok:
                print("frame grab failed")
                break
            cv2.imshow("camera", frame)
            if cv2.waitKey(1) & 0xFF in (ord("q"), 27):
                break
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
