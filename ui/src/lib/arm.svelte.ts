// Live link to arm_server.py. One instance, shared by every component.

export type Joint = {
  id: number; name: string; kind: string;
  enabled: boolean; connected: boolean;
  deg: number | null; vel_dps: number | null;
  moving: boolean; fault: number;
  voltage: number | null; temp: number | null;
  min_deg: number; max_deg: number; home_deg: number;
};

export type Route = { name: string; step: number; total: number };

export type ArmState = {
  ts: number; sim: boolean;
  armed: boolean; estopped: boolean; speed: number;
  busy: string | null; route: Route | null;
  joints: Joint[];
};

export type LogLine = { level: string; msg: string; t: number };

const URL = 'ws://127.0.0.1:8787';

class ArmLink {
  connected = $state(false);
  state = $state<ArmState | null>(null);
  routes = $state<string[]>([]);
  logs = $state<LogLine[]>([]);
  lastError = $state('');

  #ws: WebSocket | null = null;
  #retry = 0;
  #timer: ReturnType<typeof setTimeout> | null = null;

  start() {
    if (!this.#ws) this.#open();
  }

  #open() {
    try {
      this.#ws = new WebSocket(URL);
    } catch {
      this.#schedule();
      return;
    }
    const ws = this.#ws;
    ws.onopen = () => {
      this.connected = true;
      this.#retry = 0;
      this.send({ cmd: 'list_routes' });
    };
    ws.onclose = () => {
      this.connected = false;
      this.#ws = null;
      this.#schedule();
    };
    ws.onmessage = (ev) => this.#msg(String(ev.data));
  }

  #schedule() {
    if (this.#timer) return;
    const wait = Math.min(3000, 300 * Math.pow(1.6, this.#retry++));
    this.#timer = setTimeout(() => {
      this.#timer = null;
      this.#open();
    }, wait);
  }

  #msg(raw: string) {
    let m: any;
    try { m = JSON.parse(raw); } catch { return; }
    if (m.type === 'state') this.state = m as ArmState;
    else if (m.type === 'routes') this.routes = m.items ?? [];
    else if (m.type === 'log') this.#log(m.level, m.msg);
    else if (m.type === 'error') this.#err(m.msg);
    else if (m.type === 'ack' && !m.ok) this.#err(`${m.cmd}: ${m.msg}`);
  }

  #log(level: string, msg: string) {
    const next = [...this.logs, { level, msg, t: Date.now() }];
    this.logs = next.length > 150 ? next.slice(-150) : next;
  }

  #err(msg: string) {
    this.lastError = msg;
    this.#log('error', msg);
    setTimeout(() => { if (this.lastError === msg) this.lastError = ''; }, 6000);
  }

  send(obj: Record<string, unknown>) {
    if (this.#ws && this.#ws.readyState === WebSocket.OPEN) {
      this.#ws.send(JSON.stringify(obj));
    }
  }

  arm()    { this.send({ cmd: 'arm' }); }
  disarm() { this.send({ cmd: 'disarm' }); }
  estop()  { this.send({ cmd: 'estop' }); }
  home()   { this.send({ cmd: 'home' }); }
  enable(id: number)  { this.send({ cmd: 'enable_joint', id }); }
  disable(id: number) { this.send({ cmd: 'disable_joint', id }); }
  jog(id: number, delta_deg: number) { this.send({ cmd: 'jog', id, delta_deg }); }
  moveTo(id: number, deg: number)    { this.send({ cmd: 'move_to', id, deg }); }
  setSpeed(value: number)  { this.send({ cmd: 'set_speed', value }); }
  zero(ids: number[] | null) { this.send({ cmd: 'zero', ids, confirm: true }); }
  runRoute(name: string) { this.send({ cmd: 'run_route', name }); }
  stopRoute() { this.send({ cmd: 'stop_route' }); }
}

export const arm = new ArmLink();
