#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SPC workflow GUI by Dr.C.Liu@HZDR.

This interface wraps the existing SPC workflow without modifying the original
scripts:
1. calculate average background
2. subtract background
3. compile spc.f90
4. generate single photon images (SPI)
5. plot spectra
"""

import glob
import math
import os
import pickle
import queue
import shutil
import subprocess
import tempfile
import threading
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from tkinter import (
    BOTH,
    END,
    LEFT,
    NW,
    RIGHT,
    X,
    Y,
    Button,
    Entry,
    Frame,
    Label,
    LabelFrame,
    StringVar,
    Tk,
    filedialog,
    messagebox,
)
from tkinter.scrolledtext import ScrolledText

os.environ.setdefault(
    "MPLCONFIGDIR",
    str(Path(tempfile.gettempdir()) / "spc_gui_matplotlib"),
)
os.environ.setdefault(
    "XDG_CACHE_HOME",
    str(Path(tempfile.gettempdir()) / "spc_gui_cache"),
)

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from PIL import Image, ImageTk

try:
    import imageio.v2 as imageio
except ImportError:
    import imageio


PROJECT_DIR = Path(__file__).resolve().parent
REPO_DIR = PROJECT_DIR.parent


def tif_files(folder):
    return sorted(glob.glob(str(Path(folder).expanduser() / "*.tif")))


def read_tif(path):
    return np.array(imageio.imread(path))


def write_tif(path, data):
    imageio.imwrite(path, data)


def ensure_dir(path):
    Path(path).expanduser().mkdir(parents=True, exist_ok=True)


def load_response_data(filter_file, qe_file):
    with open(filter_file, "rb") as f1:
        energy, be, kap = pickle.load(f1)

    with open(qe_file, "rb") as f2:
        qe = pickle.load(f2)

    energy = np.concatenate((energy, np.linspace(30100, 70000, 400)), axis=0) / 1000
    be = np.concatenate((be, np.ones(400) * be[-1]), axis=0)
    kap = np.concatenate((kap, np.ones(400) * kap[-1]), axis=0)
    return energy, be, kap, qe


def safe_response(be_vals, kap_vals, qe_vals):
    denominator = be_vals * kap_vals * qe_vals
    return np.divide(
        1.0,
        denominator,
        out=np.zeros_like(denominator, dtype=float),
        where=denominator > 0,
    )


def cell_column(cell_reference):
    letters = "".join(ch for ch in cell_reference if ch.isalpha())
    index = 0
    for letter in letters:
        index = index * 26 + ord(letter.upper()) - ord("A") + 1
    return index - 1


def read_xlsx_first_sheet_rows(path):
    ns = {"a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    with zipfile.ZipFile(path) as archive:
        shared_strings = []
        if "xl/sharedStrings.xml" in archive.namelist():
            root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
            for item in root.findall("a:si", ns):
                text = "".join(node.text or "" for node in item.findall(".//a:t", ns))
                shared_strings.append(text)

        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        first_sheet = workbook.find("a:sheets/a:sheet", ns)
        relationship_id = first_sheet.attrib[
            "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
        ]

        rels = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        rel_ns = {"r": "http://schemas.openxmlformats.org/package/2006/relationships"}
        sheet_target = None
        for rel in rels.findall("r:Relationship", rel_ns):
            if rel.attrib.get("Id") == relationship_id:
                sheet_target = rel.attrib["Target"]
                break
        if sheet_target is None:
            raise RuntimeError("Cannot find first worksheet in shot sheet.")

        sheet_target = sheet_target.lstrip("/")
        if sheet_target.startswith("xl/"):
            sheet_path = sheet_target
        else:
            sheet_path = "xl/" + sheet_target
        sheet = ET.fromstring(archive.read(sheet_path))

    rows = []
    for row in sheet.findall("a:sheetData/a:row", ns):
        values = []
        for cell in row.findall("a:c", ns):
            col = cell_column(cell.attrib.get("r", "A1"))
            while len(values) <= col:
                values.append(None)

            cell_type = cell.attrib.get("t")
            value_node = cell.find("a:v", ns)
            inline_node = cell.find("a:is/a:t", ns)
            if cell_type == "s" and value_node is not None:
                value = shared_strings[int(value_node.text)]
            elif cell_type == "inlineStr" and inline_node is not None:
                value = inline_node.text
            elif value_node is not None:
                raw = value_node.text
                try:
                    value = int(float(raw))
                except (TypeError, ValueError):
                    value = raw
            else:
                value = None
            values[col] = value
        rows.append(values)
    return rows


class SpcGui:
    def __init__(self, root):
        self.root = root
        self.root.title("SPC workflow interface")
        self.log_queue = queue.Queue()

        self.background_files = []
        self.background_mode = None
        self.experiment_dir = None
        self.shot_sheet_file = None
        self.shot_metadata = {}
        self.background_dir = None
        self.background_file = None
        self.background_subtracted_dir = None
        self.spi_output_dir = None
        self.spectra_output_dir = None
        self.f90_file = PROJECT_DIR / "spc.f90"
        self.executable_file = PROJECT_DIR / "spc"

        self.bg_files_status = StringVar(value="No background files selected")
        self.bg_save_status = StringVar(value="Backgrounds folder: not set")
        self.experiment_status = StringVar(value="Experiment folder: not set")
        self.shot_sheet_status = StringVar(value="Shot sheet: not selected")
        self.background_status = StringVar(value="B.tif: not created")
        self.sub_status = StringVar(value="Background Subtracted: not created")
        self.compile_status = StringVar(value="spc executable: not compiled")
        self.spi_status = StringVar(value="Single Photon Image: not created")
        self.spectra_status = StringVar(value="Spectra-temp: not created")

        self.spi_threshold = StringVar(value="75")
        self.spi_max_hit = StringVar(value="10000")

        self.filter_file = StringVar(value=str(REPO_DIR / "metal-filter.pckl"))
        self.qe_file = StringVar(value=str(REPO_DIR / "QE.pckl"))
        self.counts_per_e = StringVar(value="4.9")
        self.binwidth = StringVar(value="10")
        self.max_count = StringVar(value="10000")
        self.energy_offset = StringVar(value="-0.3")
        self.xmin = StringVar(value="5")
        self.xmax = StringVar(value="20")
        self.ymin = StringVar(value="1e1")
        self.ymax = StringVar(value="1e6")

        self.filter_file_status = StringVar(value=self.short_path(self.filter_file.get()))
        self.qe_file_status = StringVar(value=self.short_path(self.qe_file.get()))
        self.preview_status = StringVar(value="No spectrum PNG loaded")
        self.preview_folder = None
        self.preview_images = []
        self.preview_index = 0
        self.preview_photo = None
        self.preview_width = 680
        self.preview_height = 360

        self.build_ui()
        self.root.after_idle(self.sync_column_heights)
        self.root.after(100, self.drain_log_queue)

    def build_ui(self):
        main = Frame(self.root, padx=8, pady=8)
        main.pack(fill=X)

        left = Frame(main)
        left.pack(side=LEFT, fill=X, expand=True, padx=(0, 8), anchor=NW)
        right = Frame(main, width=700)
        right.pack(side=RIGHT, fill=X, anchor=NW)
        self.left_column = left
        self.right_column = right

        bg_frame = LabelFrame(left, text="1. Background", padx=4, pady=3)
        bg_frame.pack(fill=X, pady=1)
        bg_body = Frame(bg_frame)
        bg_body.pack(fill=X)
        bg_status = Frame(bg_body)
        bg_status.pack(side=LEFT, fill=BOTH, expand=True, padx=(0, 6))
        self.status_row(bg_status, "Selected files", self.bg_files_status)
        self.status_row(bg_status, "Experiment folder", self.experiment_status)
        self.status_row(bg_status, "Shot sheet", self.shot_sheet_status)
        self.status_row(bg_status, "Backgrounds folder", self.bg_save_status)
        self.status_row(bg_status, "Background file", self.background_status)

        selector_col = Frame(bg_body)
        selector_col.pack(side=RIGHT, fill=Y)
        manual_box = LabelFrame(selector_col, text="Manual", padx=3, pady=2)
        manual_box.pack(fill=X)
        Button(
            manual_box,
            text="Choose background tif files",
            command=self.choose_background_files,
        ).pack(fill=X)

        auto_box = LabelFrame(selector_col, text="Auto", padx=3, pady=2)
        auto_box.pack(fill=X, pady=(2, 0))
        Button(auto_box, text="Choose shot sheet", command=self.choose_shot_sheet).pack(
            fill=X
        )
        Button(
            auto_box,
            text="Choose experiment folder",
            command=self.choose_experiment_folder,
        ).pack(fill=X, pady=(2, 0))
        Button(bg_frame, text="Create B.tif", command=self.run_background).pack(
            anchor="e", pady=(2, 0)
        )

        sub_frame = LabelFrame(left, text="2. Background subtraction", padx=4, pady=3)
        sub_frame.pack(fill=X, pady=1)
        self.status_row(sub_frame, "Output", self.sub_status)
        Button(sub_frame, text="Subtract background", command=self.run_subtract).pack(
            anchor="e", pady=(2, 0)
        )

        compile_frame = LabelFrame(left, text="3. Compile Fortran", padx=4, pady=3)
        compile_frame.pack(fill=X, pady=1)
        self.status_row(compile_frame, "Status", self.compile_status)
        Button(compile_frame, text="Compile spc", command=self.run_compile).pack(anchor="e")

        self.path_section(
            left,
            "4. Generate single photon images",
            [
                ("Threshold", self.spi_threshold, "number"),
                ("Max hard-hit count", self.spi_max_hit, "number"),
            ],
            self.run_single_photon,
            "Generate SPI",
            status=("Output", self.spi_status),
        )

        self.plot_section(left)

        self.preview_section(right)

        log_frame = LabelFrame(right, text="Log", padx=5, pady=4)
        log_frame.pack(fill=X, pady=(4, 0))
        self.log_text = ScrolledText(log_frame, height=5)
        self.log_text.pack(fill=X)

    def plot_section(self, parent):
        frame = LabelFrame(parent, text="5. Plot spectra", padx=4, pady=3)
        frame.pack(fill=X, pady=1)
        self.status_row(frame, "Output", self.spectra_status)

        file_grid = Frame(frame)
        file_grid.pack(fill=X, pady=1)
        self.compact_file_row(file_grid, "Filter", self.filter_file, self.filter_file_status, 0, 0)
        self.compact_file_row(file_grid, "QE", self.qe_file, self.qe_file_status, 0, 1)

        number_grid = Frame(frame)
        number_grid.pack(fill=X, pady=1)
        number_rows = [
            ("counts/e", self.counts_per_e),
            ("binwidth (counts)", self.binwidth),
            ("max count", self.max_count),
            ("offset (keV)", self.energy_offset),
            ("x min (keV)", self.xmin),
            ("x max (keV)", self.xmax),
            ("y min (dN/dE)", self.ymin),
            ("y max (dN/dE)", self.ymax),
        ]
        for idx, (label_text, variable) in enumerate(number_rows):
            row = idx // 4
            col = idx % 4
            cell = Frame(number_grid)
            cell.grid(row=row, column=col, sticky="w", padx=(0, 12), pady=1)
            Label(cell, text=label_text, anchor="w").pack(side=LEFT)
            Entry(cell, textvariable=variable, width=8).pack(side=LEFT, padx=(4, 0))

        Button(frame, text="Plot spectra", command=self.run_plot_spectra).pack(anchor="e", pady=(1, 0))

    def compact_file_row(self, parent, label_text, variable, status_variable, row, col):
        cell = Frame(parent)
        cell.grid(row=row, column=col, sticky="ew", padx=(0, 8), pady=1)
        parent.grid_columnconfigure(col, weight=1)
        Label(cell, text=label_text, width=7, anchor="w").pack(side=LEFT)
        Label(cell, textvariable=status_variable, anchor="w").pack(side=LEFT, fill=X, expand=True)
        Button(
            cell,
            text="Browse",
            command=lambda v=variable, s=status_variable: self.browse_short_file(v, s),
        ).pack(side=RIGHT, padx=(4, 0))

    def preview_section(self, parent):
        frame = LabelFrame(parent, text="Spectrum preview", padx=6, pady=6)
        frame.pack(fill=X)
        Label(frame, textvariable=self.preview_status, anchor="w").pack(fill=X)
        self.preview_box = Frame(
            frame,
            width=self.preview_width,
            height=self.preview_height,
        )
        self.preview_box.pack(fill=X, pady=6)
        self.preview_box.pack_propagate(False)
        self.preview_label = Label(
            self.preview_box,
            text="spectra preview",
            anchor="center",
        )
        self.preview_label.place(relx=0.5, rely=0.5, anchor="center")

        controls = Frame(frame)
        controls.pack(fill=X)
        Button(controls, text="Load spectra folder", command=self.choose_preview_folder).pack(side=LEFT)
        Button(controls, text="Previous", command=self.preview_previous).pack(side=LEFT)
        Button(controls, text="Next", command=self.preview_next).pack(side=LEFT, padx=(6, 0))
        Button(controls, text="Export current to PDF", command=self.export_current_pdf).pack(
            side=RIGHT
        )

    def sync_column_heights(self):
        self.root.update_idletasks()
        left_height = self.left_column.winfo_reqheight()
        right_height = self.right_column.winfo_reqheight()
        current_preview_height = self.preview_box.winfo_reqheight()
        right_chrome_height = right_height - current_preview_height
        target_preview_height = max(260, left_height - right_chrome_height)
        self.preview_height = target_preview_height
        self.preview_box.configure(height=target_preview_height)
        self.root.update_idletasks()
        window_height = max(
            self.left_column.winfo_reqheight(),
            self.right_column.winfo_reqheight(),
        ) + 16
        self.root.geometry(f"1480x{window_height}")

    def status_row(self, parent, label_text, variable):
        row = Frame(parent)
        row.pack(fill=X, pady=0)
        Label(row, text=label_text, width=17, anchor="w").pack(side=LEFT)
        Label(row, textvariable=variable, anchor="w").pack(side=LEFT, fill=X, expand=True)

    def path_section(self, parent, title, rows, command, button_text, intro=None, status=None):
        frame = LabelFrame(parent, text=title, padx=4, pady=3)
        frame.pack(fill=X, pady=1)

        if intro:
            Label(frame, text=intro, anchor="w").pack(fill=X, pady=(0, 2))
        if status:
            self.status_row(frame, status[0], status[1])

        for label_text, variable, browse_kind in rows:
            row = Frame(frame)
            row.pack(fill=X, pady=0)
            Label(row, text=label_text, width=17, anchor="w").pack(side=LEFT)
            if browse_kind == "number":
                Entry(row, textvariable=variable, width=8).pack(side=LEFT)
            else:
                Entry(row, textvariable=variable).pack(side=LEFT, fill=X, expand=True)
            if browse_kind in {"dir", "file", "save"}:
                Button(
                    row,
                    text="Browse",
                    command=lambda v=variable, k=browse_kind: self.browse(v, k),
                ).pack(side=RIGHT, padx=(4, 0))

        Button(frame, text=button_text, command=command).pack(anchor="e", pady=(2, 0))

    def short_path(self, path):
        if not path:
            return ""
        path = Path(path).expanduser()
        try:
            return str(path.relative_to(REPO_DIR))
        except ValueError:
            return str(path)

    def choose_background_files(self):
        files = filedialog.askopenfilenames(
            title="Choose background tif files",
            filetypes=[("TIF images", "*.tif"), ("All files", "*.*")],
        )
        if not files:
            return

        parents = {Path(path).expanduser().parent for path in files}
        if len(parents) != 1:
            messagebox.showerror(
                "Background files",
                "Please choose background files from one experiment folder.",
            )
            return

        self.background_files = [Path(path).expanduser() for path in files]
        self.background_mode = "manual"
        self.experiment_dir = parents.pop()
        self.background_dir = self.experiment_dir / "Backgrounds"
        self.background_subtracted_dir = self.experiment_dir / "Background Subtracted"
        self.spi_output_dir = self.background_subtracted_dir / "Single Photon Image"
        self.spectra_output_dir = self.background_subtracted_dir / "Spectra-temp"

        self.bg_files_status.set(f"{len(self.background_files)} files selected")
        self.experiment_status.set(self.short_path(self.experiment_dir))
        self.sub_status.set(self.short_path(self.background_subtracted_dir))
        self.spi_status.set(self.short_path(self.spi_output_dir))
        self.spectra_status.set(self.short_path(self.spectra_output_dir))
        self.refresh_background_status()

    def choose_shot_sheet(self):
        value = filedialog.askopenfilename(
            title="Choose shot sheet",
            filetypes=[("Excel workbook", "*.xlsx"), ("All files", "*.*")],
        )
        if not value:
            return
        self.shot_sheet_file = Path(value).expanduser()
        self.background_mode = "auto"
        self.shot_sheet_status.set(self.short_path(self.shot_sheet_file))
        self.shot_metadata = self.load_shot_metadata(self.shot_sheet_file)
        self.log(f"Loaded shot metadata for {len(self.shot_metadata)} shots")

    def choose_experiment_folder(self):
        value = filedialog.askdirectory(title="Choose experiment folder")
        if not value:
            return
        self.background_mode = "auto"
        self.set_experiment_folder(Path(value).expanduser())

    def set_experiment_folder(self, folder):
        self.experiment_dir = folder
        self.background_dir = self.experiment_dir / "Backgrounds"
        self.background_subtracted_dir = self.experiment_dir / "Background Subtracted"
        self.spi_output_dir = self.background_subtracted_dir / "Single Photon Image"
        self.spectra_output_dir = self.background_subtracted_dir / "Spectra-temp"
        self.experiment_status.set(self.short_path(self.experiment_dir))
        self.sub_status.set(self.short_path(self.background_subtracted_dir))
        self.spi_status.set(self.short_path(self.spi_output_dir))
        self.spectra_status.set(self.short_path(self.spectra_output_dir))
        self.refresh_background_status()

    def refresh_background_status(self):
        if self.background_dir is None:
            self.bg_save_status.set("Backgrounds folder: not set")
            self.background_status.set("B.tif: not created")
            return

        if self.background_dir.exists():
            self.bg_save_status.set(f"{self.short_path(self.background_dir)} (exists)")
        else:
            self.bg_save_status.set(f"{self.short_path(self.background_dir)} (not created)")

        candidate = self.background_dir / "B.tif"
        if candidate.exists():
            self.background_file = candidate
            self.background_status.set(f"{self.short_path(candidate)} (exists)")
        else:
            self.background_file = None
            self.background_status.set("B.tif: not created")

    def run_auto_background(self):
        self.run_task("Auto background from shot sheet", self.auto_background_from_sheet)

    def auto_background_from_sheet(self):
        if self.shot_sheet_file is None:
            raise RuntimeError("Choose a shot sheet first.")
        if self.experiment_dir is None:
            raise RuntimeError("Choose an experiment folder first.")

        shot_numbers = self.background_shots_from_sheet(self.shot_sheet_file)
        if not shot_numbers:
            raise RuntimeError("No blank/trigger rows found in the shot sheet.")

        selected = []
        missing = []
        search_dirs = [self.experiment_dir]
        if self.background_dir is None:
            self.background_dir = self.experiment_dir / "Backgrounds"
        if self.background_dir.exists():
            search_dirs.append(self.background_dir)

        tif_paths = []
        for folder in search_dirs:
            tif_paths.extend(tif_files(folder))

        for shot_no in shot_numbers:
            suffix = f"_{shot_no}.tif"
            matches = [Path(path) for path in tif_paths if Path(path).name.endswith(suffix)]
            if matches:
                selected.extend(matches)
            else:
                missing.append(shot_no)

        if not selected:
            raise FileNotFoundError(
                "No matching background tif files found in experiment folder or Backgrounds folder."
            )

        self.background_files = sorted(set(selected))
        self.bg_files_status.set(
            f"{len(self.background_files)} auto-selected from shot sheet"
        )
        if missing:
            self.log("Missing background shot files: " + ", ".join(str(num) for num in missing))
        self.calculate_background()

    def background_shots_from_sheet(self, shot_sheet):
        rows = read_xlsx_first_sheet_rows(shot_sheet)
        if not rows:
            return []

        header = [str(value).strip() if value is not None else "" for value in rows[0]]
        try:
            wpm_col = header.index("W-PM")
        except ValueError:
            wpm_col = 0
        try:
            shot_col = header.index("Shot_No")
        except ValueError:
            shot_col = 2

        shot_numbers = []
        for row in rows[1:]:
            wpm_value = row[wpm_col] if wpm_col < len(row) else None
            shot_value = row[shot_col] if shot_col < len(row) else None
            if wpm_value is None or shot_value is None:
                continue
            wpm_text = str(wpm_value).strip().lower()
            if "blank" in wpm_text or "trigger" in wpm_text:
                try:
                    shot_numbers.append(int(float(shot_value)))
                except (TypeError, ValueError):
                    self.log(f"Skip invalid Shot_No value: {shot_value}")
        return shot_numbers

    def load_shot_metadata(self, shot_sheet):
        rows = read_xlsx_first_sheet_rows(shot_sheet)
        if not rows:
            return {}

        header = [str(value).strip() if value is not None else "" for value in rows[0]]
        try:
            shot_col = header.index("Shot_No")
        except ValueError:
            shot_col = 2

        material_col = header.index("Target_material") if "Target_material" in header else None
        thickness_col = (
            header.index("Target_thickness_nm")
            if "Target_thickness_nm" in header
            else None
        )

        metadata = {}
        for row in rows[1:]:
            if shot_col >= len(row) or row[shot_col] is None:
                continue
            try:
                shot_no = int(float(row[shot_col]))
            except (TypeError, ValueError):
                continue

            material = row[material_col] if material_col is not None and material_col < len(row) else None
            thickness = (
                row[thickness_col]
                if thickness_col is not None and thickness_col < len(row)
                else None
            )
            metadata[shot_no] = {
                "Target_material": material,
                "Target_thickness_nm": thickness,
            }
        return metadata

    def browse(self, variable, kind):
        if kind == "dir":
            value = filedialog.askdirectory()
        elif kind == "save":
            value = filedialog.asksaveasfilename()
        else:
            value = filedialog.askopenfilename()
        if value:
            variable.set(value)

    def browse_short_file(self, variable, status_variable):
        value = filedialog.askopenfilename()
        if value:
            variable.set(value)
            status_variable.set(self.short_path(value))

    def choose_preview_folder(self):
        value = filedialog.askdirectory(title="Choose spectra PNG folder")
        if not value:
            return
        self.load_preview_images(Path(value).expanduser())

    def load_preview_images(self, folder=None):
        if folder is not None:
            self.preview_folder = Path(folder).expanduser()
        elif self.preview_folder is None:
            self.preview_folder = self.spectra_output_dir

        if self.preview_folder is None:
            self.preview_images = []
        else:
            self.preview_images = sorted(Path(self.preview_folder).glob("*.png"))
        self.preview_index = 0
        self.show_preview()

    def show_preview(self):
        if not self.preview_images:
            self.preview_status.set("No spectrum PNG loaded")
            self.preview_label.configure(image="", text="spectra preview")
            self.preview_photo = None
            return

        image_path = self.preview_images[self.preview_index]
        image = Image.open(image_path)
        image.thumbnail((self.preview_width, self.preview_height))
        self.preview_photo = ImageTk.PhotoImage(image)
        self.preview_label.configure(image=self.preview_photo, text="")
        metadata_text = self.preview_metadata_text(image_path)
        status = f"{self.preview_index + 1}/{len(self.preview_images)}  {image_path.name}"
        if metadata_text:
            status += f"  |  {metadata_text}"
        self.preview_status.set(status)

    def preview_metadata_text(self, image_path):
        shot_no = self.shot_number_from_name(Path(image_path).stem)
        if shot_no is None:
            return ""
        metadata = self.shot_metadata.get(shot_no)
        if not metadata:
            return ""

        parts = []
        material = metadata.get("Target_material")
        thickness = metadata.get("Target_thickness_nm")
        if material not in (None, ""):
            parts.append(f"Target: {material}")
        if thickness not in (None, ""):
            parts.append(f"Thickness: {thickness} nm")
        return ", ".join(parts)

    def shot_number_from_name(self, name):
        token = str(name).split("_")[-1]
        try:
            return int(token)
        except ValueError:
            return None

    def preview_previous(self):
        if not self.preview_images:
            return
        self.preview_index = (self.preview_index - 1) % len(self.preview_images)
        self.show_preview()

    def preview_next(self):
        if not self.preview_images:
            return
        self.preview_index = (self.preview_index + 1) % len(self.preview_images)
        self.show_preview()

    def export_current_pdf(self):
        if not self.preview_images:
            messagebox.showinfo("Export PDF", "No PNG is currently loaded.")
            return

        image_path = self.preview_images[self.preview_index]
        default_name = image_path.with_suffix(".pdf").name
        output = filedialog.asksaveasfilename(
            title="Export current PNG to PDF",
            defaultextension=".pdf",
            initialfile=default_name,
            filetypes=[("PDF", "*.pdf")],
        )
        if not output:
            return

        image = Image.open(image_path).convert("RGB")
        image.save(output, "PDF", resolution=400.0)
        self.log(f"Exported PDF: {output}")

    def log(self, message):
        self.log_queue.put(message)

    def drain_log_queue(self):
        while True:
            try:
                message = self.log_queue.get_nowait()
            except queue.Empty:
                break
            self.log_text.insert(END, message + "\n")
            self.log_text.see(END)
        self.root.after(100, self.drain_log_queue)

    def run_task(self, title, func):
        def worker():
            self.log(f"\n--- {title} ---")
            try:
                func()
            except Exception as exc:
                self.log(f"ERROR: {exc}")
                self.root.after(0, lambda: messagebox.showerror(title, str(exc)))
            else:
                self.log(f"Done: {title}")

        threading.Thread(target=worker, daemon=True).start()

    def run_background(self):
        self.run_task("Create B.tif", self.create_background)

    def create_background(self):
        if self.background_mode == "auto":
            self.auto_background_from_sheet()
        elif self.background_files:
            self.calculate_background()
        elif self.shot_sheet_file is not None and self.experiment_dir is not None:
            self.auto_background_from_sheet()
        else:
            raise RuntimeError(
                "Choose background tif files, or choose both a shot sheet and an experiment folder."
            )

    def run_subtract(self):
        self.run_task("Subtract background", self.subtract_background)

    def run_compile(self):
        self.run_task("Compile Fortran", self.compile_fortran)

    def run_single_photon(self):
        self.run_task("Generate single photon images", self.generate_single_photon)

    def run_plot_spectra(self):
        self.run_task("Plot spectra", self.plot_spectra)

    def calculate_background(self):
        if not self.background_files:
            raise FileNotFoundError("Choose background tif files first.")
        if self.experiment_dir is None:
            raise RuntimeError("Experiment folder is not set.")

        if self.background_dir is None:
            self.background_dir = self.experiment_dir / "Backgrounds"
        output_dir = self.background_dir
        ensure_dir(output_dir)

        destinations = [output_dir / source.name for source in self.background_files]
        moved_files = []
        for source, destination in zip(self.background_files, destinations):
            if source.resolve() == destination.resolve():
                moved_files.append(destination)
                continue
            if destination.exists():
                self.log(f"Replace background file in folder: {self.short_path(destination)}")
                destination.unlink()
            self.log(f"Move background file: {self.short_path(source)} -> {self.short_path(destination)}")
            shutil.move(str(source), str(destination))
            moved_files.append(destination)

        self.background_files = moved_files
        background_tifs = [
            Path(path)
            for path in tif_files(output_dir)
            if Path(path).name.lower() != "b.tif"
        ]
        if not background_tifs:
            raise FileNotFoundError(f"No background tif files found in {output_dir}.")

        self.log(f"Reading {len(background_tifs)} background files from {self.short_path(output_dir)}")
        stack = np.array([read_tif(path) for path in background_tifs])
        background = np.mean(stack, axis=0, dtype=np.float64).astype(np.uint16)

        output = output_dir / "B.tif"
        if output.exists():
            self.log(f"Overwrite existing background: {self.short_path(output)}")
            output.unlink()
        write_tif(output, background)
        self.background_file = output
        self.refresh_background_status()
        self.log(f"Saved background: {output}")
        self.log(f"Background std: {np.std(background):.6g}")

    def subtract_background(self):
        if self.experiment_dir is None:
            raise RuntimeError("Choose and process background files first.")
        if self.background_file is None or not self.background_file.exists():
            raise FileNotFoundError("B.tif has not been created yet.")

        input_files = tif_files(self.experiment_dir)
        if not input_files:
            raise FileNotFoundError("No raw tif files found.")

        background = read_tif(self.background_file).astype(np.int32)
        output_dir = self.experiment_dir / "Background Subtracted"
        ensure_dir(output_dir)
        self.background_subtracted_dir = output_dir
        self.spi_output_dir = output_dir / "Single Photon Image"
        self.spectra_output_dir = output_dir / "Spectra-temp"

        for index, path in enumerate(input_files, start=1):
            self.log(f"[{index}/{len(input_files)}] subtract {Path(path).name}")
            image = read_tif(path).astype(np.int32)
            subtracted = image - background
            subtracted[subtracted < 0] = 0
            subtracted[subtracted > 65000] = 0
            write_tif(output_dir / Path(path).name, subtracted.astype(np.uint16))

        self.sub_status.set(self.short_path(output_dir))
        self.spi_status.set(self.short_path(self.spi_output_dir))
        self.spectra_status.set(self.short_path(self.spectra_output_dir))
        self.log(f"Saved background-subtracted images: {output_dir}")

    def compile_fortran(self):
        f90 = self.f90_file
        output = self.executable_file
        ensure_dir(output.parent)

        command = ["gfortran", "-O3", str(f90), "-o", str(output)]
        self.log("Running: " + " ".join(command))
        result = subprocess.run(command, capture_output=True, text=True)
        if result.stdout:
            self.log(result.stdout.strip())
        if result.stderr:
            self.log(result.stderr.strip())
        if result.returncode != 0:
            raise RuntimeError("Fortran compilation failed.")
        output.chmod(output.stat().st_mode | 0o111)
        self.compile_status.set(self.short_path(output))
        self.log(f"Saved executable: {output}")

    def generate_single_photon(self):
        if self.background_subtracted_dir is None:
            raise RuntimeError("Run background subtraction first.")
        if self.spi_output_dir is None:
            self.spi_output_dir = self.background_subtracted_dir / "Single Photon Image"

        input_files = tif_files(self.background_subtracted_dir)
        if not input_files:
            raise FileNotFoundError("No background-subtracted tif files found.")

        executable = self.executable_file
        if not executable.exists():
            raise FileNotFoundError(f"spc executable not found: {executable}")

        threshold = float(self.spi_threshold.get())
        max_hit = float(self.spi_max_hit.get())
        output_dir = self.spi_output_dir
        ensure_dir(output_dir)

        for index, path in enumerate(input_files, start=1):
            name = Path(path).name
            self.log(f"[{index}/{len(input_files)}] generate SPI {name}")
            image = read_tif(path).astype(float)
            if image.shape != (1024, 1024):
                raise ValueError(
                    f"{name} has shape {image.shape}; spc.f90 expects 1024x1024 images."
                )
            image[image >= max_hit] = 0
            image[image <= threshold] = 0

            output_image = np.zeros_like(image, dtype=float)
            with tempfile.TemporaryDirectory(prefix="spc_work_") as tmp:
                tmpdir = Path(tmp)
                workfile = tmpdir / "workfile"
                np.savetxt(workfile, image.reshape(-1), fmt="%.8g")

                result = subprocess.run(
                    [str(executable)],
                    cwd=tmpdir,
                    capture_output=True,
                    text=True,
                )
                if result.returncode != 0:
                    if result.stdout:
                        self.log(result.stdout.strip())
                    if result.stderr:
                        self.log(result.stderr.strip())
                    raise RuntimeError(f"spc failed for {name}")

                fort3 = tmpdir / "fort.3"
                if not fort3.exists():
                    raise FileNotFoundError(f"spc did not produce fort.3 for {name}")

                values = np.loadtxt(fort3)
                triplets = values.reshape(-1, 3)
                rows = triplets[:, 0].astype(int)
                cols = triplets[:, 1].astype(int)
                vals = triplets[:, 2]
                valid = (
                    (rows >= 0)
                    & (rows < output_image.shape[0])
                    & (cols >= 0)
                    & (cols < output_image.shape[1])
                )
                output_image[rows[valid], cols[valid]] = vals[valid]

            output_image = np.clip(output_image, 0, 65535).astype(np.uint16)
            write_tif(output_dir / name, output_image)

        self.spi_status.set(self.short_path(output_dir))
        self.log(f"Saved single photon images: {output_dir}")

    def plot_spectra(self):
        if self.spi_output_dir is None:
            raise RuntimeError("Generate single photon images first.")

        input_files = tif_files(self.spi_output_dir)
        if not input_files:
            raise FileNotFoundError("No single photon tif files found.")

        if self.spectra_output_dir is None:
            self.spectra_output_dir = self.spi_output_dir.parent / "Spectra-temp"
        output_dir = self.spectra_output_dir
        ensure_dir(output_dir)

        counts_per_e = float(self.counts_per_e.get())
        binwidth = int(self.binwidth.get())
        max_count = int(self.max_count.get())
        energy_offset = float(self.energy_offset.get())
        xmin = float(self.xmin.get())
        xmax = float(self.xmax.get())
        ymin = float(self.ymin.get())
        ymax = float(self.ymax.get())

        energy, be, kap, qe = load_response_data(self.filter_file.get(), self.qe_file.get())
        kev_per_count = 3.66 / 1000

        for index, path in enumerate(input_files, start=1):
            name = Path(path).name
            self.log(f"[{index}/{len(input_files)}] plot spectrum {name}")
            data = read_tif(path)
            values = data.astype(np.int64).ravel()
            values = values[(values > 0) & (values < max_count)]
            hist = np.bincount(values, minlength=max_count)[1:max_count]

            n_bins = int(math.ceil(max_count / binwidth))
            hist_bin = np.zeros(n_bins)
            for num, count in enumerate(hist):
                hist_bin[int(num / binwidth)] += count
            hist_bin = hist_bin / binwidth

            count_axis = np.arange(1, len(hist) + 1)
            xaxis = count_axis * counts_per_e * kev_per_count + energy_offset
            response = safe_response(
                np.interp(xaxis, energy, be),
                np.interp(xaxis, energy, kap),
                np.interp(xaxis, energy, qe),
            )
            spectrum = hist * response

            x_bin = np.arange(1, len(hist_bin) + 1) * counts_per_e * kev_per_count * binwidth
            x_bin = x_bin + energy_offset
            rep_bin = safe_response(
                np.interp(x_bin, energy, be),
                np.interp(x_bin, energy, kap),
                np.interp(x_bin, energy, qe),
            )
            spec_bin = hist_bin * rep_bin

            plt.figure(index)
            plt.semilogy(
                xaxis,
                spectrum,
                linestyle="none",
                marker=".",
                markersize=1,
                color="b",
            )
            plt.semilogy(
                x_bin,
                spec_bin,
                color="r",
                label="binned spectrum",
                drawstyle="steps-mid",
            )
            plt.xlim(xmin, xmax)
            plt.ylim(ymin, ymax)
            plt.xlabel("Photon Energy [keV]", fontsize=16)
            plt.ylabel("dN/dE", fontsize=16)
            plt.legend(loc="upper right")
            plt.grid(True, which="both")
            plt.savefig(output_dir / f"{Path(name).stem}.png", dpi=400)
            plt.close()

        self.spectra_status.set(self.short_path(output_dir))
        self.root.after(0, lambda folder=output_dir: self.load_preview_images(folder))
        self.log(f"Saved spectra: {output_dir}")


def main():
    root = Tk()
    root.geometry("1480x640")
    root.minsize(1380, 600)
    SpcGui(root)
    root.mainloop()


if __name__ == "__main__":
    main()
