<script lang="ts">
  import { arm } from '$lib/arm.svelte';

  let s = $derived(arm.state);
  let running = $derived(s?.route ?? null);
  let selected = $state('');

  $effect(() => {
    if (!selected && arm.routes.length) selected = arm.routes[0];
  });

  let pct = $derived(
    running && running.total ? (running.step / running.total) * 100 : 0
  );
  let canRun = $derived(
    (s?.armed ?? false) && !(s?.estopped ?? false) && !running && !!selected
  );
</script>

<section class="panel">
  <header>
    <h3>Routines</h3>
    {#if running}
      <span class="tag live">{running.name} &middot; {running.step}/{running.total}</span>
    {/if}
  </header>

  <div class="row">
    <div class="picks">
      {#each arm.routes as r}
        <button class="pick" class:sel={selected === r}
                class:active={running?.name === r}
                disabled={!!running}
                onclick={() => (selected = r)}>{r}</button>
      {/each}
      {#if !arm.routes.length}
        <span class="none">no routines found</span>
      {/if}
    </div>

    <div class="acts">
      <button class="primary" disabled={!canRun}
              onclick={() => arm.runRoute(selected)}>Run</button>
      <button class="danger" disabled={!running}
              onclick={() => arm.stopRoute()}>Stop</button>
    </div>
  </div>

  <div class="progress" class:on={!!running}>
    <div class="fill" style="width:{pct}%"></div>
  </div>
</section>

<style>
  .panel { background: var(--panel); border: 1px solid var(--line);
           border-radius: 12px; padding: 12px 14px;
           display: flex; flex-direction: column; gap: 10px; }
  header { display: flex; align-items: center; gap: 10px; }
  h3 { margin: 0; font-size: 12px; font-weight: 650; letter-spacing: .1em;
       text-transform: uppercase; color: var(--muted); }
  .tag { font-size: 11px; padding: 2px 9px; border-radius: 999px;
         border: 1px solid var(--accent); color: var(--accent); }
  .tag.live { animation: blink 1.4s infinite; }
  @keyframes blink { 50% { opacity: .55; } }

  .row { display: flex; gap: 12px; align-items: center;
         justify-content: space-between; flex-wrap: wrap; }
  .picks { display: flex; gap: 6px; flex-wrap: wrap; }
  .pick { font-size: 12px; padding: 6px 12px; }
  .pick.sel { border-color: var(--accent); color: var(--accent); }
  .pick.active { border-color: var(--accent); background: color-mix(in srgb, var(--accent) 18%, transparent); }
  .none { font-size: 11px; color: var(--muted); }
  .acts { display: flex; gap: 6px; }

  .progress { height: 5px; border-radius: 999px; background: var(--bg2);
              overflow: hidden; opacity: .4; }
  .progress.on { opacity: 1; }
  .fill { height: 100%; background: var(--accent); transition: width .25s; }
</style>
