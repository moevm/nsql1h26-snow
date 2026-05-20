from __future__ import annotations

import logging
import os
import subprocess
import tempfile

logger = logging.getLogger(__name__)


def download_osm_if_needed(osm_path: str, pbf_url: str, bbox: str) -> None:
    if os.path.exists(osm_path):
        logger.info("OSM file already exists at %s, skipping download.", osm_path)
        return

    osm_dir = os.path.dirname(osm_path)
    if osm_dir:
        os.makedirs(osm_dir, exist_ok=True)

    pbf_fd, pbf_file = tempfile.mkstemp(suffix=".osm.pbf")
    os.close(pbf_fd)
    try:
        logger.info("Downloading PBF from %s (600~ MB, this may take some time)", pbf_url)
        subprocess.run(["wget", "-q", "-O", pbf_file, pbf_url], check=True)
        logger.info("Extracting bbox %s to %s …", bbox, osm_path)
        subprocess.run(
            ["osmium", "extract", "-b", bbox, pbf_file, "-o", osm_path],
            check=True,
        )
        logger.info("OSM file ready: %s", osm_path)
    finally:
        if os.path.exists(pbf_file):
            os.unlink(pbf_file)
