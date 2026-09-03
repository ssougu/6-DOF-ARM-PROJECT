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
    args = p.parse_args()

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

    import cv2
    if args.image:
        frame = cv2.imread(args.image)
        if frame is None:
            raise SystemExit(f"could not read {args.image}")
        dets = det.detect(frame)
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
                cv2.imshow("detect", draw(frame, dets))
                if cv2.waitKey(1) & 0xFF in (ord("q"), 27):
                    break
        cv2.destroyAllWindows()
        return

    p.print_help()


if __name__ == "__main__":
    main()
