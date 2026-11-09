"""Concatenate train_edge_search.py and family_tournament.py into one Kaggle script."""

import ast
import sys
from pathlib import Path

here, dest = Path(sys.argv[1]), Path(sys.argv[2])
base = (here / "train_edge_search.py").read_text()
base = base[: base.rindex('if __name__ == "__main__":')]
tour = (here / "family_tournament.py").read_text().replace("from __future__ import annotations\n", "", 1)
combined = base + "\n\n# ---- family_tournament.py ----\n" + tour
ast.parse(combined)  # fail here, not on Kaggle
dest.write_text(combined)
print(f"wrote {dest} ({len(combined.splitlines())} lines)")
