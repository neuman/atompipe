# Installing OpenFOAM for this pack

The tier-0 gates (`cfd.case_readable`, `cfd.regime`) need nothing. The others need
**ESI OpenFOAM v2606** (openfoam.com). Without it they read Skipped, never passed.

## Which OpenFOAM

There are two OpenFOAMs, and they do not read each other's cases:

| | ESI / OpenCFD (openfoam.com) | The OpenFOAM Foundation (openfoam.org) |
|---|---|---|
| Versions | `v2606`, `v2512`, ... (year and month) | `13`, `12`, ... |
| Steady incompressible solver | `simpleFoam` | `foamRun` with `solver incompressibleFluid;` (v11 on) |
| This pack | runs v2606 | refused: the skip says it is not an ESI install |

An ESI install is told apart by its `META-INFO/api-info` file (`api=2606`). The
pack runs one API, v2606, the one it was written and checked on. Another API is
refused with a skip that names it: ESI moves function-object options between
releases, and a reader that misses a moved line can turn a miss into a pass.

The v2606 this pack was checked on was the Debian package `2606.0~rc2-1`, a
release candidate (build `_481094f-20260618`). The build string is in every
`cfd.converged` evidence file.

## Ubuntu and Debian

```sh
curl -s https://dl.openfoam.com/add-debian-repo.sh | sudo bash
sudo apt-get install openfoam2606-default
```

This puts `/usr/bin/openfoam2606` on PATH and the install under
`/usr/lib/openfoam/openfoam2606`. The pack finds the install from that wrapper.

Check:

```sh
openfoam2606 -show-api        # prints 2606
```

You do not need to source `etc/bashrc` for nopekit. The gates source it
themselves, once per run, from a bare environment, so what your shell has set
does not reach a run. The pack finds an install from the wrapper alone, never
from a `simpleFoam` on PATH: availability and the gate must agree on what is
there. If you built v2606 yourself, give it the same wrapper, an executable
`openfoam2606` on PATH holding:

```sh
#!/bin/sh
exec "/path/to/OpenFOAM-v2606"/etc/openfoam "$@"
```

## Other platforms

- **macOS, Windows:** ESI ships Docker images (`opencfd/openfoam-default:2606`)
  and a WSL route on Windows. The pack runs the tools as local executables, so
  inside Docker run nopekit in the container too. Untested.
- **conda-forge:** has an `openfoam` package; check its API with
  `foamEtcFile -show-api` before relying on it.

## What the gates set for every run

- `HOME` is a private directory under the gate's out directory, holding one
  `.OpenFOAM/2606/controlDict` that turns off `allowSystemOperations`. Your own
  `~/.OpenFOAM` never reaches a run. Measured on v2606: the
  `-info-switch allowSystemOperations=0` option does not work (the switch is
  "unregistered"); the file does.
- `FOAM_SIGFPE=true`, so a diverging run dies on SIGFPE instead of carrying NaN.
- `PWD` is the staged case, so OpenFOAM does not warn that `PWD is not the cwd()`.

Each tool's banner must show `OPENFOAM=2606`, `trapFpe: Floating point exception
trapping enabled` and `allowSystemOperations : Disallowing`; a run without any of
them is an error.
