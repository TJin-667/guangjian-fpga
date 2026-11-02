"""Bounded retry of a verified result's atomic directory rename on Windows.

No acquisition is repeated here. Only transient access/sharing errors can
retry, every attempt is traced, and the executor's cancellation/deadline
check remains authoritative. A permanent failure still reaches the original
SDK fail/quarantine path. Never overwrite an existing destination.
"""
import os
from pathlib import Path
import time

VERSION = "bounded-windows-publish-1"


def atomic_publish(source, destination, *, check, event, max_wait_s=.25,
                   replace=os.replace):
    source, destination = Path(source), Path(destination)
    started = time.monotonic()
    retries = 0
    while True:
        check()
        if destination.exists():
            raise FileExistsError("Refusing to overwrite an existing result: "+str(destination))
        try:
            replace(source,destination)
            return retries
        except PermissionError as exc:
            if getattr(exc,"winerror",None) not in (5,32,33) or not source.is_dir():
                raise
            if time.monotonic()-started >= max_wait_s:
                raise
            retries += 1
            event("publication_retry",retry=retries,winerror=exc.winerror,
                  waited_ms=(time.monotonic()-started)*1000)
            time.sleep(.01)


def executor_overlay(source):
    """One explicit, versioned software-only delta to the pinned SDK bytes."""
    old = b"os.replace(pending, published_path)"
    new = b"publish_directory.atomic_publish(pending, published_path, check=self._check, event=self._event)"
    if source.count(old) != 1:
        raise ValueError("Pinned SDK publication site changed; review the overlay")
    return source.replace(old,new,1)
