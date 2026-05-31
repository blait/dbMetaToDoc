"""Single shared ThreadPoolExecutor for background jobs."""
from concurrent.futures import ThreadPoolExecutor
from .. import config

_executor = None


def executor():
    global _executor
    if _executor is None:
        _executor = ThreadPoolExecutor(max_workers=config.JOB_WORKERS,
                                       thread_name_prefix="db2doc-job")
    return _executor
