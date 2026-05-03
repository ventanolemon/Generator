# Стандарт модулей генератора заданий

Документ описывает архитектурный стандарт для системы, генерирующей учебные задания по разным дисциплинам и выводящей их в нескольких представлениях. Цель стандарта — добиться полиморфизма: добавление нового предмета или нового типа задания не должно требовать правки ядра, групп, тестов или экспортёров.

---

## 1. Принципы

1. **Ядро не знает о предметах.** Главное окно, реестр, группы, тесты и экспортёры работают только с абстракциями `TaskGenerator`, `Task`, `Block`. Никаких `if subject == "Линал"` нигде, кроме реестра при старте.
2. **Контент — это список типизированных блоков, не строка.** Текст, формула, изображение, код, таблица — все они блоки с одинаковым интерфейсом, реализующим три метода рендеринга (Qt, plain, docx).
3. **У задания две природы — статичная и интерактивная.** Статичная: условие+ответ. Интерактивная: сессия с собственным циклом «спроси — проверь — продолжи». Обе живут под общим маркером `Task`, но имеют разные интерфейсы.
4. **Генератор декларирует свои возможности.** Через флаги `Capability` модуль сообщает, какие представления и режимы (группы, тесты, экспорт) ему применимы. Каркас опирается на эти флаги, а не на классовое ветвление.
5. **Композиция вместо наследования.** Группы и тесты — обычные `TaskGenerator`-ы, принимающие список других генераторов. Они не знают о предметах своих детей.
6. **Один модуль — один файл — один класс.** Минимальный модуль состоит из функции-генератора + класса-обёртки `TaskGenerator` + одной строки регистрации.

---

## 2. Архитектурные слои

```
UI                    StaticTaskView    TableTaskView    InteractiveTaskView    TestExportView
                              ↑                ↑                  ↑                  ↑
Композиты              GeneratorRegistry  •  GroupGenerator  •  TestGenerator
                                              ↑
Доменные модули        matan / linal / fisic / opvs / english / ...
                                              ↑                                   реализуют
Ядро                   TaskGenerator (контракт)  →  Task: StaticTask | InteractiveTask
                                                            ↑ содержат
                                              Block: TextBlock | FormulaBlock | ImageBlock | CodeBlock | TableBlock
```

Каждый слой знает только тот, что ниже. UI не знает про доменные модули; группы и тесты не знают про предметы; модули не знают про UI.

---

## 3. Контракты ядра

### 3.1. `Block` — единица контента

```python
# core/content.py
from abc import ABC, abstractmethod
from PyQt6.QtWidgets import QWidget
from docx.document import Document as DocxDoc

class Block(ABC):
    """Атомарная единица контента в задании или ответе."""

    @abstractmethod
    def render_qt(self, parent: QWidget) -> QWidget:
        """Вернуть виджет PyQt для отображения в интерфейсе."""

    @abstractmethod
    def render_plain(self) -> str:
        """Текстовое представление: буфер обмена, отладка, fallback."""

    @abstractmethod
    def render_docx(self, doc: DocxDoc) -> None:
        """Дописать себя в открытый docx-документ при экспорте."""
```

**Стандартные реализации (`core/blocks.py`):**

| Класс | Назначение | Что хранит |
|---|---|---|
| `TextBlock(text: str)` | Обычный текст | Строка |
| `FormulaBlock(latex: str)` | LaTeX-формула | LaTeX-исходник |
| `ImageBlock(image, caption="")` | Растровое изображение | `PIL.Image` или `bytes` |
| `CodeBlock(code: str, language="c")` | Листинг кода | Исходник + язык |
| `TableBlock(rows, header=None)` | Табличные данные | Список списков |

**Правило расширения.** Чтобы ввести новый тип контента (например, граф или интерактивную диаграмму), достаточно создать класс, наследующий `Block`, и реализовать три метода. Все существующие `View` и экспортёры подхватят его без правок.

### 3.2. `Task` — задание

```python
# core/task.py
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

class Task(ABC):
    """Маркерный базовый класс. Любой результат generate() — это Task."""
    meta: dict


@dataclass
class StaticTask(Task):
    """Задание формата 'условие → ответ'.
    Подходит для: матан, линал, физика, opvs (картинка + ответ)."""
    statement: list[Block]
    answer: list[Block]
    meta: dict = field(default_factory=dict)


class InteractiveTask(Task, ABC):
    """Задание-сессия с собственным циклом взаимодействия.
    Подходит для: тренажёров, диалоговых упражнений, пошаговых задач."""

    @abstractmethod
    def initial_prompt(self) -> list[Block]:
        """Что показать пользователю в начале сессии."""

    @abstractmethod
    def submit(self, user_input: str) -> "TurnResult":
        """Принять ответ пользователя и вернуть результат хода."""

    @abstractmethod
    def is_finished(self) -> bool:
        """Закончилась ли сессия."""


@dataclass
class TurnResult:
    correct: bool
    feedback: list[Block]            # реакция на ответ пользователя
    next_prompt: list[Block] | None  # следующий вопрос или None при завершении
```

**Соглашения:**
- `meta` — словарь со служебными данными: `partition_id`, имя раздела, оригинальные параметры генерации. Используется группами/тестами для связи с БД и для отладки.
- Контент в обоих ветках — **только** `list[Block]`. Никаких сырых строк или HTML.

### 3.3. `Capability` — флаги возможностей

```python
# core/generator.py
from enum import Flag, auto

class Capability(Flag):
    NONE        = 0
    STATIC      = auto()  # generate() возвращает StaticTask
    INTERACTIVE = auto()  # generate() возвращает InteractiveTask
    EXPORTABLE  = auto()  # имеет смысл выводить в .docx
    GROUPABLE   = auto()  # можно положить в группу или тест
    HAS_IMAGES  = auto()  # подсказка для UI: задание содержит ImageBlock
```

**Правила:**
- Один из `STATIC` / `INTERACTIVE` обязателен. Они взаимоисключающие.
- `INTERACTIVE` обычно не сочетается с `GROUPABLE` и `EXPORTABLE` — у диалоговых задач нет «готового» контента для группы или экспорта.
- `HAS_IMAGES` — оптимизационная подсказка: табличный вид расширяет колонку, экспортёр не пытается уместить картинку в строку.

### 3.4. `TaskGenerator` — модуль

```python
# core/generator.py
from abc import ABC, abstractmethod

class TaskGenerator(ABC):
    """Контракт модуля. Один файл — один класс, наследующий это."""

    name: str                                # человекочитаемое имя для UI
    partition_id: int | None = None          # привязка к строке БД (опционально)
    capabilities: Capability = (
        Capability.STATIC | Capability.GROUPABLE | Capability.EXPORTABLE
    )

    @abstractmethod
    def generate(self) -> Task:
        """Сгенерировать новое задание. Тип возврата согласован с capabilities."""

    def configure(self, params: dict) -> None:
        """Опционально: применить параметры из БД (поле generation_parametrs)."""
        pass
```

**Что обязано быть:**
- Атрибут `name`.
- Реализация `generate()`.
- Согласованность: если `capabilities` содержит `STATIC` — `generate()` возвращает `StaticTask`; если `INTERACTIVE` — `InteractiveTask`.

**Что опционально:**
- `partition_id` — нужен только если модуль привязан к существующей строке БД.
- `configure()` — нужен модулям-конструкторам, читающим параметры из БД.

---

## 4. Представления

```python
# core/views.py

class StaticTaskView(QWidget):
    """Один статичный таск: условие + кнопка 'показать ответ'.
    Перебирает блоки и зовёт у каждого render_qt."""
    def __init__(self, generator: TaskGenerator):
        assert Capability.STATIC in generator.capabilities


class TableTaskView(QWidget):
    """Таблица из N сгенерированных заданий с колонкой 'удалить'.
    Принимает любой STATIC-генератор."""
    def __init__(self, generator: TaskGenerator):
        assert Capability.STATIC in generator.capabilities


class InteractiveTaskView(QWidget):
    """Диалог: поле ввода + история ходов.
    Цикл: показать prompt → submit → показать feedback и next_prompt."""
    def __init__(self, generator: TaskGenerator):
        assert Capability.INTERACTIVE in generator.capabilities


class TestExportView(QWidget):
    """Тест с настройками отображения ответов и кнопкой экспорта в Word.
    Принимает только генераторы с EXPORTABLE."""
    def __init__(self, generator: TaskGenerator):
        assert Capability.EXPORTABLE in generator.capabilities
```

**Правило:** в `View` запрещено `isinstance(task, ...)`. Каждый view знает ровно один тип задачи.

---

## 5. Композитные генераторы

```python
class GroupGenerator(TaskGenerator):
    """Группа из других генераторов. Сам по себе — обычный TaskGenerator."""
    capabilities = Capability.STATIC | Capability.EXPORTABLE

    def __init__(self, children: list[TaskGenerator]):
        self.children = [c for c in children
                         if Capability.GROUPABLE in c.capabilities]
        if not self.children:
            raise ValueError("В группу не попал ни один групповой генератор")

    def generate(self) -> StaticTask:
        return random.choice(self.children).generate()


class TestGenerator(TaskGenerator):
    """Тест: упорядоченная последовательность заданий с заданными количествами."""
    capabilities = Capability.STATIC | Capability.EXPORTABLE

    def __init__(self, items: list[tuple[TaskGenerator, int]]):
        # items = [(generator, count), ...]
        for gen, _ in items:
            assert Capability.GROUPABLE in gen.capabilities
        self.items = items

    def generate(self) -> StaticTask:
        statement, answer = [], []
        n = 1
        for gen, count in self.items:
            for _ in range(count):
                t = gen.generate()
                statement.append(TextBlock(f"{n}) "))
                statement.extend(t.statement)
                answer.append(TextBlock(f"{n}) "))
                answer.extend(t.answer)
                n += 1
        return StaticTask(statement=statement, answer=answer)
```

Группы и тесты не знают, какой предмет у их детей. Они работают на уровне `TaskGenerator` → `StaticTask` → `Block`. Английский (интерактивный) физически не попадает в их состав благодаря фильтру по `GROUPABLE`.

---

## 6. Реестр и точка входа

```python
# core/registry.py
class GeneratorRegistry:
    def __init__(self):
        self._by_partition: dict[int, TaskGenerator] = {}

    def register(self, generator: TaskGenerator) -> None:
        if generator.partition_id is not None:
            self._by_partition[generator.partition_id] = generator

    def get(self, partition_id: int) -> TaskGenerator:
        return self._by_partition[partition_id]
```

```python
# pycode/windows/generator.py — упрощённый GeneratorWindow
def open_partition(self, partition_id: int):
    gen = self.registry.get(partition_id)
    view_kind = self.repo.get_view_kind(partition_id)  # 'single' | 'table' | 'test'

    if Capability.INTERACTIVE in gen.capabilities:
        view = InteractiveTaskView(gen)
    elif view_kind == "table":
        view = TableTaskView(gen)
    elif view_kind == "test":
        view = TestExportView(gen)
    else:
        view = StaticTaskView(gen)

    self._set_central_widget(view)
```

Это весь роутинг. Никакого знания о предметах.

---

## 7. Примеры адаптации существующих модулей

### 7.1. Матан (формулы LaTeX)

```python
# pycode/exercises/matan/diff/just_diff_gen.py
from pycode.exercises.matan.diff.just_diff import get_just_diff
from core import TaskGenerator, StaticTask, TextBlock, FormulaBlock

def _to_block(tup):
    kind, content = tup
    return TextBlock(content) if kind == "text" else FormulaBlock(content)

class JustDiffGenerator(TaskGenerator):
    name = "Обычные производные"
    partition_id = 40
    # capabilities = STATIC | GROUPABLE | EXPORTABLE — из дефолта

    def generate(self) -> StaticTask:
        desc, cond, ans = get_just_diff()
        return StaticTask(
            statement=[_to_block(desc), _to_block(cond)],
            answer=[_to_block(ans)],
            meta={"partition_id": self.partition_id},
        )
```

Существующая функция `get_just_diff` не меняется. Адаптер — 10 строк.

### 7.2. opvs (картинка + ответ)

```python
# pycode/exercises/opvs/circuit_gen.py
from pycode.exercises.opvs.png_generator import make_function, draw_circuit_to_image
from core import TaskGenerator, StaticTask, Capability, TextBlock, ImageBlock

class LogicCircuitGenerator(TaskGenerator):
    name = "Логическая схема"
    capabilities = (
        Capability.STATIC | Capability.GROUPABLE
        | Capability.EXPORTABLE | Capability.HAS_IMAGES
    )

    def generate(self) -> StaticTask:
        elements = make_function()
        image = draw_circuit_to_image(elements)   # PIL.Image, не файл
        formula = elements[-1].get_logic_str()
        return StaticTask(
            statement=[
                TextBlock("Постройте таблицу истинности для приведённой схемы."),
                ImageBlock(image, caption="Логическая схема"),
            ],
            answer=[TextBlock(f"Логическая функция: {formula}")],
        )
```

Требуется минимальная доработка `png_generator.py`: разделить `draw_circuit` на «нарисовать в `PIL.Image`» и «сохранить в файл». Картинка живёт в памяти и упаковывается в `ImageBlock`.

### 7.3. Английский (интерактивная сессия)

```python
# pycode/exercises/english/words_gen.py
import json
from core import TaskGenerator, InteractiveTask, TurnResult, Capability, TextBlock

class WordsTrainerGenerator(TaskGenerator):
    name = "Тренажёр английских слов"
    capabilities = Capability.INTERACTIVE   # не GROUPABLE, не EXPORTABLE

    def __init__(self, semester_file: str):
        self.semester_file = semester_file

    def generate(self) -> InteractiveTask:
        return WordsSession(self.semester_file)


class WordsSession(InteractiveTask):
    def __init__(self, semester_file: str):
        with open(semester_file, encoding="utf-8") as f:
            self.words = json.load(f)
        self.current = None

    def initial_prompt(self):
        self.current = self._pick()
        return [TextBlock(f"Переведите: {self.words[self.current]}")]

    def submit(self, user_input: str) -> TurnResult:
        ok = user_input.strip().lower() == self.current.lower()
        feedback = [TextBlock(("✓ " if ok else "✗ ") + self.current)]
        if ok:
            self.words.pop(self.current)
        if not self.words:
            return TurnResult(ok, feedback, None)
        self.current = self._pick()
        return TurnResult(ok, feedback, [TextBlock(f"Переведите: {self.words[self.current]}")])

    def is_finished(self) -> bool:
        return not self.words
```

Английский не наследует `StaticTask` и не пытается выдавать «готовое задание». Он живёт в `InteractiveTaskView`, который подбирается каркасом по флагу `INTERACTIVE` и в группы/тесты не попадает по фильтру `GROUPABLE`.

---

## 8. Чек-лист добавления нового модуля

1. **Контент.** Хватает ли существующих блоков? Если нужен новый тип (граф, диаграмма, аудио) — создать класс, наследующий `Block`, с тремя методами рендера. Это единственный случай, когда правится ядро.
2. **Природа задания.** Готовое условие+ответ → `StaticTask`. Интерактивная сессия → подкласс `InteractiveTask`.
3. **Класс генератора.** Наследовать `TaskGenerator`. Указать `name`, при необходимости `partition_id`. Установить `capabilities`. Реализовать `generate()`.
4. **Регистрация.** Одна строка в стартовой инициализации реестра.
5. **БД.** Добавить запись в `Partitions`, если модуль завязан на БД. Поле `view_kind` определяет, какой `View` использовать (`single` / `table` / `test`).

**Что не нужно делать:**
- Править `GeneratorWindow`.
- Править `GroupGenerator` / `TestGenerator`.
- Править экспортёры.
- Создавать собственные `View`-классы (если только не вводится принципиально новый режим взаимодействия).

---

## 9. Гарантии стандарта

- **Полиморфизм представлений.** `StaticTaskView` рисует и LaTeX матана, и PNG opvs, и текст линала — потому что зовёт `block.render_qt()` у каждого блока, не зная их типов.
- **Полиморфизм экспорта.** `TestExportView` собирает Word-документ из любых статичных задач, не различая предметы.
- **Безопасная композиция.** Интерактивные модули физически не могут попасть в группу или тест: фильтр по `GROUPABLE` отсекает их на этапе создания композита.
- **Изолированное расширение.** Добавление нового предмета — N файлов в `pycode/exercises/<новый_предмет>/` плюс N строк регистрации. Ноль изменений в ядре.
- **Прозрачная миграция.** Существующие функции-генераторы (`get_just_diff`, `make_function`, `get_exercise`) не переписываются — оборачиваются тонкими адаптерами в `TaskGenerator`.

---

## 10. Что остаётся за рамками стандарта

Стандарт описывает контракт между модулями, ядром и UI. Намеренно не специфицирует:

- Реализацию `_latex_to_qlabel`, `_pil_to_qpixmap`, `_insert_latex_into_docx` — это инфраструктурный код, который пишется один раз и переиспользуется.
- Конкретные SQL-запросы и схему БД — слой репозитория за пределами стандарта.
- Стилизацию виджетов — это задача `View`, а не контракта.
- Логику восстановления сессий, кеширования, фоновой генерации — это ортогональные задачи, которые можно встроить, не ломая стандарт.

---

## 11. Редакторы разделов (для разделов с конфигом в БД)

Часть разделов хранит свою конфигурацию прямо в БД (поле `generation_parametrs`):
группы, тесты, конструкторы. Чтобы пользователь мог их создавать и менять
через UI, вводится параллельный стандарт — `PartitionEditor`.

### Контракт

```python
class PartitionEditor(QWidget):
    saved = pyqtSignal(int)         # испускается с partition_id после успеха
    cancelled = pyqtSignal()

    def __init__(self, repository, subject_id, partition_id=None, ...):
        # partition_id is None  → режим создания
        # partition_id is int   → режим редактирования

    @abstractmethod
    def load_existing(self) -> None:
        """Заполнить форму данными существующего раздела."""

    @abstractmethod
    def collect_payload(self) -> tuple[str, int, dict | list]:
        """(name, constracted, generation_params) или ValueError."""

    def save(self) -> int | None:
        """Базовый метод: зовёт collect_payload и пишет в БД через Repository."""
```

### Связь с генераторами

Редактор и генератор — **независимые** сущности:
* Генератор читает из БД (через `Repository` и `Capability`-флаги).
* Редактор пишет в БД (через `Repository.upsert_partition`).
* Между ними нет прямых зависимостей.

После сохранения главное окно зовёт `registry_builder()` — фабрику,
которая пересобирает `GeneratorRegistry` с обновлёнными данными из БД.
Уже открытые `View` не страдают, потому что у них в руках свой генератор.

### Привязка редактора к разделу

`Repository.editor_kind_for(partition)` отдаёт строку:
* `"group"` — группа (constracted=2)
* `"test"` — тест (constracted=3)
* `"fisic"` — физический конструктор (constracted=1)
* `None` — раздел не редактируется через UI

Это единственное место, где `constracted` ↔ редактор. Добавление нового
редактируемого типа = одна строка в `EDITOR_KIND_BY_CONSTRACTED` и
один новый класс, наследующий `PartitionEditor`.

### Что даёт стандарт редакторов

* **Главное окно не знает о редакторах.** Оно зовёт `create_editor(kind, ...)`
  и подключает два сигнала. Логика — внутри редактора.
* **Изоморфизм со стандартом генераторов.** Создание нового типа
  редактируемого раздела проходит по той же схеме: один файл, один класс,
  одна регистрация.
* **Никакого обхода стандарта генераторов.** Всё, что делает редактор —
  пишет в БД. Стандарт `TaskGenerator` остаётся в силе: при следующем
  чтении из БД его подхватит фабрика в реестре.

---

## 12. Динамические блоки

Не все блоки — статичный текст. Бывает, что блок должен **взаимодействовать
с пользователем внутри статичного задания**: поля ввода, кнопки переключения,
интерактивные элементы. Стандарт это поддерживает без изменений: динамический
блок — это обычный `Block`, у которого `render_qt()` возвращает виджет
с полями ввода или другой интерактивностью.

### Пример: `FillInTheBlankBlock`

Принимает шаблон с маркерами `___` и список правильных ответов:

```python
FillInTheBlankBlock(
    template="The CPU ___ instructions and ___ them.",
    answers=["fetches", "executes"]
)
```

Поведение в трёх средах:
* **`render_qt`**: текст с встроенными `QLineEdit`, по мере набора подсвечивает
  правильность зелёным/красным.
* **`render_plain`**: пропуски замещаются ответами в подчёркиваниях
  (`"The CPU _fetches_ instructions and _executes_ them."`).
* **`render_docx`**: пропуски замещаются ответами курсивом — задание остаётся
  читаемым в Word с подсвеченным правильным заполнением.

### Когда использовать

Динамический блок — это **не** замена `InteractiveTask`. У них разные
жизненные циклы:

| Сценарий | Использовать |
|---|---|
| Цикл «спроси → ответь → следующее задание» | `InteractiveTask` |
| Внутри одного статичного задания нужен ввод | Динамический `Block` |
| Подсветка/проверка прямо при наборе | Динамический `Block` |
| Долгая сессия с накоплением счёта | `InteractiveTask` |

Динамический блок — часть `StaticTask` со всеми его свойствами:
он `GROUPABLE`, `EXPORTABLE`, попадает в группы и тесты, корректно
экспортируется в Word. Только в Qt-режиме он умеет реагировать на ввод.

### Создание своего динамического блока

Тот же контракт `Block`, что и у статичных:

```python
class MyDynamicBlock(Block):
    def render_qt(self, parent):
        # Создать виджет с интерактивностью
        return widget_with_inputs

    def render_plain(self):
        # Текстовое представление с правильным контентом
        return "..."

    def render_docx(self, doc):
        # Запись в Word: тоже с правильным контентом
        doc.add_paragraph("...")
```

Главное правило: в `plain` и `docx` блок должен показать **правильно
заполненный результат**. Без этого экспортированное задание потеряет смысл.
