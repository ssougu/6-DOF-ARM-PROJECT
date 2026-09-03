# vision

Perception for the pick demo. Runs on the laptop, independent of the arm —
everything here except the eventual hand-eye calibration works with nothing
but a camera and a printed board, which is why it can be built while the
mechanical side is still in CAD.

Design decisions live in [`../docs/VISION_APPROACH.md`](../docs/VISION_APPROACH.md).
This is the code and how to run it.

## Start here

```bash
cd vision
python check_vision.py          # proves the whole stack, needs no camera
```

Eight checks: CUDA, OpenCV ChArUco, board geometry, weights, the model
actually landing on the GPU, inference latency, and — the useful one —
ray-plane localisation recovering known millimetres from synthetic pixels.
Exits non-zero on failure.

## The pipeline

| File | What it does |
|---|---|
| `board.py` | Defines the ChArUco board once, and renders it for printing |
| `camera.py` | Opens a camera and **pins focus/exposure**, reporting what the driver actually did |
| `calibrate.py` | Intrinsics from board views, with a coverage score |
| `detect.py` | YOLO11m on CUDA → boxes, and the ground point of each |
| `locate.py` | **pixel → table millimetres**, by ray–plane |
| `check_vision.py` | Self-check, PASS/FAIL |

Localisation is ray–plane, not stereo depth: the board defines the table
plane, a pixel defines a ray, the object is where they meet. No depth is
involved, which is why a plain webcam is enough and why it survives the
textureless and shiny objects that break stereo.

## Bring-up, in order

**1. Print the board.**

```bash
python board.py                 # writes charuco_7x5_25mm.png
```

Print at **exactly 100% scale** — no "fit to page". Then measure a square
with calipers and confirm it is 25 mm. A scale error here is invisible in
every later diagnostic and corrupts every distance. Glue it to something
rigid; a board that bows is a board whose plane is not a plane.

**2. Check the camera can hold still.**

```bash
python camera.py --list
python camera.py --index 0 --lock
```

**Focus is what matters, not exposure.** Focus changes the intrinsics, so a
calibration taken at one focus stops being true at another — and the symptom
is results that drift for no visible reason. Exposure moves no pixel
geometrically; it only costs image quality and consistency. A well-exposed
auto frame beats a pinned dark one, so `ok` reports focus alone.

The `AUTOFOCUS` property returning −1 is **ambiguous** — it means the driver
exposes no control, which covers both a fixed-focus lens (nothing to pin,
calibrate away) and autofocus that cannot be switched off (useless). The
property cannot tell them apart, so `camera.py` watches Laplacian sharpness
over a couple of seconds instead: a lens that hunts varies, a fixed lens does
not. **Keep the scene still while it measures.**

On this laptop's built-in webcam: sharpness cv ~1–3%, so it reads as
fixed-focus and is safe to calibrate.

Exposure is trickier. Switching to manual *without* supplying a value leaves
the driver on its manual default, which is usually a near-black frame — if
your image suddenly goes dark, that is why. `lock()` now lets auto converge,
takes the value it chose, and pins that; if the driver ignores manual exposure
entirely (this laptop's does), it detects that and stays on auto rather than
handing you a black picture. Just avoid changing the lighting mid-calibration.

**3. Calibrate.**

```bash
python calibrate.py --index 0 --lock --tag webcam
```

SPACE keeps a view, `c` calibrates. Needs 12+ views: tilt the board, fill the
frame corners, vary the distance. Flat-on views from one position produce a
beautiful residual and badly modelled distortion, so the script scores
coverage and complains when it is thin.

**Reprojection error is not accuracy.** It says the model fits the views you
gave it, nothing more.

**4. Measure the thing that actually matters.**

```bash
python locate.py --ruler
```

Click two points a known distance apart and compare with a real ruler. That
number — millimetres of error at working distance — is the error-budget input
the arm design needs. Nothing upstream substitutes for it.

Then:

```bash
python locate.py --detect        # YOLO objects, located on the table in mm
```

## Without a printed board

Calibration needs the board, but choosing and characterising the demo object
does not — and that decision gets expensive late, so make it early.

```bash
python detect.py --list-classes            # the 80 COCO classes, free
python detect.py --live --label bottle     # does it hold on your object?
python detect.py --stability --label bottle --n 200
```

**Pick a COCO class.** YOLO11m already knows `bottle`, `cup`, `bowl`, `apple`,
`banana`, `orange`, `sports ball`, `mouse`, `cell phone`, `book`, `scissors`.
Anything outside those 80 means collecting and training a custom dataset —
weeks. Choosing an object the model already knows is the single biggest
schedule saving available in perception.

**`--stability` is perception repeatability, in pixels.** Put the object
down, don't touch it, and measure how much the detected ground point wanders.
It is the same kind of number as J1's 0.36°, and once intrinsics exist it
converts straight to millimetres — so it is the perception half of the error
budget, measurable today.

It reports detection *rate* and jitter separately because they fail
differently. A box that is rock-steady in the 60% of frames where it appears
is not usable; neither is one found every frame that wanders 30 px.

Worth testing while you are there, all of it board-free:

- **Each candidate object**, and keep the one that detects most reliably.
- **Object shape vs the ground-point assumption.** Bottom-centre of the box is
  taken as the contact point. That is true for a bottle or a ball; a mug with a
  handle has a box skewed by the handle, so its bottom-centre is not under the
  object's centre. This biases every grasp, and it is cheaper to pick a
  friendlier object than to correct for it.
- **Lighting.** Re-run under the lighting the fair will actually have.
- **Distance and clutter.** Where does the rate fall off?
- **Pose.** Bottle upright vs on its side — confidence often differs a lot.

## Notes

- **`--plane-offset`** is the mounting thickness: positive means the real
  contact surface sits that far *behind* the board's printed face. Board glued
  to 3 mm foamboard, object on the bare table → `--plane-offset 3`. Skip it
  and every grasp carries a constant offset.
- **Detections use the box's bottom-centre**, not its centre — that is where
  the object meets the table. Box centre floats roughly half the object's
  height above the surface and biases every grasp toward the camera.
- **Intrinsics are resolution-specific.** `locate.py` refuses to run if the
  camera size does not match the calibration, rather than silently rescaling.
- **FP16 is not worth it here.** Measured on the RTX 4060: median 8.4 ms vs
  8.8 ms FP32, but p95 17.1 ms vs 10.4 ms. The workload is bound by
  preprocessing and NMS, not conv math.
- Weights are gitignored. `check_vision.py` prints the fetch command.

## Measured on this machine

RTX 4060 Laptop, 8 GB, torch 2.6.0+cu124, YOLO11m at imgsz 640:

| | |
|---|---|
| median | 8.8 ms (114 fps) |
| p95 | 10.4 ms |
| worst | 44.2 ms |

Far faster than the demo needs — it is look-then-move, not visual servoing.
Detection will not be the bottleneck; localisation accuracy will.
