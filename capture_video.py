"""capture_video.py - reads input.csv and records one video per row.

Usage:
    python capture_video.py                  # uses ./input.csv, videos -> ./video
    python capture_video.py data.csv         # another CSV file
    python capture_video.py --video-dir out  # another output folder
"""
import argparse
import csv
import sys

import qscript

EXPECTED_COLUMNS = [
    "URL", "Company Name", "Language", "Country",
    "Postcode", "City", "Street", "HouseNo",
]


def main():
    parser = argparse.ArgumentParser(description="Record browser videos for every CSV row.")
    parser.add_argument("csv_file", nargs="?", default="input.csv",
                        help="path to the input CSV (default: input.csv)")
    parser.add_argument("--video-dir", default="./video",
                        help="folder for the videos (default: ./video)")
    args = parser.parse_args()

    # override the global variable of the module
    qscript.PATH_TO_VIDEO_FOLDER = args.video_dir

    try:
        # utf-8-sig also accepts files saved with a BOM (e.g. by Excel)
        f = open(args.csv_file, newline="", encoding="utf-8-sig")
    except OSError as exc:
        print("Cannot open %s: %s" % (args.csv_file, exc))
        return 1

    failed = 0
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

            if path:
                print("    saved: %s" % path)
            else:
                failed += 1
                print("    FAILED: no video was produced")

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
