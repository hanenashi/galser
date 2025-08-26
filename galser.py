#!/usr/bin/env python3
# file: thumb_server.py
#
# Local gallery server:
# - Thumbnail grid for images in current directory
# - Pure fullscreen viewer (no UI) with animated swipe between images
# - Swipe left/right (or Arrow keys). Android Back exits viewer to gallery.
#
# Run:  python thumb_server.py  [--port 8000]
# Open: http://127.0.0.1:8000

import http.server
import socketserver
import os
import sys
import re
import urllib.parse
from functools import lru_cache

IMAGE_EXTS = {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp', '.tiff', '.tif', '.avif'}
PORT = 8000

def human_sort_key(s):
    # Natural sort: splits digits and text so IMG2 < IMG10
    return [int(t) if t.isdigit() else t.lower() for t in re.findall(r'\d+|\D+', s)]

@lru_cache(maxsize=1)
def list_images():
    files = [f for f in os.listdir('.') if os.path.isfile(f)]
    imgs = [f for f in files if os.path.splitext(f)[1].lower() in IMAGE_EXTS]
    imgs.sort(key=human_sort_key)
    return imgs

def reset_cache():
    list_images.cache_clear()
    list_images()

def html_escape(s):
    return (s.replace("&", "&amp;")
             .replace("<", "&lt;")
             .replace(">", "&gt;")
             .replace('"', "&quot;"))

class GalleryHandler(http.server.SimpleHTTPRequestHandler):
    # Serve gallery at "/" and viewer at "/view"
    # Static files are served by the base class.

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path == '/refresh':
            reset_cache()
            self.send_response(302)
            self.send_header('Location', '/')
            self.end_headers()
            return

        if path == '/':
            return self._serve_gallery()
        if path == '/view':
            return self._serve_view(parsed.query)

        # Otherwise serve actual files
        return super().do_GET()

    def _serve_gallery(self):
        imgs = list_images()

        items_html = []
        for idx, name in enumerate(imgs):
            url = "/view?i=" + str(idx)
            img_src = "/" + urllib.parse.quote(name)
            title = html_escape(name)
            items_html.append(f'''
            <a class="card" href="{url}">
              <div class="thumb"><img loading="lazy" src="{img_src}" alt="{title}"></div>
              <div class="cap" title="{title}">{title}</div>
            </a>
            ''')

        html = f'''<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Local Gallery</title>
<style>
  :root {{
    --bg:#111; --fg:#eee; --muted:#aaa; --card:#1b1b1b;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin:0; font-family: system-ui, -apple-system, Segoe UI, Roboto, "Noto Sans", Arial, sans-serif;
    background: var(--bg); color: var(--fg);
  }}
  header {{
    position: sticky; top:0; z-index:10;
    background: linear-gradient(180deg, rgba(0,0,0,0.9), rgba(0,0,0,0.6));
    backdrop-filter: blur(6px);
    padding: 10px 14px; display:flex; gap:10px; align-items:center;
    border-bottom: 1px solid #222;
  }}
  header .title {{ font-weight:600; letter-spacing:0.3px; }}
  header .spacer {{ flex:1; }}
  header a.btn {{
    color: var(--fg); text-decoration:none; background:#222; padding:6px 10px; border-radius:8px; border:1px solid #333;
  }}
  .grid {{
    display:grid; gap:10px; padding:12px;
    grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
  }}
  .card {{
    display:block; text-decoration:none; color:inherit; background: var(--card);
    border:1px solid #222; border-radius:12px; overflow:hidden;
    transition: transform .08s ease, border-color .08s ease;
  }}
  .card:active {{ transform: scale(0.99); border-color:#444; }}
  .thumb {{ width:100%; aspect-ratio:1/1; background:#000; display:grid; place-items:center; }}
  .thumb img {{ width:100%; height:100%; object-fit:cover; }}
  .cap {{ font-size:12px; color:var(--muted); padding:8px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }}
  footer {{ padding:10px; text-align:center; color:#777; font-size:12px; }}
  .empty {{ text-align:center; padding:40px 20px; color:#bbb; }}
</style>
</head>
<body>
  <header>
    <div class="title">📷 Local Gallery</div>
    <div class="spacer"></div>
    <a class="btn" href="/refresh" title="Rescan folder">Rescan</a>
  </header>
  {'<div class="grid">' + ''.join(items_html) + '</div>' if imgs else '<div class="empty">No images found in this folder.</div>'}
  <footer>Folder: {html_escape(os.path.abspath("."))}</footer>
</body>
</html>'''
        self._send_html(html)

    def _serve_view(self, query):
        params = urllib.parse.parse_qs(query or '')
        try:
            idx = int(params.get('i', ['0'])[0])
        except ValueError:
            idx = 0
        imgs = list_images()
        if not imgs:
            self.send_response(302)
            self.send_header('Location', '/')
            self.end_headers()
            return

        idx = max(0, min(idx, len(imgs)-1))
        urls = ["/" + urllib.parse.quote(n) for n in imgs]

        html = f'''<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,user-scalable=no">
<title>Viewer</title>
<style>
  * {{ box-sizing:border-box; }}
  html, body {{
    margin:0; height:100%; background:#000; color:#fff; overscroll-behavior: none;
  }}
  .stage {{
    position:fixed; inset:0; background:#000; touch-action: pan-y; /* allow vertical scroll gestures */
    overflow:hidden;
  }}
  .layer {{
    position:absolute; inset:0; display:grid; place-items:center;
  }}
  img.viewer {{
    max-width:100vw; max-height:100vh; object-fit:contain;
    touch-action: pan-y;
    will-change: transform;
    transform: translateX(0px);
  }}
  /* We'll animate via JS by toggling transition on/off */
</style>
</head>
<body>
  <div class="stage" id="stage">
    <div class="layer"><img class="viewer" id="under"  alt=""></div>
    <div class="layer"><img class="viewer" id="current" alt=""></div>
  </div>

<script>
  const urls = {urls!r};
  let index = {idx};

  const cur = document.getElementById('current');
  const under = document.getElementById('under');
  const stage = document.getElementById('stage');

  function setNoTransition(el) {{ el.style.transition = 'none'; }}
  function setTransition(el)   {{ el.style.transition = 'transform 200ms ease-out'; }}

  function clamp(i) {{ return Math.max(0, Math.min(urls.length-1, i)); }}

  function show(i, replaceHistory=true) {{
    index = clamp(i);
    // Set current image; under hidden/reset
    setNoTransition(cur);
    setNoTransition(under);
    cur.src = urls[index];
    cur.style.transform = 'translateX(0px)';
    under.style.transform = 'translateX(0px)';
    under.style.visibility = 'hidden';

    const url = new URL(window.location.href);
    url.searchParams.set('i', index);
    if (replaceHistory) {{
      history.replaceState({{}}, '', url);
    }}

    // Attempt fullscreen on first show (may be ignored by some browsers)
    if (document.fullscreenEnabled && !document.fullscreenElement) {{
      document.documentElement.requestFullscreen().catch(()=>{{}});
    }}
  }}

  // Prepare the "under" image for a drag direction: dir = -1 (prev) or +1 (next)
  function prepareUnder(dir) {{
    const target = index + dir;
    if (target < 0 || target >= urls.length) {{
      under.style.visibility = 'hidden';
      return false;
    }}
    under.src = urls[target];
    under.style.visibility = 'visible';
    const W = window.innerWidth || 1;
    setNoTransition(under);
    under.style.transform = `translateX(${{dir>0 ? W : -W}}px)`;
    return true;
  }}

  // Commit the swipe to a new index (dir = -1 / +1)
  function commit(dir) {{
    const target = index + dir;
    if (target < 0 || target >= urls.length) return cancel(); // guard
    const W = window.innerWidth || 1;

    // Animate: current slides off, under slides into place
    setTransition(cur);
    setTransition(under);
    cur.style.transform   = `translateX(${{dir>0 ? -W : W}}px)`;
    under.style.transform = 'translateX(0px)';

    // After animation, swap in new current and reset under
    const onDone = () => {{
      cur.removeEventListener('transitionend', onDone);
      show(target, /*replaceHistory*/ true);
    }};
    cur.addEventListener('transitionend', onDone);
  }}

  function cancel() {{
    // Snap back to center, hide under
    setTransition(cur);
    setTransition(under);
    cur.style.transform = 'translateX(0px)';
    const W = window.innerWidth || 1;
    const dx = _dx; // last delta to know from which side to return under
    if (dx > 0) under.style.transform = `translateX(${{-W}}px)`;
    else if (dx < 0) under.style.transform = `translateX(${{W}}px)`;
    else under.style.transform = 'translateX(0px)';

    const onDone = () => {{
      cur.removeEventListener('transitionend', onDone);
      under.style.visibility = 'hidden';
    }};
    cur.addEventListener('transitionend', onDone);
  }}

  // --- Interactive drag (Pointer Events) ---
  let startX = null, startY = null, dragging = false;
  let _dx = 0, _dy = 0;
  const COMMIT = 80;   // px distance to commit swipe
  const MAX_OFF = 120; // allow some vertical drift

  function pd(e) {{
    dragging = true;
    startX = e.clientX; startY = e.clientY;
    _dx = 0; _dy = 0;
    setNoTransition(cur);
    setNoTransition(under);
  }}
  function pm(e) {{
    if (!dragging) return;
    _dx = e.clientX - startX;
    _dy = e.clientY - startY;

    // If hugely vertical, treat as scroll and don't animate
    if (Math.abs(_dy) > MAX_OFF) return;

    const dir = _dx < 0 ? +1 : -1; // dragging left => next (+1), right => prev (-1)
    const ok = prepareUnder(dir);

    // Apply resistance at edges (no next/prev)
    const edge = (!ok);
    const effectiveDx = edge ? (_dx * 0.3) : _dx;

    cur.style.transform = `translateX(${{effectiveDx}}px)`;
    if (ok) {{
      const W = window.innerWidth || 1;
      under.style.transform = `translateX(${{dir>0 ? (W + effectiveDx) : (-W + effectiveDx)}}px)`;
    }}
  }}
  function pu(e) {{
    if (!dragging) return;
    dragging = false;

    if (Math.abs(_dy) > MAX_OFF) {{
      return cancel();
    }}
    if (Math.abs(_dx) >= COMMIT) {{
      commit(_dx < 0 ? +1 : -1);
    }} else {{
      cancel();
    }}
  }}
  function pcancel() {{
    if (!dragging) return;
    dragging = false;
    cancel();
  }}

  [stage, cur].forEach(el => {{
    el.addEventListener('pointerdown', pd, {{ passive: true }});
    el.addEventListener('pointermove', pm, {{ passive: true }});
    el.addEventListener('pointerup', pu,   {{ passive: true }});
    el.addEventListener('pointercancel', pcancel, {{ passive: true }});
    el.addEventListener('pointerleave',  pcancel, {{ passive: true }});
  }});

  // Keyboard fallback
  window.addEventListener('keydown', (e) => {{
    if (e.key === 'ArrowRight') commit(+1);
    else if (e.key === 'ArrowLeft') commit(-1);
    else if (e.key === 'Escape') window.location.href = '/';
  }});

  // Back → gallery
  window.onpopstate = () => {{ location.href = '/'; }};

  // Initial render
  show(index, true);
</script>
</body>
</html>'''
        self._send_html(html)

    def _send_html(self, html):
        data = html.encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

def main():
    global PORT
    if len(sys.argv) >= 3 and sys.argv[1] in ('-p', '--port'):
        try:
            PORT = int(sys.argv[2])
        except ValueError:
            pass

    handler = GalleryHandler
    with socketserver.TCPServer(("", PORT), handler) as httpd:
        print(f"Serving ⟶  http://127.0.0.1:{PORT}")
        print(f"Tip: On your phone, open  http://<your-computer-LAN-IP>:{PORT}")
        print("Press Ctrl+C to stop.")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nShutting down...")

if __name__ == '__main__':
    reset_cache()
    main()
