#!/usr/bin/env python3
"""
simulation.py — бенчмарк словарного тренажёра.

Многократно прогоняет WordsSession с виртуальным учеником (вероятность
правильного ответа p) и собирает метрики. Параллельно гоняет baseline
RandomChoiceSession (без anti-repeat буферов) для сравнения.

Метрики на пробег:
  * total_steps — общее число шагов до опустошения пула
  * shows_per_word — распределение количества показов одного слова
  * repeat_distances — гистограмма расстояния между повторами (в шагах)
  * wrong_returns_5 — доля ошибочных слов, вернувшихся в первые 5 шагов

Результаты:
  * trials.csv — построчно, одна строка на пробег
  * summary.csv — агрегаты по (kind, p)
  * plots/*.png — графики через matplotlib
  * report.md — отчёт со сводными таблицами и встроенными графиками
  * sim_<timestamp>.zip — всё запаковано

CLI:
  python simulation.py --dict resources/words/term_4_unit1_internet.json \
                       --trials 100 --probs 0.5,0.7,0.9 --output out/

Без аргументов: подбирает первый JSON-словарь из resources/words/,
гоняет 50 пробегов на p ∈ {0.5, 0.7, 0.9} для smart и baseline,
пишет отчёт в sim_results/sim_<timestamp>/.
"""

from __future__ import annotations
import argparse
import csv
import os
import random
import statistics
import sys
import time
import zipfile
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import matplotlib
matplotlib.use("Agg")  # без дисплея
import matplotlib.pyplot as plt
import numpy as np

# Корень проекта — текущая директория (скрипт лежит в корне).
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from exercises.english.generators import (
    WordsSession, WordsTrainerGenerator, _read_json_lenient,
)


# ---------- Baseline ----------

class RandomChoiceSession:
    """
    Простой baseline: следующее слово — случайное из ещё не отгаданных,
    без буфера антиповтора и без приоритизации ошибок.

    Интерфейс совместим с WordsSession в той части, что нужна симулятору:
    атрибут `_current`, методы `initial_prompt`, `submit`, `is_finished`.
    submit принимает user_input (строку) и сравнивает с _current, как и
    WordsSession — чтобы один и тот же цикл драйвера работал для обоих.
    """

    def __init__(self, words_dict: dict[str, str], **_ignored):
        self._remaining: dict[str, str] = dict(words_dict)
        self._current: str | None = None

    def initial_prompt(self):
        if self._remaining:
            self._current = random.choice(list(self._remaining.keys()))
        return []

    def submit(self, user_input: str):
        if self._current is None:
            return None
        expected = self._current
        ok = user_input.strip().lower() == expected.lower()
        if ok:
            self._remaining.pop(expected, None)
        if not self._remaining:
            self._current = None
            return ok
        self._current = random.choice(list(self._remaining.keys()))
        return ok

    def is_finished(self) -> bool:
        return not self._remaining


# ---------- Метрики ----------

@dataclass
class TrialMetrics:
    """Метрики одного прогона сессии."""
    kind: str                       # "smart" или "baseline"
    probability: float              # p — вероятность правильного ответа
    trial_id: int
    pool_size: int                  # начальный размер словаря
    total_steps: int
    shows_per_word: dict[str, int]  # сколько раз показалось каждое слово
    max_shows: int
    mean_shows: float
    repeat_distances: list[int]     # расстояния между повторами в шагах
    mean_repeat_distance: float
    median_repeat_distance: float
    wrong_count: int                # сколько было ошибочных ответов
    wrong_returns_5: int            # из них вернулись в течение 5 шагов

    @property
    def return_5_frac(self) -> float:
        return self.wrong_returns_5 / self.wrong_count if self.wrong_count else 0.0


# ---------- Прогон одной сессии ----------

# Защитный предел на случай патологии — при p=0.0 сессия не завершится.
# 200x от размера словаря с запасом покрывает даже p=0.3.
MAX_STEPS_FACTOR = 200


def run_trial(
    kind: str,
    p: float,
    words: dict[str, str],
    priority_recent_wrong: float,
    trial_id: int,
) -> TrialMetrics:
    """
    Прогнать одну сессию с виртуальным учеником и вернуть метрики.

    Виртуальный ученик отвечает правильно с вероятностью p, независимо
    от слова. В случае правильного ответа подаём строку = expected,
    иначе — заведомо неправильную "WRONG_ANSWER", чтобы пройти штатным
    путём через submit (а не патчить внутренности сессии).
    """
    if kind == "smart":
        sess = WordsSession(
            words, priority_recent_wrong=priority_recent_wrong,
        )
    elif kind == "baseline":
        sess = RandomChoiceSession(words)
    else:
        raise ValueError(f"Unknown session kind: {kind!r}")

    sess.initial_prompt()

    step_log: list[tuple[str, bool]] = []
    max_steps = MAX_STEPS_FACTOR * max(1, len(words))

    while not sess.is_finished():
        word = sess._current
        if word is None:
            break
        ok = random.random() < p
        step_log.append((word, ok))
        sess.submit(word if ok else "WRONG_ANSWER")
        if len(step_log) > max_steps:
            # Аварийный выход: на p, близких к 0, сессия может не сойтись
            # в разумное число шагов. Сохраняем то, что есть.
            break

    return _extract_metrics(kind, p, trial_id, step_log, len(words))


def _extract_metrics(
    kind: str, p: float, tid: int,
    log: list[tuple[str, bool]], pool_size: int,
) -> TrialMetrics:
    shows: Counter[str] = Counter()
    last_seen_step: dict[str, int] = {}
    repeat_dists: list[int] = []
    wrong_indices: list[tuple[int, str]] = []

    for step, (word, ok) in enumerate(log):
        shows[word] += 1
        prev = last_seen_step.get(word)
        if prev is not None:
            repeat_dists.append(step - prev)
        last_seen_step[word] = step
        if not ok:
            wrong_indices.append((step, word))

    # Сколько раз ошибочное слово вернулось в первые 5 шагов после ошибки
    wrong_returns_5 = 0
    for step, word in wrong_indices:
        for k in range(step + 1, min(step + 6, len(log))):
            if log[k][0] == word:
                wrong_returns_5 += 1
                break

    total = len(log)
    return TrialMetrics(
        kind=kind,
        probability=p,
        trial_id=tid,
        pool_size=pool_size,
        total_steps=total,
        shows_per_word=dict(shows),
        max_shows=max(shows.values()) if shows else 0,
        mean_shows=(total / pool_size) if pool_size else 0.0,
        repeat_distances=repeat_dists,
        mean_repeat_distance=statistics.mean(repeat_dists) if repeat_dists else 0.0,
        median_repeat_distance=(
            statistics.median(repeat_dists) if repeat_dists else 0.0
        ),
        wrong_count=len(wrong_indices),
        wrong_returns_5=wrong_returns_5,
    )


# ---------- CSV ----------

def write_csvs(trials: list[TrialMetrics], out_dir: Path) -> None:
    # Построчно — одна строка на пробег
    with (out_dir / "trials.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow([
            "trial_id", "kind", "p", "pool_size",
            "total_steps", "max_shows", "mean_shows",
            "mean_repeat_distance", "median_repeat_distance",
            "wrong_count", "wrong_returns_5", "return_5_frac",
        ])
        for t in trials:
            w.writerow([
                t.trial_id, t.kind, t.probability, t.pool_size,
                t.total_steps, t.max_shows, f"{t.mean_shows:.3f}",
                f"{t.mean_repeat_distance:.3f}",
                f"{t.median_repeat_distance:.3f}",
                t.wrong_count, t.wrong_returns_5, f"{t.return_5_frac:.4f}",
            ])

    # Агрегаты по (kind, p)
    grouped: dict[tuple[str, float], list[TrialMetrics]] = defaultdict(list)
    for t in trials:
        grouped[(t.kind, t.probability)].append(t)

    with (out_dir / "summary.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow([
            "kind", "p", "trials",
            "mean_steps", "std_steps", "median_steps",
            "mean_max_shows", "mean_repeat_distance",
            "mean_return_5_frac",
        ])
        for key in sorted(grouped.keys()):
            ts = grouped[key]
            steps = [t.total_steps for t in ts]
            max_shows = [t.max_shows for t in ts]
            dists = [t.mean_repeat_distance for t in ts]
            fracs = [t.return_5_frac for t in ts]
            w.writerow([
                key[0], key[1], len(ts),
                f"{statistics.mean(steps):.2f}",
                f"{statistics.stdev(steps) if len(steps) > 1 else 0.0:.2f}",
                f"{statistics.median(steps):.2f}",
                f"{statistics.mean(max_shows):.2f}",
                f"{statistics.mean(dists):.3f}",
                f"{statistics.mean(fracs):.4f}",
            ])


# ---------- Графики ----------

# Стабильный палитра по виду сессии — чтобы один цвет = один алгоритм
KIND_COLOR = {"smart": "#1f77b4", "baseline": "#d62728"}


def _group(trials: list[TrialMetrics]):
    """Сгруппировать по (kind, p), вернуть отсортированный список ключей."""
    g: dict[tuple[str, float], list[TrialMetrics]] = defaultdict(list)
    for t in trials:
        g[(t.kind, t.probability)].append(t)
    # Порядок: сначала p по возрастанию, потом kind (smart перед baseline)
    keys = sorted(g.keys(), key=lambda k: (k[1], k[0]))
    return g, keys


def plot_total_steps(trials, out_path: Path) -> None:
    """Бар: среднее число шагов с погрешностью stdev, по (kind, p)."""
    grouped, keys = _group(trials)
    means = [statistics.mean([t.total_steps for t in grouped[k]]) for k in keys]
    stds = [
        statistics.stdev([t.total_steps for t in grouped[k]])
        if len(grouped[k]) > 1 else 0.0
        for k in keys
    ]
    pool = trials[0].pool_size if trials else 0

    fig, ax = plt.subplots(figsize=(9, 5))
    x = np.arange(len(keys))
    colors = [KIND_COLOR[k[0]] for k in keys]
    ax.bar(x, means, yerr=stds, color=colors, capsize=4, edgecolor="#333")
    ax.set_xticks(x)
    ax.set_xticklabels([f"{k[0]}\np={k[1]}" for k in keys])
    ax.set_ylabel("Шагов до завершения")
    ax.set_title(f"Среднее число шагов (размер словаря = {pool})")
    ax.axhline(pool, color="gray", linestyle="--", linewidth=1,
               label=f"идеал = {pool} (по 1 показу на слово)")
    ax.legend(loc="upper right")
    ax.grid(axis="y", linestyle=":", alpha=0.5)
    plt.tight_layout()
    plt.savefig(out_path, dpi=120)
    plt.close()


def plot_return_5_frac(trials, out_path: Path) -> None:
    """Бар: доля ошибочных слов, вернувшихся в первые 5 шагов."""
    grouped, keys = _group(trials)
    means = [statistics.mean([t.return_5_frac for t in grouped[k]]) for k in keys]

    fig, ax = plt.subplots(figsize=(9, 5))
    x = np.arange(len(keys))
    colors = [KIND_COLOR[k[0]] for k in keys]
    ax.bar(x, means, color=colors, edgecolor="#333")
    ax.set_xticks(x)
    ax.set_xticklabels([f"{k[0]}\np={k[1]}" for k in keys])
    ax.set_ylabel("Доля")
    ax.set_ylim(0, 1.0)
    ax.set_title("Доля ошибочных слов, вернувшихся в течение 5 шагов")
    ax.grid(axis="y", linestyle=":", alpha=0.5)
    plt.tight_layout()
    plt.savefig(out_path, dpi=120)
    plt.close()


def plot_shows_distribution(trials, out_path: Path) -> None:
    """
    Гистограмма «сколько раз показалось одно слово», по разрезам (kind, p).
    Все пробеги объединяются — это даёт устойчивое распределение.
    """
    grouped, keys = _group(trials)
    fig, axes = plt.subplots(
        len(keys), 1, figsize=(9, 2.0 * len(keys)), sharex=True
    )
    if len(keys) == 1:
        axes = [axes]
    for ax, key in zip(axes, keys):
        all_shows: list[int] = []
        for t in grouped[key]:
            all_shows.extend(t.shows_per_word.values())
        if all_shows:
            bins = np.arange(0.5, max(all_shows) + 1.5, 1)
            ax.hist(all_shows, bins=bins, color=KIND_COLOR[key[0]],
                    edgecolor="#333", alpha=0.85)
        ax.set_title(f"{key[0]}, p={key[1]}")
        ax.set_ylabel("Слов")
        ax.grid(axis="y", linestyle=":", alpha=0.5)
    axes[-1].set_xlabel("Сколько раз слово было показано")
    fig.suptitle("Распределение количества показов одного слова")
    plt.tight_layout()
    plt.savefig(out_path, dpi=120)
    plt.close()


def plot_repeat_distances(trials, out_path: Path) -> None:
    """
    Гистограмма расстояний между повторами одного и того же слова.
    Хвост вправо = слова возвращаются нескоро; пик у нуля = алгоритм
    повторяет почти сразу. Smart-алгоритм должен сдвигать массу вправо.
    """
    grouped, keys = _group(trials)
    fig, axes = plt.subplots(
        len(keys), 1, figsize=(9, 2.0 * len(keys)), sharex=True
    )
    if len(keys) == 1:
        axes = [axes]
    # Общий диапазон по всем разрезам, чтобы оси были одинаковыми
    all_dists = [d for t in trials for d in t.repeat_distances]
    if not all_dists:
        upper = 10
    else:
        # 95-й перцентиль обрезает редкие выбросы для читаемости
        upper = int(np.percentile(all_dists, 95)) + 1
    for ax, key in zip(axes, keys):
        flat: list[int] = []
        for t in grouped[key]:
            flat.extend(t.repeat_distances)
        if flat:
            bins = np.arange(0.5, upper + 1.5, 1)
            ax.hist(flat, bins=bins, color=KIND_COLOR[key[0]],
                    edgecolor="#333", alpha=0.85)
        ax.set_title(f"{key[0]}, p={key[1]}")
        ax.set_ylabel("Пар повторов")
        ax.grid(axis="y", linestyle=":", alpha=0.5)
    axes[-1].set_xlabel("Расстояние между повторами (шаги)")
    fig.suptitle("Распределение расстояний между повторами")
    plt.tight_layout()
    plt.savefig(out_path, dpi=120)
    plt.close()


# ---------- Отчёт ----------

def build_report(
    trials: list[TrialMetrics],
    out_dir: Path,
    config: dict,
) -> Path:
    """
    Markdown-отчёт со сводными таблицами и встроенными графиками.
    Возвращает путь к файлу report.md.
    """
    grouped, keys = _group(trials)

    lines: list[str] = []
    lines.append("# Бенчмарк словарного тренажёра")
    lines.append("")
    lines.append(f"Запуск: **{config['timestamp']}**  ")
    lines.append(f"Словарь: `{config['dict_path']}` ({config['pool_size']} слов)  ")
    lines.append(f"Пробегов на конфигурацию: **{config['trials']}**  ")
    lines.append(f"Вероятности: {', '.join(str(p) for p in config['probs'])}  ")
    lines.append(f"priority_recent_wrong: **{config['priority_recent_wrong']}**  ")
    lines.append("")

    lines.append("## Сводная таблица")
    lines.append("")
    lines.append("| Алгоритм | p | Пробегов | Среднее шагов | Std шагов | "
                 "Медиана | Макс. показов в среднем | Среднее расстояние повторов | "
                 "Возврат после ошибки в 5 шагов |")
    lines.append("|---|---|---|---|---|---|---|---|---|")
    for key in keys:
        ts = grouped[key]
        steps = [t.total_steps for t in ts]
        max_shows = [t.max_shows for t in ts]
        dists = [t.mean_repeat_distance for t in ts]
        fracs = [t.return_5_frac for t in ts]
        lines.append(
            f"| {key[0]} | {key[1]} | {len(ts)} | "
            f"{statistics.mean(steps):.1f} | "
            f"{(statistics.stdev(steps) if len(steps) > 1 else 0):.1f} | "
            f"{statistics.median(steps):.0f} | "
            f"{statistics.mean(max_shows):.2f} | "
            f"{statistics.mean(dists):.2f} | "
            f"{statistics.mean(fracs):.1%} |"
        )
    lines.append("")

    lines.append("## Графики")
    lines.append("")
    lines.append("### Шагов до завершения")
    lines.append("")
    lines.append("![Total steps](plots/total_steps.png)")
    lines.append("")
    lines.append("Идеал — 1 показ на слово (равно размеру пула). Smart и baseline "
                 "обычно дают близкое общее число шагов: алгоритм меняет не "
                 "*сколько* раз спрашивает, а *в каком порядке* и *за что* "
                 "наказывает повторами.")
    lines.append("")

    lines.append("### Возврат к ошибочному слову в первые 5 шагов")
    lines.append("")
    lines.append("![Wrong returns within 5](plots/wrong_returns_5.png)")
    lines.append("")
    lines.append("Главное отличие алгоритмов. Baseline случайно возвращает "
                 "ошибочное слово сразу же — это раздражает и не даёт паузы "
                 "для забывания. Smart благодаря FIFO `_last` держит пройденное "
                 "слово в стороне минимум ~⅓ пула; обходом этой паузы служит "
                 "`_last_wrong`, но и тогда возврат намного реже случайного.")
    lines.append("")

    lines.append("### Распределение показов одного слова")
    lines.append("")
    lines.append("![Shows distribution](plots/shows_distribution.png)")
    lines.append("")
    lines.append("При высоких p (≥0.7) у обоих алгоритмов большинство слов "
                 "показывается 1-2 раза. При p=0.5 smart намеренно показывает "
                 "проблемные слова чаще (более длинный хвост вправо у max_shows): "
                 "часто ошибочные слова сознательно повторяются, в то время как "
                 "у baseline шум распределяется равномерно.")
    lines.append("")

    lines.append("### Расстояния между повторами")
    lines.append("")
    lines.append("![Repeat distances](plots/repeat_distances.png)")
    lines.append("")
    lines.append("При высоких p — smart сдвигает массу вправо (антиповтор работает). "
                 "При низких p, наоборот, smart сжимает распределение влево: "
                 "балансировка `_last_wrong` сознательно возвращает недавно "
                 "ошибочные слова раньше, чтобы их закрепить. Baseline всегда "
                 "даёт около `pool_size/2` в среднем — это статистика случайного "
                 "выбора без памяти.")
    lines.append("")

    lines.append("## Файлы")
    lines.append("")
    lines.append("- `trials.csv` — построчные метрики каждого пробега")
    lines.append("- `summary.csv` — агрегаты по (kind, p)")
    lines.append("- `plots/*.png` — графики")
    lines.append("")

    report_path = out_dir / "report.md"
    report_path.write_text("\n".join(lines), encoding="utf-8")
    return report_path


# ---------- Пакетная упаковка ----------

def zip_directory(src: Path, archive: Path) -> None:
    """Запаковать всё содержимое каталога src в zip-архив archive."""
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in src.rglob("*"):
            if path.is_file():
                zf.write(path, path.relative_to(src.parent))


# ---------- Загрузка словаря ----------

def load_dictionary(path: Path | None) -> tuple[Path, dict[str, str]]:
    """
    Загрузить словарь term→translation. Если path не задан — берём первый
    JSON из resources/words, который распознался как «words».
    """
    from exercises.english.generators import _detect_kind

    if path is None:
        words_dir = ROOT / "resources" / "words"
        candidates = sorted(words_dir.glob("*.json"))
        for p in candidates:
            if _detect_kind(p) == "words":
                path = p
                break
        if path is None:
            raise SystemExit(f"Не найден словарь в {words_dir}")
    data = _read_json_lenient(path)
    words = WordsTrainerGenerator._flatten_words(data)
    if not words:
        raise SystemExit(f"Словарь {path} пуст или не распознан.")
    return path, words


# ---------- CLI ----------

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Бенчмарк словарного тренажёра (smart vs baseline).",
    )
    p.add_argument("--dict", dest="dict_path", type=Path, default=None,
                   help="Путь к JSON-словарю. По умолчанию — первый из resources/words.")
    p.add_argument("--trials", type=int, default=50,
                   help="Пробегов на каждую конфигурацию (kind, p). По умолчанию 50.")
    p.add_argument("--probs", type=str, default="0.5,0.7,0.9",
                   help="Вероятности правильного ответа через запятую.")
    p.add_argument("--priority-recent-wrong", type=float, default=0.4,
                   help="Параметр приоритизации smart-алгоритма (0..1).")
    p.add_argument("--output", type=Path, default=None,
                   help="Каталог результатов. По умолчанию sim_results/sim_<ts>/.")
    p.add_argument("--seed", type=int, default=None,
                   help="Фиксировать random seed для воспроизводимости.")
    p.add_argument("--no-zip", action="store_true",
                   help="Не паковать выходной каталог в zip.")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.seed is not None:
        random.seed(args.seed)

    try:
        probs = [float(x) for x in args.probs.split(",") if x.strip()]
    except ValueError:
        print(f"Не удалось разобрать --probs={args.probs!r}", file=sys.stderr)
        return 2

    dict_path, words = load_dictionary(args.dict_path)
    pool_size = len(words)

    ts = time.strftime("%Y%m%d_%H%M%S")
    out_dir = args.output or (ROOT / "sim_results" / f"sim_{ts}")
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "plots").mkdir(exist_ok=True)

    print(f"Словарь: {dict_path} ({pool_size} слов)")
    print(f"Вероятности: {probs}")
    print(f"Пробегов на конфигурацию: {args.trials}")
    print(f"Выходной каталог: {out_dir}")

    trials: list[TrialMetrics] = []
    total_configs = 2 * len(probs)
    config_idx = 0
    for kind in ("smart", "baseline"):
        for p in probs:
            config_idx += 1
            print(f"[{config_idx}/{total_configs}] {kind}, p={p} ...", flush=True)
            for trial_id in range(args.trials):
                trials.append(run_trial(
                    kind, p, words,
                    priority_recent_wrong=args.priority_recent_wrong,
                    trial_id=trial_id,
                ))

    print("Запись CSV ...", flush=True)
    write_csvs(trials, out_dir)

    print("Построение графиков ...", flush=True)
    plot_total_steps(trials, out_dir / "plots" / "total_steps.png")
    plot_return_5_frac(trials, out_dir / "plots" / "wrong_returns_5.png")
    plot_shows_distribution(trials, out_dir / "plots" / "shows_distribution.png")
    plot_repeat_distances(trials, out_dir / "plots" / "repeat_distances.png")

    config = {
        "timestamp": ts,
        "dict_path": str(dict_path),
        "pool_size": pool_size,
        "trials": args.trials,
        "probs": probs,
        "priority_recent_wrong": args.priority_recent_wrong,
    }
    report_path = build_report(trials, out_dir, config)
    print(f"Отчёт: {report_path}")

    if not args.no_zip:
        archive = out_dir.with_suffix(".zip")
        zip_directory(out_dir, archive)
        print(f"Архив: {archive}")

    print("Готово.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
