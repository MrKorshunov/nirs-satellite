"""Create a self-contained, source-backed HTML explanation of one synthetic scenario.

Usage (Windows): py explain.py
No external dependencies. This only visualizes the v0.1 simulation; it does not
compute or optimize orbital windows, cloud cover, or real link budgets.
"""
from __future__ import annotations

from html import escape
from pathlib import Path
import sys

from main import load_scenario
from nirs_satellite.engine import simulate


def fmt_mb(num: float) -> str:
    return f"{num / 1_000_000:,.2f}".replace(",", " ")


def fmt_min(seconds: float) -> str:
    return f"{seconds / 60:g}"


def table(headings: list[str], rows: list[list[str]]) -> str:
    headers = "".join(f"<th>{escape(str(x))}</th>" for x in headings)
    body = "".join("<tr>" + "".join(f"<td>{escape(str(x))}</td>" for x in row) + "</tr>" for row in rows)
    return f"<table><thead><tr>{headers}</tr></thead><tbody>{body}</tbody></table>"


def rect(x: float, y: float, width: float, color: str, label: str) -> str:
    return f'<rect x="{x:.2f}" y="{y}" width="{max(width, 1):.2f}" height="22" rx="4" fill="{color}"><title>{escape(label)}</title></rect>'


def timeline(scenario, result, horizon_s: float) -> str:
    width, left, right = 1000, 132, 28
    w = width - left - right
    scale = lambda t: left + (t / horizon_s) * w
    bits = [f'<svg viewBox="0 0 {width} 216" role="img" aria-label="Временная диаграмма операций">']
    for minute in range(0, int(horizon_s / 60) + 1, 30):
        x = scale(minute * 60)
        bits.append(f'<line x1="{x:.2f}" y1="30" x2="{x:.2f}" y2="187" stroke="#dae1e9" stroke-dasharray="3 4"/>')
        bits.append(f'<text x="{x:.2f}" y="22" text-anchor="middle" font-size="12" fill="#65758b">{minute} мин</text>')
    for y, title in [(55, 'Съёмка'), (102, 'Сеансы связи'), (149, 'Передача')]:
        bits.append(f'<text x="6" y="{y + 15}" font-size="14" fill="#26364a">{escape(title)}</text>')
        bits.append(f'<line x1="{left}" y1="{y + 27}" x2="{width - right}" y2="{y + 27}" stroke="#e2e8f0"/>')
    for t in scenario.tasks:
        bits.append(rect(scale(t.capture_start_s), 55, scale(t.capture_end_s) - scale(t.capture_start_s), '#2f9b6d', f'{t.id}: съёмка {fmt_min(t.capture_start_s)}–{fmt_min(t.capture_end_s)} мин'))
    for c in scenario.contacts:
        bits.append(rect(scale(c.start_s), 102, scale(c.end_s) - scale(c.start_s), '#9ec5ed', f'Связь {fmt_min(c.start_s)}–{fmt_min(c.end_s)} мин'))
    colors = {'A_fields': '#3478c6', 'B_water': '#9b59b6', 'C_forest': '#d28d2d'}
    for e in result.events:
        if e['type'] == 'downlink':
            bits.append(rect(scale(e['time_s']), 149, scale(e['end_s']) - scale(e['time_s']), colors.get(e['task'], '#4b5563'), f"{e['task']}: передано {fmt_mb(e['bytes'])} МБ; {fmt_min(e['time_s'])}–{fmt_min(e['end_s'])} мин"))
    bits.append('<text x="132" y="208" font-size="12" fill="#65758b">Наведите курсор на полосу для подробностей. Все времена отсчитываются от t=0.</text>')
    return ''.join(bits) + '</svg>'


def event_description(event: dict) -> str:
    labels = {'capture_finished': 'Снимок записан', 'capture_rejected': 'Снимок отклонён (нехватка памяти)',
              'downlink': 'Передача', 'delivered_on_time': 'Доставлено в срок', 'delivered_late': 'Доставлено с опозданием'}
    return labels.get(event['type'], event['type'])


def report(source: Path, target: Path) -> None:
    scenario = load_scenario(source)
    results = {policy: simulate(scenario, policy) for policy in ('fifo', 'edf')}
    horizon = max([t.deadline_s for t in scenario.tasks] + [c.end_s for c in scenario.contacts] + [60])
    task_rows = [[t.id, f'{fmt_min(t.capture_start_s)}–{fmt_min(t.capture_end_s)}', fmt_mb(t.volume_bytes), fmt_min(t.deadline_s), str(t.priority)] for t in scenario.tasks]
    contact_rows = [[f'{fmt_min(c.start_s)}–{fmt_min(c.end_s)}', f'{fmt_mb(c.rate_bytes_per_s)}', f'{8 * c.rate_bytes_per_s / 1_000_000:g}', fmt_mb((c.end_s-c.start_s)*c.rate_bytes_per_s)] for c in scenario.contacts]
    sections = []
    for policy, result in results.items():
        s = result.summary()
        rows = []
        for e in sorted(result.events, key=lambda q: (q['time_s'], q['type'])):
            interval = fmt_min(e['time_s'])
            if 'end_s' in e:
                interval += '–' + fmt_min(e['end_s'])
            rows.append([interval, e['task'], event_description(e), fmt_mb(e['bytes']), e.get('reason', '')])
        sections.append(f'''
        <section><h2>{policy.upper()} — K = {s['k_weighted_on_time']:.3f}</h2>
        <p>Доставлены в срок: <strong>{escape(', '.join(s['completed_on_time']) or 'нет')}</strong>.
        Отклонены из-за памяти: <strong>{escape(', '.join(s['rejected_memory']) or 'нет')}</strong>.
        Доставлены поздно: <strong>{escape(', '.join(s['delivered_late']) or 'нет')}</strong>.</p>
        {timeline(scenario, result, horizon)}
        <h3>Журнал операций</h3>{table(['Минута', 'Задание', 'Событие', 'МБ', 'Причина'], rows)}
        <details><summary>Состояние памяти по временным точкам</summary>
        {table(['Минута', 'Занято памяти, МБ'], [[fmt_min(p['time_s']), fmt_mb(p['memory_bytes'])] for p in result.memory_trace])}
        </details></section>''')
    try:
        source_label = str(source.resolve().relative_to(Path(__file__).resolve().parent))
    except ValueError:
        source_label = str(source)
    html = f'''<!DOCTYPE html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>НИРС — разбор контрольного моделирования v0.1.1</title>
<style>
body{{font-family:Segoe UI,Arial,sans-serif;max-width:1120px;margin:30px auto;padding:0 18px;color:#203047;line-height:1.55;background:#f8fafc}}
h1{{font-size:28px}}h2{{margin-top:0}}h3{{margin-top:24px}}section,.note{{background:white;padding:24px;border:1px solid #e2e8f0;border-radius:14px;margin:18px 0;box-shadow:0 3px 14px #10203009}}
.warning{{border-left:5px solid #bf873a}}table{{width:100%;border-collapse:collapse;margin:12px 0 20px}}th,td{{padding:9px 12px;border-bottom:1px solid #e7edf4;text-align:left;font-size:14px}}th{{background:#f2f6fa}}svg{{width:100%;height:auto;display:block;margin:16px 0}}code{{background:#f1f4f9;padding:2px 5px;border-radius:4px}}details{{margin-top:12px}}summary{{cursor:pointer;font-weight:600}}@media(max-width:670px){{.note,section{{padding:14px}}table{{display:block;overflow-x:auto}}}}
</style></head><body>
<h1>НИРС · Почему получились именно такие результаты?</h1>
<div class="note warning"><strong>Статус данных: синтетический контрольный сценарий.</strong>
Значения взяты из <code>{escape(source_label)}</code>, а не из паспортов реального спутника.
Не рассчитываются орбита, прогноз облачности, энергетика или физическая радиолиния.
Программа моделирует заранее назначенные съёмки и выбирает только порядок передачи данных.</div>
<section><h2>1. Что подали на вход</h2><p>Бортовая память: <strong>{fmt_mb(scenario.memory_capacity_bytes)} МБ</strong> (1 МБ = 1 000 000 байт).</p>
<h3>Задания</h3>{table(['ID', 'Съёмка, мин', 'Снимок, МБ', 'Срок, мин', 'Вес'], task_rows)}
<h3>Сеансы связи</h3>{table(['Интервал, мин', 'Скорость, МБ/с', 'Скорость, Мбит/с', 'Максимум за окно, МБ'], contact_rows)}
<p>Времена задаются в секундах от начала моделирования. После завершения съёмки продукт занимает полный объём памяти до конца передачи.</p></section>
<section><h2>2. Как работает модель</h2><p>По событиям окончания съёмки снимки помещаются в память, если хватает места. Во время сеанса связи передаётся один выбранный продукт.
<strong>FIFO</strong> — сначала самый ранний по времени записи; <strong>EDF</strong> — сначала продукт с ближайшим сроком доставки.
Продукт засчитывается, только когда полностью передан не позже срока.</p>
<p>Метрика: <code>K = сумма весов доставленных в срок заданий / сумма весов всех заданий</code>.</p>
<p>Ограничение: даже частично переданный продукт в этой версии продолжает занимать полный объём памяти; съёмка и передача не совмещаются.</p></section>
{''.join(sections)}
<section><h2>3. Что означает результат</h2><p>На этом конкретном наборе искусственных данных EDF выполняет больше заданий в срок, чем FIFO.
Это <strong>не</strong> доказательство превосходства метода при других сценариях или для реального КА.</p>
<p>Для физической проверки позднее потребуются паспортные параметры полезной нагрузки, реальная схема памяти и радиоканала, рассчитанные окна доступа и независимые тесты.</p></section>
</body></html>'''
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(html, encoding='utf-8')
    print(f'Объясняющий отчёт создан: {target.resolve()}')


if __name__ == '__main__':
    root = Path(__file__).resolve().parent
    source = Path(sys.argv[1]) if len(sys.argv) > 1 else root / 'scenarios' / 'demo.json'
    target = Path(sys.argv[2]) if len(sys.argv) > 2 else root / 'results' / 'report.html'
    report(source, target)
