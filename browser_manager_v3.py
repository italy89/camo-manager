#!/usr/bin/env python3
"""
Browser Manager v3 - Multi-profile, multi-tab, thread-safe
==========================================================
Improvements over v2:
- Fix cookie persistence: proper data_dir resolution + legacy path support
- Multi-tab support per profile (new_tab, close_tab, switch_tab)
- Thread-safe concurrent commands via threading locks (no file locks)
- Better error handling with typed responses
- Clean API with type hints

Usage:
    bm = BrowserManager()
    bm.open_browser('ACC001')
    bm.cmd('ACC001', 'goto', url='https://example.com')
    bm.cmd('ACC001', 'screenshot', path='test.png')
    
    # Multi-tab
    bm.cmd('ACC001', 'new_tab', id='tab2')
    bm.cmd('ACC001', 'goto', url='https://other.com', tab='tab2')
    
    # Concurrent profiles
    bm.open_browser('ACC002')
    # ACC001 and ACC002 run in parallel processes
    
    bm.close_browser('ACC001')
"""
import json, os, subprocess, sys, threading, time
from pathlib import Path
from typing import Any, Optional
from datetime import datetime, timezone

BASE_DIR = Path(__file__).parent
PROFILES_DIR = BASE_DIR / "profiles"
LOCKS_DIR = BASE_DIR / "locks"
VENV_PYTHON = BASE_DIR.parent / "camoufox-env" / "bin" / "python3"
WORKER_SCRIPT = BASE_DIR / "browser_worker_v3.py"

# Legacy profile dir (upload_soundon.py cũ dùng path này)
LEGACY_PROFILE_DIR = Path.home() / ".camoufox-profile"


class BrowserError(Exception):
    pass


class ProfileWorker:
    """Manages a single browser worker process."""
    
    def __init__(self, name: str, process: subprocess.Popen, lock: threading.Lock):
        self.name = name
        self.process = process
        self.lock = lock
        self.started_at = time.time()
        self._read_lock = threading.Lock()
    
    def send(self, command: dict, timeout: float = 60) -> dict:
        """Send command and get response. Thread-safe."""
        with self.lock:
            try:
                line = json.dumps(command) + '\n'
                self.process.stdin.write(line)
                self.process.stdin.flush()

                # Read response with timeout
                self.process.stdout.settimeout(timeout) if hasattr(self.process.stdout, 'settimeout') else None
                resp_line = self.process.stdout.readline()
                if not resp_line:
                    raise BrowserError(f"Browser '{self.name}' is no longer running")
                return json.loads(resp_line.strip())
            except json.JSONDecodeError as e:
                raise BrowserError(f"Invalid response from worker: {e}")
            except (BrokenPipeError, OSError):
                raise BrowserError(f"Browser '{self.name}' is no longer running")
    
    @property
    def alive(self) -> bool:
        return self.process.poll() is None


class BrowserManager:
    """Multi-profile browser manager with thread-safe command dispatch."""
    
    def __init__(self):
        self.workers: dict[str, ProfileWorker] = {}
        self._global_lock = threading.Lock()
        LOCKS_DIR.mkdir(exist_ok=True)
        PROFILES_DIR.mkdir(exist_ok=True)
    
    def _resolve_data_dir(self, name: str) -> str:
        """Resolve browser data directory. Checks legacy path first."""
        # Check legacy path (has actual cookies/data)
        legacy = LEGACY_PROFILE_DIR / name
        if legacy.exists() and any(legacy.iterdir()):
            # Legacy dir has data — use it
            return str(legacy)
        
        # Use camo-manager profile dir
        profile_data = PROFILES_DIR / name / "browser_data"
        profile_data.mkdir(parents=True, exist_ok=True)
        return str(profile_data)
    
    def _load_config(self, name: str) -> dict:
        """Load profile config."""
        config_path = PROFILES_DIR / name / "config.json"
        if config_path.exists():
            with open(config_path) as f:
                return json.load(f)
        return {}
    
    def _save_config(self, name: str, config: dict):
        """Save profile config."""
        config_dir = PROFILES_DIR / name
        config_dir.mkdir(parents=True, exist_ok=True)
        with open(config_dir / "config.json", 'w') as f:
            json.dump(config, f, indent=2)
    
    def _update_history(self, name: str, action: str):
        """Update profile usage history."""
        hist_path = PROFILES_DIR / name / "history.json"
        history = []
        if hist_path.exists():
            try:
                with open(hist_path) as f:
                    data = json.load(f)
                    # Handle both formats: list or {"sessions": list}
                    if isinstance(data, list):
                        history = data
                    elif isinstance(data, dict) and 'sessions' in data:
                        history = data['sessions']
            except: pass
        
        history.append({
            'action': action,
            'timestamp': datetime.now(timezone.utc).isoformat(),
        })
        # Keep last 100 entries
        history = history[-100:]
        with open(hist_path, 'w') as f:
            json.dump(history, f, indent=2)
    
    def open_browser(self, name: str, headless: Optional[bool] = None) -> bool:
        """Open browser for profile. Returns True if successful."""
        with self._global_lock:
            # Already running?
            if name in self.workers and self.workers[name].alive:
                print(f"[{name}] Already running")
                return True
            
            config = self._load_config(name)
            data_dir = self._resolve_data_dir(name)
            
            # Override headless if specified
            if headless is not None:
                config['headless'] = headless
            
            worker_config = {
                'profile': name,
                'data_dir': data_dir,
                'headless': config.get('headless', False),
                'geoip': config.get('geoip', True),
                'screen': config.get('screen', {}),
                'viewport': config.get('viewport', {}),
            }
            
            # Proxy - normalize to dict format
            if config.get('proxy'):
                proxy = config['proxy']
                if isinstance(proxy, str):
                    # Parse string format "host:port"
                    parts = proxy.rsplit(':', 1)
                    proxy = {
                        'host': parts[0],
                        'port': int(parts[1]) if len(parts) > 1 else 1080,
                        'type': config.get('proxy_type', 'socks5'),
                    }
                worker_config['proxy'] = proxy
            
            print(f"[{name}] Opening browser (data_dir={data_dir}, headless={worker_config['headless']})")
            
            try:
                proc = subprocess.Popen(
                    [str(VENV_PYTHON), str(WORKER_SCRIPT), json.dumps(worker_config)],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    bufsize=1,
                )
                
                # Wait for ready signal
                ready_line = proc.stdout.readline()
                if not ready_line:
                    stderr = proc.stderr.read()
                    print(f"[{name}] Worker failed to start: {stderr[:500]}")
                    return False
                
                resp = json.loads(ready_line.strip())
                if resp.get('status') == 'fatal':
                    print(f"[{name}] Worker fatal: {resp.get('error')}")
                    return False
                
                if resp.get('status') != 'ready':
                    print(f"[{name}] Unexpected response: {resp}")
                    return False
                
                worker = ProfileWorker(name, proc, threading.Lock())
                self.workers[name] = worker
                self._update_history(name, 'opened')
                
                # Update use_count
                config['use_count'] = config.get('use_count', 0) + 1
                config['last_used'] = datetime.now(timezone.utc).isoformat()
                self._save_config(name, config)
                
                print(f"[{name}] ✅ Ready (tabs: {resp.get('tabs', [])})")
                return True
                
            except Exception as e:
                print(f"[{name}] ❌ Failed: {e}")
                return False
    
    def close_browser(self, name: str):
        """Close browser for profile."""
        with self._global_lock:
            worker = self.workers.pop(name, None)
        
        if worker and worker.alive:
            try:
                worker.send({'action': 'close'}, timeout=10)
            except: pass
            
            try:
                worker.process.terminate()
                worker.process.wait(timeout=5)
            except:
                worker.process.kill()
            
            self._update_history(name, 'closed')
            print(f"[{name}] 🔒 Closed")
        else:
            print(f"[{name}] Not running")
    
    def cmd(self, name: str, action: str, timeout: float = 60, **params) -> Any:
        """Send command to profile worker. Thread-safe.
        
        Returns the result value directly (unwrapped from response).
        Raises BrowserError on failure.
        """
        worker = self.workers.get(name)
        if not worker or not worker.alive:
            raise BrowserError(f"Profile {name} not running")
        
        command = {'action': action, **params}
        resp = worker.send(command, timeout=timeout)
        
        if resp.get('status') == 'error':
            raise BrowserError(resp.get('error', 'Unknown error'))
        
        return resp.get('result')
    
    # === Convenience methods ===
    
    def goto(self, name: str, url: str, **kw):
        return self.cmd(name, 'goto', url=url, **kw)
    
    def click(self, name: str, selector: str, **kw):
        return self.cmd(name, 'click', selector=selector, **kw)
    
    def fill(self, name: str, selector: str, value: str, **kw):
        return self.cmd(name, 'fill', selector=selector, value=value, **kw)
    
    def screenshot(self, name: str, path: str, **kw):
        return self.cmd(name, 'screenshot', path=path, **kw)
    
    def evaluate(self, name: str, expression: str, **kw):
        return self.cmd(name, 'evaluate', expression=expression, **kw)
    
    def get_text(self, name: str, **kw) -> str:
        result = self.cmd(name, 'get_text', **kw)
        return result.get('text', '') if isinstance(result, dict) else ''
    
    def upload_file(self, name: str, selector: str, path: str, **kw):
        return self.cmd(name, 'upload_file', selector=selector, path=path, **kw)
    
    def scroll(self, name: str, x: int = 0, y: int = 0):
        return self.cmd(name, 'scroll', x=x, y=y)

    def show_browser(self, name: str):
        """Bring browser window to front. Cleans up dead worker if needed."""
        worker = self.workers.get(name)
        if not worker or not worker.alive:
            # Clean up dead worker
            self.workers.pop(name, None)
            raise BrowserError(f"Profile {name} not running")
        return self.cmd(name, 'bring_to_front')

    def sleep(self, name: str, duration: float = 1):
        return self.cmd(name, 'sleep', duration=duration)
    
    def wait_for(self, name: str, selector: str, **kw):
        return self.cmd(name, 'wait_for_selector', selector=selector, **kw)
    
    def new_tab(self, name: str, tab_id: str = None, **kw):
        params = {}
        if tab_id:
            params['id'] = tab_id
        return self.cmd(name, 'new_tab', **params, **kw)
    
    def close_tab(self, name: str, tab_id: str):
        return self.cmd(name, 'close_tab', tab=tab_id)

    # === Info methods ===
    
    def status(self) -> dict:
        result = {}
        dead_workers = []
        for name, w in list(self.workers.items()):
            # Process already exited?
            if not w.alive:
                dead_workers.append(name)
                result[name] = {'alive': False, 'uptime': 0, 'url': ''}
                continue

            info = {
                'alive': True,
                'uptime': int(time.time() - w.started_at),
                'url': '',
            }
            # Ping to check if browser is actually alive
            try:
                r = w.send({'action': 'ping'}, timeout=5)
                if r.get('status') == 'error':
                    # Process alive but browser dead (user closed X)
                    info['alive'] = False
                    dead_workers.append(name)
                else:
                    info['url'] = r.get('result', {}).get('url', '')
            except Exception:
                info['alive'] = False
                dead_workers.append(name)
            result[name] = info

        # Clean up dead workers
        for name in dead_workers:
            w = self.workers.pop(name, None)
            if w:
                try:
                    w.process.terminate()
                    w.process.wait(timeout=3)
                except Exception:
                    try:
                        w.process.kill()
                    except Exception:
                        pass
                self._update_history(name, 'closed')
        return result
    
    def list_profiles(self) -> list:
        profiles = []
        for d in sorted(PROFILES_DIR.iterdir()):
            if d.is_dir() and (d / 'config.json').exists():
                config = self._load_config(d.name)
                profiles.append({
                    'name': d.name,
                    'running': d.name in self.workers and self.workers[d.name].alive,
                    'use_count': config.get('use_count', 0),
                    'last_used': config.get('last_used', ''),
                    'data_dir': self._resolve_data_dir(d.name),
                })
        return profiles
    
    def close_all(self):
        """Close all running browsers."""
        names = list(self.workers.keys())
        for name in names:
            self.close_browser(name)


# CLI interface
if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Browser Manager v3')
    parser.add_argument('action', choices=['list', 'status', 'open', 'close', 'close-all'])
    parser.add_argument('--profile', '-p', help='Profile name')
    parser.add_argument('--headless', action='store_true')
    args = parser.parse_args()
    
    bm = BrowserManager()
    
    if args.action == 'list':
        for p in bm.list_profiles():
            status = '🟢' if p['running'] else '⚪'
            print(f"  {status} {p['name']} (uses: {p['use_count']}, data: {p['data_dir']})")
    
    elif args.action == 'status':
        s = bm.status()
        if not s:
            print("  No browsers running")
        for name, info in s.items():
            print(f"  {'🟢' if info['alive'] else '🔴'} {name}: {info}")
    
    elif args.action == 'open':
        if not args.profile:
            print("Need --profile")
            sys.exit(1)
        bm.open_browser(args.profile, headless=args.headless or None)
    
    elif args.action == 'close':
        if not args.profile:
            print("Need --profile")
            sys.exit(1)
        bm.close_browser(args.profile)
    
    elif args.action == 'close-all':
        bm.close_all()
