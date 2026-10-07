from __future__ import annotations

from pathlib import Path

import pytest

from plg.sitegen.builder import (
    REPO_URL,
    SiteConfig,
    build_site,
    ensure_dataset,
    markdown_section,
    render_markdown,
)

ROOT = Path(__file__).resolve().parents[1]


def test_markdown_section_stops_at_next_heading() -> None:
    text = "# T\n\n## A\n\nfirst\n\n### sub\n\nstill A\n\n## B\n\nsecond\n"
    assert markdown_section(text, "A") == "first\n\n### sub\n\nstill A"
    assert markdown_section(text, "B") == "second"
    with pytest.raises(ValueError, match="no '## C' section"):
        markdown_section(text, "C")


def test_render_markdown_tables_and_links() -> None:
    html = render_markdown(
        "| a | b |\n| --- | --- |\n| 1 | 2 |\n\n"
        "[brief](docs/PRODUCT.md) [ext](https://example.com) [top](#x) <script>x</script>"
    )
    assert "<table>" in html
    assert f'href="{REPO_URL}/blob/main/docs/PRODUCT.md"' in html
    assert 'href="https://example.com"' in html
    assert 'href="#x"' in html
    assert "<script>" not in html


def test_ensure_dataset_rejects_other_config(tmp_path: Path) -> None:
    data = tmp_path / "data"
    ensure_dataset(SiteConfig(data_dir=data, users=1_500, seed=5))
    with pytest.raises(ValueError, match="n_users=1500, seed=5"):
        ensure_dataset(SiteConfig(data_dir=data, users=1_500, seed=6))


def test_build_site_writes_self_contained_pages(tmp_path: Path) -> None:
    cfg = SiteConfig(
        out_dir=tmp_path / "site",
        data_dir=tmp_path / "data",
        repo_root=ROOT,
        users=3_000,
        seed=11,
        peeking_sims=50,
    )
    paths = build_site(cfg)
    names = {p.relative_to(cfg.out_dir).as_posix() for p in paths}
    assert {"index.html", "product.html", ".nojekyll", "img/architecture.svg"} <= names
    assert all(p.exists() for p in paths)

    index = (cfg.out_dir / "index.html").read_text()
    assert "$ plg experiment onboarding_v2" in index
    assert "Decision: " in index
    assert "(SYNTHETIC)" in index
    assert "3,000 users, seed 11" in index
    assert "{{" not in index
    assert "{%" not in index
    # Offline: no stylesheet or script pulled from elsewhere.
    assert "<script" not in index
    assert 'rel="stylesheet"' not in index
    for img in ("experiment_ci.png", "sequential.png", "funnel.png", "retention_heatmap.png"):
        assert f'src="img/{img}"' in index
        assert (cfg.out_dir / "img" / img).read_bytes()[:4] == b"\x89PNG"

    product = (cfg.out_dir / "product.html").read_text()
    assert "<h2>Success metrics and evals</h2>" in product
    assert "<table>" in product
