"""
AICoverGen Launcher v2
- Auto-detect terminal ANSI support
- Show WebUI progress in terminal
- Clean banner display
"""
import os
import sys
import socket
import subprocess
import time
import threading

# ─── Terminal Detection ───
def is_ansi_supported():
    if os.environ.get("WT_SESSION") or os.environ.get("TERM_PROGRAM"):
        return True
    if sys.platform == "win32":
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
            return True
        except Exception:
            return False
    return True

USE_COLOR = is_ansi_supported()

if USE_COLOR:
    C = {
        "reset": "\033[0m", "bold": "\033[1m",
        "cyan": "\033[96m", "green": "\033[92m",
        "yellow": "\033[93m", "red": "\033[91m",
        "gray": "\033[90m", "white": "\033[97m",
    }
else:
    C = {k: "" for k in ["reset","bold","cyan","green","yellow","red","gray","white"]}

def cprint(text, color="white", bold=False, end="\n"):
    prefix = C.get("bold","") if bold else ""
    color_code = C.get(color, "")
    print(f"{prefix}{color_code}{text}{C['reset']}", end=end)

def banner():
    print()
    cprint("  +--------------------------------------------------+", "cyan")
    cprint("  |                                                  |", "cyan")
    cprint("  |      /\\                                          |", "cyan")
    cprint("  |     /  \\     ", "cyan", end="")
    cprint("AI ", "white", end="")
    cprint("COVER ", "cyan", end="")
    cprint("GEN", "white", end="")
    cprint("                          |", "cyan")
    cprint("  |    /    \\    ", "cyan", end="")
    cprint("WebUI Smart Launcher", "gray", end="")
    cprint("                  |", "cyan")
    cprint("  |   /      \\   ", "cyan", end="")
    cprint("RTX 2050 4GB Optimized", "gray", end="")
    cprint("                 |", "cyan")
    cprint("  |                                                  |", "cyan")
    cprint("  +--------------------------------------------------+", "cyan")
    print()

def step(num, total, text):
    cprint(f"  [{num}/{total}] ", "cyan", end="")
    cprint(text, "white", bold=True)

def success(msg):
    cprint(f"    + {msg}", "green")

def warn(msg):
    cprint(f"    ! {msg}", "yellow")

def error(msg):
    cprint(f"    x {msg}", "red")

def info(msg):
    cprint(f"    {msg}", "gray")

def log_monitor(logfile, proc):
    """Monitor log file and print new lines to terminal"""
    last_pos = 0
    while proc.poll() is None:
        try:
            if os.path.exists(logfile):
                with open(logfile, "r", encoding="utf-8", errors="ignore") as f:
                    f.seek(last_pos)
                    new_lines = f.readlines()
                    last_pos = f.tell()
                    for line in new_lines:
                        line = line.rstrip()
                        if not line:
                            continue
                        # Color progress messages
                        if "[~]" in line:
                            cprint(f"    {line}", "cyan")
                        elif "cuda" in line.lower() or "half" in line.lower():
                            cprint(f"    {line}", "green")
                        elif "error" in line.lower():
                            cprint(f"    {line}", "red")
                        elif "Running on" in line or "http" in line:
                            cprint(f"    {line}", "white", bold=True)
                        elif "Traceback" in line or "Error" in line:
                            cprint(f"    {line}", "red")
                        else:
                            info(line)
        except Exception:
            pass
        time.sleep(0.5)

def kill_old_processes(port):
    result = subprocess.run(
        f'netstat -aon | findstr ":{port}" | findstr "LISTENING"',
        capture_output=True, text=True, shell=True
    )
    killed = False
    for line in result.stdout.strip().split("\n"):
        if line.strip():
            parts = line.split()
            if len(parts) >= 5:
                pid = parts[-1]
                warn(f"Found process on port {port}: PID {pid}")
                subprocess.run(f"taskkill /F /PID {pid}", capture_output=True, shell=True)
                success(f"Terminated PID {pid}")
                killed = True
    if not killed:
        info("No old processes found")
    return killed

def check_port(port):
    try:
        s = socket.socket()
        s.settimeout(1)
        result = s.connect_ex(("127.0.0.1", port))
        s.close()
        return result == 0
    except Exception:
        return False

def main():
    os.system("cls" if os.name == "nt" else "clear")
    banner()

    PYTHON = r"D:\Code\AICoverGen\.venv\Scripts\python.exe"
    SCRIPT = "src\\webui.py"
    HOST = "0.0.0.0"
    PORT = 7860
    LOGFILE = r"D:\Code\AICoverGen\webui.log"

    # Step 1
    step(1, 4, "Checking for old processes...")
    kill_old_processes(PORT)
    time.sleep(1)
    print()

    # Step 2
    step(2, 4, "Checking Python...")
    try:
        result = subprocess.run([PYTHON, "--version"], capture_output=True, text=True)
        ver = result.stdout.strip()
        success(f"{ver}")
    except Exception:
        error("Python not found!")
        error(f"Expected: {PYTHON}")
        input("Press Enter to exit...")
        sys.exit(1)
    print()

    # Step 3
    step(3, 4, "Starting WebUI...")
    info(f"Port: {PORT}")

    # Clear old log
    if os.path.exists(LOGFILE):
        os.remove(LOGFILE)

    proc = subprocess.Popen(
        [PYTHON, "-u", SCRIPT, "--listen", "--listen-host", HOST, "--listen-port", str(PORT)],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    success(f"Process started (PID: {proc.pid})")
    print()

    # Step 4
    step(4, 4, "Waiting for WebUI to start...")
    ready = False
    for i in range(1, 16):
        time.sleep(1)
        if check_port(PORT):
            ready = True
            break
        info(f"Connecting... {i}/15")

    print()

    if ready:
        cprint("  +--------------------------------------------------+", "green")
        cprint("  |                                                  |", "green")
        cprint("  |   ", "green", end="")
        cprint("  WebUI is running!  ", "white", bold=True, end="")
        cprint("                        |", "green")
        cprint("  |                                                  |", "green")
        cprint("  |   ", "green", end="")
        cprint("Local:   ", "gray", end="")
        cprint(f"http://127.0.0.1:{PORT}", "white", end="")
        pad = 39 - len(f"http://127.0.0.1:{PORT}")
        cprint(" " * pad + "|", "green")
        cprint("  |                                                  |", "green")
        cprint("  +--------------------------------------------------+", "green")
        print()
        cprint("  Open in browser:", "cyan")
        print(f"    > http://127.0.0.1:{PORT}")
        print()
        cprint("  First time?", "cyan")
        cprint('    1. Go to "Download model" tab', "gray")
        cprint("    2. Choose a voice model from Public Models", "gray")
        cprint('    3. Go to "Generate" tab', "gray")
        cprint("    4. Enter YouTube URL or local audio file", "gray")
        cprint("    5. Set Pitch and click Generate!", "gray")
        print()
        cprint("  --- Process Log ---", "cyan")
        print()

        # Monitor log in background thread
        monitor = threading.Thread(target=log_monitor, args=(LOGFILE, proc), daemon=True)
        monitor.start()

        # Keep process alive
        try:
            proc.wait()
        except KeyboardInterrupt:
            cprint("\n  Stopping WebUI...", "yellow")
            proc.terminate()
            proc.wait(timeout=5)
            success("WebUI stopped.")
    else:
        cprint("  +--------------------------------------------------+", "red")
        cprint("  |   ", "red", end="")
        cprint("  ERROR: WebUI failed to start!", "white", bold=True, end="")
        cprint("                        |", "red")
        cprint("  +--------------------------------------------------+", "red")
        print()
        cprint("  Check log:", "yellow")
        info(LOGFILE)
        print()
        try:
            with open(LOGFILE) as f:
                lines = f.readlines()
                for line in lines[-10:]:
                    info(line.rstrip())
        except Exception:
            pass
        print()
        input("Press Enter to exit...")

if __name__ == "__main__":
    main()
