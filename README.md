# galser — tiny local gallery & file commander

Zero-dependency Python 3 web server that turns any folder into a fast mobile-friendly gallery **or** a simple file list. Built for phones (Termux on Android) and desktops.

- **Two modes**
  - **Thumbnails** (images only)
  - **File list** (all files with sizes; images still open the viewer)
- **Viewer**: one-finger swipe (next/prev), two-finger **pinch-to-zoom**, clamped pan, centered fit, neighbor preloading for instant swipes.
- **Folders**: browse subfolders; **⋯ (up)** to parent. In list mode, folders appear inline as `📁 FolderName` above files.
- **Settings (⚙️)**: switch mode, sort by **name/size**, asc/desc, live thumbnail size slider, link to folder picker.
- **Folder picker** (`/roots`) to change the **Base** directory at runtime (no restart).
- **Android niceties**: canonicalizes `/sdcard` → `/storage/emulated/0` and labels it **Storage**.
- **EXIF orientation** honored via CSS (`image-orientation: from-image`).
- **Threaded server** and LAN URL printout.

_No dependencies. Standard library only. Tested with Python 3.12 (Windows & Termux). Should work on 3.8+._

---

## Quick start

    python galser.py [--port 8000]
    # Open the printed URLs (127.0.0.1 and your LAN IP)

Start it **inside** the folder you want, or change the base at runtime via **⚙️ → Change base folder…** (opens `/roots`).

### Windows (optional helper)

    @echo off
    python "%~dp0galser.py" --port 8000

### Termux (Android)

    pkg install python -y
    cd ~/GIT/galser
    python galser.py --port 8000

Grant Termux storage permission if needed:

    termux-setup-storage

On Android, **Storage** refers to `/storage/emulated/0`.

---

## Usage & controls

### Gallery

- **Modes**: Thumbnails / File list (toggle in ⚙️).
- **Sorting**: Name or Size; Asc/Desc (⚙️). Sorting applies to files; folders are always name-sorted and shown above files.
- **Thumbnail size**: live slider (⚙️).

### Viewer

- **Swipe**: one finger horizontally to navigate.
- **Zoom**: two-finger **pinch**; **pan** with one finger while zoomed.
- **Reset zoom**: press `0` (keyboard).
- **Prev/Next** (keyboard): `←` / `→` when not zoomed in.
- **Back**: Android Back or `Esc` returns to the same gallery mode & sorting.

---

## URLs (for power users)

- Gallery:  
  `/?d=<relpath>&view=thumbs|list&sort=name|size&dir=asc|desc`  
  Example: `/?d=DCIM/Camera&view=list&sort=size&dir=desc`
- Viewer:  
  `/view?d=<relpath>&i=<index>&view=...&sort=...&dir=...`
- Image bytes:  
  `/raw?d=<relpath>&n=<filename>` (images only)
- Folder picker:  
  `/roots`  
  - `GET /roots?p=/abs/path` to browse a specific abs path  
  - `GET /setroot?path=/abs/path` to set Base (limited to allowed areas)
- Cache clear (rarely needed):  
  `/refresh`

---

## Notes & limits

- **Allowed bases (Android)**: candidates include the current working dir, `/storage/emulated/0` (**Storage**), `~/storage/shared`, and common media folders. You can pick any subfolder inside these.
- **Security**: no authentication; serves files under the selected Base only. Don’t expose to untrusted networks.
- **Formats**: images are recognized by extension: `.jpg .jpeg .png .gif .webp .bmp .tiff .tif .avif`. Non-images are listed in **File list** but not served by `/raw`.
- **Performance**: DCIM with 10k+ files is fine; first load may take a few seconds. Thumbnails are real images scaled by CSS (no pre-generated thumbs).
- **EXIF**: orientation is handled by the browser via CSS; no pixel rewriting.

---

## Development

The source includes patch markers to make surgical edits easy:

    # ===== GAL:BEGIN_<SECTION> =====
    ... code ...
    # ===== GAL:END_<SECTION> =====

Search for `GAL:` to jump between sections (gallery, viewer, roots, etc.).

---

## License

MIT
