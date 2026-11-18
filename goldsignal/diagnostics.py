import logging
import time
from uuid import uuid4

from .store import transaction

log = logging.getLogger(__name__)


def record(source, message, *, level="error"):
    now = time.time_ns()
    try:
        with transaction() as store:
            store.put("backend_log", f"{now:020d}-{uuid4().hex}", {
                "time": now // 1_000_000, "source": source, "level": level, "message": message,
            })
            store.prune("backend_log", 200)
    except Exception:
        log.warning("Could not save a backend log entry for %s", source)
