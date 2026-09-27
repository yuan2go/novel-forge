from __future__ import annotations

import time
from typing import Any

from novel_forge.modules.command_kernel.dispatch_control import process_dispatch_suspended


def pause_worker_dispatch(supervisor: Any, poll_seconds: float) -> bool:
    if not process_dispatch_suspended():
        return False
    supervisor.polled(idle=True)
    time.sleep(poll_seconds)
    return True
