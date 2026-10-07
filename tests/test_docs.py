from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_readme_architecture_matches_diagram_source() -> None:
    readme = (ROOT / "README.md").read_text()
    block = re.search(r"```mermaid\n(.*?)```", readme, re.S)
    assert block is not None
    assert block.group(1) == (ROOT / "docs" / "architecture.mmd").read_text()


def test_readme_images_exist() -> None:
    readme = (ROOT / "README.md").read_text()
    for path in re.findall(r"!\[[^\]]*\]\((docs/[^)]+)\)", readme):
        assert (ROOT / path).is_file(), path
