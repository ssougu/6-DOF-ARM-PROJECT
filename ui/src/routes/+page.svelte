<script lang="ts">
  import { onMount } from 'svelte';
  import { arm } from '$lib/arm.svelte';
  import EStop from '$lib/components/EStop.svelte';
  import ArmBar from '$lib/components/ArmBar.svelte';
  import ModeSwitch from '$lib/components/ModeSwitch.svelte';
  import JointCard from '$lib/components/JointCard.svelte';
  import RoutinePanel from '$lib/components/RoutinePanel.svelte';
  import LogPane from '$lib/components/LogPane.svelte';

  onMount(() => {
    arm.start();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') { e.preventDefault(); arm.estop(); }
    };
    // Closing the window should de-energize through the server rather than
    // leaving it to the hard kill; Rust waits ~800 ms for this to land.
    const onBye = () => arm.shutdown();
    window.addEventListener('beforeunload', onBye);
    window.addEventListener('keydown', onKey);
    return () => {
      window.removeEventListener('keydown', onKey);
      window.removeEventListener('beforeunload', onBye);
    };
  });

  let s = $derived(arm.state);
  let joints = $derived(s?.joints ?? []);
  let estopped = $derived(s?.estopped ?? false);
</script>

<div class="app" class:alarm={estopped}>
  <header class="top">
    <div class="brand">
      <h1>6-DOF ARM</h1>
      <span class="badge" class:on={arm.connected}>
        {arm.connected ? 'connected' : 'no server'}
      </span>
      {#if s}<ModeSwitch />{/if}
      {#if s?.armed}<span class="badge armed">armed</span>{/if}
      {#if s?.busy}<span class="badge busy">{s.busy}</span>{/if}
    </div>
    <EStop />
  </header>

  {#if !arm.connected}
    <div class="banner">
      Control server not reachable on ws://127.0.0.1:8787 &mdash; start it with
      <code>python host/arm_server.py --sim</code>. Retrying...
    </div>
  {:else if arm.lastError}
    <div class="banner err">{arm.lastError}</div>
  {/if}

  <ArmBar />

  <div class="joints">
    {#each joints as j (j.id)}
      <JointCard {j} />
    {:else}
      <div class="empty">waiting for joint telemetry...</div>
    {/each}
  </div>

  <RoutinePanel />
  <LogPane />
</div>

<style>
  .app {
    min-height: 100vh; padding: 16px; display: flex; flex-direction: column;
    gap: 12px; max-width: 1180px; margin: 0 auto;
  }
  .app.alarm { box-shadow: inset 0 0 0 3px #b3151b; }

  .top { display: flex; align-items: center; justify-content: space-between;
         gap: 16px; }
  .brand { display: flex; align-items: center; gap: 9px; flex-wrap: wrap; }
  h1 { margin: 0; font-size: 15px; font-weight: 700; letter-spacing: .16em; }

  .badge { font-size: 10px; padding: 3px 9px; border-radius: 999px;
           border: 1px solid var(--line); color: var(--muted);
           letter-spacing: .07em; text-transform: uppercase; }
  .badge.on { color: var(--ok); border-color: color-mix(in srgb, var(--ok) 45%, var(--line)); }
  .badge.armed { color: var(--ok); border-color: var(--ok); }
  .badge.busy { color: var(--accent); border-color: var(--accent); }

  .banner { background: color-mix(in srgb, var(--warn) 12%, var(--panel));
            border: 1px solid color-mix(in srgb, var(--warn) 40%, var(--line));
            color: var(--warn); border-radius: 10px; padding: 10px 14px;
            font-size: 12px; }
  .banner.err { background: color-mix(in srgb, #b3151b 14%, var(--panel));
                border-color: #b3151b; color: #ff8f92; }
  code { font-family: ui-monospace, Consolas, monospace; font-size: 11px;
         background: var(--bg2); padding: 1px 6px; border-radius: 4px; }

  .joints { display: grid; gap: 12px;
            grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); }
  .empty { color: var(--muted); font-size: 12px; padding: 24px;
           text-align: center; border: 1px dashed var(--line);
           border-radius: 12px; }
</style>
