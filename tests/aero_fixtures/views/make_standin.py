# SPDX-License-Identifier: Apache-2.0
"""Make ``tests/aero_fixtures/views/standin/``: what the real ParaView draws of
the committed fixtures, which the stand-in pvbatch (``tests/_pv_standin.py``)
replays for an aero scene job. Run by hand, and by
`test_aero_views.TheRealPictures`, which holds the committed files to what
ParaView draws today::

    PYTHONPATH=src python3 tests/aero_fixtures/views/make_standin.py <out dir>

``pvbatch62`` must be the checked ParaView 6.2.0. For each scene of
``packs/aero-openfoam/views/_scene3d.py`` it runs the pack's own job
(``flow3d.job_for``) on the fixtures at `SIZE` through ``_pv.run``, and keeps
the PNG, the hero's glTF and the result (less what names this run: ``done``,
the sha256 values, ``bounds`` and ``camera``, which the stand-in fills in).

*Rejected:* the pictures at the pack's own 1600 x 1000 (1.1 MB a PNG in the
repository; the stand-in's bytes are read for what they are, never for their
size); pictures of the full L0 files (9 MB of input).
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
VIEWS = os.path.join(REPO, "packs", "aero-openfoam", "views")

#: The stand-in's pictures: small, so the repository carries little.
SIZE = (320, 200)
#: The scenes the stand-in replays, with the files each reads and its camera.
SCENES = {
    "hero": (("body", "tracksCentre", "tracksFar"), "HERO_CAMERA"),
    "surface_cp": (("body",), "BODY_CAMERA"),
    "wake": (("body", "wake"), "WAKE_CAMERA"),
    "wake_cuts": (("body", "cut1", "cut2", "cut3"), "CUTS_CAMERA"),
    "wall": (("yplus",), "BODY_CAMERA"),
}
#: The free-stream speed of the fixtures' run (the motorBike's 20 m/s).
SUMMARY = {"u_inf_m_s": 20.0, "ground_z_m": 0.0}


def flow3d():
    """``views/flow3d.py`` as a build loads it (with its ``_pv`` and
    ``_scales``): through the spine's loader into a registry of its own, so
    nothing is registered in the process's own."""
    sys.path.insert(0, os.path.join(REPO, "src"))
    from nopekit import site
    registry = site.ViewRegistry()
    site.load_viewgens(VIEWS, registry, pack="aero-openfoam", root=REPO)
    _spec, fn = registry.get("aero.hero")
    return sys.modules[fn.__module__]


def draw(scene: str, work: str) -> dict:
    """Run ``scene`` on the fixtures in ``work``: its result."""
    f3 = flow3d()
    roles, camera = SCENES[scene]
    files = {role: os.path.join(HERE, role + ".vtp") for role in roles}
    job = f3.job_for(scene, files, SUMMARY, camera=getattr(f3._scales, camera),
                     gltf="field.gltf" if scene == "hero" else "")
    job["size"] = list(SIZE)
    return f3._pv.run(f3._pv.locate(), f3.SCENE, job, work)


def main(out: str) -> None:
    os.makedirs(out, exist_ok=True)
    for scene in SCENES:
        with tempfile.TemporaryDirectory(prefix="nopekit-aero-standin-") as work:
            result = draw(scene, work)
            shutil.copyfile(os.path.join(work, "still.png"), os.path.join(out, scene + ".png"))
            if scene == "hero":
                shutil.copyfile(os.path.join(work, "field.gltf"), os.path.join(out, "hero.gltf"))
        kept = {k: v for k, v in result.items()
                if k not in ("done", "png_sha256", "gltf_sha256", "bounds", "camera")}
        with open(os.path.join(out, scene + ".json"), "w", encoding="utf-8") as fh:
            json.dump(kept, fh, indent=1, sort_keys=True)
            fh.write("\n")


if __name__ == "__main__":
    main(sys.argv[1])
