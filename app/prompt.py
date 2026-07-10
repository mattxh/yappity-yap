"""Native input dialogs (Windows, via a PowerShell subprocess).

Avoids tkinter (single-thread/focus pitfalls) — runs as a subprocess that shows a
modal dialog and returns the typed text on stdout (UTF-8, so Chinese works).
"""
import logging
import subprocess

log = logging.getLogger(__name__)


def _q(value) -> str:
    return str(value).replace("'", "''")


def _run(ps: str) -> str:
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                             capture_output=True, timeout=300)
        return out.stdout.decode("utf-8", "replace").strip()
    except Exception:
        log.exception("input dialog failed")
        return ""


def ask_text(message: str, title: str = "Yappity Yapp", default: str = "") -> str:
    """Show a one-line input box and return the entered text ('' if cancelled)."""
    ps = (
        "Add-Type -AssemblyName Microsoft.VisualBasic; "
        "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; "
        f"[Microsoft.VisualBasic.Interaction]::InputBox('{_q(message)}', "
        f"'{_q(title)}', '{_q(default)}')"
    )
    return _run(ps)


# A clean, modern WinForms dialog with a multiline box (for adding several words).
# Laid out with a TableLayoutPanel so it stays correct on any display scaling.
_WORDS_DIALOG = r'''
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
try {
  $sig = '[DllImport("user32.dll")] public static extern bool SetProcessDPIAware();'
  $d = Add-Type -MemberDefinition $sig -Name DpiAware -Namespace Win32 -PassThru
  $d::SetProcessDPIAware() | Out-Null
} catch {}
[System.Windows.Forms.Application]::EnableVisualStyles()
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

function Pad($a,$b,$c,$d) { New-Object System.Windows.Forms.Padding($a,$b,$c,$d) }
$ink    = [System.Drawing.Color]::FromArgb(28,28,32)
$muted  = [System.Drawing.Color]::FromArgb(120,120,132)
$accent = [System.Drawing.Color]::FromArgb(79,70,229)
$accentHover = [System.Drawing.Color]::FromArgb(67,56,202)
$line   = [System.Drawing.Color]::FromArgb(214,214,220)

$form = New-Object System.Windows.Forms.Form
$form.Text = '__TITLE__'
$form.StartPosition = 'CenterScreen'
$form.FormBorderStyle = 'FixedDialog'
$form.MaximizeBox = $false
$form.MinimizeBox = $false
$form.AutoScaleMode = [System.Windows.Forms.AutoScaleMode]::Dpi
$form.ClientSize = New-Object System.Drawing.Size(480, 356)
$form.BackColor = [System.Drawing.Color]::White
$form.Font = New-Object System.Drawing.Font('Segoe UI', 10)
$form.TopMost = $true

$grid = New-Object System.Windows.Forms.TableLayoutPanel
$grid.Dock = 'Fill'
$grid.ColumnCount = 1
$grid.RowCount = 4
$grid.Padding = Pad 20 18 20 16
$grid.BackColor = [System.Drawing.Color]::White
[void]$grid.RowStyles.Add((New-Object System.Windows.Forms.RowStyle([System.Windows.Forms.SizeType]::AutoSize)))
[void]$grid.RowStyles.Add((New-Object System.Windows.Forms.RowStyle([System.Windows.Forms.SizeType]::AutoSize)))
[void]$grid.RowStyles.Add((New-Object System.Windows.Forms.RowStyle([System.Windows.Forms.SizeType]::Percent, 100)))
[void]$grid.RowStyles.Add((New-Object System.Windows.Forms.RowStyle([System.Windows.Forms.SizeType]::AutoSize)))
$form.Controls.Add($grid)

$heading = New-Object System.Windows.Forms.Label
$heading.Text = '__HEADING__'
$heading.Font = New-Object System.Drawing.Font('Segoe UI', 15, [System.Drawing.FontStyle]::Bold)
$heading.ForeColor = $ink
$heading.AutoSize = $true
$heading.Margin = Pad 0 0 0 2
$grid.Controls.Add($heading, 0, 0)

$hint = New-Object System.Windows.Forms.Label
$hint.Text = '__HINT__'
$hint.Font = New-Object System.Drawing.Font('Segoe UI', 9.75)
$hint.ForeColor = $muted
$hint.AutoSize = $true
$hint.MaximumSize = New-Object System.Drawing.Size(430, 0)
$hint.Margin = Pad 0 0 0 12
$grid.Controls.Add($hint, 0, 1)

$tb = New-Object System.Windows.Forms.TextBox
$tb.Multiline = $true
$tb.AcceptsReturn = $true
$tb.WordWrap = $false
$tb.ScrollBars = [System.Windows.Forms.ScrollBars]::Vertical
$tb.Font = New-Object System.Drawing.Font('Segoe UI', 12)
$tb.BorderStyle = [System.Windows.Forms.BorderStyle]::FixedSingle
$tb.ForeColor = $ink
$tb.Dock = 'Fill'
$tb.Margin = Pad 0 0 0 0
$grid.Controls.Add($tb, 0, 2)

$buttons = New-Object System.Windows.Forms.FlowLayoutPanel
$buttons.FlowDirection = 'RightToLeft'
$buttons.Dock = 'Fill'
$buttons.AutoSize = $true
$buttons.Margin = Pad 0 14 0 0

$ok = New-Object System.Windows.Forms.Button
$ok.Text = '__OK__'
$ok.DialogResult = [System.Windows.Forms.DialogResult]::OK
$ok.FlatStyle = [System.Windows.Forms.FlatStyle]::Flat
$ok.FlatAppearance.BorderSize = 0
$ok.FlatAppearance.MouseOverBackColor = $accentHover
$ok.BackColor = $accent
$ok.ForeColor = [System.Drawing.Color]::White
$ok.Font = New-Object System.Drawing.Font('Segoe UI Semibold', 10)
$ok.Size = New-Object System.Drawing.Size(118, 40)
$ok.Margin = Pad 8 0 0 0
$buttons.Controls.Add($ok)

$cancel = New-Object System.Windows.Forms.Button
$cancel.Text = '__CANCEL__'
$cancel.DialogResult = [System.Windows.Forms.DialogResult]::Cancel
$cancel.FlatStyle = [System.Windows.Forms.FlatStyle]::Flat
$cancel.FlatAppearance.BorderColor = $line
$cancel.FlatAppearance.MouseOverBackColor = [System.Drawing.Color]::FromArgb(244,244,246)
$cancel.BackColor = [System.Drawing.Color]::White
$cancel.ForeColor = [System.Drawing.Color]::FromArgb(60,60,68)
$cancel.Size = New-Object System.Drawing.Size(104, 40)
$buttons.Controls.Add($cancel)

$grid.Controls.Add($buttons, 0, 3)

$form.AcceptButton = $ok
$form.CancelButton = $cancel
$form.Add_Shown({ $form.Activate(); $tb.Focus() })

$result = $form.ShowDialog()
if ($result -eq [System.Windows.Forms.DialogResult]::OK) { [Console]::Out.Write($tb.Text) }
'''


_OPEN_FILE_DIALOG = r'''
Add-Type -AssemblyName System.Windows.Forms
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$dlg = New-Object System.Windows.Forms.OpenFileDialog
$dlg.Title = '__TITLE__'
$dlg.Filter = 'Text files (*.txt)|*.txt|All files (*.*)|*.*'
$dlg.Multiselect = $false
if ($dlg.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) {
    [Console]::Out.Write($dlg.FileName)
}
'''


def ask_open_file(title: str = "Yappity Yapp") -> str:
    """Show a Windows 'open file' picker and return the chosen path ('' if cancelled)."""
    return _run(_OPEN_FILE_DIALOG.replace("__TITLE__", _q(title)))


def ask_words(heading: str, hint: str, ok_label: str = "Add",
              cancel_label: str = "Cancel", title: str = "Yappity Yapp") -> str:
    """Show a modern multiline dialog and return the raw text the user entered
    ('' if cancelled). Caller splits it into individual words."""
    ps = (_WORDS_DIALOG
          .replace("__TITLE__", _q(title))
          .replace("__HEADING__", _q(heading))
          .replace("__HINT__", _q(hint))
          .replace("__OK__", _q(ok_label))
          .replace("__CANCEL__", _q(cancel_label)))
    return _run(ps)
