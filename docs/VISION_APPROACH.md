# Vision approach

Design notes, 2026-09-01. Nothing here is built yet — this is the plan for the
perception half of the demo.

Target: *detect an object on a flat surface, select it from a terminal, pick it
up. Reliably, repeatably.*

---

## The transform chain

```
(u,v) + depth  ──deproject──►  P_camera
                                   │
                            T_base←camera            ← the whole problem
                                   ▼
                                P_base  ──IK──►  joint angles  ──►  Arm.move_deg()
```

Deprojection is solved (`rs2_deproject_pixel_to_point` with the camera
intrinsics) and IK is written once. **Everything hard lives in
`T_base←camera`**, and its form depends on the mount:

- **Fixed camera:** `T_base←cam` is one constant matrix, calibrated once.
- **Eye-in-hand:** `T_base←cam = FK(q) · T_link←cam`, recomputed every frame,
  and its accuracy is bounded by forward-kinematics accuracy.

**Write the transform layer so the mount is a config choice, not a rewrite** —
the same trick that makes `joints.py` work. Then switching mounts later is a
swap of one function.

---

## Mount: eye-in-hand, on the forearm

Decided eye-in-hand (per CLAUDE.md). Mount on the link **before** the wrist
(after J3/J4), angled forward and down past the gripper — **not** on the tool
flange:

| | Tool flange | Forearm |
|---|---|---|
| Standoff at grasp | ~0 mm, inside min-Z | 150–250 mm retained |
| Cable crosses | all 6 joints | 3–4 joints |
| Mass at lever tip | worst case | much better |
| Sees the gripper | no | **yes** — verify the object is between the fingers |

### Look-then-move dissolves the min-Z problem

The camera does **not** need to see during the grasp:

```
1. observation pose   arm high, camera 400–600 mm from the table
2. detect + localise  object position in base frame
3. (optional) closer look, re-detect, refine
4. pre-grasp pose     directly above the object, ~120 mm up
5. descend blind      straight down, no vision
6. close gripper
```

Depth only has to be valid at steps 1–3, well outside min-Z. This is how most
industrial eye-in-hand cells work.

### Camera model

| Mount | Standoff | Model |
|---|---|---|
| Fixed / high observation | 500–800 mm | **D435** (optimal ~0.3–3 m) |
| Eye-in-hand, close work | 70–300 mm | **D405** (optimal 7–50 cm) |

**Confirm which model we actually own before finalising the bracket geometry.**
Platform is safe either way: RealSense spun out of Intel in July 2025 as an
independent company with a $50M Series A; D435/D415/D405/D401 and SDK 2.0 are
actively supported.

---

## Localisation: ray–plane first, depth as a cross-check

The object sits on a **known flat plane**. That is a strong constraint:

1. Calibrate the table plane once in base coordinates (falls out of the
   calibration below).
2. Object pixel `(u,v)` → ray through the camera using intrinsics.
3. **Intersect the ray with the plane.** That is the 3D position.

No depth involved, and it beats depth exactly where stereo fails:

| | Stereo depth | Ray–plane |
|---|---|---|
| Shiny / black / transparent | **fails** — no texture to match | fine |
| Noise | ~2% of range | none, pure geometry |
| Edge dropout | common | none |
| Needs object height | no | assumes object on the plane |

**Use ray–plane as primary, depth as a cross-check and for object height.** If
they disagree beyond a threshold, that detection is untrustworthy — a genuinely
useful reliability signal for a demo that must run twenty times.

Bonus: if the RealSense misbehaves at the booth, a cheap webcam is a working
fallback.

---

## Detection: two layers, fused

- **Geometry (reliable):** RANSAC plane fit to find the table, then Euclidean
  clustering on the remaining points. Real 3D centroids, works on *any* object,
  no training. Open3D does this in a few lines.
- **Labels (impressive + needed for the terminal UI):** pretrained
  **YOLOv8/v11 on COCO**. No training, ~5 ms on the 4090. Assign each detection
  to the nearest cluster.

Gives `1: cup at (0.31, -0.05, 0.02)` for the terminal selection.

**Take the centroid from the point-cloud cluster, not one pixel's depth** —
averaging hundreds of points cuts random noise by √N.

**Skip 6-DOF grasp-pose networks (GraspNet etc.).** For top-down picks:
approach straight down, set gripper yaw from PCA on the cluster (align to the
object's minor axis). That is the entire grasp planner — and another argument
that 4 DOF suffices.

---

## Calibration

### Hand-eye (required for eye-in-hand)

`cv2.calibrateHandEye()`, solving AX=XB for `T_link←cam`:

1. Fix a **ChArUco board** in the workspace (better than a checkerboard —
   tolerates partial views and occlusion).
2. Move to **12–20 varied poses** where the board is visible.
3. At each, record `T_base←link` (FK) and `T_cam←board` (`cv2.solvePnP`).
4. Solve. Compare `CALIB_HAND_EYE_PARK` against `..._DANIILIDIS` residuals.

⚠️ **The trap:** AX=XB is **degenerate if all rotations share an axis.** Only
swivelling the base between poses yields confident-looking garbage. **Tilt the
wrist about genuinely different axes.** If the residual will not converge to a
few mm, this is why.

⚠️ **Hand-eye accuracy is bounded by FK accuracy.** Measure link lengths
physically; do not trust CAD.

### Fixed-camera alternative (much easier, if the mount ever changes)

Touch the gripper tip to ~8–10 scattered points, record FK position and
camera-frame position at each, solve with **Kabsch/Umeyama**
(`Rotation.align_vectors`, or ten lines of SVD). No board needed. The RMS
residual **is** the calibration quality and belongs in the logs.

---

## Error budget

Independent random errors combine as RSS, and only long-lever joints matter:

| Joint | Lever arm | 0.36° becomes |
|---|---|---|
| J1 base yaw | ~400 mm | 2.5 mm |
| J2 shoulder | ~350 mm | 2.2 mm |
| J3 elbow | ~200 mm | 1.3 mm |
| J4 | ~100 mm | 0.6 mm |
| J5/J6 wrist | ~30 mm | negligible |

√(2.5² + 2.2² + 1.3² + 0.6²) ≈ **3.6 mm** — not 6× anything. Add vision (~2–3 mm
with cluster centroids) and calibration residual (~3–5 mm) and the realistic
total is **5–8 mm at the gripper.**

**Split the budget:**
- **Systematic** (link lengths off from CAD, joint offsets, gearbox ratio,
  camera transform bias) — **calibratable, and it is most of a naive budget.**
- **Random** (repeatability, depth noise) — must be absorbed. ~5 mm.

### Is 5–8 mm good enough? It depends entirely on the object

| Object | Size | 6 mm error |
|---|---|---|
| Coffee cup | 80 mm | trivial |
| Can / bottle | 65 mm | comfortable |
| Small block | 25 mm | tight, needs a compliant gripper |
| Screw, coin | 5 mm | no |

**We choose the object.** Picking something 60–80 mm is not cheating, it is
specifying the operating envelope. **Avoid shiny, black or transparent
objects** — stereo depth genuinely fails on them (though ray–plane does not).

### The two decisions that make error a non-issue

1. ⚠️ **A self-centring gripper.** V-groove or funnel fingers with 15–20 mm of
   compliance mechanically absorb the entire budget. Worth more than any
   filtering. **Tell the ME before the gripper is designed.**
2. **Approach from a consistent direction.** CLAUDE.md already measures 0.23°
   of direction-dependent error (backlash); a consistent approach removes that
   term for free.

---

## Mechanical checklist — where eye-in-hand projects die

- **Rigidity.** Flex between camera and link continuously invalidates
  calibration. Thick print with short standoffs, or aluminium. Do not
  cantilever off a thin bracket.
- **Repeatable remount.** Dowel pins or a keyed pocket. If the camera comes off
  and returns 1° different, hand-eye is silently wrong. This *will* happen.
- **Cable is the #1 failure point.** RealSense needs USB 3.x for full
  framerate and the stock cable is stiff. Use a **thin 28 AWG flexible USB-C
  cable**, leave a **service loop at every joint**, and **anchor it to each
  link** so joint motion never pulls the connector. Intermittent USB dropouts
  from connector fatigue are miserable to debug mid-demo.
- **Mass:** D435 ≈ 72 g, D405 ≈ 60 g plus mount. Re-check J2/J3 holding torque
  once it is on.

---

## Practical RealSense notes

- **`rs.align(rs.stream.color)` is mandatory.** Without it, RGB pixel
  coordinates do not index the matching depth pixel and everything is subtly
  wrong in a way that is miserable to debug.
- Use the **color** intrinsics for deprojection after aligning.
- Do not recalibrate intrinsics — factory values are good.
- `pyrealsense2` on Windows is fine.

---

## Verification, in the style we already use

- **A `--sim` vision source** publishing fake detections, so the pick pipeline
  is testable with no camera — the pattern that makes `sim_test.py` useful.
- **Hand-eye RMS residual** in mm, logged next to the J1 repeatability numbers.
- **End-to-end:** place the object at ~20 known positions, log computed vs
  measured 3D position. That table is the perception spec, and it is what makes
  the fair demo credible.
- **Recalibration drift:** re-run hand-eye after a day of use. If it moved, the
  mount is not stiff enough — better to learn that now than at the booth.

## Dependencies

Hand-eye needs working FK → needs measured link lengths → needs the arm built.
**The bracket can be designed now; calibration is gated on mechanical
completion.** Put that on the schedule explicitly.
