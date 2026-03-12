"""
Browser Daemon - Giữ browser chạy nền theo profile
Đại Ca mở ACC001 một lần, làm dở thì ra, vào lại vẫn còn nguyên 🦊

Usage:
    # Lần đầu (hoặc nếu chưa chạy): tự khởi động
    # Lần sau: tự attach vào browser đang chạy

    from browser_daemon import get_or_launch

    with get_or_launch("ACC001") as (browser, page):
        page.goto("https://example.com")
        # browser vẫn sống sau khi with block thoát!
"""

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional, Tuple

BASE_DIR = Path(__file__).parent
PROFILES_DIR = BASE_DIR / "profiles"
LOCKS_DIR = BASE_DIR / "locks"
LOCKS_DIR.mkdir(exist_ok=True)


def _lock_path(name: str) -> Path:
    return LOCKS_DIR / f"{name}.json"


def _is_process_alive(pid: int) -> bool:
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
        # Kiểm tra process còn sống không
        if not _is_process_alive(lock.get("pid", 0)):
            p.unlink()
            return None
        return lock
    except Exception:
        return None


def _write_lock(name: str, pid: int, ws_url: str, cdp_url: str):
    with open(_lock_path(name), "w") as f:
        json.dump({
            "name": name,
            "pid": pid,
            "ws_url": ws_url,
            "cdp_url": cdp_url,
            "started_at": time.time(),
        }, f, indent=2)


def _remove_lock(name: str):
    p = _lock_path(name)
    if p.exists():
        p.unlink()


def is_running(name: str) -> bool:
    """Kiểm tra profile có đang chạy không."""
    return _read_lock(name) is not None


def status(name: str) -> str:
    lock = _read_lock(name)
    if lock:
        uptime = int(time.time() - lock["started_at"])
        m, s = divmod(uptime, 60)
        h, m = divmod(m, 60)
        return f"🟢 {name} đang chạy (PID {lock['pid']}, uptime {h:02d}:{m:02d}:{s:02d})"
    return f"⚫ {name} chưa chạy"


def launch_background(name: str) -> dict:
    """
    Khởi động browser cho profile trong background.
    Trả về lock info với cdp_url để attach sau.
    """
    from camoufox import Camoufox
    from browserforge.fingerprints.generator import Screen as BFScreen

    config_path = PROFILES_DIR / name / "config.json"
    if not config_path.exists():
        raise ValueError(f"Profile '{name}' không tồn tại!")

    with open(config_path) as f:
        config = json.load(f)

    browser_data_dir = str(PROFILES_DIR / name / "browser_data")

    kwargs = {
        "headless": True,
        "persistent_context": True,
        "user_data_dir": browser_data_dir,
        "geoip": True,
        "screen": BFScreen(min_width=1920, max_width=1920, min_height=1080, max_height=1080),
        "viewport": {"width": 1920, "height": 1080},
        "args": ["--remote-debugging-port=0"],  # CDP port tự động
    }

    # Proxy
    if config.get("proxy"):
        proxy_str = config["proxy"]
        proxy_type = config.get("proxy_type", "http")
        auth = None
        host_port = proxy_str
        if "@" in proxy_str:
            auth, host_port = proxy_str.rsplit("@", 1)
        parts = host_port.split(":")
        host = parts[0]
        port = int(parts[1]) if len(parts) > 1 else 1080
        proxy_dict = {"server": f"{host}:{port}"}
        if auth:
            up = auth.split(":", 1)
            proxy_dict["username"] = up[0]
            if len(up) > 1:
                proxy_dict["password"] = up[1]
        kwargs["proxy"] = proxy_dict

    # Launch browser — context manager nhưng KHÔNG exit
    camo = Camoufox(**kwargs)
    context = camo.__enter__()

    pages = context.pages
    page = pages[0] if pages else context.new_page()

    # Lấy CDP URL từ browser
    browser = context.browser
    cdp_url = ""
    ws_url = ""
    try:
        cdp_url = browser.contexts[0].pages[0].evaluate("() => 'http://localhost:' + window.location.port")
    except Exception:
        pass

    # Lưu lock — dùng PID của process hiện tại + lưu context để dùng lại
    pid = os.getpid()

    # Lưu context vào file để script khác có thể tìm thấy
    # Dùng approach khác: subprocess với script riêng chạy background
    return camo, context, page


class BrowserPool:
    """
    Pool quản lý browser instances theo tên profile.
    Singleton per process — giữ browser sống suốt vòng đời process.
    """
    _instances: dict = {}  # name -> (camo, context, page)

    @classmethod
    def get(cls, name: str) -> Optional[Tuple]:
        return cls._instances.get(name)

    @classmethod  
    def put(cls, name: str, camo, context, page):
        cls._instances[name] = (camo, context, page)

    @classmethod
    def remove(cls, name: str):
        if name in cls._instances:
            try:
                camo, context, page = cls._instances[name]
                camo.__exit__(None, None, None)
            except Exception:
                pass
            del cls._instances[name]
            _remove_lock(name)

    @classmethod
    def close_all(cls):
        for name in list(cls._instances.keys()):
            cls.remove(name)


def get_or_launch(name: str, url: Optional[str] = None, headless: bool = True):
    """
    Context manager thông minh:
    - Nếu ACC001 đang mở (trong process này): dùng lại page đó
    - Nếu chưa mở: mở mới, lưu vào pool
    - Khi 'with' block thoát: KHÔNG đóng browser — để dùng lại lần sau

    Usage:
        with get_or_launch("ACC001") as (context, page):
            page.goto("https://soundon.global")
            # Xong rồi ra ngoài — browser vẫn còn!

        # Lần sau:
        with get_or_launch("ACC001") as (context, page):
            # Vẫn ở trang cũ, cookies còn nguyên!
    """
    return _PoolSession(name, url, headless)


class _PoolSession:
    def __init__(self, name: str, url: Optional[str], headless: bool):
        self.name = name
        self.url = url
        self.headless = headless
        self._context = None
        self._page = None
        self._is_new = False

    def __enter__(self):
        existing = BrowserPool.get(self.name)
        
        if existing:
            camo, context, page = existing
            # Kiểm tra page còn sống không
            try:
                _ = page.url  # Sẽ raise nếu browser đã chết
                self._context = context
                self._page = page
                print(f"✅ [{self.name}] Kết nối lại browser đang chạy — đang ở: {page.url}")
            except Exception:
                # Browser chết rồi, xóa và mở mới
                BrowserPool.remove(self.name)
                existing = None

        if not existing:
            self._is_new = True
            print(f"🚀 [{self.name}] Khởi động browser mới...")
            camo, context, page = launch_background(self.name)
            BrowserPool.put(self.name, camo, context, page)
            self._context = context
            self._page = page
            print(f"✅ [{self.name}] Browser started!")

        if self.url:
            print(f"🌐 [{self.name}] Navigate to: {self.url}")
            self._page.goto(self.url, wait_until="networkidle", timeout=60000)

        return self._context, self._page

    def __exit__(self, *args):
        # KHÔNG đóng browser — giữ sống để dùng lại
        if self._page:
            try:
                ss_dir = PROFILES_DIR / self.name / "screenshots"
                ss_dir.mkdir(exist_ok=True)
                ts = time.strftime("%Y%m%d_%H%M%S")
                ss_path = ss_dir / f"{ts}.png"
                self._page.screenshot(path=str(ss_path))
            except Exception:
                pass
        print(f"💤 [{self.name}] Browser vẫn đang chạy nền (không đóng)")


def kill(name: str):
    """Đóng hẳn browser của profile."""
    BrowserPool.remove(name)
    print(f"🔴 [{name}] Đã đóng browser")


if __name__ == "__main__":
    # CLI nhanh
    if len(sys.argv) < 2:
        print("Usage: python browser_daemon.py [status|kill] <profile>")
        sys.exit(0)
    
    cmd = sys.argv[1]
    name = sys.argv[2] if len(sys.argv) > 2 else "ACC001"
    
    if cmd == "status":
        print(status(name))
    elif cmd == "kill":
        kill(name)
