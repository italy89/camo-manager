"""
Browser Server - Chạy browser như một server, lắng nghe lệnh qua socket
Đại Ca mở ACC001 một lần → browser chạy nền mãi
Script khác kết nối vào làm tiếp từ chỗ dở 🦊

Chạy server:
    python browser_server.py start ACC001

Kết nối từ script khác:
    from browser_client import BrowserClient
    with BrowserClient("ACC001") as page:
        page.goto("...")
        page.screenshot(path="test.png")

Dừng:
    python browser_server.py stop ACC001
    python browser_server.py status  (xem tất cả)
"""

import json
import os
import signal
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Optional

BASE_DIR = Path(__file__).parent
PROFILES_DIR = BASE_DIR / "profiles"
LOCKS_DIR = BASE_DIR / "locks"
LOCKS_DIR.mkdir(exist_ok=True)

# Port range cho CDP debugging (mỗi profile 1 port)
CDP_BASE_PORT = 19222


def _profile_port(name: str) -> int:
    """Tính port duy nhất cho mỗi profile."""
    # Hash tên profile để ra port cố định
    h = sum(ord(c) * i for i, c in enumerate(name, 1))
    return CDP_BASE_PORT + (h % 100)


def _lock_path(name: str) -> Path:
    return LOCKS_DIR / f"{name}.lock.json"


def _is_pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def _read_lock(name: str) -> Optional[dict]:
    p = _lock_path(name)
    if not p.exists():
        return None
    try:
        with open(p) as f:
            lock = json.load(f)
        if not _is_pid_alive(lock.get("pid", 0)):
            p.unlink(missing_ok=True)
            return None
        return lock
    except Exception:
        return None


def is_running(name: str) -> bool:
    return _read_lock(name) is not None


def get_cdp_url(name: str) -> Optional[str]:
    lock = _read_lock(name)
    if lock:
        return lock.get("cdp_url")
    return None


def status_all() -> list:
    results = []
    for f in LOCKS_DIR.glob("*.lock.json"):
        try:
            with open(f) as fh:
                lock = json.load(fh)
            name = lock["name"]
            if _is_pid_alive(lock["pid"]):
                uptime = int(time.time() - lock["started_at"])
                m, s = divmod(uptime, 60)
                h, m = divmod(m, 60)
                results.append(f"🟢 {name} | PID {lock['pid']} | CDP {lock['cdp_url']} | uptime {h:02d}:{m:02d}:{s:02d}")
            else:
                f.unlink(missing_ok=True)
        except Exception:
            pass
    return results or ["(không có browser nào đang chạy)"]


def start_browser_daemon(name: str, headless: bool = True) -> dict:
    """
    Khởi động browser daemon cho profile, chạy như tiến trình nền.
    Trả về thông tin CDP URL để kết nối.
    """
    # Kiểm tra đã chạy chưa
    existing = _read_lock(name)
    if existing:
        print(f"✅ [{name}] Đã đang chạy tại {existing['cdp_url']}")
        return existing

    config_path = PROFILES_DIR / name / "config.json"
    if not config_path.exists():
        raise ValueError(f"Profile '{name}' không tồn tại!")

    cdp_port = _profile_port(name)

    # Chạy script launch trong subprocess riêng (daemon)
    script = f"""
import sys, os, json, time, signal
sys.path.insert(0, {repr(str(BASE_DIR))})

from camoufox import Camoufox
from browserforge.fingerprints.generator import Screen as BFScreen
from pathlib import Path
import json

BASE_DIR = Path({repr(str(BASE_DIR))})
PROFILES_DIR = BASE_DIR / "profiles"
LOCKS_DIR = BASE_DIR / "locks"
name = {repr(name)}

with open(PROFILES_DIR / name / "config.json") as f:
    config = json.load(f)

browser_data_dir = str(PROFILES_DIR / name / "browser_data")
cdp_port = {cdp_port}

kwargs = {{
    "headless": {headless},
    "persistent_context": True,
    "user_data_dir": browser_data_dir,
    "geoip": True,
    "screen": BFScreen(min_width=1920, max_width=1920, min_height=1080, max_height=1080),
    "viewport": {{"width": 1920, "height": 1080}},
    "args": [f"--remote-debugging-port={{cdp_port}}"],
}}

if config.get("proxy"):
    proxy_str = config["proxy"]
    proxy_type = config.get("proxy_type", "http")
    host_port = proxy_str.split("@")[-1]
    parts = host_port.split(":")
    proxy_dict = {{"server": f"{{parts[0]}}:{{parts[1]}}"}}
    kwargs["proxy"] = proxy_dict

camo = Camoufox(**kwargs)
context = camo.__enter__()
pages = context.pages
page = pages[0] if pages else context.new_page()

# Ghi lock file
lock_data = {{
    "name": name,
    "pid": os.getpid(),
    "cdp_url": f"http://localhost:{{cdp_port}}",
    "started_at": time.time(),
}}
with open(LOCKS_DIR / f"{{name}}.lock.json", "w") as f:
    json.dump(lock_data, f, indent=2)

print(f"READY:{{cdp_port}}", flush=True)

# Signal handler để graceful shutdown
def shutdown(sig, frame):
    print("Shutting down...", flush=True)
    try: camo.__exit__(None, None, None)
    except: pass
    (LOCKS_DIR / f"{{name}}.lock.json").unlink(missing_ok=True)
    sys.exit(0)

signal.signal(signal.SIGTERM, shutdown)
signal.signal(signal.SIGINT, shutdown)

# Giữ process sống mãi
while True:
    time.sleep(1)
"""

    # Tìm python trong virtualenv
    venv_python = BASE_DIR.parent / "camoufox-env" / "bin" / "python3"
    if not venv_python.exists():
        venv_python = sys.executable

    proc = subprocess.Popen(
        [str(venv_python), "-c", script],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,  # Detach từ parent process
    )

    # Chờ READY signal
    print(f"⏳ [{name}] Đang khởi động browser (port {cdp_port})...")
    ready = False
    for _ in range(60):  # Chờ tối đa 60 giây
        line = proc.stdout.readline()
        if line:
            line = line.decode().strip()
            print(f"   [{name}] {line}")
            if line.startswith("READY:"):
                ready = True
                break
        if proc.poll() is not None:
            err = proc.stderr.read().decode()
            raise RuntimeError(f"Browser daemon crashed!\n{err}")
        time.sleep(1)

    if not ready:
        proc.terminate()
        raise RuntimeError(f"Browser daemon không start được sau 60 giây!")

    # Đọc lock (subprocess đã ghi)
    time.sleep(0.5)
    lock = _read_lock(name)
    if not lock:
        # Ghi manually nếu subprocess chưa kịp
        lock = {
            "name": name,
            "pid": proc.pid,
            "cdp_url": f"http://localhost:{cdp_port}",
            "started_at": time.time(),
        }
        with open(_lock_path(name), "w") as f:
            json.dump(lock, f, indent=2)

    print(f"✅ [{name}] Browser daemon đang chạy! CDP: {lock['cdp_url']}")
    return lock


def stop_browser_daemon(name: str):
    """Dừng browser daemon của profile."""
    lock = _read_lock(name)
    if not lock:
        print(f"⚫ [{name}] Không đang chạy")
        return
    try:
        os.kill(lock["pid"], signal.SIGTERM)
        time.sleep(1)
        if _is_pid_alive(lock["pid"]):
            os.kill(lock["pid"], signal.SIGKILL)
    except Exception:
        pass
    _lock_path(name).unlink(missing_ok=True)
    print(f"🔴 [{name}] Đã dừng")


# ============================================================
# CLIENT — dùng từ script khác để kết nối vào browser đang chạy
# ============================================================

class BrowserClient:
    """
    Kết nối vào browser đang chạy nền.

    Usage:
        with BrowserClient("ACC001") as (context, page):
            page.goto("https://soundon.global/library/publish/single")
            # Làm việc...
            # Khi thoát: browser vẫn sống!

        # Lần sau chạy lại:
        with BrowserClient("ACC001") as (context, page):
            print(page.url)  # Vẫn còn ở trang cũ!
    """

    def __init__(self, name: str, auto_start: bool = True, headless: bool = True):
        self.name = name
        self.auto_start = auto_start
        self.headless = headless
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None

    def __enter__(self):
        from playwright.sync_api import sync_playwright

        # Kiểm tra daemon đang chạy chưa
        lock = _read_lock(self.name)
        if not lock:
            if self.auto_start:
                lock = start_browser_daemon(self.name, self.headless)
            else:
                raise RuntimeError(f"Profile '{self.name}' chưa chạy. Dùng start_browser_daemon() trước.")

        cdp_url = lock["cdp_url"]
        print(f"🔌 [{self.name}] Kết nối vào {cdp_url}...")

        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.connect_over_cdp(cdp_url)
        
        # Lấy context và page hiện tại
        contexts = self._browser.contexts
        if contexts:
            self._context = contexts[0]
            pages = self._context.pages
            self._page = pages[0] if pages else self._context.new_page()
        else:
            self._context = self._browser.new_context()
            self._page = self._context.new_page()

        print(f"✅ [{self.name}] Đang ở: {self._page.url}")
        return self._context, self._page

    def __exit__(self, *args):
        # Chụp ảnh trước khi thoát
        if self._page:
            try:
                ss_dir = PROFILES_DIR / self.name / "screenshots"
                ss_dir.mkdir(exist_ok=True)
                ts = time.strftime("%Y%m%d_%H%M%S")
                ss_path = ss_dir / f"{ts}.png"
                self._page.screenshot(path=str(ss_path))
                print(f"📸 Screenshot: {ss_path}")
            except Exception as e:
                print(f"Screenshot lỗi: {e}")

        # Disconnect nhưng KHÔNG đóng browser
        if self._browser:
            try:
                self._browser.close()  # Chỉ đóng connection, không kill process
            except Exception:
                pass
        if self._playwright:
            try:
                self._playwright.stop()
            except Exception:
                pass
        print(f"💤 [{self.name}] Disconnected (browser vẫn chạy nền)")


# ============================================================
# CLI
# ============================================================

if __name__ == "__main__":
    args = sys.argv[1:]
    
    if not args:
        print(__doc__)
        sys.exit(0)

    cmd = args[0]

    if cmd == "start":
        name = args[1] if len(args) > 1 else "ACC001"
        start_browser_daemon(name)

    elif cmd == "stop":
        name = args[1] if len(args) > 1 else "ACC001"
        stop_browser_daemon(name)

    elif cmd == "status":
        for s in status_all():
            print(s)

    elif cmd == "restart":
        name = args[1] if len(args) > 1 else "ACC001"
        stop_browser_daemon(name)
        time.sleep(2)
        start_browser_daemon(name)

    else:
        print(f"Unknown command: {cmd}")
        print("Commands: start <profile> | stop <profile> | status | restart <profile>")
