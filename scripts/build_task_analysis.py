#!/usr/bin/env python3
"""日報Markdownからテーマ別タスク集計を行い、静的HTMLを生成する。"""

from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INPUT_DIR = ROOT / "input"
OUTPUT_DIR = ROOT / "output"
THEME_TAGS_PATH = INPUT_DIR / "theme_tags.json"
HTML_OUTPUT_PATH = OUTPUT_DIR / "task_analysis.html"

REPORT_GLOB = "*_日報.md"
DATE_IN_FILE = re.compile(r"(\d{8})_日報\.md$")
DATE_IN_TABLE = re.compile(r"(\d{4})/(\d{2})/(\d{2})")
SECTION_HEADING = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)
CHECKBOX_LINE = re.compile(r"^-\s+\[([ xX])\]\s+(.+)$", re.MULTILINE)
TABLE_ROW = re.compile(r"^\|(.+)\|\s*$", re.MULTILINE)
BULLET_LINE = re.compile(r"^-\s+(.+)$", re.MULTILINE)


def load_theme_config() -> dict:
    with THEME_TAGS_PATH.open(encoding="utf-8") as f:
        return json.load(f)


def normalize_date(y: str, m: str, d: str) -> str:
    return f"{y}-{m}-{d}"


def parse_date_from_content(text: str) -> str | None:
    section = extract_section(text, "基本情報")
    if not section:
        return None
    for line in section.splitlines():
        if "日付" in line and "|" in line:
            m = DATE_IN_TABLE.search(line)
            if m:
                return normalize_date(m.group(1), m.group(2), m.group(3))
    return None


def parse_date_from_filename(path: Path) -> str | None:
    m = DATE_IN_FILE.search(path.name)
    if not m:
        return None
    s = m.group(1)
    return f"{s[0:4]}-{s[4:6]}-{s[6:8]}"


def extract_section(text: str, title: str) -> str | None:
    headings = list(SECTION_HEADING.finditer(text))
    for i, match in enumerate(headings):
        if match.group(1).strip() != title:
            continue
        start = match.end()
        end = headings[i + 1].start() if i + 1 < len(headings) else len(text)
        return text[start:end].strip()
    return None


def split_table_cells(row: str) -> list[str]:
    parts = [p.strip() for p in row.strip("|").split("|")]
    return parts


def is_separator_row(cells: list[str]) -> bool:
    if not cells:
        return True
    return all(re.match(r"^:?-+:?$", c.replace(" ", "")) for c in cells if c)


def parse_markdown_table(section: str) -> list[list[str]]:
    rows: list[list[str]] = []
    for line in section.splitlines():
        if not line.strip().startswith("|"):
            continue
        cells = split_table_cells(line)
        if is_separator_row(cells):
            continue
        rows.append(cells)
    return rows


def strip_markdown_bold(text: str) -> str:
    return re.sub(r"\*\*(.+?)\*\*", r"\1", text)


def extract_fragments(text: str, source_file: str) -> list[dict]:
    fragments: list[dict] = []
    report_date = parse_date_from_content(text)
    file_date = parse_date_from_filename(Path(source_file))
    if report_date and file_date and report_date != file_date:
        print(
            f"警告: {source_file} の表日付({report_date})とファイル名({file_date})が不一致。表日付を使用します。",
            file=sys.stderr,
        )
    date = report_date or file_date
    if not date:
        print(f"警告: {source_file} から日付を取得できませんでした。スキップします。", file=sys.stderr)
        return []

    # 本日の目標
    goals = extract_section(text, "本日の目標")
    if goals:
        for m in CHECKBOX_LINE.finditer(goals):
            status = "done" if m.group(1).lower() == "x" else "open"
            fragments.append(
                {
                    "date": date,
                    "section": "本日の目標",
                    "text": strip_markdown_bold(m.group(2).strip()),
                    "status": status,
                }
            )

    # 業務内容（表: ヘッダ除くデータ行）
    work = extract_section(text, "業務内容")
    if work:
        rows = parse_markdown_table(work)
        for row in rows:
            if len(row) < 3:
                continue
            header_like = row[0] in ("時間帯", "項目") or row[1] in ("業務内容",)
            if header_like:
                continue
            combined = " / ".join(strip_markdown_bold(c) for c in row if c)
            if combined.strip():
                fragments.append(
                    {
                        "date": date,
                        "section": "業務内容",
                        "text": combined,
                        "status": None,
                    }
                )

    # 本日の成果・実績
    results = extract_section(text, "本日の成果・実績")
    if results:
        for m in BULLET_LINE.finditer(results):
            line = m.group(1).strip()
            if not line or line.startswith("※"):
                continue
            fragments.append(
                {
                    "date": date,
                    "section": "本日の成果・実績",
                    "text": strip_markdown_bold(line),
                    "status": None,
                }
            )

    # 明日の予定
    tomorrow = extract_section(text, "明日の予定")
    if tomorrow:
        rows = parse_markdown_table(tomorrow)
        for row in rows:
            if len(row) < 3:
                continue
            if row[0] in ("優先度",) or row[1] in ("予定・タスク",):
                continue
            priority, task, goal = row[0], row[1], row[2]
            combined = f"[{priority}] {strip_markdown_bold(task)} — {strip_markdown_bold(goal)}"
            fragments.append(
                {
                    "date": date,
                    "section": "明日の予定",
                    "text": combined,
                    "status": priority,
                }
            )

    return fragments


def match_themes(text: str, config: dict) -> list[dict]:
    matched: list[dict] = []
    lower = text.lower()
    for theme in config["themes"]:
        for kw in theme["keywords"]:
            if kw.lower() in lower or kw in text:
                matched.append({"id": theme["id"], "label": theme["label"]})
                break
    if not matched:
        matched.append(
            {
                "id": config.get("fallback_id", "other"),
                "label": config.get("fallback_label", "その他"),
            }
        )
    return matched


def build_analysis(reports: list[tuple[Path, str]], config: dict) -> dict:
    all_items: list[dict] = []
    for path, content in reports:
        for frag in extract_fragments(content, path.name):
            themes = match_themes(frag["text"], config)
            all_items.append(
                {
                    **frag,
                    "source_file": path.name,
                    "themes": [t["id"] for t in themes],
                    "theme_labels": [t["label"] for t in themes],
                }
            )

    all_items.sort(key=lambda x: (x["date"], x["section"], x["text"]))

    theme_meta = {t["id"]: t["label"] for t in config["themes"]}
    theme_meta[config.get("fallback_id", "other")] = config.get("fallback_label", "その他")

    theme_totals: dict[str, int] = defaultdict(int)
    for item in all_items:
        for tid in item["themes"]:
            theme_totals[tid] += 1

    theme_totals_list = sorted(
        [
            {"id": tid, "label": theme_meta.get(tid, tid), "count": cnt}
            for tid, cnt in theme_totals.items()
        ],
        key=lambda x: (-x["count"], x["label"]),
    )

    dates = sorted({item["date"] for item in all_items})
    by_date: list[dict] = []
    for d in dates:
        day_counts: dict[str, int] = defaultdict(int)
        for item in all_items:
            if item["date"] != d:
                continue
            for tid in item["themes"]:
                day_counts[tid] += 1
        by_date.append({"date": d, "themes": dict(day_counts)})

    return {
        "meta": {
            "from": dates[0] if dates else None,
            "to": dates[-1] if dates else None,
            "reportCount": len(reports),
            "itemCount": len(all_items),
            "generatedAt": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        },
        "themeMeta": theme_meta,
        "themeTotals": theme_totals_list,
        "byDate": by_date,
        "items": all_items,
    }


def render_html(data: dict) -> str:
    data_json = json.dumps(data, ensure_ascii=False, indent=2)
    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>日報タスク分析（テーマ別）</title>
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
  <style>
    :root {{
      --bg: #0f1419;
      --surface: #1a2332;
      --border: #2d3a4f;
      --text: #e7ecf3;
      --muted: #8b9cb3;
      --accent: #4f8cff;
      --accent2: #3dd68c;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "Segoe UI", "Hiragino Sans", "Yu Gothic UI", sans-serif;
      background: var(--bg);
      color: var(--text);
      line-height: 1.5;
    }}
    .wrap {{ max-width: 1100px; margin: 0 auto; padding: 1.5rem; }}
    h1 {{ font-size: 1.5rem; margin: 0 0 0.25rem; }}
    .meta {{ color: var(--muted); font-size: 0.9rem; margin-bottom: 1.5rem; }}
    .cards {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 1rem;
      margin-bottom: 1.5rem;
    }}
    .card {{
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 1rem;
    }}
    .card .label {{ color: var(--muted); font-size: 0.8rem; }}
    .card .value {{ font-size: 1.75rem; font-weight: 700; color: var(--accent2); }}
    .card .sub {{ font-size: 0.85rem; color: var(--muted); }}
    .panel {{
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 1rem 1.25rem;
      margin-bottom: 1.5rem;
    }}
    .panel h2 {{ font-size: 1rem; margin: 0 0 1rem; }}
    .charts {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 1rem;
    }}
    @media (max-width: 800px) {{
      .charts {{ grid-template-columns: 1fr; }}
    }}
    .chart-box {{ position: relative; height: 280px; }}
    .filters {{
      display: flex;
      flex-wrap: wrap;
      gap: 0.5rem;
      align-items: center;
      margin-bottom: 1rem;
    }}
    .filters label {{ color: var(--muted); font-size: 0.9rem; }}
    select, input[type="search"] {{
      background: var(--bg);
      color: var(--text);
      border: 1px solid var(--border);
      border-radius: 6px;
      padding: 0.4rem 0.6rem;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 0.85rem;
    }}
    th, td {{
      border-bottom: 1px solid var(--border);
      padding: 0.5rem 0.6rem;
      text-align: left;
      vertical-align: top;
    }}
    th {{ color: var(--muted); font-weight: 600; }}
    .tag {{
      display: inline-block;
      background: #243044;
      color: var(--accent);
      border-radius: 4px;
      padding: 0.1rem 0.4rem;
      margin: 0.1rem 0.15rem 0.1rem 0;
      font-size: 0.75rem;
    }}
    .numeric-table {{ font-size: 0.85rem; }}
    .numeric-table td:last-child {{ text-align: right; }}
  </style>
</head>
<body>
  <div class="wrap">
    <h1>日報タスク分析（テーマ別集計）</h1>
    <p class="meta" id="headerMeta"></p>

    <div class="cards" id="summaryCards"></div>

    <div class="charts">
      <div class="panel">
        <h2>テーマ別言及数（期間合計）</h2>
        <div class="chart-box"><canvas id="barChart"></canvas></div>
      </div>
      <div class="panel">
        <h2>日別 × テーマ（積み上げ）</h2>
        <div class="chart-box"><canvas id="stackedChart"></canvas></div>
      </div>
    </div>

    <div class="panel">
      <h2>テーマ別数値一覧</h2>
      <table class="numeric-table" id="numericTable">
        <thead><tr><th>テーマ</th><th>言及数</th></tr></thead>
        <tbody></tbody>
      </table>
    </div>

    <div class="panel">
      <h2>詳細（出典付き）</h2>
      <div class="filters">
        <label for="themeFilter">テーマ</label>
        <select id="themeFilter"><option value="">すべて</option></select>
        <label for="sectionFilter">セクション</label>
        <select id="sectionFilter"><option value="">すべて</option></select>
        <label for="searchBox">検索</label>
        <input type="search" id="searchBox" placeholder="キーワード…" />
      </div>
      <table id="detailTable">
        <thead>
          <tr>
            <th>日付</th>
            <th>セクション</th>
            <th>テーマ</th>
            <th>内容</th>
          </tr>
        </thead>
        <tbody></tbody>
      </table>
    </div>
  </div>

  <script id="analysisData" type="application/json">
{data_json}
  </script>
  <script>
    const DATA = JSON.parse(document.getElementById("analysisData").textContent);

    const CHART_COLORS = [
      "#4f8cff", "#3dd68c", "#f0b429", "#e85d75", "#a78bfa", "#38bdf8", "#94a3b8"
    ];

    function initHeader() {{
      const m = DATA.meta;
      document.getElementById("headerMeta").textContent =
        `対象: ${{m.from || "—"}} 〜 ${{m.to || "—"}} ｜ 日報 ${{m.reportCount}} 件 ｜ 抽出 ${{m.itemCount}} 件 ｜ 生成: ${{m.generatedAt}}`;
    }}

    function initSummaryCards() {{
      const top = DATA.themeTotals.slice(0, 3);
      const el = document.getElementById("summaryCards");
      el.innerHTML = top.map((t, i) => `
        <div class="card">
          <div class="label">TOP ${{i + 1}} テーマ</div>
          <div class="value">${{t.count}}</div>
          <div class="sub">${{t.label}}</div>
        </div>
      `).join("") + `
        <div class="card">
          <div class="label">抽出件数</div>
          <div class="value">${{DATA.meta.itemCount}}</div>
          <div class="sub">全セクション合計</div>
        </div>`;
    }}

    function initNumericTable() {{
      const tbody = document.querySelector("#numericTable tbody");
      tbody.innerHTML = DATA.themeTotals.map(t =>
        `<tr><td>${{t.label}}</td><td>${{t.count}}</td></tr>`
      ).join("");
    }}

    let barChart, stackedChart;

    function initCharts() {{
      const labels = DATA.themeTotals.map(t => t.label);
      const counts = DATA.themeTotals.map(t => t.count);

      barChart = new Chart(document.getElementById("barChart"), {{
        type: "bar",
        data: {{
          labels,
          datasets: [{{
            label: "言及数",
            data: counts,
            backgroundColor: CHART_COLORS.slice(0, labels.length),
          }}],
        }},
        options: {{
          responsive: true,
          maintainAspectRatio: false,
          plugins: {{ legend: {{ display: false }} }},
          scales: {{
            y: {{ beginAtZero: true, ticks: {{ precision: 0 }} }},
            x: {{ ticks: {{ maxRotation: 45, minRotation: 0 }} }},
          }},
        }},
      }});

      const dates = DATA.byDate.map(d => d.date);
      const themeIds = DATA.themeTotals.map(t => t.id);
      const datasets = themeIds.map((id, i) => ({{
        label: DATA.themeMeta[id] || id,
        data: DATA.byDate.map(d => d.themes[id] || 0),
        backgroundColor: CHART_COLORS[i % CHART_COLORS.length],
        stack: "stack0",
      }}));

      stackedChart = new Chart(document.getElementById("stackedChart"), {{
        type: "bar",
        data: {{ labels: dates, datasets }},
        options: {{
          responsive: true,
          maintainAspectRatio: false,
          scales: {{
            x: {{ stacked: true }},
            y: {{ stacked: true, beginAtZero: true, ticks: {{ precision: 0 }} }},
          }},
        }},
      }});
    }}

    function initFilters() {{
      const themeSel = document.getElementById("themeFilter");
      DATA.themeTotals.forEach(t => {{
        const opt = document.createElement("option");
        opt.value = t.id;
        opt.textContent = t.label;
        themeSel.appendChild(opt);
      }});

      const sections = [...new Set(DATA.items.map(i => i.section))].sort();
      const secSel = document.getElementById("sectionFilter");
      sections.forEach(s => {{
        const opt = document.createElement("option");
        opt.value = s;
        opt.textContent = s;
        secSel.appendChild(opt);
      }});

      [themeSel, secSel, document.getElementById("searchBox")].forEach(el => {{
        el.addEventListener("input", renderDetailTable);
        el.addEventListener("change", renderDetailTable);
      }});
    }}

    function renderDetailTable() {{
      const themeId = document.getElementById("themeFilter").value;
      const section = document.getElementById("sectionFilter").value;
      const q = document.getElementById("searchBox").value.trim().toLowerCase();

      const filtered = DATA.items.filter(item => {{
        if (themeId && !item.themes.includes(themeId)) return false;
        if (section && item.section !== section) return false;
        if (q && !item.text.toLowerCase().includes(q)) return false;
        return true;
      }});

      const tbody = document.querySelector("#detailTable tbody");
      tbody.innerHTML = filtered.map(item => `
        <tr>
          <td>${{item.date}}</td>
          <td>${{item.section}}</td>
          <td>${{item.theme_labels.map(l => `<span class="tag">${{l}}</span>`).join("")}}</td>
          <td>${{escapeHtml(item.text)}}</td>
        </tr>
      `).join("");
    }}

    function escapeHtml(s) {{
      return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
    }}

    initHeader();
    initSummaryCards();
    initNumericTable();
    initCharts();
    initFilters();
    renderDetailTable();
  </script>
</body>
</html>
"""


def main() -> int:
    if not THEME_TAGS_PATH.exists():
        print(f"エラー: {THEME_TAGS_PATH} が見つかりません。", file=sys.stderr)
        return 1

    config = load_theme_config()
    report_paths = sorted(OUTPUT_DIR.glob(REPORT_GLOB))
    if not report_paths:
        print(f"エラー: {OUTPUT_DIR} に日報がありません。", file=sys.stderr)
        return 1

    reports: list[tuple[Path, str]] = []
    for path in report_paths:
        reports.append((path, path.read_text(encoding="utf-8")))

    data = build_analysis(reports, config)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    html = render_html(data)
    HTML_OUTPUT_PATH.write_text(html, encoding="utf-8")

    print(f"生成完了: {HTML_OUTPUT_PATH}")
    print(f"  日報: {data['meta']['reportCount']} 件")
    print(f"  抽出: {data['meta']['itemCount']} 件")
    print("  テーマ別:")
    for t in data["themeTotals"]:
        print(f"    - {t['label']}: {t['count']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
