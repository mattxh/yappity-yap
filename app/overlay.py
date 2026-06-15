"""Sleek 'glass pill' status overlay (tkinter on its own thread, queue-driven).

A rounded, slightly translucent dark pill with a softly pulsing status dot, a label,
and a dimmer hint. Uses a Windows -transparentcolor key so the area outside the pill is
fully transparent (true rounded corners). WS_EX_NOACTIVATE | WS_EX_TRANSPARENT |
WS_EX_TOOLWINDOW keep it click-through and focus-neutral so the paste target keeps focus.
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

TRANSPARENT_KEY = "#FF00FF"   # color mapped to "transparent" by Windows
PILL_BG = "#1c1c20"
BORDER = "#3a3a40"
LABEL_FG = "#f4f4f5"
HINT_FG = "#86868f"
ACCENTS = {"recording": "#f4796f", "transcribing": "#f0a83a"}
LEADING_GLYPHS = ("● ", "✍ ")  # "● ", "✍ " — we draw our own dot instead


def _blend(c1: str, c2: str, t: float) -> str:
    a = [int(c1[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(c2[i:i + 2], 16) for i in (1, 3, 5)]
    return "#%02x%02x%02x" % tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


class Overlay:
    def __init__(self, enabled: bool = True):
        self.enabled = enabled
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
            root.attributes("-alpha", 0.96)
            try:
                root.attributes("-transparentcolor", TRANSPARENT_KEY)
            except tk.TclError:
                pass
            root.configure(bg=TRANSPARENT_KEY)
            canvas = tk.Canvas(root, bg=TRANSPARENT_KEY, highlightthickness=0, bd=0)
            canvas.pack()
            label_font = tkfont.Font(family="Segoe UI", size=11)
            hint_font = tkfont.Font(family="Segoe UI", size=10)
            st = {"accent": "#9aa0a6", "dim": "#1c1c20", "dot": None,
                  "phase": 0.0, "visible": False}

            def round_rect(x1, y1, x2, y2, r, **kw):
                pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2,
                       x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
                return canvas.create_polygon(pts, smooth=True, **kw)

            def build(text, mode):
                canvas.delete("all")
                accent = ACCENTS.get(mode, "#9aa0a6")
                for g in LEADING_GLYPHS:
                    if text.startswith(g):
                        text = text[len(g):]
                        break
                if " — " in text:           # split on em dash → label + hint
                    label, hint = text.split(" — ", 1)
                else:
                    label, hint = text, ""
                pad, dot_r, gap, h = 18, 5, 11, 40
                lw = label_font.measure(label)
                hw = hint_font.measure(hint) if hint else 0
                w = pad + dot_r * 2 + gap + lw + ((gap + hw) if hint else 0) + pad
                canvas.config(width=w, height=h)
                round_rect(2, 2, w - 2, h - 2, (h - 4) // 2,
                           fill=PILL_BG, outline=BORDER, width=1)
                cy = h // 2
                dot = canvas.create_oval(pad, cy - dot_r, pad + dot_r * 2, cy + dot_r,
                                         fill=accent, outline="")
                tx = pad + dot_r * 2 + gap
                canvas.create_text(tx, cy, text=label, fill=LABEL_FG,
                                   font=label_font, anchor="w")
                if hint:
                    canvas.create_text(tx + lw + gap, cy, text=hint, fill=HINT_FG,
                                       font=hint_font, anchor="w")
                st.update(accent=accent, dim=_blend(accent, PILL_BG, 0.6),
                          dot=dot, phase=0.0)
                root.update_idletasks()
                sx = (root.winfo_screenwidth() - w) // 2
                sy = root.winfo_screenheight() - 140
                root.geometry(f"{w}x{h}+{sx}+{sy}")
                root.deiconify()
                root.attributes("-topmost", True)
                self._apply_exstyles(root)

            def animate():
                if st["visible"] and st["dot"] is not None:
                    st["phase"] += 0.09
                    t = (1 + math.sin(st["phase"])) / 2     # 0..1 breathing
                    canvas.itemconfig(st["dot"], fill=_blend(st["accent"], st["dim"], 1 - t))
                root.after(50, animate)

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
            root.after(50, animate)
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
