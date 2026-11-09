"""Small Russian desktop control panel for the NIRS Basilisk research project.

Requires the repository and its Python 3.13 .venv. Does not require an IDE,
admin rights, cloud server, or shell commands during normal use.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk

from nirs_satellite.launcher_core import (
    ROOT, PROFILES, PROFILE_PHYSICAL, PROFILE_RESEARCH, PROFILE_TEST,
    build_plan, simulator_python,
)


def reveal(path: Path) -> None:
    """Open a result or configuration using the host OS."""
    if os.name == "nt":
        os.startfile(str(path))  # Windows file association.
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])


class NirsWindow:
    def __init__(self, window: tk.Tk):
        self.window = window
        window.title("НИРС — модель космического аппарата")
        window.geometry("900x690")
        window.minsize(740, 550)
        self.active = False
        self.process: subprocess.Popen | None = None
        self.last_plan = None
        self.messages: queue.Queue[tuple[str, object]] = queue.Queue()
        self.profile = tk.StringVar(value=PROFILES[PROFILE_PHYSICAL])
        self.hours = tk.StringVar(value="0.2")
        self.run_name = tk.StringVar()
        self.vizard = tk.BooleanVar(value=True)
        self.state = tk.StringVar(value="Готово к запуску")
        self.current_python = simulator_python()
        self._build()
        self._new_name()
        self._update_profile()
        window.protocol("WM_DELETE_WINDOW", self._close)
        self.window.after(100, self._poll)

    def _build(self):
        self.window.configure(padx=20, pady=14)
        title = ttk.Label(self.window, text="НИРС · Моделирование спутника",
                          font=("Segoe UI", 18, "bold"))
        title.pack(anchor="w", pady=(0, 5))
        ttk.Label(self.window, text=(
            "Физический аппарат — Basilisk 2.12.2. "
            "Все аппаратные характеристики пока условные."
        )).pack(anchor="w", pady=(0, 14))
        outer = ttk.Frame(self.window)
        outer.pack(fill="x")

        ttk.Label(outer, text="Режим").grid(row=0, column=0, sticky="w", pady=5)
        self.select = ttk.Combobox(outer, textvariable=self.profile,
                                   values=list(PROFILES.values()), state="readonly",
                                   width=72)
        self.select.grid(row=0, column=1, columnspan=3, sticky="ew", padx=10, pady=5)
        self.select.bind("<<ComboboxSelected>>", lambda _ev: self._update_profile())

        ttk.Label(outer, text="Длительность, ч").grid(row=1, column=0, sticky="w", pady=6)
        self.duration_entry = ttk.Entry(outer, textvariable=self.hours, width=12)
        self.duration_entry.grid(row=1, column=1, sticky="w", padx=10, pady=6)
        self.viz_check = ttk.Checkbutton(outer, text="Создать запись для Vizard",
                                         variable=self.vizard)
        self.viz_check.grid(row=1, column=2, columnspan=2, sticky="w", pady=6)

        ttk.Label(outer, text="Название запуска").grid(row=2, column=0, sticky="w", pady=6)
        self.name_entry = ttk.Entry(outer, textvariable=self.run_name, width=38)
        self.name_entry.grid(row=2, column=1, columnspan=2, sticky="ew", padx=10, pady=6)
        ttk.Button(outer, text="Новое имя", command=self._new_name).grid(
            row=2, column=3, sticky="ew", pady=6)
        outer.columnconfigure(1, weight=1)
        outer.columnconfigure(2, weight=1)

        actions = ttk.Frame(self.window)
        actions.pack(fill="x", pady=(12, 9))
        self.btn_start = ttk.Button(actions, text="▶ Запустить", command=self._start)
        self.btn_start.pack(side="left", padx=(0, 10))
        self.btn_stop = ttk.Button(actions, text="■ Остановить",
                                   command=self._stop, state="disabled")
        self.btn_stop.pack(side="left", padx=(0, 10))
        ttk.Button(actions, text="Открыть результаты",
                   command=self._open_results).pack(side="left", padx=(0, 10))
        ttk.Button(actions, text="Все исходные данные",
                   command=self._open_config).pack(side="left", padx=(0, 10))
        ttk.Button(actions, text="Папка Vizard",
                   command=self._open_vizard).pack(side="left")

        ttk.Label(self.window, textvariable=self.state,
                  font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(5, 8))
        self.log = scrolledtext.ScrolledText(
            self.window, wrap="word", height=15, font=("Consolas", 10))
        self.log.pack(fill="both", expand=True)
        self.log.configure(state="disabled")
        ttk.Label(self.window, text=(
            "Физический режим переключается между двумя целями без перезапуска Basilisk. "
            "Режим нескольких задач использует упрощённые ресурсные ограничения."
        ), wraplength=840).pack(anchor="w", pady=(12, 2))
        ttk.Label(self.window, text="Записанные результаты находятся в папке results/ проекта.",
                  foreground="#666666").pack(anchor="w")

    def _code(self):
        selected = self.profile.get()
        return next((code for code, label in PROFILES.items()
                     if label == selected), PROFILE_PHYSICAL)

    def _new_name(self):
        code = self._code()
        prefix = {"physical": "physical", "research": "research",
                  "tests": "tests"}[code]
        now = datetime.now().strftime("%Y%m%d_%H%M%S")
        base = prefix + "_" + now
        candidate = base
        index = 2
        while (ROOT / "results" / candidate).exists():
            candidate = f"{base}_{index}"
            index += 1
        self.run_name.set(candidate)

    def _update_profile(self):
        code = self._code()
        self.hours.set("0.2" if code == PROFILE_PHYSICAL else "4" if
                       code == PROFILE_RESEARCH else "0")
        self.duration_entry.configure(state=("disabled" if code == PROFILE_TEST
                                             else "normal"))
        self.name_entry.configure(state=("disabled" if code == PROFILE_TEST
                                         else "normal"))
        self.viz_check.configure(state=("normal" if code == PROFILE_PHYSICAL
                                        else "disabled"))
        self._new_name()

    def _append(self, value: str):
        self.log.configure(state="normal")
        self.log.insert("end", value.rstrip("\n") + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _start(self):
        if self.active:
            return
        if not self.current_python.is_file():
            messagebox.showerror(
                "Не установлены зависимости",
                "Не найдено виртуальное окружение .venv.\n"
                "Запустите двойным щелчком SETUP_NIRS.cmd в папке проекта.")
            return
        try:
            code = self._code()
            plan = build_plan(profile=code, name=self.run_name.get(),
                              hours=float(self.hours.get().replace(",", ".")),
                              python_executable=self.current_python,
                              record_vizard=self.vizard.get(), root=ROOT)
        except (ValueError, TypeError) as exc:
            messagebox.showerror("Неверные параметры", str(exc))
            return
        if plan.result_dir is not None and plan.result_dir.exists():
            messagebox.showerror("Такой запуск уже существует",
                                 "Измените имя, чтобы не затереть результаты предыдущего запуска.")
            return
        self.last_plan = plan
        self.active = True
        self.btn_start.configure(state="disabled")
        self.btn_stop.configure(state="normal")
        self.state.set("Расчёт выполняется…")
        self._append("")
        self._append("=" * 60)
        self._append("Запуск: " + self.profile.get())
        self._append("Данные: " + (str(plan.result_dir) if plan.result_dir else "только тесты"))
        thread = threading.Thread(target=self._work, args=(plan,), daemon=True)
        thread.start()

    def _work(self, plan):
        try:
            kwargs = dict(
                cwd=str(ROOT), stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace", bufsize=1,
            )
            if os.name == "nt":
                # Hide the child console while streaming its output into GUI.
                kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
            else:
                kwargs["start_new_session"] = True
            self.process = subprocess.Popen(list(plan.argv), **kwargs)
            self.messages.put(("start", self.process.pid))
            assert self.process.stdout is not None
            for line in self.process.stdout:
                self.messages.put(("log", line))
            status = self.process.wait()
            self.messages.put(("done", status))
        except Exception as exc:
            self.messages.put(("error", repr(exc)))
        finally:
            self.process = None

    def _poll(self):
        try:
            while True:
                kind, payload = self.messages.get_nowait()
                if kind == "log":
                    self._append(str(payload))
                elif kind == "start":
                    self.state.set(f"Расчёт выполняется · PID {payload}")
                elif kind == "done":
                    self.active = False
                    self.btn_start.configure(state="normal")
                    self.btn_stop.configure(state="disabled")
                    self.state.set("Завершено успешно" if payload == 0 else
                                   f"Завершено с ошибкой (код {payload})")
                    self._append("Код завершения: " + str(payload))
                elif kind == "error":
                    self.active = False
                    self.btn_start.configure(state="normal")
                    self.btn_stop.configure(state="disabled")
                    self.state.set("Ошибка запуска")
                    self._append("Ошибка: " + str(payload))
        except queue.Empty:
            pass
        if self.window.winfo_exists():
            self.window.after(100, self._poll)

    def _stop(self):
        process = self.process
        if process is None or process.poll() is not None:
            return
        self.state.set("Остановка расчёта…")
        if os.name == "nt":
            # The research CLI launches a subprocess; terminate the owned tree.
            subprocess.Popen(
                ["taskkill", "/T", "/F", "/PID", str(process.pid)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW)
        else:
            import signal
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass

    def _open_results(self):
        path = self.last_plan.result_dir if (
            self.last_plan is not None and self.last_plan.result_dir) else ROOT / "results"
        if not path.exists():
            path = ROOT / "results"
        if not path.exists():
            messagebox.showinfo("Результаты", "Расчёты ещё не создавали результатов.")
        else:
            reveal(path)

    def _open_config(self):
        from nirs_satellite.input_editor import open_input_editor
        open_input_editor(self.window)

    def _open_vizard(self):
        base = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "NIRS_Satellite" / "viz"
        if base.exists():
            reveal(base)
        else:
            messagebox.showinfo("Vizard", "Сначала выполните физическую модель с включённой записью.")

    def _close(self):
        if self.active:
            if not messagebox.askyesno("Закрыть программу?",
                                       "Остановить расчёт и закрыть окно?"):
                return
            self._stop()
        self.window.destroy()


def main():
    root = tk.Tk()
    try:
        ttk.Style().theme_use("clam")
    except tk.TclError:
        pass
    NirsWindow(root)
    root.mainloop()


if __name__ == "__main__":
    main()
