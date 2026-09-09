import json
import logging


class JSONFormatter(logging.Formatter):
    """Format log records as compact JSON for production log processors."""

    def format(self, record: logging.LogRecord) -> str:
        """Return a JSON encoded log record."""
        payload = {
            'level': record.levelname,
            'logger': record.name,
            'message': record.getMessage(),
            'time': self.formatTime(record, self.datefmt),
        }
        if record.exc_info:
            payload['exception'] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)
