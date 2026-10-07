from __future__ import annotations

from pathlib import Path

import pytest

from plg.synthetic import GeneratorConfig, SyntheticDataset, generate


@pytest.fixture(scope="session")
def synthetic() -> SyntheticDataset:
    """Full-size synthetic dataset (default config), shared across the session."""
    return generate(GeneratorConfig())


@pytest.fixture(scope="session")
def synthetic_dir(tmp_path_factory: pytest.TempPathFactory, synthetic: SyntheticDataset) -> Path:
    out = tmp_path_factory.mktemp("synthetic")
    synthetic.write(out)
    return out
