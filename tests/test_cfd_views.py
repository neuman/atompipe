# SPDX-License-Identifier: Apache-2.0
"""cfd-openfoam's figures (GitHub #15, Phase 2): what the site draws of a CFD result.

Two charts, bound to cfd.pressure_drop's verdict entry (``packs/cfd-openfoam/
views/flow.py``): the ladder (the pressure drop on each mesh against its cell
size, the Richardson value and the GCI band) and the settling history (the change
at each iteration on each mesh, the tolerance and each estimate). They need no
tool, so they are on the page wherever the gate ran.

What these tests hold, through the stand-in OpenFOAM (``tests/_cfd_standin.py``):

- the gate writes what the pictures draw, each number its own or OpenFOAM's: the
  B.3.1 keys of ``summary.json``, OpenFOAM's own ``mag`` and ``pressure`` field
  objects in cfd.pressure_drop's ladder only (design O3), and the sha256 of the
  finest level's fields and mesh;
- each chart draws from the verified evidence alone, with no ParaView, and
  every number it holds is a number of that evidence: a chart number the
  viewgen computed would be a number no run wrote, and the spine refuses it;
- a chart holds no limit (the floor's limit and judged point are the spine's);
- on the pack's baseline wrapped as a project, ``check --tier 2`` and ``site
  build`` put both charts beside every claim the gate covers, of the served
  entry, with the claims' chips, the floor's limit and the judged point.

The pvbatch wrapper (P2.2, ``views/_pv.py``), through the stand-in pvbatch
(``tests/_pv_standin.py``) and, where it is installed, the real ParaView 6.2.0:

- a run gets an environment built from nothing, a new empty HOME outside the
  project, a timeout; a crash, a hang, a result of another job and a GL other
  than llvmpipe are refused, and stderr decides nothing;
- pvbatch62 is the build the pack's lock names (its package sha256 values, the
  pvbatch they installed, the banner); another build with the same banner is
  unavailable and named, and the environment's bypass is loud;
- the renderer control runs once a build and fails, naming the cell, on a
  renderer that clips past the scale or lights the faces;
- ``doctor`` has a pvbatch62 row and runs no control.

The stills (P2.3: ``views/_scene.py``, ``views/_scales.py``, the speed and
pressure viewgens), through the stand-in and, where both tools are installed,
the real v2606 and ParaView 6.2.0:

- each still binds the finest level's field and mesh by the summary's
  digests, and ParaView reads a copy of those files and no other; another
  run's fields, an unchecked ParaView and a failed renderer control draw
  nothing and say why; a preset other than the legend's is an error;
- the scale is the pack's constants times the summary's values, and the
  legend's stops are the preset ParaView exported (``views/viridis.json``);
- on the real tools every cell's centre pixel is the preset's colour for its
  value within 2, a value past the scale is exactly magenta, two draws are
  byte-identical, each plane's line is where the summary puts it, and a lit
  copy of the scene fails the same check.

The 3D view is P2.4.

Run:  PYTHONPATH=src python3 -m unittest discover -s tests -p test_cfd_views.py -v
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

import _env
import _projects
import _pv_standin as pv_standin
import test_cfd_openfoam as cfd_tests
from nopekit import cli, page, report, store
from nopekit import site as site_mod

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACK = os.path.join(REPO, "packs", "cfd-openfoam")
GATE = "cfd.pressure_drop"
LADDER, SETTLE = "cfd-openfoam.ladder", "cfd-openfoam.settle"
SPEED, PRESSURE = "cfd-openfoam.speed", "cfd-openfoam.pressure"
STILLS = (SPEED, PRESSURE)
#: The keys a chart may not hold: the spine's own list.
FORBIDDEN = site_mod.CHART_FORBIDDEN_KEYS


def _views() -> site_mod.ViewRegistry:
    registry = site_mod.ViewRegistry()
    cli._load_viewgens(os.path.join(PACK, "views"), registry, pack="cfd-openfoam", root=REPO)
    return registry


def _scales_mod():
    """``views/_scales.py`` as the views load it (``_pv.sibling``)."""
    _views()
    return sys.modules["nopekit_cfd_openfoam_scales"]


def _evidence_numbers(paths) -> set[float]:
    """Every number the evidence holds, read here independently of the spine's
    reader: a JSON file's leaves (no booleans), a CSV file's cells."""
    out: set[float] = set()

    def walk(node):
        if isinstance(node, bool):
            return
        if isinstance(node, (int, float)):
            out.add(float(node))
        elif isinstance(node, dict):
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)
    for path in paths:
        if path.endswith(".json"):
            with open(path, encoding="utf-8") as fh:
                walk(json.load(fh))
        elif path.endswith(".csv"):
            with open(path, encoding="utf-8", newline="") as fh:
                for row in csv.reader(fh):
                    for cell in row:
                        try:
                            out.add(float(cell))
                        except ValueError:
                            pass
    return out


def _chart_numbers(data: dict) -> list[float]:
    """Every number under the parts of a chart the spine holds to the evidence."""
    out: list[float] = []

    def walk(node):
        if isinstance(node, bool):
            return
        if isinstance(node, (int, float)):
            out.append(float(node))
        elif isinstance(node, dict):
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)
    for key in site_mod.CHART_NUMBER_KEYS:
        walk(data.get(key))
    return out


def _keys(node) -> set[str]:
    if isinstance(node, dict):
        return set(node) | {k for v in node.values() for k in _keys(v)}
    if isinstance(node, list):
        return {k for v in node for k in _keys(v)}
    return set()


def _sha256(path: str) -> str:
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


# --------------------------------------------------------------------------- #
@unittest.skipIf(os.name == "nt", "the stand-in OpenFOAM is a #! script and a bash rc")
class _OnTheStandIn(_env.EnvCase):
    """cfd.pressure_drop run once per class, in process, on the stand-in
    OpenFOAM with nothing else on PATH (no pvbatch)."""

    @classmethod
    def setUpClass(cls):
        import tempfile
        cls.dir = tempfile.mkdtemp(prefix="nopekit-test-")
        cls.inst, cls.bin = cfd_tests.install_standin(os.path.join(cls.dir, "tool"))
        cls.path = cls.bin + os.pathsep + "/usr/bin:/bin"
        cls.work = os.path.join(cls.dir, "work")
        os.makedirs(cls.work)
        with mock.patch.dict(os.environ, {"PATH": cls.path}):
            cls.verdict = cfd_tests._run(cfd_tests._registry(), GATE, cls.work,
                                         cfd_tests._baseline())
        cls.out = os.path.join(cls.work, "out", GATE.replace(".", "_"))

    @classmethod
    def tearDownClass(cls):
        _env._rmtree(cls.dir)

    def setUp(self):
        self.assertEqual(self.verdict.outcome, "pass", self.verdict.render())
        self.assertTrue(os.path.isfile(os.path.join(self.inst, "calls")),
                        "the stand-in OpenFOAM never ran")

    def summary(self) -> dict:
        path = next(p for p in self.verdict.evidence if p.endswith("summary.json"))
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)

    def context(self, *, drop: tuple[str, ...] = ()) -> site_mod.BoundContext:
        """A BoundContext over the verdict's evidence, as the spine hands it:
        ``files`` holds the verified evidence, less the base names in ``drop``
        (files the entry's manifest does not vouch for)."""
        files = {os.path.relpath(p, self.out).replace(os.sep, "/"): p
                 for p in self.verdict.evidence if os.path.basename(p) not in drop}
        entry = site_mod.BoundEntry(gate=GATE, name="0" * 16 + "-" + "0" * 8, fresh=True,
                                    files=files)
        scratch = os.path.join(self.dir, "scratch")
        os.makedirs(scratch, exist_ok=True)
        ctx = site_mod.BoundContext(root=self.work, entry=entry, scratch=scratch, view_id="")
        # What the spine sets from the entry's manifest (`site._bound_entry`).
        ctx.digests = {portable: _sha256(path) for portable, path in files.items()}
        return ctx


class TheGateWritesWhatThePicturesDraw(_OnTheStandIn):
    """B.3.1: cfd.pressure_drop's summary holds every number a figure draws,
    each the gate's or OpenFOAM's, and the digests of the fields it solved."""

    def test_the_summary_holds_the_keys_the_figures_read(self):
        s = self.summary()
        for key in ("dp_pa", "dp_ext_pa", "band_top_pa", "h_rel_ext", "u_upstream_m_s",
                    "p_up_pa", "p_down_pa", "planes", "fields"):
            self.assertIn(key, s)
        cells = [lv["cells"] for lv in s["levels"]]
        for lv in s["levels"]:
            self.assertAlmostEqual(lv["h_rel"], (cells[-1] / lv["cells"]) ** 0.5, places=12)
            self.assertAlmostEqual(lv["dp_pa"], 870.0 * lv["dp_m2_s2"], places=12)
        self.assertEqual(s["levels"][-1]["h_rel"], 1.0)
        self.assertEqual(s["levels"][-1]["dp_pa"], s["dp_pa"])
        self.assertAlmostEqual(s["p_up_pa"] - s["p_down_pa"], s["dp_pa"], places=12)
        self.assertAlmostEqual(s["u_upstream_m_s"], 0.01, places=12)
        self.assertEqual([p["normal"] for p in s["planes"]], [[1.0, 0.0, 0.0]] * 2)

    def test_the_fields_are_the_finest_levels_with_their_digests(self):
        fields = self.summary()["fields"]
        self.assertEqual(fields["stage"], "<out>/cfd-openfoam/cfd_pressure_drop/level2")
        stage = os.path.join(self.out, "cfd-openfoam", "cfd_pressure_drop", "level2")
        t = fields["time"]
        self.assertEqual(sorted(fields["sha256"]), sorted(
            [f"{t}/{n}" for n in ("U", "p", "mag(U)", "static(p)")]
            + [f"constant/polyMesh/{n}" for n in ("points", "faces", "owner", "neighbour",
                                                   "boundary")]))
        for rel, digest in fields["sha256"].items():
            self.assertEqual(_sha256(os.path.join(stage, *rel.split("/"))), digest, rel)
        # Digests only: the fields are never cited, so the site never copies them.
        self.assertFalse([p for p in self.verdict.evidence if "polyMesh" in p
                          or os.path.basename(p) in ("U", "p", "mag(U)", "static(p)")])

    def test_only_the_pressure_drop_ladder_runs_the_field_objects(self):
        """Design O3: the guards keep their two plane objects, so a density edit
        never re-keys them for a picture."""
        def control(gid, where):
            with open(os.path.join(self.work, "out", gid.replace(".", "_"), "cfd-openfoam",
                                   gid.replace(".", "_"), where, "system", "controlDict"),
                      encoding="utf-8") as fh:
                return fh.read()
        for k in range(3):
            text = control(GATE, f"level{k}")
            self.assertIn("type            mag;", text)
            self.assertIn("rhoInf          870.0;", text)
        with mock.patch.dict(os.environ, {"PATH": self.path}):
            v = cfd_tests._run(cfd_tests._registry(), "cfd.mesh_independence", self.work,
                               cfd_tests._baseline())
        self.assertEqual(v.outcome, "pass", v.render())
        text = control("cfd.mesh_independence", "level2")
        self.assertNotIn("nopekit_magU", text)
        self.assertNotIn("rhoInf", text)
        with open(next(p for p in v.evidence if p.endswith("summary.json")),
                  encoding="utf-8") as fh:
            self.assertNotIn("fields", json.load(fh))


class ChartsNeedNoTool(_OnTheStandIn):
    """Both charts draw from the verified evidence alone, with no ParaView on
    PATH, and the spine's own check of a bound chart (`_figure_refusal`) finds
    nothing to refuse."""

    def draw(self, view_id: str, **kw):
        spec, fn = _views().get(view_id)
        ctx = self.context(**kw)
        with mock.patch.dict(os.environ, {"PATH": self.path}):
            self.assertIsNone(shutil.which("pvbatch62"))
            self.assertIsNone(shutil.which("pvbatch"))
            view = fn(ctx)
        return spec, view, ctx

    def test_both_charts_draw_and_pass_the_spines_check(self):
        for view_id in (LADDER, SETTLE):
            with self.subTest(view_id):
                spec, view, ctx = self.draw(view_id)
                self.assertIsNotNone(view, ctx.notes)
                self.assertEqual((spec.evidence_of, tuple(spec.requires_tools)), (GATE, ()))
                self.assertEqual(site_mod._figure_refusal(spec, view, ctx, [0.6]), "")
                self.assertEqual(page.vega_forbidden(page.chart_spec(view.data, None, None)),
                                 [])

    def test_every_chart_number_is_in_the_evidence(self):
        held = _evidence_numbers(self.verdict.evidence)
        for view_id in (LADDER, SETTLE):
            with self.subTest(view_id):
                _spec, view, _ctx = self.draw(view_id)
                numbers = _chart_numbers(view.data)
                self.assertTrue(numbers)
                self.assertEqual([n for n in numbers if n not in held], [])

    def test_a_chart_holds_no_limit(self):
        """No limit key, and not the limit's value: cfd_dp_max_pa (0.6 Pa) is in
        the summary as limit_pa, and no chart number is it."""
        limit = self.summary()["limit_pa"]
        for view_id in (LADDER, SETTLE):
            with self.subTest(view_id):
                _spec, view, _ctx = self.draw(view_id)
                self.assertFalse(_keys(view.data) & FORBIDDEN)
                self.assertNotIn(limit, _chart_numbers(view.data))

    def test_the_ladder_draws_the_meshes_the_extrapolation_and_the_band(self):
        s = self.summary()
        _spec, view, _ctx = self.draw(LADDER)
        series = {item["key"]: item for item in view.data["series"]}
        self.assertEqual(series["meshes"]["points"],
                         [[lv["h_rel"], lv["dp_pa"]] for lv in s["levels"]])
        self.assertEqual(series["meshes"]["labels"],
                         [f"{lv['cells']} cells" for lv in s["levels"]])
        self.assertEqual(series["richardson"],
                         {"key": "richardson", "label": "zero cell size",
                          "points": [[0.0, s["dp_ext_pa"]]], "hollow": True})
        self.assertEqual(series["band_top"]["points"], [[1.0, s["band_top_pa"]]])
        self.assertEqual(view.data["band"], [{"x": 1.0, "lo": s["dp_pa"],
                                              "hi": s["band_top_pa"], "label": "GCI band"}])
        self.assertEqual(view.data["y"], {"label": "pressure drop", "units": "Pa",
                                          "zero": False})
        # The judged value (the band's top) is a series point, so the spine puts
        # the judged point at the finest mesh, not as a line across the chart.
        self.assertEqual(page._series_x(view.data, round(s["band_top_pa"], 9)), 1.0)
        current = {"x": 1.0, "y": round(s["band_top_pa"], 9), "margin_text": "13% inside"}
        spec = page.chart_spec(view.data, None, current)
        [line] = [l for l in spec["layer"] if l["mark"].get("style") == "nk-series"]
        self.assertEqual(line["encoding"]["y"]["scale"], {"zero": False})
        # The judged point's words sit above the finest mesh's "8000 cells", not
        # over it (they were drawn over each other until P2.1).
        [words] = [l for l in spec["layer"] if l["mark"].get("style") == "nk-current-label"]
        [cells] = [l for l in spec["layer"] if l["mark"].get("style") == "nk-point-label"]
        self.assertLess(words["mark"]["dy"], cells["mark"]["dy"])

    def test_the_settling_chart_draws_each_mesh_its_tolerance_and_estimates(self):
        s = self.summary()
        _spec, view, _ctx = self.draw(SETTLE)
        self.assertEqual([item["key"] for item in view.data["series"]],
                         [f"level{lv['k']}" for lv in s["levels"]])
        for item, lv in zip(view.data["series"], s["levels"]):
            path = next(p for p in self.verdict.evidence
                        if p.endswith(f"history_level{lv['k']}.csv"))
            with open(path, encoding="utf-8", newline="") as fh:
                rows = list(csv.DictReader(fh))
            # Every row with a change above zero, none other: a zero has no place
            # on a log axis, and the first row has no change.
            self.assertEqual(item["points"], [[int(r["iteration"]), float(r["change_pct"])]
                                              for r in rows if r["change_pct"]
                                              and float(r["change_pct"]) > 0])
            self.assertLess(len(item["points"]), len(rows))
        self.assertEqual(view.data["rule"], {"value": s["convergence_tol_pct"],
                                             "label": "tolerance"})
        self.assertEqual(view.data["y"]["scale"], "log")
        estimates = [(e["x"], e["y"]) for e in view.data["estimates"]]
        self.assertEqual(estimates, [(lv["converged_in"], lv["iterative_error_pct"])
                                     for lv in s["levels"] if lv["iterative_error_pct"]])

    def test_another_runs_evidence_draws_no_chart(self):
        """A file the entry's manifest does not vouch for is not in ``files``:
        no summary draws neither chart, and a missing history draws no
        settling chart (a mesh left out would read as the whole run)."""
        for view_id, drop in ((LADDER, ("summary.json",)), (SETTLE, ("summary.json",)),
                              (SETTLE, ("history_level1.csv",))):
            with self.subTest(view_id, drop=drop):
                _spec, view, ctx = self.draw(view_id, drop=drop)
                self.assertIsNone(view)
                self.assertTrue(ctx.notes and "--only cfd.pressure_drop" in ctx.notes[0],
                                ctx.notes)

    def test_a_computed_number_is_refused_by_the_spine(self):
        """The control of the evidence rule on these charts: one number the
        viewgen computed (a mean of the meshes) is refused."""
        spec, view, ctx = self.draw(LADDER)
        pts = view.data["series"][0]["points"]
        pts.append([2.5, sum(p[1] for p in pts) / len(pts)])
        self.assertIn("which no evidence file of this result holds",
                      site_mod._figure_refusal(spec, view, ctx, [0.6]))


# --------------------------------------------------------------------------- #
@unittest.skipIf(os.name == "nt", "the stand-in OpenFOAM is a #! script and a bash rc")
@unittest.skipUnless(shutil.which("git"), "the wrapped project's page is built in a repository")
class TheCfdFiguresOnTheStandIn(_env.EnvCase):
    """B.6's test: the pack's baseline wrapped as a project, the stand-in
    OpenFOAM, ``check --tier 2`` and ``site build``, first with no ParaView on
    PATH, then with the stand-in pvbatch (accepted through the environment's
    extra lock, so the page says a build this pack did not check drew the
    stills), then once more. All four figures sit beside every claim
    cfd.pressure_drop covers, each of the entry the page serves, beside the
    claims' chips: the two charts with the floor's limit and judged point,
    the two stills with their scale and the planes' marks. Without ParaView
    the stills are left out and no status moves; the third build draws
    nothing (the memo).

    The cfd gates are opaque (they read OpenFOAM through subprocesses), so the
    spine reads their entries stale once ``check`` is done, and the figures say
    the same word as the claims beside them."""

    @classmethod
    def setUpClass(cls):
        import tempfile
        cls.dir = tempfile.mkdtemp(prefix="nopekit-test-")
        cls.inst, cls.bin = cfd_tests.install_standin(os.path.join(cls.dir, "tool"))
        cls.env = {"PATH": cls.bin + os.pathsep + "/usr/bin:/bin"}
        cls.stand = pv_standin.install(os.path.join(cls.dir, "pv"))
        cls.pv_env = {"PATH": os.pathsep.join([cls.stand["bin"], cls.bin, "/usr/bin:/bin"]),
                      _pv().EXTRA_LOCK_ENV: cls.stand["extra_lock"]}
        cls.root = _projects.wrap_pack_baseline("cfd-openfoam", os.path.join(cls.dir, "proj"))
        cls.procs = [_env.nopekit(argv, cwd=cls.root, env=cls.env, timeout=900)
                     for argv in (["check", "--tier", "2"], ["site", "init"],
                                  ["site", "build", "--json"])]
        cls.before = cls.baked_file("page.json")
        cls.procs.append(_env.nopekit(["site", "build", "--json"], cwd=cls.root,
                                      env=cls.pv_env, timeout=900))
        cls.scenes = len(cls.scene_calls())
        cls.again = _env.nopekit(["site", "build", "--json"], cwd=cls.root, env=cls.pv_env,
                                 timeout=900)

    @classmethod
    def tearDownClass(cls):
        _env._rmtree(cls.dir)

    @classmethod
    def baked_file(cls, name: str) -> dict:
        with open(os.path.join(cls.root, "site", "data", name), encoding="utf-8") as fh:
            return json.load(fh)

    @classmethod
    def scene_calls(cls) -> list[dict]:
        return [c for c in pv_standin.calls(cls.stand["prefix"]) if "case_files" in c]

    def setUp(self):
        for proc in [*self.procs, self.again]:
            self.assertEqual(proc.returncode, 0, proc.stdout[-3000:] + proc.stderr[-3000:])
        self.assertTrue(os.path.isfile(os.path.join(self.inst, "calls")),
                        "the stand-in OpenFOAM never ran")
        self.assertTrue(self.scenes, "the stand-in pvbatch never drew a still")

    def baked(self, name: str) -> dict:
        return self.baked_file(name)

    def served_entry(self) -> str:
        names = [n[:-len(".json")] for n in os.listdir(
            os.path.join(self.root, ".nopekit", "verdicts", GATE))
            if n.endswith(".json") and not n.startswith("control-")]
        self.assertEqual(len(names), 1, names)
        return names[0]

    def summary(self) -> dict:
        folder = os.path.join(self.root, "site", "assets", "evidence", GATE,
                              self.served_entry())
        with open(os.path.join(folder, "summary.json"), encoding="utf-8") as fh:
            return json.load(fh)

    def test_four_figures_beside_every_claim_the_gate_covers(self):
        doc = self.baked("page.json")
        entry = self.served_entry()
        covered = sorted(doc["claims"])
        self.assertEqual(covered, [f"G{n}" for n in range(1, 7)])
        chips = [{"id": cid, "token": doc["claims"][cid]["token"]} for cid in covered]
        for cid in covered:
            figs = {f["view"]: f for f in doc["claims"][cid].get("figures") or ()}
            self.assertEqual(sorted(figs), sorted([LADDER, SETTLE, *STILLS]), cid)
            for view_id, fig in figs.items():
                with self.subTest(cid=cid, view=view_id):
                    self.assertEqual((fig["gate"], fig["entry"], fig["kind"]),
                                     (GATE, entry, "image" if view_id in STILLS else "chart"))
                    # Opaque gates: the served entry reads stale, and so do the
                    # claims and the figures (the class docstring).
                    self.assertEqual((fig["currency"], doc["claims"][cid]["token"]),
                                     ("stale", "stale"))
                    self.assertEqual([{"id": c["id"], "token": c["token"]}
                                      for c in fig["claims"]], chips)
                    src = fig["src"] if view_id in STILLS else fig["data_src"]
                    self.assertTrue(src.startswith(f"assets/figures/{GATE}/{entry}/"), src)
                    self.assertTrue(os.path.isfile(
                        os.path.join(self.root, "site", *src.split("/"))))
                    if view_id not in STILLS:
                        self.assertEqual(page.vega_forbidden(fig["chart"]["spec"]), [])
        summary = json.loads(self.procs[3].stdout)
        self.assertEqual({(v["view"], v["entry"]) for v in summary["viewgens"]},
                         {(v, entry) for v in (LADDER, SETTLE, *STILLS)})

    def test_each_still_is_the_stand_ins_bytes_with_its_scale_and_marks(self):
        doc = self.baked("page.json")
        summary = self.summary()
        scales = _scales_mod()
        for view_id, png in ((SPEED, pv_standin.SPEED_PNG), (PRESSURE, pv_standin.PRESSURE_PNG)):
            with self.subTest(view_id):
                fig = next(f for f in doc["claims"]["G6"]["figures"] if f["view"] == view_id)
                with open(os.path.join(self.root, "site", *fig["src"].split("/")), "rb") as fh:
                    published = fh.read()
                self.assertEqual(published, png)
                self.assertEqual(fig["sha256"], hashlib.sha256(png).hexdigest())
                scale = fig["scale"]
                for end in ("lo", "hi"):
                    self.assertAlmostEqual(scale[end], sum(
                        s[end] * summary[s["key"]] for s in scale["source"]), places=12)
                self.assertEqual(scale["stops"], scales.stops())
                self.assertEqual(scale["over"], "#ff00ff")
                self.assertEqual([m["text"] for m in fig["marks"]],
                                 ["upstream plane", "downstream plane"])
                self.assertEqual([m["at"] for m in fig["marks"]], pv_standin.STILL_MARKS)
                # The stand-in is accepted through the environment: loud, in
                # the spine's words (the sidecar's ``tool.accepted_by``).
                self.assertEqual(fig["tool_word"],
                                 report.HUMAN["site"]["figure"]["tool_unchecked"])
                self.assertEqual(fig["chart"], {})
        speed = next(f for f in doc["claims"]["G6"]["figures"] if f["view"] == SPEED)
        self.assertAlmostEqual(speed["scale"]["hi"], 2.0 * summary["u_upstream_m_s"], places=12)

    def test_paraview_reads_only_the_bound_files(self):
        summary = self.summary()
        time = summary["fields"]["time"]
        for call in self.scene_calls():
            field = call["job"]["field"]
            with self.subTest(field):
                self.assertEqual(call["case_files"], sorted(
                    [f"{time}/{field}", "system/controlDict",
                     *(f"constant/polyMesh/{n}" for n in
                       ("points", "faces", "owner", "neighbour", "boundary"))]))
                case = os.path.realpath(call["job"]["case"])
                self.assertFalse(case.startswith(os.path.realpath(self.root) + os.sep), case)
                self.assertFalse(os.path.exists(case), "the copy outlived the draw")

    def test_without_paraview_the_stills_are_left_out_and_no_status_moves(self):
        after = self.baked("page.json")
        for cid, claim in self.before["claims"].items():
            self.assertEqual(claim["token"], after["claims"][cid]["token"], cid)
            figs = {f["view"]: f for f in claim.get("figures") or ()}
            for view_id in STILLS:
                with self.subTest(cid=cid, view=view_id):
                    self.assertEqual((figs[view_id]["currency"], figs[view_id]["src"]),
                                     ("none", ""))
        notes = {v["view"]: v for v in json.loads(self.procs[2].stdout)["viewgens"]}
        for view_id in STILLS:
            self.assertEqual(notes[view_id]["status"], "unavailable", notes[view_id])

    def test_a_build_that_judged_nothing_new_draws_nothing(self):
        self.assertEqual(len(self.scene_calls()), self.scenes)
        self.assertEqual(self.baked("page.json"), self.baked_file("page.json"))
        notes = {v["view"]: v["status"] for v in json.loads(self.again.stdout)["viewgens"]}
        self.assertEqual({notes[v] for v in STILLS}, {"memo"})

    def test_the_ladder_carries_the_floors_limit_and_judged_point(self):
        doc = self.baked("page.json")
        with open(os.path.join(self.root, ".nopekit", "verdicts", GATE,
                               self.served_entry() + ".json"), encoding="utf-8") as fh:
            verdict = json.load(fh)["verdict"]
        fig = next(f for f in doc["claims"]["G5"]["figures"] if f["view"] == LADDER)
        self.assertEqual(fig["chart"]["limit"]["value"], verdict["limit"])
        self.assertEqual((fig["chart"]["current"]["x"], fig["chart"]["current"]["y"]),
                         (1.0, verdict["measured"]))
        settle = next(f for f in doc["claims"]["G5"]["figures"] if f["view"] == SETTLE)
        # Its y axis is a percentage: no limit line and no judged point.
        self.assertEqual((settle["chart"]["limit"], settle["chart"]["current"]), (None, None))

    def test_every_published_chart_number_is_in_the_published_evidence(self):
        doc = self.baked("page.json")
        entry = self.served_entry()
        folder = os.path.join(self.root, "site", "assets", "evidence", GATE, entry)
        published = [os.path.join(folder, n) for n in os.listdir(folder)]
        held = _evidence_numbers(published)
        for fig in doc["claims"]["G5"]["figures"]:
            if fig["kind"] != "chart":
                continue
            with self.subTest(fig["view"]):
                with open(os.path.join(self.root, "site", *fig["data_src"].split("/")),
                          encoding="utf-8") as fh:
                    data = json.load(fh)
                numbers = _chart_numbers(data)
                self.assertTrue(numbers)
                self.assertEqual([n for n in numbers if n not in held], [])


# --------------------------------------------------------------------------- #
# P2.2: the pvbatch wrapper (views/_pv.py)
# --------------------------------------------------------------------------- #
def _pv():
    """``views/_pv.py`` as flow.py loads it: one module under one name, so
    the tests and the views share its identity cache."""
    name = "nopekit_cfd_openfoam_pv"
    if name not in sys.modules:
        _views()                         # flow.py loads it
    return sys.modules[name]


@unittest.skipIf(os.name == "nt", "the stand-in pvbatch is a #! script")
class _OnTheStandInPvbatch(_env.EnvCase):
    """The stand-in pvbatch (``tests/_pv_standin.py``) behind its own
    ``pvbatch62`` launcher, alone on PATH, accepted through the environment's
    extra lock (the class that holds the identity unsets it)."""

    def setUp(self):
        super().setUp()
        self.pv = _pv()
        self.pv._identity.cache_clear()
        self.addCleanup(self.pv._identity.cache_clear)
        self.dir = self.tmp()
        self.stand = pv_standin.install(self.dir)
        self.prefix = self.stand["prefix"]
        self.root = os.path.join(self.dir, "proj")
        os.makedirs(self.root)
        self.env = {"PATH": self.stand["bin"] + os.pathsep + "/usr/bin:/bin",
                    self.pv.EXTRA_LOCK_ENV: self.stand["extra_lock"]}

    def environ(self, **changes):
        env = dict(self.env)
        env.update(changes)
        patch = mock.patch.dict(os.environ, {k: v for k, v in env.items() if v is not None})
        patch.start()
        self.addCleanup(patch.stop)
        for key, value in env.items():
            if value is None:
                os.environ.pop(key, None)

    def mode(self, mode: str, **kw) -> None:
        pv_standin.set_mode(self.prefix, mode, **kw)

    def jobs(self) -> list[dict]:
        """The stand-in's calls that ran a script (not ``--version``)."""
        return [c for c in pv_standin.calls(self.prefix) if c["argv"] != ["--version"]]

    def control(self, *, timeout: float = 60):
        self.environ()
        inst = self.pv.locate()
        return self.pv.control(inst, self.pv.cache_dir(self.root), timeout=timeout)


class PvbatchRunsInAScrubbedWorld(_OnTheStandInPvbatch):
    """B.3.2: pvbatch runs in an environment built from nothing, with a new
    empty HOME outside the project each time, under a timeout; a crash, a
    result of another job and a GL other than llvmpipe are refused, and stderr
    decides nothing."""

    def test_the_environment_is_exactly_the_listed_keys(self):
        self.environ(PYTHONPATH="/somewhere/src", LD_LIBRARY_PATH="/opt/lib", DISPLAY=":0")
        self.control()
        calls = self.jobs()
        self.assertEqual(len(calls), 1, "the stand-in pvbatch never ran the control")
        env = calls[0]["env"]
        self.assertEqual(sorted(env), sorted(self.pv.environment("x")))
        self.assertEqual({k: v for k, v in env.items() if k != "HOME"},
                         {k: v for k, v in self.pv.environment("x").items() if k != "HOME"})
        for key in ("PYTHONPATH", "LD_LIBRARY_PATH", "DISPLAY", self.pv.EXTRA_LOCK_ENV):
            self.assertNotIn(key, env)
        self.assertEqual((env["PYTHONNOUSERSITE"], env["GALLIUM_DRIVER"],
                          env["LIBGL_ALWAYS_SOFTWARE"]), ("1", "llvmpipe", "1"))
        self.assertEqual(calls[0]["argv"][0], "--force-offscreen-rendering")
        self.assertEqual(calls[0]["argv"][1], self.pv.CONTROL_SCRIPT)

    def test_home_is_new_empty_and_outside_the_project_each_run(self):
        self.mode("dirty-home")
        self.environ()
        inst = self.pv.locate()
        for _ in range(2):
            with tempfile.TemporaryDirectory() as work:
                self.pv.run(inst, self.pv.CONTROL_SCRIPT, self.pv.control_job(), work)
        homes = [(c["env"]["HOME"], c["home_held"]) for c in self.jobs()]
        self.assertEqual(len(homes), 2, "the stand-in pvbatch never ran")
        self.assertEqual([held for _, held in homes], [[], []],
                         "a run saw what an earlier run left in its HOME")
        self.assertNotEqual(homes[0][0], homes[1][0])
        for home, _ in homes:
            self.assertFalse(os.path.exists(home), f"{home} outlived its run")
            self.assertFalse(os.path.realpath(home).startswith(os.path.realpath(self.root)))
        self.assertEqual(os.listdir(self.root), [], "a run wrote into the project")

    def test_a_hang_is_unavailable_and_is_not_kept(self):
        self.mode("hang")
        with self.assertRaises(self.pv.Unavailable) as caught:
            self.control(timeout=2)
        self.assertIn("ran past 2 s and was killed", str(caught.exception))
        self.assertEqual(len(self.jobs()), 1, "the stand-in pvbatch never ran")
        self.assertFalse(os.path.isdir(self.pv.cache_dir(self.root)),
                         "a run that did not finish was kept as the control's outcome")

    def test_sigabrt_is_named(self):
        self.mode("sigabrt")
        with self.assertRaises(self.pv.RunError) as caught:
            self.control()
        self.assertIn("SIGABRT", str(caught.exception))
        self.assertIn("PYTHONNOUSERSITE", str(caught.exception))
        self.assertEqual(len(self.jobs()), 1, "the stand-in pvbatch never ran")

    def test_a_crash_is_an_error_that_quotes_its_last_line(self):
        self.mode("crash")
        with self.assertRaises(self.pv.RunError) as caught:
            self.control()
        self.assertIn("exited 1", str(caught.exception))
        self.assertIn("no preset with name Viridis", str(caught.exception))

    def test_stderr_noise_is_no_error(self):
        self.mode("noise")
        rec = self.control()
        self.assertTrue(rec["ok"], rec["problems"])
        self.assertEqual(len(self.jobs()), 1, "the stand-in pvbatch never ran")

    def test_a_result_of_another_job_is_refused(self):
        self.mode("no-done")
        with self.assertRaises(self.pv.RunError) as caught:
            self.control()
        self.assertIn("not this job's", str(caught.exception))

    def test_no_result_is_refused(self):
        self.mode("no-result")
        with self.assertRaises(self.pv.RunError) as caught:
            self.control()
        self.assertIn("wrote no result.json", str(caught.exception))

    def test_another_gl_is_refused(self):
        self.mode("gpu")
        with self.assertRaises(self.pv.RunError) as caught:
            self.control()
        self.assertIn("D3D12", str(caught.exception))
        self.assertIn("not llvmpipe", str(caught.exception))
        self.assertEqual(len(self.jobs()), 1, "the stand-in pvbatch never ran")


class ToolIdentityIsTheBuild(_OnTheStandInPvbatch):
    """W14: pvbatch62 is the ParaView build the pack's lock names, by the
    sha256 of its packages and of the pvbatch they installed, and its banner
    agrees. Another build with the same banner is unavailable, named; the
    environment's extra lock is the one bypass, and it is loud."""

    def test_an_unchecked_build_with_the_same_banner_is_unavailable_and_named(self):
        self.environ(**{self.pv.EXTRA_LOCK_ENV: None})
        with self.assertRaises(self.pv.Unavailable) as caught:
            self.pv.locate()
        said = str(caught.exception)
        sha12 = self.stand["packages"]["paraview"][:12]
        self.assertIn(f"pvbatch62 is ParaView build paraview-6.2.0-py312ha24fc4a_1:{sha12}, "
                      f"which this pack did not check", said)
        ok, words = self.pv.doctor_check(self.root)
        self.assertFalse(ok)
        self.assertIn("which this pack did not check", words)
        self.assertIn(self.pv.NO_PICTURES, words)

    def test_the_locked_packages_with_another_pvbatch_are_refused(self):
        """The records say the build is the locked one; the pvbatch on disk is
        not the file that package installed."""
        with open(self.pv.LOCK, encoding="utf-8") as fh:
            locked = json.load(fh)["accepted"][0]["packages"]
        other = pv_standin.install(os.path.join(self.dir, "relabelled"), packages=locked)
        self.environ(PATH=other["bin"] + os.pathsep + "/usr/bin:/bin",
                     **{self.pv.EXTRA_LOCK_ENV: None})
        pvbatch = os.path.join(other["prefix"], "bin", "pvbatch")
        with open(pvbatch, "a", encoding="utf-8") as fh:
            fh.write("# edited after the install\n")
        with self.assertRaises(self.pv.Unavailable) as caught:
            self.pv.locate()
        self.assertIn("is not the file the paraview-6.2.0-py312ha24fc4a_1 package installed",
                      str(caught.exception))

    def test_the_banner_must_say_the_locked_version(self):
        self.mode("ok", banner="paraview version 6.1.0")
        self.environ()
        with self.assertRaises(self.pv.Unavailable) as caught:
            self.pv.locate()
        self.assertIn("not paraview version 6.2.0", str(caught.exception))
        self.assertEqual([c["argv"] for c in pv_standin.calls(self.prefix)], [["--version"]])

    def test_the_bypass_is_loud(self):
        self.environ()
        inst = self.pv.locate()
        self.assertEqual(inst.accepted_by, "environment")
        self.assertEqual(inst.tool_word, self.pv.UNCHECKED_WORD)
        self.assertEqual(inst.identity,
                         f"paraview-6.2.0-py312ha24fc4a_1:{self.stand['packages']['paraview'][:12]}")
        rec = self.pv.control(inst, self.pv.cache_dir(self.root))
        self.assertEqual(rec["accepted_by"], "environment")
        ok, words = self.pv.doctor_check(self.root)
        self.assertTrue(ok, words)
        self.assertIn(f"accepted through {self.pv.EXTRA_LOCK_ENV}: a build this pack did not "
                      f"check", words)

    def test_the_lock_names_every_locked_package(self):
        with open(self.pv.LOCK, encoding="utf-8") as fh:
            lock = json.load(fh)
        for entry in lock["accepted"]:
            self.assertEqual(sorted(entry["packages"]), sorted(self.pv.LOCKED_PACKAGES))
            for sha in entry["packages"].values():
                self.assertRegex(sha, r"^[0-9a-f]{64}$")

    def test_the_launcher_names_the_prefix_and_nothing_else(self):
        launcher = os.path.join(self.stand["bin"], "pvbatch62")
        self.assertEqual(self.pv.prefix_from_wrapper(launcher), self.prefix)
        bare = os.path.join(self.dir, "bare")
        with open(bare, "w", encoding="utf-8") as fh:
            fh.write("#!/bin/sh\n# PATH=/opt/pv/bin:/usr/bin\nexec pvbatch \"$@\"\n")
        self.assertIsNone(self.pv.prefix_from_wrapper(bare))

    def test_nothing_on_path_is_unavailable_and_says_no_status_moves(self):
        self.environ(PATH="/usr/bin:/bin")
        with self.assertRaises(self.pv.Unavailable):
            self.pv.locate()
        ok, words = self.pv.doctor_check(self.root)
        self.assertEqual((ok, words), (False, f"not found. {self.pv.NO_PICTURES} "
                                              f"{self.pv.SEE}"))


class TheRendererControlRuns(_OnTheStandInPvbatch):
    """W10: the renderer control draws the strip once per build (and per
    control script and fixture), and it is judged in nopekit from the pixels
    and the lookup table's colours the run reported. A renderer that clips a
    value past the scale or lights the faces fails, naming the cell, and
    then no pvbatch picture is drawn."""

    def test_ok_passes_and_runs_once_per_identity(self):
        self.environ()
        first = self.pv.ready(self.root)
        second = self.pv.ready(self.root)
        self.assertEqual(first, second)
        self.assertEqual(len(self.jobs()), 1, "the control ran again for the same build")
        kept = os.listdir(self.pv.cache_dir(self.root))
        self.assertEqual(len(kept), 1, kept)
        with open(os.path.join(self.pv.cache_dir(self.root), kept[0]), encoding="utf-8") as fh:
            rec = json.load(fh)
        self.assertEqual((rec["ok"], rec["problems"], rec["identity"]),
                         (True, [], first.identity))
        ok, words = self.pv.doctor_check(self.root)
        self.assertTrue(ok)
        self.assertTrue(words.endswith(", checked"), words)

    def test_the_control_is_keyed_on_the_build_not_the_path(self):
        self.environ()
        self.pv.ready(self.root)

        def jobs(stand):
            return [c for c in pv_standin.calls(stand["prefix"]) if c["argv"] != ["--version"]]
        # The same packages at another path: the same build, not drawn again.
        same = pv_standin.install(os.path.join(self.dir, "same"))
        self.environ(PATH=same["bin"] + os.pathsep + "/usr/bin:/bin",
                     **{self.pv.EXTRA_LOCK_ENV: same["extra_lock"]})
        self.pv.ready(self.root)
        self.assertEqual(jobs(same), [], "the control ran again for the same build")
        # Another paraview package: another build, with a control of its own.
        other = pv_standin.install(os.path.join(self.dir, "other"),
                                   packages={"paraview": "f" * 64})
        self.environ(PATH=other["bin"] + os.pathsep + "/usr/bin:/bin",
                     **{self.pv.EXTRA_LOCK_ENV: other["extra_lock"]})
        self.pv.ready(self.root)
        self.assertEqual(len(jobs(other)), 1, "another build was served this build's control")
        self.assertEqual(len(os.listdir(self.pv.cache_dir(self.root))), 2)

    def test_a_renderer_that_clips_past_the_scale_fails_and_names_the_cell(self):
        self.mode("no-overrange")
        self.environ()
        with self.assertRaises(self.pv.Unavailable) as caught:
            self.pv.ready(self.root)
        said = str(caught.exception)
        self.assertIn("renderer control failed", said)
        self.assertIn("cell 13 (t = 1.1), above the scale: drew (253, 231, 37)", said)
        self.assertIn("cell 0 (t = -0.2), below the scale", said)
        self.assertEqual(len(self.jobs()), 1, "the stand-in pvbatch never ran")
        # Judged, so kept: the next build does not draw it again, and still refuses.
        with self.assertRaises(self.pv.Unavailable):
            self.pv.ready(self.root)
        self.assertEqual(len(self.jobs()), 1)
        ok, words = self.pv.doctor_check(self.root)
        self.assertFalse(ok)
        self.assertIn("renderer control failed", words)

    def test_a_lit_renderer_fails(self):
        self.mode("lit")
        self.environ()
        with self.assertRaises(self.pv.Unavailable) as caught:
            self.pv.ready(self.root)
        self.assertIn("cell 7 (t = 0.5): drew (26, 111, 104), the scale's colour is "
                      "(33, 144, 140)", str(caught.exception))

    def test_the_judge_refuses_a_report_that_leaves_cells_out(self):
        good = [{"index": i, "value": v, "where": w, "pixel": list(p), "want": list(q)}
                for i, v, w, p, q in pv_standin.CELLS]
        self.assertEqual(self.pv.judge_control({"cells": good}), [])
        no_above = [c for c in good if c["where"] != "above"]
        self.assertIn("the control reported no cell above the scale",
                      self.pv.judge_control({"cells": no_above}))
        no_known = [c for c in good if c["value"] != 0.5]
        self.assertIn("the control reported no cell at t = 0.5",
                      self.pv.judge_control({"cells": no_known}))
        other_map = [dict(c, want=[c["pixel"][2], c["pixel"][1], c["pixel"][0]],
                          pixel=[c["pixel"][2], c["pixel"][1], c["pixel"][0]])
                     if c["where"] == "in" else c for c in good]
        self.assertTrue(any("not viridis's" in p
                            for p in self.pv.judge_control({"cells": other_map})))
        self.assertEqual(self.pv.judge_control({}), ["the control reported no cells"])


@unittest.skipIf(os.name == "nt", "the stand-in pvbatch is a #! script")
class ViewToolsInDoctor(_env.EnvCase):
    """B.7: ``nopekit doctor`` has a row for each tool the views draw with,
    from the pack's own check: pvbatch62 found and checked, or not found with
    the words that no status depends on the pictures. It runs no control."""

    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp(prefix="nopekit-test-")
        cls.root = _projects.wrap_pack_baseline("cfd-openfoam", os.path.join(cls.dir, "proj"))
        cls.stand = pv_standin.install(os.path.join(cls.dir, "pv"))

    @classmethod
    def tearDownClass(cls):
        _env._rmtree(cls.dir)

    def doctor(self, env: dict) -> str:
        proc = _env.nopekit(["doctor"], cwd=self.root, env=env, timeout=600)
        return proc.stdout + proc.stderr

    def row(self, out: str) -> str:
        rows = [ln for ln in out.splitlines() if "pvbatch62" in ln]
        self.assertEqual(len(rows), 1, out[-3000:])
        return rows[0]

    def test_not_found_says_no_status_depends_on_the_pictures(self):
        row = self.row(self.doctor({"PATH": "/usr/bin:/bin"}))
        self.assertIn("pvbatch62: not found. The CFD pictures are not drawn. No status "
                      "depends on them.", row)

    def test_found_names_the_build_and_runs_no_control(self):
        env = {"PATH": self.stand["bin"] + os.pathsep + "/usr/bin:/bin",
               "NOPEKIT_PVBATCH_EXTRA_LOCK": self.stand["extra_lock"]}
        row = self.row(self.doctor(env))
        self.assertIn("pvbatch62: found, paraview-6.2.0-py312ha24fc4a_1, accepted through "
                      "NOPEKIT_PVBATCH_EXTRA_LOCK", row)
        self.assertIn("its renderer control has not run in this project", row)
        self.assertEqual({tuple(c["argv"]) for c in pv_standin.calls(self.stand["prefix"])},
                         {("--version",)}, "doctor ran more than the banner")

    def test_a_view_tool_with_no_check_reads_found_or_not(self):
        registry = site_mod.ViewRegistry()

        @site_mod.viewgen(id="probe.view", kind="chart", registry=registry,
                          requires_tools=["nopekit-no-such-tool-6b1e"])
        def probe(ctx):                   # pragma: no cover - never called
            return None

        def boom(root):
            raise RuntimeError("the check broke")
        registry.add_tool_check("nopekit-checked-tool-6b1e", boom, pack="probe")
        rows = site_mod.view_tool_rows(registry, self.root)
        self.assertEqual(rows[0], (False, "nopekit-no-such-tool-6b1e: not on PATH. These views "
                                          "are not drawn: probe.view. No status depends on "
                                          "them."))
        self.assertFalse(rows[1][0])
        self.assertIn("raised RuntimeError: the check broke", rows[1][1])
        self.assertEqual(site_mod.view_tool_rows(registry, self.root,
                                                 skip=["nopekit-no-such-tool-6b1e",
                                                       "nopekit-checked-tool-6b1e"]), [])


class TheRealRendererControl(_env.EnvCase):
    """W10 on the real ParaView 6.2.0: the renderer control passes, two runs
    write byte-identical PNGs, and the control fails on a lit display and on
    a lookup table with no above-range colour, the two faults it exists to
    catch (planted in copies of the control script). Not walked, and says
    so, where pvbatch62 is not the checked build."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if os.name == "nt" or not shutil.which("pvbatch62"):
            raise unittest.SkipTest("not walked: pvbatch62 is not on PATH")
        pv = _pv()
        try:
            cls.inst = pv.locate()
        except pv.Unavailable as exc:
            raise unittest.SkipTest(f"not walked: {exc}")

    def setUp(self):
        super().setUp()
        self.pv = _pv()

    def run_script(self, edit=None) -> dict:
        work = self.tmp()
        script = self.pv.CONTROL_SCRIPT
        if edit is not None:
            with open(script, encoding="utf-8") as fh:
                text = fh.read()
            for old, new in edit:
                self.assertIn(old, text)
                text = text.replace(old, new)
            script = os.path.join(work, "planted_control.py")
            with open(script, "w", encoding="utf-8") as fh:
                fh.write(text)
        return self.pv.run(self.inst, script, self.pv.control_job(), os.path.join(work, "job"))

    def test_the_control_passes_and_is_byte_identical(self):
        first, second = self.run_script(), self.run_script()
        self.assertEqual(self.pv.judge_control(first), [])
        self.assertIn("llvmpipe", first["gl_renderer"])
        self.assertEqual(first["png_sha256"], second["png_sha256"])
        self.assertEqual(first["cells"], second["cells"])

    def test_a_lit_display_fails(self):
        result = self.run_script([("display.Ambient = 1.0", "display.Ambient = 0.0"),
                                  ("display.Diffuse = 0.0", "display.Diffuse = 1.0")])
        problems = self.pv.judge_control(result)
        self.assertTrue(any("a lit or tinted display" in p for p in problems), problems)

    def test_no_above_range_colour_fails(self):
        result = self.run_script([("lut.UseAboveRangeColor = 1", "lut.UseAboveRangeColor = 0")])
        problems = self.pv.judge_control(result)
        self.assertTrue(any("above the scale" in p and "clips" in p for p in problems),
                        problems)

    def test_ready_runs_the_control_once(self):
        root = self.tmp()
        self.assertEqual(self.pv.ready(root), self.inst)
        kept = os.listdir(self.pv.cache_dir(root))
        self.assertEqual(len(kept), 1)
        ok, words = self.pv.doctor_check(root)
        self.assertEqual((ok, words), (True, f"found, {self.inst.name}, checked"))



# --------------------------------------------------------------------------- #
# P2.3: the stills (views/_scene.py, views/_scales.py, flow.py)
# --------------------------------------------------------------------------- #
def _run_in_project(root: str, path: str):
    """cfd.pressure_drop on the baseline with ``root``'s ``.nopekit/out`` as
    its out directory, as ``check`` runs it: the summary's ``<out>/...`` stage
    is then where ``BoundContext.bind`` looks."""
    from nopekit import gates as gates_mod
    from nopekit.models import Ledger, ProjectMeta
    registry = cfd_tests._registry()
    spec_fn = registry.get(GATE)
    ctx = gates_mod.GateContext(
        root=root, ledger=Ledger(meta=ProjectMeta(name="cfd")), model=None,
        params=dict(cfd_tests._baseline()), out_dir=store.out_dir(root), tier=2,
        log=lambda _m: None, extra={})
    with mock.patch.dict(os.environ, {"PATH": path}):
        return gates_mod.run_gate(*spec_fn, ctx)


def _bound_context(root: str, verdict, view_id: str, scratch: str) -> site_mod.BoundContext:
    """The BoundContext the spine hands a bound viewgen for ``verdict``'s
    entry: its evidence as ``files``, their digests set (`site._bound_entry`)."""
    out = store.out_dir(root)
    files = {os.path.relpath(p, out).replace(os.sep, "/"): p for p in verdict.evidence}
    entry = site_mod.BoundEntry(gate=GATE, name="0" * 16 + "-" + "0" * 8, fresh=True,
                                files=files)
    shutil.rmtree(scratch, ignore_errors=True)
    os.makedirs(scratch)
    ctx = site_mod.BoundContext(root=root, entry=entry, scratch=scratch, view_id=view_id)
    ctx.digests = {portable: _sha256(path) for portable, path in files.items()}
    return ctx


def _summary_of(verdict) -> dict:
    path = next(p for p in verdict.evidence if p.endswith("summary.json"))
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


@unittest.skipIf(os.name == "nt", "the stand-ins are #! scripts")
class TheStillsOnTheStandIn(_env.EnvCase):
    """The speed and pressure viewgens through both stand-ins: the gate run
    once per class into a project's ``.nopekit/out``, then each still drawn
    by the stand-in pvbatch from a BoundContext as the spine builds it. What
    is held here is the pack's path to a picture, not the pixels (those are
    `TheRealStills`): what is bound, what is left out and why, and what is
    an error."""

    @classmethod
    def setUpClass(cls):
        import tempfile
        cls.dir = tempfile.mkdtemp(prefix="nopekit-test-")
        cls.foam, foam_bin = cfd_tests.install_standin(os.path.join(cls.dir, "tool"))
        cls.foam_path = foam_bin + os.pathsep + "/usr/bin:/bin"
        cls.root = os.path.join(cls.dir, "proj")
        os.makedirs(cls.root)
        cls.verdict = _run_in_project(cls.root, cls.foam_path)

    @classmethod
    def tearDownClass(cls):
        _env._rmtree(cls.dir)

    def setUp(self):
        super().setUp()
        self.assertEqual(self.verdict.outcome, "pass", self.verdict.render())
        self.pv = _pv()
        self.pv._identity.cache_clear()
        self.addCleanup(self.pv._identity.cache_clear)
        shutil.rmtree(self.pv.cache_dir(self.root), ignore_errors=True)
        self.stand = pv_standin.install(self.tmp())
        self.environ(**{"PATH": self.stand["bin"] + os.pathsep + self.foam_path,
                        self.pv.EXTRA_LOCK_ENV: self.stand["extra_lock"]})

    def environ(self, **env):
        patch = mock.patch.dict(os.environ, {k: v for k, v in env.items() if v is not None})
        patch.start()
        self.addCleanup(patch.stop)
        for key, value in env.items():
            if value is None:
                os.environ.pop(key, None)

    def draw(self, view_id: str):
        spec, fn = _views().get(view_id)
        ctx = _bound_context(self.root, self.verdict, view_id, os.path.join(self.dir, "scratch"))
        view, note = site_mod.run_viewgen(spec, fn, ctx)
        return spec, view, note, ctx

    def scenes(self) -> list[dict]:
        return [c for c in pv_standin.calls(self.stand["prefix"]) if "case_files" in c]

    def test_both_stills_draw_and_pass_the_spines_check(self):
        for view_id, png in ((SPEED, pv_standin.SPEED_PNG), (PRESSURE, pv_standin.PRESSURE_PNG)):
            with self.subTest(view_id):
                spec, view, note, ctx = self.draw(view_id)
                self.assertIsNotNone(view, note + "; ".join(ctx.notes))
                self.assertEqual(site_mod._figure_refusal(spec, view, ctx,
                                                          [self.verdict.limit]), "")
                self.assertEqual(list(ctx.outputs), [view.src])
                with open(ctx.outputs[view.src][0], "rb") as fh:
                    self.assertEqual(fh.read(), png)
                self.assertEqual(spec.requires_tools, ("pvbatch62",))
                self.assertEqual(spec.recipe, ("views/_scene.py", "views/_scales.py",
                                               "views/viridis.json"))
                self.assertEqual(view.meta["tool"]["accepted_by"], "environment")
                self.assertEqual(page.caption_status(view.meta["caption"]), "")
        self.assertEqual([c["job"]["field"] for c in self.scenes()], ["mag(U)", "static(p)"])

    def test_the_job_is_the_scale_and_the_pack_constants(self):
        _spec, view, _note, _ctx = self.draw(PRESSURE)
        scales = _scales_mod()
        job = self.scenes()[-1]["job"]
        summary = _summary_of(self.verdict)
        dp = summary["p_up_pa"] - summary["p_down_pa"]
        self.assertAlmostEqual(job["range"][0], summary["p_down_pa"] - dp, places=12)
        self.assertAlmostEqual(job["range"][1], summary["p_down_pa"] + 2 * dp, places=12)
        self.assertEqual(job["range"], [view.meta["scale"]["lo"], view.meta["scale"]["hi"]])
        self.assertEqual((job["preset"], job["over"], job["under"]),
                         ("Viridis", [255, 0, 255], [128, 128, 128]))
        self.assertEqual((job["width"], job["line_px"]), (scales.WIDTH_PX, scales.LINE_PX))
        self.assertEqual(job["planes"], [{"point": p["point"], "normal": p["normal"]}
                                         for p in summary["planes"]])
        # The scene's ticks, placed on the gradient from 0 to 1.
        ticks = view.meta["scale"]["ticks"]
        self.assertEqual([t["at"] for t in ticks], [0.0, 1.0])

    def test_the_legend_is_the_exported_preset(self):
        """The stops are the export's points (every STOP_EVERY-th and the last),
        read here from the file without the pack's code."""
        with open(os.path.join(PACK, "views", "viridis.json"), encoding="utf-8") as fh:
            preset = json.load(fh)
        points = preset["RGBPoints"]
        rows = [points[i:i + 4] for i in range(0, len(points), 4)]
        self.assertEqual((preset["Name"], len(rows)), ("Viridis", 256))
        stops = _scales_mod().stops()
        self.assertEqual(len(stops), 65)
        self.assertEqual([s["at"] for s in stops],
                         [rows[i][0] for i in [*range(0, 256, 4), 255]])
        self.assertEqual((stops[0]["colour"], stops[-1]["colour"]), ("#440154", "#fde725"))

    def test_another_runs_fields_draw_no_still(self):
        summary = _summary_of(self.verdict)
        stage = summary["fields"]["stage"].replace("<out>", store.out_dir(self.root), 1)
        field = os.path.join(stage, summary["fields"]["time"], "mag(U)")
        with open(field, "rb") as fh:
            kept = fh.read()
        self.addCleanup(lambda: open(field, "wb").write(kept))
        with open(field, "ab") as fh:
            fh.write(b"// another run\n")
        _spec, view, _note, ctx = self.draw(SPEED)
        self.assertIsNone(view)
        self.assertTrue(any("is from another run" in n for n in ctx.notes), ctx.notes)
        self.assertEqual(self.scenes(), [])
        self.assertEqual(ctx.outputs, {})

    def test_a_preset_that_is_not_the_legends_is_an_error(self):
        pv_standin.set_mode(self.stand["prefix"], "other-preset")
        _spec, view, note, ctx = self.draw(SPEED)
        self.assertIsNone(view)
        self.assertTrue(note.startswith("error:"), note)
        self.assertIn("views/viridis.json", note)
        self.assertEqual(ctx.outputs, {})

    def test_an_unchecked_paraview_draws_nothing_and_says_why(self):
        self.environ(**{self.pv.EXTRA_LOCK_ENV: None})
        _spec, view, note, ctx = self.draw(SPEED)
        self.assertIsNone(view)
        said = " ".join(ctx.notes)
        self.assertIn("which this pack did not check", said)
        self.assertIn(self.pv.NO_PICTURES, said)
        # Refused on its conda records, before its banner: nothing ran.
        self.assertEqual(pv_standin.calls(self.stand["prefix"]), [])

    def test_a_failed_renderer_control_draws_nothing(self):
        pv_standin.set_mode(self.stand["prefix"], "no-overrange")
        _spec, view, _note, ctx = self.draw(PRESSURE)
        self.assertIsNone(view)
        self.assertTrue(any("renderer control failed" in n and "clips" in n
                            for n in ctx.notes), ctx.notes)
        self.assertEqual(self.scenes(), [])

    def test_no_paraview_on_path_is_unavailable_before_the_viewgen_runs(self):
        self.environ(PATH=self.foam_path)
        _spec, view, note, _ctx = self.draw(SPEED)
        self.assertIsNone(view)
        self.assertTrue(note.startswith("unavailable:"), note)
        self.assertEqual(pv_standin.calls(self.stand["prefix"]), [])


def _real_pvbatch():
    """The checked pvbatch62 Install, or None."""
    if os.name == "nt" or not shutil.which("pvbatch62"):
        return None
    pv = _pv()
    try:
        return pv.locate()
    except pv.Unavailable:
        return None


def _internal_field(path: str) -> list[float]:
    """The cell values of an ASCII OpenFOAM volScalarField, read here."""
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    body = text.split("internalField", 1)[1].split("(", 1)[1].split(")", 1)[0]
    return [float(v) for v in body.split()]


def _points_bounds(path: str) -> list[float]:
    """``[xmin, xmax, ymin, ymax, zmin, zmax]`` of a polyMesh points file."""
    import re
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    pts = [tuple(float(c) for c in m.groups()) for m in
           re.finditer(r"\(\s*([-+0-9.eE]+)\s+([-+0-9.eE]+)\s+([-+0-9.eE]+)\s*\)",
                         text.split("(", 1)[1])]
    return [f(p[k] for p in pts) for k in range(3) for f in (min, max)]


@unittest.skipIf(cfd_tests._real_install() is None or _real_pvbatch() is None,
                 "not walked: needs ESI OpenFOAM v2606 and the checked pvbatch62")
class TheRealStills(_env.EnvCase):
    """W10 on the real tools: cfd.pressure_drop on the baseline (v2606), then
    each still drawn by the real ParaView 6.2.0 through its viewgen. Every
    cell's centre pixel is the preset's colour for its value within 2 (read
    from the committed export here, with no code of the pack), a value past
    the scale is exactly magenta, two draws are byte-identical, and each
    plane's line is where the summary's plane and the mesh put it. A copy of
    the scene with a lit display fails the same colour check, so the check
    can fail; and the committed preset is what ParaView exports today."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        import tempfile
        cls.dir = tempfile.mkdtemp(prefix="nopekit-test-")
        cls.root = os.path.join(cls.dir, "proj")
        os.makedirs(cls.root)
        cls.verdict = _run_in_project(cls.root, os.environ.get("PATH", ""))
        cls.drawn = {}
        for view_id in STILLS:
            spec, fn = _views().get(view_id)
            pngs = []
            for n in range(2):
                ctx = _bound_context(cls.root, cls.verdict, view_id,
                                     os.path.join(cls.dir, f"scratch{n}", view_id))
                view, note = site_mod.run_viewgen(spec, fn, ctx)
                if view is None:
                    raise AssertionError(f"{view_id}: {note} {ctx.notes}")
                with open(ctx.outputs[view.src][0], "rb") as fh:
                    pngs.append(fh.read())
            cls.drawn[view_id] = (spec, view, ctx, pngs)

    @classmethod
    def tearDownClass(cls):
        _env._rmtree(cls.dir)

    def setUp(self):
        super().setUp()
        self.assertEqual(self.verdict.outcome, "pass", self.verdict.render())
        self.summary = _summary_of(self.verdict)
        fields = self.summary["fields"]
        self.stage = fields["stage"].replace("<out>", store.out_dir(self.root), 1)
        self.time = fields["time"]

    def frame(self, size):
        """``(x0, x1, y0, y1)`` of the picture: the cut's bounds plus 5% on
        the side that fills it, as B.3.3 states it, computed here."""
        b = _points_bounds(os.path.join(self.stage, "constant", "polyMesh", "points"))
        w, h = size
        dx, dy = b[1] - b[0], b[3] - b[2]
        self.assertEqual(h, max(64, round(w * dy / dx)))
        half_h = max(dx * h / w, dy) * 1.05 / 2
        half_w = half_h * w / h
        cx, cy = (b[0] + b[1]) / 2, (b[2] + b[3]) / 2
        return cx - half_w, cx + half_w, cy - half_h, cy + half_h, b

    def worst_cell(self, png: bytes, field: str, scale: dict) -> tuple[int, dict]:
        """The largest channel difference between a cell's centre pixel and
        the preset's colour for its value (OVER and UNDER exact past the
        scale), over every cell away from the planes' lines; and the count
        of cells in each place."""
        from PIL import Image
        import io
        image = Image.open(io.BytesIO(png)).convert("RGB")
        x0, x1, y0, y1, b = self.frame(image.size)
        level = self.summary["levels"][-1]
        nx, ny, _nz = level["counts"][0]
        values = _internal_field(os.path.join(self.stage, self.time, field))
        self.assertEqual(len(values), nx * ny)
        with open(os.path.join(PACK, "views", "viridis.json"), encoding="utf-8") as fh:
            pts = json.load(fh)["RGBPoints"]
        rows = [pts[i:i + 4] for i in range(0, len(pts), 4)]
        lo, hi = scale["lo"], scale["hi"]
        lines = [(p["point"][0] - x0) / (x1 - x0) * image.size[0] for p in self.summary["planes"]]
        worst, seen = 0, {"in": 0, "over": 0, "under": 0}
        for i, v in enumerate(values):
            ix, iy = i % nx, i // nx
            x = b[0] + (ix + 0.5) * (b[1] - b[0]) / nx
            y = b[2] + (iy + 0.5) * (b[3] - b[2]) / ny
            px = int((x - x0) / (x1 - x0) * image.size[0])
            py = int((y1 - y) / (y1 - y0) * image.size[1])
            if any(abs(px - line) < 8 for line in lines):
                continue
            t = (v - lo) / (hi - lo)
            if t > 1:
                want, where = (255, 0, 255), "over"
            elif t < 0:
                want, where = (128, 128, 128), "under"
            else:
                k = next(j for j in range(len(rows) - 1) if rows[j][0] <= t <= rows[j + 1][0])
                f = (t - rows[k][0]) / (rows[k + 1][0] - rows[k][0])
                want, where = tuple(round(255 * (a + (c - a) * f)) for a, c in
                                    zip(rows[k][1:4], rows[k + 1][1:4])), "in"
            got = image.getpixel((px, py))
            seen[where] += 1
            diff = max(abs(a - c) for a, c in zip(got, want))
            if where != "in" and diff:
                diff = 255
            worst = max(worst, diff)
        return worst, seen

    def test_every_cell_is_the_presets_colour_for_its_value(self):
        for view_id, field in ((SPEED, "mag(U)"), (PRESSURE, "static(p)")):
            with self.subTest(view_id):
                _spec, view, _ctx, pngs = self.drawn[view_id]
                worst, seen = self.worst_cell(pngs[0], field, view.meta["scale"])
                self.assertLessEqual(worst, 2, seen)
                self.assertGreater(seen["in"], 7000, seen)
        # On the baseline the inlet's corners are past the pressure scale's
        # top (_scales.PRESSURE_HI's provenance): they are magenta.
        _w, seen = self.worst_cell(self.drawn[PRESSURE][3][0], "static(p)",
                                   self.drawn[PRESSURE][1].meta["scale"])
        self.assertGreater(seen["over"], 0, seen)

    def test_both_stills_pass_the_spines_check(self):
        for view_id in STILLS:
            spec, view, ctx, _pngs = self.drawn[view_id]
            self.assertEqual(site_mod._figure_refusal(spec, view, ctx, [self.verdict.limit]), "")
            self.assertEqual(view.meta["tool"]["accepted_by"], "lock")

    def test_two_draws_are_byte_identical(self):
        for view_id in STILLS:
            pngs = self.drawn[view_id][3]
            self.assertEqual(pngs[0], pngs[1], view_id)
            self.assertTrue(pngs[0].startswith(site_mod.PNG_SIGNATURE))
            # Pillow wrote it again with no chunk but the image's.
            self.assertNotIn(b"tEXt", pngs[0])

    def test_the_planes_are_where_the_summary_says(self):
        from PIL import Image
        import io
        for view_id in STILLS:
            with self.subTest(view_id):
                _spec, view, _ctx, pngs = self.drawn[view_id]
                image = Image.open(io.BytesIO(pngs[0])).convert("RGB")
                w, h = image.size
                x0, x1, *_rest = self.frame(image.size)
                want = [(p["point"][0] - x0) / (x1 - x0) for p in self.summary["planes"]]
                self.assertEqual(len(view.meta["marks"]), 2)
                for mark, at in zip(view.meta["marks"], want):
                    self.assertAlmostEqual(mark["at"], at, delta=0.5 / w)
                dark = [x for x in range(w) if max(image.getpixel((x, h // 2))) < 40]
                runs = []
                for x in dark:
                    if runs and x == runs[-1][-1] + 1:
                        runs[-1].append(x)
                    else:
                        runs.append([x])
                self.assertEqual(len(runs), 2, runs)
                for run, at in zip(runs, want):
                    self.assertGreaterEqual(len(run), _scales_mod().LINE_PX)
                    self.assertAlmostEqual((run[0] + run[-1] + 1) / 2, at * w, delta=1.0)

    def test_a_lit_scene_fails_the_colour_check(self):
        spec, fn = _views().get(SPEED)
        with open(fn.__globals__["SCENE"], encoding="utf-8") as fh:
            text = fh.read()
        for old, new in (("display.Ambient = 1.0", "display.Ambient = 0.0"),
                         ("display.Diffuse = 0.0", "display.Diffuse = 1.0")):
            self.assertIn(old, text)
            text = text.replace(old, new)
        planted = os.path.join(self.tmp(), "planted_scene.py")
        with open(planted, "w", encoding="utf-8") as fh:
            fh.write(text)
        ctx = _bound_context(self.root, self.verdict, SPEED, os.path.join(self.dir, "lit"))
        with mock.patch.dict(fn.__globals__, {"SCENE": planted}):
            view, note = site_mod.run_viewgen(spec, fn, ctx)
        self.assertIsNotNone(view, note)
        with open(ctx.outputs[view.src][0], "rb") as fh:
            worst, _seen = self.worst_cell(fh.read(), "mag(U)", view.meta["scale"])
        self.assertGreater(worst, 2)

    def test_the_committed_preset_is_what_paraview_exports(self):
        pv = _pv()
        inst = pv.locate()
        work = self.tmp()
        target = os.path.join(work, "viridis.json")
        scrubbed = {k: v for k, v in pv.environment(work).items() if k != "HOME"}
        proc = _env.run([inst.pvbatch, "--force-offscreen-rendering",
                         os.path.join(PACK, "views", "_export_preset.py"), target],
                        cwd=work, home=work, env=scrubbed, timeout=pv.TIMEOUT_S)
        self.assertEqual(proc.returncode, 0, proc.stderr[-2000:])
        with open(target, "rb") as fh, \
                open(os.path.join(PACK, "views", "viridis.json"), "rb") as committed:
            self.assertEqual(fh.read(), committed.read())


if __name__ == "__main__":
    unittest.main()
