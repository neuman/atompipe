# KiCad 3D models for the baseline board

`SOT-23-6.step` and `PinHeader_1x04_P2.54mm_Vertical.step` are KiCad's own models
for the baseline's two footprints, copied unchanged from the kicad-packages3D
library at tag 9.0.0:

    https://gitlab.com/kicad/libraries/kicad-packages3D/-/raw/9.0.0/Package_TO_SOT_SMD.3dshapes/SOT-23-6.step
    https://gitlab.com/kicad/libraries/kicad-packages3D/-/raw/9.0.0/Connector_PinHeader_2.54mm.3dshapes/PinHeader_1x04_P2.54mm_Vertical.step

They are licensed CC-BY-SA 4.0 with the KiCad libraries' exception for designs
that use them, as each file's header states; the copyright is the KiCad library
contributors'. They are here so `pcb.enclosure_fit` sees the same parts on every
host: `kicad-cli pcb export step` silently leaves out a part whose model it cannot
find, and many hosts install KiCad without its 3D library. The baseline board
names them as `${KIPRJMOD}/3d/<name>.step`.
