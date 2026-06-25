"""Read the focused control's text via UI Automation (best-effort, import-guarded).

Returns None whenever UIA is unavailable or the control doesn't expose text — the
auto-learn feature then simply does nothing. Never raises.
"""
import logging
import threading

log = logging.getLogger(__name__)

_tls = threading.local()   # COM objects are apartment-bound -> one client per thread
_lib = None
_failed = False


def _client():
    """Return a per-thread IUIAutomation client. Each thread (worker, clipboard-restore)
    gets its own, since COM interface pointers can't be shared across apartments."""
    global _lib, _failed
    if _failed:
        return None, None
    client = getattr(_tls, "client", None)
    if client is not None:
        return client, _lib
    try:
        import comtypes
        import comtypes.client

        comtypes.CoInitialize()
        if _lib is None:
            _lib = comtypes.client.GetModule("UIAutomationCore.dll")
        client = comtypes.client.CreateObject(
            _lib.CUIAutomation, interface=_lib.IUIAutomation)
        _tls.client = client
        return client, _lib
    except Exception:
        log.info("UI Automation unavailable", exc_info=True)
        _failed = True
        return None, None


def focused_is_text_input():
    """Best-effort: is the focused control somewhere a paste (Ctrl+V) would land?

    Deliberately conservative — it returns False ONLY for controls that clearly can't
    take typed text (a button, menu item, checkbox, …). Real text boxes, rich editors,
    containers and anything ambiguous return True/None so the caller pastes as normal.
    This avoids the far worse failure of diverting a genuine paste to the copy overlay.
    """
    iuia, lib = _client()
    if iuia is None:
        return None
    try:
        el = iuia.GetFocusedElement()
        if el is None:
            return None
        # Editable signals -> definitely paste.
        try:
            patt = el.GetCurrentPattern(lib.UIA_ValuePatternId)
            if patt:
                vp = patt.QueryInterface(lib.IUIAutomationValuePattern)
                if not vp.CurrentIsReadOnly:
                    return True
                # a read-only ValuePattern is NOT proof it can't take a paste (many
                # editable controls mis-report it) — fall through, don't conclude False
        except Exception:
            pass
        try:
            if el.GetCurrentPattern(lib.UIA_TextPatternId):
                return True   # a text surface (editor, doc, code editor)
        except Exception:
            pass
        try:
            ctype = el.CurrentControlType
        except Exception:
            return None
        if ctype in (lib.UIA_EditControlTypeId, lib.UIA_DocumentControlTypeId):
            return True
        # Only these clearly can't receive typed text. Everything else (panes, groups,
        # lists, unknown custom controls) is treated as paste-able.
        try:
            non_text = {
                lib.UIA_ButtonControlTypeId, lib.UIA_CheckBoxControlTypeId,
                lib.UIA_RadioButtonControlTypeId, lib.UIA_MenuItemControlTypeId,
                lib.UIA_HyperlinkControlTypeId, lib.UIA_TabItemControlTypeId,
            }
        except Exception:
            return None
        return False if ctype in non_text else None
    except Exception:
        log.debug("focused_is_text_input failed", exc_info=True)
        return None


def read_selected_text() -> str | None:
    """Return the currently selected text via TextPattern.GetSelection (no keystrokes),
    or None if there's no selection or UIA can't read it. Used as a fallback when the
    Ctrl+C copy comes back empty."""
    iuia, lib = _client()
    if iuia is None:
        return None
    try:
        el = iuia.GetFocusedElement()
        if el is None:
            return None
        patt = el.GetCurrentPattern(lib.UIA_TextPatternId)
        if not patt:
            return None
        tp = patt.QueryInterface(lib.IUIAutomationTextPattern)
        ranges = tp.GetSelection()
        if ranges is None or ranges.Length <= 0:
            return None
        parts = []
        for i in range(ranges.Length):
            try:
                parts.append(ranges.GetElement(i).GetText(-1))
            except Exception:
                pass
        text = "".join(parts).strip()
        return text or None
    except Exception:
        log.debug("read_selected_text failed", exc_info=True)
        return None


def read_focused_text() -> str | None:
    """Return the focused control's text (ValuePattern, else TextPattern), or None."""
    iuia, lib = _client()
    if iuia is None:
        return None
    try:
        el = iuia.GetFocusedElement()
        if el is None:
            return None
        try:
            patt = el.GetCurrentPattern(lib.UIA_ValuePatternId)
            if patt:
                value = patt.QueryInterface(lib.IUIAutomationValuePattern).CurrentValue
                if value:
                    return value
        except Exception:
            pass
        try:
            patt = el.GetCurrentPattern(lib.UIA_TextPatternId)
            if patt:
                rng = patt.QueryInterface(lib.IUIAutomationTextPattern).DocumentRange
                text = rng.GetText(-1)
                if text:
                    return text
        except Exception:
            pass
        return None
    except Exception:
        log.debug("read_focused_text failed", exc_info=True)
        return None
