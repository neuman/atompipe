# SPDX-License-Identifier: Apache-2.0
"""Render a real CalculiX result for the README; run with PYTHONPATH=src.

python3 packs/topology-simp/references/make_figure.py --out /tmp/simp-figure --png docs/img/packs/topology-simp-stress.png
"""
import argparse
import json
from pathlib import Path
import numpy as np
from nopekit import packs
from nopekit.modelio import load_path

if __name__ == "__main__":
    ap=argparse.ArgumentParser();ap.add_argument('--out',required=True);ap.add_argument('--png',required=True)
    a=ap.parse_args();root=Path(__file__).resolve().parents[1]
    part=load_path(str(root/'gates/_part.py'));ccx=load_path(str(root/'gates/_ccx.py'))
    ctx=packs.baseline_context(str(root),out_dir=a.out)
    result,evidence=part.solve(ctx,part.case(ctx),'figure')
    deck=Path(next(p for p in evidence if p.endswith('fine.inp')))
    nodes,tets=[],[];section=None
    for line in deck.read_text().splitlines():
        if line.startswith('*'):
            section='nodes' if line=='*NODE' else ('elements' if line.startswith('*ELEMENT,TYPE=C3D10') else None)
        elif section=='nodes':nodes.append([float(x) for x in line.split(',')[1:]])
        elif section=='elements':tets.append([int(x)-1 for x in line.split(',')[1:]])
    nodes,tets=np.array(nodes),np.array(tets)
    S=ccx.frd_blocks(str(deck.with_suffix('')),'STRESS')[0]
    vm=ccx.von_mises(S)
    faces=np.concatenate([tets[:,i] for i in ([0,1,2],[0,1,3],[0,2,3],[1,2,3])])
    _,inverse,count=np.unique(np.sort(faces,axis=1),axis=0,return_inverse=True,return_counts=True)
    faces=faces[count[inverse]==1]
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from mpl_toolkits.mplot3d.art3d import Poly3DCollection
    from matplotlib.colors import Normalize
    fig=plt.figure(figsize=(9,5),facecolor='#101f30');ax=fig.add_subplot(projection='3d',facecolor='#101f30')
    norm=Normalize(0,float(vm.max()));cmap=plt.get_cmap('inferno')
    surface=Poly3DCollection(nodes[faces],facecolors=cmap(norm(vm[faces].mean(axis=1))),linewidths=.08,edgecolors='#203040')
    ax.add_collection3d(surface);ax.set_xlim(0,40);ax.set_ylim(0,8);ax.set_zlim(0,8)
    ax.set_box_aspect((40,8,8));ax.view_init(elev=24,azim=-62);ax.set_axis_off()
    fig.text(.06,.9,'Check the shape that will be built',color='white',size=20,weight='bold')
    fig.text(.06,.83,'CalculiX · 1 N end load · 40 × 8 × 8 mm cantilever',color='#b8cbdc',size=12)
    bar=fig.colorbar(plt.cm.ScalarMappable(norm=norm,cmap=cmap),ax=ax,shrink=.5,pad=.01)
    bar.set_label('von Mises stress (MPa)',color='white');bar.ax.tick_params(colors='white')
    fig.text(.06,.1,'Full stress field shown; the gate judges only the region 8 ≤ x ≤ 32 mm.',color='#b8cbdc',size=10)
    fig.text(.06,.05,f"Checked region: {result['stress_mpa']:.3f} MPa · Max displacement: {result['displacement_mm']:.4f} mm",color='#63d5c1',size=12)
    fig.savefig(a.png,dpi=150,facecolor=fig.get_facecolor());plt.close(fig)
    Path(a.out,'result.json').write_text(json.dumps(result,indent=2)+'\n')
