"""The integration tests and docker-compose must use the same images."""

import re
from pathlib import Path

from tests.integration.images import IMAGES

COMPOSE = Path(__file__).resolve().parents[2] / "docker-compose.yml"


def test_images_match_compose() -> None:
    compose_images = set(re.findall(r"^\s+image:\s*(\S+)", COMPOSE.read_text(), re.M))
    model_servers = {i for i in compose_images if "text-embeddings-inference" in i}
    assert set(IMAGES.values()) == compose_images - model_servers
