"""
Browser Manager v2 - Quản lý browser như GoLogin
- Mỗi profile chạy 1 worker process riêng
- Worker giữ browser sống nền
- Script gửi lệnh qua stdin pipe → worker thực thi → trả JSON
- Nhiều script có thể điều khiển cùng 1 browser instance

Usage:
    manager = BrowserManager()
    
    # Mở ACC001 (nếu chưa mở) hoặc dùng lại (nếu đang chạy)
    manager.open("ACC001")
    
    # Làm việc
    manager.goto("ACC001", "https://soundon.global/library")
    manager.screenshot("ACC001", "test.png")
    manager.click("ACC001", "button:has-text('Upload')")
    
    # Đại Ca đi ra ngoài... 
    # Script kết thúc nhưng browser vẫn chạy!
    
    # Lần sau vào lại:
    manager.open("ACC001")  # Attach vào browser cũ, không mở mới
    print(manager.get_url("ACC001"))  # Vẫn ở trang cũ!
    
    # Đóng hẳn
    manager.close("ACC001")
    manager.close_all()
"""

import json
import os
import signal
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


def _lock_path(name: str) -> Path:
    return LOCKS_DIR / f"{name}.json"


def _is_pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


class BrowserManager:
    """
    Quản lý nhiều browser profiles cùng lúc.
    Mỗi profile = 1 worker process với browser riêng.
    Workers giữ browser sống giữa các lần kết nối.
    """

    def __init__(self):
        self._workers: dict[str, subprocess.Popen] = {}  # name -> Popen
        self._cmd_counter = 0

    def _next_id(self) -> int:
        self._cmd_counter += 1
        return self._cmd_counter

    def _send_cmd(self, name: str, action: str, **kwargs) -> dict:
        """Gửi lệnh tới worker và chờ response."""
        proc = self._workers.get(name)
        if not proc or proc.poll() is not None:
            raise RuntimeError(f"Worker '{name}' không chạy. Gọi open('{name}') trước.")

        cmd_id = self._next_id()
        cmd = {"id": cmd_id, "action": action, **kwargs}
        
        try:
            proc.stdin.write(json.dumps(cmd, ensure_ascii=False) + "\n")
            proc.stdin.flush()

            # Chờ response
            while True:
                line = proc.stdout.readline()
                if not line:
                    raise RuntimeError(f"Worker '{name}' đã chết!")
                line = line.decode().strip()
                if not line:
                    continue
                resp = json.loads(line)
                if resp.get("id") == cmd_id:
                    return resp
                # Response khác (log) → bỏ qua

        except Exception as e:
            raise RuntimeError(f"Lỗi gửi lệnh tới '{name}': {e}")

    def is_open(self, name: str) -> bool:
        """Kiểm tra profile có đang mở không."""
        # Kiểm tra lock file (worker process)
        lock = self._load_lock(name)
        if lock and _is_pid_alive(lock["pid"]):
            return True
        # Kiểm tra trong memory
        proc = self._workers.get(name)
        return proc is not None and proc.poll() is None

    def _load_lock(self, name: str) -> Optional[dict]:
        p = _lock_path(name)
        if not p.exists():
            return None
        try:
            with open(p) as f:
                return json.load(f)
        except Exception:
            return None

    def _save_lock(self, name: str, pid: int):
        with open(_lock_path(name), "w") as f:
            json.dump({"name": name, "pid": pid, "started_at": time.time()}, f)

    def open(self, name: str, headless: bool = True) -> bool:
        """
        Mở profile. 
        - Nếu đang chạy: tự động attach (không làm gì thêm)
        - Nếu chưa chạy: start worker mới
        Trả về True nếu đã mở sẵn, False nếu vừa start mới.
        """
        # Kiểm tra worker trong memory hiện tại
        proc = self._workers.get(name)
        if proc and proc.poll() is None:
            print(f"✅ [{name}] Đã đang mở (PID {proc.pid})")
            return True

        # Kiểm tra lock file — có thể worker chạy từ process khác
        # (Lần này chưa support cross-process, sẽ start mới)
        lock = self._load_lock(name)
        if lock and _is_pid_alive(lock["pid"]):
            # Worker từ process khác — không thể attach pipe
            # TODO: implement cross-process IPC
            print(f"⚠️  [{name}] Đang chạy từ process khác (PID {lock['pid']}), sẽ start lại trong process này...")

        print(f"🚀 [{name}] Khởi động browser worker...")
        worker_script = BASE_DIR / "browser_worker.py"

        proc = subprocess.Popen(
            [str(VENV_PYTHON), str(worker_script), name],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=1,
        )

        # Chờ "ready" response (id=0)
        deadline = time.time() + 120
        while time.time() < deadline:
            line = proc.stdout.readline()
            if not line:
                if proc.poll() is not None:
                    err = proc.stderr.read().decode()
                    raise RuntimeError(f"Worker '{name}' crash khi start:\n{err}")
                time.sleep(0.5)
                continue
            line = line.decode().strip()
            if not line:
                continue
            try:
                resp = json.loads(line)
                if resp.get("id") == 0:
                    if resp["success"]:
                        self._workers[name] = proc
                        self._save_lock(name, proc.pid)
                        url = resp.get("data", {}).get("url", "")
                        print(f"✅ [{name}] Browser ready! URL: {url}")
                        return False
                    else:
                        proc.terminate()
                        raise RuntimeError(f"Worker '{name}' lỗi: {resp.get('error')}")
            except json.JSONDecodeError:
                continue  # log line, bỏ qua

        proc.terminate()
        raise RuntimeError(f"Worker '{name}' không ready sau 120s!")

    def close(self, name: str):
        """Đóng browser của profile."""
        if name in self._workers:
            try:
                self._send_cmd(name, "quit")
            except Exception:
                pass
            proc = self._workers[name]
            proc.terminate()
            proc.wait(timeout=5)
            del self._workers[name]
        _lock_path(name).unlink(missing_ok=True)
        print(f"🔴 [{name}] Đã đóng")

    def close_all(self):
        for name in list(self._workers.keys()):
            self.close(name)

    # ============================================================
    # Playwright actions
    # ============================================================

    def goto(self, name: str, url: str, wait_until: str = "networkidle", timeout: int = 60000) -> str:
        resp = self._send_cmd(name, "goto", url=url, wait_until=wait_until, timeout=timeout)
        if not resp["success"]:
            raise RuntimeError(resp.get("error"))
        return resp["data"]["url"]

    def screenshot(self, name: str, path: str, full_page: bool = True) -> str:
        resp = self._send_cmd(name, "screenshot", path=path, full_page=full_page)
        if not resp["success"]:
            raise RuntimeError(resp.get("error"))
        return resp["data"]["path"]

    def click(self, name: str, selector: str, timeout: int = 10000):
        resp = self._send_cmd(name, "click", selector=selector, timeout=timeout)
        if not resp["success"]:
            raise RuntimeError(resp.get("error"))

    def fill(self, name: str, selector: str, value: str):
        resp = self._send_cmd(name, "fill", selector=selector, value=value)
        if not resp["success"]:
            raise RuntimeError(resp.get("error"))

    def wait_for(self, name: str, selector: str, timeout: int = 30000):
        resp = self._send_cmd(name, "wait_for", selector=selector, timeout=timeout)
        if not resp["success"]:
            raise RuntimeError(resp.get("error"))

    def upload_file(self, name: str, selector: str, file_path: str):
        resp = self._send_cmd(name, "upload_file", selector=selector, file_path=file_path)
        if not resp["success"]:
            raise RuntimeError(resp.get("error"))

    def get_url(self, name: str) -> str:
        resp = self._send_cmd(name, "get_url")
        if not resp["success"]:
            raise RuntimeError(resp.get("error"))
        return resp["data"]["url"]

    def get_text(self, name: str) -> str:
        resp = self._send_cmd(name, "get_text")
        if not resp["success"]:
            raise RuntimeError(resp.get("error"))
        return resp["data"]["text"]

    def eval(self, name: str, expr: str) -> str:
        resp = self._send_cmd(name, "eval", expr=expr)
        if not resp["success"]:
            raise RuntimeError(resp.get("error"))
        return resp["data"]["result"]

    def dismiss_popup(self, name: str) -> bool:
        resp = self._send_cmd(name, "dismiss_popup")
        if not resp["success"]:
            raise RuntimeError(resp.get("error"))
        return resp["data"]["dismissed"]

    def sleep(self, name: str, seconds: float = 1):
        resp = self._send_cmd(name, "sleep", seconds=seconds)

    def status(self) -> list:
        results = []
        for name, proc in self._workers.items():
            if proc.poll() is None:
                try:
                    url = self.get_url(name)
                    results.append(f"🟢 {name} | PID {proc.pid} | {url}")
                except Exception:
                    results.append(f"🟡 {name} | PID {proc.pid} | (không lấy được URL)")
            else:
                results.append(f"🔴 {name} | Đã chết")
        return results or ["(không có browser nào)"]


# ============================================================
# Singleton global instance — dùng khi import từ script khác
# ============================================================
_global_manager: Optional[BrowserManager] = None


def get_manager() -> BrowserManager:
    global _global_manager
    if _global_manager is None:
        _global_manager = BrowserManager()
    return _global_manager


def open_browser(name: str, headless: bool = True) -> BrowserManager:
    """
    Tương thích ngược với manager.py cũ.
    Mở profile và trả về manager instance để dùng tiếp.
    
    Usage (new style):
        mgr = open_browser("ACC001")
        mgr.goto("ACC001", "https://soundon.global")
        mgr.screenshot("ACC001", "test.png")
        mgr.close("ACC001")
    """
    mgr = get_manager()
    mgr.open(name, headless=headless)
    return mgr


if __name__ == "__main__":
    # Test nhanh
    mgr = BrowserManager()
    
    print("=== Test 1: Mở ACC001 ===")
    mgr.open("ACC001")
    
    print("\n=== Test 2: Navigate ===")
    url = mgr.goto("ACC001", "https://www.soundon.global/library?lang=en")
    print(f"URL: {url}")
    
    print("\n=== Test 3: Screenshot ===")
    path = mgr.screenshot("ACC001", "/home/phuongcan/.openclaw/workspace/test_daemon_1.png")
    print(f"Screenshot: {path}")
    
    print("\n=== Test 4: Giả vờ script kết thúc ===")
    print("(browser vẫn chạy vì mgr còn tồn tại)")
    
    print("\n=== Test 5: Kết nối lại ===")
    already_open = mgr.open("ACC001")  # Phải nói "đã đang mở"
    url2 = mgr.get_url("ACC001")
    print(f"URL sau khi 'reconnect': {url2}")
    
    print("\n=== Status ===")
    for s in mgr.status():
        print(s)
    
    print("\n=== Đóng ===")
    mgr.close_all()
