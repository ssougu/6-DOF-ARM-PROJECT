function tt = j1_travel_time(d, vlim, alim)
%J1_TRAVEL_TIME  Trapezoidal (or triangular) traverse time for a move.
%
%   tt = J1_TRAVEL_TIME(d, vlim, alim) mirrors travel_time() in
%   host/joint_console_v2.py:454, WITHOUT its 0.75 s settling margin.
%
%   If the move is short enough that cruise speed is never reached the
%   profile is triangular:          tt = 2*sqrt(d/a)
%   otherwise it is trapezoidal:    tt = 2*(v/a) + (d - v^2/a)/v
%
%   This exists because of the single most important methodological finding
%   of 2026-10-18: `goto`/`step` commands pass through moteus's trajectory
%   generator, which is rate-limited by velocity_limit and accel_limit.  So
%   the measured "settling time" is mostly the TRAJECTORY DURATION, not the
%   joint's dynamic response.  Four of five step sizes match this prediction
%   to within 20%.  Any zeta / omega_n fitted to such a trace describes the
%   rate limiter, not the servo.

if nargin < 2 || isempty(vlim), vlim = 0.25; end
if nargin < 3 || isempty(alim), alim = 1.00; end

d = abs(d);
if d <= vlim^2 / alim
    tt = 2 * sqrt(d / alim);
else
    tt = 2 * (vlim / alim) + (d - vlim^2 / alim) / vlim;
end
end
