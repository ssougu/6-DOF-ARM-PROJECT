<script lang="ts">
  let { children } = $props();
</script>

{@render children()}

<style>
  :global(:root) {
    --bg:     #0e1116;
    --bg2:    #161b23;
    --panel:  #12171f;
    --line:   #262e3a;
    --fg:     #e6edf5;
    --fg2:    #b6c2d1;
    --muted:  #6c7a8c;
    --accent: #4ea3ff;
    --accent2:#ffa14e;
    --ok:     #3ddc84;
    --warn:   #ffc857;
    color-scheme: dark;
  }
  :global(*) { box-sizing: border-box; }
  :global(html), :global(body) { height: 100%; }
  :global(body) {
    margin: 0; background: var(--bg); color: var(--fg);
    font: 13px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif;
    -webkit-font-smoothing: antialiased;
    user-select: none;
  }
  :global(button) {
    background: var(--bg2); color: var(--fg2); cursor: pointer;
    border: 1px solid var(--line); border-radius: 7px;
    padding: 7px 13px; font: inherit; font-size: 12px;
    transition: border-color .12s, color .12s, background .12s;
  }
  :global(button:hover:not(:disabled)) { border-color: var(--muted); color: var(--fg); }
  :global(button:disabled) { opacity: .38; cursor: not-allowed; }
  :global(button.primary) {
    background: color-mix(in srgb, var(--accent) 16%, var(--bg2));
    border-color: color-mix(in srgb, var(--accent) 50%, var(--line));
    color: var(--accent); font-weight: 600;
  }
  :global(button.danger) {
    background: color-mix(in srgb, #b3151b 16%, var(--bg2));
    border-color: color-mix(in srgb, #b3151b 55%, var(--line)); color: #ff8f92;
  }
  :global(input) {
    background: var(--bg); color: var(--fg); border: 1px solid var(--line);
    border-radius: 7px; padding: 7px 10px; font: inherit; font-size: 12px;
  }
  :global(input:focus) { outline: none; border-color: var(--accent); }
  :global(input:disabled) { opacity: .38; }
  :global(input[type="range"]) { padding: 0; accent-color: var(--accent); }
  :global(::-webkit-scrollbar) { width: 9px; height: 9px; }
  :global(::-webkit-scrollbar-thumb) { background: var(--line); border-radius: 9px; }
</style>
