"""
Browser Worker v2 - Socket-based
Worker giữ browser sống, lắng nghe lệnh qua Unix socket.
Nhiều process/script khác nhau có thể kết nối cùng lúc!

Socket path: camo-manager/locks/<profile>.sock
"""

import json
import os
import select
import signal
import socket
import sys
import time
import threading
from pathlib import Path

BASE_DIR = Path(__file__).parent
PROFILES_DIR = BASE_DIR / "profiles"
LOCKS_DIR = BASE_DIR / "locks"
LOCKS_DIR.mkdir(exist_ok=True)


def get_socket_path(name: str) -> str:
    return str(LOCKS_DIR / f"{name}.sock")


def get_lock_path(name: str) -> str:
    return str(LOCKS_DIR / f"{name}.json")


def handle_client(conn, page, context, profile_name):
    """Xử lý kết nối từ 1 client."""
    try:
        buf = ""
        conn.settimeout(300)  # 5 phút timeout
        while True:
            try:
                data = conn.recv(65536)
                if not data:
                    break
                buf += data.decode()
                while "\n" in buf:
                    line, buf = buf.split("\n", 1)
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        cmd = json.loads(line)
                    except json.JSONDecodeError as e:
                        resp = {"id": -1, "success": False, "error": f"JSON parse error: {e}"}
                        conn.send((json.dumps(resp) + "\n").encode())
                        continue

                    resp = execute_command(cmd, page, context, profile_name)
                    conn.send((json.dumps(resp, ensure_ascii=False) + "\n").encode())

                    if cmd.get("action") == "quit":
                        return
            except socket.timeout:
                break
            except ConnectionResetError:
                break
    except Exception as e:
        pass
    finally:
        try:
            conn.close()
        except Exception:
            pass


def execute_command(cmd: dict, page, context, profile_name: str) -> dict:
    """Thực thi 1 lệnh Playwright."""
    cmd_id = cmd.get("id", -1)
    action = cmd.get("action", "")

    try:
        if action == "ping":
            return {"id": cmd_id, "success": True, "data": {"pong": True, "url": page.url}}

        elif action == "goto":
            url = cmd["url"]
            wait_until = cmd.get("wait_until", "networkidle")
            timeout = cmd.get("timeout", 60000)
            page.goto(url, wait_until=wait_until, timeout=timeout)
            return {"id": cmd_id, "success": True, "data": {"url": page.url}}

        elif action == "screenshot":
            path = cmd.get("path", f"/tmp/{profile_name}_{int(time.time())}.png")
            full_page = cmd.get("full_page", True)
            page.screenshot(path=path, full_page=full_page)
            return {"id": cmd_id, "success": True, "data": {"path": path}}

        elif action == "click":
            selector = cmd["selector"]
            timeout = cmd.get("timeout", 10000)
            page.click(selector, timeout=timeout)
            return {"id": cmd_id, "success": True, "data": {"url": page.url}}

        elif action == "fill":
            selector = cmd["selector"]
            value = cmd["value"]
            page.fill(selector, value)
            return {"id": cmd_id, "success": True}

        elif action == "wait_for":
            selector = cmd["selector"]
            timeout = cmd.get("timeout", 30000)
            page.wait_for_selector(selector, timeout=timeout)
            return {"id": cmd_id, "success": True}

        elif action == "upload_file":
            selector = cmd["selector"]
            file_path = cmd["file_path"]
            page.set_input_files(selector, file_path)
            return {"id": cmd_id, "success": True}

        elif action == "eval":
            result = page.evaluate(cmd["expr"])
            return {"id": cmd_id, "success": True, "data": {"result": str(result)}}

        elif action == "get_text":
            text = page.inner_text("body")
            return {"id": cmd_id, "success": True, "data": {"text": text[:5000]}}

        elif action == "get_url":
            return {"id": cmd_id, "success": True, "data": {"url": page.url}}

        elif action == "sleep":
            time.sleep(cmd.get("seconds", 1))
            return {"id": cmd_id, "success": True}

        elif action == "dismiss_popup":
            try:
                n = page.locator("text=Not now")
                if n.is_visible(timeout=3000):
                    n.click()
                    time.sleep(0.5)
                    return {"id": cmd_id, "success": True, "data": {"dismissed": True}}
                return {"id": cmd_id, "success": True, "data": {"dismissed": False}}
            except Exception:
                return {"id": cmd_id, "success": True, "data": {"dismissed": False}}

        elif action == "reload":
            page.reload(wait_until="networkidle", timeout=cmd.get("timeout", 30000))
            return {"id": cmd_id, "success": True, "data": {"url": page.url}}

        elif action == "quit":
            return {"id": cmd_id, "success": True, "data": {"status": "shutting_down"}}

        else:
            return {"id": cmd_id, "success": False, "error": f"Unknown action: {action}"}

    except Exception as e:
        import traceback
        return {"id": cmd_id, "success": False, "error": f"{type(e).__name__}: {e}"}


def run_server(profile_name: str, headless: bool = True):
    """Main worker loop."""
    config_path = PROFILES_DIR / profile_name / "config.json"
    if not config_path.exists():
        print(json.dumps({"id": 0, "success": False, "error": f"Profile '{profile_name}' không tồn tại!"}), flush=True)
        sys.exit(1)

    with open(config_path) as f:
        config = json.load(f)

    browser_data_dir = str(PROFILES_DIR / profile_name / "browser_data")

    from camoufox import Camoufox
    from browserforge.fingerprints.generator import Screen as BFScreen

    kwargs = {
        "headless": headless,
        "persistent_context": True,
        "user_data_dir": browser_data_dir,
        "geoip": True,
        "screen": BFScreen(min_width=1920, max_width=1920, min_height=1080, max_height=1080),
        "viewport": {"width": 1920, "height": 1080},
    }

    if config.get("proxy"):
        proxy_str = config["proxy"]
        host_port = proxy_str.split("@")[-1]
        parts = host_port.split(":")
        kwargs["proxy"] = {"server": f"{parts[0]}:{parts[1]}"}

    camo = Camoufox(**kwargs)
    context = camo.__enter__()
    pages = context.pages
    page = pages[0] if pages else context.new_page()

    # Unix socket server
    sock_path = get_socket_path(profile_name)
    if os.path.exists(sock_path):
        os.unlink(sock_path)

    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(sock_path)
    server.listen(10)
    os.chmod(sock_path, 0o666)

    # Ghi lock file
    lock_data = {
        "name": profile_name,
        "pid": os.getpid(),
        "socket": sock_path,
        "started_at": time.time(),
    }
    with open(get_lock_path(profile_name), "w") as f:
        json.dump(lock_data, f, indent=2)

    print(json.dumps({"id": 0, "success": True, "data": {"status": "ready", "pid": os.getpid(), "socket": sock_path, "url": page.url}}), flush=True)

    # Signal handlers
    def shutdown(sig=None, frame=None):
        try:
            camo.__exit__(None, None, None)
        except Exception:
            pass
        try:
            os.unlink(sock_path)
        except Exception:
            pass
        try:
            os.unlink(get_lock_path(profile_name))
        except Exception:
            pass
        sys.exit(0)

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    should_quit = threading.Event()

    def accept_loop():
        while not should_quit.is_set():
            try:
                server.settimeout(1)
                conn, _ = server.accept()
                t = threading.Thread(target=handle_client_wrapper, args=(conn,), daemon=True)
                t.start()
            except socket.timeout:
                continue
            except Exception:
                break

    def handle_client_wrapper(conn):
        nonlocal page
        try:
            buf = ""
            conn.settimeout(300)
            while True:
                data = conn.recv(65536)
                if not data:
                    break
                buf += data.decode()
                while "\n" in buf:
                    line, buf = buf.split("\n", 1)
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        cmd = json.loads(line)
                    except Exception as e:
                        conn.send((json.dumps({"id": -1, "success": False, "error": str(e)}) + "\n").encode())
                        continue
                    resp = execute_command(cmd, page, context, profile_name)
                    conn.send((json.dumps(resp, ensure_ascii=False) + "\n").encode())
                    if cmd.get("action") == "quit":
                        should_quit.set()
                        return
        except Exception:
            pass
        finally:
            try:
                conn.close()
            except Exception:
                pass

    t = threading.Thread(target=accept_loop, daemon=True)
    t.start()
    t.join()
    shutdown()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("profile", default="ACC001", nargs="?")
    parser.add_argument("--headless", action="store_true", default=True)
    args = parser.parse_args()
    run_server(args.profile, headless=args.headless)
