# Mission 01 — единый информационный цикл одного КА

**Статус:** экспериментальная ветка `feature/mission-01-datachain` (PR #16). Модель синтетическая, без реальной камеры и без энергетики.

## Смысл этапа

Для одного физически вращающегося в Basilisk КА связаны:

```text
Orbit 01 + Ground 01 (orbit, rotating Earth, target)
  → ADCS 01 (truth-like simpleNav, locationPointing, MRP controller,
             ideal external torque and actual body rotation)
  → real AttGuidMsg & AccessMsg → simpleInstrumentController
  → simpleInstrument (one SYNTHETIC data item, 1 MB)
  → partitionedStorageUnit (4 MB bounded memory, science partition)
  → spaceToGroundTransmitter (fixed-rate negative bits/s, packets)
  ← independent groundLocation for synthetic ground station
  → recorded downlink bits; NO real receiver/ACK/bit errors
```

Снимок — **только один условный информационный продукт**, не растровое изображение. Положительный доступ к цели без подходящей ориентации **не должен** разрешать генерацию данных. Геометрия станции рассчитывается отдельно от геометрии цели.

## Windows: запуск из корня репозитория

Первый запуск — план без симуляции:

```powershell
.\.venv\Scripts\python.exe -m experiments.mission_01.run_mission --plan-only
```

Стандартная проверка: **12 модельных минут**, физический шаг 0,5 с, **160 кбит/с**, 10 КБ пакет:

```powershell
.\.venv\Scripts\python.exe -m experiments.mission_01.run_mission --viz-mode file --viz-step-s 10
```

После расчёта:

```powershell
Invoke-Item .\results\mission_01\mission_dataflow.png
Invoke-Item .\results\mission_01\adcs_pointing.png
notepad .\results\mission_01\mission_summary.json
notepad .\results\mission_01\RESULTS_EXPLAINED.md
explorer "$env:LOCALAPPDATA\NIRS_Satellite\viz"
```

В Vizard открой `mission_01.bin`. Визуально предусмотрены маркеры цели (пурпурный) и наземной станции (зелёный), а также прибор, радиоустройство и панель бортовой памяти, привязанные к сообщениям Basilisk. **Точное наличие и вид панели требует пользовательской проверки в Vizard**, CI подтверждает только формирование файла.

Контрольный прогон с той же орбитой, целью и пакетом, но **10 кбит/с**:

```powershell
.\.venv\Scripts\python.exe -m experiments.mission_01.run_mission --mission-profile slow_link --output-name mission_01_slow
Invoke-Item .\results\mission_01_slow\mission_dataflow.png
```

Оба профиля — самостоятельные исходные JSON, их содержимое и SHA-256 записываются в `run_manifest.json`. Программа **не подменяет** исходный файл на лету.

## Синтетические исходные параметры

| Величина | Номинально | Замедленный канал | Происхождение |
|---|---:|---:|---|
| Орбита | круговая, 500 км, 45° | та же | `orbit_01/config.json` |
| Наземная цель | 14°N, 43°E, доступ от 10° | та же | `ground_01/config.json` |
| Отдельная станция | 12°N, 45°E, доступ от 10° | та же | `mission_01/config*.json` |
| Объём условного продукта | 1 000 000 байт | тот же | `capture.product_bytes` |
| Максимум продуктов | 1 на прогон | 1 | `capture.maximum_products_per_run` |
| Оценка допуска наведения | около 5° полная угловая ошибка через норму MRP | то же | `capture.maximum_attitude_mrp_error` |
| Допуск скорости наведения | 0,01 рад/с | тот же | `capture.maximum_rate_error_rad_s` |
| Память | 4 000 000 байт | та же | `storage.capacity_bytes` |
| Скорость модели передачи | **160 000 бит/с** | **10 000 бит/с** | `downlink.rate_bits_per_s` |
| Минимальный передаваемый пакет | 10 000 байт | тот же | `downlink.packet_bytes` |
| Шаг интегрирования | 0,5 с | тот же | `--step-s`/ADCS 01 |

Все значения — учебно-исследовательские **синтетические**, не измерены на конкретной аппаратуре. Номинальная скорость 160 кбит/с не подтверждена радиобюджетом.

## На что смотреть в результатах

- `mission_summary.json` — время однократного формирования, фактическая ошибка ориентации в этот момент, переданные и оставшиеся биты, доля передачи, время окончания, окно станции и баланс.
- `mission_states.csv` — каждому моменту соответствует событие съёмки, генерация, состояние памяти, передача, накопленная доля данных и отдельные флаги доступа.
- `mission_dataflow.png` — график заполнения памяти и переданных данных с отметкой окна станции.
- `adcs_summary.json` и `adcs_pointing.png` — соответствие фактической ориентации и порога.
- `access.csv` — ориентация и радиоканал **не должны изменять траекторию** в этой упрощённой модели.
- `run_manifest.json` — точные исходные JSON, SHA-256, версии ПО, параметры запуска.
- `RESULTS_EXPLAINED.md` — пояснения по значению всех основных показателей на русском.

Для битового баланса проверяется:

```text
сгенерировано ≈ передано через модель + осталось в памяти
```

Ошибки округления конечной точности не объявляются ошибками физики. **Передано** — значит биты вычтены из модели бортового накопителя при доступной станции; настоящее подтверждение наземного приёмника не моделируется.

## Что сравниваем научно

При идентичных параметрах орбиты, вращения Земли, наведения, цели, станции, объёма продукта и размере пакета:

1. **160 кбит/с:** полная передача одного синтетического продукта за доступный сеанс.
2. **10 кбит/с:** часть данных осталась в памяти после окончания окна станции, так как вся передача не успела завершиться.

Это проверка зависимости завершения информационного цикла от пропускной способности канала. Исследовать зависимость можно **без** притворства, что известны энергетика радиолинии, полоса, модуляция, затухание и качество приёма.

**Отдельный нюанс Basilisk:** `spaceToGroundTransmitter` не начинает новый пакет, если данных меньше размера пакета. Ранний прототип с пакетом 50 КБ остановился, оставив около 44 КБ в памяти, несмотря на длительное окно связи. Причина — пакетизация, не недостаток времени. Поэтому в обоих сравниваемых профилях пакет установлен **10 КБ**, и сравнение меняет только скорость канала.

## Что ещё НЕ завершено

- Настоящая модель камеры: поле зрения, съёмочная полоса, оптические параметры, экспозиция и объём файла.
- Реалистичная ADCS: ограничение крутящего момента/момента инерции маховиков, накопление кинетического момента, датчики, погрешности и ограничения угловых скоростей.
- Энергетика и затмения, тепловые и вычислительные ресурсы.
- Радиобюджет, ошибки приёма, подтверждение доставки на станции.
- Планирование нескольких снимков, очереди заданий, выбор объектов, ограничения ресурсов.
- Привязка к UTC, J2/атмосфера, геодезия/точная картография, облачность.
- Контрольная пользовательская проверка Vizard и локального вывода Mission 01.

**Группировка не является следующим этапом**: сначала одна полностью согласованная модель КА с измеримыми критериями выполнения заданий.

## Основные использованные источники Basilisk 2.12.2

- [Официальный пример GroundLocationImaging](https://github.com/AVSLab/basilisk/blob/v2.12.2/examples/scenarioGroundLocationImaging.py)
- [Документация SimpleInstrumentController](https://github.com/AVSLab/basilisk/blob/v2.12.2/src/fswAlgorithms/sensorInterfaces/simpleInstrumentController/simpleInstrumentController.rst)
- [Документация PartitionedStorageUnit](https://github.com/AVSLab/basilisk/blob/v2.12.2/src/simulation/onboardDataHandling/storageUnit/partitionedStorageUnit.rst)
- [Документация SpaceToGroundTransmitter](https://github.com/AVSLab/basilisk/blob/v2.12.2/src/simulation/onboardDataHandling/spaceToGroundTransmitter/spaceToGroundTransmitter.rst)
