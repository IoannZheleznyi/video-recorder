"""video_client.py - client functions used by the recorder.

The `requests` library is imported lazily inside the functions, so the
recorder keeps working without it when no server is used.
"""
import mimetypes
import os

CONNECT_TIMEOUT_S = 10
READ_TIMEOUT_S = 300


class VideoClientError(Exception):
    """The server could not be reached or answered with an error."""


class VideoNotFoundError(VideoClientError):
    """The server has no video for the requested company name."""


def _endpoint(server_url, path):
    return server_url.rstrip("/") + path


def _error_message(response):
    try:
        data = response.json()
    except ValueError:
        data = None
    if isinstance(data, dict) and data.get("error"):
        return str(data["error"])
    return response.text[:200].strip() or "HTTP %d" % response.status_code


def _read_video_url(response):
    try:
        data = response.json()
    except ValueError:
        data = None
    if not isinstance(data, dict) or not data.get("video_url"):
        raise VideoClientError("Server answer has no 'video_url': %s" % response.text[:200])
    return str(data["video_url"])


def UploadVideo(server_url: str, video_path: str, company_name: str) -> str:
    """Uploads a video file to the server and returns its URL."""
    import requests

    if not os.path.isfile(video_path):
        raise FileNotFoundError("Video file not found: %s" % video_path)

    content_type = mimetypes.guess_type(video_path)[0] or "application/octet-stream"
    with open(video_path, "rb") as fileobj:
        try:
            response = requests.post(
                _endpoint(server_url, "/upload"),
                files={"file": (os.path.basename(video_path), fileobj, content_type)},
                data={"company_name": company_name},
                timeout=(CONNECT_TIMEOUT_S, READ_TIMEOUT_S),
            )
        except requests.RequestException as exc:
            raise VideoClientError("Upload request failed: %s" % exc) from exc

    if response.status_code != 200:
        raise VideoClientError(
            "Upload failed (HTTP %d): %s" % (response.status_code, _error_message(response))
        )
    return _read_video_url(response)


def GetVideoURL(server_url: str, company_name: str) -> str:
    """Returns the video URL for the given company name."""
    import requests

    try:
        response = requests.get(
            _endpoint(server_url, "/get_video_url"),
            params={"company_name": company_name},
            timeout=(CONNECT_TIMEOUT_S, 30),
        )
    except requests.RequestException as exc:
        raise VideoClientError("Request failed: %s" % exc) from exc

    if response.status_code == 404:
        raise VideoNotFoundError("No video for company '%s'." % company_name)
    if response.status_code != 200:
        raise VideoClientError(
            "Request failed (HTTP %d): %s" % (response.status_code, _error_message(response))
        )
    return _read_video_url(response)