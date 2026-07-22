"""System tray icon and menu (pystray). Runs on the main thread."""
import logging
import threading

import pystray
from PIL import Image, ImageDraw
from pystray import Menu
from pystray import MenuItem as Item

from . import startup
from .i18n import tr

log = logging.getLogger(__name__)

_icon_lock = threading.Lock()


def apply_icon(icon, image) -> None:
    """Set the tray icon image safely. pystray's Win32 backend recreates the native
    icon handle on every assignment and is NOT thread-safe. The hotkey, worker and
    watchdog threads all change the state, and two racing updates raised
    ``OSError: [WinError 1402] invalid icon handle`` — which, happening mid-``_stop``,
    silently dropped the in-flight dictation. Serialize the updates with a lock and
    never let a backend hiccup escape: the icon is purely cosmetic."""
    with _icon_lock:
        try:
            icon.icon = image
        except Exception:
            log.warning("tray icon update failed (ignored)", exc_info=True)

# The mic takes the state colour (idle grey, recording red, transcribing orange); the
# duck stays yellow so the icon is always recognisable.
COLORS = {"idle": "#9e9e9e", "recording": "#e74c3c", "transcribing": "#e67e22"}
_DUCK = "#ffd23f"
_DUCK_WING = "#f2b705"
_BEAK = "#ff8c00"
_EYE = "#1c1c22"


def make_icon_image(state: str) -> Image.Image:
    """A cute duck quacking into a microphone."""
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    mic = COLORS.get(state, COLORS["idle"])

    # duck body + head
    d.ellipse([4, 32, 40, 60], fill=_DUCK)          # body
    d.ellipse([16, 12, 44, 40], fill=_DUCK)         # head
    d.chord([12, 40, 34, 56], 200, 20, fill=_DUCK_WING)   # wing
    d.ellipse([32, 20, 38, 26], fill=_EYE)          # eye
    # open beak (quacking) pointing toward the mic
    d.polygon([(42, 24), (56, 23), (44, 29)], fill=_BEAK)   # upper bill
    d.polygon([(42, 31), (54, 32), (44, 29)], fill=_BEAK)   # lower bill

    # microphone the duck is quacking into
    d.rounded_rectangle([52, 30, 61, 47], radius=4, fill=mic)   # capsule
    d.line([56, 47, 56, 55], fill=mic, width=3)                 # stand
    d.line([50, 56, 62, 56], fill=mic, width=3)                 # base
    if state == "recording":                                    # little sound waves
        d.arc([44, 22, 52, 38], 300, 60, fill=mic, width=2)
    return img


def run_tray(app, on_ready=None):
    """Blocks on the pystray loop until Quit. `app` is __main__.App."""

    def t(key):
        return tr(key, app.cfg.get("ui_language", "en"))

    animated = app.cfg.get("animated_tray_icon", True)
    icon = pystray.Icon("Yappity Yapp", make_icon_image("idle"), title="Yappity Yapp")
    state_images = {}

    def set_state(state):
        # Flat-icon mode: never mutate icon.icon, so the tray icon can't be a source of
        # cross-thread update races. Recording state still shows in the overlay pill.
        if not animated:
            return
        img = state_images.get(state)
        if img is None:
            img = state_images[state] = make_icon_image(state)
        apply_icon(icon, img)

    def lang_item(label_key, value):
        return Item(
            lambda item: t(label_key),
            lambda: (app.set_language(value), icon.update_menu()),
            checked=lambda item: app.cfg["language"] == value,
            radio=True,
        )

    def ui_lang_item(label, value):
        return Item(
            label,
            lambda: (app.set_ui_language(value), rebuild()),
            checked=lambda item: app.cfg["ui_language"] == value,
            radio=True,
        )

    def provider_item(label, value):
        return Item(
            label,
            lambda: (app.set_provider(value), rebuild()),
            checked=lambda item: app.cfg.get("provider") == value,
            radio=True,
        )

    def style_item(value):
        return Item(
            value.capitalize(),
            lambda: (app.set_cleanup_style(value), icon.update_menu()),
            checked=lambda item: app.cfg.get("cleanup", {}).get("style") == value,
            radio=True,
        )

    def recent_menu():
        entries = app.recent_entries(8)
        if not entries:
            return Menu(Item(lambda item: t("no_history"), None, enabled=False))
        items = []
        for entry in entries:
            text = entry.get("text", "")
            preview = ((text[:40] + "…") if len(text) > 40 else text).replace("\n", " ")
            items.append(Item(preview, (lambda tx: lambda: app.copy_recent(tx))(text)))
        return Menu(*items)

    def remove_menu():
        words = app.dictionary_words()   # [(word, is_auto), ...]
        if not words:
            return Menu(Item(lambda item: t("no_words"), None, enabled=False))
        items = []
        for word, is_auto in words[:30]:
            label = word + (f"  ({t('auto_tag')})" if is_auto else "")
            items.append(Item(label, (lambda w: lambda: (app.remove_word(w), rebuild()))(word)))
        return Menu(*items)

    def toggle_startup():
        try:
            if startup.is_installed():
                startup.uninstall()
                app.notifier.toast(t("startup_off"))
            else:
                startup.install()
                app.notifier.toast(t("startup_on"))
        except Exception as e:
            log.exception("startup toggle failed")
            app.notifier.toast(str(e))
        icon.update_menu()

    def toggle_desktop():
        try:
            if startup.desktop_shortcut_installed():
                startup.uninstall_desktop_shortcut()
            else:
                startup.install_desktop_shortcut()
        except Exception as e:
            log.exception("desktop shortcut toggle failed")
            app.notifier.toast(str(e))
        icon.update_menu()

    def build_menu():
        return Menu(
            Item(lambda item: t("ready"), None, enabled=False),
            Menu.SEPARATOR,
            Item(lambda item: t("cleanup_toggle"),
                 lambda: (app.toggle_cleanup(), icon.update_menu()),
                 checked=lambda item: app.cfg.get("cleanup", {}).get("enabled", True)),
            Item(lambda item: t("cleanup_style"), Menu(
                style_item("light"),
                style_item("balanced"),
                style_item("heavy"),
            )),
            Item(lambda item: t("language"), Menu(
                lang_item("lang_auto", "auto"),
                lang_item("lang_en", "en"),
                lang_item("lang_zh", "zh"),
            )),
            Item(lambda item: t("provider"), Menu(
                provider_item("OpenAI", "openai"),
                provider_item("ElevenLabs", "elevenlabs"),
                provider_item("Groq", "groq"),
            )),
            Item(lambda item: t("ui_language"), Menu(
                ui_lang_item("English", "en"),
                ui_lang_item("繁體中文", "zh-TW"),
            )),
            Menu.SEPARATOR,
            Item(lambda item: t("recent"), recent_menu()),
            Item(lambda item: t("add_words"), lambda: app.add_words()),
            Item(lambda item: t("import_words"), lambda: app.import_words()),
            Item(lambda item: t("remove_word"), remove_menu()),
            Item(lambda item: t("dashboard"), lambda: app.open_dashboard()),
            Item(lambda item: t("stats"), lambda: app.show_stats()),
            Item(lambda item: t("retry_last"), lambda: app.retry_last()),
            Item(lambda item: t("open_history"), lambda: app.open_history()),
            Item(lambda item: t("open_config"), lambda: app.open_config()),
            Item(lambda item: t("help"), lambda: app.open_help()),
            Item(lambda item: t("start_with_windows"), toggle_startup,
                 checked=lambda item: startup.is_installed()),
            Item(lambda item: t("desktop_shortcut"), toggle_desktop,
                 checked=lambda item: startup.desktop_shortcut_installed()),
            Menu.SEPARATOR,
            Item(lambda item: t("quit"), lambda: (app.shutdown(), icon.stop())),
        )

    def rebuild():
        icon.menu = build_menu()
        icon.update_menu()

    def setup(icon_obj):
        icon_obj.visible = True
        if on_ready is not None:
            try:
                on_ready()
            except Exception:
                log.exception("on_ready failed")

    icon.menu = build_menu()
    app.set_tray_state = set_state
    app.on_history_changed = rebuild   # refresh the Recent submenu after dictations
    app.notifier.set_sink(lambda msg, title: icon.notify(msg, title))
    icon.run(setup=setup)
