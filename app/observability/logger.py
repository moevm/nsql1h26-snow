import logging
import sys

def setup_logging(level: int = logging.INFO) -> None:
    fmt = "%(asctime)s  %(levelname)-7s  [%(name)s]  %(message)s"
    logging.basicConfig(
        level=level,
        format=fmt,
        handlers=[logging.StreamHandler(sys.stdout)],
    )
    logging.getLogger("neo4j").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
