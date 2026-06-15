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
