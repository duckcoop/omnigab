"""
omnigab Desktop Launcher
==========================
Opens omnigab as a desktop-style window using Edge/Chrome app mode.
No extra dependencies needed - uses the browser you already have but
strips away tabs, address bar, and bookmarks so it looks like a native app.

Just double-click omnigab.bat to run.
"""

import sys
import os
import time
import threading
import socket
import subprocess
import shutil

SRC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "src")
sys.path.insert(0, SRC_DIR)
os.chdir(SRC_DIR)


def wait_for_server(port, timeout=120):
    """Wait until the server is accepting connections."""
    start = time.time()
    while time.time() - start < timeout:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                return True
        except (ConnectionRefusedError, OSError):
            time.sleep(0.5)
    return False


def start_server(port):
    """Start the FastAPI server in this thread."""
    import uvicorn
    from web_app import app
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


def find_browser():
    """Find Edge or Chrome to launch in app mode."""
    candidates = [
        # Edge (comes with Windows 10/11)
        os.path.expandvars(r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"),
        os.path.expandvars(r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"),
        # Chrome
        os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
        # Brave
        os.path.expandvars(r"%ProgramFiles%\BraveSoftware\Brave-Browser\Application\brave.exe"),
        os.path.expandvars(r"%LocalAppData%\BraveSoftware\Brave-Browser\Application\brave.exe"),
    ]
    for path in candidates:
        if os.path.exists(path):
            return path
    return None


def open_as_app(url):
    """Open URL in browser app mode (no tabs, no address bar, looks native)."""
    browser = find_browser()
    if browser:
        # --app mode removes all browser chrome - looks like a real desktop app
        subprocess.Popen([
            browser,
            f"--app={url}",
            "--window-size=1100,750",
            "--disable-extensions",
            "--new-window",
        ])
        return True
    return False


def main():
    port = 8080

    # Check if server is already running
    already_running = False
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.5):
            already_running = True
            print(f"Server already running on port {port}")
    except (ConnectionRefusedError, OSError):
        pass

    if not already_running:
        print()
        print("  ╔══════════════════════════════════════╗")
        print("  ║        omnigab                     ║")
        print("  ║  Loading model & building index...   ║")
        print("  ║  This may take a minute on first run ║")
        print("  ╚══════════════════════════════════════╝")
        print()

        server_thread = threading.Thread(target=start_server, args=(port,), daemon=True)
        server_thread.start()

        print("  Waiting for server...", end="", flush=True)
        if not wait_for_server(port):
            print(" FAILED")
            print("\n  ERROR: Server did not start within 120 seconds.")
            input("\n  Press Enter to exit...")
            sys.exit(1)
        print(" ready!")

    url = f"http://127.0.0.1:{port}"

    if open_as_app(url):
        print(f"\n  App window opened.")
        print(f"  Keep this console open (it runs the server).")
        print(f"  Close this window to shut everything down.\n")
    else:
        # Fallback: open in default browser normally
        import webbrowser
        webbrowser.open(url)
        print(f"\n  Opened in your default browser: {url}")
        print(f"  Keep this console open.\n")

    # Keep the main thread alive so the server stays running
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n  Shutting down...")


if __name__ == "__main__":
    main()
