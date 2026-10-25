# Rendering: ParaView for the pictures

The gates of this pack do not use ParaView. Only the pictures of the flow on
the site use it. OpenFOAM's function objects calculate every field, surface
and stream track that a picture shows (`aero.converged`, `gates/_fo.py`).
ParaView only draws those files. Without ParaView the pictures are not drawn,
the chart is still drawn, and no status changes.

## Install

The pack uses the same ParaView build as cfd-openfoam: **ParaView 6.2.0 from
conda-forge, build `py312ha24fc4a_1`, linux-64**, with Mesa (llvmpipe). The
environment file `paraview-6.2-linux-64.lock` (beside this file) is the whole
environment. It installs this build and nothing else, in about 2.7 GB, with
no root:

```sh
micromamba create -p ~/.local/opt/paraview-6.2 --file paraview-6.2-linux-64.lock
```

Do not put `~/.local/opt/paraview-6.2/bin` on PATH: its `python` and `pip`
hide the system ones. Put one launcher on PATH, `~/.local/bin/pvbatch62`:

```sh
#!/bin/sh
exec env -i HOME="$HOME" PATH=/home/you/.local/opt/paraview-6.2/bin:/usr/bin:/bin PYTHONNOUSERSITE=1 GALLIUM_DRIVER=llvmpipe LIBGL_ALWAYS_SOFTWARE=1 /home/you/.local/opt/paraview-6.2/bin/pvbatch --force-offscreen-rendering "$@"
```

Then `chmod +x ~/.local/bin/pvbatch62` and `nopekit doctor`. The pack reads
the install's path from the launcher's `exec` line and runs that `pvbatch`
itself, in an empty HOME outside the project, with `PATH=/usr/bin:/bin`,
`PYTHONNOUSERSITE=1`, `LC_ALL=C` and llvmpipe. A run that takes more than
120 s is stopped, and the picture is not drawn.

## How the pack checks the build

`views/_pv.py` is cfd-openfoam's file, copied. Only its known pixel
(`KNOWN`) is different. A test holds the two copies equal with that one
constant masked. The pack draws a picture only when:

1. the conda record of paraview lists `bin/pvbatch` at the sha256 on disk;
2. the packages `paraview`, `mesalib`, `mesa-libgallium`, `mesa-llvmpipe`
   and `pillow` are an entry of `views/paraview.lock.json`;
3. `pvbatch --version` gives the version of the record; and
4. the renderer control passed on this build (below).

## The renderer control

Before the first picture on a build, the pack draws `views/fixture/strip.vtk`
with `views/_control.py`: 15 cells from -0.2 to 1.2 of a scale from 0 to 1,
ParaView's `Turbo` preset, unlit, magenta above the scale and grey below it.
Each cell in the scale must be within 1 of the lookup table's colour, each
cell past the scale must be exactly magenta or grey, and the cell at 0.5
must be Turbo's (163, 253, 60). Measured on the locked build (P0): all 15
cells exact. The result is kept in `.nopekit/cache/pvbatch/`.

## The colours

- **Turbo, for the 3D pictures only.** `views/turbo.json` is ParaView's
  `Turbo` preset as `views/_export_preset.py` exported it (sha256
  `05f02e23...c94f`). Each run reports the sha256 of the preset it applied,
  and the pack uses the picture only when it is this file's. The page's
  legend comes from the same file. cfd-openfoam's 2D stills keep Viridis.
- **The ends of each scale are pack constants** (`views/_scales.py`), or a
  factor times the free-stream speed the gate wrote. No end is a limit.
  Cp -1.5 to 1.05; speed on the tracks 0 to 2.0 times the free-stream
  speed, and on the wake surface 0 to 1.0 times it; CpT -0.2 to 1.05. Each
  top is 1.05, not 1, because 1 is `aero.converged`'s own limit (1%) and the
  site refuses a scale with an end at a limit. The wake has its own speed
  range because its air is slower than the free stream: on the tracks'
  range, 95% of its surface was in the lowest 27% of the colours and the
  picture was one blue. Magenta is above a scale, grey below it.
- **A lit picture's shade is not the key.** The hero and the wake are lit:
  light and shade make a colour darker or lighter than the colour in the key,
  and their captions say so. The Cp still (`aero.surface_cp`) is unlit: each
  of its pixels is a colour of the key. The cuts are unlit too.
- **What holds the colours** (real-tool tests, `tests/test_aero_views.py`):
  each coloured pixel of an unlit still is within 2 of the Turbo ramp; an
  unlit twin of the hero, at the hero's camera, is within 2; a lit twin and a
  tone-mapped twin are not (the negative controls); and the lit hero keeps the
  twin's hue (95% of the pixels within 6 degrees). Nothing in nopekit judges
  pixels at build time.

## The pictures

| View | Kind | From | Light |
|---|---|---|---|
| `aero.hero` | still and 3D file | the body by Cp, the stream tracks as tubes by speed, a floor and a sky | lit |
| `aero.surface_cp` | still | the body by Cp | unlit |
| `aero.history` | chart | the drag area at each iteration, from `history.csv` | none |
| `aero.wake` | still | the surface CpT = 0 by speed, the body grey | lit |
| `aero.wake_cuts` | still | three cuts behind the body by CpT, clipped above 0.95 | cuts unlit |

Each is bound to the verdict entry of `aero.converged`, on the base mesh.
The summary names each file with its sha256, and the view copies only those
bytes into a scratch folder before ParaView reads them. A picture bound to
`aero.converged` still shows when a later gate fails.

- **Why front faces are culled.** OpenFOAM's patch normals point into the
  body, so the faces toward the camera are back faces. Of the two coincident
  faces of each `-shadow` baffle on the motorBike, the one toward the camera
  is kept. Drawn with both faces, the baffles speckled (measured). The
  page's 3D view draws both faces, each lit by the side the reader sees: in
  the browser a file with every face turned over draws the same pixels, and
  no face of the motorBike is black or lit by the ambient light alone
  (measured in P7, from the file's camera and from behind).
- **Why no SSAO, no tone mapping, no shadows.** SSAO made the sky white and
  added grain; tone mapping moved every colour; this build has no OSPRay for
  shadows (each measured).
- **`InterpolateScalarsBeforeMapping`** is 1 in the stills (every pixel a
  colour of the table) and 0 on the 3D file's displays (without it ParaView
  writes `TEXCOORD_0` and a texture, not `COLOR_0`).
- **FXAA** is on for the hero and the wake only: on the cuts it blended
  their edges off the ramp.
- **The 3D file.** The same run as the hero's still exports ParaView's glTF:
  the body triangulated and decimated by 0.75, the tracks decimated by 0.95
  and drawn as 4-sided tubes, `InlineData` 1. Measured on the motorBike L0:
  1.50 MB with all 78 tracks (the 2 MiB cap; decimation 0.8 gave 3.69 MB).
  The page shows it lit, with a "Flat colours" control that shows the
  colours of the file with no light.

## What was measured

On ParaView 6.2.0 (`py312ha24fc4a_1`, llvmpipe), on the motorBike L0
function-object files (P0, 2026-10-23):

- each still is 1600 x 1000; the hero about 1.2 MB, the Cp still about
  350 KB, the wake about 420 KB, the cuts about 280 KB;
- two runs of the hero write PNG files with the same bytes;
- one picture takes 4 to 8 s, the renderer control about 10 s with other
  work on the machine;
- the hero's 3D file has `COLOR_0` within 1 of the ramp and no `TEXCOORD_0`,
  and the Khronos glTF validator gives no error and no warning.
