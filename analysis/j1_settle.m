function ts = j1_settle(t, pos, target, band)
%J1_SETTLE  First entry into a band around target, never leaving it.
%
%   ts = J1_SETTLE(t, pos, target, band) returns the settling time, or NaN
%   if the trace never enters the band and stays there.
%
%   Two bands are used throughout this analysis (plan section 7.1):
%
%     RELATIVE  band = 0.02 * |delta|          the original criterion
%     ABSOLUTE  band = 0.36 deg = 0.001 rev    the measured repeatability
%
%   The relative band becomes finer than the measured backlash (0.23 deg)
%   below delta = 0.23/7.2 = 0.0319 rev = 11.5 deg, at which point "did not
%   settle" is an artifact of the metric rather than a property of the
%   joint.  Measurement confirms the flip happens exactly there.
%
%   The absolute band is degenerate at the other end: at delta = 0.5 deg it
%   is 72% of the whole step, so the joint counts as settled after moving
%   0.14 deg.  Neither criterion means anything below about delta = 1.8 deg
%   (5x the absolute band); report the static error floor there instead.

inside = abs(pos - target) <= band;
ts     = NaN;
for i = 1:numel(t)
    if all(inside(i:end))
        ts = t(i);
        return
    end
end
end
