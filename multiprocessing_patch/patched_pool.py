import threading
import time

import multiprocessing.pool
from multiprocessing.pool import TERMINATE
from multiprocessing.util import debug

# Patch multiprocessing.pool.Pool to prevent deadlocks on terminate()
# See https://bugs.python.org/issue29759 for more details

class PatchedPool(multiprocessing.pool.Pool):

    def __init__(self, *args, **kwargs):
        super(PatchedPool, self).__init__(*args, **kwargs)

    @staticmethod
    def _help_stuff_finish(inqueue, task_handler, size):
        # task_handler may be blocked trying to put items on inqueue
        debug('removing tasks from inqueue until task handler finished')
        inqueue._rlock.acquire()
        sentinels_taken = 0
        while task_handler.is_alive() and inqueue._reader.poll():
            obj = inqueue._reader.recv()
            if obj is None:
                sentinels_taken += 1
            time.sleep(0)
        for _ in range(sentinels_taken):
            inqueue._writer.send(None)
        inqueue._rlock.release()

    @classmethod
    def _terminate_pool(cls, taskqueue, inqueue, outqueue, pool,
                        worker_handler, task_handler, result_handler, cache):
        # this is guaranteed to only be called once
        debug('finalizing pool')

        worker_handler._state = TERMINATE

        # We must wait for the worker handler to exit before terminating
        # workers because we don't want workers to be restarted behind our back.
        debug('joining worker handler')
        if threading.current_thread() is not worker_handler:
            worker_handler.join(1e100)

        debug('helping task handler/workers to finish')
        cls._help_stuff_finish(inqueue, task_handler, len(pool))

        task_handler._state = TERMINATE

        assert result_handler.is_alive() or len(cache) == 0

        result_handler._state = TERMINATE
        outqueue.put(None)                  # sentinel

        debug('joining task handler')
        if threading.current_thread() is not task_handler:
            task_handler.join(1e100)

        debug('joining result handler')
        if threading.current_thread() is not result_handler:
            result_handler.join(1e100)

        if pool and hasattr(pool[0], 'terminate'):
            debug('joining pool workers')
            for p in pool:
                if p.is_alive():
                    # worker has not yet exited
                    debug('cleaning up worker %d' % p.pid)
                    p.join()
