#!/usr/bin/env python3
"""
Browser Worker v3 - Camoufox persistent browser process
- 1 process per profile, keeps browser alive
- Receives JSON commands via stdin, returns JSON via stdout
- Supports multi-tab operations
- Proper persistent context for cookie retention
"""
import sys, json, time, os, traceback, threading
from pathlib import Path

def main():
    config = json.loads(sys.argv[1])
    profile_name = config['profile']
    data_dir = config['data_dir']
    headless = config.get('headless', False)
    proxy = config.get('proxy', None)
    viewport = config.get('viewport', {})
    geoip = config.get('geoip', True)

    # Default viewport if not set
    if not viewport or not viewport.get('width'):
        viewport = {'width': 1920, 'height': 1080}

    # Import camoufox
    from camoufox.sync_api import Camoufox
    from browserforge.fingerprints.generator import Screen as BFScreen

    # Build launch kwargs
    # Always pin screen to match viewport so Camoufox doesn't randomize
    vw, vh = viewport['width'], viewport['height']
    launch_kw = {
        'persistent_context': True,
        'user_data_dir': data_dir,
        'headless': headless,
        'geoip': geoip,
        'screen': BFScreen(min_width=vw, max_width=vw, min_height=vh, max_height=vh),
        'viewport': viewport,
        'enable_cache': True,
        'firefox_user_prefs': {
            # Enable back/forward navigation and session history
            'browser.sessionhistory.max_entries': 50,
            'browser.sessionhistory.max_total_viewers': -1,
            # Enable bookmarks
            'browser.bookmarks.restore_default_bookmarks': False,
            'browser.toolbars.bookmarks.visibility': 'always',
            # Keep browsing history
            'places.history.enabled': True,
            'privacy.clearOnShutdown.history': False,
            'privacy.clearOnShutdown_v2.historyFormDataAndDownloads': False,
        },
    }

    if proxy:
        ptype = proxy.get('type', 'socks5')
        host, port = proxy['host'], proxy['port']
        launch_kw['proxy'] = {
            'server': f'{ptype}://{host}:{port}',
        }
        if proxy.get('username'):
            launch_kw['proxy']['username'] = proxy['username']
            launch_kw['proxy']['password'] = proxy.get('password', '')

    # Signal ready
    def respond(data):
        sys.stdout.write(json.dumps(data) + '\n')
        sys.stdout.flush()

    def respond_ok(result=None):
        respond({'status': 'ok', 'result': result})

    def respond_err(msg):
        respond({'status': 'error', 'error': str(msg)})

    try:
        with Camoufox(**launch_kw) as browser:
            # Get default page or create one
            pages = browser.pages if hasattr(browser, 'pages') else []
            if not pages:
                pages = [browser.new_page()]

            # Tab management: tab_id -> page
            tabs = {'main': pages[0]}
            active_tab = 'main'

            # --- Watchdog: detect browser closed by user (X button) ---
            browser_dead = threading.Event()

            def watchdog():
                """Check every 2s if browser is still alive.
                When user closes browser window, page ops will fail.
                We then close stdin to unblock the command loop."""
                while not browser_dead.is_set():
                    time.sleep(2)
                    try:
                        main_page = tabs.get('main')
                        if main_page:
                            _ = main_page.url
                    except Exception:
                        browser_dead.set()
                        try:
                            sys.stdin.close()
                        except Exception:
                            pass
                        break

            wd = threading.Thread(target=watchdog, daemon=True)
            wd.start()
            # --- End watchdog ---

            respond({'status': 'ready', 'profile': profile_name, 'tabs': list(tabs.keys())})

            # Command loop
            for line in sys.stdin:
                if browser_dead.is_set():
                    break

                line = line.strip()
                if not line:
                    continue

                try:
                    cmd = json.loads(line)
                except json.JSONDecodeError:
                    respond_err('Invalid JSON')
                    continue

                action = cmd.get('action', '')
                tab_id = cmd.get('tab', active_tab)
                page = tabs.get(tab_id)

                try:
                    # Tab management
                    if action == 'new_tab':
                        new_id = cmd.get('id', f'tab_{len(tabs)}')
                        new_page = browser.new_page()
                        tabs[new_id] = new_page
                        active_tab = new_id
                        respond_ok({'tab': new_id, 'tabs': list(tabs.keys())})
                        continue

                    elif action == 'close_tab':
                        if tab_id == 'main':
                            respond_err('Cannot close main tab')
                            continue
                        if tab_id in tabs:
                            tabs[tab_id].close()
                            del tabs[tab_id]
                            if active_tab == tab_id:
                                active_tab = 'main'
                        respond_ok({'tabs': list(tabs.keys())})
                        continue

                    elif action == 'list_tabs':
                        respond_ok({'tabs': list(tabs.keys()), 'active': active_tab})
                        continue

                    elif action == 'switch_tab':
                        if tab_id in tabs:
                            active_tab = tab_id
                            respond_ok({'active': active_tab})
                        else:
                            respond_err(f'Tab not found: {tab_id}')
                        continue

                    # Require valid page for other actions
                    if not page:
                        respond_err(f'Tab not found: {tab_id}')
                        continue

                    # Navigation
                    if action == 'goto':
                        url = cmd['url']
                        timeout = cmd.get('timeout', 60000)
                        page.goto(url, timeout=timeout)
                        page.wait_for_load_state('networkidle', timeout=120000)
                        respond_ok({'url': page.url, 'title': page.title()})

                    elif action == 'reload':
                        page.reload(timeout=cmd.get('timeout', 30000))
                        respond_ok()

                    elif action == 'go_back':
                        page.go_back(timeout=cmd.get('timeout', 30000))
                        respond_ok()

                    # Interaction
                    elif action == 'click':
                        selector = cmd['selector']
                        timeout = cmd.get('timeout', 5000)
                        click_count = cmd.get('click_count', 1)
                        el = page.locator(selector).first
                        el.click(timeout=timeout, click_count=click_count)
                        respond_ok()

                    elif action == 'fill':
                        selector = cmd['selector']
                        value = cmd['value']
                        timeout = cmd.get('timeout', 5000)
                        el = page.locator(selector).first
                        el.wait_for(timeout=timeout)
                        el.click(click_count=3)  # Select all first
                        el.fill(value)
                        respond_ok()

                    elif action == 'type':
                        selector = cmd['selector']
                        text = cmd['text']
                        delay = cmd.get('delay', 50)
                        el = page.locator(selector).first
                        el.type(text, delay=delay)
                        respond_ok()

                    elif action == 'select_option':
                        selector = cmd['selector']
                        value = cmd.get('value')
                        label = cmd.get('label')
                        kw = {}
                        if value is not None: kw['value'] = value
                        if label is not None: kw['label'] = label
                        page.locator(selector).first.select_option(**kw)
                        respond_ok()

                    elif action == 'check':
                        page.locator(cmd['selector']).first.check()
                        respond_ok()

                    elif action == 'uncheck':
                        page.locator(cmd['selector']).first.uncheck()
                        respond_ok()

                    # File upload
                    elif action == 'upload_file':
                        selector = cmd['selector']
                        path = cmd['path']
                        el = page.locator(selector).first
                        el.set_input_files(path)
                        respond_ok()

                    # Screenshot
                    elif action == 'screenshot':
                        path = cmd.get('path', f'/tmp/screenshot_{int(time.time())}.png')
                        full_page = cmd.get('full_page', False)
                        os.makedirs(os.path.dirname(path), exist_ok=True)
                        page.screenshot(path=path, full_page=full_page)
                        respond_ok({'path': path})

                    # Page info
                    elif action == 'get_text':
                        text = page.inner_text('body', timeout=cmd.get('timeout', 5000))
                        respond_ok({'text': text})

                    elif action == 'get_html':
                        html = page.content()
                        respond_ok({'html': html})

                    elif action == 'get_url':
                        respond_ok({'url': page.url, 'title': page.title()})

                    # Evaluate JS
                    elif action == 'evaluate':
                        expr = cmd['expression']
                        result = page.evaluate(expr)
                        respond_ok({'result': result})

                    # Wait
                    elif action == 'wait_for_selector':
                        selector = cmd['selector']
                        timeout = cmd.get('timeout', 10000)
                        state = cmd.get('state', 'visible')
                        page.locator(selector).first.wait_for(timeout=timeout, state=state)
                        respond_ok()

                    elif action == 'wait_for_text':
                        text = cmd['text']
                        timeout = cmd.get('timeout', 10000)
                        page.locator(f'text={text}').first.wait_for(timeout=timeout)
                        respond_ok()

                    elif action == 'wait_for_load':
                        state = cmd.get('state', 'networkidle')
                        timeout = cmd.get('timeout', 30000)
                        page.wait_for_load_state(state, timeout=timeout)
                        respond_ok()

                    # Scroll
                    elif action == 'scroll':
                        x = cmd.get('x', 0)
                        y = cmd.get('y', 0)
                        page.evaluate(f'window.scrollTo({x}, {y})')
                        respond_ok()

                    elif action == 'scroll_by':
                        dx = cmd.get('dx', 0)
                        dy = cmd.get('dy', 0)
                        page.evaluate(f'window.scrollBy({dx}, {dy})')
                        respond_ok()

                    # Utility
                    elif action == 'sleep':
                        time.sleep(cmd.get('duration', 1))
                        respond_ok()

                    elif action == 'bring_to_front':
                        # Try current page first, fallback to any alive page
                        try:
                            page.bring_to_front()
                        except Exception:
                            alive_pages = browser.pages if hasattr(browser, 'pages') else []
                            if alive_pages:
                                alive_pages[0].bring_to_front()
                                tabs[active_tab] = alive_pages[0]
                            else:
                                # No pages left, create one
                                new_p = browser.new_page()
                                tabs[active_tab] = new_p
                                new_p.bring_to_front()
                        respond_ok()

                    elif action == 'count':
                        selector = cmd['selector']
                        n = page.locator(selector).count()
                        respond_ok({'count': n})

                    elif action == 'is_visible':
                        selector = cmd['selector']
                        vis = page.locator(selector).first.is_visible()
                        respond_ok({'visible': vis})

                    elif action == 'get_attribute':
                        selector = cmd['selector']
                        attr = cmd['attribute']
                        val = page.locator(selector).first.get_attribute(attr)
                        respond_ok({'value': val})

                    elif action == 'cookies':
                        # Get all cookies
                        cookies = browser.cookies() if hasattr(browser, 'cookies') else []
                        respond_ok({'cookies': cookies})

                    elif action == 'ping':
                        respond_ok({'pong': True, 'url': page.url})

                    else:
                        respond_err(f'Unknown action: {action}')

                except Exception as e:
                    respond_err(f'{action}: {str(e)}')

    except Exception as e:
        respond({'status': 'fatal', 'error': str(e), 'traceback': traceback.format_exc()})
        sys.exit(1)

if __name__ == '__main__':
    main()
