# Power 01 — физические вычислительные модули Basilisk

Вместо приближённого бюджета Mission 02 отдельная диагностическая подсистема
содержит `eclipse.Eclipse`, `simpleSolarPanel.SimpleSolarPanel`,
`simplePowerSink.SimplePowerSink`, `simpleBattery.SimpleBattery`.

## Windows: запуск из корня

```powershell
.\.venv\Scripts\python.exe -m experiments.ground_01.run_ground --power --duration-hours 0.3 --step-s 10 --output-name power01_local
```

Подключение к Mission 01 как **телеметрии** (не автоматической блокировки):

```powershell
.\.venv\Scripts\python.exe -m experiments.mission_01.run_mission --power --output-name mission01_power_demo
```

Результаты `power_summary.json`, `power_states.csv`,
`power_states.png`: панель, затмение, уровень батареи, шина.

## Граница применимости

Расчёт освещения, положения панели и интеграции энергии производится
реальными штатными модулями Basilisk. Однако Солнце векторно
фиксировано в условной инерциальной системе, без действительного UTC.
Габариты/КПД/ёмкость — **синтетические**.
Потребитель камеры может следовать сообщению её включения, но радио
не подключено к переключению мощности при реальных пакетах: его
энергетическая нагрузка отключена до отдельной интеграции.

**Низкий заряд не отключает прибор.** Воспроизведение Mission 02 по этой
энергии ещё не выполнено. Поэтому данный эксперимент — физический
эталон сравнительных профилей освещённости и заряда, а не валидированное
управление питанием реального аппарата.

Официальный пример:
https://avslab.github.io/basilisk/examples/scenarioPowerDemo.html
