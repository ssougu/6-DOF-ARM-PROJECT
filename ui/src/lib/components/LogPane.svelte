<script lang="ts">
  import { arm } from '$lib/arm.svelte';
  let box: HTMLDivElement | null = $state(null);

  $effect(() => {
    arm.logs.length;
    if (box) box.scrollTop = box.scrollHeight;
  });
</script>

<section class="panel">
  <h3>Log</h3>
  <div class="lines" bind:this={box}>
    {#each arm.logs as l}
      <div class="line {l.level}">{l.msg}</div>
    {:else}
      <div class="line muted">waiting for the control server...</div>
    {/each}
  </div>
</section>

<style>
  .panel { background: var(--panel); border: 1px solid var(--line);
           border-radius: 12px; padding: 12px 14px; display: flex;
           flex-direction: column; gap: 8px; min-height: 0; }
  h3 { margin: 0; font-size: 12px; font-weight: 650; letter-spacing: .1em;
       text-transform: uppercase; color: var(--muted); }
  .lines { overflow-y: auto; flex: 1; min-height: 90px; max-height: 160px;
           font-family: ui-monospace, Consolas, monospace; font-size: 11px;
           line-height: 1.55; }
  .line { white-space: pre-wrap; word-break: break-word; color: var(--fg2); }
  .line.error { color: #ff8080; }
  .line.warn { color: var(--warn); }
  .line.muted { color: var(--muted); }
</style>
