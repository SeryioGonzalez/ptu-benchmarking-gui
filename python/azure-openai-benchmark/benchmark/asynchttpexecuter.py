
import asyncio
import logging
import os
import signal
import time
from datetime import timedelta
from typing import Callable

import aiohttp

from .ratelimiting import NoRateLimiter

# Threshold in seconds to warn about requests lagging behind target rate.
LAG_WARN_DURATION = 1.0

logger = logging.getLogger(__name__)

class AsyncHTTPExecuter:
    """
    An implementation of an async HTTP executer class with rate limiting and
    concurrency control.
    """
    def __init__(self, async_http_func: Callable[[aiohttp.ClientSession], None], rate_limiter=NoRateLimiter(), max_concurrency=12, finish_run_func=None):
        """
        Creates a new executer.
        :param async_http_func: A callable function that takes aiohttp.ClientSession to use to perform request.
        :param rate_limiter: Rate limiter object to use, defaults to NoRateLimiter.
        :param max_concurrency: Maximum number of concurrent requests, defaults to 12.
        :param finish_run_func: Function to run when run reaches end.
        """
        self.async_http_func = async_http_func
        self.rate_limiter = rate_limiter
        self.max_concurrency = max_concurrency
        self.max_lag_warn = timedelta(seconds=5).seconds
        self.terminate = False
        self.finish_run_func = finish_run_func

    def run(self, duration = None) -> None:
        """
        Schedule the executor loop as a background task on the current event loop.
        """
        logger.info("HTTP executer run")
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # No loop running: safe to start a brand-new one
            asyncio.run(self._run(duration))
        else:
            # Inside an existing loop: schedule as a background task
            loop.create_task(self._run(duration))

    async def _run(self, duration=None):
        logger.info("Async HTTP executer run")
        
        # disable all TCP limits for highly parallel loads
        conn = aiohttp.TCPConnector(limit=0)
        logger.info("Using aiohttp TCP connector with no limits")


        async with aiohttp.ClientSession(connector=conn) as session:
            start_time = time.time()
            calls_made = 0
            request_tasks = set()
            run_end_conditions_met = False
            while not run_end_conditions_met and not self.terminate:
                async with self.rate_limiter:
                    if len(request_tasks) > self.max_concurrency:
                        wait_start_time = time.time()
                        _, crs_pending = await asyncio.wait(request_tasks, return_when=asyncio.FIRST_COMPLETED)
                        request_tasks = crs_pending
                        waited = time.time() - wait_start_time
                        if waited > LAG_WARN_DURATION and type(self.rate_limiter) is not NoRateLimiter:
                            logging.warning(f"falling behind committed rate by {round(waited, 3)}s, consider increasing number of clients.")
                    v = asyncio.create_task(self.async_http_func(session))
                    request_tasks.add(v)
                    calls_made += 1
                    # Determine whether to end the run
                    if duration is None:
                        run_end_conditions_met = False
                    else:
                        duration_limit_reached = duration is not None and (time.time() - start_time) > duration
                        run_end_conditions_met = duration_limit_reached

            if len(request_tasks) > 0:
                logging.info(f"waiting for {len(request_tasks)} requests to drain (up to a max of 30 seconds)")
                await asyncio.wait(request_tasks, timeout=30)

            if self.finish_run_func:
                self.finish_run_func()

        signal.signal(signal.SIGINT, orig_sigint_handler)
        signal.signal(signal.SIGTERM, orig_sigterm_handler)

    def _terminate(self, *args):
        if not self.terminate:
            logging.warning("got terminate signal, draining. signal again to exit immediately.")
            self.terminate = True
        else:
            logging.info("forcing program exit")
            os._exit(0)
