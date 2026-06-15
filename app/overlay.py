"""Always-on-top status pill (tkinter on its own thread, queue-driven).

WS_EX_NOACTIVATE | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW make it click-through
and focus-neutral so the paste target keeps focus.
"""
import logging
import queue
import threading

log = logging.getLogger(__name__)

GWL_EXSTYLE = -20
WS_EX_NOACTIVATE = 0x08000000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOOLWINDOW = 0x00000080

COLORS = {"recording": "#e74c3c", "transcribing": "#e67e22"}


class Overlay:
    def __init__(self, enabled: bool = True):
        self.enabled = enabled
        self._q: queue.Queue = queue.Queue()
        if enabled:
            threading.Thread(target=self._run, daemon=True, name="overlay").start()

    def show(self, text: str, mode: str):
        if self.enabled:
            self._q.put(("show", text, COLORS.get(mode, "#888888")))

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

            root = tk.Tk()
            root.overrideredirect(True)
            root.attributes("-topmost", True)
            root.attributes("-alpha", 0.92)
            root.configure(bg="#1e1e1e")
            label = tk.Label(root, text="", font=("Segoe UI", 11), fg="white",
                             bg="#1e1e1e", padx=18, pady=8)
            label.pack()
            root.withdraw()
            self._apply_exstyles(root)

            def poll():
                try:
                    while True:
                        cmd, text, color = self._q.get_nowait()
                        if cmd == "show":
                            label.config(text=text, fg=color)
                            root.update_idletasks()
                            w = root.winfo_reqwidth()
                            x = (root.winfo_screenwidth() - w) // 2
                            y = root.winfo_screenheight() - 140
                            root.geometry(f"+{x}+{y}")
                            root.deiconify()
                            root.attributes("-topmost", True)
                            self._apply_exstyles(root)
                        elif cmd == "hide":
                            root.withdraw()
                        elif cmd == "close":
                            root.destroy()
                            return
                except queue.Empty:
                    pass
                root.after(50, poll)

            root.after(50, poll)
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
