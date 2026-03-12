"""
Browser Client v2 - Kết nối tới browser worker qua Unix socket
Nhiều script, nhiều process đều có thể kết nối vào cùng 1 browser!

Usage:
    from browser_client import BrowserClient, start_profile, stop_profile, status

    # Mở profile (nếu chưa chạy thì tự start)
    start_profile("ACC001")
    
    # Kết nối và làm việc
    with BrowserClient("ACC001") as bc:
        bc.goto("https://soundon.global/library")
        bc.screenshot("/path/to/shot.png")
        print(bc.get_url())
    # browser vẫn sống!
    
    # Script khác, process khác:
    with BrowserClient("ACC001") as bc:
        print(bc.get_url())  # vẫn ở trang cũ!
    
    # Đóng hẳn:
    stop_profile("ACC001")
"""

import json
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

BASE_DIR = Path(__file__).parent
PROFILES_DIR = BASE_DIR / "profiles"
LOCKS_DIR = BASE_DIR / "locks"
LOCKS_DIR.mkdir(exist_ok=True)

VENV_PYTHON = BASE_DIR.parent / "camoufox-env" / "bin" / "python3"
if not VENV_PYTHON.exists():
    VENV_PYTHON = Path(sys.executable)


def get_lock_path(name: str) -> Path:
    return LOCKS_DIR / f"{name}.json"


def get_socket_path(name: str) -> str:
    return str(LOCKS_DIR / f"{name}.sock")


def _is_pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def _read_lock(name: str) -> Optional[dict]:
    p = get_lock_path(name)
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


def status_all() -> list[str]:
    results = []
    for f in LOCKS_DIR.glob("*.json"):
        try:
            with open(f) as fh:
                lock = json.load(fh)
            name = lock["name"]
            if _is_pid_alive(lock["pid"]):
                uptime = int(time.time() - lock["started_at"])
                m, s = divmod(uptime, 60)
                h, m = divmod(m, 60)
                results.append(f"🟢 {name} | PID {lock['pid']} | uptime {h:02d}:{m:02d}:{s:02d}")
            else:
                f.unlink(missing_ok=True)
        except Exception:
            pass
    return results or ["(không có browser nào đang chạy)"]


def start_profile(name: str, headless: bool = True) -> dict:
    """
    Start browser daemon cho profile.
    Nếu đã chạy rồi thì không làm gì.
    """
    existing = _read_lock(name)
    if existing:
        print(f"✅ [{name}] Đã đang chạy (PID {existing['pid']})")
        return existing

    config_path = PROFILES_DIR / name / "config.json"
    if not config_path.exists():
        raise ValueError(f"Profile '{name}' không tồn tại!")

    print(f"🚀 [{name}] Khởi động browser daemon...")
    worker_script = BASE_DIR / "browser_worker_v2.py"

    proc = subprocess.Popen(
        [str(VENV_PYTHON), str(worker_script), name],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,  # Detach — sống sau khi parent thoát!
    )

    # Chờ READY
    deadline = time.time() + 120
    while time.time() < deadline:
        line = proc.stdout.readline()
        if not line:
            if proc.poll() is not None:
                err = proc.stderr.read().decode()
                raise RuntimeError(f"Browser daemon crash:\n{err}")
            time.sleep(0.5)
            continue
        line = line.decode().strip()
        if not line:
            continue
        try:
            resp = json.loads(line)
            if resp.get("id") == 0:
                if resp["success"]:
                    lock = resp["data"]
                    print(f"✅ [{name}] Daemon ready! Socket: {lock['socket']}")
                    return lock
                else:
                    proc.terminate()
                    raise RuntimeError(f"Daemon lỗi: {resp.get('error')}")
        except json.JSONDecodeError:
            continue

    proc.terminate()
    raise RuntimeError(f"Daemon không ready sau 120s!")


def stop_profile(name: str):
    """Dừng browser daemon."""
    lock = _read_lock(name)
    if not lock:
        print(f"⚫ [{name}] Không đang chạy")
        return
    try:
        os.kill(lock["pid"], signal.SIGTERM)
        for _ in range(10):
            if not _is_pid_alive(lock["pid"]):
                break
            time.sleep(0.5)
        if _is_pid_alive(lock["pid"]):
            os.kill(lock["pid"], signal.SIGKILL)
    except Exception:
        pass
    get_lock_path(name).unlink(missing_ok=True)
    sock = get_socket_path(name)
    if os.path.exists(sock):
        os.unlink(sock)
    print(f"🔴 [{name}] Đã dừng")


class BrowserClient:
    """
    Client kết nối vào browser worker qua socket.
    
    - Tự động start worker nếu chưa chạy (auto_start=True)
    - Khi thoát khỏi 'with': browser KHÔNG đóng
    - Lần sau vào lại: vẫn ở trang cũ
    """

    def __init__(self, name: str, auto_start: bool = True, headless: bool = True, timeout: int = 300):
        self.name = name
        self.auto_start = auto_start
        self.headless = headless
        self.timeout = timeout
        self._sock: Optional[socket.socket] = None
        self._cmd_id = 0
        self._buf = ""

    def _connect(self):
        sock_path = get_socket_path(self.name)
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(self.timeout)
        s.connect(sock_path)
        self._sock = s
        self._buf = ""

    def _send(self, action: str, **kwargs) -> dict:
        if not self._sock:
            raise RuntimeError("Not connected")
        self._cmd_id += 1
        cmd = {"id": self._cmd_id, "action": action, **kwargs}
        self._sock.send((json.dumps(cmd, ensure_ascii=False) + "\n").encode())
        # Read response
        while True:
            data = self._sock.recv(65536)
            if not data:
                raise RuntimeError("Connection closed by worker")
            self._buf += data.decode()
            while "\n" in self._buf:
                line, self._buf = self._buf.split("\n", 1)
                line = line.strip()
                if not line:
                    continue
                resp = json.loads(line)
                if resp.get("id") == self._cmd_id:
                    return resp

    def __enter__(self):
        # Kiểm tra / start daemon
        if not is_running(self.name):
            if self.auto_start:
                start_profile(self.name, self.headless)
                time.sleep(1)  # Chờ socket sẵn sàng
            else:
                raise RuntimeError(f"Profile '{self.name}' chưa chạy. Gọi start_profile() trước.")

        self._connect()
        resp = self._send("ping")
        if resp["success"]:
            print(f"🔌 [{self.name}] Connected! Đang ở: {resp['data']['url']}")
        return self

    def __exit__(self, *args):
        # Chụp screenshot tự động
        try:
            ss_dir = PROFILES_DIR / self.name / "screenshots"
            ss_dir.mkdir(exist_ok=True)
            ts = time.strftime("%Y%m%d_%H%M%S")
            ss_path = str(ss_dir / f"{ts}.png")
            self._send("screenshot", path=ss_path)
        except Exception:
            pass

        if self._sock:
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None
        print(f"💤 [{self.name}] Disconnected (browser vẫn chạy nền!)")

    # ============================================================
    # Actions
    # ============================================================

    def goto(self, url: str, wait_until: str = "networkidle", timeout: int = 60000) -> str:
        resp = self._send("goto", url=url, wait_until=wait_until, timeout=timeout)
        if not resp["success"]:
            raise RuntimeError(resp.get("error"))
        return resp["data"]["url"]

    def screenshot(self, path: str, full_page: bool = True) -> str:
        resp = self._send("screenshot", path=path, full_page=full_page)
        if not resp["success"]:
            raise RuntimeError(resp.get("error"))
        return resp["data"]["path"]

    def click(self, selector: str, timeout: int = 10000):
        resp = self._send("click", selector=selector, timeout=timeout)
        if not resp["success"]:
            raise RuntimeError(resp.get("error"))

    def fill(self, selector: str, value: str):
        resp = self._send("fill", selector=selector, value=value)
        if not resp["success"]:
            raise RuntimeError(resp.get("error"))

    def wait_for(self, selector: str, timeout: int = 30000):
        resp = self._send("wait_for", selector=selector, timeout=timeout)
        if not resp["success"]:
            raise RuntimeError(resp.get("error"))

    def upload_file(self, selector: str, file_path: str):
        resp = self._send("upload_file", selector=selector, file_path=file_path)
        if not resp["success"]:
            raise RuntimeError(resp.get("error"))

    def get_url(self) -> str:
        resp = self._send("get_url")
        if not resp["success"]:
            raise RuntimeError(resp.get("error"))
        return resp["data"]["url"]

    def get_text(self) -> str:
        resp = self._send("get_text")
        if not resp["success"]:
            raise RuntimeError(resp.get("error"))
        return resp["data"]["text"]

    def eval(self, expr: str) -> str:
        resp = self._send("eval", expr=expr)
        if not resp["success"]:
            raise RuntimeError(resp.get("error"))
        return resp["data"]["result"]

    def dismiss_popup(self) -> bool:
        resp = self._send("dismiss_popup")
        if not resp["success"]:
            raise RuntimeError(resp.get("error"))
        return resp["data"]["dismissed"]

    def sleep(self, seconds: float = 1):
        self._send("sleep", seconds=seconds)

    def reload(self, timeout: int = 30000) -> str:
        resp = self._send("reload", timeout=timeout)
        if not resp["success"]:
            raise RuntimeError(resp.get("error"))
        return resp["data"]["url"]


# CLI
if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        print("Commands: start <profile> | stop <profile> | status | test <profile>")
        sys.exit(0)

    cmd = args[0]
    name = args[1] if len(args) > 1 else "ACC001"

    if cmd == "start":
        start_profile(name)
    elif cmd == "stop":
        stop_profile(name)
    elif cmd == "status":
        for s in status_all():
            print(s)
    elif cmd == "test":
        with BrowserClient(name) as bc:
            print("URL:", bc.get_url())
            text = bc.get_text()
            print("Page text (200 chars):", text[:200])
    else:
        print(f"Unknown: {cmd}")
