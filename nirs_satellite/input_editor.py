"""Human-editable JSON input editor for all active satellite configurations.

Only predefined inputs/ paths are writable. Save performs a basic structural
check and an automatic backup; each individual model validates its numerical
constraints during simulation. The editor does not claim full schema validation.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import tempfile

from nirs_satellite.input_paths import FILES, input_path


def validate_json_text(text: str) -> dict:
    obj = json.loads(text)
    if not isinstance(obj, dict):
        raise ValueError("Ожидается JSON-объект, а не список или число.")
    if not isinstance(obj.get("scenario_id"), str) or not obj["scenario_id"]:
        raise ValueError("Не указано непустое поле scenario_id.")
    if not str(obj.get("provenance", "")).startswith("SYNTHETIC"):
        raise ValueError("Поле provenance должно сохранять пометку SYNTHETIC.")
    return obj


def save_input(name: str, text: str) -> Path:
    """Store UTF-8 JSON with a backup and atomic overwrite in inputs/ only."""
    data = validate_json_text(text)
    destination = input_path(name)  # rejects arbitrary paths
    if not destination.exists():
        raise FileNotFoundError(f"Исходный файл не найден: {destination}")
    backup = destination.with_suffix(destination.suffix + ".bak")
    normalized = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    fd, temp_name = tempfile.mkstemp(
        prefix=".nirs_edited_", suffix=".json.tmp", dir=destination.parent
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(normalized)
            stream.flush()
            os.fsync(stream.fileno())
        shutil.copy2(destination, backup)
        os.replace(temp_name, destination)
    finally:
        if Path(temp_name).exists():
            Path(temp_name).unlink()
    return destination


def open_input_editor(parent):
    import tkinter as tk
    from tkinter import messagebox, scrolledtext, ttk

    dialog = tk.Toplevel(parent)
    dialog.title("НИРС — редактирование исходных данных")
    dialog.geometry("960x750")
    dialog.minsize(680, 520)
    dialog.transient(parent)
    dialog.configure(padx=14, pady=12)

    ttk.Label(dialog, text="Исходные данные спутника и экспериментов",
              font=("Segoe UI", 14, "bold")).pack(anchor="w", pady=(0, 5))
    ttk.Label(dialog, text=(
        "Выберите раздел. Все значения — условные. При сохранении создаётся "
        "резервная копия .bak. Модель проверит допустимость чисел при запуске."
    ), wraplength=850).pack(anchor="w", pady=(0, 12))

    names = list(FILES)
    labels = {f"{FILES[name][1]}  —  {FILES[name][0]}": name for name in names}
    selection = tk.StringVar(value=next(iter(labels)))
    selector = ttk.Combobox(dialog, textvariable=selection,
                            values=list(labels), state="readonly", width=95)
    selector.pack(fill="x", pady=(0, 6))

    path_text = tk.StringVar()
    ttk.Label(dialog, textvariable=path_text,
              foreground="#666666").pack(anchor="w", pady=(0, 8))
    editor = scrolledtext.ScrolledText(dialog, wrap="none", font=("Consolas", 10))
    editor.pack(fill="both", expand=True)
    status = tk.StringVar(value="")

    current_name = [None]
    original = [""]
    def get_text():
        return editor.get("1.0", "end-1c")

    def load_config():
        name = labels[selection.get()]
        path = input_path(name)
        text = path.read_text(encoding="utf-8")
        editor.delete("1.0", "end")
        editor.insert("1.0", text)
        current_name[0] = name
        original[0] = text
        path_text.set("Файл: " + str(path))
        status.set("Файл загружен.")

    def changed():
        return get_text() != original[0]

    def choose(_event=None):
        if changed() and not messagebox.askyesno(
            "Есть несохранённые изменения",
            "Переключиться на другой раздел без сохранения изменений?",
            parent=dialog,
        ):
            for title, code in labels.items():
                if code == current_name[0]:
                    selection.set(title)
                    break
            return
        load_config()

    def validate():
        try:
            validate_json_text(get_text())
        except (ValueError, json.JSONDecodeError) as exc:
            messagebox.showerror("Ошибка JSON", str(exc), parent=dialog)
            return False
        status.set("Формат JSON и обязательные поля проверены. Численные ограничения проверяются при запуске модели.")
        return True

    def save():
        if not validate():
            return
        if not messagebox.askyesno(
            "Сохранение параметров",
            "Сохранить параметры? Предыдущая версия будет помещена в файл .bak.",
            parent=dialog,
        ):
            return
        try:
            dest = save_input(current_name[0], get_text())
            original[0] = get_text()
            status.set("Сохранено: " + str(dest))
        except (OSError, ValueError, KeyError) as exc:
            messagebox.showerror("Ошибка сохранения", str(exc), parent=dialog)

    def close():
        if changed() and not messagebox.askyesno(
            "Несохранённые изменения",
            "Закрыть редактор без сохранения?",
            parent=dialog,
        ):
            return
        dialog.destroy()

    buttons = ttk.Frame(dialog)
    buttons.pack(fill="x", pady=(9, 3))
    ttk.Button(buttons, text="Проверить JSON", command=validate).pack(side="left", padx=(0, 8))
    ttk.Button(buttons, text="Сохранить с резервной копией",
               command=save).pack(side="left", padx=(0, 8))
    ttk.Button(buttons, text="Закрыть", command=close).pack(side="right")
    ttk.Label(dialog, textvariable=status, wraplength=850).pack(anchor="w")
    selector.bind("<<ComboboxSelected>>", choose)
    dialog.protocol("WM_DELETE_WINDOW", close)
    load_config()
    dialog.focus_set()
    return dialog
