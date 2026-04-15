"""Standalone browser worker entrypoint."""

from __future__ import annotations

import asyncio

from loguru import logger

from nanobot.browser_worker.config import BrowserWorkerSettings
from nanobot.browser_worker.runner import BrowserExecutor, BrowserWorker, RedisBrowserJobConsumer
from nanobot.cloud.browser_store import RedisBrowserStore
from nanobot.cloud.config import RedisSettings
from nanobot.cloud.redis_client import create_redis_client


async def _run() -> None:
    settings = BrowserWorkerSettings.load()
    logger.info(
        "Starting browser worker id={} redis_url={} redis_mode={} redis_key_prefix={} browser_key_prefix={} shm_root={}",
        settings.worker_id,
        settings.redis_url,
        settings.redis_mode,
        settings.redis_key_prefix,
        settings.browser_key_prefix,
        settings.shm_root,
    )
    redis = create_redis_client(
        RedisSettings(
            url=settings.redis_url,
            mode=settings.redis_mode,
            key_prefix=settings.redis_key_prefix,
        )
    )
    store = RedisBrowserStore(
        redis,
        key_prefix=f"{settings.redis_key_prefix}:{settings.browser_key_prefix}",
    )
    worker = BrowserWorker(
        store=store,
        worker_id=settings.worker_id,
        auth_ttl_s=settings.auth_ttl_s,
        qr_ttl_s=settings.qr_ttl_s,
        executor=BrowserExecutor(shm_root=settings.shm_root),
    )
    consumer = RedisBrowserJobConsumer(
        redis,
        store,
        worker,
        block_ms=settings.poll_block_ms,
    )
    logger.info(
        "Browser worker consuming stream={} event_stream={} consumer_group=workers",
        store.keys.job_stream,
        store.keys.event_stream,
    )
    await consumer.run_forever()


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
