"""Read the focused control's text via UI Automation (best-effort, import-guarded).

Returns None whenever UIA is unavailable or the control doesn't expose text — the
auto-learn feature then simply does nothing. Never raises.
"""
import logging

log = logging.getLogger(__name__)

_iuia = None
_lib = None
_failed = False


def _client():
    global _iuia, _lib, _failed
    if _failed:
        return None, None
    if _iuia is not None:
        return _iuia, _lib
    try:
        import comtypes
        import comtypes.client

        comtypes.CoInitialize()
        _lib = comtypes.client.GetModule("UIAutomationCore.dll")
        _iuia = comtypes.client.CreateObject(
            _lib.CUIAutomation, interface=_lib.IUIAutomation)
        return _iuia, _lib
    except Exception:
        log.info("UI Automation unavailable; auto-learn dictionary disabled", exc_info=True)
        _failed = True
        return None, None


def focused_is_text_input():
    """Best-effort: is the focused control somewhere a paste (Ctrl+V) would land?

    Returns True for editable text controls, False for clearly non-text controls
    (buttons, panes/desktop, list items, …), and None when UIA can't tell — callers
    should treat None as 'probably fine, go ahead and paste'.
    """
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
                vp = patt.QueryInterface(lib.IUIAutomationValuePattern)
                return not vp.CurrentIsReadOnly   # writable edit -> True, read-only -> False
        except Exception:
            pass
        try:
            ctype = el.CurrentControlType
        except Exception:
            return None
        if ctype in (lib.UIA_EditControlTypeId, lib.UIA_DocumentControlTypeId):
            return True
        non_text = {
            lib.UIA_ButtonControlTypeId, lib.UIA_CheckBoxControlTypeId,
            lib.UIA_RadioButtonControlTypeId, lib.UIA_MenuItemControlTypeId,
            lib.UIA_HyperlinkControlTypeId, lib.UIA_TabItemControlTypeId,
            lib.UIA_ListItemControlTypeId, lib.UIA_TreeItemControlTypeId,
            lib.UIA_ImageControlTypeId, lib.UIA_PaneControlTypeId,
            lib.UIA_WindowControlTypeId, lib.UIA_TextControlTypeId,
        }
        if ctype in non_text:
            return False
        return None
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
