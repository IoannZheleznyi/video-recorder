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
| `requirements.txt` | Python dependencies (`playwright` only) |

## Requirements

- Python 3.9+
- Playwright for Python 1.49+ (installed from `requirements.txt`)
- No other third-party libraries (the stdlib `csv` module is used for reading the input)

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

## Known limitations

- Fixed pauses (`time.sleep`) are used to make the video readable; they are not tuned for speed.
- The scenario is written for DuckDuckGo and depends on its current markup.
- There are no automatic retries when a row fails; the failed row is reported and skipped.