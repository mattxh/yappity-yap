"""System tray icon and menu (pystray). Runs on the main thread."""
import logging

import pystray
from PIL import Image, ImageDraw
from pystray import Menu
from pystray import MenuItem as Item

from . import startup
from .i18n import tr

log = logging.getLogger(__name__)

COLORS = {"idle": "#9e9e9e", "recording": "#e74c3c", "transcribing": "#e67e22"}


def make_icon_image(state: str) -> Image.Image:
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    color = COLORS.get(state, COLORS["idle"])
    d.rounded_rectangle([22, 8, 42, 38], radius=10, fill=color)      # mic capsule
    d.arc([14, 22, 50, 50], start=0, end=180, fill=color, width=4)   # cradle
    d.line([32, 50, 32, 58], fill=color, width=4)                    # stem
    d.line([22, 58, 42, 58], fill=color, width=4)                    # base
    return img


def run_tray(app, on_ready=None):
    """Blocks on the pystray loop until Quit. `app` is __main__.App."""

    def t(key):
        return tr(key, app.cfg.get("ui_language", "en"))

    icon = pystray.Icon("VoiceToText", make_icon_image("idle"), title="VoiceToText")

    def set_state(state):
        icon.icon = make_icon_image(state)

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
            items.append(Item(preview, (lambda tx: lambda: app.reinsert(tx))(text)))
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
            Item(lambda item: t("add_word"), lambda: app.add_word()),
            Item(lambda item: t("dashboard"), lambda: app.open_dashboard()),
            Item(lambda item: t("stats"), lambda: app.show_stats()),
            Item(lambda item: t("retry_last"), lambda: app.retry_last()),
            Item(lambda item: t("open_history"), lambda: app.open_history()),
            Item(lambda item: t("open_config"), lambda: app.open_config()),
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
