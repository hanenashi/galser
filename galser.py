#!/usr/bin/env python3
# file: galser.py
#
# Local gallery server with:
# - Subfolder browsing (⋯ up)
# - Two gallery modes: thumbnails (images only) or file list (all files + sizes)
# - Sorting for both modes: by name or size, ascending/descending (server-side, URL + localStorage)
# - Settings (⚙️): view mode, sort options, live thumbnail-size slider (persisted), link to folder picker, show hidden files
# - Built-in folder picker (/roots) to change BASE at runtime
#   * Android: canonicalizes /sdcard → /storage/emulated/0 and labels it “Storage”
# - Fullscreen viewer:
#   * One-finger swipe = next/prev (animated)
#   * Two-finger pinch = zoom (center-correct), one-finger pan (clamped), images centered
# - Threaded server + LAN URL printout
# - EXIF orientation honored (CSS image-orientation)
#
# Run:  python galser.py  [--port 8000]
# Open: http://127.0.0.1:8000

# ===== GAL:BEGIN_IMPORTS =====
import http.server
from http.server import ThreadingHTTPServer
import os, sys, re, urllib.parse, mimetypes, socket
from functools import lru_cache
# ===== GAL:END_IMPORTS =====

# ===== GAL:BEGIN_CONFIG =====
IMAGE_EXTS = {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp', '.tiff', '.tif', '.avif'}
PORT = 8000
# ===== GAL:END_CONFIG =====

# ===== GAL:BEGIN_ANDROID_STORAGE_CANON =====
def _real(p): return os.path.realpath(os.path.abspath(os.path.expanduser(p)))

ANDROID_STORAGE = _real('/storage/emulated/0')
SYMLINK_SDCARD  = _real('/sdcard')
HOME_SHARED     = _real('~/storage/shared')

def is_storage_path(p):
    rp = _real(p)
    return rp in (ANDROID_STORAGE, SYMLINK_SDCARD, HOME_SHARED)

def canonical_storage(p):
    rp = _real(p)
    return ANDROID_STORAGE if is_storage_path(rp) else rp

def termux_candidates():
    seeds = [
        os.getcwd(),
        ANDROID_STORAGE,
        HOME_SHARED,
        _real('~/Pictures'),
        _real('~/DCIM'),
        _real('~/Download'),
    ]
    uniq, seen = [], set()
    for p in seeds:
        if os.path.isdir(p):
            rp = canonical_storage(p)
            if rp not in seen:
                uniq.append(rp); seen.add(rp)
    return uniq

def display_label(path):
    rp = canonical_storage(path)
    if rp == ANDROID_STORAGE:
        return "Storage"
    # Pretty drive labels on Windows (e.g., "C:")
    if os.name == 'nt' and re.match(r'^[A-Z]:\\$', rp):
        return rp[:2]
    base = os.path.basename(rp)
    return base if base else rp
# ===== GAL:END_ANDROID_STORAGE_CANON =====

# ===== GAL:BEGIN_DYNAMIC_ROOT =====
CURRENT_ROOT  = _real(os.getcwd())

def is_android_env():
    # Heuristic: typical Termux/Android paths exist
    return os.path.isdir('/storage/emulated/0') or os.path.isdir(_real('~/storage/shared'))

def windows_drive_roots():
    roots=[]
    # Probe A: to Z:
    for code in range(ord('A'), ord('Z')+1):
        d = f"{chr(code)}:\\"
        try:
            if os.path.isdir(d):
                roots.append(_real(d))
        except Exception:
            pass
    return roots

def posix_roots():
    roots = [_real('/')]
    # Common macOS external mounts:
    if os.path.isdir('/Volumes'):
        try:
            with os.scandir('/Volumes') as it:
                for e in it:
                    if e.is_dir():
                        roots.append(_real(os.path.join('/Volumes', e.name)))
        except Exception:
            pass
    return roots

def desktop_candidates():
    seeds = []
    if os.name == 'nt':
        seeds.extend(windows_drive_roots())
        # nice-to-haves:
        seeds.extend([
            _real(os.getcwd()),
            _real(os.path.expanduser('~')),
            _real(os.path.join(os.path.expanduser('~'), 'Pictures')),
            _real(os.path.join(os.path.expanduser('~'), 'Downloads')),
        ])
    else:
        # POSIX
        seeds.extend(posix_roots())
        seeds.extend([
            _real(os.getcwd()),
            _real(os.path.expanduser('~')),
            _real(os.path.join(os.path.expanduser('~'), 'Pictures')),
            _real(os.path.join(os.path.expanduser('~'), 'Downloads')),
            _real('/mnt'),
            _real('/media'),
        ])
    # de-dup keep order
    uniq, seen = [], set()
    for p in seeds:
        if os.path.isdir(p):
            if p not in seen:
                uniq.append(p); seen.add(p)
    return uniq

ALLOWED_BASES = termux_candidates() if is_android_env() else desktop_candidates()

def is_subpath(child, base):
    try:
        return os.path.commonpath([_real(child), _real(base)]) == _real(base)
    except Exception:
        return False

def is_allowed_abs(abs_path: str) -> bool:
    ap = _real(abs_path)
    for base in ALLOWED_BASES:
        if is_subpath(ap, base):
            return True
    return False

def set_current_root(abs_path: str) -> bool:
    global CURRENT_ROOT
    ap = _real(abs_path)
    if is_allowed_abs(ap):
        CURRENT_ROOT = ap
        reset_cache()
        return True
    return False
# ===== GAL:END_DYNAMIC_ROOT =====

# ===== GAL:BEGIN_SORT_AND_PATH_UTILS =====
_num_re = re.compile(r'(\d+)')

def human_sort_key(name: str):
    """Natural sort key (stable: tag text vs number)."""
    s = os.fspath(name)
    parts = _num_re.split(s)
    key = []
    for tok in parts:
        if tok.isdigit():
            key.append((1, int(tok)))
        else:
            key.append((0, tok.casefold()))
    return tuple(key)

def norm_rel(rel):
    rel = rel.strip().replace('\\','/').lstrip('/')
    norm = os.path.normpath(rel)
    if norm in ('.','') or norm.startswith('..'):
        return ''
    return norm.replace('\\','/')

def safe_join(rel, *parts):
    rel = norm_rel(rel)
    root = _real(CURRENT_ROOT)
    path = _real(os.path.join(root, rel, *parts))
    if not is_subpath(path, root):
        raise PermissionError("Path traversal blocked")
    return path

def fmt_size(n: int) -> str:
    # ===== GAL:BEGIN_FMT_SIZE =====
    try:
        n = int(n)
    except Exception:
        return '?'
    units = ['B','KB','MB','GB','TB']
    size = float(n)
    for u in units:
        if size < 1024 or u == units[-1]:
            if u == 'B': return f"{int(size)} B"
            return f"{size:.1f} {u}"
        size /= 1024.0
    return f"{n} B"
    # ===== GAL:END_FMT_SIZE =====
# ===== GAL:END_SORT_AND_PATH_UTILS =====

# ===== GAL:BEGIN_HIDDEN_HELPER =====
def _is_hidden_entry(entry):
    name = entry.name
    # Dotfiles everywhere
    if name.startswith('.'):
        return True
    # Windows hidden attribute (Python 3.8+: st_file_attributes)
    if os.name == 'nt':
        try:
            st = entry.stat(follow_symlinks=False)
            attr = getattr(st, 'st_file_attributes', 0)
            # FILE_ATTRIBUTE_HIDDEN = 0x2
            return bool(attr & 0x2)
        except Exception:
            return False
    return False
# ===== GAL:END_HIDDEN_HELPER =====

# ===== GAL:BEGIN_DIR_CACHE =====
@lru_cache(maxsize=512)
def scan_dir(rel, show_hidden=False):
    """Return (subdirs, files_info) where files_info = list of (name, size, is_image)."""
    folder = safe_join(rel)
    subs, files = [], []
    try:
        with os.scandir(folder) as it:
            for e in it:
                name = e.name
                try:
                    if not show_hidden and _is_hidden_entry(e):
                        continue
                    if e.is_dir():
                        subs.append(name)
                    elif e.is_file():
                        ext = os.path.splitext(name)[1].lower()
                        try:
                            size = e.stat(follow_symlinks=False).st_size
                        except Exception:
                            size = 0
                        files.append((name, size, ext in IMAGE_EXTS))
                except Exception:
                    continue
    except FileNotFoundError:
        pass
    subs.sort(key=human_sort_key)
    return subs, files

@lru_cache(maxsize=512)
def list_dir(rel, show_hidden=False):
    subs, files = scan_dir(rel, show_hidden)
    imgs = [name for (name, _sz, is_img) in files if is_img]
    imgs.sort(key=human_sort_key)
    return subs, imgs

def reset_cache():
    scan_dir.cache_clear()
    list_dir.cache_clear()
# ===== GAL:END_DIR_CACHE =====

# ===== GAL:BEGIN_MISC_UTILS =====
def html_escape(s):
    return s.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;").replace('"',"&quot;")

def get_lan_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return '127.0.0.1'
# ===== GAL:END_MISC_UTILS =====

# ===== GAL:BEGIN_HTTP_HANDLER =====
class Handler(http.server.SimpleHTTPRequestHandler):
    # Routes:
    #   /               → gallery (grid or list; ?d=&view=&sort=&dir=&hidden=)
    #   /view           → viewer (requires ?d=&i= and carries view/sort/dir/hidden)
    #   /raw            → file bytes (images only; respects hidden)
    #   /refresh        → clear caches and redirect back
    #   /roots          → simple file commander to pick new base folder
    #   /setroot        → set CURRENT_ROOT (GET ?path=ABS_PATH) if allowed
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
        if path == '/roots':
            return self._serve_roots(parsed.query)
        if path == '/setroot':
            return self._serve_setroot(parsed.query)
        self.send_error(404, "Not Found")
# ===== GAL:END_HTTP_HANDLER =====

# ===== GAL:BEGIN_GALLERY_HANDLER =====
    def _serve_gallery(self, query):
        qs = urllib.parse.parse_qs(query or '')
        rel   = norm_rel(qs.get('d',[''])[0])
        view  = (qs.get('view',['thumbs'])[0] or 'thumbs')   # 'thumbs' | 'list'
        sort  = (qs.get('sort',['name'])[0] or 'name')       # 'name'   | 'size'
        sdir  = (qs.get('dir', ['asc'])[0]  or 'asc')        # 'asc'    | 'desc'
        hidden = (qs.get('hidden', ['0'])[0] == '1')         # False | True
        desc  = (sdir == 'desc')

        subdirs, files = scan_dir(rel, hidden)

        # ----- sorting for files -----
        def sort_key_name(item):  # (name, size, is_image)
            return human_sort_key(item[0])
        def sort_key_size(item):
            return (item[1], human_sort_key(item[0]))
        key = sort_key_size if sort == 'size' else sort_key_name
        files_sorted = sorted(files, key=key, reverse=desc)
        images_sorted = [name for (name, _sz, is_img) in files_sorted if is_img]

        cards = []
        list_rows = []

        # -- GRID mode --
        if view == 'thumbs':
            # Up card (only if not at base)
            if rel:
                parent = rel.rsplit('/',1)[0] if '/' in rel else ''
                cards.append(
                    '<a class="card folder" href="/?' +
                    urllib.parse.urlencode({'d': parent, 'view': view, 'sort': sort, 'dir': sdir, 'hidden': '1' if hidden else '0'}) +
                    '" title="Up"><div class="thumb"><div class="folder-emoji">⋯</div></div><div class="cap">.. (up)</div></a>'
                )
            # Folders
            for name in subdirs:
                next_rel = f"{rel}/{name}" if rel else name
                title = html_escape(name)
                cards.append(
                    '<a class="card folder" href="/?' +
                    urllib.parse.urlencode({'d': next_rel, 'view': view, 'sort': sort, 'dir': sdir, 'hidden': '1' if hidden else '0'}) +
                    f'" title="{title}"><div class="thumb"><div class="folder-emoji">📁</div></div><div class="cap">{title}</div></a>'
                )
            # Images
            for idx, name in enumerate(images_sorted):
                vq    = urllib.parse.urlencode({'d': rel, 'i': str(idx), 'view': view, 'sort': sort, 'dir': sdir, 'hidden': '1' if hidden else '0'})
                src_q = urllib.parse.urlencode({'d': rel, 'n': name, 'hidden': '1' if hidden else '0'})
                title = html_escape(name)
                loading = "eager" if idx < 8 else "lazy"
                cards.append(
                    '<a class="card" href="/view?' + vq + '">'
                    '<div class="thumb"><img loading="' + loading + '" decoding="async" src="/raw?' + src_q + '" alt="' + title + '"></div>'
                    '<div class="cap" title="' + title + '">' + title + '</div>'
                    '</a>'
                )
        # -- LIST mode --
        else:
            # Up row
            if rel:
                parent = rel.rsplit('/',1)[0] if '/' in rel else ''
                up_q = urllib.parse.urlencode({'d': parent, 'view': view, 'sort': sort, 'dir': sdir, 'hidden': '1' if hidden else '0'})
                list_rows.append(
                    '<div class="row folder"><a class="fname" href="/?' + up_q + '" title="Up">⋯ (up)</a><span class="fsize"></span></div>'
                )
            # Folders first
            for name in subdirs:
                next_rel = f"{rel}/{name}" if rel else name
                title = html_escape(name)
                q = urllib.parse.urlencode({'d': next_rel, 'view': view, 'sort': sort, 'dir': sdir, 'hidden': '1' if hidden else '0'})
                list_rows.append(
                    '<div class="row folder"><a class="fname" href="/?' + q + '" title="' + title + '">📁 ' + title + '</a><span class="fsize"></span></div>'
                )
            # Files (images clickable → viewer)
            img_index = {name: i for i, name in enumerate(images_sorted)}
            for (name, size, is_img) in files_sorted:
                title = html_escape(name)
                sz = html_escape(fmt_size(size))
                if is_img:
                    vq = urllib.parse.urlencode({'d': rel, 'i': str(img_index[name]), 'view': view, 'sort': sort, 'dir': sdir, 'hidden': '1' if hidden else '0'})
                    list_rows.append(
                        '<div class="row file"><a class="fname" href="/view?' + vq + '" title="' + title + '">' + title + '</a><span class="fsize">' + sz + '</span></div>'
                    )
                else:
                    list_rows.append(
                        '<div class="row file"><span class="fname" title="' + title + '">' + title + '</span><span class="fsize">' + sz + '</span></div>'
                    )

        cards_html = ''.join(cards)
        list_html = ''.join(list_rows)

        # ===== GAL:BEGIN_GALLERY_PAGE =====
        tmpl = r'''<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta id="viewportMeta" name="viewport" content="width=device-width, initial-scale=1, user-scalable=no">
<title>galser – __TITLE_PATH__</title>
<style>
  :root { --bg:#111; --fg:#eee; --muted:#aaa; --card:#1b1b1b; --cell: 140px; }
  * { box-sizing: border-box; }
  body { margin:0; font-family: system-ui, -apple-system, Segoe UI, Roboto, "Noto Sans", Arial, sans-serif; background:var(--bg); color:var(--fg); }
  header { position:sticky; top:0; z-index:10; background:linear-gradient(180deg, rgba(0,0,0,.9), rgba(0,0,0,.6)); backdrop-filter:blur(6px); padding:10px 14px; display:flex; gap:10px; align-items:center; border-bottom:1px solid #222; }
  header .title { font-weight:600; letter-spacing:.3px; overflow-wrap:anywhere; white-space:normal; line-height:1.2; }
  header .spacer { flex:1; }
  button.icon { color:var(--fg); text-decoration:none; background:#222; padding:6px 10px; border-radius:8px; border:1px solid #333; cursor:pointer; }

  .grid { display:grid; gap:10px; padding:12px; grid-template-columns: repeat(auto-fill, minmax(var(--cell), 1fr)); }
  .card { display:block; text-decoration:none; color:inherit; background:var(--card); border:1px solid #222; border-radius:12px; overflow:hidden; transition:transform .08s ease, border-color .08s ease; }
  .card.folder .thumb { background:#0b0b0b; }
  .card:active { transform:scale(.99); border-color:#444; }
  .thumb { width:100%; aspect-ratio:1/1; background:#000; display:grid; place-items:center; }
  .thumb img { width:100%; height:100%; object-fit:cover; image-orientation: from-image; }
  .folder-emoji { font-size:48px; opacity:.85; }
  .cap { font-size:12px; color:var(--muted); padding:8px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }

  /* File list mode */
  .listwrap { padding:12px; }
  .row.file, .row.folder { display:flex; align-items:center; gap:12px; padding:10px 12px; border-bottom:1px solid #222; }
  .row .fname { flex:1; color:var(--fg); text-decoration:none; overflow-wrap:anywhere; }
  .row .fsize { color:#bbb; font-variant-numeric: tabular-nums; }
  .row .fname:hover { text-decoration:underline; }
  .row.folder .fname { font-weight:600; }
  .row.folder .fsize { visibility:hidden; }

  footer { padding:10px; text-align:center; color:#777; font-size:12px; }

  .overlay { position:fixed; inset:0; background:rgba(0,0,0,.55); display:none; align-items:center; justify-content:center; z-index:100; }
  .panel { width:min(560px,92vw); background:#151515; border:1px solid #333; border-radius:14px; padding:16px; box-shadow:0 10px 30px rgba(0,0,0,.5); }
  .panel h3 { margin:0 0 12px 0; }
  .row.set { display:flex; align-items:center; gap:10px; margin:10px 0; }
  .row.set label { flex:1; }
  input[type="number"], input[type="range"], select { accent-color:#888; }
  .row.set input[type="number"] { width:100px; background:#222; color:#eee; border:1px solid #333; border-radius:8px; padding:6px; }
  .panel .actions { display:flex; gap:8px; justify-content:flex-end; margin-top:14px; }
  .panel .actions button, a.btn { background:#222; color:#eee; border:1px solid #333; border-radius:8px; padding:8px 12px; cursor:pointer; text-decoration:none; }

  @media (max-width: 600px) {
    header { padding:10px 10px; }
    header .title { font-size:15px; }
    .row.file, .row.folder { padding:14px 12px; }
    .row .fname { font-size:16px; }
    .row .fsize { font-size:14px; }
  }
</style>
</head>
<body>
  <header>
    <div class="title">📷 galser — __TITLE_PATH__</div>
    <div class="spacer"></div>
    <button class="icon" id="gearBtn" title="Settings">⚙️</button>
  </header>

  __BODY__

  <footer>Base: __BASE_ABS__</footer>

  <!-- GAL:BEGIN_SETTINGS -->
  <div class="overlay" id="overlay">
    <div class="panel">
      <h3>Settings</h3>
      <div class="row set">
        <label for="modeSel">View mode</label>
        <select id="modeSel">
          <option value="thumbs">Thumbnails (images)</option>
          <option value="list">File names (all files)</option>
        </select>
      </div>
      <div class="row set">
        <label for="sortSel">Sort by</label>
        <select id="sortSel">
          <option value="name">Name</option>
          <option value="size">Size</option>
        </select>
        <select id="dirSel">
          <option value="asc">Ascending</option>
          <option value="desc">Descending</option>
        </select>
      </div>
      <div class="row set">
        <label for="hiddenChk">Show hidden files</label>
        <input type="checkbox" id="hiddenChk">
      </div>
      <div class="row set">
        <label for="thumbRange">Thumbnail size</label>
        <input type="range" id="thumbRange" min="60" max="480" step="1">
        <input type="number" id="thumbSize" min="60" max="480" step="10">
        <span>px</span>
      </div>
      <div class="row set">
        <a class="btn" href="/roots">Change base folder…</a>
      </div>
      <div class="actions">
        <button id="applyBtn">Apply</button>
        <button id="closeBtn">Close</button>
      </div>
    </div>
  </div>
  <!-- GAL:END_SETTINGS -->

  <!-- GAL:BEGIN_GALLERY_SCRIPT -->
  <script>
    const CURRENT_VIEW="__VIEW__", CURRENT_SORT="__SORT__", CURRENT_DIR="__DIR__", CURRENT_HIDDEN="__HIDDEN__";
    const CURR_REL="__REL__";

    const LS = window.localStorage, DEF_SIZE = 140, MIN_SIZE = 60, MAX_SIZE = 480;
    function getThumbSize(){ const v=parseInt(LS.getItem('thumbSize')||DEF_SIZE,10); return isNaN(v)?DEF_SIZE:Math.min(MAX_SIZE,Math.max(MIN_SIZE,v)); }
    function setThumbSize(px){ const c=Math.min(MAX_SIZE,Math.max(MIN_SIZE,Math.round(px))); LS.setItem('thumbSize',String(c)); document.documentElement.style.setProperty('--cell', c+'px'); const r=document.getElementById('thumbRange'), n=document.getElementById('thumbSize'); if(r) r.value=c; if(n) n.value=c; }
    setThumbSize(getThumbSize());

    const overlay=document.getElementById('overlay'), gearBtn=document.getElementById('gearBtn'),
          thumbRange=document.getElementById('thumbRange'), thumbSizeInp=document.getElementById('thumbSize'),
          modeSel=document.getElementById('modeSel'), sortSel=document.getElementById('sortSel'), dirSel=document.getElementById('dirSel'),
          hiddenChk=document.getElementById('hiddenChk'),
          applyBtn=document.getElementById('applyBtn'), closeBtn=document.getElementById('closeBtn');

    function openOverlay(){
      const v=getThumbSize(); thumbRange.value=v; thumbSizeInp.value=v;
      modeSel.value = CURRENT_VIEW; sortSel.value = CURRENT_SORT; dirSel.value = CURRENT_DIR;
      hiddenChk.checked = (localStorage.getItem('galser.hidden') ?? CURRENT_HIDDEN) === '1';
      overlay.style.display='flex';
    }
    function closeOverlay(){ overlay.style.display='none'; }

    gearBtn.addEventListener('click',openOverlay);
    overlay.addEventListener('click',(e)=>{ if(e.target===overlay) closeOverlay(); });
    closeBtn.addEventListener('click',closeOverlay);

    thumbRange.addEventListener('input',(e)=>setThumbSize(parseInt(e.target.value||DEF_SIZE,10)),{passive:true});
    thumbSizeInp.addEventListener('input',(e)=>setThumbSize(parseInt(e.target.value||DEF_SIZE,10)),{passive:true});

    applyBtn.addEventListener('click', ()=>{
      LS.setItem('galser.view', modeSel.value);
      LS.setItem('galser.sort', sortSel.value);
      LS.setItem('galser.dir',  dirSel.value);
      LS.setItem('galser.hidden', hiddenChk.checked ? '1' : '0');
      const q = new URLSearchParams(location.search);
      q.set('d', CURR_REL);
      q.set('view', modeSel.value);
      q.set('sort', sortSel.value);
      q.set('dir',  dirSel.value);
      q.set('hidden', hiddenChk.checked ? '1' : '0');
      location.href = '/?'+q.toString();
    });

    (function bootstrapURL(){
      const q = new URLSearchParams(location.search);
      if (!q.has('view') || !q.has('sort') || !q.has('dir') || !q.has('hidden')){
        const v = LS.getItem('galser.view') || CURRENT_VIEW;
        const s = LS.getItem('galser.sort') || CURRENT_SORT;
        const d = LS.getItem('galser.dir')  || CURRENT_DIR;
        const h = LS.getItem('galser.hidden') || CURRENT_HIDDEN || '0';
        q.set('view', v); q.set('sort', s); q.set('dir', d); q.set('hidden', h);
        history.replaceState({},'', '/?'+q.toString());
      }
    })();
  </script>
  <!-- GAL:END_GALLERY_SCRIPT -->
</body>
</html>'''
        # ===== GAL:END_GALLERY_PAGE =====

        if view == 'thumbs':
            empty_grid = '<div class="empty">No files here.</div>'
            body_html = '<div class="grid" id="grid">' + (cards_html if (cards_html or rel) else empty_grid) + '</div>'
        else:
            empty_list = '<div class="empty">No files.</div>'
            list_block = '<div class="listwrap">' + (list_html if list_html else empty_list) + '</div>'
            body_html = list_block  # folders already included inline above files

        html = (tmpl
                .replace('__TITLE_PATH__', html_escape('/' + (rel if rel else '')))
                .replace('__BODY__', body_html)
                .replace('__BASE_ABS__', html_escape(safe_join(rel)))
                .replace('__VIEW__', html_escape(view))
                .replace('__SORT__', html_escape(sort))
                .replace('__DIR__',  html_escape(sdir))
                .replace('__REL__',  html_escape(rel))
                .replace('__HIDDEN__', '1' if hidden else '0'))
        self._send_html(html)
# ===== GAL:END_GALLERY_HANDLER =====

# ===== GAL:BEGIN_VIEWER_HANDLER =====
    def _serve_view(self, query):
        qs = urllib.parse.parse_qs(query or '')
        rel   = norm_rel(qs.get('d',[''])[0])
        try:
            idx = int(qs.get('i',['0'])[0])
        except ValueError:
            idx = 0
        sort  = (qs.get('sort',['name'])[0] or 'name')
        sdir  = (qs.get('dir', ['asc'])[0]  or 'asc')
        view_mode = (qs.get('view',['thumbs'])[0] or 'thumbs')
        hidden = (qs.get('hidden', ['0'])[0] == '1')
        desc  = (sdir == 'desc')

        _subdirs, files = scan_dir(rel, hidden)
        def sort_key_name(item): return human_sort_key(item[0])
        def sort_key_size(item): return (item[1], human_sort_key(item[0]))
        key = sort_key_size if sort == 'size' else sort_key_name
        files_sorted = sorted(files, key=key, reverse=desc)
        images = [name for (name, _sz, is_img) in files_sorted if is_img]

        if not images:
            self.send_response(302)
            self.send_header('Location','/?'+urllib.parse.urlencode({'d':rel, 'view':view_mode, 'sort':sort, 'dir':sdir, 'hidden': '1' if hidden else '0'}))
            self.end_headers()
            return

        idx = max(0, min(idx, len(images)-1))
        urls = ["/raw?"+urllib.parse.urlencode({'d':rel,'n':name,'hidden':'1' if hidden else '0'}) for name in images]
        back_q = urllib.parse.urlencode({'d': rel, 'view': view_mode, 'sort': sort, 'dir': sdir, 'hidden': '1' if hidden else '0'})

        # ===== GAL:BEGIN_VIEWER_PAGE =====
        tmpl = r'''<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,user-scalable=no">
<title>Viewer</title>
<style>
  /* GAL:BEGIN_VIEWER_STYLE */
  * { box-sizing:border-box; }
  html,body { margin:0; height:100%; background:#000; color:#fff; overscroll-behavior:none; }
  .stage { position:fixed; inset:0; background:#000; touch-action:none; overflow:hidden; }
  .layer { position:absolute; inset:0; display:grid; place-items:center; }
  .wrap { width:100vw; height:100vh; will-change:transform; transform:translateX(0px); display:grid; place-items:center; }
  img.viewer { max-width:100vw; max-height:100vh; object-fit:contain; will-change:transform; transform:translate(0px,0px) scale(1); transform-origin:0 0; image-orientation:from-image; touch-action:none; }
  /* GAL:END_VIEWER_STYLE */
</style>
</head>
<body>
  <div class="stage" id="stage">
    <div class="layer"><div class="wrap" id="underWrap"><img class="viewer" id="under"  alt=""></div></div>
    <div class="layer"><div class="wrap" id="curWrap"><img class="viewer" id="current" alt=""></div></div>
  </div>

  <!-- GAL:BEGIN_VIEWER_SCRIPT -->
  <script>
    const urls = __URLS__, cur=document.getElementById('current'), under=document.getElementById('under'), curWrap=document.getElementById('curWrap'), underWrap=document.getElementById('underWrap'), stage=document.getElementById('stage');
    let index = __INDEX__;

    const preloadCache=new Map();
    function preload(src){ if(preloadCache.has(src)) return; const im=new Image(); im.decoding='async'; im.loading='eager'; im.src=src; preloadCache.set(src,im); }
    function preloadAround(i){ const p=i-1,n=i+1; if(p>=0) preload(urls[p]); if(n<urls.length) preload(urls[n]); }

    function setNoTransition(el){ el.style.transition='none'; }
    function setTransition(el){ el.style.transition='transform 200ms ease-out'; }
    function clamp(i){ return Math.max(0, Math.min(urls.length-1, i)); }

    let zScale=1, zTx=0, zTy=0; const Z_MIN=1, Z_MAX=6;

    function baseBox(){
      const vw=window.innerWidth||1, vh=window.innerHeight||1;
      const iw=cur.naturalWidth||vw, ih=cur.naturalHeight||vh;
      const baseScale=Math.min(vw/iw, vh/ih);
      const w0=iw*baseScale, h0=ih*baseScale;
      const x0=(vw-w0)/2, y0=(vh-h0)/2;
      return {vw,vh,iw,ih,baseScale,w0,h0,x0,y0};
    }

    function clampPan(){
      const bb=baseBox(), w=bb.w0*zScale, h=bb.h0*zScale;
      if (w>=bb.vw){ const minL=bb.vw-w, maxL=0; const left=Math.max(minL, Math.min(maxL, bb.x0+zTx)); zTx=left-bb.x0; }
      else { zTx=( (bb.vw-w)/2 ) - bb.x0; }
      if (h>=bb.vh){ const minT=bb.vh-h, maxT=0; const top=Math.max(minT, Math.min(maxT, bb.y0+zTy)); zTy=top-bb.y0; }
      else { zTy=( (bb.vh-h)/2 ) - bb.y0; }
    }

    function applyZoom(){ cur.style.transform = `translate(${zTx}px, ${zTy}px) scale(${zScale})`; }
    function resetZoom(){ zScale=1; zTx=0; zTy=0; applyZoom(); }

    function show(i, replaceHistory=true){
      index=clamp(i);
      setNoTransition(curWrap); setNoTransition(underWrap);
      curWrap.style.transform='translateX(0px)'; underWrap.style.transform='translateX(0px)';
      resetZoom();
      cur.src=urls[index]; under.src=''; underWrap.style.visibility='hidden';

      const url=new URL(window.location.href); url.searchParams.set('i', index); if(replaceHistory) history.replaceState({},'',url);
      if (document.fullscreenEnabled && !document.fullscreenElement){ document.documentElement.requestFullscreen().catch(()=>{}); }
      preloadAround(index);
    }

    function prepareUnder(dir){
      const t=index+dir; if(t<0||t>=urls.length){ underWrap.style.visibility='hidden'; return false; }
      under.src=urls[t]; underWrap.style.visibility='visible';
      const W=window.innerWidth||1; setNoTransition(underWrap);
      underWrap.style.transform=`translateX(${dir>0?W:-W}px)`; return true;
    }

    function commit(dir){
      const t=index+dir; if(t<0||t>=urls.length) return cancel();
      const W=window.innerWidth||1; setTransition(curWrap); setTransition(underWrap);
      curWrap.style.transform=`translateX(${dir>0?-W:W}px)`; underWrap.style.transform='translateX(0px)';
      const onDone=()=>{ curWrap.removeEventListener('transitionend',onDone); show(t,true); };
      curWrap.addEventListener('transitionend', onDone);
    }

    function cancel(){
      setTransition(curWrap); setTransition(underWrap);
      curWrap.style.transform='translateX(0px)';
      const W=window.innerWidth||1, dx=_dx;
      if (dx>0) underWrap.style.transform=`translateX(${-W}px)`;
      else if (dx<0) underWrap.style.transform=`translateX(${W}px)`;
      else underWrap.style.transform='translateX(0px)';
      const onDone=()=>{ curWrap.removeEventListener('transitionend',onDone); underWrap.style.visibility='hidden'; };
      curWrap.addEventListener('transitionend', onDone);
    }

    const ptrs=new Map(); let mode='idle', startX=0, startY=0, _dx=0, _dy=0;
    let pStartDist=1, pStartScale=1, pStartTx=0, pStartTy=0;

    function dist(a,b){ const dx=a.x-b.x, dy=a.y-b.y; return Math.hypot(dx,dy); }
    function centroid(a,b){ return {x:(a.x+b.x)/2, y:(a.y+b.y)/2}; }

    function onDown(e){
      ptrs.set(e.pointerId, { x: e.clientX, y: e.clientY });
      try{ e.target.setPointerCapture(e.pointerId);}catch(_){}
      if (ptrs.size===1){
        const only=ptrs.values().next().value; startX=only.x; startY=only.y; _dx=0; _dy=0;
        if (zScale>1.01){ mode='pan'; } else { mode='swipe'; setNoTransition(curWrap); setNoTransition(underWrap); }
      } else if (ptrs.size===2){
        let residual=0;
        const m = curWrap.style.transform && curWrap.style.transform.match(/translateX\(([-\d.]+)px\)/);
        if (m) residual = parseFloat(m[1]) || 0;
        setNoTransition(curWrap); setNoTransition(underWrap);
        curWrap.style.transform='translateX(0px)'; underWrap.style.transform='translateX(0px)'; underWrap.style.visibility='hidden'; _dx=0; _dy=0;
        if (Math.abs(residual)>0.001){ zTx+=residual; clampPan(); applyZoom(); }

        const it=Array.from(ptrs.values());
        pStartDist=dist(it[0], it[1])||1; pStartScale=zScale; pStartTx=zTx; pStartTy=zTy; mode='pinch';
      }
    }

    function onMove(e){
      if (!ptrs.has(e.pointerId)) return;
      ptrs.set(e.pointerId, { x: e.clientX, y: e.clientY });

      if (mode==='pinch' && ptrs.size>=2){
        const [pA,pB]=Array.from(ptrs.values());
        const d=dist(pA,pB)||1; const c=centroid(pA,pB);
        const bb=baseBox();
        const newScale=Math.min(Z_MAX, Math.max(Z_MIN, pStartScale*(d/pStartDist))); const ds=newScale/pStartScale;
        zTx = (1-ds)*(c.x - bb.x0) + ds*pStartTx;
        zTy = (1-ds)*(c.y - bb.y0) + ds*pStartTy;
        zScale=newScale; clampPan(); applyZoom(); return;
      }

      if (mode==='pan' && ptrs.size===1){
        const p=Array.from(ptrs.values())[0]; const dx=p.x-startX, dy=p.y-startY; startX=p.x; startY=p.y;
        zTx+=dx; zTy+=dy; clampPan(); applyZoom(); return;
      }

      if (mode==='swipe' && ptrs.size===1){
        const p=Array.from(ptrs.values())[0]; _dx=p.x-startX; _dy=p.y-startY;
        if (Math.abs(_dy)>120) return;
        const dir=_dx<0?+1:-1; const ok=prepareUnder(dir); const edge=(!ok); const eff=edge?(_dx*0.3):_dx;
        curWrap.style.transform=`translateX(${eff}px)`;
        if (ok){ const W=window.innerWidth||1; underWrap.style.transform=`translateX(${dir>0?(W+eff):(-W+eff)}px)`; }
      }
    }

    function onUp(e){
      if (!ptrs.has(e.pointerId)) return;
      ptrs.delete(e.pointerId);

      if (mode==='pinch'){ if (ptrs.size===1 && zScale>1.01){ mode='pan'; const p=Array.from(ptrs.values())[0]; startX=p.x; startY=p.y; } else if (ptrs.size===0){ mode='idle'; } return; }
      if (mode==='pan'){ if (ptrs.size===0) mode='idle'; return; }
      if (mode==='swipe'){ if (Math.abs(_dy)>120){ cancel(); mode='idle'; return; } if (Math.abs(_dx)>=80) commit(_dx<0?+1:-1); else cancel(); mode='idle'; return; }
    }

    function onCancel(e){ if (!ptrs.has(e.pointerId)) return; ptrs.delete(e.pointerId); if (mode==='swipe') cancel(); mode = ptrs.size ? 'pan' : 'idle'; }

    [stage, cur, under, curWrap, underWrap].forEach(el=>{
      el.addEventListener('pointerdown', onDown, {passive:true});
      el.addEventListener('pointermove', onMove, {passive:true});
      el.addEventListener('pointerup', onUp, {passive:true});
      el.addEventListener('pointercancel', onCancel, {passive:true});
      el.addEventListener('pointerleave', onCancel, {passive:true});
    });

    window.addEventListener('keydown', (e)=>{ if(e.key==='ArrowRight' && zScale<=1.01) commit(+1); else if(e.key==='ArrowLeft' && zScale<=1.01) commit(-1); else if(e.key==='0'){ resetZoom(); } else if(e.key==='Escape') window.location.href='/?__BACKQ__'; });
    window.onpopstate = ()=>{ location.href='/?__BACKQ__'; };

    show(index, true);
  </script>
  <!-- GAL:END_VIEWER_SCRIPT -->
</body>
</html>'''
        # ===== GAL:END_VIEWER_PAGE =====
        html = (tmpl.replace('__URLS__', repr(urls))
                    .replace('__INDEX__', str(idx))
                    .replace('__BACKQ__', back_q))
        self._send_html(html)
# ===== GAL:END_VIEWER_HANDLER =====

# ===== GAL:BEGIN_RAW_HANDLER =====
    def _serve_raw(self, query):
        qs = urllib.parse.parse_qs(query or '')
        rel = norm_rel(qs.get('d',[''])[0])
        name = qs.get('n',[''])[0]
        hidden = (qs.get('hidden', ['0'])[0] == '1')
        if not name:
            return self._send_status(400, b'bad request')

        _, images = list_dir(rel, hidden)
        if name not in images:
            return self._send_status(404, b'not found')

        path = safe_join(rel, name)
        try:
            with open(path,'rb') as f:
                data=f.read()
        except FileNotFoundError:
            return self._send_status(404, b'not found')

        ctype = mimetypes.guess_type(path)[0] or 'application/octet-stream'
        self.send_response(200)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control','private, max-age=3600')
        self.end_headers()
        self.wfile.write(data)
# ===== GAL:END_RAW_HANDLER =====

# ===== GAL:BEGIN_ROOTS_HANDLER =====
    def _serve_roots(self, query):
        qs = urllib.parse.parse_qs(query or '')
        base = qs.get('p', [None])[0]

        def page_list_allowed():
            items = []
            for p in ALLOWED_BASES:
                canon = canonical_storage(p)
                label = display_label(canon)
                esc = html_escape(canon)
                items.append(
                    '<div class="row">'
                    '<div class="path"><b>' + html_escape(label) + '</b> — ' + esc + '</div>'
                    '<div class="actions">'
                    '<a class="btn" href="/roots?' + urllib.parse.urlencode({'p': canon}) + '">Browse</a>'
                    '<a class="btn" href="/setroot?' + urllib.parse.urlencode({'path': canon}) + '">Use this folder</a>'
                    '</div></div>'
                )
            body = '\n'.join(items) if items else '<p>No allowed roots found.</p>'
            return roots_template().replace('__TITLE__', 'Pick a base folder').replace('__BODY__', body)

        def page_browse(abs_base):
            if not is_allowed_abs(abs_base):
                return self._simple_msg(403, "Forbidden: outside allowed areas")
            try:
                entries = []
                with os.scandir(abs_base) as it:
                    for e in it:
                        if e.name.startswith('.'):
                            # allow dotfolders if user wants them; we list all here, visibility is decided in gallery
                            pass
                        if e.is_dir():
                            entries.append(e.name)
                entries.sort(key=human_sort_key)
            except Exception as e:
                return self._simple_msg(404, f"Not accessible: {html_escape(str(e))}")

            parent = _real(os.path.dirname(abs_base))
            up_link = ''
            if parent != abs_base and is_allowed_abs(parent):
                up_link = '<a class="btn" href="/roots?' + urllib.parse.urlencode({"p": parent}) + '">⋯ Up</a>'

            rows = []
            for name in entries:
                child = _real(os.path.join(abs_base, name))
                rows.append(
                    '<div class="row">'
                    '<div class="path">' + html_escape(child) + '</div>'
                    '<div class="actions">'
                    '<a class="btn" href="/roots?' + urllib.parse.urlencode({'p': child}) + '">Open</a>'
                    '<a class="btn" href="/setroot?' + urllib.parse.urlencode({'path': child}) + '">Use here</a>'
                    '</div></div>'
                )
            body = (
                '<div class="toolbar">' +
                (up_link or '') +
                '<a class="btn" href="/setroot?' + urllib.parse.urlencode({'path': abs_base}) + '">Use this folder</a>'
                '<a class="btn" href="/">Back to gallery</a>'
                '</div>'
                '<h3>Subfolders of</h3>'
                '<div class="current">' + html_escape(abs_base) + '</div>' +
                (''.join(rows) if rows else '<p>No subfolders.</p>')
            )
            return roots_template().replace('__TITLE__', 'Browse').replace('__BODY__', body)

        html = page_list_allowed() if not base else page_browse(_real(base))
        self._send_html(html)

    def _serve_setroot(self, query):
        qs = urllib.parse.parse_qs(query or '')
        path = qs.get('path', [''])[0]
        if not path:
            return self._simple_msg(400, "Missing path")
        ok = set_current_root(path)
        if not ok:
            return self._simple_msg(403, "Path not allowed")
        self.send_response(302)
        self.send_header('Location', '/')
        self.end_headers()
# ===== GAL:END_ROOTS_HANDLER =====

# ===== GAL:BEGIN_HTTP_HELPERS =====
    def _simple_msg(self, code, msg):
        body = "<!doctype html><meta charset='utf-8'><title>galser</title><body style='background:#111;color:#eee;font-family:system-ui'><p>" + html_escape(msg) + "</p><p><a href='/'>Back</a></p></body>"
        data = body.encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type','text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_status(self, code, body=b''):
        self.send_response(code)
        self.send_header('Content-Type','text/plain; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        if body: self.wfile.write(body)

    def _send_html(self, html):
        data = html.encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type','text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)
# ===== GAL:END_HTTP_HELPERS =====

# ===== GAL:BEGIN_ROOTS_TEMPLATE =====
def roots_template():
    return (r'''<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>galser — roots</title>
<style>
  :root { --bg:#111; --fg:#eee; --muted:#aaa; }
  * { box-sizing:border-box; }
  body { margin:0; font-family:system-ui, -apple-system, Segoe UI, Roboto, "Noto Sans", Arial, sans-serif; background:var(--bg); color:var(--fg); }
  header { padding:14px 18px; border-bottom:1px solid #222; display:flex; gap:10px; align-items:center; flex-wrap:wrap; }
  header .title { font-weight:700; font-size:18px; }
  a.btn { color:var(--fg); text-decoration:none; background:#222; padding:10px 14px; border-radius:12px; border:1px solid #333; font-size:16px; }
  .wrap { padding:14px 18px; }
  .row { display:flex; gap:12px; align-items:center; border:1px solid #222; border-radius:12px; padding:12px 14px; margin:12px 0; background:#1a1a1a; }
  .row .path { flex:1; font-family:ui-monospace, SFMono-Regular, Menlo, Consolas, "Liberation Mono", monospace; color:#ddd; overflow:auto; font-size:16px; }
  .row .actions { display:flex; gap:10px; flex-wrap:wrap; }
  .toolbar { display:flex; gap:10px; margin:10px 0 16px; flex-wrap:wrap; }
  .current { font-family:ui-monospace; color:#bbb; margin-bottom:8px; font-size:15px; }
  form.quick { display:flex; gap:8px; align-items:center; flex:1; }
  form.quick input[type="text"] { flex:1; min-width:220px; background:#222; color:#eee; border:1px solid #333; border-radius:10px; padding:10px 12px; }
  form.quick button { background:#222; color:#eee; border:1px solid #333; border-radius:10px; padding:10px 14px; cursor:pointer; }
  @media (max-width: 640px) {
    header .title { font-size:20px; }
    a.btn { font-size:18px; padding:12px 16px; border-radius:14px; }
    .row { padding:14px 16px; }
    .row .path { font-size:18px; }
  }
</style>
</head>
<body>
  <header>
    <div class="title">📁 __TITLE__</div>
    <div style="flex:1"></div>
    <a class="btn" href="/">Back to gallery</a>
  </header>
  <div class="wrap">
    <div class="toolbar">
      <form class="quick" method="get" action="/roots">
        <input type="text" name="p" placeholder="Type an absolute path… (e.g., D:\DOWN or /Volumes/Drive)" value="">
        <button type="submit">Browse</button>
      </form>
    </div>
    __BODY__
  </div>
</body>
</html>''')
# ===== GAL:END_ROOTS_TEMPLATE =====

# ===== GAL:BEGIN_MAIN =====
def main():
    global PORT, CURRENT_ROOT, ALLOWED_BASES
    if is_android_env() and is_storage_path(CURRENT_ROOT):
        CURRENT_ROOT = ANDROID_STORAGE
    ALLOWED_BASES = termux_candidates() if is_android_env() else desktop_candidates()

    if len(sys.argv) >= 3 and sys.argv[1] in ('-p','--port'):
        try: PORT = int(sys.argv[2])
        except ValueError: pass

    with ThreadingHTTPServer(("", PORT), Handler) as httpd:
        lan = get_lan_ip()
        print(f"Serving ⟶  http://127.0.0.1:{PORT}")
        print(f"Phone   ⟶  http://{lan}:{PORT}")
        print(f"Base    ⟶  {CURRENT_ROOT}")
        print("Press Ctrl+C to stop.")
        try: httpd.serve_forever()
        except KeyboardInterrupt: print("\nShutting down...")

if __name__ == '__main__':
    reset_cache()
    main()
# ===== GAL:END_MAIN =====
