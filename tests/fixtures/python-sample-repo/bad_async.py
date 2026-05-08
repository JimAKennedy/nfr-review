"""Async fire-and-forget anti-patterns for testing PythonAstCollector."""

import asyncio


async def fire_and_forget():
    """create_task without storing — fire-and-forget anti-pattern."""
    asyncio.create_task(do_work())


async def stored_task():
    """create_task with stored result — correct pattern."""
    task = asyncio.create_task(do_work())
    await task


async def ensure_future_untracked():
    """ensure_future without storing — fire-and-forget."""
    asyncio.ensure_future(do_work())


async def ensure_future_tracked():
    """ensure_future with stored result — correct."""
    future = asyncio.ensure_future(do_work())
    await future


async def do_work():
    await asyncio.sleep(1)
