# Choosing the print orientation

Orientation is the one decision in filament printing that moves four things at once,
and moves at least two of them the wrong way whatever you choose. It deserves to be
a recorded parameter with rejected alternatives, not an accident of how the model
happened to be drawn.

## What each axis choice costs

**Strength.** In-plane the part is close to the material's bulk behaviour. Across
layers it is a stack of welds worth roughly half that (see `sourcing.md`). So the
rule is: *put the layers across the load path, not along the crack you expect*. A
hook loaded downward wants its layers perpendicular to the hook's axis at the root.
A pin in shear wants the shear plane in-plane.

`fdm.layer_alignment` measures this and derates any utilisation the model carries.
It is the only gate in this pack that can catch a part that has passed a full
structural review and is still going to snap.

**Surface finish.** Three different surfaces come out of one print:

- The bed face is the flattest and most dimensionally accurate; it takes the bed's
  texture, which is a finish choice in itself.
- Top faces are ironed-smooth-ish and slightly dished on wide spans.
- Side walls carry layer lines. On a vertical wall they are even; on any slope they
  become steps whose visible width is `layer_height / tan(angle from vertical)` — at
  0.2 mm layers a 10°-from-vertical surface shows 1.1 mm steps, which is very
  visible, and a 60° one shows 0.12 mm, which is not.

**Support.** Rotating a part rarely removes overhangs; it moves them. What matters
is whether it moves them onto a face you can reach and do not care about. See
`lenses.md` lens 2.

**Time.** Time scales with layer count far more than with volume, because every
layer pays a minimum cooling time and a fixed set of travel moves. The same part
lying down and standing up can differ by 2–3×. Standing tall also raises the risk of
a knock-off and usually needs a brim.

## The procedure

1. **Name the load path** and the plane you expect it to break on. Write it into
   the model as `load_axis`.
2. **Pick the orientation that puts the layers across that path**, and check
   `fdm.layer_alignment` passes with the structural utilisation applied.
3. **Check what that orientation did to the overhangs** with `fdm.overhang`, and to
   the spans with `fdm.bridge_span`.
4. If the result needs support, **try to design the support away** before accepting
   it: chamfer the overhang to 45°, teardrop a horizontal hole, split the part.
5. **Record what lost.** "Printed flat rather than on end: on end the layer
   alignment was right but the 90 mm tower needed a brim and a draft shield, and
   the first attempt knocked off at 60 mm." That sentence saves the next person a
   day.

## The three orientations worth trying first

For most functional parts the candidates are:

- **Flat on the largest face.** Fastest, best adhesion, least support. Layers run
  parallel to that face, so any load that tries to peel the part apart through its
  thickness is loading welds.
- **On end.** Usually the right layer direction for a part loaded along its length,
  and usually the slowest and the most fragile on the bed.
- **Tipped 45°.** Occasionally the compromise that removes support from two opposed
  overhangs at once, at the cost of surface finish everywhere and support underneath
  the whole part.

If none of the three works, the part probably wants splitting. A well-chosen split
plane plus a glued or dowelled joint is a legitimate design decision, not a defeat —
and it frequently produces a *stronger* part than the one-piece version, because
both halves can be oriented for their own load path.

## Setting `build_axis`

The gates default to `[0, 0, 1]`. Set `build_axis` explicitly in the projection when
the exported mesh is not in its print orientation, rather than re-exporting the mesh
— one parameter with a rationale beats a second copy of the geometry (rule 1). The
mesh gates then measure every angle against the axis you named.
