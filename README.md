# SimpleDM

IDM-style download manager: multi-connection HTTP downloads, pause/resume,
queue, torrents/magnets, GUI, Chrome/Edge/Brave extension.

## Run
    pip install -r requirements.txt
    python app.py

(Linux: `sudo apt install python3-tk` if Tkinter is missing.)
If `libtorrent` fails to install, HTTP downloads still work; only torrents need it.

## Browser extension
1. Open chrome://extensions, turn on Developer mode.
2. Click "Load unpacked" and pick the `extension` folder.
3. Keep SimpleDM running. Browser downloads and magnet links are sent to it.
   Right-click any link -> "Download with SimpleDM".
If the app is closed, the browser downloads normally.

## Notes
- Queue: max simultaneous downloads and connections per file are in Settings.
- Resume works after closing the app (needs a server with Range support).
- Cookies/referrer from the browser are used for login-protected links but are
  not saved to disk, so resume after restart may need re-adding such links.
- Torrents are paused (not seeded) when finished. Only download content you
  have the right to.

## Make a Windows .exe (no Python needed to run it)
Option A, no Python on your PC: upload these files to a new GitHub repo, open the
Actions tab, run "Build Windows installer", then download SimpleDM-Setup from the run.
Option B: install Python once, double-click build.bat, get dist\SimpleDM.exe.
