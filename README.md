# CSV-driven Browser Automation Video Recorder

A small Python tool that records a video of automated browser actions for every
row of an input CSV file. It uses Playwright (sync API) with Chromium.

For each row the tool opens DuckDuckGo, moves a custom cursor smoothly to the
search box, types a query like a human, runs the search and clicks the first
result, while the whole session is recorded to a `.webm` file.

A sample recording is available in [`demo/`](demo/).

## Features

- Custom SVG cursor (white arrow, black outline, ~32x32 px), because Playwright's
  video does not capture the OS cursor
- Semi-transparent yellow highlight circle that follows the cursor
- Click ripple that expands and fades out
- Smooth cursor movement along a curved path with easing (no teleporting)
- Human-like typing, symbol by symbol, with random delays
- Callout helper `ShowCallout(text, bgColor, textColor, fade)` with fade-in / fade-out
- Handles the full page navigation after the search (the JS context is destroyed)

## Project structure

| File | Purpose |
| --- | --- |
| `capture_video.py` | Main script: reads the CSV and calls `qscript.CaptureVideo_Magento(...)` for every row |
| `qscript.py` | Automation module: `CaptureVideo_Magento(...)`, `ShowCallout(...)`, global `PATH_TO_VIDEO_FOLDER` |
| `input.csv` | Sample input (3 rows) |
| `web_service.py` | Flask web service with a SQLite database: upload, lookup by company name, serving of videos |
| `video_client.py` | Client functions `UploadVideo(...)` and `GetVideoURL(...)` used by the recorder |
| `requirements.txt` | Python dependencies (`playwright`, `flask`, `requests`) |

## Requirements

- Python 3.9+
- Playwright for Python 1.49+ (installed from `requirements.txt`)
- Flask and requests (installed from `requirements.txt`)
- No other third-party libraries: the stdlib is used for everything else (`csv`, `sqlite3`, ...)

## Installation

macOS / Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium
```

Windows (PowerShell):

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m playwright install chromium
```

## Usage

```bash
python capture_video.py
```

Optional arguments:

```bash
python capture_video.py data.csv              # another CSV file
python capture_video.py --video-dir out       # another output folder
HEADLESS=1 python capture_video.py            # run without a browser window (macOS / Linux)
```

On Windows PowerShell use `$env:HEADLESS="1"; python capture_video.py`.

By default the browser window is shown: it is more reliable against bot detection. If no display is available, the script falls back to headless mode automatically.

For every row the script prints the path of the saved video:

```
[1] Acme GmbH ...
    saved: /path/to/project/video/Acme GmbH.webm
```

Videos are saved to `./video/<company_name>.webm` (the folder is created if missing).
Open them in a browser or VLC (QuickTime does not play `.webm`).

## Web service and video preview

The recorder can upload every recorded video to a small web service and open the
uploaded video in a browser.

Start the service in one terminal (it creates `videos.db` and `uploads/` next to `web_service.py`):

```bash
python web_service.py
```

It listens on `0.0.0.0:8000` by default. Change it with `FLASK_HOST` / `FLASK_PORT`
(on Windows PowerShell: `$env:FLASK_PORT="9000"; python web_service.py`).

Run the recorder in another terminal with `--server`:

```bash
python capture_video.py --server http://127.0.0.1:8000
python capture_video.py --server http://127.0.0.1:8000 --view-seconds 20
python capture_video.py --server http://127.0.0.1:8000 --view-seconds 0
```

After each recorded video the recorder uploads it, prints the returned URL and opens it in
a visible Chromium window. `--view-seconds N` keeps the window open for N seconds
(default 10); `0` keeps it open until you press Enter. A failed upload or preview is logged
and the loop continues with the next row.

### Endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/upload` | `UploadVideo`: multipart form with `file` and `company_name`, returns `{"company_name", "video_url"}` |
| `GET` | `/get_video_url?company_name=<name>` | `GetVideoURL`: returns `{"company_name", "video_url"}`, `404` for an unknown name |
| `GET` | `/media/<filename>` | Serves an uploaded video file (supports range requests, so seeking works) |
| `GET` | `/videos` | Lists all records |

Uploading the same `company_name` again updates the existing record (upsert, no duplicates).
Errors are returned as JSON: `{"error": "..."}`.

```bash
curl -F "file=@video/Acme GmbH.webm" -F "company_name=Acme GmbH" http://127.0.0.1:8000/upload
curl "http://127.0.0.1:8000/get_video_url?company_name=Acme%20GmbH"
```

### Database

SQLite (`videos.db`), table `videos`: `id`, `company_name` (unique), `file_path` (absolute path
on disk), `video_url`, `created_at`, `updated_at`. Only the path and the URL are stored, never
the video bytes; the files live in `uploads/`.

### Client functions

```python
from video_client import UploadVideo, GetVideoURL

url = UploadVideo("http://127.0.0.1:8000", "video/Acme GmbH.webm", "Acme GmbH")
url = GetVideoURL("http://127.0.0.1:8000", "Acme GmbH")
```

Both return the URL as a string and raise `VideoClientError` on failure
(`VideoNotFoundError` when the company is unknown). `requests` is imported lazily, so the
recorder runs without it when `--server` is not used.

### Design notes

- A new SQLite connection is opened per request (`flask.g`); WAL mode and a busy timeout
  prevent "database is locked" errors during concurrent uploads.
- Video URLs are built from `request.host_url`, not from a hard-coded host.
- File names are derived from the company name and sanitized; different company names that
  would map to the same file name get a short hash suffix so they never overwrite each other.
- Files are written to a temporary name and renamed, so a half-uploaded file is never served.

## Input format

`input.csv` is UTF-8, delimiter `;`, field qualifier `"`. The header is fixed:

```
URL;Company Name;Language;Country;Postcode;City;Street;HouseNo
"https://duckduckgo.com";"Acme GmbH";"de";"DE";"10115";"Berlin";"Invalidenstrasse";"12"
```

The search query is built from the city: `Magento developer in <city>`.

## API

```python
import qscript

qscript.PATH_TO_VIDEO_FOLDER = "./video"   # global, can be overridden

path = qscript.CaptureVideo_Magento(
    url, company_name, language, country, postcode, city, street, house_no
)
# -> absolute path to the .webm file, or None on failure
```

All parameters are strings. `language` and `country` set the browser locale,
`postcode`, `city`, `street`, `house_no` are shown in the first callout and
`city` is used in the search query.

## How it works

1. A Chromium context is created with `record_video_dir` and `record_video_size` (1280x720).
2. An init script (`context.add_init_script`) injects the cursor, the highlight, the ripple
   and the callout into every page. The cursor position is kept in `sessionStorage` and is
   re-synced from Python after each navigation.
3. Python moves the real mouse with `page.mouse.move` along a quadratic Bezier curve with
   ease-in-out timing; the injected cursor follows the `mousemove` events.
4. Clicks use real `mouse.down()` / `mouse.up()`, so default actions (focus, form submit,
   link navigation) work.
5. After the search the script polls for the first result, because results are rendered
   client-side and can take a long time. Errors caused by the destroyed JS context are ignored.
6. The context is closed to finalize the video, then the file is renamed to
   `<company_name>.webm`.

## Configuration

Constants at the top of `qscript.py`:

| Name | Meaning |
| --- | --- |
| `PATH_TO_VIDEO_FOLDER` | Output folder (default `./video`) |
| `VIEWPORT` | Viewport and video size (default 1280x720) |
| `HEADLESS` | Environment variable: `1` runs without a window (default: window is shown) |
| `RESULTS_TIMEOUT_S` | How long to wait for search results (default 60 s) |
| `SEL_SEARCH_BOX`, `SEL_SEARCH_BUTTON`, `SEL_FIRST_RESULT` | DuckDuckGo selectors |

## Troubleshooting

- **`command not found: python` or `pip` on macOS** - activate the virtual environment first
  (`source .venv/bin/activate`) or use `python3` / `pip3`.
- **`search results did not appear within 60 s`** - DuckDuckGo may show a bot check or the
  markup may have changed. A screenshot `debug_<company>.png` is saved to the video folder
  together with the page URL and title. Watch the browser window to see what happens, or try
  again later / from another network.
- **DuckDuckGo error page `418` / "blocked the request as automated traffic"** - the site
  detected automation. The script already runs headless mode as full Chromium
  (`channel="chromium"`, needs Playwright 1.49+). If it still happens, wait a few minutes,
  switch network, or set `BROWSER_CHANNEL=chrome` to use an installed Google Chrome.
- **Bot check (CAPTCHA) on the results page** - DuckDuckGo may show a challenge instead of results.
  In the default (window) mode the script waits up to 3 minutes while you solve it in the browser window,
  then continues. With `HEADLESS=1` it fails with a clear message.
- **Selectors stopped working** - update the `SEL_*` constants in `qscript.py`.
- **`UPLOAD FAILED: ... Connection refused`** - the web service is not running or the `--server`
  address is wrong. Start `python web_service.py` and use the same host and port.
- **`PREVIEW FAILED`** - the preview needs a visible browser window (`headless=False`), so it
  cannot run on a machine without a display.

## Known limitations

- Fixed pauses (`time.sleep`) are used to make the video readable; they are not tuned for speed.
- The scenario is written for DuckDuckGo and depends on its current markup.
- There are no automatic retries when a row fails; the failed row is reported and skipped.