#!/usr/bin/env python3
"""
locate.py -- pixel -> table coordinates in millimetres, by ray-plane.

    python locate.py --ruler              # click two points, get the distance
    python locate.py --click              # click anything, get board mm
    python locate.py --detect             # YOLO objects, located on the table

This is the primary localiser from VISION_APPROACH.md, and it uses no depth.
The board lying on the table defines the plane; a pixel defines a ray; the
object is where they meet. It beats stereo exactly where stereo is weakest --
textureless, shiny and thin objects -- and it works on a plain webcam.

    ray:    P(s) = s * d          d = undistorted pixel as a camera-frame ray
    plane:  n . (P - t) = 0       n = board Z axis in camera frame, t = origin
    =>      s = (n . t) / (n . d)

`--ruler` is the test that matters. Click two points a known distance apart and
compare. That number is the real error budget input -- reprojection residual
from calibration does not tell you whether millimetres are right.

**The plane is the board's top surface, not the table.** If the board is glued
to 3 mm foamboard, everything reports 3 mm high, which becomes a constant
offset in every grasp. Measure the mounting thickness and pass --plane-offset.
"""

import argparse
import json
from pathlib import Path

import cv2
import numpy as np

from board import make_board, SQUARE_MM
from calibrate import load as load_intrinsics


class TablePlane:
    """The board's plane, and the transform between the camera and it."""

    def __init__(self, K, dist, square_mm=SQUARE_MM, plane_offset_mm=0.0):
        self.K, self.dist = K, dist
        self.board, _ = make_board(square_mm)
        self.det = cv2.aruco.CharucoDetector(self.board)
        self.offset = plane_offset_mm
        self.R = self.t = None            # board -> camera, once seen

    def update(self, frame):
        """Find the board and store its pose. False if it is not visible."""
        corners, ids, _, _ = self.det.detectBoard(frame)
        if ids is None or len(ids) < 6:
            return False
        obj, img = self.board.matchImagePoints(corners, ids)
        if obj is None or len(obj) < 6:
            return False
        ok, rvec, tvec = cv2.solvePnP(obj, img, self.K, self.dist,
                                      flags=cv2.SOLVEPNP_ITERATIVE)
        if not ok:
            return False
        self.R = cv2.Rodrigues(rvec)[0]
        self.t = tvec.reshape(3)
        self.rvec, self.tvec = rvec, tvec
        self._corners, self._ids = corners, ids
        return True

    @property
    def seen(self):
        return self.R is not None

    def pixel_to_table(self, u, v):
        """(u, v) px -> (x, y) mm in the board frame, or None if it misses.

        Returns board-frame millimetres: origin at the board's first corner,
        x/y along the board, z out of it. z is ~0 by construction, and is
        returned so callers can assert that rather than assume it.
        """
        if not self.seen:
            return None
        # Undistort to a normalised ray. Passing P=None gives normalised
        # coords, so the direction is simply [x, y, 1].
        pt = np.array([[[float(u), float(v)]]], dtype=np.float64)
        xy = cv2.undistortPoints(pt, self.K, self.dist).reshape(2)
        d = np.array([xy[0], xy[1], 1.0])

        # Board +Z points out of the printed face, i.e. back toward the camera
        # when the board lies on a table below it. The real contact surface is
        # `offset` mm *behind* that face (the mounting thickness), so step
        # along -Z to reach it.
        n = self.R[:, 2]                       # board Z, in camera frame
        origin = self.t - n * self.offset
        denom = float(n @ d)
        if abs(denom) < 1e-9:                  # ray parallel to the table
            return None
        s = float(n @ origin) / denom
        if s <= 0:                             # intersection behind the camera
            return None
        p_cam = s * d
        p_board = self.R.T @ (p_cam - self.t)
        return p_board                          # (x, y, z) mm

    def draw(self, frame):
        if self.seen:
            cv2.drawFrameAxes(frame, self.K, self.dist, self.rvec, self.tvec,
                              SQUARE_MM * 2)
            cv2.aruco.drawDetectedCornersCharuco(frame, self._corners,
                                                 self._ids, (0, 220, 120))
        else:
            cv2.putText(frame, "board not visible", (12, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (60, 120, 255), 2)
        return frame


def _fmt(p):
    return f"({p[0]:7.1f}, {p[1]:7.1f}) mm   z={p[2]:+.2f}"


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--intrinsics", default=None)
    p.add_argument("--index", type=int, default=0)
    p.add_argument("--realsense", action="store_true")
    p.add_argument("--squares-mm", type=float, default=SQUARE_MM)
    p.add_argument("--plane-offset", type=float, default=0.0,
                   help="mm from the board surface down to the real table")
    p.add_argument("--ruler", action="store_true",
                   help="click two points, print the distance between them")
    p.add_argument("--click", action="store_true")
    p.add_argument("--detect", action="store_true",
                   help="locate YOLO detections on the table")
    p.add_argument("--lock", action="store_true")
    args = p.parse_args()

    intr = args.intrinsics or (Path(__file__).parent / "intrinsics_webcam.json")
    if not Path(intr).exists():
        raise SystemExit(
            f"no intrinsics at {intr} -- run calibrate.py first.\n"
            f"Ray-plane is only as good as the camera model behind it.")
    K, dist, meta = load_intrinsics(intr)

    from camera import Camera
    det = None
    if args.detect:
        from detect import Detector, draw as draw_dets
        det = Detector()
        det.warmup()

    plane = TablePlane(K, dist, args.squares_mm, args.plane_offset)
    clicks = []

    def on_mouse(event, x, y, flags, _):
        if event != cv2.EVENT_LBUTTONDOWN:
            return
        pt = plane.pixel_to_table(x, y)
        if pt is None:
            print("  no intersection (board not seen, or ray misses the plane)")
            return
        if args.ruler:
            clicks.append(pt)
            print(f"  point {len(clicks)}: {_fmt(pt)}")
            if len(clicks) == 2:
                d = float(np.linalg.norm(clicks[0][:2] - clicks[1][:2]))
                print(f"  --> distance {d:.2f} mm      "
                      f"(measure it and compare)")
                clicks.clear()
        else:
            print(f"  {_fmt(pt)}")

    with Camera(args.index, realsense=args.realsense) as cam:
        if args.lock:
            print(cam.lock().report())
        if list(cam.size) != list(meta["image_size"]):
            raise SystemExit(
                f"camera is {cam.size[0]}x{cam.size[1]} but the intrinsics "
                f"were measured at {meta['image_size'][0]}x"
                f"{meta['image_size'][1]}.\nThey do not transfer between "
                f"resolutions -- recalibrate or change the capture size.")
        cv2.namedWindow("locate")
        cv2.setMouseCallback("locate", on_mouse)
        print("  click on the image. q or Esc to quit.")
        if args.ruler:
            print("  ruler mode: two clicks give a distance. Compare it with")
            print("  a real ruler -- that comparison is the actual test.\n")

        while True:
            ok, frame = cam.read()
            if not ok:
                break
            plane.update(frame)
            view = plane.draw(frame.copy())
            if det is not None and plane.seen:
                for d_ in det.detect(frame):
                    gx, gy = d_.ground_px
                    pt = plane.pixel_to_table(gx, gy)
                    x1, y1, x2, y2 = (int(v) for v in d_.xyxy)
                    cv2.rectangle(view, (x1, y1), (x2, y2), (0, 220, 120), 2)
                    tag = (f"{d_.label} {pt[0]:.0f},{pt[1]:.0f}mm"
                           if pt is not None else f"{d_.label} off-plane")
                    cv2.putText(view, tag, (x1, max(14, y1 - 6)),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                                (0, 220, 120), 1, cv2.LINE_AA)
                    cv2.circle(view, (int(gx), int(gy)), 4, (60, 120, 255), -1)
            cv2.imshow("locate", view)
            if cv2.waitKey(1) & 0xFF in (ord("q"), 27):
                break
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
