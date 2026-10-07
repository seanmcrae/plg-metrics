"""Build the static documentation site from live analysis output.

Every number and chart on the site comes from running the package on the bundled
SYNTHETIC dataset at build time, plus the committed multi-seed validation CSV
that ``make validate`` produces. Nothing is fetched from the network: CSS is
inlined and the architecture diagram is a pre-rendered SVG.
"""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import pandas as pd
from jinja2 import Environment, FileSystemLoader, StrictUndefined
from markdown_it import MarkdownIt

from plg.experiment import Readout, run_experiment
from plg.funnel import FunnelSpec, funnel
from plg.plots import experiment_ci_plot, funnel_chart, retention_heatmap, sequential_plot
from plg.render import format_readout
from plg.reports import activation_report, data_label, funnel_report
from plg.retention import retention_matrix
from plg.store import Warehouse
from plg.synthetic import GeneratorConfig, generate
from plg.validation import PeekingResult, decision_counts, peeking_simulation, summarize

REPO_URL = "https://github.com/seanmcrae/plg-metrics"
PAGES_URL = "https://seanmcrae.github.io/plg-metrics/"


@dataclass(frozen=True)
class SiteConfig:
    out_dir: Path = Path("site")
    data_dir: Path = Path("data/synthetic")
    repo_root: Path = Path()
    users: int = 20_000
    seed: int = 7
    experiment: str = "onboarding_v2"
    peeking_sims: int = 2_000

    @property
    def validation_csv(self) -> Path:
        return self.repo_root / "docs" / "validation" / "ground_truth.csv"


def ensure_dataset(cfg: SiteConfig) -> Warehouse:
    """Generate the demo dataset if absent; refuse to publish from a different config."""
    if not (cfg.data_dir / "users.parquet").exists():
        generate(GeneratorConfig(n_users=cfg.users, seed=cfg.seed)).write(cfg.data_dir)
    wh = Warehouse(cfg.data_dir)
    gen = wh.metadata.get("config", {})
    if (gen.get("n_users"), gen.get("seed")) != (cfg.users, cfg.seed):
        raise ValueError(
            f"{cfg.data_dir} was generated with n_users={gen.get('n_users')}, "
            f"seed={gen.get('seed')}; the site documents n_users={cfg.users}, seed={cfg.seed}. "
            f"Regenerate with `plg generate --out {cfg.data_dir}`."
        )
    return wh


def markdown_section(markdown: str, heading: str) -> str:
    """Body of the ``## heading`` section, up to the next level-2 heading."""
    match = re.search(rf"^## {re.escape(heading)}\n(.*?)(?=^## |\Z)", markdown, re.M | re.S)
    if match is None:
        raise ValueError(f"no '## {heading}' section found")
    return match.group(1).strip()


def render_markdown(markdown: str) -> str:
    """CommonMark plus tables; repository-relative links point at GitHub."""
    html = MarkdownIt("commonmark", {"html": False}).enable("table").render(markdown)
    return re.sub(r'href="(?!https?:|#|mailto:)([^"]+)"', rf'href="{REPO_URL}/blob/main/\1"', html)


def headline(readout: Readout, peeking: PeekingResult) -> dict[str, str]:
    """Hero figures for the landing page, formatted from the readout."""
    cfg = readout.config
    primary = readout.metric(cfg.primary.name)
    seq = readout.sequential
    naive_hits = seq.index[seq["naive_reject"]]
    msprt_hits = seq.index[seq["msprt_reject"]]
    return {
        "decision": readout.decision.split(":")[0],
        "decision_full": readout.decision,
        "primary": primary.spec.name,
        "lift_pp": f"{primary.cuped.diff * 100:+.2f} pp",
        "ci_pp": f"[{primary.cuped.ci_low * 100:+.2f}, {primary.cuped.ci_high * 100:+.2f}] pp",
        "truth_pp": f"{(primary.true_effect or 0.0) * 100:+.2f} pp",
        "baseline": f"{primary.raw.control_mean:.1%}",
        "prob_better": f"{readout.bayes.prob_treatment_better:.1%}",
        "naive_fpr": f"{peeking.naive_false_positive_rate:.1%}",
        "msprt_fpr": f"{peeking.msprt_false_positive_rate:.1%}",
        "naive_stop_look": str(int(naive_hits[0]) + 1) if len(naive_hits) else "never",
        "msprt_stop_look": str(int(msprt_hits[0]) + 1) if len(msprt_hits) else "never",
        "looks": str(len(seq)),
        "units": f"{sum(readout.srm.observed):,}",
    }


def validation_rows(csv: Path) -> tuple[list[dict[str, str]], dict[str, int], int]:
    rows = pd.read_csv(csv)
    summary = summarize(rows)
    table = [
        {
            "metric": str(r.metric),
            "true_effect": f"{r.mean_true_effect:.4f}",
            "bias": f"{r.mean_cuped_bias:+.4f}",
            "raw_coverage": f"{r.raw_coverage:.0%}",
            "cuped_coverage": f"{r.cuped_coverage:.0%}",
            "se_ratio": f"{r.mean_se_ratio:.3f}",
            "power": f"{r.power:.0%}",
        }
        for r in summary.itertuples()
    ]
    return table, decision_counts(rows), int(rows["seed"].nunique())


def _save_charts(wh: Warehouse, readout: Readout, img_dir: Path) -> list[str]:
    img_dir.mkdir(parents=True, exist_ok=True)
    figures = {
        "experiment_ci.png": experiment_ci_plot(readout),
        "sequential.png": sequential_plot(readout),
        "funnel.png": funnel_chart(funnel(wh, FunnelSpec())),
        "retention_heatmap.png": retention_heatmap(retention_matrix(wh, "bounded")),
    }
    for name, fig in figures.items():
        fig.savefig(img_dir / name, dpi=150, facecolor="white")
        plt.close(fig)
    return list(figures)


def build_site(cfg: SiteConfig) -> list[Path]:
    """Write ``index.html``, ``product.html``, images, and ``.nojekyll`` to ``cfg.out_dir``."""
    readme = (cfg.repo_root / "README.md").read_text()
    product_md = (cfg.repo_root / "docs" / "PRODUCT.md").read_text()
    architecture_svg = cfg.repo_root / "docs" / "img" / "architecture.svg"
    architecture_src = (cfg.repo_root / "docs" / "architecture.mmd").read_text()

    wh = ensure_dataset(cfg)
    readout = run_experiment(wh, cfg.experiment)
    peeking = peeking_simulation(sims=cfg.peeking_sims)
    validation, decisions, n_seeds = validation_rows(cfg.validation_csv)

    if cfg.out_dir.exists():
        shutil.rmtree(cfg.out_dir)
    img_dir = cfg.out_dir / "img"
    charts = _save_charts(wh, readout, img_dir)
    shutil.copy(architecture_svg, img_dir / "architecture.svg")

    templates = resources.files("plg.sitegen") / "templates"
    env = Environment(
        loader=FileSystemLoader(str(templates)),
        autoescape=True,
        undefined=StrictUndefined,
        keep_trailing_newline=True,
    )
    common: dict[str, Any] = {
        "repo_url": REPO_URL,
        "pages_url": PAGES_URL,
        "css": (templates / "style.css").read_text(),
        "data_label": data_label(wh),
        "users": f"{cfg.users:,}",
        "seed": cfg.seed,
    }
    pages = {
        "index.html": env.get_template("index.html").render(
            **common,
            page="index",
            h=headline(readout, peeking),
            readout_text=format_readout(readout, data_label(wh)),
            funnel_text=funnel_report(wh, FunnelSpec(), by="plan"),
            activation_text=activation_report(wh, top=6),
            validation=validation,
            decisions=decisions,
            n_seeds=n_seeds,
            peeking=peeking,
            design_html=render_markdown(markdown_section(readme, "Design decisions")),
            limitations_html=render_markdown(markdown_section(readme, "Limitations")),
            architecture_src=architecture_src,
            charts=charts,
        ),
        "product.html": env.get_template("product.html").render(
            **common, page="product", product_html=render_markdown(product_md)
        ),
    }
    written = []
    for name, html in pages.items():
        path = cfg.out_dir / name
        path.write_text(html)
        written.append(path)
    nojekyll = cfg.out_dir / ".nojekyll"
    nojekyll.touch()
    return [*written, nojekyll, *(img_dir / c for c in charts), img_dir / "architecture.svg"]
