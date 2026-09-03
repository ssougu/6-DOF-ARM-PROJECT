#!/usr/bin/env python3
"""
calibrate.py -- camera intrinsics from the ChArUco board.

    python calibrate.py --index 0 --lock      # live capture, SPACE to keep
    python calibrate.py --from-dir shots/     # from saved images
    python calibrate.py --check               # re-check a saved calibration

Writes `intrinsics_<tag>.json`: camera matrix, distortion, image size, the
board it was calibrated against, and the residual. Everything downstream loads
that file, and refuses to run if the image size does not match -- intrinsics
are only valid for the resolution they were measured at, and silently reusing
them at another resolution is a scale error nobody notices.

RealSense colour has usable factory intrinsics (see VISION_APPROACH.md), so
this is mainly for a webcam. It is still worth running once on the RealSense to
have an independent number to compare against.

**Reprojection error is not accuracy.** A low residual means the model fits the
views you gave it. Give it twenty views from one angle and it will fit them
beautifully and generalise badly. Coverage is what matters: tilt the board to
real angles, fill the frame corners, vary distance. This script scores coverage
and will tell you when it is thin.
"""

import argparse
import json
import time
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

from board import make_board, SQUARE_MM, SQUARES_X, SQUARES_Y

MIN_VIEWS = 12
MIN_CORNERS = 8


def detector(square_mm=SQUARE_MM):
    board, d = make_board(square_mm)
    return cv2.aruco.CharucoDetector(board), board


def find(img, det):
    """Charuco corners in one image, or (None, None)."""
    corners, ids, _, _ = det.detectBoard(img)
    if ids is None or len(ids) < MIN_CORNERS:
        return None, None
    return corners, ids


def coverage(all_corners, size):
    """Fraction of a 4x4 grid of the frame that any corner has landed in.

    Cheap proxy for "did you actually move the board around". Distortion is
    largest at the edges, so a calibration fed only centre views constrains the
    coefficients that matter least.
    """
    w, h = size
    hit = set()
    for c in all_corners:
        for pt in c.reshape(-1, 2):
            hit.add((min(3, int(pt[0] / w * 4)), min(3, int(pt[1] / h * 4))))
    return len(hit) / 16.0


def calibrate(all_corners, all_ids, board, size):
    flags = cv2.CALIB_RATIONAL_MODEL
    obj_pts, img_pts = [], []
    for c, i in zip(all_corners, all_ids):
        o, p = board.matchImagePoints(c, i)
        if o is not None and len(o) >= MIN_CORNERS:
            obj_pts.append(o)
            img_pts.append(p)
    if len(obj_pts) < MIN_VIEWS:
        raise RuntimeError(f"only {len(obj_pts)} usable views, need {MIN_VIEWS}")
    rms, K, dist, rvecs, tvecs = cv2.calibrateCamera(
        obj_pts, img_pts, size, None, None, flags=flags)

    # Per-view residual, so one bad view can be spotted instead of being
    # averaged into an innocuous-looking mean.
    per_view = []
    for o, p, r, t in zip(obj_pts, img_pts, rvecs, tvecs):
        proj, _ = cv2.projectPoints(o, r, t, K, dist)
        per_view.append(float(np.sqrt(np.mean(
            np.sum((proj.reshape(-1, 2) - p.reshape(-1, 2)) ** 2, axis=1)))))
    return rms, K, dist, per_view


def save(path, K, dist, size, rms, per_view, square_mm, tag):
    data = {
        "tag": tag,
        "created": datetime.now().isoformat(timespec="seconds"),
        "image_size": [int(size[0]), int(size[1])],
        "camera_matrix": K.tolist(),
        "dist_coeffs": dist.ravel().tolist(),
        "rms_reproj_px": float(rms),
        "per_view_reproj_px": [round(v, 4) for v in per_view],
        "board": {"squares_x": SQUARES_X, "squares_y": SQUARES_Y,
                  "square_mm": square_mm},
        "units": "millimetres -- board square size sets the scale",
    }
    Path(path).write_text(json.dumps(data, indent=2))
    return data


def load(path):
    d = json.loads(Path(path).read_text())
    K = np.array(d["camera_matrix"], dtype=np.float64)
    dist = np.array(d["dist_coeffs"], dtype=np.float64).reshape(1, -1)
    return K, dist, d


def live_capture(args):
    from camera import Camera
    det, board = detector(args.squares_mm)
    kept_c, kept_i = [], []
    with Camera(args.index, args.width, args.height,
                realsense=args.realsense) as cam:
        if args.lock:
            got = cam.lock()
            print(got.report())
            if not got.ok:
                print("  ! optics not pinned -- calibration will not hold")
        size = cam.size
        print(f"\n  {size[0]}x{size[1]}  SPACE=keep view   c=calibrate   q=quit")
        print(f"  need {MIN_VIEWS}+ views: tilt the board, fill the corners,\n"
              f"  vary distance. Flat-on views from one spot do not constrain\n"
              f"  distortion.\n")
        while True:
            ok, frame = cam.read()
            if not ok:
                break
            corners, ids = find(frame, det)
            view = frame.copy()
            if ids is not None:
                cv2.aruco.drawDetectedCornersCharuco(view, corners, ids,
                                                     (0, 220, 120))
            cov = coverage(kept_c, size) if kept_c else 0.0
            cv2.putText(view, f"kept {len(kept_c)}/{MIN_VIEWS}   "
                              f"coverage {cov*100:.0f}%",
                        (12, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.7,
                        (0, 220, 120) if len(kept_c) >= MIN_VIEWS
                        else (60, 180, 255), 2, cv2.LINE_AA)
            cv2.imshow("calibrate", view)
            k = cv2.waitKey(1) & 0xFF
            if k == ord(" ") and ids is not None:
                kept_c.append(corners)
                kept_i.append(ids)
                print(f"  kept view {len(kept_c)} ({len(ids)} corners)")
            elif k == ord("c"):
                break
            elif k in (ord("q"), 27):
                cv2.destroyAllWindows()
                return None
    cv2.destroyAllWindows()
    return kept_c, kept_i, size, board


def from_dir(args):
    det, board = detector(args.squares_mm)
    kept_c, kept_i, size = [], [], None
    for f in sorted(Path(args.from_dir).glob("*.*")):
        img = cv2.imread(str(f))
        if img is None:
            continue
        size = (img.shape[1], img.shape[0])
        c, i = find(img, det)
        if i is not None:
            kept_c.append(c)
            kept_i.append(i)
            print(f"  {f.name}: {len(i)} corners")
        else:
            print(f"  {f.name}: no board")
    return kept_c, kept_i, size, board


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--index", type=int, default=0)
    p.add_argument("--width", type=int, default=1280)
    p.add_argument("--height", type=int, default=720)
    p.add_argument("--realsense", action="store_true")
    p.add_argument("--lock", action="store_true", help="pin focus/exposure")
    p.add_argument("--squares-mm", type=float, default=SQUARE_MM)
    p.add_argument("--from-dir")
    p.add_argument("--out", default=None)
    p.add_argument("--tag", default="webcam")
    p.add_argument("--check", help="print a saved calibration and exit")
    args = p.parse_args()

    if args.check:
        K, dist, d = load(args.check)
        print(json.dumps({k: v for k, v in d.items()
                          if k != "per_view_reproj_px"}, indent=2))
        return

    got = from_dir(args) if args.from_dir else live_capture(args)
    if not got:
        return
    kept_c, kept_i, size, board = got
    if len(kept_c) < MIN_VIEWS:
        raise SystemExit(f"\n  only {len(kept_c)} views -- need {MIN_VIEWS}. "
                         f"Nothing written.")

    cov = coverage(kept_c, size)
    rms, K, dist, per_view = calibrate(kept_c, kept_i, board, size)
    out = args.out or Path(__file__).parent / f"intrinsics_{args.tag}.json"
    save(out, K, dist, size, rms, per_view, args.squares_mm, args.tag)

    fx, fy = K[0, 0], K[1, 1]
    cx, cy = K[0, 2], K[1, 2]
    print(f"\n  wrote {out}")
    print(f"  views {len(kept_c)}   coverage {cov*100:.0f}%")
    print(f"  fx {fx:.1f}  fy {fy:.1f}  cx {cx:.1f}  cy {cy:.1f}")
    print(f"  rms reprojection {rms:.3f} px   worst view "
          f"{max(per_view):.3f} px")
    print()
    if rms > 1.0:
        print("  ! rms > 1 px -- something is off. Blurry frames, a bowed")
        print("    board, or a wrong --squares-mm.")
    if cov < 0.6:
        print(f"  ! coverage {cov*100:.0f}% is thin. The residual will look")
        print("    good and the edges will be badly modelled. Re-run and put")
        print("    the board in the frame corners.")
    if abs(fx - fy) / max(fx, fy) > 0.05:
        print("  ! fx and fy differ by >5% -- unusual for a normal lens;")
        print("    suspect a wrong board size or non-square pixels.")
    if rms <= 1.0 and cov >= 0.6:
        print("  looks sound. Verify it for real with locate.py against a")
        print("  ruler -- the residual alone does not prove accuracy.")


if __name__ == "__main__":
    main()
