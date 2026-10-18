function j1_figures(outDir)
%J1_FIGURES  Generate every figure for the 2026-10-18 J1 bench session.
%
%   j1_figures            % render on screen
%   j1_figures('figs')    % render and save PNGs into analysis/figs
%
%   Eight figures, all from logged data in host/logs.  Nothing here is
%   synthetic.  Where only summary statistics exist (repeatability), that is
%   stated on the figure itself rather than filled in with invented points.
%
%   Figure map
%     1  Step response family across step size
%     2  Settling-criterion crossover  <- confirms a quantitative prediction
%     3  Measured settling vs trajectory-generator prediction  <- key finding
%     4  Host timing jitter            <- answers the timing open question
%     5  Gain sweep: settling and static error
%     6  Torque during the step sweep, against the real ceilings
%     7  Repeatability, August vs October, with confidence intervals
%     8  Capability utilisation: how little of the envelope was used

if nargin < 1, outDir = ''; end
S = j1_style();
M = j1_manifest();
if ~isempty(outDir) && ~exist(outDir, 'dir'), mkdir(outDir); end

fig1_step_family(M, S, outDir);
fig2_crossover(M, S, outDir);
fig3_trajectory(M, S, outDir);
fig4_jitter(M, S, outDir);
fig5_gain_sweep(M, S, outDir);
fig6_torque(M, S, outDir);
fig7_repeatability(M, S, outDir);
fig8_capability(M, S, outDir);
fprintf('\nDone. 8 figures generated.\n');
if ~isempty(outDir)
    fprintf('Saved to %s\n', outDir);
end
end


% ======================================================================
function fig1_step_family(M, S, outDir)
f = newfig('J1 step response across step size');
hold on; grid on; box off
xlim([0 2.2]); ylim([-110 20])      % set before any axis-spanning line
h = gobjects(1, numel(M.delta.stamp));
lbl = cell(1, numel(M.delta.stamp));
for i = 1:numel(M.delta.stamp)
    R   = loadrun(M, M.delta.stamp{i});
    tgt = R.pos(1) + M.delta.rev(i);
    % normalise: percent of commanded step, so all five share one axis
    y   = 100 * (R.pos - tgt) / M.delta.rev(i);
    h(i)   = plot(R.t, y, '-', 'Color', S.ramp(i,:), 'LineWidth', S.lw);
    lbl{i} = sprintf('%.2f deg', M.delta.deg(i));
end
yline0(S, 0, 'target');
xlabel('time since command (s)'); ylabel('position error (% of commanded step)')
title({'J1 step response, cold, kp = 225', ...
       'monotone approach from below -- no overshoot at any step size'})
legend(h, lbl, 'Location', 'southeast', 'Box', 'off', 'TextColor', S.ink2)
dress(gca, S); finish(f, outDir, 'fig1_step_family');
end


% ======================================================================
function fig2_crossover(M, S, outDir)
% The prediction: the relative band (2% of the step) equals the measured
% backlash at delta = 0.23/7.2 = 0.0319 rev = 11.5 deg.  Below that,
% "did not settle" is a property of the metric, not of the joint.
f = newfig('J1 settling-criterion crossover');
hold on; grid on; box off
d  = M.delta.deg;
br = 0.02 * M.delta.rev * 360;       % relative band, deg
ba = M.hw.absBandDeg * ones(size(d));
fin = zeros(size(d)); okRel = false(size(d));
for i = 1:numel(d)
    R   = loadrun(M, M.delta.stamp{i});
    tgt = R.pos(1) + M.delta.rev(i);
    fin(i)   = abs(mean(R.pos(end-9:end)) - tgt) * 360;
    okRel(i) = ~isnan(j1_settle(R.t, R.pos, tgt, 0.02*M.delta.rev(i)));
end
h1 = plot(d, br,  '-o', 'Color', S.cat(1,:), 'LineWidth', S.lw, ...
          'MarkerSize', S.ms, 'MarkerFaceColor', S.cat(1,:));
h2 = plot(d, ba,  '--', 'Color', S.cat(2,:), 'LineWidth', S.lw);
h3 = plot(d, fin, '-s', 'Color', S.ink2, 'LineWidth', S.lwThin, ...
          'MarkerSize', S.ms, 'MarkerFaceColor', S.surface);
xc = M.hw.backlashDeg / 7.2 * 360;   % = 11.5 deg
plot([xc xc], [1e-3 10], ':', 'Color', S.critical, 'LineWidth', S.lw);
text(xc*1.15, 0.0125, sprintf('predicted crossover\n%.1f deg', xc), ...
     'Color', S.critical, 'FontSize', 9);
% mark which runs actually settled under the relative criterion
plot(d(okRel),  br(okRel),  'o', 'MarkerSize', S.ms+6, ...
     'MarkerEdgeColor', S.good, 'LineWidth', S.lw);
plot(d(~okRel), br(~okRel), 'x', 'MarkerSize', S.ms+6, ...
     'MarkerEdgeColor', S.critical, 'LineWidth', S.lw);
set(gca, 'XScale', 'log', 'YScale', 'log')
xlabel('commanded step (deg)'); ylabel('band or error (deg)')
title({'Why the relative settling criterion fails on small steps', ...
       'circle = settled, cross = "did not settle" (an artifact)'})
legend([h1 h2 h3], {'relative band (2% of step)', ...
       'absolute band (0.36 deg)', 'measured static error'}, ...
       'Location', 'northwest', 'Box', 'off', 'TextColor', S.ink2)
dress(gca, S); finish(f, outDir, 'fig2_crossover');
end


% ======================================================================
function fig3_trajectory(M, S, outDir)
% The key methodological finding: these are not step responses.  Commands
% pass through moteus's trajectory generator, so settling time is mostly
% the rate-limited traverse time.
f = newfig('J1 settling vs trajectory prediction');
hold on; grid on; box off
ts = zeros(1,numel(M.delta.stamp)); tj = ts;
for i = 1:numel(M.delta.stamp)
    R     = loadrun(M, M.delta.stamp{i});
    tgt   = R.pos(1) + M.delta.rev(i);
    ts(i) = j1_settle(R.t, R.pos, tgt, M.hw.absBandDeg/360);
    tj(i) = j1_travel_time(M.delta.rev(i), 0.25, 1.0);
end
lim = [0.04 2];
plot(lim, lim, '--', 'Color', S.axis, 'LineWidth', S.lwThin);
% placed clear of the 45 deg data label -- they collided at (0.9, 0.78)
text(0.235, 0.33, 'y = x', 'Color', S.muted, 'FontSize', 9, 'Rotation', 38);
for i = 1:numel(ts)
    plot(tj(i), ts(i), 'o', 'MarkerSize', S.ms+2, ...
         'MarkerFaceColor', S.ramp(i,:), 'MarkerEdgeColor', S.surface, ...
         'LineWidth', 2);
    text(tj(i)*1.12, ts(i), sprintf('%.1f deg', M.delta.deg(i)), ...
         'FontSize', 9, 'Color', S.ink2);
end
[~, k] = max(ts ./ tj);
% anchored with a leader line -- unanchored text read as floating
text(tj(k)*0.33, ts(k)*1.55, sprintf('%.1fx -- the only\nreal outlier', ...
     ts(k)/tj(k)), 'Color', S.critical, 'FontSize', 9);
plot([tj(k)*0.62 tj(k)*1.02], [ts(k)*1.42 ts(k)*1.01], '-', ...
     'Color', S.critical, 'LineWidth', S.lwThin);
set(gca, 'XScale', 'log', 'YScale', 'log')
axis([lim lim])
xlabel('trapezoidal traverse time, predicted (s)')
ylabel('measured settling time (s)')
title({'"Settling time" is the trajectory generator, not joint dynamics', ...
       'four of five land on y = x -- so no zeta or omega_n is defensible'})
dress(gca, S); finish(f, outDir, 'fig3_trajectory');
end


% ======================================================================
function fig4_jitter(M, S, outDir)
% Falls out of data already logged: control_loop stamps every sample with
% time.monotonic(), so inter-sample deltas are a host timing dataset.
f = newfig('J1 host loop timing jitter');
hold on; grid on; box off
dt = [];
all = [M.delta.stamp, M.kp.stamp];
for i = 1:numel(all)
    R  = loadrun(M, all{i});
    dt = [dt; diff(R.t) * 1000];   %#ok<AGROW>
end
histogram(dt, 'BinWidth', 0.5, 'FaceColor', S.cat(1,:), ...
          'EdgeColor', S.surface, 'FaceAlpha', 1);
nominal = 1000 / M.hw.controlHz;
plot([nominal nominal], ylim, '--', 'Color', S.critical, 'LineWidth', S.lw);
text(nominal*1.02, max(ylim)*0.88, sprintf('nominal %.1f ms\n(CONTROL_HZ = %d)', ...
     nominal, M.hw.controlHz), 'Color', S.critical, 'FontSize', 9);
mu = mean(dt);
text(mu*0.52, max(ylim)*0.55, sprintf('measured mean %.2f ms\n= %.1f Hz (%.2fx nominal)', ...
     mu, 1000/mu, (1000/mu)/M.hw.controlHz), 'Color', S.ink, 'FontSize', 9);
xlabel('interval between samples (ms)'); ylabel('count')
title({sprintf('Host loop runs at %.1f Hz, not 50 Hz  (n = %d intervals)', 1000/mu, numel(dt)), ...
       'quantised to the 15.6 ms Windows scheduler tick, with 0.7% double ticks'})
xlim([13 33])
dress(gca, S); finish(f, outDir, 'fig4_jitter');
end


% ======================================================================
function fig5_gain_sweep(M, S, outDir)
% Two measures of different scale -> two panels, never a dual y-axis.
f = newfig('J1 gain sweep'); set(f, 'Position', [100 100 980 420]);

ts = nan(1,numel(M.kp.stamp)); fin = ts; pk = ts;
for i = 1:numel(M.kp.stamp)
    R     = loadrun(M, M.kp.stamp{i});
    tgt   = R.pos(1) + M.kp.deltaRev;
    ts(i) = j1_settle(R.t, R.pos, tgt, M.hw.absBandDeg/360);
    fin(i)= (mean(R.pos(end-9:end)) - tgt) * 360;
    pk(i) = max(abs(R.tq));
end
x = M.kp.scale;

subplot(1,2,1); hold on; grid on; box off
plot(x, ts, '-o', 'Color', S.cat(1,:), 'LineWidth', S.lw, ...
     'MarkerSize', S.ms, 'MarkerFaceColor', S.cat(1,:));
bad = isnan(ts);
if any(bad)
    plot(x(bad), zeros(1,sum(bad)), 'x', 'MarkerSize', S.ms+6, ...
         'MarkerEdgeColor', S.critical, 'LineWidth', S.lw);
    text(x(find(bad,1)), 0.07, 'never settled', 'Color', S.critical, 'FontSize', 9);
end
set(gca, 'XScale', 'log', 'XTick', x, 'XTickLabel', ...
     arrayfun(@(v) sprintf('%.2g', v), x, 'UniformOutput', false))
xlabel('kp\_scale  (effective kp = 225 x scale)')
ylabel('settling time, 0.36 deg band (s)')
title('Settling'); dress(gca, S);

subplot(1,2,2); hold on; grid on; box off
bar(1:numel(x), abs(fin), 0.6, 'FaceColor', S.cat(1,:), 'EdgeColor', S.surface);
plot(xlim, [M.hw.absBandDeg M.hw.absBandDeg], '--', ...
     'Color', S.cat(2,:), 'LineWidth', S.lw);
text(1.1, M.hw.absBandDeg*1.14, 'repeatability floor, 0.36 deg', ...
     'Color', S.cat(2,:), 'FontSize', 9);
set(gca, 'XTick', 1:numel(x), 'XTickLabel', ...
     arrayfun(@(v) sprintf('%.2g', v), x, 'UniformOutput', false))
xlabel('kp\_scale'); ylabel('|static error| (deg)')
title('Static error'); dress(gca, S);

sgt = sprintf(['Raising stiffness settles %.1fx faster with no ringing ' ...
    '-- but n = 1 per cell, one step size, unloaded'], ts(3)/min(ts));
try, sgtitle(sgt, 'FontSize', 10, 'Color', S.ink); catch, end
finish(f, outDir, 'fig5_gain_sweep');
end


% ======================================================================
function fig6_torque(M, S, outDir)
f = newfig('J1 torque during the step sweep');
hold on; grid on; box off
xlim([0 2.2]); ylim([0 M.hw.tqAvail*1.08])   % before axis-spanning lines
h = gobjects(1,numel(M.delta.stamp)); lbl = cell(1,numel(M.delta.stamp));
for i = 1:numel(M.delta.stamp)
    R = loadrun(M, M.delta.stamp{i});
    h(i)   = plot(R.t, abs(R.tq), '-', 'Color', S.ramp(i,:), 'LineWidth', S.lw);
    lbl{i} = sprintf('%.2f deg', M.delta.deg(i));
end
hc = plot(xlim, [M.hw.tqCeiling M.hw.tqCeiling], '--', ...
          'Color', S.cat(2,:), 'LineWidth', S.lw);
ha = plot(xlim, [M.hw.tqAvail M.hw.tqAvail], ':', ...
          'Color', S.critical, 'LineWidth', S.lw);
text(1.3, M.hw.tqAvail*0.93, sprintf('%.2f N.m available at %d A', ...
     M.hw.tqAvail, M.hw.maxCurrentA), 'Color', S.critical, 'FontSize', 9);
text(1.3, M.hw.tqCeiling*1.1, 'max\_torque ceiling used, 1.0 N.m', ...
     'Color', S.cat(2,:), 'FontSize', 9);
xlabel('time since command (s)')
ylabel('|torque| at the output, lossless-referred (N.m)')
title({'Torque never approached the envelope', ...
       'peak 0.80 N.m = 18% of available; the ceiling itself was only 23%'})
legend([h hc ha], [lbl, {'ceiling', 'available'}], 'Location', 'east', ...
       'Box', 'off', 'TextColor', S.ink2)
dress(gca, S); finish(f, outDir, 'fig6_torque');
end


% ======================================================================
function fig7_repeatability(M, S, outDir)
% Only aggregates exist: do_random never saved per-move samples, so no
% histogram is possible.  Shown as sigma with its confidence interval.
f = newfig('J1 repeatability, August vs October');
set(f, 'Position', [100 100 940 430]);

subplot(1,2,1); hold on; grid on; box off
sd = M.rep.sigma; n = M.rep.n;
rel = 1.96 ./ sqrt(2*(n-1));
for i = 1:2
    bar(i, sd(i), 0.5, 'FaceColor', S.cat(i,:), 'EdgeColor', S.surface);
    errorbar(i, sd(i), sd(i)*rel(i), 'Color', S.ink, 'LineWidth', S.lw, ...
             'CapSize', 14, 'LineStyle', 'none');
    text(i, sd(i)*(1+rel(i))+0.022, sprintf('+/-%.0f%%', 100*rel(i)), ...
         'HorizontalAlignment', 'center', 'FontSize', 9, 'Color', S.ink2);
end
set(gca, 'XTick', 1:2, 'XTickLabel', M.rep.label)
ylabel('sigma of landing error (deg)'); ylim([0 0.46])
title({'Landing-error sigma', 'F = 1.70, p = 0.21 -- NOT significant'})
dress(gca, S);

subplot(1,2,2); hold on; grid on; box off
raw = M.rep.refRange;
nrm = raw ./ M.rep.d2;
hb = bar([raw; nrm]', 0.72, 'EdgeColor', S.surface);
set(hb(1), 'FaceColor', S.cat(1,:)); set(hb(2), 'FaceColor', S.cat(2,:));
set(gca, 'XTick', 1:2, 'XTickLabel', M.rep.label)
ylabel('reference-point scatter (deg)')
title({'Range vs sigma at the reference point', ...
       sprintf('raw ranges read %.2fx; normalised for n it is %.2fx', ...
               raw(2)/raw(1), nrm(2)/nrm(1))})
legend({'raw range (max - min)', 'sigma = range / d_2'}, ...
       'Location', 'northwest', 'Box', 'off', 'TextColor', S.ink2)
dress(gca, S);

try
    sgtitle({'Comparing ranges at different n is invalid -- the headline 0.36 deg was a range of 20', ...
             'no error histogram is possible: do\_random never saved per-move samples'}, ...
            'FontSize', 10, 'Color', S.ink);
catch
end
finish(f, outDir, 'fig7_repeatability');
end


% ======================================================================
function fig8_capability(M, S, outDir)
f = newfig('J1 capability utilisation');
set(f, 'Position', [100 100 900 400]);

subplot(1,2,1); hold on; grid on; box off
v = [M.hw.velUsed, M.hw.velCap, M.hw.velVoltLim, M.hw.velNoLoad];
nm = {'used this session', 'servo.max\_velocity', 'voltage-limited', 'no-load theoretical'};
for i = 1:4
    barh(i, v(i), 0.55, 'FaceColor', S.ramp(i,:), 'EdgeColor', S.surface);
    text(v(i)*1.08, i, sprintf('%.2f', v(i)), 'FontSize', 9, 'Color', S.ink2);
end
set(gca, 'YTick', 1:4, 'YTickLabel', nm, 'XScale', 'log')
xlabel('output velocity (rev/s)'); xlim([0.15 16])
title(sprintf('Velocity: capped %.0fx below capability', M.hw.velNoLoad/M.hw.velCap))
dress(gca, S);

subplot(1,2,2); hold on; grid on; box off
t = [0.802, M.hw.tqCeiling, M.hw.tqAvail];
nm2 = {'peak actually drawn', 'max\_torque ceiling', 'available at 10 A'};
for i = 1:3
    barh(i, t(i), 0.55, 'FaceColor', S.ramp(i+1,:), 'EdgeColor', S.surface);
    text(t(i)+0.09, i, sprintf('%.2f N.m  (%.0f%%)', t(i), 100*t(i)/M.hw.tqAvail), ...
         'FontSize', 9, 'Color', S.ink2);
end
set(gca, 'YTick', 1:3, 'YTickLabel', nm2)
xlabel('output torque, lossless-referred (N.m)'); xlim([0 M.hw.tqAvail*1.5])
title('Torque: 23% of the envelope was ever requested')
dress(gca, S);

try
    sgtitle('Both axes of the envelope were barely explored -- by configuration, not by physics', ...
            'FontSize', 10, 'Color', S.ink);
catch
end
finish(f, outDir, 'fig8_capability');
end


% ================= helpers =================
function R = loadrun(M, stamp)
R = j1_load_run(fullfile(M.logDir, [stamp '_j1_step.csv']));
end

function f = newfig(name)
f = figure('Name', name, 'Color', 'w', 'NumberTitle', 'off');
end

function yline0(S, y, txt)
plot(xlim, [y y], '-', 'Color', S.axis, 'LineWidth', S.lwThin);
if nargin > 2
    text(0.04, y+3, txt, 'Color', S.muted, 'FontSize', 9);
end
end

function dress(ax, S)
set(ax, 'FontSize', S.font, 'FontName', S.fontName, ...
        'XColor', S.muted, 'YColor', S.muted, ...
        'GridColor', S.grid, 'GridAlpha', 1, 'Layer', 'bottom', ...
        'TickDir', 'out', 'Box', 'off');
set(get(ax,'Title'),  'Color', S.ink,  'FontWeight', 'normal');
set(get(ax,'XLabel'), 'Color', S.ink2);
set(get(ax,'YLabel'), 'Color', S.ink2);
end

function finish(f, outDir, name)
if ~isempty(outDir)
    p = fullfile(outDir, [name '.png']);
    try
        exportgraphics(f, p, 'Resolution', 200);
    catch
        print(f, p, '-dpng', '-r200');
    end
    fprintf('  wrote %s\n', p);
end
end
