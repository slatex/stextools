import contextlib
import time

@contextlib.contextmanager
def timelogger(logger, task):
    start = time.time()
    yield
    elapsed = time.time() - start
    logger.info(f"{task} took {elapsed} seconds")
