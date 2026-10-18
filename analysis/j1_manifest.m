function M = j1_manifest(logDir)
%J1_MANIFEST  The 2026-10-18 J1 bench session, as a data manifest.
%
%   M = J1_MANIFEST(logDir) returns a struct describing every run of the
%   session.  Metadata (step size, gain scale) was extracted from the JSON
%   sidecar written beside each CSV by log_run() in joint_console_v2.py and
%   is restated here so the plotting scripts need no JSON parser.
%
%   Session conditions, identical across all runs unless stated:
%     kp = 225, kd = 4.5, ki = 200, ilimit = 0.5      (scales all 1.0)
%     vel_limit 0.25 rev/s, accel_limit 1.0 rev/s^2
%     max_torque 1.0 N.m   (= 23% of the 4.34 N.m available at 10 A)
%     bus 23.5 V, board 26 C at start, 30 C at end
%     servopos +/- 0.55 rev,  rotor_to_output_ratio 1/15,  cpr 16384

if nargin < 1 || isempty(logDir)
    here   = fileparts(mfilename('fullpath'));
    logDir = fullfile(here, '..', 'host', 'logs');
end
M.logDir = logDir;

% ---- step-size sweep (section 15.1): constant gains, varying delta ----
M.delta.stamp = { '20261018-143719', '20261018-143724', '20261018-143729', ...
                  '20261018-143735', '20261018-143742' };
M.delta.rev   = [ 0.00139, 0.00556, 0.03190, 0.12500, 0.25000 ];
M.delta.deg   = M.delta.rev * 360;

% ---- gain sweep (section 15.7): constant delta = 0.0319 rev, varying kp ----
M.kp.stamp    = { '20261018-144553', '20261018-144557', '20261018-144601', ...
                  '20261018-144605', '20261018-144609' };
M.kp.scale    = [ 0.25, 0.50, 1.00, 2.00, 4.00 ];
M.kp.deltaRev = 0.03190;
M.kp.configured = 225;          % servo.pid_position.kp

% ---- repeatability, summary statistics only ----
% do_random calls log_run() WITHOUT a samples argument, so the individual
% landing errors were never written to disk.  Only these aggregates exist.
% That gap is why no error histogram appears in this figure set.
M.rep.label   = { '2026-08-26  n=20', '2026-10-18  n=50' };
M.rep.n       = [ 20, 50 ];
M.rep.sigma   = [ mean([0.2168 0.2282 0.2333]), 0.2950 ];   % deg
M.rep.meanAbs = [ mean([0.1807 0.1932 0.1886]), 0.2656 ];   % deg
M.rep.dirSplit= [ mean([0.2292 0.2363 0.2193]), 0.0231 ];   % deg
M.rep.refRange= [ mean([0.3625 0.3735 0.3516]), 1.0162 ];   % deg, max-min
M.rep.d2      = [ 3.736, 4.499 ];   % E[range]/sigma for n=20 and n=50

% ---- machine constants, read from the board 2026-10-18 ----
M.hw.Kv          = 330;                      % RPM/V, motor.Kv
M.hw.N           = 15;                       % reduction
M.hw.KtRotor     = 9.5493 / 330;             % N.m/A  = 0.02894
M.hw.maxCurrentA = 10;                       % servo.max_current_A
M.hw.tqAvail     = 15 * (9.5493/330) * 10;   % N.m at the output = 4.341
M.hw.tqCeiling   = 1.0;                      % max_torque used this session
M.hw.velUsed     = 0.25;                     % rev/s
M.hw.velCap      = 0.5;                      % servo.max_velocity
M.hw.velVoltLim  = 330 * 24 / sqrt(3) / 60 / 15;   % rev/s = 5.08
M.hw.velNoLoad   = 330 * 24 / 60 / 15;             % rev/s = 8.80
M.hw.backlashDeg = 0.23;                     % two-point, 2026-08-26
M.hw.absBandDeg  = 0.36;                     % absolute settling band
M.hw.controlHz   = 50;                       % CONTROL_HZ, nominal
end
