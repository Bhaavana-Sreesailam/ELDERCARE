"""
ElderCare Guardian - Fall detection.

The MPU6050 gives us acceleration on three axes. We combine them into a
single magnitude:

    magnitude = sqrt(ax^2 + ay^2 + az^2)

When the wearer is still, magnitude sits near 1 g (just gravity). A fall
has a recognisable signature:

    1. Free-fall : magnitude dips toward 0 g for a fraction of a second.
    2. Impact    : magnitude spikes well above 1 g as the body hits a surface.
    3. Stillness : magnitude settles back near 1 g and stays flat (the person
                   may be unable to get up).

We keep a short rolling buffer of recent magnitudes so that when we see an
impact we can look *backwards* for the free-fall that preceded it. Requiring
both the dip and the spike makes us far less likely to mistake an ordinary
sharp movement (sitting down hard, setting the arm on a table) for a fall.
"""

import math
from collections import deque

import config


def magnitude(ax, ay, az):
    """Combine three axes (in g) into a single acceleration magnitude."""
    return math.sqrt(ax * ax + ay * ay + az * az)


class FallDetector:
    """
    Stateful detector. Feed it one reading at a time with `update()`.
    It returns True on the sample where a fall is confirmed.
    """

    def __init__(self):
        self.buffer = deque(maxlen=config.FREEFALL_WINDOW)
        self.saw_freefall = False

    def update(self, mag):
        """
        Process one acceleration magnitude. Returns True if this sample
        completes a fall pattern (free-fall followed by impact).
        """
        self.buffer.append(mag)

        # Did we just dip into free-fall? Remember it for the next few samples.
        if mag < config.FREEFALL_THRESHOLD:
            self.saw_freefall = True

        # An impact spike is the trigger we react to.
        if mag > config.IMPACT_THRESHOLD:
            # Strong confidence: a free-fall preceded this impact.
            if self.saw_freefall:
                self.saw_freefall = False
                return True
            # Medium confidence: a very hard impact on its own. We also
            # check the buffer directly in case the dip was recorded but
            # the flag was reset by an intervening event.
            if any(m < config.FREEFALL_THRESHOLD for m in self.buffer):
                return True

        return False

    def reset(self):
        self.buffer.clear()
        self.saw_freefall = False


def classify_impact(mag):
    """
    A quick label for a single magnitude reading, handy for logging and
    for the on-device check in the firmware.
    """
    if mag > config.IMPACT_THRESHOLD:
        return "impact"
    if mag < config.FREEFALL_THRESHOLD:
        return "freefall"
    if abs(mag - 1.0) < config.INACTIVITY_THRESHOLD:
        return "still"
    return "active"
