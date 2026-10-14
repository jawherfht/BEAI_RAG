"""Ingestion worker entry point. The queue consumer is implemented in Phase 2."""

import logging

logger = logging.getLogger(__name__)


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    logger.info("ingestion-worker skeleton: consumer arrives in Phase 2")


if __name__ == "__main__":
    main()
