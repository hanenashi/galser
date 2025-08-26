# 📷 galser

A lightweight local photo gallery you can launch with one click. Runs a local Python web server and provides a mobile‑friendly, swipe‑to‑navigate fullscreen viewer.

## Features
- 📂 Auto‑discovers image files in the current folder (`.jpg`, `.jpeg`, `.png`, `.gif`, `.webp`, `.bmp`, `.tiff`).
- 🖼️ Responsive thumbnail grid.
- 👆 Swipe left/right on touch devices to navigate images.
- ⌨️ Arrow key navigation (desktop).
- 🔙 Android back button closes viewer and returns to gallery.
- 🚀 One‑click start via `galser.bat` (Windows) which opens your default browser in fullscreen mode.
- ⚡ Uses lazy‑loading for thumbnails.

## Requirements
- [Python 3.9+](https://www.python.org/downloads/)
- [pip](https://pip.pypa.io/)

## Installation

1. Clone this repository:
   ```bash
   git clone https://github.com/hanenashi/galser.git
   cd galser
   ```

2. (Optional) Create and activate a virtual environment:
   ```bash
   python -m venv .venv
   .\.venv\Scripts\activate   # on Windows
   source .venv/bin/activate   # on macOS/Linux
   ```

3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

*(Current version only uses Python standard library, so `requirements.txt` may be empty.)*

---

## Usage

### On Windows
Run:
```bat
server.bat
```
This will start the local server in the background and open your browser in fullscreen mode at [http://127.0.0.1:8000](http://127.0.0.1:8000).

### On Other Platforms
Run:
```bash
python thumb_server.py --port 8000
```
Then open [http://127.0.0.1:8000](http://127.0.0.1:8000) in your browser manually.

---

## Controls
- 📷 Tap an image in the grid to view fullscreen.
- ⬅️➡️ Swipe left/right (or use arrow keys on desktop) to navigate.
- 🔙 Use the browser **Back** button (or Android back button) to return to the gallery.

---

## Notes
- This tool is designed for **local use**. Do not expose the server to the internet.
- Works best in modern browsers (Chrome, Edge, Firefox, Safari). Mobile browsers support swipe gestures.
