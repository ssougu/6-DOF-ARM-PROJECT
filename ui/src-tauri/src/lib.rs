// Thin Tauri shell. The arm logic lives in Python (host/arm_server.py); this
// process only owns that server's lifetime so closing the window can never
// leave a control server holding COM ports.

use std::path::PathBuf;
use std::process::{Child, Command};
use std::sync::Mutex;

use tauri::{Manager, State};

#[derive(Default)]
struct Server {
    child: Mutex<Option<Child>>,
    sim: Mutex<bool>,
}

#[derive(serde::Serialize)]
struct Status {
    running: bool,
    port: u16,
    sim: bool,
}

const PORT: u16 = 8787;

/// Walk up from the executable / cwd looking for host/arm_server.py.
fn find_host_dir() -> Option<PathBuf> {
    let mut roots: Vec<PathBuf> = Vec::new();
    if let Ok(cwd) = std::env::current_dir() {
        roots.push(cwd);
    }
    if let Ok(exe) = std::env::current_exe() {
        if let Some(p) = exe.parent() {
            roots.push(p.to_path_buf());
        }
    }
    for root in roots {
        let mut dir = root.as_path();
        for _ in 0..6 {
            let cand = dir.join("host").join("arm_server.py");
            if cand.is_file() {
                return Some(dir.join("host"));
            }
            match dir.parent() {
                Some(p) => dir = p,
                None => break,
            }
        }
    }
    None
}

fn spawn_server(sim: bool) -> Result<Child, String> {
    let host = find_host_dir().ok_or_else(|| {
        "could not locate host/arm_server.py -- run the app from inside the repo"
            .to_string()
    })?;
    let mut cmd = Command::new("python");
    cmd.arg("-u")
        .arg(host.join("arm_server.py"))
        .arg("--port")
        .arg(PORT.to_string())
        // so a hard-killed / crashed UI can't leave motors energized
        .arg("--parent-pid")
        .arg(std::process::id().to_string())
        .current_dir(&host);
    if sim {
        cmd.arg("--sim");
    }
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        cmd.creation_flags(0x0800_0000); // CREATE_NO_WINDOW
    }
    cmd.spawn()
        .map_err(|e| format!("could not start python: {e}. Is Python on PATH?"))
}

fn kill(state: &Server) {
    if let Ok(mut guard) = state.child.lock() {
        if let Some(mut c) = guard.take() {
            let _ = c.kill();
            let _ = c.wait();
        }
    }
}

#[tauri::command]
fn server_status(state: State<Server>) -> Status {
    let running = state
        .child
        .lock()
        .ok()
        .and_then(|mut g| g.as_mut().map(|c| matches!(c.try_wait(), Ok(None))))
        .unwrap_or(false);
    Status {
        running,
        port: PORT,
        sim: *state.sim.lock().unwrap(),
    }
}

#[tauri::command]
fn restart_server(state: State<Server>, sim: Option<bool>) -> Result<Status, String> {
    kill(&state);
    let want = sim.unwrap_or(*state.sim.lock().unwrap());
    let child = spawn_server(want)?;
    *state.child.lock().unwrap() = Some(child);
    *state.sim.lock().unwrap() = want;
    Ok(Status { running: true, port: PORT, sim: want })
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .manage(Server::default())
        .invoke_handler(tauri::generate_handler![server_status, restart_server])
        .setup(|app| {
            // ARM_UI_SIM=0 launches against real hardware; default is sim so a
            // stray double-click can never energize a motor.
            let sim = std::env::var("ARM_UI_SIM")
                .map(|v| v != "0" && v.to_lowercase() != "false")
                .unwrap_or(true);
            let state = app.state::<Server>();
            match spawn_server(sim) {
                Ok(child) => {
                    *state.child.lock().unwrap() = Some(child);
                    *state.sim.lock().unwrap() = sim;
                    println!("arm_server started (sim={sim}) on port {PORT}");
                }
                Err(e) => eprintln!("arm_server did not start: {e}"),
            }
            Ok(())
        })
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::Destroyed = event {
                kill(&window.state::<Server>());
            }
        })
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(|app, event| {
            if let tauri::RunEvent::ExitRequested { .. } = event {
                kill(&app.state::<Server>());
            }
        });
}
