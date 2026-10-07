from __future__ import annotations

from pathlib import Path

from plg.plots import render_all
from plg.store import Warehouse
from plg.synthetic import GeneratorConfig, generate


def test_render_all_writes_pngs(tmp_path: Path) -> None:
    data = tmp_path / "data"
    generate(GeneratorConfig(n_users=4_000, seed=21)).write(data)
    paths = render_all(Warehouse(data), tmp_path / "img", "onboarding_v2")
    assert [p.name for p in paths] == [
        "funnel.png",
        "retention_heatmap.png",
        "experiment_ci.png",
        "sequential.png",
    ]
    for p in paths:
        assert p.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
        assert p.stat().st_size > 10_000
