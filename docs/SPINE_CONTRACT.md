# Spine contract (internal)

Every spine module builds against `src/atompipe/models.py`. **Read that file first.**
It defines every type that crosses a module boundary; no module may define its own.

Hard rules for the whole spine:

1. **Standard library only.** No third-party imports anywhere under `src/atompipe/`.
   The spine must never be the reason an install fails. Packs declare their own deps.
2. **Python 3.10+ syntax** (`X | None`, `match` ok). Target 3.12.
3. **No `Date.now()`-style hidden state in logic** — callers pass timestamps in. A
   function that stamps its own time is untestable. Use `utcnow_iso()` from `util.py`
   only at the CLI edge.
4. Every public function gets a real docstring saying *why*, not just *what*.
5. Comments carry provenance: when a rule exists because
   something slipped through, say what slipped through.
6. `from __future__ import annotations` at the top of every module.
7. Errors the user caused raise `AtompipeError` (from `util.py`); bugs raise normally.

## Module map and public surface

### `util.py`  (no deps)
```python
class AtompipeError(Exception): ...          # user-facing, CLI prints message not traceback
def utcnow_iso() -> str                      # "2026-09-11T14:46:00Z"
def atomic_write_text(path, text) -> None    # write temp + os.replace; never truncate on crash
def atomic_write_json(path, obj) -> None     # sorted keys, indent=2, trailing newline
def read_json(path, default=None) -> Any
def sha256_text(text: str) -> str
def short_hash(text: str, n: int = 12) -> str
def human_bytes(n: int) -> str
def human_duration(seconds: float) -> str
def rel(path, root) -> str                   # repo-relative posix path, for stable records
class FileLock:                              # build lock; a concurrent run once overwrote a
    def __init__(self, path: str, *, stale_after: float = 3600.0)   # concurrent run
    def __enter__(self) / __exit__(...)      # writes pid; reaps stale locks of dead pids
```

### `store.py`  (deps: models, util)
Persistence. The project lives in `<root>/.atompipe/`.
```python
ATOMPIPE_DIR = ".atompipe"
LEDGER_NAME  = "ledger.json"
def find_root(start: str | None = None) -> str | None   # walk up for .atompipe/
def require_root(start=None) -> str                     # raises AtompipeError if none
def ledger_path(root) -> str
def load(root) -> Ledger                                # missing file -> empty Ledger
def save(root, ledger: Ledger) -> None                  # atomic
def init(root, meta: ProjectMeta) -> Ledger             # creates dirs, refuses if exists
def runs_dir(root) -> str                               # .atompipe/runs/
def record_run(root, verdicts, run_meta) -> str         # append-only history; returns path
def load_runs(root, limit=20) -> list[dict]
def inputs_dir(root) -> str                             # inputs/   (NOT hidden - users put files here)
def out_dir(root) -> str                                # .atompipe/out/  gate scratch + evidence
```
Layout created by `init`:
```
.atompipe/ledger.json   .atompipe/runs/   .atompipe/out/
inputs/{sketches,references,cad,screenshots,datasheets,specs,measurements,data}/
docs/   model/
```

### `modelio.py`  (deps: models, util, store)
The model contract. A project's model is a **Python module** exposing:
```python
CONFIG: dataclass instance          # or  Config: type  +  CONFIG = Config()
def build(config) -> dict           # the resolved geometry/state; pure, deterministic
PARAMS: list[Param] = [...]         # optional explicit provenance; else inferred from fields
```
```python
@dataclass
class LoadedModel:
    module: Any; config: Any; entry: str; params: list[Param]
def load_model(root, entry: str | None = None) -> LoadedModel   # entry from ledger.meta
def project(model: LoadedModel) -> dict      # {"config": {...}, "derived": {...}} JSON-safe
def model_hash(projection: dict) -> str      # stable; drives staleness
def write_projection(root, projection) -> str   # .atompipe/model.json  (the diffable view)
def params_from_model(model) -> list[Param]  # merge PARAMS with dataclass fields+defaults
```
Rule enforced here: a projection value that is a dataclass/enum is encoded via
`models._enc`. Non-JSON-safe values raise `AtompipeError` naming the field —
silent coercion is how a model and its projection drift apart.

### `gates.py`  (deps: models, util, store)
```python
@dataclass
class GateContext:
    root: str; ledger: Ledger; model: Any | None; params: dict
    out_dir: str; tier: int; log: Callable[[str], None]; extra: dict
    pack: str; key_scope: str                           # stamped by run_gate from the spec
    def param(self, name, default=None, *, scope=...) -> Any   # PACK-SCOPED first: see below
    def pack_param(self, name, default=None) -> Any
    def first_pack_param(self, names, default=None) -> Any
    def first_pack_param_named(self, names, default=None) -> tuple[Any, str]
    def require_param(self, name) -> Any                # raises rather than compare with None
def scope_of(gate_id: str) -> str                       # "fdm.bed_fit" -> "fdm"
SCOPE_SEP = "."
class Registry:
    def register(self, spec: GateSpec, fn) -> None      # raises if no negative_control
    def get(self, gate_id) -> tuple[GateSpec, Callable] | None
    def specs(self) -> list[GateSpec]
    def for_claim(self, claim_id, tags) -> list[GateSpec]
    def by_tier(self, max_tier: int) -> list[GateSpec]
REGISTRY: Registry                                      # module-level default
def gate(*, id, claims=(), tier=Tier.INSTANT, settles="", requires_tools=(),
         requires_python=(), negative_control=None, title="", description="",
         pack="", registry=REGISTRY)                    # decorator -> registers, returns fn
def availability(spec) -> tuple[bool, str]              # (ok, "requires openfoam (not on PATH)")
def run_gate(spec, fn, ctx) -> Verdict                  # times it; catches exceptions -> error verdict
def run_all(registry, ctx, *, max_tier=0, only=None) -> list[Verdict]
def selftest(spec, fn, ctx) -> Verdict                  # runs the NEGATIVE CONTROL
def load_fixture(ref: str, root: str) -> Any            # "mod:fn" or "path/to/file.py"
```
A gate function receives `GateContext` and returns `Verdict` **or** a plain
`(bool, detail)` / dict, which `run_gate` normalises. `run_gate` always fills in
`gate`, `tier`, `pack`, `claims`, `duration_s` from the spec — a gate cannot lie
about its own identity.

**Parameter lookup is PACK-SCOPED.** `ctx.param("bbox_mm")` inside `fdm.bed_fit`
resolves `fdm.bbox_mm` (flat or nested), then `fdm-print.bbox_mm`, then the bare
`bbox_mm`, then the last dotted segment. For a synonym family
(`first_pack_param`): every scoped spelling in declared order, then every bare one.
That is what lets `cad-solid` and `fdm-print` both read a `bbox_mm` from one
projection and mean different objects — see `docs/PACK_FORMAT.md`. `run_gate`
stamps `pack` and `key_scope` from the spec, so a caller cannot hand a gate
somebody else's namespace.

**`Registry.register` raises `AtompipeError` if `negative_control is None`.**
This is rule 5 of the method made mechanical: a gate that cannot demonstrate
failure is a logger, and one shipped green for a whole revision.

### `claims.py`  (deps: models, util)
The derivation logic. Nothing here writes.
```python
def resolve_status(claim, verdicts, *, stale: bool = False) -> ClaimStatus
def statuses(ledger, *, stale=False) -> dict[str, ClaimStatus]
def coverage(ledger, registry) -> dict[str, list[str]]       # claim id -> LIVE gate ids
def effective_gates(ledger, registry) -> dict[str, list[str]]  # cached `claim.gates` UNION live
def find_gaps(ledger, registry) -> list[Need]                # MEASURABLE claims with no gate
def blocking(ledger, registry, *, stale=False) -> list[tuple[Claim, ClaimStatus]]
def summarise(ledger, registry, *, stale=False) -> dict      # counts by status, for the CLI
def next_claim_id(ledger, prefix="C") -> str                 # C1, C2, ...
```
`blocking` returns **(claim, status) pairs**, not bare claims. The caller is about
to approve an irreversible spend and needs the reason — "C7 blocks" sends them
hunting, "C7 is BLOCKED: no gate ran, the solver is not installed" tells them what
to do. Returning bare claims would also force every caller to re-derive the status
it just discarded, and a second copy of the precedence ladder is a second answer to
the only question this module exists to answer.

`effective_gates` is the **single** definition of which gates cover a claim, and
anything rendering coverage calls it rather than re-deriving one. `coverage` alone
is the live half; the union with the ledger's cached `claim.gates` is what keeps a
gate visible when the pack supplying it is not loaded in this process. A second,
live-only copy of the rule in `report.py` dropped exactly those gates, so the PROVEN
table's **PARTIAL** caveat vanished whenever a pack went missing — the report read
*more* certain the less it could see.

`resolve_status` precedence (deliberate):
ASSUMPTION -> ASSERTED. PHYSICAL -> VERIFIED/REFUTED if a result exists, else UNVERIFIED.
MEASURABLE -> no covering gate: UNCLAIMED; **every** covering verdict skipped (and none
errored): BLOCKED; none run: PENDING; any covering verdict errored **or** failed: FAIL;
all ran and passed and `stale`: STALE; else PASS. **A skip is never a pass.**

An error outranks a skip on purpose: BLOCKED reads "your toolbox is incomplete" and
FAIL reads "something is wrong here". A gate that crashed is not a gate that was
absent — it ran, it was given this project's data, and it came apart on it, which is
the louder signal and may itself be the defect. Folding a crash into BLOCKED would
file it under "install something", which is the one instruction that will not help.

### `artifacts.py`  (deps: models, util, store)
Intake of real evidence — sketches, teardown photos, CAD, datasheets, measurements.
```python
ASK_FOR: dict[str, list[str]]        # artifact-kind -> concrete prompts the agent should use
def kind_for(path) -> ArtifactKind   # by extension + directory hint
def ingest(root, ledger, src, *, kind=None, description="", when="", copy=True,
           licence="", note="") -> InputArtifact     # copies into inputs/<bucket>/, hashes
def ingest_link(root, ledger, url, *, description="", kind=ArtifactKind.LINK, when="") -> InputArtifact
def add_extraction(ledger, artifact_id, extraction: Extraction) -> InputArtifact
def inputs_hash(ledger) -> str                       # over sorted (id, sha256)
def unextracted(ledger) -> list[InputArtifact]       # evidence nobody read = decoration
def grounding(ledger) -> dict[str, list[str]]        # param/claim id -> artifact ids
def suggest_requests(ledger, *, project_kind="") -> list[str]
    # the ASK list, filtered to what is MISSING. This is what makes intake actively
    # solicit files instead of waiting for the user to think of them.
```
`ASK_FOR` must cover at minimum: sketch, reference, cad, screenshot, datasheet,
spec, measurement, standard, data — each with 2-4 concrete, domain-neutral prompts
phrased as things to ask a human ("a photo of the closest existing product you'd
buy instead, even a bad one").

### `packs.py`  (deps: models, util, store)
```python
def search_paths(root=None) -> list[str]     # project .atompipe/packs, ~/.atompipe/packs, bundled packs/
def discover(root=None) -> list[PackManifest]              # reads pack.json only (tier 1)
def find(name, root=None) -> str | None                    # directory
def read_manifest(pack_dir) -> PackManifest
def load_gates(name, registry, root=None) -> list[GateSpec]  # imports pack gates/*.py
def load_all_gates(names, registry, root=None) -> list[GateSpec]
def pack_doc(name, root=None) -> str                       # PACK.md  (tier 2)
def reference_doc(name, ref, root=None) -> str             # references/<ref>.md (tier 3)
def validate(pack_dir) -> list[str]                        # problems; empty = ok
def match(need: Need, manifests) -> list[PackManifest]      # gap -> candidate packs, by `settles`
def key_scope(manifest) -> str                             # "fdm-print" -> "fdm" (from its gate ids)
def key_vocabulary(name, root=None) -> dict[str, dict]     # every projection key the pack reads
def key_collisions(names, root=None, *, projection_keys=()) -> list[KeyCollision]
```
`key_collisions` is what makes two packs wanting one word DETECTABLE rather than
discoverable: it diffs the installed packs' vocabularies (from each
`selftest/baseline.json`'s keys, `_notes` and `_aliases`) and reports any key two
of them declare differently. `atompipe doctor` renders it as a warning naming both
packs. See `docs/PACK_FORMAT.md`.
Pack layout (also documented in the pack-authoring skill):
```
packs/<name>/pack.json  PACK.md  references/*.md  gates/*.py  generators/*.py
             lenses.md  sourcing.md  scaffold/  selftest/
```
`load_gates` imports each `gates/*.py` with the pack directory on `sys.path` and a
module-level `PACK = "<name>"`; gate modules use the `@gate` decorator.

### `decisions.py`  (deps: models, util, store)
```python
def add(ledger, *, title, summary, when, rejected=(), params_changed=(),
        claims_changed=(), body="", evidence=()) -> Decision
def render_log(ledger) -> str                # markdown, NEWEST FIRST
def write_log(root, ledger) -> str           # docs/decisions.md
def why(ledger, name: str) -> str            # one param or claim: value, rationale,
                                             # rejected alternatives, gates, grounding,
                                             # and the decisions that moved it
```
`why` is the context-window win: an agent pulls one parameter's full history
instead of reading a 1,672-line decision log.

### `report.py`  (deps: models, util, store, claims, artifacts)
```python
def render_terminal(ledger, registry, *, stale=False) -> str
def render_markdown(ledger, registry, *, stale=False, title="") -> str
def write_report(root, ledger, registry, *, stale=False) -> str   # docs/readiness.md
```
The markdown report has this shape, generated:
**Verdict** (one honest sentence) / **PROVEN** table with evidence per row /
**NOT VERIFIED** list with why / **OPEN GAPS** (Needs) / **STANDING CONSTRAINTS**
(assumptions) / **Reproduce** (the exact commands). It must never call a skipped
or unrun gate "proven".

`store` is in the deps for one reason: `write_report` takes its destination from
`store.project_paths(root)["readiness"]`. Layout is `store`'s job alone, and a
second module that knows where `docs/readiness.md` lives is a second module to
edit when it moves.

A PROVEN row whose claim is *also* covered by a gate that produced no proof is
marked **PARTIAL**, names that gate and the reason (`never run`, the skip reason,
`errored`, `failed`), and says how many of the covering gates the row rests on.
Coverage for that check comes from `claims.effective_gates` — the union — so the
caveat survives the pack going missing, which is when it matters most.

### `cli.py`  (deps: everything)
`argparse`, subcommands, `main(argv=None) -> int`. Catches `AtompipeError` and
prints `error: <msg>` to stderr, returns 2.
```
atompipe init [--name] [--summary]        atompipe status
atompipe claim add|list|show|edit|physical  atompipe gap [--propose]
atompipe ingest <path...> [--kind] [--desc]   atompipe inputs [--unextracted]
atompipe extract <artifact> --what ... --grounds ...
atompipe ask [--kind]                     # what evidence to request from the user
atompipe check [--tier N] [--only GATE]   atompipe gate list|selftest|show
atompipe report [--write]                 atompipe why <param-or-claim>
atompipe decide --title ... --summary ...  atompipe packs [list|show|validate]
atompipe model [--write]                  atompipe doctor
```
Output is terse and machine-parseable by default (one line per verdict);
`--json` on every read command.
