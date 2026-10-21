# SPDX-License-Identifier: Apache-2.0
"""A stand-in for ParaView's ``pvbatch`` (issue #15, B.6, W15): installed by
``tests/test_cfd_views.py`` as ``<tmp>/opt/pv/bin/pvbatch``, with a fake
``conda-meta/`` and a ``pvbatch62`` launcher on a temporary PATH, it plays the
part ParaView plays for cfd-openfoam's ``views/_pv.py``. It never runs inside
nopekit's process: ``_pv.run`` starts it as it starts pvbatch, in the scrubbed
environment, under its timeout.

It draws nothing. It writes committed fixture bytes (rule 0.4 of the issue's
design: a stand-in writes bytes a trusted tool made, and grows no codec): the
PNG and the cell readings that ParaView 6.2.0 (conda-forge
``py312ha24fc4a_1``, llvmpipe) wrote for the renderer control
(``packs/cfd-openfoam/views/_control.py`` on ``views/fixture/strip.vtk``) on
2026-10-21, and, for the planted faults, what the same ParaView drew with a lit
display and with no above-range colour; for a scene job (``views/_scene.py``,
a job with a ``case``), the still the same ParaView drew of the job's field on
the pack's baseline.

Its install is ``<prefix>/bin/pvbatch`` (a three-line Python launcher that
calls ``main``), ``<prefix>/conda-meta/*.json`` and ``<prefix>/standin.json``,
which holds its mode (the environment is scrubbed, so the mode cannot come
from there). Each call appends one JSON line to ``<prefix>/calls.jsonl``: its
argv, its whole environment, what its HOME held and its cwd, and for a scene
job the job and every file of its case (``case_files``): what ParaView would
have read.

Modes: ``ok``; ``no-overrange`` (values past the scale drawn in the end
colours, so the renderer control must fail); ``lit`` (the lit display's
pixels); ``sigabrt`` (kills itself with SIGABRT); ``hang`` (sleeps past any
timeout); ``noise`` (stderr junk, exit 0, a good result); ``no-done`` (a result
whose ``done`` is another job's); ``gpu`` (reports a GL renderer other than
llvmpipe); ``crash`` (a traceback, exit 1); ``no-result`` (exit 0, nothing
written); ``dirty-home`` (writes into its HOME, then a good result);
``other-preset`` (a scene job reports another preset than viridis). Its
``--version`` banner is ``standin.json``'s ``banner``.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import signal
import sys
import time

#: The renderer control's PNG as ParaView 6.2.0 wrote it (600 x 120, RGB).
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAlgAAAB4CAIAAAChNxuUAAAAFHRFWHRBcHBsaWNhdGlvbgBQYXJhVmlld5SClFUA"
    "AAVFSURBVHja7d1PjttkGMDh106cTOZP2w0qqKrKDSqxhh0H4AQ9DjsWnIMr0CuAyh6kboEFnUwmYzuxuyE7iiaR"
    "/M348/Moy5GsL2P759fOZIq+7wMApqr0FgAghAAghAAghAAghAAghAAghAAghAAghAAghAAghAAghAAghAAghAAg"
    "hAAghAAghAAghAAghAAghAAghAAghAAghAAghAAghAAghAAghAAghAAghAAghAAghAAghAAghAAghAAghAAghAAg"
    "hAAghAAghAAghABwsvn9f/Tt27fr9bqu66ZpmqZp23Z3sD/oum7Ub8evP/6x+ec26ZXIvCy/fJV0i2W5ffks5RaL"
    "srj+okq6xqK4+TwSb3HzfJ94i/3zbdKTRVm+/OyvlFusytlXz35Pu8X5N5e/pd3i6uvF5gFmoB9+iT8v4zriJmIT"
    "cRuxjbiLqCOaw6t9xCfrKmJxeC0jziJWEecRFxGXEU8iXkR8P0AI1+v1u3fv8r4uuHi1SBzCfnWeeI3tqkq8xeas"
    "SLzFru8jiuRbTL3GxG/r2WKbeI1Pqw+pj45ul3yLqd/Vf888738ufvpuxCfrNqKN+J9LiDfHXBbc/0frus5+QN7X"
    "ySfa5DN0kfyUXXRBBrrU5Y1979nNYNaXmS/wepgQNk2Tfwib5Ofs5FmKLnkI+yADyUfQ6IRwOJvzzBd4I4QjCmE3"
    "gfT2SmgiPG0iLLztQ12e3q5yL/0wIWzbNv9Dvc0/Sw9wa1QHTYQjSe+EbHMP4TEf9jgihLvdLvt9o9vlf6My0mdJ"
    "CDMJYfKDI4RwMHdnuZdeCE8PYeqJsJ/CjUohzCOEYSLMSL3IvfRCOKKJcAJZcmvURDiW9E5Ik3sIj/krhyNCuN/v"
    "8z/U9/mHsOjdG2UcWepNhEJ4+gKFcEQhDM8IMRH+N88IB9RWmS9QCE8/8PZTeH6WfAZ10smkhOknQm+6ED6yEI79"
    "e0TvdeB1nhGaCHk8O46LqOFCOM99gcOEEADyI4QACCEACCEACCEACCEACCEACCEACCEACCEACCEACCEACCEATC6E"
    "ZZl/NYsy+bfdF+m3GPlvkUx2HP+4ZDDVLvcFDhPC2WyW/3XBbAJZSv9/xp10Milh8v9k6RJqwE60mS9wIYQnH3iz"
    "CYxLJkJGkqXSRZQQCuEkQpj87NIXSshpv8X0E6EQDteJJvcFDhPC+Xye/b5Rzj0jHCK9zjomwnGkVwjzsRTC00OY"
    "+gNBRSG9mAg/cTyaCAfsRO4hPBPCEU2EpWeEmAg/dXoSwuE6cZf5AlfDhLCqquz3jbJK/iciE3hG6NZoLiE0EebU"
    "iW3mCzwfJoSLxSL7fWO2SB7CMv/0+hR8JpeJybM0E8LhLk/Pcw/hhRCOKIRF/jdjTYQmwlN31c7bPlgnbjNf4OUw"
    "IVwul9nvG7Nl/hPhA9wa9UV+JsITJ0IhHMzVTeYLfHLEzx7x+Zerq6vXr1/Xdd00TdM0bdvuDvYHXTfuHXfzPvUn"
    "qYpt6uuyatsm/m6lxV2f+Ll8mTz2D7LFxF26a1YRSc+eH9qnEX8nPTrK1B8JrMpVxOYB5vtX38abiOuIm4hNxG3E"
    "NuIuoo5oDq/H/Df3VcTi8FpGnEWsIs4jLiIuI55EvDjm3eh7d+EBmC43rQAQQgAQQgAQQgAQQgAQQgAQQgAQQgAQ"
    "QgAQQgAQQgAQQgAQQgAQQgAQQgAQQgAQQgAQQgAQQgAQQgAQQgAQQgAQQgAQQgAQQgAQQgAQQgAQQgAQQgAQQgAQ"
    "QgAQQgAQQgAQQgAQQgAQQgAQQgAQQgAQQgAQQgA43UdhwYDUPW2r0gAAAABJRU5ErkJggg==")

#: ``(index, t, where, pixel, want)`` of each strip cell, as ParaView 6.2.0
#: reported them for the unlit display: the centre pixel and the lookup
#: table's colour for the cell's value.
CELLS = [
    (0, -0.2, "below", (128, 128, 128), (128, 128, 128)),
    (1, -0.1, "below", (128, 128, 128), (128, 128, 128)),
    (2, 0.0, "in", (68, 1, 84), (68, 1, 84)),
    (3, 0.1, "in", (72, 37, 117), (72, 37, 117)),
    (4, 0.2, "in", (65, 68, 135), (65, 68, 135)),
    (5, 0.3, "in", (52, 95, 141), (52, 95, 141)),
    (6, 0.4, "in", (42, 120, 142), (42, 120, 142)),
    (7, 0.5, "in", (33, 144, 140), (33, 144, 140)),
    (8, 0.6, "in", (34, 168, 132), (34, 168, 132)),
    (9, 0.7, "in", (67, 191, 113), (67, 191, 113)),
    (10, 0.8, "in", (122, 209, 81), (122, 209, 81)),
    (11, 0.9, "in", (188, 223, 39), (188, 223, 39)),
    (12, 1.0, "in", (253, 231, 37), (253, 231, 37)),
    (13, 1.1, "above", (255, 0, 255), (255, 0, 255)),
    (14, 1.2, "above", (255, 0, 255), (255, 0, 255)),
]

#: The pixels the same ParaView drew with a lit display (Ambient 0, Diffuse 1).
LIT = [(100, 99, 95), (100, 99, 95), (53, 1, 62), (56, 29, 87), (51, 52, 100),
       (41, 73, 105), (33, 93, 105), (26, 111, 104), (27, 130, 98), (52, 147, 84),
       (95, 161, 60), (147, 172, 29), (198, 178, 27), (200, 0, 189), (200, 0, 189)]

#: Past the scale with no above-range or below-range colour, the end colours
#: (measured, with both turned off in a copy of the control).
CLIPPED = {"above": (253, 231, 37), "below": (68, 1, 84)}

GL = "llvmpipe (LLVM 23.1.3, 256 bits)"

#: The stills ParaView 6.2.0 drew of the pack's baseline (cfd.pressure_drop on
#: the real ESI v2606, 8000 cells) with ``views/_scene.py`` on 2026-10-21: |U|
#: on [0, 0.02] m/s and static p on [-0.258, 1.306] Pa (1600 x 160, RGB, no
#: chunk but the image's). The stand-in writes the one of the job's field,
#: whatever the case holds: it draws nothing.
SPEED_PNG = base64.b64decode(
    "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")
PRESSURE_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAABkAAAACgCAIAAADb+jdIAAAN/UlEQVR42u3dS48c13kG4O/Upad5ieiQlAERspGF"
    "aMNAHMvZxXCgJECQrJMfkEU22RtaGMjeC8E/wj8gm+yyioVAC8G27ECRDZBCgESKBNgUYzqkZqbrcrKQZWvMqsYU"
    "p3qmp/t5VqxioW5d0yy+POdlyjkHAAAAAGyrwi0AAAAAIARYAAAAAPBsKrcAuIza3DV91/Zdk7tV36669rhvjrrm"
    "sFsddqsn7fE3brz06quvvv3WT+7fvx8Rd+/e/eofv/zaa6+98ejd69XBlXJxpVwsy8VBUS2KalFUVVHWRVkXZZVK"
    "txcAuPi3na5vuq5pu6brm6Y7btvjVXu0ag9XzeFx8/ho9ctHj17/p++9/e8//u3bzte+/srf/t3nnrtxfbm4sqyv"
    "LOrlojqoq4O6qquyroq6LOuqrErjGIAQYJ3CtyLeiXg/4r2IiPhCxIvRv/TxT7/9zZybnJscq5zbT7b96eqL3ae/"
    "/qxfdddyDLR3HeaDeGp901cxtHGbB/6a2kUaPOs+D3/Ld3lg+35kaFufR3Y+dNDxjYsJG085Yp7l9KbtpDj9xmNn"
    "OMtd3ei15+GdxOl3kmPiEYcfyxnu6lhp3rQnasrOJ1377xzxP++98dGb//HJr9988813rz/5yb99Z/Zrz1Ouffga"
    "t+eIY9/bw3c7Jv00Tdp4eOebPOLoxeezHjHmOOL4ZzPhoxk/4sBO0tSGzHzma5/jiGmWuz3tiBM/9ymnkfIM15LO"
    "/DBMvvazX+PEhyTFHDvZ4GO53dc48TLneSznuNtnP5N07p/vJj6C//r+Dx/e++Fv3nbu/2/3o/SlmU979A/gTV77"
    "mT+yNM9jmTd3jTN9i+YN/ehN/O7KZ9/J+MZ5jm/LvA3XONONyps84q9/o6qKqiqruqzrsq6qxaJcHNTLZb1c1sur"
    "i2tXD249f/3v/+Ev9iDAei/iXz6z+E7EO/Gr6l/b7sFQPNSOfDTzvPgDO6z/eHXi++TkIgDAZdetjtYsAjybtu3b"
    "to+jJmI4UPnLv/6j2IsOrF8MrKs+uuURAWZ+pTs6kVj1RwIsAGCn9O3Jt53G2w5wHp58fBz7G2A9vOkJAGZ+pfvk"
    "XwxGFgEALv3bzsnE6nfyLIANObqI2S0XMYXw50Pn8eB2M5SmVakfPu+R9WUeWN+lYmR+bJ5QnxETJ9lut2SmJfvw"
    "SnfcrFkEANi1EVgCLOBcHF3E4AAjsIAdDrDaNYsAAJc/wGrWLAKEAOtMnh9Y1958GDl5CIA5X+lW7ZpFAIDLLnft"
    "mkWADVldxOyWi5hC+PmBQVir2x+tonh6Dls5MlWwGF2fT//fTA5PIYwJG0dEpDThP7acZ8Zh3qG5jLDJV7qmW7MI"
    "AHDZ9ScTq16ABZyL1arb3xFYzc2HngBgXrntTg6qF2ABALv1ttO3axYBNqRpWgEWQMzXCtGtybMAAOLSTyHs1iwC"
    "xKYCrG4vphD2Lz45fuUH5YcvVB/ciYj2zgfdCx8Wd/7HEwBsdASWAAsA2LkRWN2aRYANafckwPrvb30l56fqvvri"
    "qP+9gW/kkWb3scKnibVW5y1FhP4qOL8Aq1+zCAAgwAJ4Bm27Hx1YA+lVRBT+YgkAAAAQWx9g9fvRgQUAAAAAIcAC"
    "AAAAYCdcQAfWg+5qjoHZkkd9/fTKbqQeKscszVP57DVVm6uvmnTEqaeXPfsAAABAGIEVY9GJZkEAAAAAwhRCAAAA"
    "AEKABQAAAACxax1Yj/rrOQb+w8XjPHAyXR6O2HJOG5zjGJPapPIc3VPJswgAAAAQW9OB1bvvAAAAAIQphAAAAACE"
    "AAsAAAAAYsc6sJ70yzxUBbUa7MAaidjyHKVRKSaVUU2or0oxseoqexQBAAAAYns6sKQ1AAAAAIQphAAAAACEKYTP"
    "4igfDE6Z63JxypUR0Y9MxpthauHEWX5pWz7KsfNLJi0CAAAAYQRWzBK1AAAAAECYQggAAABACLAAAAAAIC5tB9Zx"
    "rgdnEeY80NbUjURso11XG5uemLZmJ/sgmX0KAAAAhA4sAAAAAEKABQAAAAAhwAIAAAAgdGDNp83l6TfuczGyPm33"
    "7MQ8R7mTyiwAAAAAI7AAAAAACAEWAAAAAIQACwAAAIDQgRWzdGAVU6qkpnVdDW6ffc4AAAAAYQQWAAAAAIQACwAA"
    "AIAQYAEAAABA7HEHVjfSgZWG2q5yntaNNSKd8zWmDW8PAAAAEEZgAQAAAEAIsAAAAAAgBFgAAAAAhA6s0+tHGp9S"
    "Huy6ikkdWPkC6qSyVisAAACAMAILAAAAgBBgAQAAAECYQtiPpGZpdL7ggJwnTOebNPdvqs3NFUwbnOG4yRNPm7zd"
    "AAAAQBiBBQAAAAAhwAIAAACAEGABAAAAEDqwpsujpUzp9MVJeUqF0wV0Xc3SA5XGLj55cAEAAIAwAgsAAAAAQoAF"
    "AAAAACHAAgAAACB0YMWERqo0pRxrat/TVvdDKa8CAAAACCOwAAAAAAgBFgAAAACEAAsAAAAALqQDK87eEDVWpJXz"
    "+Z94Oued7FaRVlYXBgAAAIQRWAAAAACEAAsAAAAAQoAFAAAAQOjA2rw0uR1rC04OAAAAgDACCwAAAABCgAUAAABA"
    "mEL4DPKUKX3ZRwcAAAAQRmABAAAAQAiwAAAAACAEWAAAAACEDqw4S9dVpJG6KwAAAADCCCwAAAAACAEWAAAAAIQA"
    "CwAAAIAQYAEAAABACLAAAAAAQIAFAAAAQAiwAAAAAOAZVed/yDT6O3na5gAAAACEEVgAAAAAEAIsAAAAAAgBFgAA"
    "AAChAytm78bKkzbPPlIAAACAMAILAAAAAEKABQAAAAAXNIVwq+f5mYQIAAAAEEZgAQAAAEAIsAAAAAAIARYAAAAA"
    "xI51YKXR9XnK5sNdVSmljfVapS3ZyW61dCU/hAAAAEAYgQUAAABACLAAAAAAIARYAAAAAIQOrNh46dFYfdXQ2pxH"
    "eqAmdWNtS9FS9sQBAAAAhBFYAAAAAIQACwAAAABCgAUAAABA6MA6dylN6cYa2ziPV2xtpgErx7mXXeXkAQUAAAAw"
    "AgsAAACAEGABAAAAQAiwAAAAAAgdWDFHZtZHnLbtKo8WaaWJ3VixFd1YF7Dncy/Syn6sAAAAgDACCwAAAIAQYAEA"
    "AABA7OcUwjwyK3BgZc5j09RGdnIBE9iSxwgAAAAgjMACAAAAIARYAAAAABACLAAAAACIbe7AKlN/+o1zGm6Y6vOk"
    "rqvzLsbKG94eAAAAIIzAAgAAAIAQYAEAAABACLAAAAAACB1YEw45pQOry8MRWxrZPg3VSSWfMwAAAEAYgQUAAAAA"
    "IcACAAAAIARYAAAAABB73YHVDa7PeaCrKqex4G2kGytvyY1NG94eAAAAIIzAAgAAAIAQYAEAAABAbFuAZbocAAAA"
    "ALG9HVgHqRlc3w2laXmk06qNPCEcm6MYa5ZyreyJc6MAAACAMIUQAAAAgBBgAQAAAEDowAIAAAAgdGCdu2U6Hly/"
    "GjqZbiTtKkbKsdLZ25NyXM62pqRNCgAAAAgjsAAAAAAgdj7ASqYQAgAAABBbPIXwWnE0uP5xP7CyyWVsaKrgyOy6"
    "PEd1V44woQ8AAAAgTCEEAAAAIARYAAAAABB71oElNQMAAAAgtrcD60bxeHD9YN3VUaoHN04pb6xkKk3cc5ph5wAA"
    "AACEKYQAAAAAhAALAAAAAOLSd2CV7jsAAAAAsbUdWLfLjwfX/19ePr3ycb+MM1dJ5dH1acrGsanSrTmOeP6nBwAA"
    "ABCmEAIAAACAAAsAAACAEGCdkFI9sLYXpQEAAABsu6oq9qID64vf/dnxWz8oP3yh+uBORLR3Puhe+PDw7rvLf/xO"
    "DKRdeY5aq7Ql/VCaquA8parIbf/ZRfcEANipt52izH332UX3BIjzCLDKvQiwivevXXn9z36zuLj35bj35SfXDj0B"
    "wNwBVnkywPJKBwAIsADOqqrL/ejA+sXAuvrhTU8AMPMX3MnESoAFAOyYVJZrFgE2pBZgAcw7AmtNngUAcPlHYFVr"
    "FgFiUwFWtRdTCOPnA+sWD24too+nGq+6PByx9aPrJ3VgnXXjsf6q0Y1n+nPKTwuc6kfl5D8LpFqABQDslKKs1iwC"
    "bMhisccjsKqHNyOpMgdm/YJbVGsWAQDi0k8hrNYsAmzI4qDejwDr+YF17c2HngBg5i+4g2rNIgDA5W/8rNcsAmzI"
    "clnvxxTCzw8MwmpvP6ijf3rbdmSq4Nj6biiSG5xXGBF5eL7hNJd02JjRbuxHgFWvWQQAuPwB1mLNIkDsUIBlBBaw"
    "u690J79Vi6UACwDYrbedWoAFXIDl1cUeB1i3PvIEAPMqlydf6ZZe6QCA2OURWLW3HeA8XLt6EHsxhfALEX8V8X7E"
    "e58uvhjP/cGfV+XtnJucmxyrnNtf//0zVd2nv44T/w9fysPT4NLQ9Lhkzhzs4yvdyX8WKK96pQMAdkq5WK5ZBHg2"
    "VVVUVVnVZV2XdVUtFuXioF4u6+WyXl5dXLt6cOv56/sRYH13cCTY1T+Mt55e/7IHB4jBIryu6bu275rcrfp21bXH"
    "fXPUNYfd6rBbPWmPv3HjpVf/+eHbj6/dv38/Iu7evfvVL7382p9++41H716vDq6UiyvlYlkuDopqUVSLoqqKsi7K"
    "uiirVLq9AMDFv+10fdN1Tds1Xd803XHbHq/ao1V7uGoOj5vHR6tfPnr0en/v7d8vf/u287Wvv/I3f/K5525cXy6u"
    "LOsri3q5qA7q6qCu6qqsq6Iuy7oqq7Jwe4FLJ+VsaBIAAAAA20v0DgAAAEAIsAAAAADgGf0/iIUbtN836+UAAAAA"
    "SUVORK5CYII=")
STILLS = {"mag(U)": SPEED_PNG, "static(p)": PRESSURE_PNG}
#: What the same run reported: the size, the two planes' lines as a fraction
#: of the width, and the sha256 of the Viridis preset as ParaView exports it
#: (``views/viridis.json``).
STILL_SIZE = [1600, 160]
STILL_MARKS = [0.2619047619047619, 0.7380952558347154]
PRESET_SHA256 = "5b8b8756066f371cf291618a5fe31e60a23e3bb7e620cc3c4167e00dfe625f68"


def _mode(prefix: str) -> dict:
    try:
        with open(os.path.join(prefix, "standin.json"), encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def _log(prefix: str, argv: list, job: dict | None = None) -> None:
    home = os.environ.get("HOME", "")
    try:
        held = sorted(os.listdir(home)) if home else None
    except OSError:
        held = None
    row = {"argv": argv, "env": dict(os.environ), "home_held": held, "cwd": os.getcwd()}
    if job is not None and "case" in job:
        case = job["case"]
        row["job"] = job
        row["case_files"] = sorted(
            os.path.relpath(os.path.join(d, f), case).replace(os.sep, "/")
            for d, _dirs, names in os.walk(case) for f in names)
    with open(os.path.join(prefix, "calls.jsonl"), "a", encoding="utf-8") as fh:
        fh.write(json.dumps(row) + "\n")


def main(prefix: str) -> int:
    argv = sys.argv[1:]
    mode = _mode(prefix)
    if argv == ["--version"]:
        _log(prefix, argv)
        print(mode.get("banner", "paraview version 6.2.0"))
        return 0
    job_path = argv[-1]
    with open(job_path, "rb") as fh:
        raw = fh.read()
    job = json.loads(raw.decode("utf-8"))
    _log(prefix, argv, job)
    out_dir = os.path.dirname(os.path.abspath(job_path))
    kind = mode.get("mode", "ok")
    if kind == "sigabrt":
        sys.stderr.write("malloc(): invalid size (unsorted)\n")
        sys.stderr.flush()
        os.kill(os.getpid(), signal.SIGABRT)
    if kind == "hang":
        time.sleep(3600)
    if kind == "crash":
        sys.stderr.write("Traceback (most recent call last):\n  File \"_control.py\"\n"
                         "RuntimeError: no preset with name Viridis present\n")
        return 1
    if kind == "no-result":
        return 0
    if kind == "noise":
        sys.stderr.write("MESA-EGL: warning: Not allowed to force software rendering\n"
                         "(   1.128s) [pvbatch ] WARN| bad X server connection. DISPLAY=\n" * 50)
    if kind == "dirty-home":
        with open(os.path.join(os.environ["HOME"], "left-behind"), "w") as fh:
            fh.write("a file a run left in its HOME\n")
    if "case" in job:
        return _still(job, raw, out_dir, kind)
    with open(os.path.join(out_dir, "control.png"), "wb") as fh:
        fh.write(PNG)
    cells = []
    for (index, value, where, pixel, want), lit in zip(CELLS, LIT):
        if kind == "no-overrange" and where != "in":
            pixel = CLIPPED[where]
        if kind == "lit":
            pixel = lit
        cells.append({"index": index, "value": value, "where": where, "pixel": list(pixel),
                      "want": list(want)})
    done = hashlib.sha256(raw if kind != "no-done" else raw + b" ").hexdigest()
    result = {"done": done,
              "gl_renderer": "D3D12 (NVIDIA GeForce RTX 4070)" if kind == "gpu" else GL,
              "paraview": "paraview version 6.2.0",
              "png_sha256": hashlib.sha256(PNG).hexdigest(), "cells": cells}
    with open(os.path.join(out_dir, "result.json"), "w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=1, sort_keys=True)
    return 0


def _still(job: dict, raw: bytes, out_dir: str, kind: str) -> int:
    """A scene job (``views/_scene.py``): the recorded still of the job's
    field, and a result in the scene's form. The ticks are the job's two
    ends, as ``%g``; ``other-preset`` reports another preset's sha256."""
    png = STILLS.get(job["field"])
    if png is None:
        sys.stderr.write(f"the stand-in has no still of {job['field']}\n")
        return 1
    with open(os.path.join(out_dir, job["png"]), "wb") as fh:
        fh.write(png)
    lo, hi = job["range"]
    preset = PRESET_SHA256 if kind != "other-preset" else hashlib.sha256(b"Plasma").hexdigest()
    result = {"done": hashlib.sha256(raw if kind != "no-done" else raw + b" ").hexdigest(),
              "gl_renderer": "D3D12 (NVIDIA GeForce RTX 4070)" if kind == "gpu" else GL,
              "paraview": "paraview version 6.2.0", "png_sha256": hashlib.sha256(png).hexdigest(),
              "size": STILL_SIZE, "preset_sha256": preset,
              "marks": [{"at": at, "px": at * STILL_SIZE[0]} for at in STILL_MARKS],
              "ticks": [lo, hi], "tick_texts": [f"{lo:g}", f"{hi:g}"]}
    with open(os.path.join(out_dir, "result.json"), "w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=1, sort_keys=True)
    return 0


# --------------------------------------------------------------------------- #
# the install (test side)
# --------------------------------------------------------------------------- #
#: The paraview build the fake records name: the build the pack's lock holds,
#: so only the package sha256 values tell the stand-in from ParaView.
VERSION, BUILD = "6.2.0", "py312ha24fc4a_1"
PACKAGES = ("paraview", "mesalib", "mesa-libgallium", "mesa-llvmpipe", "pillow")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def install(directory: str, *, packages: dict | None = None) -> dict:
    """The stand-in under ``directory``: ``{"prefix", "bin", "packages",
    "extra_lock"}``. ``bin`` holds only the ``pvbatch62`` launcher, to put on
    PATH; ``packages`` the sha256 each fake conda record names (``packages=``
    overrides them); ``extra_lock`` the ``NOPEKIT_PVBATCH_EXTRA_LOCK`` value
    that accepts this build."""
    prefix = os.path.join(directory, "opt", "pv")
    os.makedirs(os.path.join(prefix, "bin"))
    os.makedirs(os.path.join(prefix, "conda-meta"))
    pvbatch = os.path.join(prefix, "bin", "pvbatch")
    here = os.path.dirname(os.path.abspath(__file__))
    with open(pvbatch, "w", encoding="utf-8") as fh:
        fh.write(f"#!{sys.executable}\nimport sys; sys.path.insert(0, {here!r})\n"
                 f"import _pv_standin; sys.exit(_pv_standin.main({prefix!r}))\n")
    os.chmod(pvbatch, 0o755)
    with open(pvbatch, "rb") as fh:
        pv_sha = _sha(fh.read())
    shas = {name: _sha(f"stand-in {name}".encode()) for name in PACKAGES}
    shas.update(packages or {})
    for name in PACKAGES:
        version = VERSION if name == "paraview" else "0"
        build = BUILD if name == "paraview" else "standin_0"
        record = {"name": name, "version": version, "build": build, "sha256": shas[name],
                  "paths_data": {"paths": []}}
        if name == "paraview":
            record["paths_data"]["paths"] = [{"_path": "bin/pvbatch", "path_type": "hardlink",
                                              "sha256": pv_sha, "sha256_in_prefix": pv_sha}]
        with open(os.path.join(prefix, "conda-meta", f"{name}-{version}-{build}.json"),
                  "w", encoding="utf-8") as fh:
            json.dump(record, fh)
    bin_dir = os.path.join(directory, "bin")
    os.makedirs(bin_dir)
    launcher = os.path.join(bin_dir, "pvbatch62")
    # The launcher of references/rendering.md, with the stand-in's prefix.
    with open(launcher, "w", encoding="utf-8") as fh:
        fh.write("#!/bin/sh\n# pvbatch62: the test stand-in\n"
                 f'exec env -i HOME="$HOME" PATH={prefix}/bin:/usr/bin:/bin PYTHONNOUSERSITE=1 '
                 f"GALLIUM_DRIVER=llvmpipe LIBGL_ALWAYS_SOFTWARE=1 {prefix}/bin/pvbatch "
                 f'--force-offscreen-rendering "$@"\n')
    os.chmod(launcher, 0o755)
    set_mode(prefix)
    lock = {"paraview": VERSION, "build": BUILD, "packages": shas}
    return {"prefix": prefix, "bin": bin_dir, "packages": shas, "extra_lock": json.dumps(lock)}


def set_mode(prefix: str, mode: str = "ok", *, banner: str = "paraview version 6.2.0") -> None:
    """The mode of the next calls, and the banner ``--version`` prints."""
    with open(os.path.join(prefix, "standin.json"), "w", encoding="utf-8") as fh:
        json.dump({"mode": mode, "banner": banner}, fh)


def calls(prefix: str) -> list[dict]:
    """Every call so far, oldest first."""
    try:
        with open(os.path.join(prefix, "calls.jsonl"), encoding="utf-8") as fh:
            return [json.loads(line) for line in fh if line.strip()]
    except OSError:
        return []
