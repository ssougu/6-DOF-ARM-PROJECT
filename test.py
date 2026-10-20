"""
YOLO medium pose detection on a webcam feed.

Install:
    pip install ultralytics opencv-python
    # For CUDA, install a CUDA build of PyTorch first, e.g.:
    # pip install torch torchvision --index-url https://download.pytorch.org/whl/cu121

Run:
    python test.py
Press 'q' to quit.
"""

import os
import time

import cv2
import torch
from ultralytics import YOLO

MODEL_NAME = "yolo11m-pose.pt"  # medium pose model (auto-downloads on first run)
CAMERA_INDEX = 1  # 0 = built-in laptop cam, 1 = external USB webcam (try 2 if needed)
CONF_THRESHOLD = 0.5
IMG_SIZE = 640


def main():
    use_cuda = torch.cuda.is_available()
    device = "cuda:0" if use_cuda else "cpu"
    print(f"Using device: {device}")
    if use_cuda:
        print(f"GPU: {torch.cuda.get_device_name(0)}")

    print("Loading model (downloads on first run)...", flush=True)
    model = YOLO(MODEL_NAME)
    model.to(device)
    print("Model loaded.", flush=True)

    print(f"Opening webcam {CAMERA_INDEX}...", flush=True)
    # DirectShow opens USB webcams much faster than the default MSMF backend on Windows
    backend = cv2.CAP_DSHOW if os.name == "nt" else cv2.CAP_ANY
    cap = cv2.VideoCapture(CAMERA_INDEX, backend)
    if not cap.isOpened():
        raise RuntimeError(f"Could not open webcam at index {CAMERA_INDEX}")
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
    print("Webcam opened. Starting inference (first frame warms up the GPU)...", flush=True)

    prev_time = time.time()
    fps = 0.0

    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                print("Failed to grab frame")
                break

            results = model.predict(
                frame,
                device=device,
                conf=CONF_THRESHOLD,
                imgsz=IMG_SIZE,
                half=use_cuda,  # FP16 on GPU for extra speed
                verbose=False,
            )

            result = results[0]
            annotated = result.plot()  # draws boxes + skeletons

            # Smoothed FPS counter
            now = time.time()
            fps = 0.9 * fps + 0.1 * (1.0 / max(now - prev_time, 1e-6))
            prev_time = now

            num_people = len(result.boxes) if result.boxes is not None else 0
            cv2.putText(annotated, f"FPS: {fps:.1f}", (10, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
            cv2.putText(annotated, f"People: {num_people}", (10, 65),
                        cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)

            # Keypoints are available here if you want to use them:
            # result.keypoints.xy   -> (N, 17, 2) pixel coords
            # result.keypoints.conf -> (N, 17) confidences

            cv2.imshow("YOLO Pose (medium)", annotated)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break
    finally:
        cap.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()