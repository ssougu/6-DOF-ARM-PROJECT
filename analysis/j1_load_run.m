function R = j1_load_run(csvPath)
%J1_LOAD_RUN  Read one J1 sample CSV written by joint_console_v2.py.
%
%   R = J1_LOAD_RUN(csvPath) returns a struct with fields t, pos, vel, tq.
%
%   The files look like:
%       # 20261018-143719
%       t_s,position_rev,velocity_rev_s,torque_Nm
%       0.0000,-0.030182,0.000000,0.041000
%
%   Units: t seconds, pos OUTPUT revolutions, vel output rev/s,
%   tq N.m referred to the OUTPUT of the 15:1 reduction (see note below).
%
%   NOTE ON TORQUE UNITS.  moteus scales the TORQUE register by
%   1/rotor_to_output_ratio, so these values are already output-side.
%   Verified from the board: Kv = 330 -> Kt_rotor = 0.02894 N.m/A, and
%   servo.max_current_A = 10 A, so the rotor can produce at most
%   0.289 N.m.  The peak logged here is 0.802 N.m, which would need
%   27.7 A rotor-side (impossible) but only 1.85 A output-side.
%   These numbers are LOSSLESS-REFERRED: true output torque is eta times
%   these, and eta is not yet measured.
%
%   Comment lines and the text header are skipped; any line that does not
%   parse to 4 finite numbers is ignored.  Robust across MATLAB versions
%   and works in Octave.

txt   = fileread(csvPath);
lines = regexp(txt, '\r?\n', 'split');

v = zeros(numel(lines), 4);
k = 0;
for i = 1:numel(lines)
    L = strtrim(lines{i});
    if isempty(L) || L(1) == '#'
        continue
    end
    n = str2double(strsplit(L, ','));
    if numel(n) >= 4 && all(isfinite(n(1:4)))
        k = k + 1;
        v(k, :) = n(1:4);
    end
end

if k == 0
    error('j1_load_run:empty', 'No numeric rows parsed from %s', csvPath);
end

v      = v(1:k, :);
R.t    = v(:, 1);
R.pos  = v(:, 2);
R.vel  = v(:, 3);
R.tq   = v(:, 4);
R.file = csvPath;
R.n    = k;
end
