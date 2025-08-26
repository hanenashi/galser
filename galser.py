#!/usr/bin/env python3
# file: galser.py
#
# Local gallery server with subfolder browsing:
# - Gallery shows subfolders (first) and image thumbnails.
# - Tap folder to open that folder's gallery; first card in subfolder is 🔙 (up).
# - ⚙️ Settings overlay with a slider to change thumbnail size live (persists).
# - Pure fullscreen viewer (no UI) with animated swipe between images.
# - Android Back leaves viewer to the folder gallery you came from.
#
# Run:  python galser.py  [--port 8000]
# Open: http://127.0.0.1:8000

import http.server
import socketserver
import os
import sys
import re
import urllib.parse
import mimetypes
from functools import lru_cache

IMAGE_EXTS = {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp', '.tiff', '.tif', '.avif'}
PORT = 8000

BASE_ROOT = os.path.abspath(os.getcwd())  # root of browsing

def human_sort_key(s):
    return [int(t) if t.isdigit() else t.lower() for t in re.findall(r'\d+|\D+', s)]

def norm_rel(rel):
    """Normalize a user-supplied relative path and keep it inside BASE_ROOT."""
    rel = rel.strip().replace('\\', '/')
    rel = rel.lstrip('/')  # force relative
    norm = os.path.normpath(rel)
    if norm in ('.', ''):
        return ''
    if norm.startswith('..'):
        return ''
    return norm.replace('\\', '/')

def safe_join(rel, *parts):
    rel = norm_rel(rel)
    path = os.path.abspath(os.path.join(BASE_ROOT, rel, *parts))
    if not path.startswith(BASE_ROOT):
        raise PermissionError("Path traversal blocked")
    return path

@lru_cache(maxsize=512)
def list_dir(rel):
    """Return (subdirs, images) for a relative subpath."""
    folder = safe_join(rel)
    try:
        with os.scandir(folder) as it:
            subs, imgs = [], []
            for e in it:
                if e.name.startswith('.'):
                    continue
                if e.is_dir():
                    subs.append(e.name)
                elif e.is_file():
                    ext = os.path.splitext(e.name)[1].lower()
                    if ext in IMAGE_EXTS:
                        imgs.append(e.name)
    except FileNotFoundError:
        subs, imgs = [], []
    subs.sort(key=human_sort_key)
    imgs.sort(key=human_sort_key)
    return subs, imgs

def reset_cache():
    list_dir.cache_clear()

def html_escape(s):
    return (s.replace("&", "&amp;")
             .replace("<", "&lt;")
             .replace(">", "&gt;")
             .replace('"', "&quot;"))

class Handler(http.server.SimpleHTTPRequestHandler):
    # Routes:
    #   /               → gallery (root or ?d=relpath)
    #   /view           → viewer (requires ?d=&i=)
    #   /raw            → serve file bytes (requires ?d=&n=)
    #   /refresh        → clear caches and redirect back
    #
    # All other paths → 404

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path == '/refresh':
            reset_cache()
            self.send_response(302)
            self.send_header('Location', '/' + ('?' + parsed.query if parsed.query else ''))
            self.end_headers()
            return

        if path == '/':
            return self._serve_gallery(parsed.query)
        if path == '/view':
            return self._serve_view(parsed.query)
        if path == '/raw':
            return self._serve_raw(parsed.query)

        self.send_error(404, "Not Found")

    # ------------------ Gallery ------------------

    def _serve_gallery(self, query):
        qs = urllib.parse.parse_qs(query or '')
        rel = norm_rel(qs.get('d', [''])[0])

        subdirs, images = list_dir(rel)

        # Build cards
        cards = []

        # Up (only if not at root)
        if rel:
            parent = rel.rsplit('/', 1)[0] if '/' in rel else ''
            up_q = urllib.parse.urlencode({'d': parent})
            cards.append(f'''
            <a class="card folder" href="/?{up_q}" title="Up">
              <div class="thumb"><div class="folder-emoji">🔙</div></div>
              <div class="cap">.. (up)</div>
            </a>
            ''')

        # Folders
        for name in subdirs:
            next_rel = f"{rel}/{name}" if rel else name
            q = urllib.parse.urlencode({'d': next_rel})
            title = html_escape(name)
            cards.append(f'''
            <a class="card folder" href="/?{q}" title="{title}">
              <div class="thumb"><div class="folder-emoji">📁</div></div>
              <div class="cap">{title}</div>
            </a>
            ''')

        # Images
        for idx, name in enumerate(images):
            vq = urllib.parse.urlencode({'d': rel, 'i': str(idx)})
            src_q = urllib.parse.urlencode({'d': rel, 'n': name})
            title = html_escape(name)
            cards.append(f'''
            <a class="card" href="/view?{vq}">
              <div class="thumb"><img loading="lazy" src="/raw?{src_q}" alt="{title}"></div>
              <div class="cap" title="{title}">{title}</div>
            </a>
            ''')

        disp_path = '/' + rel if rel else '/'
        disp_abs = safe_join(rel)

        html = f'''<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta id="viewportMeta" name="viewport" content="width=device-width, initial-scale=1, user-scalable=no">
<title>galser – {html_escape(disp_path)}</title>
<style>
  :root {{
    --bg:#111; --fg:#eee; --muted:#aaa; --card:#1b1b1b;
    --cell: 140px; /* default thumbnail cell size */
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
  header .title {{ font-weight:600; letter-spacing:0.3px; white-space:nowrap; overflow:auto; }}
  header .spacer {{ flex:1; }}
  a.btn {{
    color: var(--fg); text-decoration:none; background:#222; padding:6px 10px; border-radius:8px; border:1px solid #333;
  }}
  button.icon {{
    background:#222; color:var(--fg); border:1px solid #333; border-radius:8px; padding:6px 10px; cursor:pointer;
  }}

  .grid {{
    display:grid; gap:10px; padding:12px;
    grid-template-columns: repeat(auto-fill, minmax(var(--cell), 1fr));
  }}

  .card {{
    display:block; text-decoration:none; color:inherit; background: var(--card);
    border:1px solid #222; border-radius:12px; overflow:hidden;
    transition: transform .08s ease, border-color .08s ease;
  }}
  .card.folder .thumb {{ background:#0b0b0b; }}
  .card:active {{ transform: scale(0.99); border-color:#444; }}
  .thumb {{ width:100%; aspect-ratio:1/1; background:#000; display:grid; place-items:center; }}
  .thumb img {{ width:100%; height:100%; object-fit:cover; }}
  .folder-emoji {{ font-size:48px; opacity:0.85; }}
  .cap {{ font-size:12px; color:var(--muted); padding:8px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }}
  footer {{ padding:10px; text-align:center; color:#777; font-size:12px; }}

  /* Settings overlay */
  .overlay {{
    position: fixed; inset:0; background: rgba(0,0,0,0.55);
    display:none; align-items:center; justify-content:center; z-index: 100;
  }}
  .panel {{
    width:min(520px, 92vw); background:#151515; border:1px solid #333; border-radius:14px; padding:16px;
    box-shadow: 0 10px 30px rgba(0,0,0,0.5);
  }}
  .panel h3 {{ margin:0 0 12px 0; }}
  .row {{ display:flex; align-items:center; gap:10px; margin:10px 0; }}
  .row label {{ flex:1; }}
  input[type="number"], input[type="range"] {{
    accent-color:#888;
  }}
  .row input[type="number"] {{
    width:100px; background:#222; color:#eee; border:1px solid #333; border-radius:8px; padding:6px;
  }}
  .panel .actions {{ display:flex; gap:8px; justify-content:flex-end; margin-top:14px; }}
  .panel .actions button {{
    background:#222; color:#eee; border:1px solid #333; border-radius:8px; padding:8px 12px; cursor:pointer;
  }}
</style>
</head>
<body>
  <header>
    <div class="title">📷 galser — {html_escape(disp_path)}</div>
    <div class="spacer"></div>
    <a class="btn" href="/refresh?{urllib.parse.urlencode({'d': rel})}" title="Rescan">Rescan</a>
    <button class="icon" id="gearBtn" title="Settings">⚙️</button>
  </header>

  <div class="grid" id="grid">
    {''.join(cards) if (subdirs or images or rel) else '<div class="empty">No images or subfolders here.</div>'}
  </div>
  <footer>{html_escape(disp_abs)}</footer>

  <!-- Settings overlay -->
  <div class="overlay" id="overlay">
    <div class="panel">
      <h3>Settings</h3>
      <div class="row">
        <label for="thumbRange">Thumbnail size</label>
        <input type="range" id="thumbRange" min="60" max="480" step="1">
        <input type="number" id="thumbSize" min="60" max="480" step="10">
        <span>px</span>
      </div>
      <div class="actions">
        <button id="closeBtn">Close</button>
      </div>
    </div>
  </div>

<script>
  // --- Persisted settings ---
  const LS = window.localStorage;
  const DEF_SIZE = 140;
  const MIN_SIZE = 60, MAX_SIZE = 480;

  function getThumbSize() {{
    const v = parseInt(LS.getItem('thumbSize') || DEF_SIZE, 10);
    return isNaN(v) ? DEF_SIZE : Math.min(MAX_SIZE, Math.max(MIN_SIZE, v));
  }}
  function setThumbSize(px) {{
    const clamped = Math.min(MAX_SIZE, Math.max(MIN_SIZE, Math.round(px)));
    LS.setItem('thumbSize', String(clamped));
    document.documentElement.style.setProperty('--cell', clamped + 'px');
    // Keep controls in sync if open
    const r = document.getElementById('thumbRange');
    const n = document.getElementById('thumbSize');
    if (r) r.value = clamped;
    if (n) n.value = clamped;
  }}

  // Initialize grid size
  setThumbSize(getThumbSize());

  // Settings overlay logic
  const overlay = document.getElementById('overlay');
  const gearBtn = document.getElementById('gearBtn');
  const thumbRange = document.getElementById('thumbRange');
  const thumbSizeInp = document.getElementById('thumbSize');
  const closeBtn = document.getElementById('closeBtn');

  function openOverlay() {{
    const v = getThumbSize();
    thumbRange.value = v;
    thumbSizeInp.value = v;
    overlay.style.display = 'flex';
  }}
  function closeOverlay() {{ overlay.style.display = 'none'; }}

  gearBtn.addEventListener('click', openOverlay);
  overlay.addEventListener('click', (e)=>{{ if (e.target === overlay) closeOverlay(); }});
  closeBtn.addEventListener('click', closeOverlay);

  // Live update via slider/number (persists immediately)
  thumbRange.addEventListener('input', (e) => setThumbSize(parseInt(e.target.value || DEF_SIZE, 10)), {{ passive: true }});
  thumbSizeInp.addEventListener('input', (e) => setThumbSize(parseInt(e.target.value || DEF_SIZE, 10)), {{ passive: true }});
</script>
</body>
</html>'''
        self._send_html(html)

    # ------------------ Viewer (swipe restored, no pinch zoom) ------------------

    def _serve_view(self, query):
        qs = urllib.parse.parse_qs(query or '')
        rel = norm_rel(qs.get('d', [''])[0])
        try:
            idx = int(qs.get('i', ['0'])[0])
        except ValueError:
            idx = 0

        subdirs, images = list_dir(rel)
        if not images:
            self.send_response(302)
            self.send_header('Location', '/?' + urllib.parse.urlencode({'d': rel}))
            self.end_headers()
            return

        idx = max(0, min(idx, len(images) - 1))
        urls = ["/raw?" + urllib.parse.urlencode({'d': rel, 'n': name}) for name in images]

        html = f'''<!doctype html>
<html>
<head>
<meta charset="utf-8">
<!-- Lock zoom to keep swipe reliable -->
<meta name="viewport" content="width=device-width,initial-scale=1,user-scalable=no">
<title>Viewer</title>
<style>
  * {{ box-sizing:border-box; }}
  html, body {{
    margin:0; height:100%; background:#000; color:#fff; overscroll-behavior: none;
  }}
  .stage {{
    position:fixed; inset:0; background:#000; touch-action: pan-y;
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

    if (document.fullscreenEnabled && !document.fullscreenElement) {{
      document.documentElement.requestFullscreen().catch(()=>{{}});
    }}
  }}

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

  function commit(dir) {{
    const target = index + dir;
    if (target < 0 || target >= urls.length) return cancel();
    const W = window.innerWidth || 1;
    setTransition(cur);
    setTransition(under);
    cur.style.transform   = `translateX(${{dir>0 ? -W : W}}px)`;
    under.style.transform = 'translateX(0px)';
    const onDone = () => {{
      cur.removeEventListener('transitionend', onDone);
      show(target, true);
    }};
    cur.addEventListener('transitionend', onDone);
  }}

  function cancel() {{
    setTransition(cur);
    setTransition(under);
    cur.style.transform = 'translateX(0px)';
    const W = window.innerWidth || 1;
    const dx = _dx;
    if (dx > 0) under.style.transform = `translateX(${{-W}}px)`;
    else if (dx < 0) under.style.transform = `translateX(${{W}}px)`;
    else under.style.transform = 'translateX(0px)';
    const onDone = () => {{
      cur.removeEventListener('transitionend', onDone);
      under.style.visibility = 'hidden';
    }};
    cur.addEventListener('transitionend', onDone);
  }}

  // Drag swipe (single-finger)
  let startX=null, startY=null, dragging=false;
  let _dx=0, _dy=0;
  const COMMIT=80, MAX_OFF=120;

  function pd(e) {{
    // Only start a swipe if we're single-pointer
    if (e.isPrimary === false) return;
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
    if (Math.abs(_dy) > MAX_OFF) return; // ignore vertical drags
    const dir = _dx < 0 ? +1 : -1;
    const ok = prepareUnder(dir);
    const edge = (!ok);
    const effectiveDx = edge ? (_dx * 0.3) : _dx;
    cur.style.transform = `translateX(${{effectiveDx}}px)`;
    if (ok) {{
      const W = window.innerWidth || 1;
      under.style.transform = `translateX(${{dir>0 ? (W + effectiveDx) : (-W + effectiveDx)}}px)`;
    }}
  }}
  function pu() {{
    if (!dragging) return;
    dragging = false;
    if (Math.abs(_dy) > MAX_OFF) return cancel();
    if (Math.abs(_dx) >= COMMIT) commit(_dx < 0 ? +1 : -1);
    else cancel();
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

  window.addEventListener('keydown', (e) => {{
    if (e.key === 'ArrowRight') commit(+1);
    else if (e.key === 'ArrowLeft') commit(-1);
    else if (e.key === 'Escape') window.location.href = '/?{urllib.parse.urlencode({'d': rel})}';
  }});

  window.onpopstate = () => {{ location.href = '/?{urllib.parse.urlencode({'d': rel})}'; }};

  show(index, true);
</script>
</body>
</html>'''
        self._send_html(html)

    # ------------------ Raw file serving ------------------

    def _serve_raw(self, query):
        qs = urllib.parse.parse_qs(query or '')
        rel = norm_rel(qs.get('d', [''])[0])
        name = qs.get('n', [''])[0]
        if not name:
            return self._send_status(400, b'bad request')

        subdirs, images = list_dir(rel)
        if name not in images:
            return self._send_status(404, b'not found')

        path = safe_join(rel, name)
        try:
            with open(path, 'rb') as f:
                data = f.read()
        except FileNotFoundError:
            return self._send_status(404, b'not found')

        ctype = mimetypes.guess_type(path)[0] or 'application/octet-stream'
        self.send_response(200)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'private, max-age=3600')
        self.end_headers()
        self.wfile.write(data)

    # ------------------ Helpers ------------------

    def _send_status(self, code, body=b''):
        self.send_response(code)
        self.send_header('Content-Type', 'text/plain; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

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

    with socketserver.TCPServer(("", PORT), Handler) as httpd:
        print(f"Serving ⟶  http://127.0.0.1:{PORT}")
        print(f"Root   ⟶  {BASE_ROOT}")
        print(f"Tip: On your phone, open  http://<your-computer-LAN-IP>:{PORT}")
        print("Press Ctrl+C to stop.")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nShutting down...")

if __name__ == '__main__':
    reset_cache()
    main()
