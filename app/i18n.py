"""EN / Traditional Chinese string tables for tray, overlay, notifications."""

STRINGS = {
    "en": {
        "app_name": "VoiceToText",
        "recording": "● Recording — Esc to cancel",
        "transcribing": "✍ Transcribing…",
        "ready": "Ready — hold or tap Win+Ctrl to dictate",
        "quit": "Quit",
        "language": "Language",
        "lang_auto": "Auto-detect",
        "lang_en": "English",
        "lang_zh": "中文 (Mandarin)",
        "ui_language": "UI language",
        "retry_last": "Retry last recording",
        "open_history": "Open history",
        "open_config": "Open config",
        "start_with_windows": "Start with Windows",
        "already_running": "VoiceToText is already running.",
        "err_no_key": "No API key set. Open config and add your key, then restart.",
        "err_mic": "Microphone error: {error}",
        "err_api": "Transcription failed: {error}\nAudio saved — use 'Retry last recording'.",
        "err_empty": "Nothing transcribed (no speech detected).",
        "auto_stopped": "Recording auto-stopped after {minutes} min and was transcribed.",
        "retry_none": "No saved recording to retry.",
        "done_notify": "Inserted {chars} characters.",
        "startup_on": "Will start with Windows.",
        "startup_off": "Removed from Windows startup.",
    },
    "zh-TW": {
        "app_name": "VoiceToText 語音輸入",
        "recording": "● 錄音中 — 按 Esc 取消",
        "transcribing": "✍ 轉錄中…",
        "ready": "就緒 — 按住或輕按 Win+Ctrl 開始聽寫",
        "quit": "結束",
        "language": "辨識語言",
        "lang_auto": "自動偵測",
        "lang_en": "英文",
        "lang_zh": "中文（國語）",
        "ui_language": "介面語言",
        "retry_last": "重試上次錄音",
        "open_history": "開啟歷史紀錄",
        "open_config": "開啟設定檔",
        "start_with_windows": "開機時自動啟動",
        "already_running": "VoiceToText 已在執行中。",
        "err_no_key": "尚未設定 API 金鑰。請開啟設定檔填入金鑰後重新啟動。",
        "err_mic": "麥克風錯誤：{error}",
        "err_api": "轉錄失敗：{error}\n音檔已保留 — 可用「重試上次錄音」。",
        "err_empty": "沒有辨識到語音內容。",
        "auto_stopped": "錄音已於 {minutes} 分鐘後自動停止並完成轉錄。",
        "retry_none": "沒有可重試的錄音。",
        "done_notify": "已輸入 {chars} 個字元。",
        "startup_on": "已設定開機自動啟動。",
        "startup_off": "已取消開機自動啟動。",
    },
}


def tr(key: str, ui_language: str, **fmt) -> str:
    table = STRINGS.get(ui_language) or STRINGS["en"]
    text = table.get(key) or STRINGS["en"].get(key) or key
    return text.format(**fmt) if fmt else text
