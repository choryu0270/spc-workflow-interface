# SPC workflow interface

GUI for data processing of the the Single Photon Counting (SPC) spectrometer on J-KAREN-P facility.

## Requirements

Python packages:

- numpy
- matplotlib
- imageio
- pillow

System tools:

- Python with tkinter support
- gfortran, for compiling `spc.f90`

The shot-sheet reader uses Python standard-library modules for `.xlsx` parsing.

## Run

From a terminal, activate the Python environment that contains the required
packages, then change into this interface folder and run:

```bash
cd /path/to/spc-script/spc_interface
python spc_gui.py
```

If the interface folder is inside a cloned or copied SPC script directory,
replace `/path/to/spc-script/spc_interface` with that local path.

## Workflow

1. Select multiple background tif files manually, or select a shot sheet plus
   experiment folder for automatic background-shot selection. Then click
   `Create B.tif`. The GUI creates `Backgrounds` inside the experiment folder,
   moves those files there, and creates `B.tif`.
2. Subtract `B.tif` from the remaining raw tif files in the experiment folder.
   Output is saved to `Background Subtracted`.
3. Compile the copied `spc.f90` to the local `spc` executable.
4. Run `spc` on `Background Subtracted` and save `Single Photon Image`.
5. Plot spectra from `Single Photon Image`. The generated PNG spectra are loaded into the preview panel on the right.

Notes:

- Plot output is saved as `.png`.
- Use Previous/Next to preview generated PNG spectra. Use Export current to PDF
  to save the currently displayed spectrum as a single-page PDF.
- Use Load PNG folder in the preview panel to browse previously generated
  spectra without running the full workflow.
- Automatic background selection reads the first worksheet of the shot sheet:
  rows whose `W-PM` value contains `blank` or `trigger` are matched to `.tif` files
  ending in `_Shot_No.tif`. If it does not work, try to choose background `.tif` files manually.
- Step 1 moves the selected background files into `[experiment folder]/Backgrounds`.
  If you need to keep originals in place, duplicate them before using the GUI.

## Acknowledgement

The original SPC code was developed by Dr. E.G. Hill and Dr. H.F. Lowe 
at Imperial College London. Many thanks to them for the original version and
coding foundation.
