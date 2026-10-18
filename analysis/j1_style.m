function S = j1_style()
%J1_STYLE  Figure styling constants for the J1 characterization plots.
%
%   Colours come from a validated palette (dataviz reference instance),
%   checked against a white figure surface:
%     - 5-step ordinal blue ramp  -> ALL CHECKS PASS (monotone L, dL >= 0.06,
%       light end 2.11:1 vs white, single hue, spread 3 deg)
%     - 2-slot categorical blue/orange -> ALL CHECKS PASS (all-pairs CVD
%       dE 24.7 protan, normal-vision dE 33.6, both >= 3:1 on white)
%
%   Rules honoured throughout: one y-axis per plot (never dual-axis),
%   ordinal ramps for ordered quantities, categorical slots in fixed order,
%   recessive grid and axes, thin marks, legend whenever >= 2 series.

% --- ordinal ramp: use for ORDERED quantities (step size, gain) ---
S.ramp = [ hx('#86b6ef')      % step 250 - lightest permitted on white
           hx('#5598e7')      % step 350
           hx('#2a78d6')      % step 450
           hx('#1c5cab')      % step 550
           hx('#104281') ];   % step 650

% --- categorical slots: use for UNORDERED identity, in fixed order ---
S.cat = [ hx('#2a78d6')       % slot 1 blue
          hx('#eb6834')       % slot 2 orange
          hx('#1baf7a') ];    % slot 3 aqua

% --- status (reserved; never a series colour) ---
S.good     = hx('#0ca30c');
S.critical = hx('#d03b3b');

% --- chrome and ink ---
S.ink      = hx('#0b0b0b');   % primary text
S.ink2     = hx('#52514e');   % secondary text
S.muted    = hx('#898781');   % axis labels
S.grid     = hx('#e1e0d9');   % hairline gridlines
S.axis     = hx('#c3c2b7');   % baseline / axis
S.surface  = [1 1 1];

% --- marks ---
S.lw       = 2.0;             % data line width
S.lwThin   = 1.2;             % reference / annotation lines
S.ms       = 8;               % marker size (>= 8 px)
S.font     = 10;
S.fontName = 'Helvetica';
end

function c = hx(h)
h = char(h);
if h(1) == '#', h = h(2:end); end
c = [hex2dec(h(1:2)), hex2dec(h(3:4)), hex2dec(h(5:6))] / 255;
end
