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

The stills and the 3D view (pvbatch) are the later steps of Phase 2.

Run:  PYTHONPATH=src python3 -m unittest discover -s tests -p test_cfd_views.py -v
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import shutil
import unittest
from unittest import mock

import _env
import _projects
import test_cfd_openfoam as cfd_tests
from nopekit import cli, page
from nopekit import site as site_mod

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACK = os.path.join(REPO, "packs", "cfd-openfoam")
GATE = "cfd.pressure_drop"
LADDER, SETTLE = "cfd-openfoam.ladder", "cfd-openfoam.settle"
#: The keys a chart may not hold: the spine's own list.
FORBIDDEN = site_mod.CHART_FORBIDDEN_KEYS


def _views() -> site_mod.ViewRegistry:
    registry = site_mod.ViewRegistry()
    cli._load_viewgens(os.path.join(PACK, "views"), registry, pack="cfd-openfoam", root=REPO)
    return registry


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
    """The chart half of B.6's test: the pack's baseline wrapped as a project,
    the stand-in OpenFOAM and no ParaView on PATH, ``check --tier 2`` and ``site
    build``. Both charts sit beside every claim cfd.pressure_drop covers, each
    of the entry the page serves, beside the claims' chips, with the floor's
    limit and judged point.

    The cfd gates are opaque (they read OpenFOAM through subprocesses), so the
    spine reads their entries stale once ``check`` is done, and the figures say
    the same word as the claims beside them; the stills of P2.3 change none of
    that."""

    @classmethod
    def setUpClass(cls):
        import tempfile
        cls.dir = tempfile.mkdtemp(prefix="nopekit-test-")
        cls.inst, cls.bin = cfd_tests.install_standin(os.path.join(cls.dir, "tool"))
        cls.env = {"PATH": cls.bin + os.pathsep + "/usr/bin:/bin"}
        cls.root = _projects.wrap_pack_baseline("cfd-openfoam", os.path.join(cls.dir, "proj"))
        cls.procs = [_env.nopekit(argv, cwd=cls.root, env=cls.env, timeout=900)
                     for argv in (["check", "--tier", "2"], ["site", "init"],
                                  ["site", "build", "--json"])]

    @classmethod
    def tearDownClass(cls):
        _env._rmtree(cls.dir)

    def setUp(self):
        for proc in self.procs:
            self.assertEqual(proc.returncode, 0, proc.stdout[-3000:] + proc.stderr[-3000:])
        self.assertTrue(os.path.isfile(os.path.join(self.inst, "calls")),
                        "the stand-in OpenFOAM never ran")

    def baked(self, name: str) -> dict:
        with open(os.path.join(self.root, "site", "data", name), encoding="utf-8") as fh:
            return json.load(fh)

    def served_entry(self) -> str:
        names = [n[:-len(".json")] for n in os.listdir(
            os.path.join(self.root, ".nopekit", "verdicts", GATE))
            if n.endswith(".json") and not n.startswith("control-")]
        self.assertEqual(len(names), 1, names)
        return names[0]

    def test_both_charts_beside_every_claim_the_gate_covers(self):
        doc = self.baked("page.json")
        entry = self.served_entry()
        covered = sorted(doc["claims"])
        self.assertEqual(covered, [f"G{n}" for n in range(1, 7)])
        chips = [{"id": cid, "token": doc["claims"][cid]["token"]} for cid in covered]
        for cid in covered:
            figs = {f["view"]: f for f in doc["claims"][cid].get("figures") or ()}
            self.assertEqual(sorted(figs), [LADDER, SETTLE], cid)
            for view_id, fig in figs.items():
                with self.subTest(cid=cid, view=view_id):
                    self.assertEqual((fig["gate"], fig["entry"], fig["kind"]),
                                     (GATE, entry, "chart"))
                    # Opaque gates: the served entry reads stale, and so do the
                    # claims and the figures (the class docstring).
                    self.assertEqual((fig["currency"], doc["claims"][cid]["token"]),
                                     ("stale", "stale"))
                    self.assertEqual([{"id": c["id"], "token": c["token"]}
                                      for c in fig["claims"]], chips)
                    self.assertTrue(fig["data_src"].startswith(
                        f"assets/figures/{GATE}/{entry}/"), fig["data_src"])
                    self.assertTrue(os.path.isfile(
                        os.path.join(self.root, "site", *fig["data_src"].split("/"))))
                    self.assertEqual(page.vega_forbidden(fig["chart"]["spec"]), [])
        summary = json.loads(self.procs[2].stdout)
        self.assertEqual({(v["view"], v["entry"]) for v in summary["viewgens"]},
                         {(LADDER, entry), (SETTLE, entry)})

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
            with self.subTest(fig["view"]):
                with open(os.path.join(self.root, "site", *fig["data_src"].split("/")),
                          encoding="utf-8") as fh:
                    data = json.load(fh)
                numbers = _chart_numbers(data)
                self.assertTrue(numbers)
                self.assertEqual([n for n in numbers if n not in held], [])


if __name__ == "__main__":
    unittest.main()
