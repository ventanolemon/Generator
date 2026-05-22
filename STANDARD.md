# Стандарт модулей генератора заданий

Документ описывает архитектурный стандарт для системы, генерирующей учебные задания
по разным дисциплинам и выводящей их в нескольких представлениях. Цель стандарта —
**полиморфизм**: добавление нового предмета, нового типа задания или нового вида
контента не требует правки ядра, групп, тестов, представлений или экспортёров.

Документ — самодостаточный референс для разработчиков. Ниже описаны все ключевые
сущности, их контракты, точки расширения, известные особенности и тонкости работы
системы. Он же используется как контекст-промпт для AI-агентов, работающих над
проектом.

---

## 1. Принципы

1. **Ядро не знает о предметах.** Главное окно, реестр, группы, тесты, экспортёры
   и редакторы работают только с абстракциями `TaskGenerator`, `Task`, `Block`,
   `Capability`. Конструкции вида `if subject == "..."` в ядре запрещены.

2. **Контент — это список типизированных блоков, не строка.** Каждый блок умеет
   рендериться в трёх средах: Qt-виджет (UI), plain text (буфер обмена, fallback),
   docx (экспорт в Word). Новый тип контента — новый класс с тремя методами,
   и всё ядро автоматически с ним совместимо.

3. **У задания две природы — статичная и интерактивная.** `StaticTask` — готовое
   условие+ответ. `InteractiveTask` — сессия со своим циклом «спроси-проверь».
   Обе наследуют общий маркер `Task`, но имеют разные интерфейсы.

4. **Генератор декларирует свои возможности.** Через флаги `Capability` модуль
   сообщает, какие представления, режимы (группы, тесты, экспорт) ему применимы.
   Каркас опирается на эти флаги, а не на знание классов.

5. **Композиция вместо наследования.** Группы и тесты — обычные `TaskGenerator`,
   принимающие список других генераторов. Они не знают о предметах детей.

6. **Один модуль — один файл — один класс.** Минимальный модуль состоит из
   функции-генератора, класса-обёртки `TaskGenerator` и одной строки регистрации
   в bootstrap.

7. **Sync БД при старте.** Все code-only генераторы автоматически создают записи
   в таблице `Partitions` при первом запуске. Bootstrap — единственный источник
   правды о привязке генераторов к предметам.

---

## 2. Архитектурные слои

```
UI                    StaticTaskView   TableTaskView   InteractiveTaskView   TestExportView
                              ↑               ↑                ↑                    ↑
Редакторы             GroupEditor    TestEditor    FisicEditor   (PartitionEditor)
                              ↘               ↘                ↘
Композиты              GeneratorRegistry  •  GroupGenerator  •  TestGenerator
                                              ↑
Bootstrap              sync_database()  •  build_registry()
                                              ↑
Доменные модули        matan / linal / fisic / opvs / english / ...
                                              ↑                          реализуют
Ядро                   TaskGenerator (контракт)  →  Task: StaticTask | InteractiveTask
                                                            ↑ содержат
                                              Block: TextBlock | FormulaBlock | ImageBlock |
                                                     CodeBlock | TableBlock | FillInTheBlankBlock | ...
```

Каждый слой знает только тот, что ниже. UI не знает про доменные модули;
группы и тесты не знают про предметы; модули не знают про UI; редакторы
пишут в БД, не зная, что с ней потом сделают генераторы.

---

## 3. Контракты ядра

### 3.1. `Block` — единица контента

```python
# core/content.py
class Block(ABC):
    @abstractmethod
    def render_qt(self, parent: QWidget) -> QWidget: ...

    @abstractmethod
    def render_plain(self) -> str: ...

    @abstractmethod
    def render_docx(self, doc: DocxDoc) -> None: ...
```

**Стандартные блоки (`core/blocks.py`):**

| Класс | Назначение | Что хранит |
|---|---|---|
| `TextBlock(text)` | Обычный текст | Строка |
| `FormulaBlock(latex)` | LaTeX-формула, рендерится через matplotlib mathtext | LaTeX-исходник |
| `ImageBlock(image, caption="")` | Растровое изображение | `PIL.Image`, `bytes` или путь |
| `CodeBlock(code, language="text")` | Листинг кода с моноширинным шрифтом | Исходник + язык |
| `TableBlock(rows, header=None)` | Табличные данные | Список списков |

**Динамические блоки (`core/dynamic_blocks.py`):**

| Класс | Назначение |
|---|---|
| `FillInTheBlankBlock(template, answers, on_change=None)` | Шаблон с маркерами `___`. В Qt → поля ввода с подсветкой по мере набора. В plain/docx → ответы курсивом. |

**Правило расширения.** Любой класс, наследующий `Block` и реализующий три
метода рендера, автоматически работает во всех представлениях и экспортёрах.
Это и есть основной механизм полиморфизма проекта.

### 3.2. `Task` — задание

```python
# core/task.py
class Task(ABC):
    """Маркер для типизации."""
    meta: dict


@dataclass
class StaticTask(Task):
    statement: list[Block]
    answer:    list[Block]
    meta:      dict = field(default_factory=dict)


@dataclass
class TurnResult:
    correct:     bool
    feedback:    list[Block]
    next_prompt: list[Block] | None      # None → сессия завершена


class InteractiveTask(Task, ABC):
    @abstractmethod
    def initial_prompt(self) -> list[Block]: ...

    @abstractmethod
    def submit(self, user_input: str) -> TurnResult: ...

    @abstractmethod
    def is_finished(self) -> bool: ...
```

`meta` — словарь со служебными данными: `partition_id`, имя раздела, исходные
параметры. Ядром не интерпретируется, используется группами/тестами/отладкой.

### 3.3. `Capability` — флаги возможностей

```python
# core/generator.py
class Capability(Flag):
    NONE        = 0
    STATIC      = auto()  # generate() возвращает StaticTask
    INTERACTIVE = auto()  # generate() возвращает InteractiveTask
    EXPORTABLE  = auto()  # имеет смысл выводить в .docx
    GROUPABLE   = auto()  # можно положить в группу или тест
    HAS_IMAGES  = auto()  # подсказка для UI: задание содержит ImageBlock

STATIC_DEFAULT = STATIC | GROUPABLE | EXPORTABLE
```

**Правила сочетаемости:**
* Один из `STATIC` / `INTERACTIVE` обязателен. Они взаимоисключающие.
* `INTERACTIVE` обычно не сочетается с `GROUPABLE` и `EXPORTABLE` — у диалоговых
  задач нет «готового» контента для группы или экспорта.
* `HAS_IMAGES` — оптимизационная подсказка, не ограничение.

### 3.4. `TaskGenerator` — модуль

```python
class TaskGenerator(ABC):
    name: str = ""                     # человекочитаемое имя
    partition_id: int | None = None    # id записи в Partitions
    capabilities: Capability = STATIC_DEFAULT

    @abstractmethod
    def generate(self) -> Task: ...

    def configure(self, params: dict) -> None:
        """Применить параметры из БД (поле generation_parametrs).
        По умолчанию — игнорировать."""
```

**Обязательно:**
* `name` (для отображения в UI и сообщений об ошибках).
* `generate()`, согласованный с `capabilities`.

**Опционально:**
* `partition_id` — если модуль привязан к строке БД.
* `configure()` — для модулей-конструкторов с параметрами из БД.

### 3.5. `Repository` — доступ к БД

```python
class Repository:
    def list_subjects() -> list[Subject]
    def list_partitions_for_subject(subject_id: int) -> list[Partition]
    def get_partition(partition_id: int) -> Partition | None

    def view_kind_for(partition: Partition) -> str            # 'single'|'table'|'test'
    def editor_kind_for(partition: Partition) -> str | None   # 'group'|'test'|'fisic'|None

    # Запись (используется редакторами и sync_database)
    def upsert_partition(subject_id, name, constracted, generation_params) -> int
    def delete_partition(partition_id: int) -> None
    def ensure_subject(subject_id, name, parent_name=None) -> int
    def ensure_code_partition(partition_id, subject_id, name) -> None
```

Все запросы параметризованы. Никакого `f"SELECT ... WHERE id = {x}"` в коде.

`generation_parametrs` хранится в БД как JSON-строка. Repository парсит её в
`dict` (или нормализует list в `{"data": [...]}`). Не-JSON содержимое попадает
под ключ `"raw"`.

### 3.6. `GeneratorRegistry` — реестр модулей

```python
class GeneratorRegistry:
    def register(generator)                                 # готовый экземпляр
    def register_factory(partition_id, factory)             # фабрика
    def get(partition_id, params=None) -> TaskGenerator
    def has(partition_id) -> bool
    def all_ids() -> list[int]
```

Реестр — единственный канал связи между БД и доменными модулями. UI берёт
генератор только через реестр. После любого изменения БД (редакторы) реестр
пересобирается через `registry_builder()` в `GeneratorWindow`.

---

## 4. Четыре типа разделов (значения `constracted`)

Поле `Partitions.constracted` определяет, что это за раздел и какое
представление + редактор к нему применимы:

| `constracted` | Тип раздела | Источник конфига | View | Editor |
|---|---|---|---|---|
| `0` | Code-only генератор | Код Python | `StaticTaskView` (или `InteractiveTaskView`) | — |
| `1` | Конструктор физики | `generation_parametrs` (JSON) | `TableTaskView` | `FisicEditor` |
| `2` | Группа | `generation_parametrs` (список task_id) | `TableTaskView` | `GroupEditor` |
| `3` | Тест | `generation_parametrs` (список task_id + count) | `TestExportView` | `TestEditor` |

Эта таблица — **единственное место**, где `constracted` ↔ тип раздела связаны.
Маппинг живёт в `Repository.EDITOR_KIND_BY_CONSTRACTED` и `_VIEW_KIND_BY_CONSTRACTED`.

---

## 5. Представления

```python
# ui/views/

class StaticTaskView:           # одно задание + кнопка ответа + (опц.) кнопка экспорта
    requires:  Capability.STATIC
    extras:    Capability.EXPORTABLE → кнопка «Экспорт в Word» для текущего задания

class TableTaskView:            # накопление N задач в таблице, экспорт списком
    requires:  Capability.STATIC

class InteractiveTaskView:      # диалог: prompt → submit → next_prompt
    requires:  Capability.INTERACTIVE

class TestExportView:           # N вариантов теста в табах, экспорт всех в один docx
    requires:  Capability.EXPORTABLE
```

**Правило подбора в `GeneratorWindow._pick_view`:**

```python
if INTERACTIVE in caps:        return InteractiveTaskView      # имеет приоритет
elif view_kind == "table":     return TableTaskView
elif view_kind == "test":      return TestExportView
else:                          return StaticTaskView
```

`view_kind` приходит от `Repository.view_kind_for(partition)` и определяется
по `constracted`. `INTERACTIVE` побеждает любой `view_kind` — диалоговая
сессия не может быть таблицей.

**В `View` запрещено `isinstance(task, ...)`**. Каждый view знает ровно один
тип задачи и работает только с ним.

---

## 6. Редакторы разделов

Редакторы — параллельный стандарт для разделов, чья конфигурация хранится в БД
(constracted ∈ {1, 2, 3}). Они **не наследуют** ничего от стандарта генераторов
и **не вызывают** генераторы напрямую — связь только через БД.

```python
class PartitionEditor(QWidget):
    saved     = pyqtSignal(int)        # partition_id после успеха
    cancelled = pyqtSignal()

    @abstractmethod
    def load_existing(self) -> None: ...

    @abstractmethod
    def collect_payload(self) -> tuple[str, int, dict | list]: ...
            # (name, constracted, generation_params); ValueError при ошибке валидации

    def save(self) -> int | None:
        """Базовый: collect_payload → upsert_partition → emit saved."""
```

**Готовые редакторы:**

* `GroupEditor` — список с чекбоксами разделов того же предмета (без других групп).
  Серым/некликабельным помечает INTERACTIVE-разделы (они не GROUPABLE).
* `TestEditor` — упорядоченная таблица `(тип, count)` с кнопками `↑ ↓ ×`.
  Включает разделы родственных предметов через `pra_subject`.
* `FisicEditor` — текст условия с маркерами `#var#`, кнопки/таблица для переменных.
  Парсит `#var#` из условия и автоматически синхронизирует таблицу переменных.

**Создание нового редактора:**
1. Класс, наследующий `PartitionEditor`.
2. Запись в `Repository.EDITOR_KIND_BY_CONSTRACTED`.
3. Ветка в `ui/editors/__init__.create_editor()`.

**После сохранения** `GeneratorWindow` зовёт `registry_builder()` — фабрику,
пересобирающую `GeneratorRegistry`. Уже открытые `View` продолжают работать
со своим генератором (он у них в руках), новые клики идут к свежему реестру.

---

## 7. Bootstrap: sync БД и build_registry

`bootstrap.py` — единственное место в проекте, где явно указано, к какому
предмету относится каждый code-only генератор.

### 7.1. `CODE_GENERATORS` — таблица code-генераторов

```python
CODE_GENERATORS = [
    (subject_id, generator_instance),
    ...
]
```

Каждый элемент — пара «id предмета, экземпляр генератора». Это источник правды
для `sync_database`.

### 7.2. `sync_database(repo, words_dir)`

Вызывается **до** `build_registry`. Гарантирует:
* существование всех нужных subjects (через `repo.ensure_subject`)
* существование записей в `Partitions` для всех code-генераторов
  (через `repo.ensure_code_partition`)
* регистрацию английских словарей под `partition_id` 1000+i

`ensure_code_partition` обновляет `subject_id` и `name` для существующих записей
с `constracted=0`, но не трогает группы/тесты/конструкторы — это страховка
от перезатирания пользовательских данных.

### 7.3. `build_registry(repo, words_dir)`

Собирает реестр в три шага:

1. **Code-генераторы** из `CODE_GENERATORS` регистрируются по `partition_id`.
2. **Английские словари** в `words_dir` регистрируются с `partition_id = 1000+i`,
   тип определяется по содержимому JSON.
3. **БД**: проход по всем `Partitions`. Для записей с `constracted ∈ {1, 2, 3}`,
   которых ещё нет в реестре, регистрируются фабрики (физический конструктор,
   группа, тест).

Результат — полностью собранный реестр со всеми доступными генераторами.

---

## 8. Группы и тесты как композитные генераторы

```python
class GroupGenerator(TaskGenerator):
    capabilities = STATIC | EXPORTABLE | GROUPABLE  # группа сама может попасть в тест

    def __init__(self, name, children: list[TaskGenerator], partition_id=None):
        self.children = [c for c in children if GROUPABLE in c.capabilities]
        # Фильтр гарантирует: INTERACTIVE-генераторы автоматически отсекаются

    def generate(self) -> StaticTask:
        return random.choice(self.children).generate()


class TestGenerator(TaskGenerator):
    capabilities = STATIC | EXPORTABLE

    def __init__(self, name, items: list[tuple[TaskGenerator, int]], partition_id=None):
        # items = [(generator, count), ...]

    def generate(self) -> StaticTask:
        # Разворачивает: для каждого (gen, count) → count раз gen.generate()
        # Все статичные задания склеиваются в один большой StaticTask с нумерацией.
```

**Тонкости тестов:**
* В БД count хранится под ключом `task_cnt` (legacy от старого `TestAdder`),
  иногда как строка (`"0"`, `"1"`). Bootstrap нормализует через `int()`
  с try/except и игнорирует записи с `count <= 0`.
* В тест можно положить разделы своего предмета и **родственных**
  (с тем же `pra_subject`). Это сделано для физики, где есть подпредметы
  «Кинематика», «СCУАР» под общим «Физика».

---

## 9. Все типы заданий — обзор по технологии

В проекте присутствуют пять разных подходов к созданию заданий, демонстрирующие
разные сценарии работы со стандартом:

### 9.1. Текст + текст (линал)
```python
class Linal2DGenerator(TaskGenerator):
    name = "Задания на 2D плоскость"
    partition_id = 1
    capabilities = STATIC_DEFAULT

    def generate(self) -> StaticTask:
        text, answer = ex2_d.get_exercise()         # legacy: (str, str)
        return StaticTask(
            statement=[TextBlock(text)],
            answer=[TextBlock(answer)],
        )
```
Простейший случай. Адаптер на 5 строк.

### 9.2. Смесь текста и формул (матан)
```python
class JustDiffGenerator(_LegacyMatanAdapter):
    name = "Обычные производные"
    partition_id = 40
    _legacy_func = staticmethod(get_just_diff)
    # _wrap_legacy умеет в (("text"|"formula", content), ...)
```
Базовый класс `_LegacyMatanAdapter` обрабатывает старый формат
`((kind, content), ...)` — `kind ∈ {"text", "formula"}`. 8 типов в `diff/`,
13 в `limits/`.

### 9.3. Параметризованный конструктор (физика)

Физика — единственный модуль с богатой архитектурой внутри. Один класс
`FisicConstructorGenerator` обслуживает все физические разделы, а вся
логика генерации разнесена по слоям:

```
exercises/fisic/
├── expression.py     # Парсер и калькулятор формул на AST (безопасный, без eval)
├── generation.py     # VariableSpec и generate_value: натуральные/целые/real, шаги, forbidden
├── constraints.py    # ResultConstraint: ограничения на результат
├── formatting.py     # Единое форматирование чисел (научная нотация, целые, дроби)
├── fisic_generater.py  # generate_task: координирует всё, делает попытки до выполнения ограничений
└── generators.py     # FisicConstructorGenerator — обёртка для интеграции с реестром
```

**Особенности удобной нотации в формулах:**
* `^` → `**` (степень)
* `√(x)`, `√x` → `sqrt(x)`
* `π` → `pi`
* В диапазонах переменных (`min`/`max`) тоже допускаются формулы:
  `"min": "10^3"`, `"max": "2*pi"`, `"max": "sqrt(2)"`.

**Ограничения переменной (`VariableSpec`):**

```python
"variables": {
    "n":     {"min": 1, "max": 100, "kind": "natural"},                  # 1, 2, 3, ...
    "k":     {"min": -10, "max": 10, "kind": "integer"},                 # -10..10
    "v":     {"min": 0.5, "max": 5.0, "kind": "real", "decimals": 2},    # 0.50, 1.23, 4.99
    "even":  {"min": 2, "max": 30, "kind": "integer", "step": 2},        # только чётные
    "tenths":{"min": 0, "max": 1, "kind": "real", "step": 0.1},          # 0, 0.1, ..., 1.0
    "noZero":{"min": -5, "max": 5, "kind": "integer", "forbidden": [0]}, # без нуля
}
```

`kind`:
* `"natural"` — натуральные ≥ 1.
* `"integer"` — любые целые.
* `"real"` — действительные с округлением до `decimals` (по умолчанию 2).
* `"auto"` — старое поведение для обратной совместимости (целое если диапазон ≥ 1).

`step` — шаг сетки. Для `natural`/`integer` по умолчанию 1.

**Ограничения на результат (`ResultConstraint`):**

```python
"result": {
    "kind": "natural",        # natural | integer | real
    "min": 1,                 # опционально
    "max": 1000,              # опционально
    "tolerance": 1e-9         # опционально, допуск при проверке целочисленности
}
```

Если результат не удовлетворяет ограничениям, генератор **переподбирает значения
переменных** (до `max_attempts` раз). Это позволяет автоматически генерировать
задачи вида «количество страниц», «делится нацело», «положительное число»
и т.п. без ручного подбора диапазонов.

**Безопасность.** Формула парсится в AST и проверяется: разрешены только
арифметические операторы, скобки, фиксированный набор функций (sin, cos, sqrt,
log, exp и др.) и константы. Любые попытки доступа к атрибутам, импорта,
обращения к встроенным функциям отвергаются ещё до генерации.

**Физические константы** доступны в формулах без явного объявления: `g`
(ускорение свободного падения), `G` (гравитационная), `c` (скорость света),
`h` (Планка), `k_B` (Больцмана), `N_A` (Авогадро), `R_g` (универсальная газовая).
Пользователь может перекрыть их своей переменной с тем же именем.

**Базовый код-генератор** `generate_fisic_task(config)` принимает JSON-строку
или dict, возвращает `(condition, solution)`. Для нового кода рекомендуется
использовать `generate_task(config) -> FisicTask`, у которой больше метаданных
(сами значения, числовой результат, использованная формула).

### 9.4. Изображение + текст (opvs)
```python
class LogicCircuitGenerator(TaskGenerator):
    name = "Логическая схема"
    capabilities = STATIC | GROUPABLE | EXPORTABLE | HAS_IMAGES

    def generate(self) -> StaticTask:
        elements = make_function()
        image = render_circuit(elements)         # PIL.Image, без сохранения
        formula = elements[-1].get_logic_str()
        return StaticTask(
            statement=[TextBlock("Постройте таблицу истинности..."),
                       ImageBlock(image, caption="Логическая схема")],
            answer=[TextBlock(f"Логическая функция: {formula}")],
        )
```
Картинка в памяти как `PIL.Image`. В Qt → конвертится в `QPixmap`,
в docx → пишется через `BytesIO`. Файл на диске не появляется.

В `png_generator.py` функция `draw_circuit` была разделена на `render_circuit`
(возвращает PIL.Image) и `draw_circuit` (старый API, теперь делегирует).
Это **единственная** правка в оригинальных функциях-генераторах.

### 9.5. Интерактивная сессия (английский — словарь)
```python
class WordsTrainerGenerator(TaskGenerator):
    capabilities = Capability.INTERACTIVE     # не GROUPABLE, не EXPORTABLE

    def generate(self) -> InteractiveTask:
        return WordsSession(self._load(), self.session_size)


class WordsSession(InteractiveTask):
    def initial_prompt(self) -> list[Block]: ...
    def submit(self, user_input: str) -> TurnResult: ...
    def is_finished(self) -> bool: ...
```
`WordsSession` хранит состояние (оставшиеся слова, текущее). При исчерпании
сессии возвращает `TurnResult(next_prompt=None)` — `InteractiveTaskView`
показывает экран «сессия завершена».

### 9.6. Динамический блок (английский — пропуски)
```python
class SentenceFillGenerator(TaskGenerator):
    capabilities = STATIC_DEFAULT       # обычная статичная задача!

    def generate(self) -> StaticTask:
        item = random.choice(self._load())
        return StaticTask(
            statement=[
                TextBlock("Вставьте пропущенные слова в предложение:"),
                FillInTheBlankBlock(template=item["template"],
                                    answers=item["answers"]),
            ],
            answer=[TextBlock(...правильное предложение...)],
        )
```
**Ключевое наблюдение:** интерактивность не обязательно требует `InteractiveTask`.
Если она локальна (внутри одного задания), достаточно динамического `Block`.
Задание остаётся `STATIC`, попадает в группы/тесты, экспортируется в Word.

В Qt-режиме `FillInTheBlankBlock` рисует поля ввода прямо в условии и
подсвечивает зелёным/красным по мере набора. В docx — заменяет пропуски
ответами курсивом.

---

## 10. Когда `Block`, когда `InteractiveTask`?

Развилка возникает каждый раз, когда есть интерактивный элемент. Правило:

| Сценарий | Использовать |
|---|---|
| Цикл «спроси-ответь-следующее» | `InteractiveTask` |
| Ввод/проверка локально внутри одного задания | Динамический `Block` |
| Подсветка по мере набора | Динамический `Block` |
| Долгая сессия с накоплением счёта/прогресса | `InteractiveTask` |
| Хочется попадать в группы и тесты | Динамический `Block` |
| Нужен экспорт в Word | Динамический `Block` |

Динамический блок — часть `StaticTask` со всеми его свойствами.
Только в Qt-режиме он умеет реагировать на ввод; в plain/docx он показывает
правильно заполненный результат.

---

## 11. Как добавить новый предмет

### Шаг 1. Решить, какой это вид задания

* Есть готовая функция `f() → (text, answer)` → подойдёт обёртка как у линала.
* Функция возвращает `((kind, content), ...)` → шаблон матана.
* JSON-конфиг с переменными → конструктор как у физики.
* Есть картинка → `ImageBlock` с PIL.Image, как у opvs.
* Цикл диалога → `InteractiveTask`, как у английского-словаря.
* Локальный ввод/проверка → новый или существующий динамический `Block`,
  как у sentence-fill.

### Шаг 2. Создать структуру файлов

```
exercises/<предмет>/
├── __init__.py            # экспорт all_generators
├── <legacy_module>.py     # оригинальные функции (могут быть несколько)
└── generators.py          # классы-адаптеры TaskGenerator
```

### Шаг 3. Реализовать адаптер

```python
# exercises/<предмет>/generators.py
from core import TaskGenerator, StaticTask, TextBlock, STATIC_DEFAULT

class MyGenerator(TaskGenerator):
    name = "Моё задание"
    partition_id = 99            # уникальный, не пересекающийся
    capabilities = STATIC_DEFAULT

    def generate(self) -> StaticTask:
        text, answer = my_legacy_func()
        return StaticTask(
            statement=[TextBlock(text)],
            answer=[TextBlock(answer)],
        )

def all_generators() -> list[TaskGenerator]:
    return [MyGenerator()]
```

### Шаг 4. Зарегистрировать в bootstrap

```python
# bootstrap.py
from exercises.my_subject.generators import all_generators as my_gens

CODE_GENERATORS = [
    ...,
    *[(MY_SUBJECT_ID, g) for g in my_gens()],
]

# В sync_database:
repo.ensure_subject(MY_SUBJECT_ID, "Мой предмет", "Мой предмет")
```

### Шаг 5. Запустить

При следующем старте `sync_database` создаст subject и записи в `Partitions`,
`build_registry` зарегистрирует генератор, главное окно покажет вкладку.

**Ничего больше менять не надо.** `GeneratorWindow`, `TableTaskView`,
`StaticTaskView`, `GroupGenerator`, `TestGenerator`, `export_tasks_to_docx`,
все три редактора — работают с новым предметом без правок.

---

## 12. Как добавить новый тип контента

Если ни один существующий блок не подходит (нужен граф, видео, аудио,
хитрый виджет), создать новый класс `Block`:

```python
# core/dynamic_blocks.py (или новый файл)
class GraphBlock(Block):
    def __init__(self, nodes, edges): ...

    def render_qt(self, parent):
        return self._build_qt_graph(parent)      # QWidget

    def render_plain(self):
        return self._textual_representation()    # str

    def render_docx(self, doc):
        # Например, сохранить через graphviz в PNG и вставить как картинку
        doc.add_picture(self._render_png_buffer())
```

Не забыть добавить в `core/__init__.py`:

```python
from .dynamic_blocks import GraphBlock
__all__ = [..., "GraphBlock"]
```

После этого **любой генератор** может класть `GraphBlock` в свой `StaticTask`.
Все представления и экспортёры подхватят его автоматически.

**Главное правило для динамических блоков:** в `render_plain` и `render_docx`
блок должен показать **правильный/полностью заполненный результат**.
Без этого экспорт теряет смысл.

---

## 13. Как добавить новый редактируемый тип раздела

(Например, конструктор задач по логике, который тоже хочется редактировать через UI.)

1. Выбрать новое значение `constracted` (например, `4`).
2. Зарегистрировать его в `Repository.EDITOR_KIND_BY_CONSTRACTED`:
   ```python
   EDITOR_KIND_BY_CONSTRACTED = {1: "fisic", 2: "group", 3: "test", 4: "logic"}
   ```
3. Создать `LogicEditor(PartitionEditor)` в `ui/editors/logic_editor.py`.
4. Добавить ветку в `ui/editors/__init__.create_editor()`.
5. Добавить пункт в меню «+ Создать» в `GeneratorWindow._build_partition_controls()`.
6. Создать соответствующий `LogicGenerator`, читающий `generation_parametrs`,
   и зарегистрировать его как фабрику в `bootstrap._register_logic`.

---

## 14. Edge cases и тонкости

### 14.1. Кодировки JSON в legacy-данных

Старые файлы словарей могут быть в `cp1251` или иметь нестандартную структуру
(список с вложенными dict-ами вместо плоского dict). `_read_json_lenient`
последовательно пробует utf-8, utf-8-sig, cp1251. `WordsTrainerGenerator._flatten_words`
сплющивает вложенную структуру в плоский dict. Битые JSON просто отсеиваются.

### 14.2. Нормализация JSON-конфига в физике

Поля `min`, `max`, элементы `forbidden` могут приходить из БД как строки.
`FisicConstructorGenerator._normalize_config` приводит всё к `float`,
не-числа в `forbidden` отбрасывает. **Без этого старый код падал с TypeError**
при делении/вычитании. Это критическая защита, не «улучшение».

### 14.3. Legacy-имена полей в БД

* В тестах: `task_cnt` (а не `count`), может быть строкой.
* В группах: `task_id`, `task_name`, `constracted` — все строкой или числом.
* В физике: `forbidden` — может быть `["0"]` (список строк) вместо `[0.0]`.

Bootstrap-фабрики для групп/тестов/физики устойчивы ко всем этим вариациям.

### 14.4. Английские словари: два формата файлов

Bootstrap определяет тип по содержимому:
* `dict` или `list[dict]` (первый элемент без ключа `template`) → `WordsTrainerGenerator` (INTERACTIVE).
* `list` с первым элементом, содержащим `template` → `SentenceFillGenerator` (STATIC).
* Битые/неподдерживаемые → пропускаются (не попадают в реестр).

`partition_id` английских словарей — `1000 + i`, где `i` — индекс в
отсортированном списке файлов. Если порядок файлов меняется, ID могут «съехать»
у уже сохранённых групп/тестов, ссылающихся на них. Если это станет проблемой,
нужно будет привязывать ID к имени файла (хешем).

### 14.5. INTERACTIVE-генераторы автоматически отсекаются от групп/тестов

`GroupGenerator.__init__` фильтрует детей по флагу `GROUPABLE`. Тренажёр
английских слов имеет `capabilities = INTERACTIVE` — он не GROUPABLE, поэтому
просто не попадает в группу. Ошибки не возникает, фильтр срабатывает молча.

В UI `GroupEditor` помечает таких кандидатов **серым** с тултипом
«нельзя положить в группу» — пользователь видит, что вариант недоступен.

### 14.6. Пересборка реестра после изменений

`GeneratorWindow.registry_builder` — фабрика, переданная из `main.py`.
После сохранения раздела в редакторе или удаления раздела окно вызывает её,
заменяя `self.registry` новым объектом. **Уже открытые `View` продолжают
работать со старым генератором** — он у них в руках, ссылки никуда не делись.
Новые клики идут к свежему реестру. Это позволяет не закрывать активную работу
при правке других разделов.

### 14.7. Правка существующего code-раздела

Code-генераторы (constracted=0) **не редактируются через UI**. Кнопки
«Изменить» и «Удалить» для них неактивны (`Repository.editor_kind_for()`
возвращает `None`). Это страховка от того, что пользователь сломает
встроенные модули.

Чтобы изменить code-раздел, надо менять код в `exercises/<предмет>/generators.py`.

### 14.8. Удаление группы/теста, использующего удалённый раздел

При удалении code-раздела (через прямой запрос к БД, не через UI) группа
или тест, содержавшие его в `generation_parametrs`, при следующей сборке
реестра попытаются собрать дочерние генераторы, отфильтруют отсутствующих
и продолжат работать с остатком. Если детей не осталось — фабрика бросит
`RuntimeError`, и пользователь увидит сообщение в `GeneratorWindow`.

### 14.9. Сериализация изображений в BytesIO

`ImageBlock.render_docx`: для `PIL.Image` создаётся `BytesIO`, изображение
сохраняется в PNG, буфер передаётся в `doc.add_picture()`. Файл на диск
не пишется. То же самое для `latex_to_docx_image` — формула рендерится
в `BytesIO` через matplotlib mathtext.

### 14.10. matplotlib backend

`core/rendering.py` принудительно ставит `matplotlib.use("Agg")` перед
рендерингом формул и изображений. Это нужно, чтобы matplotlib не пытался
открыть GUI-окно при работе в Qt-приложении.

### 14.11. SQL-инжекция

Все SQL-запросы в `Repository` параметризованные (`?`-placeholders).
Никаких f-string запросов нет. При добавлении новых методов держать это в уме.

---

## 15. Что остаётся за рамками стандарта

Стандарт описывает контракт между модулями, ядром, UI и БД. Намеренно не
специфицирует:

* Реализации `_latex_to_pixmap`, `_pil_to_qpixmap`, `_insert_latex_into_docx` —
  инфраструктурный код, написан один раз и переиспользуется.
* Конкретную схему БД — это слой `Repository`. Можно поменять (например,
  с SQLite на PostgreSQL) без изменения остальных слоёв.
* Стилизацию виджетов и темы — задача `View`, не контракта.
* Логику восстановления сессий, кеширования, фоновой генерации, отмены —
  ортогональные задачи, встраиваются без правки стандарта.
* Аутентификацию и роли пользователей — выходит за рамки текущей задачи.

---

## 16. Полезные карты для AI-агентов

Эти карты помогают быстро ориентироваться в проекте при работе с ним
из агента/ассистента.

### 16.1. Куда что класть

| Что | Куда |
|---|---|
| Новый `Block` | `core/dynamic_blocks.py` (или `core/blocks.py` для статичного) + экспорт в `core/__init__.py` |
| Новый генератор | `exercises/<предмет>/generators.py` |
| Новый legacy-код-генератор (нетронутая функция) | `exercises/<предмет>/<имя>.py` рядом с адаптером |
| Новый `View` | `ui/views/` + экспорт в `ui/views/__init__.py` |
| Новый `Editor` | `ui/editors/` + ветка в `create_editor()` |
| Регистрация в реестре | `bootstrap.CODE_GENERATORS` или `_register_*` фабрика |
| Запись в БД при старте | `bootstrap.sync_database()` |
| Путь к файлу | `const.py` |

### 16.2. Имена-ловушки

* **`partition_name`**, не `name` — поле в БД
* **`generation_parametrs`** (с орфографической ошибкой) — поле в БД, унаследовано
* **`constracted`** (тоже с ошибкой) — поле в БД, тип раздела (0–3)
* **`task_cnt`**, не `count` — ключ количества в JSON тестов
* **`task_id`**, не `partition_id` — ключ в JSON групп/тестов (но это и есть partition_id)
* **`pra_subject`** — родительский предмет, по нему определяется родство в тестах

### 16.3. Диапазоны partition_id (зарезервировано)

* `1–7`: линал
* `8–37`: физика (конструкторы, группы, тесты, в том числе СCУАР)
* `40–47`: производные (8 типов)
* `50–62`: пределы (13 типов)
* `70–71`: ОПВС (схема, C-код)
* `1000+`: английский (1 файл = 1 ID)
* `48, 49, 63–69, 72–999`: свободно — для нового

При добавлении нового предмета **не трогать** существующие диапазоны,
выбирать свободный поддиапазон.

### 16.4. Что нельзя менять

* Сигнатуры публичных методов `Repository`, `GeneratorRegistry` — на них
  опираются редакторы и `GeneratorWindow`.
* Контракты `Block`, `Task`, `TaskGenerator` — на них опирается всё.
* Имя поля `task_cnt` в JSON тестов — оно унаследовано из старой БД,
  и пользовательские данные содержат его. Можно добавить чтение `count`
  как алиас, но писать всегда в `task_cnt`.
* `_normalize_raw` / `_normalize_config` в физике — без них падает legacy-код.
* `render_circuit` в opvs/png_generator — на неё опирается `LogicCircuitGenerator`.

### 16.5. Что можно (и нужно) развивать

* **Новые блоки** для специфического контента: `GraphBlock`, `AudioBlock`,
  `ChartBlock`, `Geometry3DBlock`. Главное — три рендер-метода.
* **Новые `View`** для нестандартных режимов: например, «карточный» режим
  с перелистыванием, режим повторений Лейтнера для английского.
* **Новые редакторы** для разделов с богатой конфигурацией: например,
  редактор полигональных задач линала, редактор алгоритмов на графах.
* **Новые типы заданий** в существующих предметах: один файл, один класс.
* **Альтернативные источники данных**: можно сделать `RemoteRepository`,
  читающий разделы с сервера, и это не потребует менять ни UI, ни генераторы.
