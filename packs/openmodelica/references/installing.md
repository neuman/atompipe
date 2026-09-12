# Installing OpenModelica, pinned, with a smoke test

Read `docs/EXTENSION_PROTOCOL.md` step 4 first. The rule that matters here: **a
mis-built solver produces plausible numbers**, and a plausible number is worse
than an error. Establish that the tool works on a case with a known answer before
you trust it on a case without one.

## What it costs, said out loud

| | |
|---|---|
| Disk, compiler only (`omc`) | ~700 MB – 1 GB |
| Disk, full install with libraries and the GUI | ~2–3 GB |
| Install time | 3–10 min on a decent connection |
| First `checkModel` on a fresh machine | 10–60 s (it loads and indexes the library tree) |
| Second `checkModel` on the same model | 1–5 s |
| `simulate` of a small model | 5–30 s, most of it the C compile of generated code |

That last row is why `modelica.simulates` is tier 2 and the result-reading gates
are tier 0. If the design is still moving, record one run and iterate against the
tier-0 half; reach for the compiler when the equations change.

## Linux (apt) — the usual answer on Debian/Ubuntu/WSL

```bash
sudo apt update && sudo apt install -y ca-certificates curl gnupg lsb-release

curl -fsSL https://build.openmodelica.org/apt/openmodelica.asc \
  | sudo gpg --dearmor -o /usr/share/keyrings/openmodelica-keyring.gpg

echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/openmodelica-keyring.gpg] \
https://build.openmodelica.org/apt $(lsb_release -cs) release" \
  | sudo tee /etc/apt/sources.list.d/openmodelica.list

sudo apt update
sudo apt install -y omc                 # compiler only — this is all these gates need
# sudo apt install -y openmodelica      # ...or the metapackage, with OMEdit and everything
```

Pin the version you actually installed, and record it:

```bash
apt-cache policy omc                    # what is available
sudo apt install -y omc=1.22.1-1        # example — substitute the version you checked
apt-mark hold omc                       # so an unrelated `apt upgrade` cannot move it
```

The repository also carries `nightly` and `stable` suites in place of `release`.
**Do not use `nightly` for a gate.** A validator whose tool changes underneath it
between two runs cannot gate anything.

## Docker — the reproducible option, and the one to prefer in CI

```bash
docker pull openmodelica/openmodelica:v1.22.1-minimal      # ~1 GB, no GUI
docker run --rm openmodelica/openmodelica:v1.22.1-minimal omc --version
```

To let the gates use it, put a two-line `omc` on PATH that forwards into the
container. It must mount the project at the **same absolute path inside the
container**, because the `.mos` scripts these gates generate carry absolute paths
into `loadFile`:

```bash
#!/bin/sh
# ~/bin/omc — omc-in-docker, pinned
exec docker run --rm -u "$(id -u):$(id -g)" \
  -v "$PWD:$PWD" -w "$PWD" \
  openmodelica/openmodelica:v1.22.1-minimal omc "$@"
```

Tag suffixes: `-minimal` (compiler and libraries), `-ompython` (adds the Python
bindings this pack deliberately does not use), `-gui` (adds OMEdit, much larger).

## macOS

Homebrew has no maintained formula. Use the official `.pkg` from
<https://openmodelica.org/download/download-mac/>, or Docker as above. The `.pkg`
puts `omc` in `/Applications/OpenModelica.app/Contents/Resources/opt/bin/omc`;
symlink it onto PATH rather than teaching the pack a new path — `requires_tools`
is `omc` and it is found with `shutil.which`.

## Windows

The official installer from <https://openmodelica.org/download/download-windows/>
puts `omc.exe` in `C:\Program Files\OpenModelica<version>\bin`, which is NOT on
PATH by default. Under WSL, install the Linux package inside the WSL distribution
instead of trying to reach the Windows binary: the `.mos` scripts carry POSIX
paths and `omc.exe` will not resolve them.

## The Modelica Standard Library

The compiler ships without libraries on some builds. Install the one you pin
against:

```bash
omc <<'EOF'
updatePackageIndex();
installPackage(Modelica, "4.0.0+maint.om", exactMatch=true);
getAvailablePackageVersions(Modelica, "");
EOF
```

The MSL version is a **constant with provenance** exactly like a material
property. MSL 3.2.3 and 4.0.0 differ in package names (`Modelica.SIunits` became
`Modelica.Units.SI`), in several component parameterisations, and in a few
default values. Record which one the model was validated against, in the model's
own provenance, and put it in `modelica_load_libraries`.

## The smoke test — run this before any project data

Do not skip it, and do not accept "it printed a version number" as a pass. The
point is a case with a **known answer**.

```bash
mkdir -p /tmp/omc-smoke && cd /tmp/omc-smoke
cat > Smoke.mo <<'EOF'
model Smoke "First-order decay with a closed-form answer"
  parameter Real tau(unit = "s") = 1 "Time constant";
  Real x(start = 1, fixed = true, unit = "1") "State";
equation
  tau*der(x) = -x;
end Smoke;
EOF
cat > smoke.mos <<'EOF'
loadFile("Smoke.mo");
getErrorString();
checkModel(Smoke);
simulate(Smoke, stopTime=1.0, numberOfIntervals=10, outputFormat="csv");
getErrorString();
EOF
omc smoke.mos
tail -1 Smoke_res.csv
```

Three things must be true, and all three are checkable by eye:

1. `checkModel` says **`has 1 equation(s) and 1 variable(s)`**. Equal counts.
2. `simulate` echoes a record with a non-empty `resultFile` and empty-ish
   `messages`.
3. The final row of `Smoke_res.csv` is `t = 1` and `x ≈ 0.367879` — which is
   `exp(-1)`, to as many digits as the tolerance allows. **That is the known
   answer.** A build that produces 0.36 or 0.4 here is a build to throw away.

Keep the output. It is the evidence for extension-protocol step 4, and it belongs
in the ledger next to the decision to install.

## Verifying the pack sees it

```bash
atompipe gate list | grep modelica        # the tier-2 rows stop saying BLOCKED
atompipe gate selftest modelica.checks    # the control must now FIRE, not skip
```

That second command is the one that matters. Until it reports the gate correctly
failing on `selftest/assets/bad/UnbalancedTank.mo`, the tier-2 half of this pack
is installed but unproven.
