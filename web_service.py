"""web_service.py - small Flask service that stores and serves recorded videos.

Run:
    python web_service.py

Environment variables:
    FLASK_HOST   interface to listen on (default 0.0.0.0)
    FLASK_PORT   port to listen on (default 8000)

Endpoints:
    POST /upload                       multipart: file + company_name (upsert)
    GET  /get_video_url?company_name=  returns the video URL, 404 if unknown
    GET  /media/<filename>             serves an uploaded video
    GET  /videos                       lists all records

Videos are stored on disk in ./uploads next to this file, the database
./videos.db (SQLite) keeps only the company name, the file path and the URL.
"""
import hashlib
import mimetypes
import os
import re
import sqlite3
import uuid
from urllib.parse import quote

from flask import Flask, g, jsonify, request, send_from_directory

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
DB_PATH = os.path.join(BASE_DIR, "videos.db")

ALLOWED_EXTENSIONS = {".webm", ".mp4", ".mov", ".mkv", ".m4v", ".ogv"}
DEFAULT_EXTENSION = ".webm"
MAX_UPLOAD_BYTES = 500 * 1024 * 1024
BUSY_TIMEOUT_S = 30

SCHEMA = """
CREATE TABLE IF NOT EXISTS videos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_name TEXT NOT NULL UNIQUE,
    file_path TEXT NOT NULL,
    video_url TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
)
"""

UPSERT_SQL = """
INSERT INTO videos (company_name, file_path, video_url)
VALUES (?, ?, ?)
ON CONFLICT(company_name) DO UPDATE SET
    file_path = excluded.file_path,
    video_url = excluded.video_url,
    updated_at = datetime('now')
"""

mimetypes.add_type("video/webm", ".webm")

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_BYTES


def _connect():
    conn = sqlite3.connect(DB_PATH, timeout=BUSY_TIMEOUT_S)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = %d" % (BUSY_TIMEOUT_S * 1000))
    return conn


def get_db():
    """One SQLite connection per request (Flask's server is threaded)."""
    if "db" not in g:
        g.db = _connect()
    return g.db


@app.teardown_appcontext
def close_db(exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_storage():
    """Create uploads/ and videos.db with the videos table if they are missing."""
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    conn = _connect()
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(SCHEMA)
        conn.commit()
    finally:
        conn.close()


def error_response(message, status):
    return jsonify({"error": message}), status


def make_video_url(filename):
    """Build the public URL from the current request, never from a fixed host."""
    return request.host_url + "media/" + quote(filename)


def build_filename(db, company_name, extension):
    """File name derived from the company name, unique per company."""
    stem = re.sub(r"[^\w.-]+", "_", company_name, flags=re.UNICODE).strip("._")
    stem = stem[:100] or "video"
    filename = stem + extension
    owner = db.execute(
        "SELECT company_name FROM videos WHERE file_path = ?",
        (os.path.join(UPLOAD_DIR, filename),),
    ).fetchone()
    if owner is not None and owner["company_name"] != company_name:
        digest = hashlib.sha1(company_name.encode("utf-8")).hexdigest()[:8]
        filename = "%s_%s%s" % (stem, digest, extension)
    return filename


@app.errorhandler(404)
def not_found(exc):
    return error_response("Not found.", 404)


@app.errorhandler(413)
def too_large(exc):
    return error_response("Uploaded file is too large.", 413)


@app.route("/upload", methods=["POST"])
def upload_video():
    upload = request.files.get("file")
    company_name = (request.form.get("company_name") or "").strip()

    if upload is None or not upload.filename:
        return error_response("Field 'file' with a video file is required.", 400)
    if not company_name:
        return error_response("Field 'company_name' is required.", 400)

    extension = os.path.splitext(upload.filename)[1].lower() or DEFAULT_EXTENSION
    if extension not in ALLOWED_EXTENSIONS:
        return error_response(
            "Unsupported file type '%s'. Allowed: %s."
            % (extension, ", ".join(sorted(ALLOWED_EXTENSIONS))),
            400,
        )

    db = get_db()
    filename = build_filename(db, company_name, extension)
    file_path = os.path.join(UPLOAD_DIR, filename)
    video_url = make_video_url(filename)

    os.makedirs(UPLOAD_DIR, exist_ok=True)
    temp_path = "%s.%s.part" % (file_path, uuid.uuid4().hex)
    try:
        upload.save(temp_path)
        os.replace(temp_path, file_path)
    except OSError as exc:
        if os.path.exists(temp_path):
            os.remove(temp_path)
        return error_response("Could not store the file: %s" % exc, 500)

    try:
        previous = db.execute(
            "SELECT file_path FROM videos WHERE company_name = ?", (company_name,)
        ).fetchone()
        db.execute(UPSERT_SQL, (company_name, file_path, video_url))
        db.commit()
    except sqlite3.Error as exc:
        db.rollback()
        return error_response("Database error: %s" % exc, 500)

    if previous is not None and previous["file_path"] != file_path:
        try:
            os.remove(previous["file_path"])
        except OSError:
            pass

    return jsonify({"company_name": company_name, "video_url": video_url})


@app.route("/get_video_url", methods=["GET"])
def get_video_url():
    company_name = (request.args.get("company_name") or "").strip()
    if not company_name:
        return error_response("Query parameter 'company_name' is required.", 400)

    row = get_db().execute(
        "SELECT company_name, file_path FROM videos WHERE company_name = ?",
        (company_name,),
    ).fetchone()
    if row is None:
        return error_response("Company '%s' was not found." % company_name, 404)

    return jsonify({
        "company_name": row["company_name"],
        "video_url": make_video_url(os.path.basename(row["file_path"])),
    })


@app.route("/media/<filename>", methods=["GET"])
def media(filename):
    return send_from_directory(UPLOAD_DIR, filename)


@app.route("/videos", methods=["GET"])
def list_videos():
    rows = get_db().execute(
        "SELECT id, company_name, file_path, video_url, created_at, updated_at "
        "FROM videos ORDER BY id"
    ).fetchall()
    return jsonify([dict(row) for row in rows])


init_storage()


if __name__ == "__main__":
    host = os.environ.get("FLASK_HOST", "0.0.0.0")
    port = int(os.environ.get("FLASK_PORT", "8000"))
    app.run(host=host, port=port, threaded=True)