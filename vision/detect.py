#!/usr/bin/env python3
"""
detect.py -- YOLO11m object detection on CUDA.

    python detect.py --bench              # honest latency numbers, no camera
    python detect.py --live               # webcam with boxes
    python detect.py --image path.jpg     # one image
    python detect.py --live --half        # FP16, roughly 2x on this GPU

Wraps ultralytics so the rest of the pipeline sees one small interface:
`Detector.detect(frame) -> [Detection]`, each with a pixel-space box and a
`ground_px` point -- the bottom-centre of the box, which is where the object
meets the table and therefore the only pixel worth handing to ray-plane
localisation. Box centre would float above the surface and bias every grasp.

Two things this file is careful about, both of which produce numbers that look
fine and are wrong:

  * **Silent CPU fallback.** `device='cuda'` is a request, not a guarantee.
    We assert the loaded weights really are on the GPU.
  * **Timing without a warmup or a sync.** The first inference pays CUDA
    context setup and cuDNN autotuning, and kernel launches are asynchronous,
    so a naive timer reports a fraction of the true latency.
"""

import argparse
import statistics
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import torch

MODEL_DIR = Path(__file__).parent / "models"
DEFAULT_WEIGHTS = MODEL_DIR / "yolo11m.pt"


@dataclass
class Detection:
    cls_id: int
    label: str
    conf: float
    xyxy: tuple            # (x1, y1, x2, y2) in pixels

    @property
    def center_px(self):
        x1, y1, x2, y2 = self.xyxy
        return ((x1 + x2) / 2.0, (y1 + y2) / 2.0)

    @property
    def ground_px(self):
        """Bottom-centre: where the object meets the surface.

        This is the point to feed ray-plane. The box centre sits roughly half
        the object's height above the table and would bias every grasp toward
        the camera by that much.
        """
        x1, _, x2, y2 = self.xyxy
        return ((x1 + x2) / 2.0, y2)


class Detector:
    def __init__(self, weights=DEFAULT_WEIGHTS, device="cuda", conf=0.25,
                 imgsz=640, half=False, verbose=False):
        from ultralytics import YOLO

        if device == "cuda" and not torch.cuda.is_available():
            raise RuntimeError(
                "CUDA requested but torch.cuda.is_available() is False. "
                "Run `python check_vision.py` to see why.")
        weights = Path(weights)
        if not weights.exists():
            raise FileNotFoundError(
                f"{weights} missing. Weights are gitignored -- fetch with:\n"
                f"  python -c \"from ultralytics import YOLO; "
                f"YOLO('{weights.name}')\"   (run inside vision/models/)")

        self.model = YOLO(str(weights))
        self.model.to(device)
        self.device, self.conf, self.imgsz, self.half = device, conf, imgsz, half
        self.verbose = verbose
        self.names = self.model.names

        # Verify rather than trust: .to() can no-op and inference would then
        # run on CPU at ~20x the latency while reporting identical boxes.
        got = next(self.model.model.parameters()).device.type
        want = "cuda" if device.startswith("cuda") else device
        if got != want:
            raise RuntimeError(
                f"model is on '{got}' but '{want}' was requested -- "
                f"refusing to report CPU numbers as GPU ones")

    @property
    def device_name(self):
        if self.device.startswith("cuda"):
            return torch.cuda.get_device_name(0)
        return self.device

    def detect(self, frame, classes=None):
        r = self.model.predict(frame, conf=self.conf, imgsz=self.imgsz,
                               half=self.half, device=self.device,
                               classes=classes, verbose=self.verbose)[0]
        out = []
        for b in r.boxes:
            cid = int(b.cls.item())
            out.append(Detection(cls_id=cid, label=self.names[cid],
                                 conf=float(b.conf.item()),
                                 xyxy=tuple(float(v) for v in b.xyxy[0])))
        return out

    def warmup(self, n=5):
        """Absorb CUDA context setup and cuDNN autotuning before timing."""
        blank = np.zeros((self.imgsz, self.imgsz, 3), dtype=np.uint8)
        for _ in range(n):
            self.detect(blank)
        self._sync()

    def _sync(self):
        if self.device.startswith("cuda"):
            torch.cuda.synchronize()

    def benchmark(self, n=50, frame=None):
        """Per-frame latency after warmup. Returns a dict of milliseconds."""
        if frame is None:
            rng = np.random.default_rng(0)
            frame = rng.integers(0, 255, (720, 1280, 3), dtype=np.uint8)
        self.warmup()
        times = []
        for _ in range(n):
            t0 = time.perf_counter()
            self.detect(frame)
            self._sync()                     # launches are async without this
            times.append((time.perf_counter() - t0) * 1000.0)
        times.sort()
        return {
            "n": n,
            "mean_ms": statistics.mean(times),
            "median_ms": statistics.median(times),
            "p95_ms": times[int(0.95 * (n - 1))],
            "worst_ms": times[-1],
            "fps_median": 1000.0 / statistics.median(times),
        }


def stability(det, cam, n=120, classes=None, label=None, settle=15):
    """How still is the detected ground point on a STATIONARY object?

    This is perception repeatability in pixels -- the same kind of number as
    J1's 0.36 deg, and the direct precursor to the mm error budget. Nothing
    here needs calibration: once intrinsics exist, px converts to mm.

    Reports detection *rate* separately from jitter, because they are
    different failure modes. A box that is rock steady in the 60% of frames
    where it appears is not a usable detection; neither is one found every
    frame that wanders 30 px. Both must be good.
    """
    cam._settle(settle)
    pts, confs, sizes = [], [], []
    misses = 0
    for _ in range(n):
        ok, frame = cam.read()
        if not ok:
            continue
        ds = det.detect(frame, classes=classes)
        if label:
            ds = [d for d in ds if d.label == label]
        if not ds:
            misses += 1
            continue
        d = max(ds, key=lambda x: x.conf)          # the confident one
        pts.append(d.ground_px)
        confs.append(d.conf)
        sizes.append((d.xyxy[2] - d.xyxy[0], d.xyxy[3] - d.xyxy[1]))

    seen = len(pts)
    if seen < 2:
        return {"frames": n, "seen": seen, "rate": seen / max(n, 1)}

    p = np.array(pts)
    s = np.array(sizes)
    step = np.linalg.norm(np.diff(p, axis=0), axis=1)   # frame-to-frame move
    return {
        "frames": n, "seen": seen, "misses": misses, "rate": seen / n,
        "conf_mean": float(np.mean(confs)), "conf_min": float(np.min(confs)),
        "ground_std_px": (float(np.std(p[:, 0])), float(np.std(p[:, 1]))),
        # Radial spread about the mean: one number for "how still is it".
        "ground_rms_px": float(np.sqrt(np.mean(
            np.sum((p - p.mean(axis=0)) ** 2, axis=1)))),
        "worst_jump_px": float(step.max()),
        "box_std_px": (float(np.std(s[:, 0])), float(np.std(s[:, 1]))),
        "box_mean_px": (float(np.mean(s[:, 0])), float(np.mean(s[:, 1]))),
    }


def draw(frame, dets):
    import cv2
    for d in dets:
        x1, y1, x2, y2 = (int(v) for v in d.xyxy)
        cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 220, 120), 2)
        cv2.putText(frame, f"{d.label} {d.conf:.2f}", (x1, max(14, y1 - 6)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 220, 120), 1,
                    cv2.LINE_AA)
        gx, gy = d.ground_px
        cv2.circle(frame, (int(gx), int(gy)), 4, (60, 120, 255), -1)
    return frame


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--weights", default=str(DEFAULT_WEIGHTS))
    p.add_argument("--device", default="cuda")
    p.add_argument("--conf", type=float, default=0.25)
    p.add_argument("--imgsz", type=int, default=640)
    p.add_argument("--half", action="store_true", help="FP16")
    p.add_argument("--bench", action="store_true")
    p.add_argument("--n", type=int, default=50)
    p.add_argument("--live", action="store_true")
    p.add_argument("--image")
    p.add_argument("--index", type=int, default=0, help="camera index")
    p.add_argument("--list-classes", action="store_true",
                   help="print the COCO classes YOLO already knows")
    p.add_argument("--label", help="keep only this class, e.g. 'bottle'")
    p.add_argument("--stability", action="store_true",
                   help="jitter of the ground point on a stationary object")
    args = p.parse_args()

    if args.list_classes:
        from ultralytics import YOLO
        names = YOLO(str(args.weights)).names
        for i in range(0, len(names), 4):
            print("  " + "".join(f"{j:>4} {names[j]:<18}"
                                 for j in range(i, min(i + 4, len(names)))))
        return

    det = Detector(args.weights, args.device, args.conf, args.imgsz, args.half)
    print(f"YOLO11m on {det.device_name}"
          + ("  [FP16]" if args.half else "  [FP32]"))

    if args.bench:
        s = det.benchmark(args.n)
        print(f"\n  {s['n']} frames @ 1280x720 -> imgsz {args.imgsz}")
        print(f"  median {s['median_ms']:.1f} ms  ({s['fps_median']:.0f} fps)")
        print(f"  mean   {s['mean_ms']:.1f} ms")
        print(f"  p95    {s['p95_ms']:.1f} ms")
        print(f"  worst  {s['worst_ms']:.1f} ms")
        return

    if args.stability:
        from camera import Camera
        det.warmup()
        with Camera(args.index) as cam:
            print(f"\n  hold still -- {args.n} frames"
                  + (f", class '{args.label}'" if args.label else ""))
            s = stability(det, cam, args.n, label=args.label)
        if s["seen"] < 2:
            print(f"  seen in {s['seen']}/{s['frames']} frames -- nothing to "
                  f"measure. Is the object in view and lit?")
            return
        gx, gy = s["ground_std_px"]
        bw, bh = s["box_mean_px"]
        sw, sh = s["box_std_px"]
        print(f"\n  detected in {s['seen']}/{s['frames']} frames "
              f"({s['rate']*100:.0f}%)")
        print(f"  confidence     mean {s['conf_mean']:.2f}   "
              f"min {s['conf_min']:.2f}")
        print(f"  ground point   rms {s['ground_rms_px']:.2f} px   "
              f"(x {gx:.2f}, y {gy:.2f})")
        print(f"  worst jump     {s['worst_jump_px']:.2f} px")
        print(f"  box            {bw:.0f}x{bh:.0f} px, "
              f"std {sw:.1f}x{sh:.1f}")
        print()
        if s["rate"] < 0.95:
            print("  ! dropping frames. An object the detector loses is an")
            print("    object the arm will reach for and miss. More light,")
            print("    less clutter, or a different object.")
        if s["ground_rms_px"] > 5:
            print("  ! ground point is wandering. Often the box breathing")
            print("    around a soft edge -- check it is not partly occluded.")
        print("  px here becomes mm once intrinsics exist; this is the")
        print("  perception half of the error budget.")
        return

    import cv2
    if args.image:
        frame = cv2.imread(args.image)
        if frame is None:
            raise SystemExit(f"could not read {args.image}")
        dets = det.detect(frame)
        if args.label:
            dets = [d for d in dets if d.label == args.label]
        for d in dets:
            print(f"  {d.label:<14} {d.conf:.2f}  ground_px="
                  f"({d.ground_px[0]:.0f}, {d.ground_px[1]:.0f})")
        cv2.imshow("detect", draw(frame, dets))
        cv2.waitKey(0)
        return

    if args.live:
        from camera import Camera
        det.warmup()
        with Camera(args.index) as cam:
            print("q or Esc to quit")
            while True:
                ok, frame = cam.read()
                if not ok:
                    break
                dets = det.detect(frame)
                if args.label:
                    dets = [d for d in dets if d.label == args.label]
                cv2.imshow("detect", draw(frame, dets))
                if cv2.waitKey(1) & 0xFF in (ord("q"), 27):
                    break
        cv2.destroyAllWindows()
        return

    p.print_help()


if __name__ == "__main__":
    main()
