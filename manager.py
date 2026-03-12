"""
CamoManager - Hệ thống quản lý multi-profile cho Camoufox
Phục vụ Đại Ca Phương 🦊
"""

import json
import os
import shutil
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

# Timezone Việt Nam
VN_TZ = timezone(timedelta(hours=7))

BASE_DIR = Path(__file__).parent
PROFILES_DIR = BASE_DIR / "profiles"
PROFILES_DIR.mkdir(exist_ok=True)


def _now_vn():
    return datetime.now(VN_TZ)


def _load_json(path: Path) -> dict:
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def _save_json(path: Path, data: dict):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False, default=str)


# ============================================================
# PROFILE CRUD
# ============================================================

def create_profile(
    name: str,
    proxy: Optional[str] = None,
    proxy_type: str = "http",
    note: str = "",
    tags: Optional[list] = None,
) -> dict:
    """
    Tạo profile mới.
    
    Args:
        name: Tên profile (VD: "soundon-artist1")
        proxy: Proxy string (VD: "user:pass@host:port" hoặc "host:port")
        proxy_type: "http" hoặc "socks5"
        note: Ghi chú tùy ý
        tags: Tags phân loại (VD: ["soundon", "us"])
    """
    profile_dir = PROFILES_DIR / name
    if profile_dir.exists():
        raise ValueError(f"Profile '{name}' đã tồn tại!")
    
    profile_dir.mkdir(parents=True)
    (profile_dir / "browser_data").mkdir()
    
    config = {
        "name": name,
        "proxy": proxy,
        "proxy_type": proxy_type,
        "note": note,
        "tags": tags or [],
        "created_at": _now_vn().isoformat(),
        "last_used": None,
        "use_count": 0,
    }
    _save_json(profile_dir / "config.json", config)
    _save_json(profile_dir / "history.json", {"sessions": []})
    
    return config


def list_profiles(tag: Optional[str] = None) -> list:
    """Liệt kê tất cả profiles. Lọc theo tag nếu có."""
    profiles = []
    for p in sorted(PROFILES_DIR.iterdir()):
        config_path = p / "config.json"
        if config_path.exists():
            config = _load_json(config_path)
            if tag and tag not in config.get("tags", []):
                continue
            profiles.append(config)
    return profiles


def get_profile(name: str) -> dict:
    """Lấy thông tin profile."""
    config_path = PROFILES_DIR / name / "config.json"
    if not config_path.exists():
        raise ValueError(f"Profile '{name}' không tồn tại!")
    return _load_json(config_path)


def update_profile(name: str, **kwargs) -> dict:
    """Cập nhật profile (proxy, note, tags, ...)."""
    profile_dir = PROFILES_DIR / name
    config_path = profile_dir / "config.json"
    if not config_path.exists():
        raise ValueError(f"Profile '{name}' không tồn tại!")
    
    # Allowed keys that can be added (not just updated)
    ALLOWED_NEW_KEYS = {'viewport', 'screen', 'headless', 'geoip'}

    config = _load_json(config_path)
    for key, value in kwargs.items():
        if key in config or key in ALLOWED_NEW_KEYS:
            config[key] = value
    _save_json(config_path, config)
    return config


def delete_profile(name: str) -> bool:
    """Xóa profile (chuyển vào trash)."""
    profile_dir = PROFILES_DIR / name
    if not profile_dir.exists():
        raise ValueError(f"Profile '{name}' không tồn tại!")
    
    trash_dir = BASE_DIR / ".trash"
    trash_dir.mkdir(exist_ok=True)
    dest = trash_dir / f"{name}_{int(time.time())}"
    shutil.move(str(profile_dir), str(dest))
    return True


# ============================================================
# BROWSER SESSION
# ============================================================

def _parse_proxy(proxy_str: str, proxy_type: str) -> dict:
    """Parse proxy string thành dict cho Camoufox."""
    if not proxy_str:
        return {}
    
    auth = None
    host_port = proxy_str
    
    if "@" in proxy_str:
        auth, host_port = proxy_str.rsplit("@", 1)
    
    parts = host_port.split(":")
    host = parts[0]
    port = int(parts[1]) if len(parts) > 1 else (1080 if proxy_type == "socks5" else 8080)
    
    proxy = {
        "server": f"{host}:{port}",
    }
    
    if auth:
        user_pass = auth.split(":", 1)
        proxy["username"] = user_pass[0]
        if len(user_pass) > 1:
            proxy["password"] = user_pass[1]
    
    return proxy


def open_browser(name: str, headless: bool = True, url: Optional[str] = None):
    """
    Mở browser với profile đã lưu.
    
    Returns: Camoufox context manager (chưa enter).
    Dùng với `with`:
        with open_browser(name, url=url) as (context, page):
            ...
    """
    from camoufox import Camoufox
    
    profile_dir = PROFILES_DIR / name
    config_path = profile_dir / "config.json"
    if not config_path.exists():
        raise ValueError(f"Profile '{name}' không tồn tại!")
    
    config = _load_json(config_path)
    browser_data_dir = str(profile_dir / "browser_data")
    
    from browserforge.fingerprints.generator import Screen as BFScreen
    # Build camoufox kwargs
    kwargs = {
        "headless": headless,
        "persistent_context": True,
        "user_data_dir": browser_data_dir,
        "geoip": True,
        "screen": BFScreen(min_width=1920, max_width=1920, min_height=1080, max_height=1080),
        "viewport": {"width": 1920, "height": 1080},
    }
    
    # Proxy
    if config.get("proxy"):
        proxy = _parse_proxy(config["proxy"], config.get("proxy_type", "http"))
        kwargs["proxy"] = proxy
    
    # Log & update config
    _log_session(name, "opened", url=url)
    config["last_used"] = _now_vn().isoformat()
    config["use_count"] = config.get("use_count", 0) + 1
    _save_json(config_path, config)
    
    return _BrowserSession(name, url, **kwargs)


class _BrowserSession:
    """Context manager wrapper cho Camoufox browser session."""
    
    def __init__(self, profile_name: str, url: Optional[str] = None, **kwargs):
        from camoufox import Camoufox
        self._profile_name = profile_name
        self._url = url
        self._camo = Camoufox(**kwargs)
        self._context = None
        self._page = None
    
    def __enter__(self):
        self._context = self._camo.__enter__()
        pages = self._context.pages
        self._page = pages[0] if pages else self._context.new_page()
        
        if self._url:
            self._page.goto(self._url, timeout=60000)
        
        return self._context, self._page
    
    def __exit__(self, *args):
        # Auto screenshot trước khi đóng
        if self._page:
            try:
                ss_dir = PROFILES_DIR / self._profile_name / "screenshots"
                ss_dir.mkdir(exist_ok=True)
                ts = _now_vn().strftime("%Y%m%d_%H%M%S")
                ss_path = ss_dir / f"{ts}.png"
                self._page.screenshot(path=str(ss_path))
            except Exception:
                pass
        
        self._camo.__exit__(*args)
        _log_session(self._profile_name, "closed")


def _log_session(name: str, action: str, url: Optional[str] = None):
    """Ghi log lịch sử session."""
    history_path = PROFILES_DIR / name / "history.json"
    history = _load_json(history_path)
    
    if "sessions" not in history:
        history["sessions"] = []
    
    entry = {
        "action": action,
        "timestamp": _now_vn().isoformat(),
    }
    if url:
        entry["url"] = url
    
    history["sessions"].append(entry)
    
    # Giữ tối đa 500 entries
    if len(history["sessions"]) > 500:
        history["sessions"] = history["sessions"][-500:]
    
    _save_json(history_path, history)


# ============================================================
# QUICK ACTIONS — Tiểu Đệ dùng trực tiếp
# ============================================================

def quick_browse(name: str, url: str, screenshot_path: Optional[str] = None, wait: int = 5) -> str:
    """
    Mở profile, truy cập URL, chụp ảnh, đóng browser.
    Trả về title của trang.
    """
    import time as _time
    
    with open_browser(name, headless=True, url=url) as (context, page):
        _time.sleep(wait)
        
        title = page.title()
        
        if screenshot_path:
            page.screenshot(path=screenshot_path)
        
        return title


def quick_screenshot(name: str, url: str, output_path: str, wait: int = 5) -> str:
    """Chụp ảnh nhanh một trang với profile chỉ định."""
    return quick_browse(name, url, screenshot_path=output_path, wait=wait)


# ============================================================
# SUMMARY / STATS
# ============================================================

def summary() -> dict:
    """Tổng quan hệ thống."""
    profiles = list_profiles()
    total = len(profiles)
    
    with_proxy = sum(1 for p in profiles if p.get("proxy"))
    without_proxy = total - with_proxy
    
    # Lần dùng gần nhất
    last_used = None
    for p in profiles:
        lu = p.get("last_used")
        if lu and (not last_used or lu > last_used):
            last_used = lu
    
    tags = {}
    for p in profiles:
        for t in p.get("tags", []):
            tags[t] = tags.get(t, 0) + 1
    
    return {
        "total_profiles": total,
        "with_proxy": with_proxy,
        "without_proxy": without_proxy,
        "last_activity": last_used,
        "tags": tags,
    }


# ============================================================
# CLI (nếu chạy trực tiếp)
# ============================================================

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("CamoManager 🦊")
        print("Usage: python manager.py [list|create|info|delete|summary]")
        sys.exit(0)
    
    cmd = sys.argv[1]
    
    if cmd == "list":
        for p in list_profiles():
            proxy_status = "🟢" if p.get("proxy") else "⚪"
            uses = p.get("use_count", 0)
            print(f"  {proxy_status} {p['name']} — {uses} lần dùng — {p.get('note', '')}")
    
    elif cmd == "create":
        if len(sys.argv) < 3:
            print("Usage: python manager.py create <name> [proxy] [proxy_type] [note]")
            sys.exit(1)
        name = sys.argv[2]
        proxy = sys.argv[3] if len(sys.argv) > 3 else None
        ptype = sys.argv[4] if len(sys.argv) > 4 else "http"
        note = sys.argv[5] if len(sys.argv) > 5 else ""
        config = create_profile(name, proxy=proxy, proxy_type=ptype, note=note)
        print(f"✅ Tạo profile '{name}' thành công!")
    
    elif cmd == "info":
        if len(sys.argv) < 3:
            print("Usage: python manager.py info <name>")
            sys.exit(1)
        config = get_profile(sys.argv[2])
        print(json.dumps(config, indent=2, ensure_ascii=False))
    
    elif cmd == "delete":
        if len(sys.argv) < 3:
            print("Usage: python manager.py delete <name>")
            sys.exit(1)
        delete_profile(sys.argv[2])
        print(f"🗑️ Đã xóa profile '{sys.argv[2]}'")
    
    elif cmd == "summary":
        s = summary()
        print(f"📊 Tổng: {s['total_profiles']} profiles")
        print(f"   🟢 Có proxy: {s['with_proxy']}")
        print(f"   ⚪ Chưa proxy: {s['without_proxy']}")
        if s['tags']:
            print(f"   🏷️ Tags: {s['tags']}")
        if s['last_activity']:
            print(f"   🕐 Hoạt động gần nhất: {s['last_activity']}")
    
    else:
        print(f"Lệnh không hợp lệ: {cmd}")
