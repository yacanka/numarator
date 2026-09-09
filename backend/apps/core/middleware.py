# apps/core/middleware.py
import time
import logging
import uuid

logger = logging.getLogger(__name__)


class RequestLoggingMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request_id = str(uuid.uuid4())
        request.request_id = request_id
        start_time = time.time()

        response = self.get_response(request)

        duration = time.time() - start_time
        logger.info(
            f"[{request_id}] {request.method} {request.path} "
            f"status={response.status_code} duration={duration:.3f}s "
            f"user={getattr(request.user, 'username', 'anonymous')}"
        )

        response['X-Request-ID'] = request_id
        return response