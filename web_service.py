"""web_service.py - Flask video web service backed by PostgreSQL.

In Docker the service runs under Apache + mod_wsgi (see Dockerfile and
video_service.wsgi). For local development it can also be started directly:

    DB_HOST=localhost DB_NAME=videos DB_USER=video_user DB_PASSWORD=... python web_service.py

Database settings come only from environment variables:
    DB_HOST, DB_NAME, DB_USER, DB_PASSWORD (required), DB_PORT (default 5432)
    DB_CONNECT_ATTEMPTS, DB_CONNECT_DELAY - how long to wait for the database
    at startup (defaults: 30 attempts, 2 seconds apart)

Endpoints:
    POST /upload                       multipart: file + company_name (upsert)
    GET  /get_video_url?company_name=  returns the video URL, 404 if unknown
    GET  /media/<filename>             serves an uploaded video
    GET  /videos                       lists all records

Videos are stored on disk in ./uploads next to this file; the database keeps
only the company name, the file path and the URL.
"""
import hashlib
import mimetypes
import os
import re
import time
import uuid
from urllib.parse import quote

import psycopg2
import psycopg2.extras
from flask import Flask, g, jsonify, request, send_from_directory

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")

ALLOWED_EXTENSIONS = {".webm", ".mp4", ".mov", ".mkv", ".m4v", ".ogv"}
DEFAULT_EXTENSION = ".webm"
MAX_UPLOAD_BYTES = 500 * 1024 * 1024
SCHEMA_LOCK_ID = 727274

SCHEMA = """
CREATE TABLE IF NOT EXISTS videos (
    id SERIAL PRIMARY KEY,
    company_name TEXT NOT NULL UNIQUE,
    file_path TEXT NOT NULL,
    video_url TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
)
"""

UPSERT_SQL = """
INSERT INTO videos (company_name, file_path, video_url)
VALUES (%s, %s, %s)
ON CONFLICT (company_name) DO UPDATE SET
    file_path = EXCLUDED.file_path,
    video_url = EXCLUDED.video_url,
    updated_at = NOW()
"""

mimetypes.add_type("video/webm", ".webm")

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_BYTES


def _env(name, default=None):
    value = os.environ.get(name, default)
    if value is None or value == "":
        raise RuntimeError("Environment variable %s is not set." % name)
    return value


def _connect():
    return psycopg2.connect(
        host=_env("DB_HOST"),
        port=int(_env("DB_PORT", "5432")),
        dbname=_env("DB_NAME"),
        user=_env("DB_USER"),
        password=_env("DB_PASSWORD"),
        connect_timeout=10,
    )


def connect_with_retry():
    """Connect to PostgreSQL, waiting until the database accepts connections."""
    attempts = int(os.environ.get("DB_CONNECT_ATTEMPTS", "30"))
    delay = float(os.environ.get("DB_CONNECT_DELAY", "2"))
    last_error = None
    for attempt in range(1, attempts + 1):
        try:
            return _connect()
        except psycopg2.OperationalError as exc:
            last_error = exc
            print("[web_service] database is not ready (attempt %d/%d): %s"
                  % (attempt, attempts, str(exc).strip()), flush=True)
            time.sleep(delay)
    raise last_error


def get_db():
    """One PostgreSQL connection per request (psycopg2 connections are not thread-safe)."""
    if "db" not in g:
        g.db = _connect()
    return g.db


def get_cursor():
    return get_db().cursor(cursor_factory=psycopg2.extras.RealDictCursor)


@app.teardown_appcontext
def close_db(exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_storage():
    """Create uploads/ and the videos table if they are missing.

    An advisory lock keeps several Apache worker processes from creating the
    table at the same moment.
    """
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    conn = connect_with_retry()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("SELECT pg_advisory_xact_lock(%s)", (SCHEMA_LOCK_ID,))
                cur.execute(SCHEMA)
    finally:
        conn.close()


def error_response(message, status):
    return jsonify({"error": message}), status


def make_video_url(filename):
    """Build the public URL from the current request, never from a fixed host."""
    return request.host_url + "media/" + quote(filename)


def build_filename(cur, company_name, extension):
    """File name derived from the company name, unique per company."""
    stem = re.sub(r"[^\w.-]+", "_", company_name, flags=re.UNICODE).strip("._")
    stem = stem[:100] or "video"
    filename = stem + extension
    cur.execute(
        "SELECT company_name FROM videos WHERE file_path = %s",
        (os.path.join(UPLOAD_DIR, filename),),
    )
    owner = cur.fetchone()
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


@app.errorhandler(psycopg2.OperationalError)
def database_unavailable(exc):
    return error_response("Database is not available.", 503)


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
    with get_cursor() as cur:
        filename = build_filename(cur, company_name, extension)
    db.commit()

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
        with get_cursor() as cur:
            cur.execute(
                "SELECT file_path FROM videos WHERE company_name = %s", (company_name,)
            )
            previous = cur.fetchone()
            cur.execute(UPSERT_SQL, (company_name, file_path, video_url))
        db.commit()
    except psycopg2.OperationalError:
        raise
    except psycopg2.Error as exc:
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

    with get_cursor() as cur:
        cur.execute(
            "SELECT company_name, file_path FROM videos WHERE company_name = %s",
            (company_name,),
        )
        row = cur.fetchone()
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
    with get_cursor() as cur:
        cur.execute(
            "SELECT id, company_name, file_path, video_url, created_at, updated_at "
            "FROM videos ORDER BY id"
        )
        rows = cur.fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["created_at"] = item["created_at"].isoformat()
        item["updated_at"] = item["updated_at"].isoformat()
        result.append(item)
    return jsonify(result)


init_storage()


if __name__ == "__main__":
    host = os.environ.get("FLASK_HOST", "0.0.0.0")
    port = int(os.environ.get("FLASK_PORT", "8000"))
    app.run(host=host, port=port, threaded=True)