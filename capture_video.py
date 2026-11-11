"""capture_video.py - reads input.csv and records one video per row.

Usage:
    python capture_video.py                       # uses ./input.csv, videos -> ./video
    python capture_video.py data.csv              # another CSV file
    python capture_video.py --video-dir out       # another output folder
    python capture_video.py --server http://127.0.0.1:8000
                                                  # upload every video and preview it
    python capture_video.py --server http://127.0.0.1:8000 --view-seconds 0
                                                  # keep the preview open until Enter
"""
import argparse
import csv
import sys

import qscript

EXPECTED_COLUMNS = [
    "URL", "Company Name", "Language", "Country",
    "Postcode", "City", "Street", "HouseNo",
]

PLAY_SCRIPT = (
    "() => { const v = document.querySelector('video');"
    " if (v) { v.muted = true; v.play().catch(() => {}); } }"
)


def preview_video(video_url, view_seconds):
    """Open the uploaded video in Chromium (visible window) and keep it open.

    view_seconds > 0: close the browser after that many seconds.
    view_seconds == 0: keep it open until the user presses Enter.
    """
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        try:
            page = browser.new_page(viewport={"width": 1280, "height": 720})
            page.goto(video_url)
            try:
                page.evaluate(PLAY_SCRIPT)
            except Exception:
                pass
            if view_seconds > 0:
                page.wait_for_timeout(int(view_seconds * 1000))
            else:
                try:
                    input("    Press Enter to close the browser... ")
                except EOFError:
                    pass
        finally:
            try:
                browser.close()
            except Exception:
                pass


def upload_and_preview(server_url, video_path, company_name, view_seconds):
    """Upload the video, log its URL and preview it. Never raises."""
    try:
        from video_client import UploadVideo

        video_url = UploadVideo(server_url, video_path, company_name)
    except Exception as exc:
        print("    UPLOAD FAILED: %s" % exc)
        return False
    print("    uploaded: %s" % video_url)

    try:
        preview_video(video_url, view_seconds)
    except Exception as exc:
        print("    PREVIEW FAILED: %s" % exc)
        return False
    return True


def main():
    parser = argparse.ArgumentParser(description="Record browser videos for every CSV row.")
    parser.add_argument("csv_file", nargs="?", default="input.csv",
                        help="path to the input CSV (default: input.csv)")
    parser.add_argument("--video-dir", default="./video",
                        help="folder for the videos (default: ./video)")
    parser.add_argument("--server", default=None, metavar="URL",
                        help="upload every recorded video to this web service and preview it, "
                             "e.g. http://127.0.0.1:8000")
    parser.add_argument("--view-seconds", type=float, default=10.0, metavar="N",
                        help="preview time in seconds; 0 = keep the browser open until Enter "
                             "(default: 10)")
    args = parser.parse_args()

    if args.view_seconds < 0:
        parser.error("--view-seconds must be 0 or greater")

    qscript.PATH_TO_VIDEO_FOLDER = args.video_dir

    try:
        f = open(args.csv_file, newline="", encoding="utf-8-sig")
    except OSError as exc:
        print("Cannot open %s: %s" % (args.csv_file, exc))
        return 1

    failed = 0
    upload_failed = 0
    with f:
        reader = csv.DictReader(f, delimiter=";", quotechar='"')
        missing = [c for c in EXPECTED_COLUMNS if c not in (reader.fieldnames or [])]
        if missing:
            print("Missing CSV columns: %s" % ", ".join(missing))
            return 1

        for number, row in enumerate(reader, start=1):
            values = {c: (row.get(c) or "").strip() for c in EXPECTED_COLUMNS}
            print("[%d] %s ..." % (number, values["Company Name"] or "(no name)"))

            path = qscript.CaptureVideo_Magento(
                url=values["URL"],
                company_name=values["Company Name"],
                language=values["Language"],
                country=values["Country"],
                postcode=values["Postcode"],
                city=values["City"],
                street=values["Street"],
                house_no=values["HouseNo"],
            )

            if not path:
                failed += 1
                print("    FAILED: no video was produced")
                continue

            print("    saved: %s" % path)
            if args.server:
                ok = upload_and_preview(
                    args.server, path, values["Company Name"], args.view_seconds
                )
                if not ok:
                    upload_failed += 1

    return 1 if (failed or upload_failed) else 0


if __name__ == "__main__":
    sys.exit(main())