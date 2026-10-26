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
writes names its buffers as files beside it). ``--shape lit`` writes a
sphere with vertex colours (`LIT_GLB`) for a lit 3D view, in place of the
box. Run: ``python3 tests/_draw_standin.py --png OUT --entry E --value V
[--glb OUT] [--field PATH] [--mode MODE] [--shape box|lit]``.
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

#: A sphere of radius 0.5 whose vertex colours run through five stops of
#: Turbo from its bottom to its top, as GLB, for a lit 3D view (design P2:
#: ``--shape lit``), written by trimesh 5.1.0 on 2026-10-23:
#: ``s = trimesh.creation.icosphere(subdivisions=2, radius=0.5)``, each
#: vertex's colour the stops (48,18,59), (40,188,235), (164,252,60),
#: (251,128,34), (122,4,3) linear in (z + 0.5) and rounded, alpha 255,
#: ``trimesh.Scene(s).export(file_type="glb")``. It holds POSITION and
#: COLOR_0 (UNSIGNED_BYTE) and no NORMAL, as ParaView's glTF holds none.
LIT_GLB = base64.b64decode(
    "Z2xURgIAAACYHAAAXAMAAEpTT057InNjZW5lIjowLCJzY2VuZXMiOlt7Im5vZGVzIjpbMF19XSwiYXNzZXQi"
    "OnsidmVyc2lvbiI6IjIuMCIsImdlbmVyYXRvciI6Imh0dHBzOi8vZ2l0aHViLmNvbS9taWtlZGgvdHJpbWVz"
    "aCJ9LCJhY2Nlc3NvcnMiOlt7ImNvbXBvbmVudFR5cGUiOjUxMjUsInR5cGUiOiJTQ0FMQVIiLCJidWZmZXJW"
    "aWV3IjowLCJjb3VudCI6OTYwLCJtYXgiOlsxNjFdLCJtaW4iOlswXX0seyJjb21wb25lbnRUeXBlIjo1MTI2"
    "LCJ0eXBlIjoiVkVDMyIsImJ5dGVPZmZzZXQiOjAsImJ1ZmZlclZpZXciOjEsImNvdW50IjoxNjIsIm1heCI6"
    "WzAuNSwwLjUsMC41XSwibWluIjpbLTAuNSwtMC41LC0wLjVdfSx7ImNvbXBvbmVudFR5cGUiOjUxMjEsIm5v"
    "cm1hbGl6ZWQiOnRydWUsInR5cGUiOiJWRUM0IiwiYnl0ZU9mZnNldCI6MCwiYnVmZmVyVmlldyI6MiwiY291"
    "bnQiOjE2MiwibWF4IjpbMjUxLDI1MiwyMzUsMjU1XSwibWluIjpbNDAsNCwzLDI1NV19XSwibWVzaGVzIjpb"
    "eyJuYW1lIjoiZ2VvbWV0cnlfMCIsImV4dHJhcyI6eyJzaGFwZSI6InNwaGVyZSIsInJhZGl1cyI6MC41fSwi"
    "cHJpbWl0aXZlcyI6W3siYXR0cmlidXRlcyI6eyJQT1NJVElPTiI6MSwiQ09MT1JfMCI6Mn0sImluZGljZXMi"
    "OjAsIm1vZGUiOjR9XX1dLCJub2RlcyI6W3sibmFtZSI6Imdlb21ldHJ5XzAiLCJtZXNoIjowfV0sImJ1ZmZl"
    "cnMiOlt7ImJ5dGVMZW5ndGgiOjY0MzJ9XSwiYnVmZmVyVmlld3MiOlt7ImJ1ZmZlciI6MCwiYnl0ZU9mZnNl"
    "dCI6MCwiYnl0ZUxlbmd0aCI6Mzg0MH0seyJidWZmZXIiOjAsImJ5dGVPZmZzZXQiOjM4NDAsImJ5dGVMZW5n"
    "dGgiOjE5NDR9LHsiYnVmZmVyIjowLCJieXRlT2Zmc2V0Ijo1Nzg0LCJieXRlTGVuZ3RoIjo2NDh9XX0gICAZ"
    "AABCSU4AAAAAAIkAAAA1AAAAiQAAACUAAACLAAAANQAAAIsAAAAQAAAAiQAAAIsAAAA1AAAAJQAAAIoAAACa"
    "AAAAigAAAAsAAACXAAAAmgAAAJcAAAAoAAAAigAAAJcAAACaAAAAEAAAAJgAAAA2AAAAmAAAACgAAACWAAAA"
    "NgAAAJYAAAAFAAAAmAAAAJYAAAA2AAAAJQAAAJoAAACLAAAAmgAAACgAAACYAAAAiwAAAJgAAAAQAAAAmgAA"
    "AJgAAACLAAAAAAAAADUAAAAqAAAANQAAABAAAAA3AAAAKgAAADcAAAAMAAAANQAAADcAAAAqAAAAEAAAADYA"
    "AAA7AAAANgAAAAUAAAA5AAAAOwAAADkAAAARAAAANgAAADkAAAA7AAAADAAAADoAAAArAAAAOgAAABEAAAA4"
    "AAAAKwAAADgAAAABAAAAOgAAADgAAAArAAAAEAAAADsAAAA3AAAAOwAAABEAAAA6AAAANwAAADoAAAAMAAAA"
    "OwAAADoAAAA3AAAAAAAAACoAAABFAAAAKgAAAAwAAABHAAAARQAAAEcAAAAVAAAAKgAAAEcAAABFAAAADAAA"
    "ACsAAABKAAAAKwAAAAEAAABIAAAASgAAAEgAAAAWAAAAKwAAAEgAAABKAAAAFQAAAEsAAABGAAAASwAAABYA"
    "AABJAAAARgAAAEkAAAAHAAAASwAAAEkAAABGAAAADAAAAEoAAABHAAAASgAAABYAAABLAAAARwAAAEsAAAAV"
    "AAAASgAAAEsAAABHAAAAAAAAAEUAAAB4AAAARQAAABUAAAB6AAAAeAAAAHoAAAAhAAAARQAAAHoAAAB4AAAA"
    "FQAAAEYAAACFAAAARgAAAAcAAACDAAAAhQAAAIMAAAAkAAAARgAAAIMAAACFAAAAIQAAAIcAAAB5AAAAhwAA"
    "ACQAAACEAAAAeQAAAIQAAAAKAAAAhwAAAIQAAAB5AAAAFQAAAIUAAAB6AAAAhQAAACQAAACHAAAAegAAAIcA"
    "AAAhAAAAhQAAAIcAAAB6AAAAAAAAAHgAAACJAAAAeAAAACEAAACMAAAAiQAAAIwAAAAlAAAAeAAAAIwAAACJ"
    "AAAAIQAAAHkAAACeAAAAeQAAAAoAAACcAAAAngAAAJwAAAApAAAAeQAAAJwAAACeAAAAJQAAAKAAAACKAAAA"
    "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"
    "FAAAAFYAAABTAAAAVgAAABoAAABYAAAAUwAAAFgAAAAZAAAAVgAAAFgAAABTAAAAAwAAAFEAAABjAAAAUQAA"
    "ABkAAABmAAAAYwAAAGYAAAAdAAAAUQAAAGYAAABjAAAAGQAAAFIAAAB1AAAAUgAAAAgAAAByAAAAdQAAAHIA"
    "AAAgAAAAUgAAAHIAAAB1AAAAHQAAAHcAAABkAAAAdwAAACAAAABzAAAAZAAAAHMAAAAJAAAAdwAAAHMAAABk"
    "AAAAGQAAAHUAAABmAAAAdQAAACAAAAB3AAAAZgAAAHcAAAAdAAAAdQAAAHcAAABmAAAABAAAAGcAAAA8AAAA"
    "ZwAAAB4AAABqAAAAPAAAAGoAAAASAAAAZwAAAGoAAAA8AAAAHgAAAGgAAABxAAAAaAAAAAkAAABtAAAAcQAA"
    "AG0AAAAfAAAAaAAAAG0AAABxAAAAEgAAAG8AAAA9AAAAbwAAAB8AAABsAAAAPQAAAGwAAAAFAAAAbwAAAGwA"
    "AAA9AAAAHgAAAHEAAABqAAAAcQAAAB8AAABvAAAAagAAAG8AAAASAAAAcQAAAG8AAABqAAAAAgAAAC4AAACN"
    "AAAALgAAAA4AAACPAAAAjQAAAI8AAAAmAAAALgAAAI8AAACNAAAADgAAAC8AAACTAAAALwAAAAQAAACRAAAA"
    "kwAAAJEAAAAnAAAALwAAAJEAAACTAAAAJgAAAJUAAACOAAAAlQAAACcAAACSAAAAjgAAAJIAAAALAAAAlQAA"
    "AJIAAACOAAAADgAAAJMAAACPAAAAkwAAACcAAACVAAAAjwAAAJUAAAAmAAAAkwAAAJUAAACPAAAABgAAAD8A"
    "AAB+AAAAPwAAABMAAACAAAAAfgAAAIAAAAAjAAAAPwAAAIAAAAB+AAAAEwAAAD4AAAB9AAAAPgAAAAIAAAB7"
    "AAAAfQAAAHsAAAAiAAAAPgAAAHsAAAB9AAAAIwAAAIIAAAB/AAAAggAAACIAAAB8AAAAfwAAAHwAAAAKAAAA"
    "ggAAAHwAAAB/AAAAEwAAAH0AAACAAAAAfQAAACIAAACCAAAAgAAAAIIAAAAjAAAAfQAAAIIAAACAAAAACAAA"
    "AFUAAABaAAAAVQAAABoAAABeAAAAWgAAAF4AAAAbAAAAVQAAAF4AAABaAAAAGgAAAFQAAABXAAAAVAAAAAYA"
    "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"
    "sz4aeqS919fcvo4QBT6kJl6+GHmWvkgtsD5AxFm+mZuxvlG5s74aeqS919fcvo4QBb6kJl6+GHmWvkgtsL5A"
    "xFm+jhAFvqQmXr7X19y+Ubmzvhp6pL2Zm7G+QMRZvhh5lr5ILbC+UJYGvuBbpr1xePO+SC2wvkDEWb4YeZa+"
    "jhAFvqQmXj7X19y+Ubmzvhp6pD2Zm7G+QMRZvhh5lj5ILbC+UJYGvuBbpj1xePO+SC2wvkDEWT4YeZa+UJaG"
    "vgAAAABAxNm+mZuxvlG5sz4aeqQ919fcvo4QBT6kJl4+GHmWvkgtsD5AxFk+QMTZvlCWhj4AAAAAmZuxvlG5"
    "s74aeqQ919fcvo4QBb6kJl4+GHmWvkgtsL5AxFk+QMTZvlCWhr4AAAAAjhAFvqQmXr7X19w+Ubmzvhp6pL2Z"
    "m7E+QMRZvhh5lr5ILbA+UJYGvuBbpr1xePM+SC2wvkDEWb4YeZY+jhAFvqQmXj7X19w+Ubmzvhp6pD2Zm7E+"
    "QMRZvhh5lj5ILbA+UJYGvuBbpj1xePM+SC2wvkDEWT4YeZY+UJaGvgAAAABAxNk+mEH2vgAAAACX6Qu+mEH2"
    "vgAAAACX6Qs+cXjzvlCWBj7gW6a9cXjzvlCWBr7gW6a9cXjzvlCWBj7gW6Y9cXjzvlCWBr7gW6Y9pPw8/6T8"
    "PP+k/Dz/pPw8/6EpDP+hKQz/LkVw/y5FcP8os+L/9Hog/yiz4v/0eiD/pPw8/6T8PP/7gCL/+4Ai//uAIv/7"
    "gCL/egQD/yi86/8ovOv/KLzr/yi86/8wEjv/V9So/1fUqP8tU37/LVN+/9qvLP/aryz/qzMP/6szD/+k/Dz/"
    "V9So/1fUqP8tU37/LVN+/9qvLP/aryz/qzMP/6szD/+k/Dz/pPw8/6T8PP+k/Dz/pPw8/9G8Lv/HThX/0rsu"
    "/9G8Lv/HThX/0rsu//R6IP/RvC7/x04V/9K7Lv/RvC7/x04V/9K7Lv/0eiD/hA0F/4QNBf9k25f/K3ek/2Pa"
    "mP9k25f/K3ek/2PamP8os+L/ZNuX/yt3pP9j2pj/ZNuX/yt3pP9j2pj/KLPi/y8fSP8vH0j/fOd0/zjE1P87"
    "xtH/fOd0/zjE1P87xtH/LkFr/yt6p/8rfKn/LyNM/ymezP8uQWv/K3qn/yt8qf8vI0z/KZ7M/y5FcP/A1DT/"
    "75Al/+6TJv+k/Dz/wNQ0/++QJf/ukyb/pPw8/50mDP/JUBb/ylEW/4cQBv/kah3/nSYM/8lQFv/KURb/hxAG"
    "/+RqHf+hKQz/YNmc/9S4Lv9853X/fOd1/8DUNP/A1DT/fOd0/zjE1P87xtH/fOd0/zjE1P87xtH/LkFr/yt6"
    "p/8rfKn/LyNM/ymezP8uQWv/K3qn/yt8qf8vI0z/KZ7M/y5FcP/A1DT/75Al/+6TJv+k/Dz/wNQ0/++QJf/u"
    "kyb/pPw8/50mDP/JUBb/ylEW/4cQBv/kah3/nSYM/8lQFv/KURb/hxAG/+RqHf+hKQz/YNmc/9S4Lv9853X/"
    "fOd1/8DUNP/A1DT/"
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
    parser.add_argument("--shape", default="box", choices=("box", "lit"))
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
        solid = LIT_GLB if args.shape == "lit" else GLB
        if args.glb.endswith(".gltf"):
            solid = GLTF_OUTSIDE if args.mode == "gltf-outside" else GLTF
        with open(args.glb, "wb") as fh:
            fh.write(solid)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
