"""Serialize native Django views to avoid concurrent SQLite write transactions."""

import threading

_request_lock = threading.Lock()


class SerializedRequestsMiddleware:
    """One active synchronous view per process, including response rendering.

    Django reads the request body before invoking synchronous middleware. Static
    responses are handled by WhiteNoise before this gate. Keep one server worker;
    the runtime's OS lock prevents another server from opening the same database.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        with _request_lock:
            return self.get_response(request)
