#!/usr/bin/env python3
"""
check_vision.py -- prove the vision stack works. No camera needed.

    python check_vision.py

Checks CUDA, OpenCV's ChArUco support, the YOLO weights, that the model really
lands on the GPU, and that ray-plane localisation recovers known millimetres
from synthetic pixels. Exits non-zero on failure.

The ray-plane check is the valuable one: it builds a virtual camera, projects
points whose board coordinates are known, and asserts `pixel_to_table` gets
them back. A sign error or a transposed rotation survives every visual test --
the overlay still looks plausible -- but fails here immediately.
"""

import sys
import traceback
from pathlib import Path

import numpy as np

PASS, FAIL = [], []


def check(name):
    def deco(fn):
        try:
            detail = fn()
            PASS.append((name, detail or ""))
            print(f"  [ok]   {name}" + (f"  -- {detail}" if detail else ""))
        except Exception as e:                           # noqa: BLE001
            FAIL.append((name, str(e)))
            print(f"  [FAIL] {name}\n         {e}")
            if "-v" in sys.argv:
                traceback.print_exc()
        return fn
    return deco


print("\nvision stack check\n" + "-" * 52)


@check("torch + CUDA")
def _cuda():
    import torch
    if not torch.cuda.is_available():
        raise RuntimeError(
            "torch.cuda.is_available() is False. A CPU-only torch build is "
            "the usual cause -- check `python -c \"import torch; "
            "print(torch.__version__)\"` shows a +cu suffix.")
    name = torch.cuda.get_device_name(0)
    vram = torch.cuda.get_device_properties(0).total_memory / 1024**3
    cap = ".".join(str(x) for x in torch.cuda.get_device_capability(0))
    return f"{name}, {vram:.1f} GB, sm_{cap.replace('.', '')}, torch {torch.__version__}"


@check("OpenCV ChArUco")
def _cv():
    import cv2
    if not hasattr(cv2, "aruco"):
        raise RuntimeError("cv2.aruco missing -- install opencv-contrib-python")
    if not hasattr(cv2.aruco, "CharucoDetector"):
        raise RuntimeError("CharucoDetector missing -- needs OpenCV >= 4.7")
    return f"opencv {cv2.__version__}"


@check("board geometry")
def _board():
    from board import make_board, SQUARES_X, SQUARES_Y, SQUARE_MM
    b, _ = make_board()
    n = len(b.getChessboardCorners())
    want = (SQUARES_X - 1) * (SQUARES_Y - 1)
    if n != want:
        raise RuntimeError(f"{n} inner corners, expected {want}")
    return f"{SQUARES_X}x{SQUARES_Y} @ {SQUARE_MM:g} mm, {n} corners"


@check("YOLO11m weights present")
def _weights():
    from detect import DEFAULT_WEIGHTS
    if not DEFAULT_WEIGHTS.exists():
        raise FileNotFoundError(
            f"{DEFAULT_WEIGHTS} missing (gitignored). Fetch it:\n"
            f"         cd vision/models && python -c \"from ultralytics "
            f"import YOLO; YOLO('yolo11m.pt')\"")
    return f"{DEFAULT_WEIGHTS.stat().st_size / 1024**2:.1f} MB"


@check("model loads on GPU")
def _model():
    from detect import Detector
    d = Detector()
    import torch
    dev = next(d.model.model.parameters()).device
    if dev.type != "cuda":
        raise RuntimeError(f"weights on {dev}, not cuda")
    return f"{d.device_name}, {len(d.names)} classes"


@check("inference runs")
def _infer():
    from detect import Detector
    d = Detector()
    d.warmup(2)
    rng = np.random.default_rng(0)
    frame = rng.integers(0, 255, (720, 1280, 3), dtype=np.uint8)
    d.detect(frame)                     # noise: detections optional, no crash
    s = d.benchmark(12)
    if s["median_ms"] > 200:
        raise RuntimeError(
            f"median {s['median_ms']:.0f} ms is far too slow for a GPU -- "
            f"suspect a silent CPU fallback")
    return f"median {s['median_ms']:.1f} ms ({s['fps_median']:.0f} fps)"


@check("ray-plane recovers known mm")
def _raytrace():
    """Synthetic camera, known board pose, known points. Pure math."""
    import cv2
    from locate import TablePlane

    K = np.array([[800.0, 0, 640.0], [0, 800.0, 360.0], [0, 0, 1.0]])
    dist = np.zeros((1, 5))

    # Board tilted and offset, so a transposed rotation cannot pass by luck.
    rvec = np.array([[0.35], [-0.22], [0.11]])
    tvec = np.array([[-60.0], [-40.0], [450.0]])       # mm

    truth = np.array([[0.0, 0.0, 0.0], [175.0, 0.0, 0.0],
                      [0.0, 125.0, 0.0], [87.5, 62.5, 0.0],
                      [30.0, 100.0, 0.0]])
    px, _ = cv2.projectPoints(truth, rvec, tvec, K, dist)
    px = px.reshape(-1, 2)

    plane = TablePlane(K, dist)
    plane.R = cv2.Rodrigues(rvec)[0]
    plane.t = tvec.reshape(3)

    worst = 0.0
    for (u, v), want in zip(px, truth):
        got = plane.pixel_to_table(u, v)
        if got is None:
            raise RuntimeError(f"no intersection for pixel ({u:.1f}, {v:.1f})")
        worst = max(worst, float(np.linalg.norm(got[:2] - want[:2])))
        if abs(got[2]) > 1e-6:
            raise RuntimeError(f"z={got[2]:.6f} mm, should be 0 on the plane")
    if worst > 1e-6:
        raise RuntimeError(f"recovered mm off by {worst:.6f} (expected ~0)")
    return f"{len(truth)} points, worst error {worst:.2e} mm"


@check("plane offset lands below the board face")
def _offset():
    """A 10 mm offset must put the contact plane 10 mm behind the printed face.

    Uses a board that actually faces the camera (+Z back toward it), because
    a fronto-parallel identity pose is a board facing away -- geometrically
    impossible to see, and it hides sign errors rather than exposing them.
    """
    import cv2
    from locate import TablePlane

    K = np.array([[800.0, 0, 640.0], [0, 800.0, 360.0], [0, 0, 1.0]])
    dist = np.zeros((1, 5))
    rvec = np.array([[np.pi], [0.0], [0.0]])     # board Z -> -Z_cam
    tvec = np.array([[0.0], [0.0], [500.0]])
    R = cv2.Rodrigues(rvec)[0]

    u, v = 900.0, 500.0                          # off-axis
    for off, want_z in ((0.0, 0.0), (10.0, -10.0)):
        pl = TablePlane(K, dist, plane_offset_mm=off)
        pl.R, pl.t = R, tvec.reshape(3)
        p = pl.pixel_to_table(u, v)
        if p is None:
            raise RuntimeError(f"no intersection at offset {off}")
        # Board-frame z of the hit point: 0 on the face, -offset behind it.
        if abs(p[2] - want_z) > 1e-6:
            raise RuntimeError(
                f"offset {off} mm -> board z {p[2]:.6f}, expected {want_z}")
    return "0 and 10 mm offsets land on the right plane"


print("-" * 52)
if FAIL:
    print(f"\n  {len(FAIL)} FAILED, {len(PASS)} passed\n")
    for n, e in FAIL:
        print(f"    {n}: {e}")
    print()
    raise SystemExit(1)
print(f"\n  VISION OK -- {len(PASS)} checks passed\n")
