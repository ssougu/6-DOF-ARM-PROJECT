// Tauri IPC. The app also runs as a plain page (`vite dev` at :1420) against a
// hand-started arm_server.py -- there is no Rust side there, so every helper
// degrades to "not available" rather than throwing.

export type ServerStatus = { running: boolean; port: number; sim: boolean };

/** True only inside the desktop shell, where the Rust commands exist. */
export const inTauri =
  typeof window !== 'undefined' && '__TAURI_INTERNALS__' in window;

async function call<T>(cmd: string, args?: Record<string, unknown>): Promise<T> {
  const { invoke } = await import('@tauri-apps/api/core');
  return invoke<T>(cmd, args);
}

/** Relaunch arm_server.py, optionally flipping SIM/LIVE. */
export function restartServer(sim?: boolean): Promise<ServerStatus> {
  if (!inTauri) return Promise.reject(new Error('not running in the desktop app'));
  return call<ServerStatus>('restart_server', { sim });
}

/** Whether the Rust side still has a live server child, and in which mode. */
export async function serverStatus(): Promise<ServerStatus | null> {
  if (!inTauri) return null;
  try {
    return await call<ServerStatus>('server_status');
  } catch {
    return null;
  }
}
