# bot/tasks/task_registry.py
from datetime import datetime, timezone
import asyncio

TASKS = {}
RUNNERS = {}

def _iso(dt):
    try:
        return dt.astimezone(timezone.utc).isoformat() if dt else None
    except Exception:
        return None

def register_task(name: str, loop_obj, interval_desc: str, run_once_coro):
    """Register a Discord task loop for display and run-once support."""
    if name not in TASKS:
        TASKS[name] = {
            "name": name,
            "interval": interval_desc,
            "last_execution": None,
            "last_duration": None,
            "next_execution": _iso(getattr(loop_obj, "next_iteration", None)),
            "running": False,
        }
    RUNNERS[name] = run_once_coro

def mark_start(name: str, loop_obj):
    task = TASKS.get(name)
    if task:
        task["running"] = True
        task["last_execution"] = _iso(datetime.now(timezone.utc))
        task["next_execution"] = _iso(getattr(loop_obj, "next_iteration", None))

def mark_finish(name: str, started_at, loop_obj):
    task = TASKS.get(name)
    if task:
        try:
            if isinstance(started_at, datetime):
                duration = (datetime.now(timezone.utc) - started_at).total_seconds()
            else:
                duration = float(asyncio.get_event_loop().time() - started_at)
        except Exception:
            duration = None
        task["last_duration"] = f"{duration:.2f}s" if duration else "—"
        task["running"] = False
        task["next_execution"] = _iso(getattr(loop_obj, "next_iteration", None))

def get_all():
    return list(TASKS.values())

def has_task(name: str):
    return name in RUNNERS

def run_once(loop, name: str):
    """Manually trigger a registered task by name."""
    if name not in RUNNERS:
        raise KeyError(f"Task {name} not found")
    return asyncio.run_coroutine_threadsafe(RUNNERS[name](), loop)
