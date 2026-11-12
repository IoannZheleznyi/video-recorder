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
| `web_service.py` | Flask web service with a PostgreSQL database: upload, lookup by company name, serving of videos |
| `video_client.py` | Client functions `UploadVideo(...)` and `GetVideoURL(...)` used by the recorder |
| `requirements.txt` | Python dependencies (`playwright`, `flask`, `requests`, `psycopg2-binary`) |
| `Dockerfile`, `docker-compose.yml`, `docker/`, `video_service.wsgi` | Docker setup: Apache + mod_wsgi + Flask and PostgreSQL (see below) |

## Requirements

- Python 3.9+
- Playwright for Python 1.49+ (installed from `requirements.txt`)
- Flask, requests and psycopg2 (installed from `requirements.txt`)
- Docker with Docker Compose for the web service and the database
- No other third-party libraries: the stdlib is used for everything else (`csv`, ...)

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

## Web service, database and Docker

The recorder can upload every recorded video to a web service and open the uploaded video
in a browser. The service runs in Docker: Apache + mod_wsgi serves the Flask application in
the `web` container, PostgreSQL runs in a separate `db` container.

```
recorder (host) --HTTP :8000--> web: Apache + mod_wsgi + Flask --psycopg2--> db: PostgreSQL 16
                                      |                                          |
                                volume "uploads"                           volume "db_data"
```

### Run

Docker with Docker Compose is required.

```bash
docker compose up --build
```

The `db` container starts first; `web` starts only after the database healthcheck passes
(`depends_on: condition: service_healthy`) and also retries the connection on its own.
When `docker compose ps` shows both services as healthy, open
[http://localhost:8000/videos](http://localhost:8000/videos): an empty list `[]` means the
service works and the database is connected.

Settings can be changed with a `.env` file next to `docker-compose.yml`
(copy `.env.example`, do not commit `.env`):

| Variable | Default | Meaning |
| --- | --- | --- |
| `DB_NAME` | `videos` | Database name |
| `DB_USER` | `video_user` | Database user |
| `DB_PASSWORD` | `video_pass` | Database password (change it outside of local development) |
| `WEB_PORT` | `8000` | Host port mapped to Apache's port 80 |

The database settings reach the application only as environment variables
(`DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`); nothing is hard-coded.
PostgreSQL applies `DB_USER` / `DB_PASSWORD` only when the `db_data` volume is created, so after
changing them run `docker compose down -v` once to recreate the data.

### Use it with the recorder

```bash
python capture_video.py --server http://127.0.0.1:8000
python capture_video.py --server http://127.0.0.1:8000 --view-seconds 20
python capture_video.py --server http://127.0.0.1:8000 --view-seconds 0
```

After each recorded video the recorder uploads it, prints the returned URL and opens it in
a visible Chromium window. `--view-seconds N` keeps the window open for N seconds
(default 10); `0` keeps it open until you press Enter. A failed upload or preview is logged
and the loop continues with the next row.

Without the recorder:

```bash
curl -F "file=@video/Acme GmbH.webm" -F "company_name=Acme GmbH" http://localhost:8000/upload
curl "http://localhost:8000/get_video_url?company_name=Acme%20GmbH"
```

### Data survives restarts

Videos live in the named volume `uploads` (`/app/uploads`), database files in `db_data`.

```bash
docker compose down      # removes the containers, keeps the volumes
docker compose up        # the data and videos are still there
docker compose down -v   # also deletes the volumes (all data is lost)
```

### Inspect

```bash
docker compose ps
docker compose logs -f web
docker compose exec web curl http://localhost/videos
docker compose exec db psql -U video_user -d videos -c "SELECT * FROM videos;"
```

### Endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/upload` | `UploadVideo`: multipart form with `file` and `company_name`, returns `{"company_name", "video_url"}` |
| `GET` | `/get_video_url?company_name=<name>` | `GetVideoURL`: returns `{"company_name", "video_url"}`, `404` for an unknown name |
| `GET` | `/media/<filename>` | Serves an uploaded video file (supports range requests, so seeking works) |
| `GET` | `/videos` | Lists all records |

Uploading the same `company_name` again updates the existing record (upsert, no duplicates).
Errors are returned as JSON: `{"error": "..."}`; `503` means the database is unavailable.

### Database

PostgreSQL 16, table `videos` (created automatically on startup):

```sql
CREATE TABLE IF NOT EXISTS videos (
    id SERIAL PRIMARY KEY,
    company_name TEXT NOT NULL UNIQUE,
    file_path TEXT NOT NULL,
    video_url TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

Only the path and the URL are stored, never the video bytes; the files live in `uploads/`.

### Files

| File | Purpose |
| --- | --- |
| `Dockerfile` | Debian + Apache + `libapache2-mod-wsgi-py3`; the Python packages are installed into a virtualenv that mod_wsgi uses |
| `docker-compose.yml` | Services `web` and `db`, volumes `db_data` and `uploads`, healthchecks |
| `docker/apache/video-service.conf` | Apache VirtualHost with the mod_wsgi daemon process |
| `docker/entrypoint.sh` | Starts Apache in the foreground with the container's environment variables |
| `video_service.wsgi` | WSGI entry point: `from web_service import app as application` |
| `web_service.py` | Flask application (PostgreSQL via psycopg2) |

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

- A new PostgreSQL connection is opened per request (`flask.g`), because psycopg2 connections
  are not thread-safe. The Apache daemon runs 2 processes with 8 threads each.
- The schema is created at startup under an advisory lock, so several Apache processes never
  create the table at the same time. If the database is not reachable yet, the service retries
  (30 attempts, 2 s apart) instead of crashing.
- `mod_wsgi` comes from the Debian package that matches the image's system Python; the
  application's own packages are installed into `/opt/venv` from `requirements.txt`.
- Video URLs are built from `request.host_url`, not from a hard-coded host.
- Uploaded files are served by Flask (`send_from_directory`). In production Apache could serve
  them directly with an `Alias /media/ /app/uploads/` directive placed before `WSGIScriptAlias`.
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
  address is wrong. Start it with `docker compose up` and use the same host and port.
- **`port is already allocated` on `docker compose up`** - port 8000 is busy; set `WEB_PORT=8080` in `.env`.
- **`password authentication failed` in the `web` logs** - `DB_PASSWORD` was changed after the
  database volume had been created; run `docker compose down -v` to recreate it.
- **`PREVIEW FAILED`** - the preview needs a visible browser window (`headless=False`), so it
  cannot run on a machine without a display.

## Known limitations

- Fixed pauses (`time.sleep`) are used to make the video readable; they are not tuned for speed.
- The scenario is written for DuckDuckGo and depends on its current markup.
- There are no automatic retries when a row fails; the failed row is reported and skipped.