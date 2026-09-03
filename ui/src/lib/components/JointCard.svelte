<script lang="ts">
  import { arm, type Joint } from '$lib/arm.svelte';
  import Dial from './Dial.svelte';

  let { j } = $props<{ j: Joint }>();

  let goto = $state('');
  let canMove = $derived(
    j.enabled && j.connected &&
    (arm.state?.armed ?? false) && !(arm.state?.estopped ?? false) &&
    !arm.state?.route
  );

  const JOGS = [-10, -5, -1, 1, 5, 10];

  function submitGoto(e: Event) {
    e.preventDefault();
    const v = parseFloat(goto);
    if (!Number.isFinite(v)) return;
    arm.moveTo(j.id, v);
    goto = '';
  }
</script>

<section class="card" class:disabled={!j.enabled} class:faulted={j.fault > 0}>
  <header>
    <div class="title">
      <h2>{j.name}</h2>
      <div class="sub">
        <span class="kind">{j.kind}</span>
        {#if j.link && !(arm.state?.sim ?? true)}
          <span class="link" title="where this joint is addressed">{j.link}</span>
        {/if}
      </div>
    </div>
    <button class="toggle" class:on={j.enabled}
            class:pending={j.enabled && !j.connected}
            onclick={() => (j.enabled ? arm.disable(j.id) : arm.enable(j.id))}
            title={!j.enabled ? 'Switch on'
                   : !j.connected ? 'Switched on but not connected yet'
                   : 'Switch this joint off (de-energize)'}>
      <span class="knob"></span>
      <span class="lbl">{j.enabled ? 'ON' : 'OFF'}</span>
    </button>
  </header>

  <Dial deg={j.deg} min={j.min_deg} max={j.max_deg} live={j.enabled} />

  <div class="readout">
    {#if !j.enabled}
      <span class="big muted">--</span><span class="unit">disabled</span>
    {:else if !j.connected}
      <span class="big muted">--</span><span class="unit">not connected</span>
    {:else if j.deg === null}
      <span class="big muted">--</span><span class="unit">no telemetry</span>
    {:else}
      <span class="big">{j.deg.toFixed(2)}</span><span class="unit">deg</span>
    {/if}
  </div>

  <div class="chips">
    {#if !j.enabled}
      <span class="chip">de-energized</span>
    {:else if !j.connected}
      <!-- Switched on, but the port is not open yet: joints are built lazily,
           so nothing is connected until Arm (or a fresh off/on). -->
      <span class="chip warn">switched on &mdash; press Arm to connect</span>
    {:else if j.deg !== null}
      <span class="chip" class:live={j.moving}>
        {j.moving ? 'moving' : 'idle'}
      </span>
      <span class="chip">{(j.vel_dps ?? 0).toFixed(1)} deg/s</span>
      {#if j.fault > 0}<span class="chip bad">fault {j.fault}</span>{/if}
      {#if j.voltage !== null}<span class="chip">{j.voltage.toFixed(1)} V</span>{/if}
      {#if j.temp !== null}<span class="chip">{j.temp.toFixed(0)} C</span>{/if}
    {/if}
  </div>

  <div class="jog">
    {#each JOGS as d}
      <button disabled={!canMove} onclick={() => arm.jog(j.id, d)}>
        {d > 0 ? '+' : ''}{d}
      </button>
    {/each}
  </div>

  <form class="goto" onsubmit={submitGoto}>
    <input type="number" step="0.1" placeholder="go to deg"
           bind:value={goto} disabled={!canMove}
           min={j.min_deg} max={j.max_deg} />
    <button type="submit" disabled={!canMove || goto === ''}>Go</button>
  </form>

  <div class="limits">
    limits {j.min_deg.toFixed(0)} to {j.max_deg.toFixed(0)} deg
  </div>
</section>

<style>
  .card {
    background: var(--panel); border: 1px solid var(--line);
    border-radius: 12px; padding: 14px 16px 12px;
    display: flex; flex-direction: column; gap: 10px;
  }
  .card.disabled { opacity: .62; }
  .card.faulted { border-color: #b3151b; }
  header { display: flex; justify-content: space-between; align-items: flex-start; }
  .title { display: flex; flex-direction: column; gap: 2px; }
  h2 { margin: 0; font-size: 14px; font-weight: 650; letter-spacing: .02em; }
  .sub { display: flex; align-items: center; gap: 6px; }
  .kind { font-size: 10px; color: var(--muted); text-transform: uppercase;
          letter-spacing: .08em; }
  .link { font-family: ui-monospace, Consolas, monospace; font-size: 10px;
          color: var(--muted); background: var(--bg2); padding: 1px 6px;
          border-radius: 4px; }

  .toggle {
    display: flex; align-items: center; gap: 7px; cursor: pointer;
    background: var(--bg2); border: 1px solid var(--line);
    border-radius: 999px; padding: 4px 10px 4px 5px; color: var(--muted);
    font-size: 11px; font-weight: 700; letter-spacing: .08em;
  }
  .toggle .knob {
    width: 12px; height: 12px; border-radius: 50%;
    background: var(--muted); transition: background .15s, box-shadow .15s;
  }
  .toggle.on { color: var(--ok); border-color: color-mix(in srgb, var(--ok) 45%, var(--line)); }
  .toggle.on .knob { background: var(--ok); box-shadow: 0 0 8px var(--ok); }
  /* on, but the port is not open yet -- green here would claim readiness */
  .toggle.pending { color: var(--warn);
                    border-color: color-mix(in srgb, var(--warn) 45%, var(--line)); }
  .toggle.pending .knob { background: var(--warn); box-shadow: none; }

  .readout { text-align: center; display: flex; align-items: baseline;
             justify-content: center; gap: 6px; }
  .big { font-size: 30px; font-weight: 300; font-variant-numeric: tabular-nums;
         letter-spacing: -.01em; }
  .big.muted { color: var(--muted); }
  .unit { font-size: 11px; color: var(--muted); }

  .chips { display: flex; flex-wrap: wrap; gap: 5px; justify-content: center;
           min-height: 20px; }
  .chip { font-size: 10px; padding: 2px 7px; border-radius: 999px;
          background: var(--bg2); color: var(--muted); border: 1px solid var(--line); }
  .chip.live { color: var(--accent); border-color: var(--accent); }
  .chip.warn { color: var(--warn);
               border-color: color-mix(in srgb, var(--warn) 45%, var(--line)); }
  .chip.bad { color: #ff6b6b; border-color: #b3151b; }

  .jog { display: grid; grid-template-columns: repeat(6, 1fr); gap: 4px; }
  .jog button { font-variant-numeric: tabular-nums; padding: 7px 0; font-size: 12px; }

  .goto { display: flex; gap: 6px; }
  .goto input { flex: 1; min-width: 0; }
  .goto button { padding-inline: 16px; }

  .limits { font-size: 10px; color: var(--muted); text-align: center; }
</style>
