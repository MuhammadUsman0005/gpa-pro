"""
GPA Pro - Advanced Academic Performance Tracker
================================================
Run:  python gpa_pro.py        (Python 3.9+, tkinter only; no install needed)
Optional: pip install cryptography   -> enables password-encrypted save files

Features
- Multi-semester tracking with SGPA / CGPA, live dashboard and trend chart
- Grade scales: Custom (your university), US 4.0, or fully editable (safe parser, no exec)
- Retake policies: keep all / latest attempt / best attempt
- Target CGPA planner and "what-if" calculator
- Security: no code execution, input validation, atomic saves, SHA-256 integrity check,
  optional AES-based (Fernet) password encryption, CSV formula-injection protection,
  HTML-escaped reports, private autosave (owner-only permissions)
- Export: CSV, JSON project, printable HTML report (print to PDF from browser)
- Undo (Ctrl+Z), dark/light theme, keyboard shortcuts
"""
from __future__ import annotations

import base64
import copy
import csv
import hashlib
import html
import json
import math
import os
import tempfile
import tkinter as tk
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk
from typing import List, Optional, Tuple

try:  # optional dependency
    from cryptography.fernet import Fernet, InvalidToken  # type: ignore
    from cryptography.hazmat.primitives import hashes  # type: ignore
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC  # type: ignore
    HAS_CRYPTO = True
except Exception:  # pragma: no cover
    HAS_CRYPTO = False

APP_NAME = "GPA Pro"
APP_VERSION = "2.0"
DATA_DIR = Path.home() / ".gpa_pro"
AUTOSAVE_PATH = DATA_DIR / "autosave.json"

MAX_SEMESTERS = 30
MAX_COURSES = 40
MAX_NAME_LEN = 80
MAX_FILE_BYTES = 2_000_000

# ====================================================================== #
#                               CORE LOGIC                               #
# ====================================================================== #

# Each scale is a list of (minimum_marks, gpa), highest first.
SCALE_CUSTOM: List[Tuple[int, float]] = [
    (85, 4.0), (84, 3.9), (83, 3.8), (82, 3.7), (81, 3.6), (80, 3.5),
    (79, 3.4), (78, 3.3), (77, 3.2), (76, 3.1), (75, 3.0), (72, 2.9),
    (70, 2.8), (68, 2.7), (66, 2.6), (65, 2.5), (62, 2.4), (60, 2.3),
    (58, 2.2), (56, 2.1), (55, 2.0), (53, 1.9), (51, 1.8), (50, 1.7),
]
SCALE_US: List[Tuple[int, float]] = [
    (93, 4.0), (90, 3.7), (87, 3.3), (83, 3.0), (80, 2.7), (77, 2.3),
    (73, 2.0), (70, 1.7), (67, 1.3), (63, 1.0), (60, 0.7),
]
PRESETS = {
    "Custom (University)": SCALE_CUSTOM,
    "US 4.0": SCALE_US,
}
POLICIES = {
    "Keep all attempts": "all",
    "Latest attempt replaces": "latest",
    "Best attempt replaces": "best",
}
MAX_GPA = 4.0


def clean_text(s: object, limit: int = MAX_NAME_LEN) -> str:
    """Strip control characters and cap length."""
    s = "".join(ch for ch in str(s) if ch.isprintable()).strip()
    return s[:limit]


def parse_float(s: object) -> Optional[float]:
    try:
        v = float(str(s).strip())
        if math.isnan(v) or math.isinf(v):
            return None
        return v
    except (TypeError, ValueError):
        return None


def parse_scale_text(text: str) -> List[Tuple[int, float]]:
    """Parse lines like '85,4.0' safely. Raises ValueError on bad input."""
    out: List[Tuple[int, float]] = []
    for ln, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.replace(":", ",").split(",")]
        if len(parts) != 2:
            raise ValueError(f"Line {ln}: use 'min_marks,gpa'")
        m, g = parse_float(parts[0]), parse_float(parts[1])
        if m is None or g is None or not (0 <= m <= 100) or not (0 <= g <= 10):
            raise ValueError(f"Line {ln}: invalid numbers")
        out.append((int(m), float(g)))
    if not out:
        raise ValueError("Scale is empty")
    out.sort(key=lambda t: t[0], reverse=True)
    return out


def scale_to_text(scale: List[Tuple[int, float]]) -> str:
    return "\n".join(f"{m},{g}" for m, g in scale)


def marks_to_gpa(marks: float, scale: List[Tuple[int, float]]) -> float:
    m = int(math.floor(marks + 0.5))
    for minimum, gpa in scale:
        if m >= minimum:
            return gpa
    return 0.0


@dataclass
class Course:
    name: str = ""
    marks: Optional[float] = None
    credits: float = 3.0

    def valid(self) -> bool:
        return (self.marks is not None and 0 <= self.marks <= 100
                and 0 < self.credits <= 12)


@dataclass
class Semester:
    name: str = "Semester"
    courses: List[Course] = field(default_factory=list)


@dataclass
class Result:
    sgpa: List[float]
    sem_credits: List[float]
    cgpa: float
    credits: float
    points: float


def compute(semesters: List[Semester], scale, policy: str = "all") -> Result:
    """SGPA per semester + CGPA under the chosen retake policy."""
    sgpas, scr = [], []
    entries = []  # (course_key, semester_index, gpa, credits)
    for si, sem in enumerate(semesters):
        pts = cr = 0.0
        for c in sem.courses:
            if not c.valid():
                continue
            g = marks_to_gpa(c.marks, scale)
            pts += g * c.credits
            cr += c.credits
            entries.append((c.name.strip().lower(), si, g, c.credits))
        sgpas.append(pts / cr if cr else 0.0)
        scr.append(cr)

    counted = entries
    if policy in ("latest", "best"):
        keep, anon = {}, []
        for key, si, g, cr in entries:
            if not key:
                anon.append((key, si, g, cr))
                continue
            prev = keep.get(key)
            if prev is None or policy == "latest" or g >= prev[2]:
                keep[key] = (key, si, g, cr)
        counted = list(keep.values()) + anon

    tot_cr = sum(e[3] for e in counted)
    tot_pts = sum(e[2] * e[3] for e in counted)
    cg = tot_pts / tot_cr if tot_cr else 0.0
    return Result(sgpas, scr, cg, tot_cr, tot_pts)


def standing(cgpa: float, credits: float) -> str:
    if credits <= 0:
        return "No data yet"
    if cgpa >= 3.7:
        return "Distinction"
    if cgpa >= 3.3:
        return "Very Good"
    if cgpa >= 3.0:
        return "Good"
    if cgpa >= 2.0:
        return "Satisfactory"
    return "Academic Risk"


def required_gpa(cur_pts: float, cur_cr: float, rem_cr: float, target: float):
    """Average GPA needed over rem_cr credits to reach target CGPA."""
    if rem_cr <= 0:
        return None
    return (target * (cur_cr + rem_cr) - cur_pts) / rem_cr


# ---------------------------- persistence ----------------------------- #

def state_to_dict(semesters, scale_name, scale, policy) -> dict:
    return {
        "version": 2,
        "scale_name": scale_name,
        "scale": [[m, g] for m, g in scale],
        "policy": policy,
        "semesters": [
            {"name": s.name,
             "courses": [{"name": c.name, "marks": c.marks, "credits": c.credits}
                         for c in s.courses]}
            for s in semesters
        ],
    }


def dict_to_state(d: dict):
    """Strictly validate untrusted JSON and build the model."""
    if not isinstance(d, dict):
        raise ValueError("Invalid project file")
    sems_raw = d.get("semesters")
    if not isinstance(sems_raw, list) or len(sems_raw) > MAX_SEMESTERS:
        raise ValueError("Invalid semester list")
    sems = []
    for s in sems_raw:
        if not isinstance(s, dict) or not isinstance(s.get("courses", []), list):
            raise ValueError("Invalid semester")
        if len(s["courses"]) > MAX_COURSES:
            raise ValueError("Too many courses in a semester")
        courses = []
        for c in s["courses"]:
            if not isinstance(c, dict):
                raise ValueError("Invalid course")
            marks = c.get("marks")
            marks = None if marks in (None, "") else parse_float(marks)
            cr = parse_float(c.get("credits", 3)) or 3.0
            courses.append(Course(clean_text(c.get("name", "")), marks, cr))
        sems.append(Semester(clean_text(s.get("name", "Semester")), courses))
    scale = [(int(m), float(g)) for m, g in d.get("scale", SCALE_CUSTOM)]
    if not scale or len(scale) > 120:
        raise ValueError("Invalid scale")
    scale.sort(key=lambda t: t[0], reverse=True)
    policy = d.get("policy", "all")
    if policy not in POLICIES.values():
        policy = "all"
    return sems, clean_text(d.get("scale_name", "Custom (University)")), scale, policy


def _digest(payload: dict) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def _derive_key(password: str, salt: bytes) -> bytes:
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=480_000)
    return base64.urlsafe_b64encode(kdf.derive(password.encode()))


def atomic_write(path: Path, data: bytes) -> None:
    """Write to a temp file then replace, so a crash never corrupts the file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp_")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def encode_project(payload: dict, password: str = "") -> bytes:
    wrapper = {"app": APP_NAME, "sha256": _digest(payload), "data": payload}
    raw = json.dumps(wrapper, indent=2).encode()
    if not password:
        return raw
    if not HAS_CRYPTO:
        raise RuntimeError("Install 'cryptography' (pip install cryptography) for encryption.")
    salt = os.urandom(16)
    token = Fernet(_derive_key(password, salt)).encrypt(raw)
    return json.dumps({"app": APP_NAME, "enc": 1,
                       "salt": base64.b64encode(salt).decode(),
                       "token": token.decode()}).encode()


def decode_project(blob: bytes, password_getter) -> Tuple[dict, bool]:
    """Returns (payload, integrity_ok)."""
    if len(blob) > MAX_FILE_BYTES:
        raise ValueError("File too large")
    wrapper = json.loads(blob.decode("utf-8"))
    if isinstance(wrapper, dict) and wrapper.get("enc") == 1:
        if not HAS_CRYPTO:
            raise RuntimeError("This file is encrypted. Install 'cryptography' to open it.")
        pw = password_getter()
        if not pw:
            raise ValueError("Password required")
        try:
            salt = base64.b64decode(wrapper["salt"])
            raw = Fernet(_derive_key(pw, salt)).decrypt(wrapper["token"].encode())
        except (InvalidToken, KeyError, ValueError):
            raise ValueError("Wrong password or corrupted file")
        wrapper = json.loads(raw.decode("utf-8"))
    if not isinstance(wrapper, dict):
        raise ValueError("Invalid file")
    if "data" in wrapper:
        payload = wrapper["data"]
        return payload, wrapper.get("sha256") == _digest(payload)
    return wrapper, False  # legacy / foreign format, no checksum


def csv_safe(cell: object) -> str:
    """Prevent spreadsheet formula injection."""
    s = str(cell)
    return "'" + s if s[:1] in ("=", "+", "-", "@", "\t", "\r") else s


# ====================================================================== #
#                                  GUI                                   #
# ====================================================================== #

PALETTES = {
    "light": dict(bg="#f0f2f7", fg="#1a1d29", card="#ffffff", accent="#2563eb",
                  muted="#6b7280", row_a="#ffffff", row_b="#f5f7fb", bad="#fde8e8",
                  badfg="#b91c1c", grid="#d1d5db", good="#16a34a"),
    "dark": dict(bg="#161925", fg="#e8eaf0", card="#222637", accent="#4f7bff",
                 muted="#9aa3b5", row_a="#222637", row_b="#2a2f44", bad="#4a2230",
                 badfg="#ff9a9a", grid="#3d4259", good="#4ade80"),
}


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"{APP_NAME} {APP_VERSION}")
        self.geometry("1240x780")
        self.minsize(1050, 680)

        self.theme = "light"
        self.semesters: List[Semester] = [Semester("Semester 1", [])]
        self.scale_name = "Custom (University)"
        self.scale = list(SCALE_CUSTOM)
        self.policy = "all"
        self.cur_sem = 0
        self.undo_stack: List[str] = []
        self.file_path: Optional[Path] = None
        self.dirty = False

        self.style = ttk.Style(self)
        if "clam" in self.style.theme_names():
            self.style.theme_use("clam")

        self._build_toolbar()
        self._build_tabs()
        self.status = ttk.Label(self, text="Ready", anchor="w", padding=(14, 6))
        self.status.pack(fill="x", side="bottom")
        self._bind_keys()
        self._apply_theme()
        self._try_restore_autosave()
        self.refresh_all()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ------------------------------ theme ------------------------------ #
    @property
    def P(self):
        return PALETTES[self.theme]

    def _apply_theme(self):
        P, s = self.P, self.style
        self.configure(bg=P["bg"])
        s.configure(".", background=P["bg"], foreground=P["fg"], font=("Segoe UI", 10))
        s.configure("TFrame", background=P["bg"])
        s.configure("Card.TFrame", background=P["card"], relief="solid", borderwidth=1)
        s.configure("TLabel", background=P["bg"], foreground=P["fg"])
        s.configure("Card.TLabel", background=P["card"], foreground=P["fg"])
        s.configure("Muted.TLabel", background=P["bg"], foreground=P["muted"])
        s.configure("Title.TLabel", font=("Segoe UI", 20, "bold"))
        s.configure("Big.TLabel", background=P["card"], foreground=P["accent"],
                    font=("Segoe UI", 30, "bold"))
        s.configure("Stat.TLabel", background=P["card"], foreground=P["fg"],
                    font=("Segoe UI", 11, "bold"))
        s.configure("TButton", padding=6)
        s.configure("TNotebook", background=P["bg"])
        s.configure("TNotebook.Tab", padding=(16, 8), font=("Segoe UI", 10, "bold"))
        s.configure("TCheckbutton", background=P["bg"], foreground=P["fg"])
        s.configure("Treeview", background=P["row_a"], fieldbackground=P["row_a"],
                    foreground=P["fg"], rowheight=30, bordercolor=P["grid"])
        s.configure("Treeview.Heading", background=P["accent"], foreground="#ffffff",
                    font=("Segoe UI", 10, "bold"))
        s.map("Treeview", background=[("selected", P["accent"])],
              foreground=[("selected", "#ffffff")])
        if hasattr(self, "tree"):
            self._configure_tags()
            self.sem_list.configure(bg=P["card"], fg=P["fg"],
                                    selectbackground=P["accent"],
                                    highlightbackground=P["grid"])
            self.chart.configure(bg=P["card"])
            self.scale_text.configure(bg=P["card"], fg=P["fg"], insertbackground=P["fg"])
            self.refresh_all()

    def _configure_tags(self):
        P = self.P
        self.tree.tag_configure("a", background=P["row_a"])
        self.tree.tag_configure("b", background=P["row_b"])
        self.tree.tag_configure("bad", background=P["bad"], foreground=P["badfg"])

    # ---------------------------- toolbar/tabs ------------------------- #
    def _build_toolbar(self):
        bar = ttk.Frame(self, padding=(14, 12, 14, 6))
        bar.pack(fill="x")
        left = ttk.Frame(bar)
        left.pack(side="left")
        ttk.Label(left, text=APP_NAME, style="Title.TLabel").pack(anchor="w")
        ttk.Label(left, text="Track, plan and protect your academic record",
                  style="Muted.TLabel").pack(anchor="w")
        right = ttk.Frame(bar)
        right.pack(side="right")
        for text, cmd in [("Theme", self.toggle_theme), ("HTML Report", self.export_html),
                          ("Export CSV", self.export_csv), ("Import CSV", self.import_csv),
                          ("Save", self.save_project), ("Open", self.open_project),
                          ("Undo", self.undo)]:
            ttk.Button(right, text=text, command=cmd).pack(side="right", padx=3)

    def _build_tabs(self):
        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True, padx=14, pady=8)
        self._build_dashboard()
        self._build_courses()
        self._build_planner()
        self._build_settings()

    # ---------------------------- dashboard ---------------------------- #
    def _build_dashboard(self):
        f = ttk.Frame(self.nb, padding=10)
        self.nb.add(f, text="  Dashboard  ")
        top = ttk.Frame(f)
        top.pack(fill="x")
        self.dash = {}
        for key, title in [("cgpa", "Cumulative GPA"), ("credits", "Credit Hours"),
                           ("sgpa", "Latest SGPA"), ("standing", "Standing")]:
            card = ttk.Frame(top, style="Card.TFrame", padding=16)
            card.pack(side="left", fill="x", expand=True, padx=6)
            ttk.Label(card, text=title, style="Card.TLabel").pack(anchor="w")
            lbl = ttk.Label(card, text="-", style="Big.TLabel")
            lbl.pack(anchor="w")
            self.dash[key] = lbl
        chart_card = ttk.Frame(f, style="Card.TFrame", padding=10)
        chart_card.pack(fill="both", expand=True, pady=12, padx=6)
        ttk.Label(chart_card, text="SGPA per semester (bars) and running CGPA (line)",
                  style="Card.TLabel").pack(anchor="w")
        self.chart = tk.Canvas(chart_card, highlightthickness=0, height=300)
        self.chart.pack(fill="both", expand=True)
        self.chart.bind("<Configure>", lambda e: self._draw_chart())

    def _draw_chart(self):
        c, P = self.chart, self.P
        c.delete("all")
        w, h = c.winfo_width(), c.winfo_height()
        if w < 100 or h < 100:
            return
        res = compute(self.semesters, self.scale, self.policy)
        pad_l, pad_b, pad_t, pad_r = 46, 34, 16, 16
        ph, pw = h - pad_b - pad_t, w - pad_l - pad_r
        for i in range(5):
            y = pad_t + ph - ph * i / 4
            c.create_line(pad_l, y, w - pad_r, y, fill=P["grid"])
            c.create_text(pad_l - 8, y, text=f"{MAX_GPA * i / 4:.1f}", fill=P["muted"], anchor="e")
        n = len(self.semesters)
        if n == 0:
            return
        slot = pw / n
        pts = []
        for i, sem in enumerate(self.semesters):
            x0 = pad_l + slot * i + slot * 0.2
            x1 = pad_l + slot * (i + 1) - slot * 0.2
            val = res.sgpa[i]
            y = pad_t + ph - ph * min(val / MAX_GPA, 1)
            if res.sem_credits[i] > 0:
                c.create_rectangle(x0, y, x1, pad_t + ph, fill=P["accent"], outline="")
                c.create_text((x0 + x1) / 2, y - 10, text=f"{val:.2f}", fill=P["fg"])
            c.create_text((x0 + x1) / 2, pad_t + ph + 16, text=sem.name[:14], fill=P["muted"])
            part = compute(self.semesters[: i + 1], self.scale, self.policy)
            if part.credits > 0:
                py = pad_t + ph - ph * min(part.cgpa / MAX_GPA, 1)
                pts.append(((x0 + x1) / 2, py))
        if len(pts) > 1:
            c.create_line(*[v for p in pts for v in p], fill=P["good"], width=3, smooth=True)
        for x, y in pts:
            c.create_oval(x - 4, y - 4, x + 4, y + 4, fill=P["good"], outline="")

    # ----------------------------- courses ----------------------------- #
    def _build_courses(self):
        f = ttk.Frame(self.nb, padding=10)
        self.nb.add(f, text="  Courses  ")
        side = ttk.Frame(f)
        side.pack(side="left", fill="y", padx=(0, 10))
        ttk.Label(side, text="Semesters", style="Stat.TLabel" if False else "TLabel",
                  font=("Segoe UI", 11, "bold")).pack(anchor="w")
        self.sem_list = tk.Listbox(side, width=22, height=18, exportselection=False,
                                   relief="solid", borderwidth=1, font=("Segoe UI", 10))
        self.sem_list.pack(fill="y", expand=True, pady=6)
        self.sem_list.bind("<<ListboxSelect>>", self._on_sem_select)
        for text, cmd in [("Add Semester", self.add_semester), ("Rename", self.rename_semester),
                          ("Delete", self.delete_semester)]:
            ttk.Button(side, text=text, command=cmd).pack(fill="x", pady=2)

        main = ttk.Frame(f)
        main.pack(side="left", fill="both", expand=True)
        bar = ttk.Frame(main)
        bar.pack(fill="x")
        for text, cmd in [("Add Course", self.add_course), ("Remove Selected", self.remove_courses),
                          ("Duplicate", self.duplicate_course), ("Demo Data", self.demo_data)]:
            ttk.Button(bar, text=text, command=cmd).pack(side="left", padx=3)
        ttk.Label(bar, text="Double-click a cell to edit", style="Muted.TLabel").pack(side="right")

        card = ttk.Frame(main, style="Card.TFrame", padding=6)
        card.pack(fill="both", expand=True, pady=8)
        cols = ("name", "marks", "credits", "gpa", "points")
        self.tree = ttk.Treeview(card, columns=cols, show="headings", selectmode="extended")
        for col, title, wd in [("name", "Course", 360), ("marks", "Marks (0-100)", 120),
                               ("credits", "Credit Hrs", 110), ("gpa", "GPA", 90),
                               ("points", "Quality Pts", 120)]:
            self.tree.heading(col, text=title)
            self.tree.column(col, width=wd, anchor="w" if col == "name" else "center")
        sb = ttk.Scrollbar(card, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        sb.grid(row=0, column=1, sticky="ns")
        card.rowconfigure(0, weight=1)
        card.columnconfigure(0, weight=1)
        self.tree.bind("<Double-1>", self._edit_cell)
        self.tree.bind("<Delete>", lambda e: self.remove_courses())
        self._configure_tags()

        foot = ttk.Frame(main, style="Card.TFrame", padding=12)
        foot.pack(fill="x")
        self.foot_lbl = ttk.Label(foot, text="", style="Stat.TLabel")
        self.foot_lbl.pack(side="left")
        self.foot_sgpa = ttk.Label(foot, text="SGPA 0.00", style="Big.TLabel")
        self.foot_sgpa.pack(side="right")

    # ----------------------------- planner ----------------------------- #
    def _build_planner(self):
        f = ttk.Frame(self.nb, padding=16)
        self.nb.add(f, text="  Target Planner  ")
        ttk.Label(f, text="Target CGPA Planner", style="Title.TLabel").pack(anchor="w")
        ttk.Label(f, text="Find the average GPA you need in your remaining credits.",
                  style="Muted.TLabel").pack(anchor="w", pady=(0, 12))
        form = ttk.Frame(f)
        form.pack(anchor="w")
        self.tgt_var, self.rem_var = tk.StringVar(value="3.50"), tk.StringVar(value="60")
        ttk.Label(form, text="Target CGPA:").grid(row=0, column=0, sticky="w", pady=6)
        ttk.Entry(form, textvariable=self.tgt_var, width=10).grid(row=0, column=1, padx=8)
        ttk.Label(form, text="Remaining credit hours:").grid(row=1, column=0, sticky="w", pady=6)
        ttk.Entry(form, textvariable=self.rem_var, width=10).grid(row=1, column=1, padx=8)
        ttk.Button(form, text="Calculate", command=self.run_planner).grid(row=2, column=0, pady=10, sticky="w")
        self.plan_out = ttk.Label(f, text="", wraplength=800, justify="left",
                                  font=("Segoe UI", 12))
        self.plan_out.pack(anchor="w", pady=10)

        ttk.Separator(f).pack(fill="x", pady=14)
        ttk.Label(f, text="What-if: add one hypothetical course", font=("Segoe UI", 12, "bold")).pack(anchor="w")
        row = ttk.Frame(f)
        row.pack(anchor="w", pady=8)
        self.wi_marks, self.wi_cr = tk.StringVar(value="85"), tk.StringVar(value="3")
        ttk.Label(row, text="Marks:").pack(side="left")
        ttk.Entry(row, textvariable=self.wi_marks, width=8).pack(side="left", padx=6)
        ttk.Label(row, text="Credits:").pack(side="left")
        ttk.Entry(row, textvariable=self.wi_cr, width=8).pack(side="left", padx=6)
        ttk.Button(row, text="Simulate", command=self.run_whatif).pack(side="left", padx=8)
        self.wi_out = ttk.Label(f, text="", font=("Segoe UI", 11))
        self.wi_out.pack(anchor="w")

    def run_planner(self):
        t, r = parse_float(self.tgt_var.get()), parse_float(self.rem_var.get())
        if t is None or r is None or not (0 < t <= MAX_GPA) or r <= 0 or r > 400:
            self.plan_out.config(text="Enter a target between 0 and 4.0 and positive credits.")
            return
        res = compute(self.semesters, self.scale, self.policy)
        need = required_gpa(res.points, res.credits, r, t)
        msg = f"Current CGPA {res.cgpa:.2f} over {res.credits:.0f} credits.\n"
        if need > MAX_GPA + 1e-9:
            msg += f"Required average {need:.2f} exceeds {MAX_GPA:.1f}: target not reachable with {r:.0f} credits."
        elif need <= 0:
            msg += "You already secure this target regardless of future grades."
        else:
            msg += f"You need an average GPA of {need:.2f} over the next {r:.0f} credits."
        self.plan_out.config(text=msg)

    def run_whatif(self):
        m, c = parse_float(self.wi_marks.get()), parse_float(self.wi_cr.get())
        if m is None or c is None or not (0 <= m <= 100) or not (0 < c <= 12):
            self.wi_out.config(text="Enter marks 0-100 and credits 0-12.")
            return
        res = compute(self.semesters, self.scale, self.policy)
        g = marks_to_gpa(m, self.scale)
        new = (res.points + g * c) / (res.credits + c)
        self.wi_out.config(text=f"Course GPA {g:.1f}  ->  CGPA {res.cgpa:.2f} becomes {new:.2f} "
                                f"({new - res.cgpa:+.3f})")

    # ----------------------------- settings ---------------------------- #
    def _build_settings(self):
        f = ttk.Frame(self.nb, padding=16)
        self.nb.add(f, text="  Settings & Security  ")
        ttk.Label(f, text="Grading scale", font=("Segoe UI", 12, "bold")).pack(anchor="w")
        row = ttk.Frame(f)
        row.pack(anchor="w", pady=6)
        self.preset_var = tk.StringVar(value=self.scale_name)
        cb = ttk.Combobox(row, textvariable=self.preset_var, state="readonly", width=26,
                          values=list(PRESETS) + ["Custom edited"])
        cb.pack(side="left")
        cb.bind("<<ComboboxSelected>>", self._on_preset)
        ttk.Label(row, text="Retake policy:").pack(side="left", padx=(20, 6))
        self.policy_var = tk.StringVar()
        pc = ttk.Combobox(row, textvariable=self.policy_var, state="readonly", width=26,
                          values=list(POLICIES))
        pc.pack(side="left")
        pc.bind("<<ComboboxSelected>>", self._on_policy)
        ttk.Label(f, text="One rule per line: minimum_marks,gpa  (highest first; below the last rule = 0.0)",
                  style="Muted.TLabel").pack(anchor="w", pady=(10, 2))
        self.scale_text = tk.Text(f, width=40, height=14, font=("Consolas", 10),
                                  relief="solid", borderwidth=1)
        self.scale_text.pack(anchor="w")
        ttk.Button(f, text="Apply custom scale", command=self.apply_scale_text).pack(anchor="w", pady=8)
        ttk.Separator(f).pack(fill="x", pady=10)
        sec = ("Security notes:\n"
               " - The scale editor never runs code (the old exec() risk is removed).\n"
               " - Files are checked for tampering (SHA-256) and strictly validated on load.\n"
               " - Save with a password for encryption" +
               ("" if HAS_CRYPTO else "  [needs: pip install cryptography]") + ".\n"
               f" - Autosave lives in {DATA_DIR} with owner-only permissions.\n"
               " - CSV exports are protected against formula injection.")
        ttk.Label(f, text=sec, justify="left").pack(anchor="w")
        ttk.Button(f, text="Delete autosave data", command=self.delete_autosave).pack(anchor="w", pady=8)

    def _on_preset(self, _e=None):
        name = self.preset_var.get()
        if name in PRESETS:
            self.push_undo()
            self.scale_name, self.scale = name, list(PRESETS[name])
            self.mark_dirty()
            self.refresh_all()

    def _on_policy(self, _e=None):
        self.push_undo()
        self.policy = POLICIES.get(self.policy_var.get(), "all")
        self.mark_dirty()
        self.refresh_all()

    def apply_scale_text(self):
        try:
            sc = parse_scale_text(self.scale_text.get("1.0", "end"))
        except ValueError as e:
            messagebox.showerror("Scale", str(e))
            return
        self.push_undo()
        self.scale, self.scale_name = sc, "Custom edited"
        self.mark_dirty()
        self.refresh_all()
        self.set_status("Custom scale applied")

    # ------------------------------ refresh ---------------------------- #
    def refresh_all(self):
        if not hasattr(self, "tree"):
            return
        self.cur_sem = max(0, min(self.cur_sem, len(self.semesters) - 1))
        self.sem_list.delete(0, "end")
        for s in self.semesters:
            self.sem_list.insert("end", s.name)
        self.sem_list.selection_set(self.cur_sem)
        self._refill_tree()
        res = compute(self.semesters, self.scale, self.policy)
        self.dash["cgpa"].config(text=f"{res.cgpa:.2f}")
        self.dash["credits"].config(text=f"{res.credits:.0f}")
        last = next((res.sgpa[i] for i in range(len(res.sgpa) - 1, -1, -1)
                     if res.sem_credits[i] > 0), 0.0)
        self.dash["sgpa"].config(text=f"{last:.2f}")
        self.dash["standing"].config(text=standing(res.cgpa, res.credits))
        self.dash["standing"].config(font=("Segoe UI", 18, "bold"))
        self.preset_var.set(self.scale_name if self.scale_name in PRESETS else "Custom edited")
        inv = {v: k for k, v in POLICIES.items()}
        self.policy_var.set(inv.get(self.policy, "Keep all attempts"))
        self.scale_text.delete("1.0", "end")
        self.scale_text.insert("1.0", scale_to_text(self.scale))
        self._draw_chart()

    def _refill_tree(self):
        sel = set(self.tree.selection())
        self.tree.delete(*self.tree.get_children())
        sem = self.semesters[self.cur_sem]
        tot_cr = tot_pts = 0.0
        for i, c in enumerate(sem.courses):
            if c.valid():
                g = marks_to_gpa(c.marks, self.scale)
                p = g * c.credits
                tot_cr += c.credits
                tot_pts += p
                gs, ps = f"{g:.1f}", f"{p:.2f}"
                tag = "bad" if g == 0 else ("a" if i % 2 == 0 else "b")
            else:
                gs = ps = "-"
                tag = "a" if i % 2 == 0 else "b"
            marks = "" if c.marks is None else f"{c.marks:g}"
            self.tree.insert("", "end", iid=str(i), tags=(tag,),
                             values=(c.name, marks, f"{c.credits:g}", gs, ps))
        for iid in sel:
            if self.tree.exists(iid):
                self.tree.selection_add(iid)
        sg = tot_pts / tot_cr if tot_cr else 0.0
        self.foot_lbl.config(text=f"{sem.name}:  {tot_cr:.1f} credits   |   {tot_pts:.2f} quality points")
        self.foot_sgpa.config(text=f"SGPA {sg:.2f}")

    # --------------------------- semester ops -------------------------- #
    def _on_sem_select(self, _e=None):
        s = self.sem_list.curselection()
        if s:
            self.cur_sem = s[0]
            self._refill_tree()

    def add_semester(self):
        if len(self.semesters) >= MAX_SEMESTERS:
            return messagebox.showinfo("Limit", f"Maximum {MAX_SEMESTERS} semesters.")
        self.push_undo()
        self.semesters.append(Semester(f"Semester {len(self.semesters) + 1}", []))
        self.cur_sem = len(self.semesters) - 1
        self.mark_dirty()
        self.refresh_all()

    def rename_semester(self):
        name = simpledialog.askstring("Rename", "New name:", initialvalue=self.semesters[self.cur_sem].name)
        if name and clean_text(name):
            self.push_undo()
            self.semesters[self.cur_sem].name = clean_text(name, 30)
            self.mark_dirty()
            self.refresh_all()

    def delete_semester(self):
        if len(self.semesters) <= 1:
            return messagebox.showinfo("Delete", "Keep at least one semester.")
        if messagebox.askyesno("Delete", f"Delete '{self.semesters[self.cur_sem].name}'? (Undo available)"):
            self.push_undo()
            del self.semesters[self.cur_sem]
            self.mark_dirty()
            self.refresh_all()

    # ---------------------------- course ops --------------------------- #
    def add_course(self):
        sem = self.semesters[self.cur_sem]
        if len(sem.courses) >= MAX_COURSES:
            return messagebox.showinfo("Limit", f"Maximum {MAX_COURSES} courses per semester.")
        self.push_undo()
        sem.courses.append(Course("", None, 3.0))
        self.mark_dirty()
        self.refresh_all()

    def remove_courses(self):
        sel = sorted((int(i) for i in self.tree.selection()), reverse=True)
        if not sel:
            return
        self.push_undo()
        for i in sel:
            del self.semesters[self.cur_sem].courses[i]
        self.mark_dirty()
        self.refresh_all()

    def duplicate_course(self):
        sem = self.semesters[self.cur_sem]
        sel = [int(i) for i in self.tree.selection()]
        if not sel or len(sem.courses) + len(sel) > MAX_COURSES:
            return
        self.push_undo()
        for i in sel:
            sem.courses.append(copy.copy(sem.courses[i]))
        self.mark_dirty()
        self.refresh_all()

    def demo_data(self):
        if not messagebox.askyesno("Demo", "Replace current semester with demo data?"):
            return
        self.push_undo()
        demo = [("Calculus", 80, 3), ("Discrete Structures", 71, 3), ("English", 80, 3),
                ("ICT", 62, 3), ("Programming Fundamentals", 88, 3), ("Islamic Studies", 78, 2)]
        self.semesters[self.cur_sem].courses = [Course(n, m, c) for n, m, c in demo]
        self.mark_dirty()
        self.refresh_all()

    def _edit_cell(self, ev):
        if self.tree.identify("region", ev.x, ev.y) != "cell":
            return
        iid = self.tree.identify_row(ev.y)
        col = int(self.tree.identify_column(ev.x).replace("#", "")) - 1
        if col > 2 or not iid:
            return
        x, y, w, h = self.tree.bbox(iid, f"#{col + 1}")
        entry = ttk.Entry(self.tree)
        entry.insert(0, self.tree.set(iid, self.tree["columns"][col]))
        entry.place(x=x, y=y, width=w, height=h)
        entry.focus()
        entry.select_range(0, "end")
        done = {"v": False}

        def commit(_e=None):
            if done["v"]:
                return
            done["v"] = True
            val = entry.get()
            entry.destroy()
            self._set_cell(int(iid), col, val)

        entry.bind("<Return>", commit)
        entry.bind("<FocusOut>", commit)
        entry.bind("<Escape>", lambda e: (done.__setitem__("v", True), entry.destroy()))

    def _set_cell(self, idx: int, col: int, val: str):
        courses = self.semesters[self.cur_sem].courses
        if idx >= len(courses):
            return
        c = courses[idx]
        snap = self._snapshot()
        if col == 0:
            c.name = clean_text(val)
        elif col == 1:
            if val.strip() == "":
                c.marks = None
            else:
                v = parse_float(val)
                if v is None or not (0 <= v <= 100):
                    return messagebox.showwarning("Marks", "Marks must be a number from 0 to 100.")
                c.marks = v
        else:
            v = parse_float(val)
            if v is None or not (0 < v <= 12):
                return messagebox.showwarning("Credits", "Credits must be above 0 and at most 12.")
            c.credits = v
        self.undo_stack.append(snap)
        self.mark_dirty()
        self.refresh_all()

    # ------------------------------- undo ------------------------------ #
    def _snapshot(self) -> str:
        return json.dumps(state_to_dict(self.semesters, self.scale_name, self.scale, self.policy))

    def push_undo(self):
        self.undo_stack.append(self._snapshot())
        if len(self.undo_stack) > 100:
            self.undo_stack.pop(0)

    def undo(self):
        if not self.undo_stack:
            return self.set_status("Nothing to undo")
        d = json.loads(self.undo_stack.pop())
        self.semesters, self.scale_name, self.scale, self.policy = dict_to_state(d)
        self.mark_dirty()
        self.refresh_all()
        self.set_status("Undone")

    # ---------------------------- file actions ------------------------- #
    def save_project(self):
        path = filedialog.asksaveasfilename(title="Save project", defaultextension=".gpa",
                                            filetypes=[("GPA Pro project", "*.gpa"), ("JSON", "*.json")],
                                            initialfile=self.file_path.name if self.file_path else "my_gpa.gpa")
        if not path:
            return
        pw = ""
        if messagebox.askyesno("Encrypt?", "Protect this file with a password?"):
            if not HAS_CRYPTO:
                messagebox.showwarning("Encryption", "Run: pip install cryptography\nSaving without encryption.")
            else:
                pw = simpledialog.askstring("Password", "Choose a password (min 8 chars):", show="*") or ""
                if pw and len(pw) < 8:
                    messagebox.showwarning("Password", "Too short. Saving without encryption.")
                    pw = ""
                elif pw and simpledialog.askstring("Confirm", "Repeat password:", show="*") != pw:
                    messagebox.showwarning("Password", "Passwords differ. Saving without encryption.")
                    pw = ""
        try:
            payload = state_to_dict(self.semesters, self.scale_name, self.scale, self.policy)
            atomic_write(Path(path), encode_project(payload, pw))
            self.file_path, self.dirty = Path(path), False
            self.set_status(f"Saved {path}" + (" (encrypted)" if pw else ""))
        except Exception as e:
            messagebox.showerror("Save", str(e))

    def open_project(self):
        path = filedialog.askopenfilename(title="Open project",
                                          filetypes=[("GPA Pro / JSON", "*.gpa *.json"), ("All", "*.*")])
        if not path:
            return
        try:
            if os.path.getsize(path) > MAX_FILE_BYTES:
                raise ValueError("File too large")
            blob = Path(path).read_bytes()
            payload, ok = decode_project(
                blob, lambda: simpledialog.askstring("Password", "File password:", show="*"))
            if not ok and not messagebox.askyesno(
                    "Integrity", "No valid checksum (file edited or from another source).\nOpen anyway?"):
                return
            self.push_undo()
            self.semesters, self.scale_name, self.scale, self.policy = dict_to_state(payload)
            self.file_path, self.cur_sem = Path(path), 0
            self.refresh_all()
            self.set_status(f"Opened {path}")
        except Exception as e:
            messagebox.showerror("Open", f"Could not open file:\n{e}")

    def export_csv(self):
        path = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV", "*.csv")])
        if not path:
            return
        try:
            with open(path, "w", newline="", encoding="utf-8-sig") as f:
                w = csv.writer(f)
                w.writerow(["Semester", "Course", "Marks", "Credits", "GPA"])
                for s in self.semesters:
                    for c in s.courses:
                        g = f"{marks_to_gpa(c.marks, self.scale):.1f}" if c.valid() else ""
                        w.writerow([csv_safe(s.name), csv_safe(c.name),
                                    "" if c.marks is None else c.marks, c.credits, g])
            self.set_status(f"Exported {path}")
        except Exception as e:
            messagebox.showerror("Export", str(e))

    def import_csv(self):
        """Columns: Semester, Course, Marks, Credits (header row required)."""
        path = filedialog.askopenfilename(filetypes=[("CSV", "*.csv")])
        if not path:
            return
        try:
            if os.path.getsize(path) > MAX_FILE_BYTES:
                raise ValueError("File too large")
            sems: dict = {}
            with open(path, newline="", encoding="utf-8-sig") as f:
                for row in csv.DictReader(f):
                    sn = clean_text(row.get("Semester") or "Semester 1", 30)
                    marks = row.get("Marks")
                    marks = parse_float(marks) if marks not in (None, "") else None
                    if marks is not None and not (0 <= marks <= 100):
                        marks = None
                    cr = parse_float(row.get("Credits") or 3) or 3.0
                    if not (0 < cr <= 12):
                        cr = 3.0
                    lst = sems.setdefault(sn, [])
                    if len(lst) < MAX_COURSES:
                        lst.append(Course(clean_text(row.get("Course") or ""), marks, cr))
            if not sems or len(sems) > MAX_SEMESTERS:
                raise ValueError("No usable rows (needs Semester, Course, Marks, Credits columns)")
            self.push_undo()
            self.semesters = [Semester(n, c) for n, c in sems.items()]
            self.cur_sem = 0
            self.mark_dirty()
            self.refresh_all()
            self.set_status(f"Imported {path}")
        except Exception as e:
            messagebox.showerror("Import", str(e))

    def export_html(self):
        path = filedialog.asksaveasfilename(defaultextension=".html", filetypes=[("HTML", "*.html")])
        if not path:
            return
        res = compute(self.semesters, self.scale, self.policy)
        e = html.escape
        parts = [f"<h1>Academic Report</h1><p>Generated {datetime.now():%Y-%m-%d %H:%M}</p>",
                 f"<h2>CGPA {res.cgpa:.2f} &mdash; {e(standing(res.cgpa, res.credits))} "
                 f"({res.credits:.0f} credits)</h2>"]
        for i, s in enumerate(self.semesters):
            parts.append(f"<h3>{e(s.name)} &mdash; SGPA {res.sgpa[i]:.2f}</h3><table><tr>"
                         "<th>Course</th><th>Marks</th><th>Credits</th><th>GPA</th></tr>")
            for c in s.courses:
                g = f"{marks_to_gpa(c.marks, self.scale):.1f}" if c.valid() else "-"
                m = "" if c.marks is None else f"{c.marks:g}"
                parts.append(f"<tr><td>{e(c.name)}</td><td>{m}</td><td>{c.credits:g}</td><td>{g}</td></tr>")
            parts.append("</table>")
        css = ("body{font-family:Segoe UI,Arial,sans-serif;max-width:800px;margin:30px auto;color:#1a1d29}"
               "table{border-collapse:collapse;width:100%;margin-bottom:18px}"
               "th,td{border:1px solid #ccc;padding:6px 10px;text-align:left}th{background:#2563eb;color:#fff}")
        doc = (f"<!doctype html><html><head><meta charset='utf-8'><title>Report</title>"
               f"<style>{css}</style></head><body>{''.join(parts)}</body></html>")
        try:
            atomic_write(Path(path), doc.encode("utf-8"))
            self.set_status(f"Report saved: {path} (open in browser, Ctrl+P to save as PDF)")
        except Exception as ex:
            messagebox.showerror("Report", str(ex))

    # ---------------------------- autosave/misc ------------------------ #
    def _try_restore_autosave(self):
        try:
            if AUTOSAVE_PATH.exists() and AUTOSAVE_PATH.stat().st_size < MAX_FILE_BYTES:
                payload, _ = decode_project(AUTOSAVE_PATH.read_bytes(), lambda: "")
                self.semesters, self.scale_name, self.scale, self.policy = dict_to_state(payload)
        except Exception:
            pass  # a bad autosave must never block startup

    def _autosave(self):
        try:
            payload = state_to_dict(self.semesters, self.scale_name, self.scale, self.policy)
            atomic_write(AUTOSAVE_PATH, encode_project(payload))
        except Exception:
            pass

    def delete_autosave(self):
        try:
            AUTOSAVE_PATH.unlink(missing_ok=True)
            self.set_status("Autosave deleted")
        except Exception as e:
            messagebox.showerror("Autosave", str(e))

    def mark_dirty(self):
        self.dirty = True
        self._autosave()

    def toggle_theme(self):
        self.theme = "dark" if self.theme == "light" else "light"
        self._apply_theme()

    def set_status(self, text: str):
        self.status.config(text=text)

    def _bind_keys(self):
        self.bind_all("<Control-z>", lambda e: self.undo())
        self.bind_all("<Control-s>", lambda e: self.save_project())
        self.bind_all("<Control-o>", lambda e: self.open_project())
        self.bind_all("<Control-n>", lambda e: self.add_course())

    def _on_close(self):
        self._autosave()
        self.destroy()


if __name__ == "__main__":
    App().mainloop()