<script lang="ts">
  // SIM <-> LIVE without relaunching. Entering LIVE is deliberately two
  // clicks: the whole point of the SIM default is that no single stray action
  // can energize a motor, and a one-click toggle would hand that back.
  import { arm } from '$lib/arm.svelte';
  import { inTauri, restartServer } from '$lib/tauri';

  let s = $derived(arm.state);
  // The running server is the authority on the mode; the Rust side only knows
  // what it launched, and a hand-started server may disagree.
  let sim = $derived(s?.sim ?? true);
  let routing = $derived(!!s?.route);
  let armed = $derived(s?.armed ?? false);

  let confirming = $state(false);
  let switching = $state(false);
  let error = $state('');

  // Switching restarts the server, which drops every joint. Refuse mid-route
  // rather than yanking the ports out from under a running one.
  let blocked = $derived(
    !inTauri ? 'switch modes from the desktop app (or relaunch with ARM_UI_SIM)'
    : routing ? 'stop the running route first'
    : ''
  );

  async function go(next: boolean) {
    confirming = false;
    switching = true;
    error = '';
    try {
      // De-energize through the server rather than letting the restart's kill
      // do it -- see the `shutdown` command in arm_server.py.
      if (arm.connected) {
        if (armed) arm.disarm();
        arm.shutdown();
        await arm.waitForClose(3000);
      }
      await restartServer(next);
      // ArmLink reconnects on its own backoff; the badge follows the new
      // server's own state broadcast, so we deliberately don't set it here.
    } catch (e) {
      error = String(e instanceof Error ? e.message : e);
    } finally {
      switching = false;
    }
  }

  function onClick() {
    if (blocked || switching) return;
    if (sim) confirming = true;   // into LIVE: confirm
    else go(true);                // back to SIM: no confirmation needed
  }
</script>

<div class="wrap">
  <button
    class="mode"
    class:sim
    class:live={!sim}
    disabled={!!blocked || switching || !arm.connected}
    title={blocked || (sim ? 'switch to live hardware' : 'switch back to simulation')}
    onclick={onClick}
  >
    {switching ? 'switching...' : sim ? 'SIM' : 'LIVE'}
  </button>

  {#if confirming}
    <div class="confirm" role="alertdialog" aria-label="Confirm live hardware">
      <b>Switch to LIVE hardware?</b>
      <p>
        Commands will drive the real J1 (moteus) and J2 (stepper). Before
        moving anything: put the arm at its home pose by hand and
        <em>Zero here</em> &mdash; J2 has no absolute reference, so its zero is
        wherever it powered up.
      </p>
      <div class="row">
        <button class="danger" onclick={() => go(false)}>Yes, go live</button>
        <button onclick={() => (confirming = false)}>Cancel</button>
      </div>
    </div>
  {/if}

  {#if error}<span class="err" title={error}>switch failed</span>{/if}
</div>

<style>
  .wrap { position: relative; display: inline-flex; align-items: center; gap: 6px; }

  .mode {
    font-size: 10px; padding: 3px 9px; border-radius: 999px; cursor: pointer;
    letter-spacing: .07em; text-transform: uppercase; font-weight: 600;
    background: transparent; border: 1px solid var(--line);
  }
  .mode.sim  { color: var(--accent);
               border-color: color-mix(in srgb, var(--accent) 45%, var(--line)); }
  .mode.live { color: var(--warn); border-color: var(--warn);
               background: color-mix(in srgb, var(--warn) 12%, transparent); }
  .mode:disabled { opacity: .55; cursor: not-allowed; }

  .confirm {
    position: absolute; top: calc(100% + 8px); left: 0; z-index: 20;
    width: 290px; padding: 12px 14px; border-radius: 10px;
    background: var(--panel); border: 1px solid var(--warn);
    box-shadow: 0 10px 28px rgb(0 0 0 / .45);
  }
  .confirm b { font-size: 12px; color: var(--warn); }
  .confirm p { margin: 7px 0 10px; font-size: 11px; line-height: 1.5;
               color: var(--muted); }
  .confirm em { color: var(--fg); font-style: normal; font-weight: 600; }
  .row { display: flex; gap: 8px; }

  .err { font-size: 10px; color: #ff8f92; }
</style>
