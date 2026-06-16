"""Sleek 'glass pill' status overlay (tkinter on its own thread, queue-driven).

A rounded, slightly translucent dark pill. Recording shows a minimal animated
waveform; transcribing shows a softly pulsing dot. Rendered DPI-aware so it stays
crisp on scaled displays. A Windows -transparentcolor key gives true rounded corners;
WS_EX_NOACTIVATE | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW keep it click-through and
focus-neutral so the paste target keeps focus.
"""
import logging
import math
import queue
import threading

log = logging.getLogger(__name__)

GWL_EXSTYLE = -20
WS_EX_NOACTIVATE = 0x08000000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOOLWINDOW = 0x00000080

TRANSPARENT_KEY = "#FF00FF"
PILL_BG = "#1c1c20"
BORDER = "#3a3a40"
LABEL_FG = "#f4f4f5"
HINT_FG = "#86868f"
ACCENTS = {"recording": "#f4796f", "transcribing": "#ffd24a", "command": "#9b8cff"}
WAVE_MODES = ("recording", "command")   # show the live waveform (else dots)
LEADING_GLYPHS = ("● ", "✍ ")

_N_BARS = 11        # wider waveform array for the recording state
_N_DOTS = 5         # transcribing: a wave of small dots


def _bar_params(i: int, n: int):
    """Per-bar (speed, phase offset, center-weighted shape) for the waveform."""
    shape = 0.4 + 0.6 * math.sin(math.pi * (i + 0.5) / n)
    speed = 1.0 + 0.15 * (i % 5)
    offset = i * 0.8
    return speed, offset, shape


def _blend(c1: str, c2: str, t: float) -> str:
    a = [int(c1[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(c2[i:i + 2], 16) for i in (1, 3, 5)]
    return "#%02x%02x%02x" % tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


class Overlay:
    def __init__(self, enabled: bool = True, level_source=None):
        self.enabled = enabled
        self._level_source = level_source   # callable() -> 0..1 live mic loudness
        self._q: queue.Queue = queue.Queue()
        if enabled:
            threading.Thread(target=self._run, daemon=True, name="overlay").start()

    def show(self, text: str, mode: str):
        if self.enabled:
            self._q.put(("show", text, mode))

    def hide(self):
        if self.enabled:
            self._q.put(("hide", None, None))

    def close(self):
        if self.enabled:
            self._q.put(("close", None, None))

    # -- overlay thread -------------------------------------------------------

    def _run(self):
        try:
            import tkinter as tk
            from tkinter import font as tkfont

            root = tk.Tk()
            root.overrideredirect(True)
            root.attributes("-topmost", True)
            root.attributes("-alpha", 0.97)
            try:
                root.attributes("-transparentcolor", TRANSPARENT_KEY)
            except tk.TclError:
                pass
            root.configure(bg=TRANSPARENT_KEY)
            canvas = tk.Canvas(root, bg=TRANSPARENT_KEY, highlightthickness=0, bd=0)
            canvas.pack()

            scale = max(1.0, root.winfo_fpixels("1i") / 96.0)   # DPI factor (e.g. 1.5)

            def s(px):
                return int(round(px * scale))

            label_font = tkfont.Font(family="Segoe UI", size=-s(12))
            hint_font = tkfont.Font(family="Segoe UI", size=-s(10))
            st = {"mode": None, "accent": "#9aa0a6", "dim": PILL_BG, "dot": None,
                  "dots": [], "bars": [], "cy": 0, "hmin": 0, "hmax": 0, "dr": 0,
                  "phase": 0.0, "lvl": 0.0, "visible": False}

            def round_rect(x1, y1, x2, y2, r, **kw):
                pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2,
                       x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
                return canvas.create_polygon(pts, smooth=True, **kw)

            def build(text, mode):
                canvas.delete("all")
                st["bars"], st["dot"], st["dots"] = [], None, []
                accent = ACCENTS.get(mode, "#9aa0a6")
                for g in LEADING_GLYPHS:
                    if text.startswith(g):
                        text = text[len(g):]
                        break
                label, hint = (text.split(" — ", 1) + [""])[:2]
                textless = (mode == "recording")   # recording shows only the waveform
                pad, gap, h = s(12), s(8), s(28)
                bar_w, bar_gap = s(3), s(4)        # wider gap -> wider waveform array
                dot_r, dot_step = s(2), s(7)
                if mode in WAVE_MODES:
                    ind_w = _N_BARS * bar_w + (_N_BARS - 1) * bar_gap
                elif mode == "transcribing":
                    ind_w = (_N_DOTS - 1) * dot_step + 2 * dot_r
                else:
                    ind_w = s(9)
                lw = label_font.measure(label) if not textless else 0
                hw = hint_font.measure(hint) if (hint and not textless) else 0
                if textless:
                    w = pad + ind_w + pad
                else:
                    w = pad + ind_w + gap + lw + ((gap + hw) if hint else 0) + pad
                canvas.config(width=w, height=h)
                round_rect(s(1), s(1), w - s(1), h - s(1), (h - s(2)) // 2,
                           fill=PILL_BG, outline=BORDER, width=max(1, s(1)))
                cy = h // 2
                if mode in WAVE_MODES:
                    x = pad + bar_w // 2
                    for i in range(_N_BARS):
                        sp, off, shape = _bar_params(i, _N_BARS)
                        bid = canvas.create_line(x, cy - s(3), x, cy + s(3),
                                                 fill=accent, width=bar_w, capstyle="round")
                        st["bars"].append({"id": bid, "x": x, "sp": sp, "off": off,
                                           "shape": shape})
                        x += bar_w + bar_gap
                    st.update(cy=cy, hmin=s(1), hmax=s(7), lvl=0.0)
                elif mode == "transcribing":
                    x = pad + dot_r
                    for i in range(_N_DOTS):
                        did = canvas.create_oval(x - dot_r, cy - dot_r, x + dot_r, cy + dot_r,
                                                 fill=accent, outline="")
                        st["dots"].append({"id": did, "x": x, "off": i * 0.7})
                        x += dot_step
                    st.update(cy=cy, dr=dot_r)
                else:
                    dr = s(4)
                    st["dot"] = canvas.create_oval(pad, cy - dr, pad + 2 * dr, cy + dr,
                                                   fill=accent, outline="")
                if not textless:
                    tx = pad + ind_w + gap
                    canvas.create_text(tx, cy, text=label, fill=LABEL_FG,
                                       font=label_font, anchor="w")
                    if hint:
                        canvas.create_text(tx + lw + gap, cy, text=hint, fill=HINT_FG,
                                           font=hint_font, anchor="w")
                st.update(mode=mode, accent=accent, dim=_blend(accent, PILL_BG, 0.6),
                          phase=0.0)
                root.update_idletasks()
                sx = (root.winfo_screenwidth() - w) // 2
                sy = root.winfo_screenheight() - s(96)
                root.geometry(f"{w}x{h}+{sx}+{sy}")
                root.deiconify()
                root.attributes("-topmost", True)
                self._apply_exstyles(root)

            def animate():
                if st["visible"]:
                    st["phase"] += 0.16
                    if st["mode"] in WAVE_MODES and st["bars"]:
                        target = 0.0
                        if self._level_source is not None:
                            try:
                                target = float(self._level_source())
                            except Exception:
                                target = 0.0
                        else:
                            target = 0.5 + 0.5 * math.sin(st["phase"])  # no source: gentle loop
                        st["lvl"] += (target - st["lvl"]) * 0.5           # smooth jitter
                        lvl = max(0.0, min(1.0, st["lvl"]))
                        cy, hmin, hmax = st["cy"], st["hmin"], st["hmax"]
                        for b in st["bars"]:
                            wig = 0.85 + 0.15 * math.sin(st["phase"] * b["sp"] + b["off"])
                            frac = min(1.0, lvl * b["shape"] * wig)
                            hh = hmin + (hmax - hmin) * frac
                            canvas.coords(b["id"], b["x"], cy - hh, b["x"], cy + hh)
                    elif st["dots"]:
                        cy, dr = st["cy"], st["dr"]
                        for d in st["dots"]:
                            ph = st["phase"] * 1.6 + d["off"]
                            bri = 0.5 + 0.5 * math.sin(ph)        # brightness wave
                            bob = -math.sin(ph) * dr              # small vertical bob
                            canvas.coords(d["id"], d["x"] - dr, cy + bob - dr,
                                          d["x"] + dr, cy + bob + dr)
                            canvas.itemconfig(d["id"], fill=_blend(st["dim"], st["accent"], bri))
                    elif st["dot"] is not None:
                        t = (1 + math.sin(st["phase"])) / 2
                        canvas.itemconfig(st["dot"], fill=_blend(st["accent"], st["dim"], 1 - t))
                root.after(33, animate)

            def poll():
                try:
                    while True:
                        cmd, text, mode = self._q.get_nowait()
                        if cmd == "show":
                            st["visible"] = True
                            build(text, mode)
                        elif cmd == "hide":
                            st["visible"] = False
                            root.withdraw()
                        elif cmd == "close":
                            root.destroy()
                            return
                except queue.Empty:
                    pass
                root.after(40, poll)

            root.withdraw()
            root.after(40, poll)
            root.after(33, animate)
            root.mainloop()
        except Exception:
            log.exception("overlay thread died (app continues without overlay)")

    @staticmethod
    def _apply_exstyles(root):
        try:
            import ctypes

            hwnd = ctypes.windll.user32.GetParent(root.winfo_id()) or root.winfo_id()
            style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            style |= WS_EX_NOACTIVATE | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW
            ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)
        except Exception:
            log.debug("exstyle apply failed", exc_info=True)


class NullOverlay:
    """Used when show_overlay is false or tkinter is unavailable."""

    def show(self, text, mode):
        pass

    def hide(self):
        pass

    def close(self):
        pass
