# Copyright (c) 2025 AnonymousX1025
# Licensed under the MIT License.

import shutil
import time
from pathlib import Path

from anony import logger, config


def cleanup_downloads():
    """Remove stale temporary media to prevent the downloads folder filling up."""
    folder = Path("downloads")
    folder.mkdir(parents=True, exist_ok=True)
    cutoff = time.time() - (config.DOWNLOAD_TTL_HOURS * 3600)
    removed = 0
    for item in folder.iterdir():
        try:
            if item.is_file() and item.stat().st_mtime < cutoff:
                item.unlink()
                removed += 1
        except OSError as ex:
            logger.warning("Could not remove stale download %s: %s", item, ex)
    if removed:
        logger.info("Cleaned %s stale download file(s).", removed)


def ensure_dirs():
    if not shutil.which("deno") or not shutil.which("ffmpeg"):
        raise RuntimeError("Deno and FFmpeg must be installed and accessible in the system PATH.")
    for directory in ("cache", "downloads"):
        Path(directory).mkdir(parents=True, exist_ok=True)
    cleanup_downloads()
    logger.info("Cache directories updated.")
