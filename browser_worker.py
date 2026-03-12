"""
Browser Worker - Chạy browser như worker process, nhận lệnh qua stdin pipe
Pattern: 1 process giữ browser sống, orchestrator gửi lệnh Python qua subprocess pipe

Architecture:
    [Script của Đại Ca] -- stdin pipe --> [browser_worker.py] -- playwright --> [Firefox/Camoufox]
                        <-- stdout json --

Worker chạy loop, nhận JSON commands, thực thi Playwright, trả kết quả JSON
"""

import json
import os
import sys
import time
import traceback
import base64
from pathlib import Path

BASE_DIR = Path(__file__).parent
PROFILES_DIR = BASE_DIR / "profiles"
LOCKS_DIR = BASE_DIR / "locks"
LOCKS_DIR.mkdir(exist_ok=True)

def send_response(cmd_id, success, data=None, error=None):
    resp = {"id": cmd_id, "success": success}
    if data is not None:
        resp["data"] = data
    if error is not None:
        resp["error"] = error
    print(json.dumps(resp, ensure_ascii=False), flush=True)


def run_worker(profile_name: str):
    import sys, json, time, traceback, base64
    from pathlib import Path
    sys.path.insert(0, str(BASE_DIR))

    config_path = PROFILES_DIR / profile_name / "config.json"
    if not config_path.exists():
        send_response(0, False, error=f"Profile '{profile_name}' không tồn tại!")
        sys.exit(1)

    with open(config_path) as f:
        config = json.load(f)

    browser_data_dir = str(PROFILES_DIR / profile_name / "browser_data")

    from camoufox import Camoufox
    from browserforge.fingerprints.generator import Screen as BFScreen

    kwargs = {
        "headless": True,
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

    # Launch browser
    camo = Camoufox(**kwargs)
    context = camo.__enter__()
    pages = context.pages
    page = pages[0] if pages else context.new_page()

    send_response(0, True, data={"status": "ready", "url": page.url, "pid": os.getpid()})

    # Command loop
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            cmd = json.loads(line)
        except json.JSONDecodeError as e:
            send_response(-1, False, error=f"Invalid JSON: {e}")
            continue

        cmd_id = cmd.get("id", -1)
        action = cmd.get("action", "")

        try:
            if action == "goto":
                url = cmd["url"]
                wait_until = cmd.get("wait_until", "networkidle")
                timeout = cmd.get("timeout", 60000)
                page.goto(url, wait_until=wait_until, timeout=timeout)
                send_response(cmd_id, True, data={"url": page.url})

            elif action == "screenshot":
                path = cmd.get("path", f"/tmp/{profile_name}_{int(time.time())}.png")
                full_page = cmd.get("full_page", True)
                page.screenshot(path=path, full_page=full_page)
                send_response(cmd_id, True, data={"path": path})

            elif action == "click":
                selector = cmd["selector"]
                timeout = cmd.get("timeout", 10000)
                page.click(selector, timeout=timeout)
                send_response(cmd_id, True, data={"url": page.url})

            elif action == "fill":
                selector = cmd["selector"]
                value = cmd["value"]
                page.fill(selector, value)
                send_response(cmd_id, True)

            elif action == "wait_for":
                selector = cmd["selector"]
                timeout = cmd.get("timeout", 30000)
                page.wait_for_selector(selector, timeout=timeout)
                send_response(cmd_id, True)

            elif action == "upload_file":
                selector = cmd["selector"]
                file_path = cmd["file_path"]
                page.set_input_files(selector, file_path)
                send_response(cmd_id, True)

            elif action == "eval":
                expr = cmd["expr"]
                result = page.evaluate(expr)
                send_response(cmd_id, True, data={"result": str(result)})

            elif action == "get_text":
                result = page.inner_text("body")
                send_response(cmd_id, True, data={"text": result[:2000]})

            elif action == "get_url":
                send_response(cmd_id, True, data={"url": page.url})

            elif action == "sleep":
                secs = cmd.get("seconds", 1)
                time.sleep(secs)
                send_response(cmd_id, True)

            elif action == "dismiss_popup":
                # Tìm và dismiss popup "Expand your music"
                try:
                    n = page.locator("text=Not now")
                    if n.is_visible(timeout=3000):
                        n.click()
                        time.sleep(0.5)
                        send_response(cmd_id, True, data={"dismissed": True})
                    else:
                        send_response(cmd_id, True, data={"dismissed": False})
                except Exception:
                    send_response(cmd_id, True, data={"dismissed": False})

            elif action == "quit":
                send_response(cmd_id, True, data={"status": "quitting"})
                break

            else:
                send_response(cmd_id, False, error=f"Unknown action: {action}")

        except Exception as e:
            send_response(cmd_id, False, error=f"{type(e).__name__}: {e}")

    # Cleanup
    try:
        camo.__exit__(None, None, None)
    except Exception:
        pass


if __name__ == "__main__":
    profile = sys.argv[1] if len(sys.argv) > 1 else "ACC001"
    run_worker(profile)
