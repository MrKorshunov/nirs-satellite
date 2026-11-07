# Первый связанный цикл КА: Ground + ADCS + Payload 02 + Storage 01

**Статус:** 07.11.2026, экспериментальные ветки PR #17 и #21. Сценарий полностью **синтетический**; все характеристики камеры, инерции и памяти задаются учебными входными файлами, а не паспортом настоящего спутника.

## Что стало единым моделированием

```text
Basilisk spacecraft (трансляция + физическое вращение)
       ├── planetEphemeris + groundLocation → геометрический доступ
       └── simpleNav → locationPointing → mrpFeedback → extForceTorque
                           |
                           v
                 actual attitude guidance + rate
                           |
                           v
            simpleInstrumentController (access AND MRP AND rate)
                           |
                           v
               simpleInstrument (one synthetic 1 MB product)
                           |
                           v
             partitionedStorageUnit (10 MB finite onboard buffer)
```

**Пока НЕТ:** реального оптического изображения, требований к разрешению, реальных маховиков и датчиков, аккумулятора, радиоканала, наземной станции для приёма и повторных задач. Цифровая модель КА ещё **не завершена**.

## Windows: команды

Открой GitHub Desktop, переключись на `feature/storage-01-onboard-buffer`, нажми Fetch origin/Pull origin. Все команды запускать из корня репозитория.

Проверить исходные данные без моделирования:
```powershell
.\.venv\Scripts\python.exe -m experiments.storage_01.run_storage --plan-only
```

Провести расчёт (12 минут модельного времени, шаг 0,5 с):
```powershell
.\.venv\Scripts\python.exe -m experiments.storage_01.run_storage
```

При необходимости записать Vizard:
```powershell
.\.venv\Scripts\python.exe -m experiments.storage_01.run_storage --viz-mode file --viz-step-s 10
explorer "$env:LOCALAPPDATA\NIRS_Satellite\viz"
```
Открой `ground_storage01.bin`. Внешне модель аналогична ADCS 01 — бортовая память не рисуется как отдельная деталь. Её **изменение следует смотреть в числовом отчёте**.

## Где результаты

| Каталог / файл | Что измеряется |
|---|---|
| `results/ground_storage01/adcs_summary.json` | Динамика ориентации и готовность |
| `results/ground_storage01/adcs_pointing.png` | Фактическая ошибка оси относительно цели |
| `results/ground_storage01/summary.json` | Орбита, наземная видимость, ADCS, полезная нагрузка и память |
| `results/ground_storage01/run_manifest.json` | Точные входные JSON и исходные SHA-256; версия Basilisk |
| `results/ground_storage01/RESULTS_EXPLAINED.md` | Объяснение чисел, единицы, ограничения |
| `results/payload_02_ground_storage01/events.csv` | Момент и параметры **условного формирования данных** с фактической ошибкой оси |
| `results/storage_01_ground_storage01/storage.csv` | Заполнение памяти во времени (бит/байт) |
| `results/storage_01_ground_storage01/summary.json` | Сгенерировано, в памяти, доставлено, потеряно, свободная ёмкость |

В учебном сценарии:
- Исходная ошибка наведения ≈ 89,6928°; по пользовательским графикам ошибка быстро уменьшается, контур ADCS в Vizard работает.
- В момент `t = 82.5 с` контроллер **разрешил** сформировать один продукт, так как цель видима и фактическая ошибка оси ≈ `0.002086°`, ошибка угловой скорости ≈ `4.756×10⁻⁶ рад/с`.
- Из `simpleInstrument` выходит поток `8 000 000 бит`, что соответствует **1 000 000 байт**. Это не файл изображения.
- `partitionedStorageUnit` имеет условную вместимость `80 000 000 бит` (10 000 000 байт). Итог: `8 000 000 бит` лежит на борту, `72 000 000 бит` свободно, **0 бит передано**.
- Контроль: `сгенерировано = накоплено + передано + потеряно`; здесь `8 000 000 = 8 000 000 + 0 + 0`. В будущем при радиопередаче формула остаётся, а накопление уменьшается.

Числа синтетические, исходники конфигурации расположены в `experiments/orbit_01/config.json`, `experiments/ground_01/config.json`, `experiments/adcs_01/config.json`, `experiments/payload_01/config.json`, `experiments/payload_02/config.json`, `experiments/storage_01/config.json`.

## Проверки

Оба этапа проверены автоматическими тестами на Linux и Windows с установленным Basilisk 2.12.2. Тесты включают:
1. Восстановление истинного угла между физической осью прибора и целью независимой математической формулой, а не доверие только бортовой команде.
2. Отказ при ложном флаге видимости, нарушении допусков угла/MRP/скорости и несогласованности команд и скоростей потока.
3. Положительное и отрицательные испытания сохранения бит: вместимость, потери, неожиданный расход.
4. Сохранение исходных конфигураций, контрольных сумм и реальных значений результата.

**Критические ограничения:** нет ограниченной физической модели исполнительных органов, нереалистично точная навигация; камера не имеет оптической модели; запись потока данных — дискретное событие; память не учитывает файловую систему, ECC или износ; Земля вращается относительно синтетической эпохи без UTC.

## Что дальше для завершения одного спутника

1. **Ground Station + Radio 01**: вторая географическая точка, окна радиосвязи и реальная передача бит из накопителя через Basilisk `spaceToGroundTransmitter`; независимый баланс `сгенерировано = накоплено + доставлено + потеряно`.
2. **Power 01**: Солнце/затенение, генерация, аккумулятор и потребители, количественные запреты операций при недостатке энергии.
3. **Ограничения ориентации**: физические реакционные маховики, ограничение момента, насыщение, шумы датчиков; измеряем реальные времена наведения.
4. **Камера и задания**: поле зрения, разрешение, объём, длительность, многократные наблюдения, затраты памяти/энергии.
5. **Mission 01**: сценарий от запуска до получения данных и KPI, несколько независимых вариантов/тестов. Только затем — группировка.

## Источники

- [Basilisk 2.12.2 — scenarioGroundLocationImaging](https://github.com/AVSLab/basilisk/blob/v2.12.2/examples/scenarioGroundLocationImaging.py)
- [Basilisk 2.12.2 — partitionedStorageUnit](https://github.com/AVSLab/basilisk/blob/v2.12.2/src/simulation/onboardDataHandling/storageUnit/partitionedStorageUnit.rst)
- [Basilisk 2.12.2 — simpleInstrumentController](https://github.com/AVSLab/basilisk/blob/v2.12.2/src/fswAlgorithms/sensorInterfaces/simpleInstrumentController/simpleInstrumentController.rst)

Работа выполнена в виде экспериментальных Pull Request, `main` не менялся. Сливать ветки последовательно после подтверждения пользовательского Windows-прогона.
