# SPDX-License-Identifier: Apache-2.0
"""Rebuild the analytic control surfaces; run only when changing the fixture."""
from pathlib import Path
import trimesh

if __name__ == "__main__":
    root = Path(__file__).parent / "assets"
    for name, width in (("cantilever", 8.0), ("wide", 16.0)):
        part = trimesh.creation.box(extents=[40.0, width, 8.0])
        part.apply_translation([20.0, width / 2, 4.0])
        (root / (name + ".stl")).write_text("\n".join(
            line.rstrip() for line in trimesh.exchange.stl.export_stl_ascii(part).splitlines()) + "\n")
