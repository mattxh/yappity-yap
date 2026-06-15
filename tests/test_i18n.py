from app import i18n


def test_translate_both_languages():
    assert i18n.tr("quit", "en") == "Quit"
    assert i18n.tr("quit", "zh-TW") == "結束"


def test_unknown_language_falls_back_to_english():
    assert i18n.tr("quit", "fr") == "Quit"


def test_missing_key_returns_key():
    assert i18n.tr("no_such_key_xyz", "en") == "no_such_key_xyz"


def test_string_tables_have_identical_keys():
    assert set(i18n.STRINGS["en"].keys()) == set(i18n.STRINGS["zh-TW"].keys())


def test_format_args():
    assert "3" in i18n.tr("auto_stopped", "en", minutes=3)
    assert "3" in i18n.tr("auto_stopped", "zh-TW", minutes=3)
