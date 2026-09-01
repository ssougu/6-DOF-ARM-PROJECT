<script lang="ts">
  import { arm } from '$lib/arm.svelte';
  let latched = $derived(arm.state?.estopped ?? false);
</script>

<button class="estop" class:latched onclick={() => arm.estop()}
        title="Stop everything (Esc)">
  <span class="big">E-STOP</span>
  <span class="sub">{latched ? 'LATCHED - press Arm' : 'Esc'}</span>
</button>

<style>
  .estop {
    background: #b3151b; color: #fff; border: 2px solid #6d0d10;
    border-radius: 10px; padding: 10px 22px; cursor: pointer;
    display: flex; flex-direction: column; align-items: center; gap: 2px;
    box-shadow: 0 2px 0 #6d0d10, 0 6px 18px rgba(179, 21, 27, .35);
    transition: transform .05s, background .15s;
  }
  .estop:hover { background: #cf1a21; }
  .estop:active { transform: translateY(2px); box-shadow: 0 0 0 #6d0d10; }
  .estop.latched { background: #6d0d10; animation: pulse 1.1s infinite; }
  .big { font-size: 19px; font-weight: 800; letter-spacing: .12em; }
  .sub { font-size: 10px; opacity: .75; letter-spacing: .06em; }
  @keyframes pulse { 50% { box-shadow: 0 0 0 6px rgba(179,21,27,.25); } }
</style>
