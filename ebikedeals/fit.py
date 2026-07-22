"""Estimate which rider heights a frame size suits.

Two shop populations state fit in incompatible ways: variant shops give a frame
size (54 cm, L), refurbished shops give a rider height range (165-175 cm).
A body-height filter therefore reaches only half the catalogue.

This module bridges the gap by mapping a frame size back to the rider heights
it plausibly fits. That is an estimate, not a fact - which is why it lives
behind an opt-in switch and is labelled as such in the report.

The arithmetic: frame height ~ inseam x 0.66, inseam ~ body height x 0.47, so
a trekking frame is roughly body height x 0.31. Mountain bike frames sit lower,
around body height x 0.26.

The unit tells us which factor applies, and it is a far better signal than the
product title: shops quote trekking and city frames in centimetres and mountain
bike frames in inches. Going by the title instead produced nonsense - a "54 cm"
frame on a bike named "Stereo Hybrid Fully" was read as a mountain bike and
came out at 205-211 cm of rider.
"""

from __future__ import annotations

import re

# frame_cm = body_cm * factor. The cm band is slightly wider than the single
# trekking factor because sportier frames are sometimes quoted in cm too.
CM_FACTORS = (0.285, 0.325)
INCH_FACTORS = (0.245, 0.275)

# Nobody is filtering for a rider outside this range; a computed range that
# leaves it entirely is a sign the size was not a frame size at all.
PLAUSIBLE_RIDER = (140, 210)

# Letter sizes have no arithmetic - these are the ranges manufacturers publish,
# widened by a couple of centimetres because they disagree with each other.
_LETTER_RANGES = {
    "XXS": (140, 158),
    "XS": (150, 165),
    "S": (158, 172),
    "M": (166, 180),
    "L": (174, 188),
    "XL": (182, 196),
    "XXL": (190, 210),
}

_CM_SIZE = re.compile(r"^(\d{2})(?:[.,]\d)?\s*(cm)?$", re.I)
_INCH_SIZE = re.compile(r"^(\d{2})(?:[.,]\d)?\s*(?:\"|zoll)$", re.I)


def estimate_body_height(sizes: list[str], title: str = "") -> tuple[int | None, int | None]:
    """Rider height range (cm) a set of frame sizes plausibly fits.

    `title` is accepted for call-site symmetry but deliberately unused: the
    size's unit is the reliable type signal, the title is not.
    """
    lows: list[float] = []
    highs: list[float] = []

    for raw in sizes:
        s = raw.strip().upper()
        if s in _LETTER_RANGES:
            a, b = _LETTER_RANGES[s]
            lows.append(a)
            highs.append(b)
            continue

        frame_cm = factors = None
        m = _INCH_SIZE.match(s)
        if m:
            frame_cm, factors = float(m.group(1)) * 2.54, INCH_FACTORS
        else:
            m = _CM_SIZE.match(s)
            if m and 30 <= int(m.group(1)) <= 70:
                frame_cm, factors = float(m.group(1)), CM_FACTORS
        if frame_cm is None:
            continue

        # frame = body * factor  ->  body = frame / factor. The larger factor
        # yields the smaller rider, hence the crossover here.
        lows.append(frame_cm / factors[1])
        highs.append(frame_cm / factors[0])

    if not lows:
        return None, None
    # Tolerance of +-3 cm: these tables are approximations, and a rider one
    # size out is a fitting question, not a reason to hide the offer.
    lo = int(round(min(lows))) - 3
    hi = int(round(max(highs))) + 3
    if hi < PLAUSIBLE_RIDER[0] or lo > PLAUSIBLE_RIDER[1]:
        return None, None
    return max(lo, PLAUSIBLE_RIDER[0]), min(hi, PLAUSIBLE_RIDER[1])
