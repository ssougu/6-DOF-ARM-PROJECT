#!/usr/bin/env python3
"""
board.py -- the ChArUco board, defined once and shared by everything.

    python board.py                  # write charuco_A4.png, ready to print
    python board.py --squares-mm 30  # bigger board, better pose accuracy

Every module that needs board geometry imports `make_board()` from here, so
the dictionary and square size cannot drift apart between calibration and
localisation -- a mismatch there produces poses that are confidently wrong.

ChArUco rather than a plain checkerboard because the markers identify
themselves: the board still works when partly out of frame or occluded by the
arm, which a checkerboard does not.

*** PRINTING: scale must be exactly 100%. ***
"Fit to page" silently shrinks the sheet by a few percent, and every distance
you measure afterwards is wrong by that factor -- a scale error is invisible in
the reprojection residual, so calibration will look excellent and the arm will
consistently miss. Print it, then measure a square with calipers and check it
against the number this script prints. Do not skip that check.
"""

import argparse
from pathlib import Path

import cv2
import numpy as np

# --- board geometry. Change here, nowhere else. ---------------------------
SQUARES_X = 7
SQUARES_Y = 5
SQUARE_MM = 25.0
MARKER_RATIO = 0.75                  # marker edge as a fraction of the square
DICT_ID = cv2.aruco.DICT_4X4_50      # 17 markers needed for 7x5; 50 is plenty


def make_board(square_mm=SQUARE_MM):
    """The board, in millimetres. Poses come out in mm because this does."""
    d = cv2.aruco.getPredefinedDictionary(DICT_ID)
    return cv2.aruco.CharucoBoard(
        (SQUARES_X, SQUARES_Y), square_mm, square_mm * MARKER_RATIO, d), d


def render(square_mm=SQUARE_MM, dpi=300, margin_mm=10):
    """Render at an exact physical size so a 100% print is dimensionally true."""
    board, _ = make_board(square_mm)
    px_per_mm = dpi / 25.4
    w = int(round(SQUARES_X * square_mm * px_per_mm))
    h = int(round(SQUARES_Y * square_mm * px_per_mm))
    margin = int(round(margin_mm * px_per_mm))
    img = board.generateImage((w, h), marginSize=0, borderBits=1)
    return cv2.copyMakeBorder(img, margin, margin, margin, margin,
                              cv2.BORDER_CONSTANT, value=255)


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--squares-mm", type=float, default=SQUARE_MM)
    p.add_argument("--dpi", type=int, default=300)
    p.add_argument("--out", default=None)
    args = p.parse_args()

    img = render(args.squares_mm, args.dpi)
    out = Path(args.out or Path(__file__).parent /
               f"charuco_{SQUARES_X}x{SQUARES_Y}_{args.squares_mm:g}mm.png")
    cv2.imwrite(str(out), img)

    bw = SQUARES_X * args.squares_mm
    bh = SQUARES_Y * args.squares_mm
    print(f"wrote {out}")
    print(f"  {SQUARES_X}x{SQUARES_Y} squares of {args.squares_mm:g} mm "
          f"-> {bw:.0f} x {bh:.0f} mm of pattern")
    print(f"  image {img.shape[1]}x{img.shape[0]} px at {args.dpi} dpi")
    print(f"  A4 is 210x297 mm, so this "
          f"{'fits' if bw <= 190 and bh <= 277 else 'DOES NOT fit'} with margins")
    print()
    print("  PRINT AT EXACTLY 100% SCALE -- no 'fit to page', no 'shrink to")
    print("  printable area'. Then measure one square with calipers:")
    print(f"    it must be {args.squares_mm:g} mm. If it is not, re-print;")
    print("    a scale error here silently corrupts every distance later.")
    print("  Then glue it to something rigid. A board that bows is a board")
    print("  whose plane is not a plane.")


if __name__ == "__main__":
    main()
