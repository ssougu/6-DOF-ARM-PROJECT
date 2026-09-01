<script lang="ts">
  import { arm } from '$lib/arm.svelte';

  let s = $derived(arm.state);
  let armed = $derived(s?.armed ?? false);
  let estopped = $derived(s?.estopped ?? false);
  let routing = $derived(!!s?.route);
  let speed = $derived(s?.speed ?? 1);

  let confirmZero = $state(false);

  function doZero() {
    arm.zero(null);
    confirmZero = false;
  }
</script>

<div class="bar">
  <button class="primary" onclick={() => arm.arm()} disabled={!arm.connected}>
    {estopped ? 'Re-arm' : 'Arm'}
  </button>
  <button onclick={() => arm.disarm()} disabled={!armed}>Disarm</button>
  <button onclick={() => arm.home()} disabled={!armed || estopped || routing}>
    Home
  </button>

  <div class="sep"></div>

  <label class="speed">
    <span>speed</span>
    <input type="range" min="0.05" max="1" step="0.05" value={speed}
           disabled={!arm.connected}
           oninput={(e) => arm.setSpeed(parseFloat(e.currentTarget.value))} />
    <b>{speed.toFixed(2)}</b>
  </label>

  <div class="sep"></div>

  {#if confirmZero}
    <span class="warn">Arm at home pose?</span>
    <button class="danger" onclick={doZero}>Yes, zero</button>
    <button onclick={() => (confirmZero = false)}>Cancel</button>
  {:else}
    <button onclick={() => (confirmZero = true)}
            disabled={!arm.connected || routing}>Zero here</button>
  {/if}
</div>

<style>
  .bar { display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
         background: var(--panel); border: 1px solid var(--line);
         border-radius: 12px; padding: 10px 14px; }
  .sep { width: 1px; align-self: stretch; background: var(--line); margin: 0 4px; }
  .speed { display: flex; align-items: center; gap: 8px; font-size: 11px;
           color: var(--muted); }
  .speed input { width: 130px; }
  .speed b { color: var(--fg); font-variant-numeric: tabular-nums; min-width: 30px; }
  .warn { font-size: 12px; color: var(--warn); }
</style>
