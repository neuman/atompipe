# SPDX-License-Identifier: Apache-2.0
"""A stand-in renderer for bound figures (issue #15, B.6): installed by
``tests/test_figures.py`` as ``nopekit-test-draw`` on a temporary PATH, it
plays the part ParaView's ``pvbatch`` plays for the CFD pack. It never runs
inside nopekit's process: a bound viewgen calls it as a subprocess, under the
viewgen's own timeout, as a pack calls its renderer.

It draws nothing. It writes committed fixture bytes (rule 0.4 of the issue's
design: a stand-in writes bytes a trusted tool made, and grows no codec): a
4x1 PNG Pillow 12.2.0 wrote and a box GLB trimesh 5.1.0 exported, both on
2026-10-21. What the tests need from it is what it was asked and when: each
call is a JSON line in ``$NOPEKIT_TEST_DRAW_LOG`` (the entry, the value, the
mode), so a test can say which result a picture was drawn from.

``--mode`` plants each fault the spine must survive:
``ok``; ``crash`` (exit 3); ``hang`` (sleeps past any timeout);
``oversize`` (a PNG of 2.1 MiB, over the 2 MiB cap); ``move-inputs`` (appends
to the bound field file while it draws); ``gltf-outside`` (the ``.gltf`` it
writes names its buffers as files beside it). Run:
``python3 tests/_draw_standin.py --png OUT --entry E --value V [--glb OUT]
[--field PATH] [--mode MODE]``.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time

#: A 4x1 RGB PNG, every pixel viridis's first stop (68, 1, 84), written by
#: Pillow 12.2.0 (``Image.new("RGB", (4, 1), (68, 1, 84)).save(..., "PNG")``).
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAQAAAABCAIAAAB2XpiaAAAADklEQVR4nGN0YQxhgAEABp0Am/mZMJYAAAAASUVORK5CYII=")

#: A unit box as GLB, written by trimesh 5.1.0
#: (``trimesh.Scene(trimesh.creation.box()).export(file_type="glb")``).
GLB = base64.b64decode(
    "Z2xURgIAAACgAwAAlAIAAEpTT057InNjZW5lIjowLCJzY2VuZXMiOlt7Im5vZGVzIjpbMF19XSwiYXNz"
    "ZXQiOnsidmVyc2lvbiI6IjIuMCIsImdlbmVyYXRvciI6Imh0dHBzOi8vZ2l0aHViLmNvbS9taWtlZGgv"
    "dHJpbWVzaCJ9LCJhY2Nlc3NvcnMiOlt7ImNvbXBvbmVudFR5cGUiOjUxMjUsInR5cGUiOiJTQ0FMQVIi"
    "LCJidWZmZXJWaWV3IjowLCJjb3VudCI6MzYsIm1heCI6WzddLCJtaW4iOlswXX0seyJjb21wb25lbnRU"
    "eXBlIjo1MTI2LCJ0eXBlIjoiVkVDMyIsImJ5dGVPZmZzZXQiOjAsImJ1ZmZlclZpZXciOjEsImNvdW50"
    "Ijo4LCJtYXgiOlswLjUsMC41LDAuNV0sIm1pbiI6Wy0wLjUsLTAuNSwtMC41XX1dLCJtZXNoZXMiOlt7"
    "Im5hbWUiOiJnZW9tZXRyeV8wIiwiZXh0cmFzIjp7InNoYXBlIjoiYm94IiwiZXh0ZW50cyI6WzEuMCwx"
    "LjAsMS4wXX0sInByaW1pdGl2ZXMiOlt7ImF0dHJpYnV0ZXMiOnsiUE9TSVRJT04iOjF9LCJpbmRpY2Vz"
    "IjowLCJtb2RlIjo0fV19XSwibm9kZXMiOlt7Im5hbWUiOiJnZW9tZXRyeV8wIiwibWVzaCI6MH1dLCJi"
    "dWZmZXJzIjpbeyJieXRlTGVuZ3RoIjoyNDB9XSwiYnVmZmVyVmlld3MiOlt7ImJ1ZmZlciI6MCwiYnl0"
    "ZU9mZnNldCI6MCwiYnl0ZUxlbmd0aCI6MTQ0fSx7ImJ1ZmZlciI6MCwiYnl0ZU9mZnNldCI6MTQ0LCJi"
    "eXRlTGVuZ3RoIjo5Nn1dfSAgICDwAAAAQklOAAEAAAADAAAAAAAAAAQAAAABAAAAAAAAAAAAAAADAAAA"
    "AgAAAAIAAAAEAAAAAAAAAAEAAAAHAAAAAwAAAAUAAAABAAAABAAAAAUAAAAHAAAAAQAAAAMAAAAHAAAA"
    "AgAAAAYAAAAEAAAAAgAAAAIAAAAHAAAABgAAAAYAAAAFAAAABAAAAAcAAAAFAAAABgAAAAAAAL8AAAC/"
    "AAAAvwAAAL8AAAC/AAAAPwAAAL8AAAA/AAAAvwAAAL8AAAA/AAAAPwAAAD8AAAC/AAAAvwAAAD8AAAC/"
    "AAAAPwAAAD8AAAA/AAAAvwAAAD8AAAA/AAAAPw=="
)

#: The same box as a glTF that holds its buffers inside it (``data:`` URIs),
#: written by trimesh 5.1.0 (``trimesh.Scene(trimesh.creation.box()).export(
#: file_type="gltf", embed_buffers=True)["model.gltf"]``): ParaView's form of
#: a 3D file. Written when ``--glb`` names a ``.gltf``.
GLTF = (
    '{"scene":0,"scenes":[{"nodes":[0]}],"asset":{"version":"2.0","generator":"https://github'
    '.com/mikedh/trimesh"},"accessors":[{"componentType":5125,"type":"SCALAR","bufferView":0,'
    '"count":36,"max":[7],"min":[0]},{"componentType":5126,"type":"VEC3","byteOffset":0,"buff'
    'erView":1,"count":8,"max":[0.5,0.5,0.5],"min":[-0.5,-0.5,-0.5]}],"meshes":[{"name":"geom'
    'etry_0","extras":{"shape":"box","extents":[1.0,1.0,1.0]},"primitives":[{"attributes":{"P'
    'OSITION":1},"indices":0,"mode":4}]}],"nodes":[{"name":"geometry_0","mesh":0}],"buffers":'
    '[{"uri":"data:application/octet-stream;base64,AQAAAAMAAAAAAAAABAAAAAEAAAAAAAAAAAAAAAMAAA'
    'ACAAAAAgAAAAQAAAAAAAAAAQAAAAcAAAADAAAABQAAAAEAAAAEAAAABQAAAAcAAAABAAAAAwAAAAcAAAACAAAABg'
    'AAAAQAAAACAAAAAgAAAAcAAAAGAAAABgAAAAUAAAAEAAAABwAAAAUAAAAGAAAA","byteLength":144},{"uri"'
    ':"data:application/octet-stream;base64,AAAAvwAAAL8AAAC/AAAAvwAAAL8AAAA/AAAAvwAAAD8AAAC/A'
    'AAAvwAAAD8AAAA/AAAAPwAAAL8AAAC/AAAAPwAAAL8AAAA/AAAAPwAAAD8AAAC/AAAAPwAAAD8AAAA/","byteLe'
    'ngth":96}],"bufferViews":[{"buffer":0,"byteOffset":0,"byteLength":144},{"buffer":1,"byte'
    'Offset":0,"byteLength":96}]}'
).encode("utf-8")

#: The ``gltf-outside`` mode's file: the same box with its buffers in files
#: beside it (``export(file_type="gltf")["model.gltf"]``), which the page would
#: fetch unchecked, so the spine refuses it.
GLTF_OUTSIDE = (
    '{"scene":0,"scenes":[{"nodes":[0]}],"asset":{"version":"2.0","generator":"https://github'
    '.com/mikedh/trimesh"},"accessors":[{"componentType":5125,"type":"SCALAR","bufferView":0,'
    '"count":36,"max":[7],"min":[0]},{"componentType":5126,"type":"VEC3","byteOffset":0,"buff'
    'erView":1,"count":8,"max":[0.5,0.5,0.5],"min":[-0.5,-0.5,-0.5]}],"meshes":[{"name":"geom'
    'etry_0","extras":{"shape":"box","extents":[1.0,1.0,1.0]},"primitives":[{"attributes":{"P'
    'OSITION":1},"indices":0,"mode":4}]}],"nodes":[{"name":"geometry_0","mesh":0}],"buffers":'
    '[{"uri":"gltf_buffer_0.bin","byteLength":144},{"uri":"gltf_buffer_1.bin","byteLength":96'
    '}],"bufferViews":[{"buffer":0,"byteOffset":0,"byteLength":144},{"buffer":1,"byteOffset":'
    '0,"byteLength":96}]}'
).encode("utf-8")

#: The oversize mode's size: 2.1 MiB, past the spine's 2 MiB cap
#: (`page.EVIDENCE_MAX_BYTES`), so the write is refused, never truncated.
OVERSIZE = int(2.1 * 1024 * 1024)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="nopekit-test-draw")
    parser.add_argument("--png", required=True)
    parser.add_argument("--glb", default="")
    parser.add_argument("--field", default="")
    parser.add_argument("--entry", default="")
    parser.add_argument("--value", default="")
    parser.add_argument("--mode", default="ok")
    args = parser.parse_args(argv)
    log = os.environ.get("NOPEKIT_TEST_DRAW_LOG", "")
    if log:
        with open(log, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"entry": args.entry, "value": args.value,
                                 "mode": args.mode}) + "\n")
    if args.mode == "crash":
        print("nopekit-test-draw: planted crash", file=sys.stderr)
        return 3
    if args.mode == "hang":
        time.sleep(120)
        return 0
    if args.mode == "move-inputs" and args.field:
        with open(args.field, "ab") as fh:
            fh.write(b"moved while it was drawn\n")
    payload = PNG + (b"\0" * OVERSIZE if args.mode == "oversize" else b"")
    with open(args.png, "wb") as fh:
        fh.write(payload)
    if args.glb:
        solid = GLB
        if args.glb.endswith(".gltf"):
            solid = GLTF_OUTSIDE if args.mode == "gltf-outside" else GLTF
        with open(args.glb, "wb") as fh:
            fh.write(solid)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
