# Rendering: ParaView for the pictures

The gates of this pack do not use ParaView. Only the pictures of the flow on
the site use it. Without ParaView the pictures are not drawn, the charts are
still drawn, and no status changes.

The pack was checked on one ParaView build: **ParaView 6.2.0 from conda-forge,
build `py312ha24fc4a_1`, linux-64**, with Mesa 26.2.5 (llvmpipe). The pack uses
that build and no other (see "How the pack checks the build").

## Install

The environment file `paraview-6.2-linux-64.lock` (beside this file) is the
whole environment, exported with `micromamba env export --explicit`. Each line
is one package file and its md5. It installs this build and nothing else:

```sh
micromamba create -p ~/.local/opt/paraview-6.2 --file paraview-6.2-linux-64.lock
```

It needs about 2.7 GB. It needs no root.

## The launcher

Do not put `~/.local/opt/paraview-6.2/bin` on PATH. That directory holds 426
programs, ParaView's own `python` and `pip` among them, and on PATH they hide
the system ones. Put one launcher on PATH instead, `~/.local/bin/pvbatch62`:

```sh
#!/bin/sh
# pvbatch62: ParaView 6.2.0 (conda-forge, py312) for nopekit's cfd-openfoam pictures.
exec env -i HOME="$HOME" PATH=/home/you/.local/opt/paraview-6.2/bin:/usr/bin:/bin PYTHONNOUSERSITE=1 GALLIUM_DRIVER=llvmpipe LIBGL_ALWAYS_SOFTWARE=1 /home/you/.local/opt/paraview-6.2/bin/pvbatch --force-offscreen-rendering "$@"
```

Write the full path of your install in both places, then:

```sh
chmod +x ~/.local/bin/pvbatch62
pvbatch62 --version            # paraview version 6.2.0
nopekit doctor                 # pvbatch62: found, paraview-6.2.0-py312ha24fc4a_1, ...
```

The pack reads the install's path from the launcher's `exec` line: the path
before `/bin/pvbatch`. It does not run the launcher. It runs that `pvbatch`
itself, in an environment of its own (see "How a run is made"). You can use
the launcher from a shell to try a script by hand.

## How the pack checks the build

Three checks, in this sequence. If one fails, the pictures are not drawn and
the build warnings and `nopekit doctor` say which check failed.

1. The conda record of paraview (`conda-meta/paraview-*.json`) lists
   `bin/pvbatch`, and its sha256 is the sha256 of the file on disk.
2. The package sha256 of `paraview`, `mesalib`, `mesa-libgallium`,
   `mesa-llvmpipe` and `pillow` are an entry of `views/paraview.lock.json`.
   Mesa draws the pixels and Pillow reads them, so those are locked with
   ParaView. The other 260 packages are not.
3. `pvbatch --version` says the version the record says.

The banner alone is not a check: another 6.2.0 build prints the same banner
and can link another Mesa. A build that fails check 2 reads, for example:
`pvbatch62 is ParaView build paraview-6.2.0-py312ha24fc4a_1:24e7bc58bea0,
which this pack did not check`.

To try another build, set `NOPEKIT_PVBATCH_EXTRA_LOCK` to a JSON entry in the
form of the lock's `accepted` entries. A build accepted this way says so: its
`doctor` row says "accepted through NOPEKIT_PVBATCH_EXTRA_LOCK: a build this
pack did not check", and the pictures it draws say "A ParaView build that this
pack did not check drew this picture." To make a build checked, add it to
`views/paraview.lock.json` after its renderer control and the real-tool tests
(`TheRealRendererControl` in `tests/test_cfd_views.py`) pass on it.

## How a run is made

The pack runs `<prefix>/bin/pvbatch --force-offscreen-rendering <script>
<job.json>`, with stdin closed, and with this environment and no other:

| Variable | Value | Why |
|---|---|---|
| `HOME` | a new empty directory outside the project, removed after the run | ParaView writes `~/.config/ParaView` and `~/.cache`; a run never reads your settings and never writes into the project |
| `PATH` | `/usr/bin:/bin` | ParaView's `bin/` is not needed on PATH |
| `PYTHONNOUSERSITE` | `1` | see below |
| `PYTHONDONTWRITEBYTECODE` | `1` | no `__pycache__` beside the pack's scripts |
| `LC_ALL` | `C` | numbers print the same on every machine |
| `GALLIUM_DRIVER`, `LIBGL_ALWAYS_SOFTWARE` | `llvmpipe`, `1` | see below |

No `PYTHONPATH`, `LD_LIBRARY_PATH` or `DISPLAY` comes from your shell.

A run that takes more than 120 s is stopped, and the picture is not drawn. A
run that a signal stops, or that exits with a code that is not 0, is an error
of the picture. The pack uses a run's output only when its `result.json`
holds the sha256 of the job file it was given (so the result is of this job,
not of an earlier one) and names llvmpipe as the GL renderer.

## The renderer control

Before the first picture on a build, the pack draws `views/fixture/strip.vtk`
with `views/_control.py`: 15 cells, with values from -0.2 to 1.2 of a scale
from 0 to 1. It uses ParaView's `Viridis` preset (matplotlib's viridis), a
continuous lookup table (as the stills use), the colour magenta above the scale
and grey below it, and an unlit display. Pillow,
in ParaView's own Python, reads the centre pixel of each cell. The pack then
examines the pixels:

- each cell in the scale is within 1 (in each of red, green and blue) of the
  colour of the lookup table for its value;
- each cell above the scale is exactly magenta (255, 0, 255), and each cell
  below it is exactly grey (128, 128, 128);
- the cell at 0.5 is within 1 of viridis's (33, 145, 140), so the preset is
  viridis.

The result is kept in `.nopekit/cache/pvbatch/`, keyed by the build, the
control script, the fixture and the values above. The control does not run
again until one of them changes. If the control fails, the warnings name each
cell that failed, and no picture is drawn on that build. `nopekit doctor`
reads the kept result and does not run the control.

The control finds the two faults that make a picture show an incorrect value:

- a lit display, which draws each cell darker than its colour on the scale
  (measured: the cell at 0.5 drew (26, 111, 104), not (33, 144, 140));
- a lookup table with no colour above the scale, which draws a value above
  the scale in the top colour (measured: (253, 231, 37), not magenta). A
  picture like that hides a value outside the scale.

## The stills

Each still (`cfd-openfoam.speed`, `cfd-openfoam.pressure`) is one pvbatch run
of `views/_scene.py`, about 2 s:

1. The pack copies the finest mesh and the field at its last time into a
   new case outside the project. It copies only the files whose sha256 the
   result's `summary.json` names, and it examines each sha256 again as it
   copies. It writes a controlDict of its own. ParaView reads no other file
   of the run.
2. ParaView cuts the mesh at the middle of its thickness and gives each cell
   one flat colour: ExtractSurface, Shrink 1.0, CellDatatoPointData, with
   InterpolateScalarsBeforeMapping 0 and an unlit display.
3. The colours come from the `Viridis` preset, on the scale of
   `views/_scales.py`, with a continuous lookup table. A value above the
   scale is magenta, and a value below it is grey.
4. ParaView cuts the cut again with each measuring plane, and draws that
   line in black, 6 px wide.
5. A parallel camera shows the whole cut plus 5% on each side. The picture
   is 1600 px wide, and its height follows the shape of the cut.
6. Pillow writes the PNG again with no text chunk, so two runs give the same
   bytes.

The page draws the colour legend from `views/viridis.json`. That file is the
`Viridis` preset as ParaView exported it, with
`pvbatch62 views/_export_preset.py views/viridis.json`. Each run reports the
sha256 of the preset it used, and the pack uses the picture only when that
sha256 is the sha256 of `viridis.json`. If another ParaView build changes the
preset, export it again and examine the stills.

## The 3D view

The pressure still's run also writes the 3D file. After the screenshot,
ParaView hides the lines of the planes and exports the same view with its own
glTF exporter: `InlineData` 1 (the buffers are in the file as `data:` URIs),
and `SaveNormal`, `SaveBatchId` and `SaveNaNValues` 0. ParaView 6.2 has no GLB
export. The run reports the sha256 of the file, and the pack uses the file
only when it has that sha256.

The page shows this file with no change, in the field mode of its viewer:
the colours of the file with no light and no colour conversion. The faceted
recipe of step 2 makes the file valid: each cell has its own four vertices,
all in its colour, so `POSITION` and `COLOR_0` have the same count.

A file larger than 2 MiB is not published. The still is published without it,
and the build gives a warning. A file that is not the file of the run is an
error of the picture.

The tests make two small files with the real ParaView,
`tests/cfd_fields/make_bands.py`: seven bands of known values on the
coarsest mesh of the baseline (500 cells), one export with `_scene.py` and
one with ParaView's default export. The Khronos glTF validator
2.0.0-dev.3.10 must accept the first and refuse the second.

## What was measured

On ParaView 6.2.0 (`py312ha24fc4a_1`), WSL2, 2026-10-21:

- Without `PYTHONNOUSERSITE=1`, ParaView's Python reads the user's
  site-packages, and a user site with another numpy stops pvbatch with
  `malloc(): invalid size` (SIGABRT).
- Without `GALLIUM_DRIVER=llvmpipe`, Mesa can use a GPU driver (D3D12 under
  WSL2), and the pixels are then different on each machine. With llvmpipe, two
  runs write PNG files with the same bytes.
- pvbatch writes Mesa, X server and deprecation lines to stderr in each run
  that succeeds. The pack does not examine stderr.
- ParaView 6.2 calls matplotlib's viridis `Viridis`. The older name,
  `Viridis (matplotlib)`, is not there, and `ApplyPreset` stops with an error.
- The first render resets the camera to the bounding sphere of the data. The
  control renders one time before it sets its camera.
- `pvbatch --version` takes 0.7 s. The renderer control takes about 3 s, and
  each still about 2 s.
- ParaView's default lookup table has 256 colours. With a continuous table
  the cell at 0.5 of the scale is (33, 144, 140), not (33, 145, 140).
- On the baseline (8000 cells), the centre pixel of each cell away from the
  lines is the preset's colour for the cell's value, with no difference in
  any channel. Two runs write PNG files with the same bytes. Each line is in
  1 px of its plane.
- A black line in the plane of the cells is drawn over them. A line moved
  toward the camera gave the same bytes.
- The glTF of the baseline (8000 cells) is 940 KB. The Khronos validator
  gives no error and no warning. In each cell, `COLOR_0` is the preset's
  colour for the cell's value, with no difference in any channel. Two runs
  write files with the same bytes. The file is one line with no line end,
  so the line-end rules of git do not change it.
- ParaView's default export (the cut, coloured by its cells) gives more
  vertices than colours. The validator refuses it with
  `MESH_PRIMITIVE_UNEQUAL_ACCESSOR_COUNT`.
- In headless Chromium (SwiftShader), the field mode draws each of the seven
  bands of the test file in its preset colour, in 2 of each channel. The lit
  mode of the viewer draws none of them.
- On the baseline, 6 cells at the corners of the inlet are above the
  pressure scale (to 2.62 pressure drops above the downstream plane), where
  the uniform inlet flow meets the walls. They are magenta. This pressure
  increases when the mesh is made finer, so no fixed top of the scale holds
  it.
