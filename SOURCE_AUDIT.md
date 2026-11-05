# Аудит исходного GitVerse — 04.11.2026

Источник: https://gitverse.ru/zayn/python_for_bmstu_students
Каталог: https://gitverse.ru/zayn/python_for_bmstu_students/content/main/satellite_model

## Что действительно проверено

Доступные страницы в браузере показывают каталог `satellite_model/src`:
`adcs.py`, `ballistic.py`, `cstpu.py`, `helpers.py`, `magnetic.py`,
`mission_parameters.py`, `mission_simulation.py`, `power_budget.py`,
`sun.py`, `visualization.py`.

Папка `satellite_model/tests` содержит 6 тестовых файлов: `test_adcs.py`,
`test_ballistic.py`, `test_cstpu.py`, `test_magnetic.py`,
`test_mission_simulation.py`, `test_power_budget.py`.

Страница `pyproject.toml` в корне указывает `requires-python = ">=3.12"`
и зависимости, включая NumPy, SciPy, sgp4, astropy, poliastro и др.
В `mission_simulation.py` есть `solve_ivp`, состояния ориентации,
движения/двигательной установки и энергетики; штатного планировщика
целевых продуктов и доставки в просмотренном коде не обнаружено.
`ballistic.py` рассчитывает орбитальные состояния и использует SGP4.

## Чего НЕ было

- Нет полного клона Git-репозитория в рабочем окружении.
- Не проверены все исходники построчно.
- Оригинальные тесты не запускались.
- Не подтверждены корректность физических моделей или наличие лицензии,
  разрешающей повторное использование кода.

Попытка обращения к оригиналу посредством `git ls-remote` завершилась:
`Could not resolve host: gitverse.ru`.

## Дальнейшая проверка

При доступе к архиву/клону: установить требуемый Python в отдельном
окружении, зафиксировать commit id, запустить оригинальные тесты,
сравнить орбитальные расчёты с независимым эталоном, проверить лицензию.
До этого интеграцию отложить. Наша v0.1 работает без исходного GitVerse.
