# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Iman Alavi Zadeh <iman.alavi98@gmail.com>
#
# Author: Iman Alavi Zadeh
# Developed with AI-assisted (agentic) programming; reviewed by the author.

"""A small window for running the pipeline without a terminal.

    Start GUI.bat           (Windows, double-click)
    python main.py gui      (any platform)

It is a front end, not a second implementation. Every button runs the same
``main.py`` command a terminal user would type, in a child process, and streams
its output into the log pane — so a run from the window and a run from the
terminal produce identical results, QA records included.

What it adds for someone who does not live in a terminal:

* **Setup checks** before anything runs — Python packages, Docker, the roofer and
  citygml-tools images, the input files — each with a plain instruction when it
  fails, and a button that downloads missing Docker images.
* **Tile and format choices** as a dropdown and checkboxes.
* **One-click results**: open the HTML QA report or the output folders.

Built on Tkinter, which ships with Python, so the window needs no extra install.
"""

from __future__ import annotations

import os
import queue
import shutil
import subprocess
import sys
import threading
import time
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from tkinter import filedialog, messagebox
import tkinter as tk
from tkinter import ttk

# src/run_pipeline/gui.py -> repository root, where main.py and config.yml live.
ROOT = Path(__file__).resolve().parents[2]
MAIN_PY = ROOT / "main.py"
ALL_TILES = "All tiles"
FORMATS = (("cityjson", "CityJSON"), ("citygml", "CityGML"), ("gltf", "glTF"), ("ply", "PLY"))

# Modules the pipeline imports; checked in the interpreter that will run it.
REQUIRED_MODULES = ("yaml", "numpy", "scipy", "geopandas", "shapely", "pyproj",
                    "laspy", "rasterio", "mapbox_earcut")

# Lines that mark a new stage in `main.py all` output, shown in the status bar.
STAGE_MARKERS = ("Phase 1", "Phase 2", "Export —", "Phase 3")

# Child processes get no console window of their own. They still have a hidden
# console, which docker.exe inherits, so no black windows flash during a run.
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


# ---------------------------------------------------------------------------
# Setup checks — plain functions, run on a worker thread
# ---------------------------------------------------------------------------

@dataclass
class Check:
    name: str
    ok: bool
    detail: str
    pull_image: str | None = None   # a Docker image the "download" button can fetch


def _quiet(cmd: list[str], timeout: float = 20) -> subprocess.CompletedProcess | None:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                              creationflags=_NO_WINDOW)
    except (OSError, subprocess.TimeoutExpired):
        return None


def _load_config(config_path: Path):
    """The parsed config, via the pipeline's own loader."""
    src = str(ROOT / "src")
    if src not in sys.path:
        sys.path.insert(0, src)
    from pipeline_common.config import load_config
    return load_config(config_path)


_packages_ok = False   # a successful import probe is cached: installs do not vanish mid-session


def run_checks(config_path: Path, tile: str, formats: list[str]) -> list[Check]:
    global _packages_ok
    checks: list[Check] = []

    # -- Python packages -----------------------------------------------------
    # Probed in a child process with the same interpreter that will run the
    # pipeline, so a missing package is reported here rather than mid-run.
    probe = None
    if not _packages_ok:
        probe = _quiet([sys.executable, "-c", "import " + ", ".join(REQUIRED_MODULES)], timeout=60)
        _packages_ok = probe is not None and probe.returncode == 0
    if _packages_ok:
        checks.append(Check("Python packages", True, f"Python {sys.version.split()[0]}"))
    else:
        missing = (probe.stderr.strip().splitlines() or ["unknown error"])[-1] if probe else "could not start Python"
        checks.append(Check(
            "Python packages", False,
            f"{missing}. Install them with:  {Path(sys.executable).name} -m pip install -r requirements.txt",
        ))
        return checks   # nothing below can be checked without the pipeline's modules

    try:
        cfg = _load_config(config_path)
    except Exception as exc:   # show any config problem as a check, not a traceback
        checks.append(Check("Configuration", False, f"{config_path.name}: {exc}"))
        return checks
    checks.append(Check("Configuration", True, str(config_path)))

    # -- external tools --------------------------------------------------------
    tools = []
    roofer = cfg.section("roofer")
    tools.append(("roofer", str(roofer.get("runner", "docker")),
                  str(roofer.get("image", "3dgi/roofer:v1.0.0")), str(roofer.get("binary", "roofer"))))
    if "citygml" in formats:
        gml = (cfg.get("export") or {}).get("citygml", {}) or {}
        tools.append(("citygml-tools", str(gml.get("runner", "docker")),
                      str(gml.get("image", "citygml4j/citygml-tools:2.5.0")),
                      str(gml.get("binary", "citygml-tools"))))

    if any(runner == "docker" for _, runner, _, _ in tools):
        if shutil.which("docker") is None:
            checks.append(Check("Docker", False,
                                "Docker is not installed. Install Docker Desktop, or use the "
                                "native roofer binary (see README)."))
            docker_up = False
        else:
            info = _quiet(["docker", "info", "--format", "{{.ServerVersion}}"])
            docker_up = info is not None and info.returncode == 0
            checks.append(Check(
                "Docker", docker_up,
                f"running (engine {info.stdout.strip()})" if docker_up
                else "Docker Desktop is not running. Start it, wait for \"Engine running\", then Re-check.",
            ))
    else:
        docker_up = False

    for name, runner, image, binary in tools:
        if runner == "docker":
            if not docker_up:
                checks.append(Check(name, False, f"needs Docker ({image})"))
                continue
            found = _quiet(["docker", "image", "inspect", image])
            ok = found is not None and found.returncode == 0
            checks.append(Check(name, ok, image if ok else f"image {image} is not downloaded yet",
                                pull_image=None if ok else image))
        else:
            ok = shutil.which(binary) is not None
            checks.append(Check(name, ok, shutil.which(binary) if ok
                                else f"'{binary}' is not on PATH (runner: native in config.yml)"))

    # -- input data ------------------------------------------------------------
    tiles = cfg.tiles() if tile == ALL_TILES else [t for t in cfg.tiles() if t.id == tile]
    missing_las = [str(t.las) for t in tiles if not t.las.is_file()]
    if not tiles:
        checks.append(Check("Point cloud", False, "no tiles are listed in config.yml"))
    else:
        checks.append(Check("Point cloud", not missing_las,
                            f"{len(tiles)} tile(s) found" if not missing_las
                            else "not found: " + ", ".join(missing_las)))
    fp = cfg.footprints_path
    checks.append(Check("Footprints", fp.is_file(),
                        fp.name if fp.is_file()
                        else f"not found: {fp} — add it, or build it on the \"Refresh footprints\" tab"))
    return checks


# ---------------------------------------------------------------------------
# The window
# ---------------------------------------------------------------------------

class PipelineApp(ttk.Frame):
    def __init__(self, master: tk.Tk):
        super().__init__(master, padding=12)
        self.master = master
        self.proc: subprocess.Popen | None = None
        self.messages: queue.Queue = queue.Queue()
        self.run_started = 0.0
        self.run_label = ""
        self._current_stage = ""
        self._stopped = False
        self.pull_images: list[str] = []

        self.config_var = tk.StringVar(value=str(ROOT / "config.yml"))
        self.tile_var = tk.StringVar()
        self.format_vars = {key: tk.BooleanVar(value=True) for key, _ in FORMATS}
        self.status_var = tk.StringVar(value="Ready.")

        self.fp_input_var = tk.StringVar()
        self.fp_layer_var = tk.StringVar()
        self.fp_output_var = tk.StringVar(value=str(ROOT / "data"))
        self.fp_dedup_var = tk.BooleanVar(value=True)

        self._build()
        self.grid(sticky="nsew")
        master.columnconfigure(0, weight=1)
        master.rowconfigure(0, weight=1)

        self.load_tiles()
        self.after(100, self._drain_messages)
        self.after(200, self.recheck)

    # -- layout ----------------------------------------------------------------

    def _build(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

        # Setup checks
        checks = ttk.LabelFrame(self, text="Setup checks", padding=(10, 6))
        checks.grid(row=0, column=0, sticky="ew")
        checks.columnconfigure(1, weight=1)
        self.checks_frame = ttk.Frame(checks)
        self.checks_frame.grid(row=0, column=0, columnspan=3, sticky="ew")
        self.checks_frame.columnconfigure(2, weight=1)
        buttons = ttk.Frame(checks)
        buttons.grid(row=1, column=0, columnspan=3, sticky="w", pady=(6, 0))
        self.recheck_btn = ttk.Button(buttons, text="Re-check", command=self.recheck)
        self.recheck_btn.pack(side="left")
        self.pull_btn = ttk.Button(buttons, text="Download missing Docker images",
                                   command=self.pull_missing)
        # shown only when there is something to download

        # Tabs
        tabs = ttk.Notebook(self)
        tabs.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        tabs.add(self._build_models_tab(tabs), text="  Build 3D models  ")
        tabs.add(self._build_footprints_tab(tabs), text="  Refresh footprints  ")

        # Log
        log = ttk.LabelFrame(self, text="Log", padding=(8, 6))
        log.grid(row=2, column=0, sticky="nsew", pady=(10, 0))
        log.columnconfigure(0, weight=1)
        log.rowconfigure(0, weight=1)
        self.log = tk.Text(log, height=14, wrap="none", font=("Consolas", 9),
                           state="disabled", borderwidth=0, background="#fbfbfa")
        self.log.grid(row=0, column=0, sticky="nsew")
        self.log.tag_configure("error", foreground="#b3261e")
        self.log.tag_configure("stage", foreground="#1f5fa8", font=("Consolas", 9, "bold"))
        self.log.tag_configure("note", foreground="#6a6f76")
        yscroll = ttk.Scrollbar(log, orient="vertical", command=self.log.yview)
        yscroll.grid(row=0, column=1, sticky="ns")
        xscroll = ttk.Scrollbar(log, orient="horizontal", command=self.log.xview)
        xscroll.grid(row=1, column=0, sticky="ew")
        self.log.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)

        # Status bar
        bar = ttk.Frame(self)
        bar.grid(row=3, column=0, sticky="ew", pady=(8, 0))
        bar.columnconfigure(0, weight=1)
        ttk.Label(bar, textvariable=self.status_var).grid(row=0, column=0, sticky="w")
        ttk.Button(bar, text="Clear log", command=self.clear_log).grid(row=0, column=1, padx=(6, 0))
        self.stop_btn = ttk.Button(bar, text="Stop", command=self.stop, state="disabled")
        self.stop_btn.grid(row=0, column=2, padx=(6, 0))

    def _build_models_tab(self, parent) -> ttk.Frame:
        tab = ttk.Frame(parent, padding=10)
        tab.columnconfigure(1, weight=1)

        ttk.Label(tab, text="Config file").grid(row=0, column=0, sticky="w")
        ttk.Entry(tab, textvariable=self.config_var).grid(row=0, column=1, sticky="ew", padx=6)
        ttk.Button(tab, text="Browse…", command=self.browse_config).grid(row=0, column=2)

        ttk.Label(tab, text="Tile").grid(row=1, column=0, sticky="w", pady=(8, 0))
        self.tile_box = ttk.Combobox(tab, textvariable=self.tile_var, state="readonly", width=24)
        self.tile_box.grid(row=1, column=1, sticky="w", padx=6, pady=(8, 0))
        self.tile_box.bind("<<ComboboxSelected>>", lambda _e: self.recheck())

        ttk.Label(tab, text="Export formats").grid(row=2, column=0, sticky="w", pady=(8, 0))
        formats = ttk.Frame(tab)
        formats.grid(row=2, column=1, sticky="w", padx=6, pady=(8, 0))
        for key, label in FORMATS:
            ttk.Checkbutton(formats, text=label, variable=self.format_vars[key],
                            command=self.recheck).pack(side="left", padx=(0, 12))

        run = ttk.Frame(tab)
        run.grid(row=3, column=0, columnspan=3, sticky="ew", pady=(14, 0))
        self.run_all_btn = ttk.Button(run, text="▶  Run everything", command=self.run_all)
        self.run_all_btn.pack(side="left", ipadx=10, ipady=4)
        ttk.Label(run, text="   or one step:", foreground="#6a6f76").pack(side="left")
        self.step_buttons = []
        for text, command in (("1  Prepare", "prepare"), ("2  Reconstruct", "roofer"),
                              ("3  Export", "export"), ("4  Inspect", "inspect")):
            btn = ttk.Button(run, text=text, command=lambda c=command: self.run_step(c))
            btn.pack(side="left", padx=(6, 0))
            self.step_buttons.append(btn)

        results = ttk.Frame(tab)
        results.grid(row=4, column=0, columnspan=3, sticky="w", pady=(12, 0))
        ttk.Label(results, text="Results:").pack(side="left")
        ttk.Button(results, text="Open QA report", command=self.open_report).pack(side="left", padx=(6, 0))
        ttk.Button(results, text="Open 3D models folder",
                   command=lambda: self.open_output("export")).pack(side="left", padx=(6, 0))
        ttk.Button(results, text="Open output folder",
                   command=lambda: self.open_output(None)).pack(side="left", padx=(6, 0))
        return tab

    def _build_footprints_tab(self, parent) -> ttk.Frame:
        tab = ttk.Frame(parent, padding=10)
        tab.columnconfigure(1, weight=1)
        ttk.Label(
            tab, foreground="#6a6f76", wraplength=760, justify="left",
            text=("Only needed when the cadastral footprints change. Reads Lantmäteriet's "
                  "Byggnad GeoPackage, translates it to English and keeps the newest "
                  "version of each building. The 3D models use the result."),
        ).grid(row=0, column=0, columnspan=3, sticky="w")

        ttk.Label(tab, text="Byggnad GeoPackage").grid(row=1, column=0, sticky="w", pady=(10, 0))
        ttk.Entry(tab, textvariable=self.fp_input_var).grid(row=1, column=1, sticky="ew", padx=6, pady=(10, 0))
        ttk.Button(tab, text="Browse…", command=self.browse_fp_input).grid(row=1, column=2, pady=(10, 0))

        ttk.Label(tab, text="Layer (optional)").grid(row=2, column=0, sticky="w", pady=(6, 0))
        ttk.Entry(tab, textvariable=self.fp_layer_var, width=30).grid(row=2, column=1, sticky="w", padx=6, pady=(6, 0))

        ttk.Label(tab, text="Output folder").grid(row=3, column=0, sticky="w", pady=(6, 0))
        ttk.Entry(tab, textvariable=self.fp_output_var).grid(row=3, column=1, sticky="ew", padx=6, pady=(6, 0))
        ttk.Button(tab, text="Browse…", command=self.browse_fp_output).grid(row=3, column=2, pady=(6, 0))

        ttk.Checkbutton(tab, text="Keep only the newest version of each building (recommended)",
                        variable=self.fp_dedup_var).grid(row=4, column=1, sticky="w", padx=6, pady=(6, 0))
        self.fp_run_btn = ttk.Button(tab, text="▶  Build footprints", command=self.run_footprints)
        self.fp_run_btn.grid(row=5, column=1, sticky="w", padx=6, pady=(12, 0), ipadx=10, ipady=4)
        return tab

    # -- config and checks -----------------------------------------------------

    def config_path(self) -> Path:
        return Path(self.config_var.get()).expanduser()

    def selected_formats(self) -> list[str]:
        return [key for key, _ in FORMATS if self.format_vars[key].get()]

    def load_tiles(self) -> None:
        try:
            ids = [t.id for t in _load_config(self.config_path()).tiles()]
        except Exception as exc:
            ids = []
            self.write(f"Could not read {self.config_path()}: {exc}\n", "error")
        values = ids + ([ALL_TILES] if len(ids) > 1 else [])
        self.tile_box.configure(values=values)
        if self.tile_var.get() not in values:
            self.tile_var.set(values[0] if values else "")

    def recheck(self) -> None:
        self.recheck_btn.configure(state="disabled")
        self._show_checks([Check("Checking…", True, "")], pending=True)
        config, tile, formats = self.config_path(), self.tile_var.get(), self.selected_formats()

        def work():
            try:
                result = run_checks(config, tile, formats)
            except Exception as exc:
                result = [Check("Setup checks", False, f"could not run: {exc}")]
            self.messages.put(("checks", result))

        threading.Thread(target=work, daemon=True).start()

    def _show_checks(self, checks: list[Check], pending: bool = False) -> None:
        for child in self.checks_frame.winfo_children():
            child.destroy()
        for row, check in enumerate(checks):
            mark, colour = ("…", "#6a6f76") if pending else (("✔", "#2e7d4f") if check.ok else ("✖", "#b3261e"))
            tk.Label(self.checks_frame, text=mark, fg=colour, font=("Segoe UI", 11, "bold")).grid(
                row=row, column=0, sticky="w")
            ttk.Label(self.checks_frame, text=check.name, width=18).grid(row=row, column=1, sticky="w")
            ttk.Label(self.checks_frame, text=check.detail, foreground="#3c4043" if check.ok else "#b3261e",
                      wraplength=640, justify="left").grid(row=row, column=2, sticky="w")
        self.pull_images = [c.pull_image for c in checks if c.pull_image]
        if self.pull_images and not pending:
            self.pull_btn.pack(side="left", padx=(6, 0))
        else:
            self.pull_btn.pack_forget()

    # -- running commands ------------------------------------------------------

    def _common_args(self) -> list[str]:
        args = ["--config", str(self.config_path())]
        if self.tile_var.get() and self.tile_var.get() != ALL_TILES:
            args += ["--tile", self.tile_var.get()]
        return args

    def run_all(self) -> None:
        formats = self.selected_formats()
        if not formats:
            messagebox.showwarning("No format selected", "Tick at least one export format.")
            return
        self.start("Run everything", ["all", *self._common_args(), "--format", *formats])

    def run_step(self, command: str) -> None:
        args = [command, *self._common_args()]
        if command == "export":
            formats = self.selected_formats()
            if not formats:
                messagebox.showwarning("No format selected", "Tick at least one export format.")
                return
            args += ["--format", *formats]
        labels = {"prepare": "Prepare", "roofer": "Reconstruct", "export": "Export", "inspect": "Inspect"}
        self.start(labels[command], args)

    def run_footprints(self) -> None:
        source = Path(self.fp_input_var.get())
        if not source.is_file():
            messagebox.showwarning("No input", "Choose the Byggnad GeoPackage first.")
            return
        out = Path(self.fp_output_var.get())
        target = out / "buildings_processed_postprocess.gpkg"
        if target.exists() and not messagebox.askyesno(
                "Replace footprints?",
                f"{target} already exists and will be replaced.\n\nThe 3D models are built "
                f"from this file. Continue?"):
            return
        args = ["footprints", "--input", str(source), "--output", str(out)]
        if self.fp_layer_var.get().strip():
            args += ["--layer", self.fp_layer_var.get().strip()]
        if not self.fp_dedup_var.get():
            args.append("--no-postprocess")
        self.start("Build footprints", args)

    def pull_missing(self) -> None:
        images = list(self.pull_images)
        if images:
            self.start("Download images", images, docker_pull=True)

    def start(self, label: str, args: list[str], docker_pull: bool = False) -> None:
        if self.proc is not None:
            return
        if docker_pull:
            commands = [["docker", "pull", image] for image in args]
        else:
            commands = [[sys.executable, "-u", str(MAIN_PY), *args]]

        self.run_label, self.run_started = label, time.monotonic()
        self._stopped = False
        self._set_running(True)
        self.write(f"\n$ {' '.join(commands[0])}{' …' if len(commands) > 1 else ''}\n", "note")

        env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")

        def work():
            code = 0
            for cmd in commands:
                try:
                    self.proc = subprocess.Popen(
                        cmd, cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                        creationflags=_NO_WINDOW,
                    )
                except OSError as exc:
                    self.messages.put(("line", (f"Could not start: {exc}\n", "error")))
                    code = 1
                    break
                for raw in self.proc.stdout:
                    line = raw.decode("utf-8", errors="replace")
                    self.messages.put(("line", (line, self._tag_for(line))))
                code = self.proc.wait()
                if code != 0:
                    break
            self.messages.put(("done", code))

        threading.Thread(target=work, daemon=True).start()

    @staticmethod
    def _tag_for(line: str) -> str | None:
        stripped = line.strip()
        if stripped.startswith(STAGE_MARKERS):
            return "stage"
        if any(word in stripped for word in ("Error", "Traceback", "FAILED", "failed")):
            return "error"
        return None

    def stop(self) -> None:
        proc = self.proc
        if proc is None:
            return
        self._stopped = True
        if os.name == "nt":
            # Kill the whole tree: the pipeline's own children (docker.exe) too.
            _quiet(["taskkill", "/T", "/F", "/PID", str(proc.pid)])
        else:
            proc.terminate()
        self.write("\nStopped. A roofer or citygml-tools container already started in "
                   "Docker may still finish in the background; the next run clears its output.\n",
                   "note")

    def _set_running(self, running: bool) -> None:
        state = "disabled" if running else "normal"
        for widget in (self.run_all_btn, self.fp_run_btn, self.recheck_btn, self.pull_btn,
                       *self.step_buttons):
            widget.configure(state=state)
        self.stop_btn.configure(state="normal" if running else "disabled")
        if running:
            self._tick()

    def _tick(self) -> None:
        if self.proc is None and not self.run_label:
            return
        elapsed = int(time.monotonic() - self.run_started)
        if self.run_label:
            current = self._current_stage
            self.status_var.set(f"Running: {self.run_label}{' — ' + current if current else ''}"
                                f"   {elapsed // 60}:{elapsed % 60:02d}")
            self.after(500, self._tick)

    def _drain_messages(self) -> None:
        try:
            while True:
                kind, payload = self.messages.get_nowait()
                if kind == "line":
                    text, tag = payload
                    if tag == "stage":
                        self._current_stage = text.strip()
                    self.write(text, tag)
                elif kind == "checks":
                    self._show_checks(payload)
                    self.recheck_btn.configure(state="normal" if self.proc is None else "disabled")
                elif kind == "done":
                    self._finish(payload)
        except queue.Empty:
            pass
        self.after(100, self._drain_messages)

    def _finish(self, code: int) -> None:
        elapsed = int(time.monotonic() - self.run_started)
        label = self.run_label
        self.proc, self.run_label, self._current_stage = None, "", ""
        self._set_running(False)
        took = f"{elapsed // 60}:{elapsed % 60:02d}"
        if self._stopped:
            self.status_var.set(f"Stopped {label} after {took}.")
        elif code == 0:
            self.status_var.set(f"✔ {label} finished in {took}.")
            self.write(f"\n✔ {label} finished in {took}.\n", "stage")
        else:
            self.status_var.set(f"✖ {label} failed (exit code {code}) after {took}. See the log.")
            self.write(f"\n✖ {label} failed (exit code {code}).\n", "error")
        if label == "Download images":
            self.recheck()

    # -- log -------------------------------------------------------------------

    def write(self, text: str, tag: str | None = None) -> None:
        at_bottom = self.log.yview()[1] > 0.999
        self.log.configure(state="normal")
        self.log.insert("end", text, (tag,) if tag else ())
        self.log.configure(state="disabled")
        if at_bottom:
            self.log.see("end")

    def clear_log(self) -> None:
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")

    # -- file pickers and opening results ---------------------------------------

    def browse_config(self) -> None:
        path = filedialog.askopenfilename(title="Choose config.yml", initialdir=ROOT,
                                          filetypes=[("YAML", "*.yml *.yaml"), ("All files", "*")])
        if path:
            self.config_var.set(path)
            self.load_tiles()
            self.recheck()

    def browse_fp_input(self) -> None:
        path = filedialog.askopenfilename(title="Choose the Byggnad GeoPackage",
                                          filetypes=[("GeoPackage", "*.gpkg"), ("All files", "*")])
        if path:
            self.fp_input_var.set(path)

    def browse_fp_output(self) -> None:
        path = filedialog.askdirectory(title="Choose the output folder",
                                       initialdir=self.fp_output_var.get() or ROOT)
        if path:
            self.fp_output_var.set(path)

    def _cfg_or_warn(self):
        try:
            return _load_config(self.config_path())
        except Exception as exc:
            messagebox.showerror("Configuration", f"Could not read the config file:\n\n{exc}")
            return None

    def open_report(self) -> None:
        cfg = self._cfg_or_warn()
        if cfg is None:
            return
        tile = self.tile_var.get()
        target = cfg.qa_dir if tile in ("", ALL_TILES) else cfg.qa_dir / f"{tile}_qa.html"
        if not target.exists():
            messagebox.showinfo("No report yet", f"{target} does not exist yet.\n\nRun the pipeline first.")
            return
        _open(target)

    def open_output(self, sub: str | None) -> None:
        cfg = self._cfg_or_warn()
        if cfg is None:
            return
        target = cfg.out_dir if sub is None else cfg.out_dir / sub
        tile = self.tile_var.get()
        if sub and tile not in ("", ALL_TILES) and (target / tile).is_dir():
            target = target / tile
        if not target.exists():
            messagebox.showinfo("Nothing here yet", f"{target} does not exist yet.\n\nRun the pipeline first.")
            return
        _open(target)


def _open(path: Path) -> None:
    """Open a file or folder with the system's default application."""
    if os.name == "nt":
        os.startfile(path)  # noqa: S606 — opening the user's own output
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    elif shutil.which("xdg-open"):
        subprocess.Popen(["xdg-open", str(path)])
    else:
        webbrowser.open(path.as_uri())


def main() -> int:
    if os.name == "nt":
        try:
            # Crisp text on high-DPI screens instead of Windows' blurry scaling.
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (AttributeError, OSError):
            pass

    root = tk.Tk()
    root.title("Helsingborg LOD2.2 — building reconstruction")
    # Size in points, not raw pixels, so the window is not cramped on a screen
    # scaled to 125 % or 150 %. Tk's scaling is pixels per point (1.333 at 96 dpi).
    factor = max(1.0, float(root.tk.call("tk", "scaling")) / (96 / 72))
    root.geometry(f"{int(980 * factor)}x{int(820 * factor)}")
    root.minsize(int(760 * factor), int(600 * factor))
    style = ttk.Style(root)
    if "vista" in style.theme_names():
        style.theme_use("vista")
    app = PipelineApp(root)

    def on_close():
        if app.proc is not None and not messagebox.askyesno(
                "Still running", "A run is still in progress. Stop it and close?"):
            return
        app.stop()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
