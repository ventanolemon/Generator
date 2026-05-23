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
from core import WordStatsStore, WordStat


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


# ---------- Межсессионный бенчмарк (две сессии подряд) ----------

class _NullRepo:
    """
    Заглушка Repository для гостевого WordStatsStore. Гостевой режим
    (user_id=None) хранит статистику в памяти и к БД не обращается; нужен
    лишь no-op ensure_word_stats_table при конструировании store.

    Так межсессионный прогон не зависит от файла БД и быстр, при этом
    использует ровно ту же логику WordStatsStore.fetch/record и
    WordsSession._pick_next, что и SQLite-путь авторизованных пользователей.
    """

    def ensure_word_stats_table(self) -> None:
        return None


@dataclass
class CrossSessionMetrics:
    """Метрики одного двухсессионного прогона над общим словарём."""
    config: str               # "baseline" (без памяти) или "smart"
    priority_recent_wrong: float | None
    trial_id: int
    pool_size: int
    n_first: int              # фактически измерено шагов в начале сессии 2
    hist_wrong_count: int     # сколько слов стали «исторически ошибочными»
    chance_frac: float        # hist_wrong_count / pool_size — уровень случайности
    observed_first_n: int     # из первых N шагов попали в hist_wrong
    observed_frac: float      # observed_first_n / n_first
    lift: float               # observed_frac / chance_frac (во сколько раз выше случайности)


def _historically_wrong_set(stats: dict[str, WordStat]) -> set[str]:
    """
    «Исторически ошибочные» слова: ошибались хотя бы раз и не реже, чем
    отвечали верно. Совпадает с критерием WordsSession._historically_wrong
    (без учёта давности, т.к. сессии идут подряд).
    """
    return {
        term for term, st in stats.items()
        if st.times_wrong > 0 and st.times_wrong >= st.times_correct
    }


def _drain_session(sess, words: dict[str, str], p: float, max_steps: int) -> None:
    """Прогнать сессию до конца с виртуальным учеником (вероятность p)."""
    while not sess.is_finished():
        w = sess._current
        if w is None:
            break
        ok = random.random() < p
        sess.submit(w if ok else "WRONG_ANSWER")
        if max_steps <= 0:
            break
        max_steps -= 1


def _capture_first_n(sess, p: float, n_first: int) -> list[str]:
    """
    Снять слова, показанные на первых n_first шагах сессии (промпт перед
    ответом), параллельно отвечая с вероятностью p, чтобы сессия жила.
    """
    shown: list[str] = []
    steps = 0
    while not sess.is_finished() and steps < n_first:
        w = sess._current
        if w is None:
            break
        shown.append(w)
        ok = random.random() < p
        sess.submit(w if ok else "WRONG_ANSWER")
        steps += 1
    return shown


# pr сессии 1 фиксирован — это «обычная первая тренировка» штатным алгоритмом.
# На множество ошибочных слов pr не влияет (оно определяется ответами ученика).
SESSION1_PRIORITY = 0.4


def run_cross_session_trial(
    config: str,
    pr: float | None,
    words: dict[str, str],
    p1: float,
    p2: float,
    n_first: int,
    trial_id: int,
) -> CrossSessionMetrics:
    """
    Один двухсессионный прогон над одним словарём:

      1. Сессия 1 (p=p1) штатным WordsSession с общим WordStatsStore —
         накапливает ошибки в память.
      2. Снимаем «исторически ошибочный» набор после сессии 1.
      3. Сессия 2 (p=p2) на тех же словах:
           * config="baseline" — RandomChoiceSession, статистику игнорирует
             (контрфактическое «без памяти»);
           * config="smart"    — WordsSession с подгруженной из store
             статистикой и заданным priority_recent_wrong.
      4. Метрика — доля «исторически ошибочных» среди первых n_first шагов
         сессии 2 и её отношение к уровню случайности (lift).

    Гостевой store создаётся свежим на каждый прогон, поэтому статистика
    одного прогона не протекает в другой.
    """
    pool_size = len(words)
    store = WordStatsStore(_NullRepo())  # свежая in-memory память на прогон
    max_steps = MAX_STEPS_FACTOR * max(1, pool_size)

    # --- Сессия 1: накапливаем ошибки ---
    s1 = WordsSession(
        words, stats_store=store, user_id=None,
        priority_recent_wrong=SESSION1_PRIORITY,
    )
    s1.initial_prompt()
    _drain_session(s1, words, p1, max_steps)

    # --- «Истина»: исторически ошибочные после сессии 1 ---
    stats_after = store.fetch(None, list(words.keys()))
    hist_wrong = _historically_wrong_set(stats_after)
    chance_frac = (len(hist_wrong) / pool_size) if pool_size else 0.0

    # --- Сессия 2: тот же словарь, статистика подгружена ---
    if config == "baseline":
        s2 = RandomChoiceSession(words)  # память игнорируется
    else:
        s2 = WordsSession(
            words, stats_store=store, user_id=None,
            priority_recent_wrong=(pr if pr is not None else 0.0),
        )
    s2.initial_prompt()
    first_words = _capture_first_n(s2, p2, n_first)

    n = len(first_words)
    observed = sum(1 for w in first_words if w in hist_wrong)
    observed_frac = (observed / n) if n else 0.0
    lift = (observed_frac / chance_frac) if chance_frac > 0 else 0.0

    return CrossSessionMetrics(
        config=config,
        priority_recent_wrong=pr,
        trial_id=trial_id,
        pool_size=pool_size,
        n_first=n,
        hist_wrong_count=len(hist_wrong),
        chance_frac=chance_frac,
        observed_first_n=observed,
        observed_frac=observed_frac,
        lift=lift,
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


def _cross_key(m: CrossSessionMetrics) -> tuple[str, float]:
    """Ключ группировки межсессионных прогонов: (config, pr|-1)."""
    return (m.config, m.priority_recent_wrong
            if m.priority_recent_wrong is not None else -1.0)


def _cross_label(config: str, pr: float) -> str:
    if config == "baseline":
        return "baseline\n(без памяти)"
    return f"smart\npr={pr:g}"


def write_cross_csvs(cross: list[CrossSessionMetrics], out_dir: Path) -> None:
    # Построчно
    with (out_dir / "cross_session_trials.csv").open(
        "w", newline="", encoding="utf-8"
    ) as f:
        w = csv.writer(f)
        w.writerow([
            "trial_id", "config", "priority_recent_wrong", "pool_size",
            "n_first", "hist_wrong_count", "chance_frac",
            "observed_first_n", "observed_frac", "lift",
        ])
        for m in cross:
            w.writerow([
                m.trial_id, m.config,
                "" if m.priority_recent_wrong is None else m.priority_recent_wrong,
                m.pool_size, m.n_first, m.hist_wrong_count,
                f"{m.chance_frac:.4f}", m.observed_first_n,
                f"{m.observed_frac:.4f}", f"{m.lift:.3f}",
            ])

    # Агрегаты по (config, pr)
    grouped: dict[tuple[str, float], list[CrossSessionMetrics]] = defaultdict(list)
    for m in cross:
        grouped[_cross_key(m)].append(m)

    with (out_dir / "cross_session_summary.csv").open(
        "w", newline="", encoding="utf-8"
    ) as f:
        w = csv.writer(f)
        w.writerow([
            "config", "priority_recent_wrong", "trials",
            "mean_observed_frac", "std_observed_frac",
            "mean_chance_frac", "mean_lift",
        ])
        for key in sorted(grouped.keys(), key=lambda k: (k[0] != "baseline", k[1])):
            ms = grouped[key]
            obs = [m.observed_frac for m in ms]
            chance = [m.chance_frac for m in ms]
            lifts = [m.lift for m in ms]
            w.writerow([
                key[0], "" if key[1] < 0 else key[1], len(ms),
                f"{statistics.mean(obs):.4f}",
                f"{statistics.stdev(obs) if len(obs) > 1 else 0.0:.4f}",
                f"{statistics.mean(chance):.4f}",
                f"{statistics.mean(lifts):.3f}",
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


def plot_cross_session(cross: list[CrossSessionMetrics], out_path: Path) -> None:
    """
    Бар: доля «исторически ошибочных» слов среди первых N шагов сессии 2,
    по конфигурациям. Пунктир — уровень случайности (средний chance_frac):
    столько ошибочных слов попало бы в начало при выборе без памяти.
    """
    grouped: dict[tuple[str, float], list[CrossSessionMetrics]] = defaultdict(list)
    for m in cross:
        grouped[_cross_key(m)].append(m)
    keys = sorted(grouped.keys(), key=lambda k: (k[0] != "baseline", k[1]))

    obs_means = [statistics.mean([m.observed_frac for m in grouped[k]]) for k in keys]
    obs_stds = [
        statistics.stdev([m.observed_frac for m in grouped[k]])
        if len(grouped[k]) > 1 else 0.0 for k in keys
    ]
    chance_mean = statistics.mean([m.chance_frac for m in cross]) if cross else 0.0
    n_first = cross[0].n_first if cross else 0

    colors = ["#7f7f7f" if k[0] == "baseline" else "#2ca02c" for k in keys]

    fig, ax = plt.subplots(figsize=(9, 5.5))
    x = np.arange(len(keys))
    bars = ax.bar(x, obs_means, yerr=obs_stds, color=colors,
                  capsize=4, edgecolor="#333")
    ax.axhline(chance_mean, color="#d62728", linestyle="--", linewidth=1.5,
               label=f"уровень случайности ≈ {chance_mean:.2f}")
    ax.set_xticks(x)
    ax.set_xticklabels([_cross_label(k[0], k[1]) for k in keys])
    ax.set_ylabel(f"Доля среди первых {n_first} шагов сессии 2")
    ax.set_ylim(0, 1.0)
    ax.set_title("Межсессионная память: доля «исторически ошибочных» слов\n"
                 "в начале второй сессии (тот же словарь, p=0.5 → p=0.5)")
    # Подписи значений над столбиками
    for rect, val in zip(bars, obs_means):
        ax.text(rect.get_x() + rect.get_width() / 2, val + 0.02,
                f"{val:.2f}", ha="center", va="bottom", fontsize=9)
    ax.legend(loc="upper left")
    ax.grid(axis="y", linestyle=":", alpha=0.5)
    plt.tight_layout()
    plt.savefig(out_path, dpi=120)
    plt.close()


# ---------- Отчёт ----------

def build_report(
    trials: list[TrialMetrics],
    out_dir: Path,
    config: dict,
    cross: list[CrossSessionMetrics] | None = None,
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
    lines.append("Отчёт состоит из двух частей: **(1)** внутрисессионное "
                 "поведение (smart vs baseline за одну сессию) и **(2)** "
                 "межсессионная память — эффект WordStatsStore при двух "
                 "сессиях подряд над одним словарём.")
    lines.append("")
    lines.append("## Часть 1. Внутри одной сессии")
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

    # ----- Часть 2. Межсессионная память -----
    if cross:
        _append_cross_report(lines, cross, config)

    lines.append("## Файлы")
    lines.append("")
    lines.append("- `trials.csv` — построчные метрики внутрисессионных пробегов")
    lines.append("- `summary.csv` — агрегаты по (kind, p)")
    if cross:
        lines.append("- `cross_session_trials.csv` — построчные межсессионные прогоны")
        lines.append("- `cross_session_summary.csv` — агрегаты по (config, pr)")
    lines.append("- `plots/*.png` — графики")
    lines.append("")

    report_path = out_dir / "report.md"
    report_path.write_text("\n".join(lines), encoding="utf-8")
    return report_path


def _append_cross_report(
    lines: list[str],
    cross: list[CrossSessionMetrics],
    config: dict,
) -> None:
    """Дописать в отчёт раздел про межсессионную память."""
    grouped: dict[tuple[str, float], list[CrossSessionMetrics]] = defaultdict(list)
    for m in cross:
        grouped[_cross_key(m)].append(m)
    keys = sorted(grouped.keys(), key=lambda k: (k[0] != "baseline", k[1]))

    chance_mean = statistics.mean([m.chance_frac for m in cross])
    n_first = cross[0].n_first
    cc = config.get("cross", {})

    lines.append("## Часть 2. Межсессионная память (две сессии подряд)")
    lines.append("")
    lines.append(
        f"Схема прогона: один и тот же словарь, виртуальный ученик проходит "
        f"**две сессии**. Сессия 1 (p={cc.get('p1', 0.5)}) штатным алгоритмом "
        f"накапливает ошибки в `WordStatsStore`. Сессия 2 (p={cc.get('p2', 0.5)}) "
        f"стартует на тех же словах с подгруженной статистикой. Метрика — "
        f"**доля «исторически ошибочных» слов среди первых N={n_first} шагов "
        f"сессии 2**."
    )
    lines.append("")
    lines.append(
        "«Исторически ошибочное» слово — то, в котором после сессии 1 ошибок "
        "не меньше, чем верных ответов (`times_wrong ≥ times_correct`). "
        "Это ровно тот критерий, по которому `WordsSession` отбирает слова при "
        "срабатывании `priority_recent_wrong`."
    )
    lines.append("")
    lines.append(
        f"**Уровень случайности** ≈ {chance_mean:.2f}: столько ошибочных слов "
        "попало бы в начало сессии 2 при выборе без памяти (их доля в пуле). "
        "Конфигурация `baseline` (сессия 2 = случайный выбор, статистика "
        "игнорируется) эмпирически подтверждает этот уровень. Превышение над "
        "ним — и есть измеренный эффект межсессионной памяти."
    )
    lines.append("")
    lines.append("| Конфигурация | pr | Прогонов | Доля ошибочных в первых "
                 f"{n_first} | Уровень случайности | Lift (×) |")
    lines.append("|---|---|---|---|---|---|")
    for key in keys:
        ms = grouped[key]
        obs = statistics.mean([m.observed_frac for m in ms])
        std = statistics.stdev([m.observed_frac for m in ms]) if len(ms) > 1 else 0.0
        chance = statistics.mean([m.chance_frac for m in ms])
        lift = statistics.mean([m.lift for m in ms])
        pr_label = "—" if key[1] < 0 else f"{key[1]:g}"
        cfg_label = "baseline (без памяти)" if key[0] == "baseline" else "smart"
        lines.append(
            f"| {cfg_label} | {pr_label} | {len(ms)} | "
            f"{obs:.1%} ± {std:.1%} | {chance:.1%} | {lift:.2f} |"
        )
    lines.append("")
    lines.append("![Cross-session memory](plots/cross_session.png)")
    lines.append("")
    lines.append(
        "**Вывод.** У `baseline` доля держится на уровне случайности — без "
        "использования памяти начало второй сессии ничем не выделяет ранее "
        "проваленные слова. У `smart` доля растёт вместе с `priority_recent_wrong`: "
        "память действительно выводит в начало повторной тренировки именно те "
        "слова, что были провалены в первой сессии. Это и есть эмпирическое "
        "подтверждение работы spaced-repetition-каркаса, а не только описание "
        "алгоритма."
    )
    lines.append("")


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

    # ----- Межсессионный бенчмарк -----
    p.add_argument("--cross-trials", type=int, default=60,
                   help="Прогонов на каждую межсессионную конфигурацию. По умолчанию 60.")
    p.add_argument("--first-n", type=int, default=15,
                   help="Сколько первых шагов сессии 2 измерять (N=10–20). По умолчанию 15.")
    p.add_argument("--p1", type=float, default=0.5,
                   help="Вероятность правильного ответа в сессии 1 (накопление ошибок).")
    p.add_argument("--p2", type=float, default=0.5,
                   help="Вероятность правильного ответа в сессии 2 (повтор).")
    p.add_argument("--cross-priorities", type=str, default="0.0,0.4,0.8",
                   help="Значения priority_recent_wrong для smart-сессии 2 через запятую.")
    p.add_argument("--no-cross", action="store_true",
                   help="Пропустить межсессионный бенчмарк (только часть 1).")
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

    # ----- Часть 2: межсессионный бенчмарк -----
    cross: list[CrossSessionMetrics] = []
    if not args.no_cross:
        try:
            cross_priorities = [
                float(x) for x in args.cross_priorities.split(",") if x.strip()
            ]
        except ValueError:
            print(f"Не удалось разобрать --cross-priorities="
                  f"{args.cross_priorities!r}", file=sys.stderr)
            return 2
        # Конфигурации: baseline (без памяти) + smart для каждого pr
        cross_configs: list[tuple[str, float | None]] = [("baseline", None)]
        cross_configs += [("smart", pr) for pr in cross_priorities]

        print(f"\nМежсессионный бенчмарк (две сессии, N={args.first_n}, "
              f"p1={args.p1}, p2={args.p2}):", flush=True)
        for ci, (cfg, pr) in enumerate(cross_configs, 1):
            label = "baseline" if cfg == "baseline" else f"smart pr={pr}"
            print(f"  [{ci}/{len(cross_configs)}] {label} ...", flush=True)
            for trial_id in range(args.cross_trials):
                cross.append(run_cross_session_trial(
                    cfg, pr, words,
                    p1=args.p1, p2=args.p2,
                    n_first=args.first_n, trial_id=trial_id,
                ))

    print("\nЗапись CSV ...", flush=True)
    write_csvs(trials, out_dir)
    if cross:
        write_cross_csvs(cross, out_dir)

    print("Построение графиков ...", flush=True)
    plot_total_steps(trials, out_dir / "plots" / "total_steps.png")
    plot_return_5_frac(trials, out_dir / "plots" / "wrong_returns_5.png")
    plot_shows_distribution(trials, out_dir / "plots" / "shows_distribution.png")
    plot_repeat_distances(trials, out_dir / "plots" / "repeat_distances.png")
    if cross:
        plot_cross_session(cross, out_dir / "plots" / "cross_session.png")

    config = {
        "timestamp": ts,
        "dict_path": str(dict_path),
        "pool_size": pool_size,
        "trials": args.trials,
        "probs": probs,
        "priority_recent_wrong": args.priority_recent_wrong,
        "cross": {
            "trials": args.cross_trials,
            "first_n": args.first_n,
            "p1": args.p1,
            "p2": args.p2,
        },
    }
    report_path = build_report(trials, out_dir, config, cross=cross)
    print(f"Отчёт: {report_path}")

    if not args.no_zip:
        archive = out_dir.with_suffix(".zip")
        zip_directory(out_dir, archive)
        print(f"Архив: {archive}")

    print("Готово.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
