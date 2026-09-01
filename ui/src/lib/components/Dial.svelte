<script lang="ts">
  let { deg = 0, min = -190, max = 190, live = true } = $props<{
    deg?: number | null; min?: number; max?: number; live?: boolean;
  }>();

  const R = 46, CX = 56, CY = 56;
  // dial sweeps -150..+150 screen degrees, mapped onto the joint's travel
  const SWEEP = 150;

  function toScreen(d: number) {
    const span = Math.max(max - min, 1e-6);
    const t = (d - min) / span;              // 0..1
    return -SWEEP + t * 2 * SWEEP;
  }
  function pt(a: number, r: number) {
    const rad = ((a - 90) * Math.PI) / 180;
    return [CX + r * Math.cos(rad), CY + r * Math.sin(rad)];
  }
  function arc(a0: number, a1: number, r: number) {
    const [x0, y0] = pt(a0, r), [x1, y1] = pt(a1, r);
    const large = Math.abs(a1 - a0) > 180 ? 1 : 0;
    return `M ${x0} ${y0} A ${r} ${r} 0 ${large} 1 ${x1} ${y1}`;
  }

  let shown = $derived(deg ?? 0);
  let angle = $derived(toScreen(Math.min(max, Math.max(min, shown))));
  let [nx, ny] = $derived(pt(angle, R - 8));
  let [zx, zy] = $derived(pt(toScreen(0), R - 8));
</script>

<svg viewBox="0 0 112 112" class="dial" class:off={!live}>
  <path d={arc(-SWEEP, SWEEP, R)} class="track" />
  <path d={arc(toScreen(0), angle, R)} class="sweep"
        class:neg={shown < 0} />
  <line x1={CX} y1={CY} x2={zx} y2={zy} class="zero" />
  <line x1={CX} y1={CY} x2={nx} y2={ny} class="needle" />
  <circle cx={CX} cy={CY} r="3.5" class="hub" />
</svg>

<style>
  .dial { width: 100%; max-width: 132px; display: block; margin: 0 auto; }
  .track { fill: none; stroke: var(--line); stroke-width: 7; stroke-linecap: round; }
  .sweep { fill: none; stroke: var(--accent); stroke-width: 7; stroke-linecap: round; }
  .sweep.neg { stroke: var(--accent2); }
  .needle { stroke: var(--fg); stroke-width: 2.5; stroke-linecap: round; }
  .zero { stroke: var(--muted); stroke-width: 1; stroke-dasharray: 2 3; }
  .hub { fill: var(--fg); }
  .dial.off .sweep { stroke: var(--line); }
  .dial.off .needle { stroke: var(--muted); }
</style>
