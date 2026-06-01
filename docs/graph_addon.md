# Визуальный конструктор заданий (graph addon)

Проектный документ. Описывает, как встроить в комплекс визуальную среду
node-graph программирования для ручной сборки генераторов заданий — по образцу
LabVIEW — переиспользуя существующий движок генерации, БД и слой представлений.

Статус: **Фазы 0, 1 и 2 реализованы** (headless-движок `core/graph/` + адаптер
`exercises/graph/` + врезка в БД/bootstrap/редакторы для `constracted=4` +
визуальный канвас `QGraphicsScene`). Фазы 3–4 — впереди. Документ фиксирует
архитектуру целиком; раздел 10 отмечает, что сделано.

---

## 1. Цель и область

Пользователь собирает генератор задания мышью из типизированных узлов на
канвасе. Граф сериализуется в JSON и исполняется тем же ядром, что и остальные
разделы. В перспективе тот же движок (без GUI) — основа для работы с сигналами,
портами и железом (аналог LabVIEW).

Принцип: **аддон не вводит новую подсистему сбоку, а добавляет один новый тип
раздела** в уже существующую модель.

---

## 2. Ключевой инсайт: точка расширения — поле `constracted`

Модель раздела (`core/repository.py`):

```
constracted: int   # 0=одиночный, 1=конструктор(физика), 2=группа, 3=тест
```

Всё ветвление по типу раздела построено вокруг этого числа и сосредоточено в
трёх местах — больше нигде:

| Место | Что делает |
|---|---|
| `bootstrap.build_registry` | `constracted == 1 → _register_fisic`, `2 → group`, `3 → test` |
| `Repository._VIEW_KIND_BY_CONSTRACTED` | подбор View по типу раздела |
| `ui/editors/__init__.create_editor` | выбор редактора раздела |

**Граф — это `constracted = 4` («graph»).** Следствия:

- Схема БД **не меняется.** Граф сериализуется в тот же столбец
  `generation_parametrs`, где физика уже хранит произвольный JSON
  (`Repository._row_to_partition` умеет dict/list/raw).
- Появляется адаптер `GraphConstructorGenerator(TaskGenerator)` — калька с
  `FisicConstructorGenerator` (`exercises/fisic/generators.py`): партиция хранит
  JSON, адаптер исполняет и возвращает `StaticTask`/`InteractiveTask`.
- Окно генератора, views, экспорт в `.docx` **не трогаются.** Они работают с
  абстракциями `TaskGenerator` / `Block` / `Task` и про граф не знают.

---

## 3. Граница «ядро / GUI»

В коде граница проходит **внутри** `core`, и аддон обязан её повторить:

- `core/blocks.py` **импортирует PyQt6** — `core` завязан на Qt в части
  *рендеринга*.
- Генерационный слой `exercises/fisic/{expression,generation,constraints,formatting}.py`
  — **чистый Python без Qt.** Это и есть тела будущих узлов вычисления.

Размещение аддона — в две независимые части:

```
core/graph/                  ← ЧИСТЫЙ движок, НОЛЬ Qt
    port_types.py            PortType (enum типов проводов)
    node.py                  Node (ABC) + NodeSpec (порты/параметры)
    registry.py              NodeRegistry (калька с GeneratorRegistry)
    spec.py                  GraphSpec — (де)сериализация nodes[]/edges[]
    executor.py              топосортировка + dataflow + retry
    nodes/                   реализации узлов
exercises/graph/
    generators.py            GraphConstructorGenerator(TaskGenerator)
ui/editors/graph_editor/     ← Qt-канвас (QGraphicsScene)
```

Почему так:

- `core/graph/` зависит только от существующих чистых модулей и `core/blocks`;
  **тестируется headless**, без поднятия окна.
- Чистота движка — фундамент для дальней цели (сигналы/железо): headless-движок
  переиспользуется без GUI.

### Канвас: QGraphicsScene, не React Flow

Проект целиком на PyQt6. Веб-стек (React Flow) раскалывает приложение на две
технологии и лишает прямого вызова `GraphConstructorGenerator` для live-превью.
Выбор — `QGraphicsScene`. React Flow оправдан только при будущей веб-версии
всего комплекса.

---

## 4. Решение по физике: переиспользовать как тела узлов

**Не форкать формат, не делать «экспорт графа в fisic-JSON».**
`GraphTaskGenerator` исполняет граф напрямую, а функции физики становятся
телами узлов:

| Узел | Тело (существующая чистая функция) |
|---|---|
| `random_natural` / `random_real` | `generation.generate_value` + `VariableSpec` |
| `formula` | `expression.evaluate_formula` (безопасный AST, без `eval`) |
| `constraint` | `constraints.ResultConstraint.check` / `.normalize` |
| `template` | подстановка `#var#` (как в `fisic_generater._build_task`) |
| `text_block` и др. | конструкторы `core/blocks.py` |

Преимущества: нет дублирования логики, один формат, `FisicEditor` остаётся
нетронутым. Граф — **дополнительный** путь, а не замена.

---

## 5. Контракт узла и реестр

Один узел = один класс (по образцу того, как `Block` = один класс, и его
подхватывают все View).

```python
class Node(ABC):
    type_id: str               # "random_real", "formula", ...
    category: str              # source | compute | content | assembly
    inputs:  list[Port]        # (name, PortType)
    outputs: list[Port]
    params_schema: dict        # описание полей формы в редакторе

    def compute(self, inputs: dict, params: dict, ctx: ExecContext) -> dict: ...
```

`NodeRegistry` (калька с `GeneratorRegistry`) хранит классы по `type_id`.
**Палитра редактора строится из реестра** — добавили класс, узел сам появился в
UI. Тот же приём уже работает для `Block` и `TaskGenerator`.

### Типы портов

`PortType` (enum): `NUMBER, STRING, NUMBER_DICT, IMAGE, BLOCK, BLOCK_LIST, BOOL, TASK`.

| Тип | Что несёт | Откуда → куда |
|---|---|---|
| `NUMBER` | int/float | источники → вычисление |
| `STRING` | текст | источники → блоки контента |
| `NUMBER_DICT` | `dict[str,float]` | словарь vars → формула |
| `IMAGE` | `PIL.Image` в памяти | изображение → ImageBlock |
| `BLOCK` | объект `Block` любого подтипа | блоки → списки |
| `BLOCK_LIST` | `list[Block]` | списки → StaticTask |
| `BOOL` | результат проверки | constraint → ветвление |
| `TASK` | `StaticTask`/`InteractiveTask` | финальный узел → выход |

Совместимость проверяется **и при соединении в редакторе, и при загрузке из БД**
(граф мог быть повреждён).

---

## 6. Формат сериализации (инвариант, от которого зависит всё)

Хранится в `generation_parametrs` партиции с `constracted = 4`.

```json
{
  "version": 1,
  "nodes": [
    {"id": "n1", "type": "random_real",    "params": {"min": 1, "max": 20, "decimals": 1}},
    {"id": "n2", "type": "random_natural", "params": {"min": 2, "max": 10}},
    {"id": "n3", "type": "var_dict",       "params": {"names": ["v", "t"]}},
    {"id": "n4", "type": "formula",        "params": {"expr": "v * t"}},
    {"id": "n5", "type": "constraint",     "params": {"kind": "natural", "min": 1, "max": 500}},
    {"id": "n6", "type": "template",       "params": {"text": "Скорость #v#, время #t#..."}},
    {"id": "n7", "type": "text_block"},
    {"id": "n8", "type": "static_task"}
  ],
  "edges": [
    {"from": "n1:out", "to": "n3:v"},
    {"from": "n2:out", "to": "n3:t"},
    {"from": "n3:out", "to": "n4:vars"},
    {"from": "n4:out", "to": "n5:in"},
    {"from": "n3:out", "to": "n6:vars"},
    {"from": "n6:out", "to": "n7:text"},
    {"from": "n7:out", "to": "n8:statement"}
  ],
  "meta": {"max_attempts": 100, "seed": null}
}
```

Этот граф из 8 узлов = ровно текущая физическая задача `v*t` с проверкой
«натуральный, 1..500».

---

## 7. Модель исполнения (самое тонкое)

Физика — **не чистый dataflow.** `fisic_generater.generate_task` крутит всю
генерацию в цикле `max_attempts`, пока `ResultConstraint.check` не пройдёт —
т.е. в графе есть **обратная связь**: constraint умеет заставить пере-бросить
случайные источники.

- **MVP — retry всего графа.** Источники со случайностью пере-исполняются
  целиком, пока все constraint-узлы не довольны, под общим лимитом
  `max_attempts`. Точно повторяет текущую семантику физики.
- **Фаза 2 — scoped-retry.** Узел `Loop` оборачивает подграф и пере-бросает
  только его конус зависимостей. Мощнее, требует обработки псевдоциклов.

### Детерминизм / seed

Текущий код использует глобальный `random`. Движок — повод сделать правильно:
протащить `random.Random(seed)` через `ExecContext` в источники. Даёт
воспроизводимые задания (важно для тестов и повторного экспорта партиции).

### Абстрактный Executor (единственная инвестиция в будущее)

Сейчас dataflow одноразовый (pull-based, «сгенерируй задание»); LabVIEW —
непрерывный (push-based). Чтобы будущее с сигналами не потребовало переписывать
движок, интерфейс `Executor` делается абстрактным (один метод запуска), но
**реализуется только одноразовый**. Всё остальное по железу — строго потом.

---

## 8. Таксономия узлов

### Категория «источники» (без входов)
`random_natural`, `random_real`, `constant_number`, `constant_string`,
`json_dict` (слова/предложения из `resources/words/*.json`), `image_source`
(вызов `opvs.png_generator.render_circuit`).

### Категория «вычисление»
`var_dict` (коллектор именованных значений → `NUMBER_DICT`), `formula`,
`constraint`, `template` (подстановка `#var#`), `random_choice`, `loop` (фаза 2),
`if` / `switch` (фаза 2).

### Категория «блоки контента» (обёртки над `core/blocks.py`)
`text_block`, `formula_block`, `image_block`, `code_block`, `table_block`.
`fill_in_blank` — отдельно: его класс в `core/dynamic_blocks.py`, выход не
статический `Block`, а часть интерактивной сессии (учесть при типизации портов).

### Категория «сборка задания»
`block_list` (аккумулятор → `BLOCK_LIST`), `static_task` (финал),
`interactive_task` (финал для сессий).

### Пробелы относительно исходного анализа (добавлены сюда)
1. Узлы-константы (`constant_number`, `constant_string`) — литералы, которых не
   было в исходной таксономии.
2. `loop`/retry-узел — следствие обратной связи в физике (раздел 7).
3. Ветвление `if`/`switch` — для общего движка и английского.
4. Seed/детерминизм — решение на уровне `ExecContext`.
5. `fill_in_blank` живёт в `dynamic_blocks`, а не в `blocks.py`.

Чего **не** добавляем: отдельные арифметические узлы (add/mul/sqrt) — `formula`
поверх `expression.py` уже субсумирует всю арифметику безопасно.

---

## 9. Соответствие существующим типам заданий

| Тип задания | Цепочка узлов | Переиспользуемый код |
|---|---|---|
| Физика | random_* → var_dict → formula → constraint → template → text_block → static_task | весь `exercises/fisic/*` |
| ОПВС | image_source → image_block → static_task | `opvs.png_generator.render_circuit` |
| Английский (слова) | json_dict → random_choice → interactive_task | `dynamic_blocks` / WordsSession |
| Английский (пропуски) | json_dict → random_choice → fill_in_blank → static_task | `FillInTheBlankBlock` |
| Линал/Матан | (адаптер) → text_block + formula_block → static_task | существующие генераторы |

---

## 10. План реализации по фазам

**Фаза 0 — чистый движок + тесты, без UI. ✅ СДЕЛАНО.**
`core/graph/`: `PortType`, `Node`+`NodeRegistry`, `GraphSpec`, `GraphExecutor`
(топосорт + whole-graph retry), адаптер `GraphConstructorGenerator(TaskGenerator)`
в `exercises/graph/`. 10 узлов: `constant_number`, `random_natural`,
`random_real`, `var_dict`, `formula`, `constraint`, `template`, `text_block`,
`block_list`, `static_task`. Тела вычислительных узлов — функции
`exercises/fisic/*` (без дублирования). Юнит-тесты (`tests/test_graph_engine.py`,
`tests/test_graph_physics.py`) доказывают воспроизведение физики headless.

Побочно: `core/__init__.py` и `exercises/fisic/__init__.py` переведены на
ленивый импорт (PEP 562) — публичный API без изменений, но чистые слои
(контракт, задачи, движок графа) теперь импортируются без PyQt6. Это и есть
фундамент «headless-ядра» из раздела 3.

**Фаза 1 — врезка в БД/bootstrap. ✅ СДЕЛАНО.**
`4: "table"` в `_VIEW_KIND_BY_CONSTRACTED` и `4: "graph"` в
`EDITOR_KIND_BY_CONSTRACTED` (`core/repository.py`); `_register_graph` + ветка
`constracted == 4` в `bootstrap.build_registry`; диспетчеризация `"graph"` в
`ui/editors/create_editor`; пункт «Граф» в меню «+ Создать»
(`ui/windows/generator_window.py`). Минимальный `ui/editors/graph_editor.py`
(`GraphEditor`): ввод графа JSON-текстом, кнопки «Проверить»/«Предпросмотр» —
вся валидация и предпросмотр переиспользуют движок (`GraphExecutor`,
`GraphConstructorGenerator`). Полноценный канвас — Фаза 2.

Headless-тесты Фазы 1 (`tests/test_graph_phase1.py`): маппинги репозитория для
`constracted=4` и приём конфига графа во всех формах (dict / JSON / `{"raw":...}`).
GUI-часть (редактор, меню, регистрация в bootstrap) тянет Qt и проверяется в
среде с PyQt6.

**Фаза 2 — Qt-канвас. ✅ СДЕЛАНО.**
Чистая модель `core/graph/document.py` (`GraphDocument` — узлы с экранными
позициями, рёбра, сериализация в тот же `GraphSpec`; позиции хранятся в
`meta.layout`, движком игнорируются). Qt-слой `ui/editors/graph_canvas/`:
`GraphScene`/`GraphCanvasView` (узлы мышью, провода с проверкой типов,
удаление, зум/панорама), `NodePalette` (строится из `NodeRegistry.palette()`),
`ParamInspector` (форма параметров из `PARAMS_SCHEMA`). `GraphEditor` собирает
палитру + холст + инспектор, плюс вкладка «JSON» (запасной ввод/отладка) и
кнопки «Проверить»/«Предпросмотр» поверх движка. Контракт сохранения прежний:
`collect_payload() → (name, 4, graph_dict)`.

Проверено в реальном Qt (offscreen): полный набор графовых тестов 44/44 (включая
ранее пропускавшийся Qt-тест), смоук холста (рендер, типизированные соединения,
динамические порты, round-trip, живая генерация `v·t` → корректный путь),
диспетчеризация `create_editor("graph")` и контракт payload. Чистая модель
`GraphDocument` дополнительно покрыта headless-тестами
(`tests/test_graph_document.py`).

**Фаза 3 — покрытие остальных типов.** (в работе)
Узлы изображения (ОПВС), список/случайный выбор/fill-blank/интерактив
(английский), ветвление и scoped-loop.

*Шаг 3a — ветвление. ✅ СДЕЛАНО.* Новая категория `control` и 4 узла
(`core/graph/nodes/control.py`): `constant_bool`, `compare` (NUMBER op NUMBER →
BOOL), `number_check` (чётность/знак/делимость/целочисленность → BOOL), `select`
(BOOL + on_true:T + on_false:T → T, тип T параметризуется). До этого тип BOOL был
объявлен, но никем не производился — теперь подсистема замкнута. Ветвление сделано
как «жадный» мультиплексор: обе ветви вычисляются исполнителем в топопорядке,
`select` выбирает одну — переписывать executor не требуется. Палитра/стиль
получили категорию «Управление» (янтарная). Тесты `tests/test_graph_control.py`
(14, headless) + полный набор 58/58 в Qt.

*Шаг 3b — scoped-loop (цикл/подграф). ✅ СДЕЛАНО.* Узлы `repeat` и `loop_index`
(`core/graph/nodes/loop.py`). `repeat` — обычная вершина внешнего DAG
(`count:NUMBER → out:BLOCK_LIST`), но её тело — отдельный вложенный GraphSpec в
`params["body"]`, который исполняется внутренним `GraphExecutor` N раз; результат
каждой итерации — единственный свободный выход тела типа BLOCK, всё собирается в
список. `loop_index` внутри тела отдаёт номер итерации (0..N-1) через
`ExecContext.extra`. Планировщик внешнего графа не тронут — вложенность
получается без псевдоциклов. UI: инспектор показывает кнопку «Открыть тело
цикла», `GraphEditor` ведёт стек холстов с «хлебными крошками» (вход/выход,
неразрушающая свёртка в корневой граф при сохранении/проверке). Это даёт
таблицы/списки/подзадачи переменной длины. Тесты: `tests/test_graph_loop.py`
(12), `tests/test_graph_editor_nav.py` (3, Qt); полный набор 73/73.

*Шаг 3b-2 — списки, map и внешние переменные. ✅ СДЕЛАНО.* Тип `PortType.LIST`
(универсальная коллекция); источники `string_list` и `number_range`; узлы
`map` (применяет тело-подграф к каждому элементу LIST, собирает свободный BLOCK
тела в BLOCK_LIST) и `map_item` (текущий элемент). Также import-туннели:
параметр `imports` (`['имя:тип', …]`) у `repeat`/`map` добавляет на внешний узел
по одному необязательному входу на каждую внешнюю переменную, а узел `input_var`
внутри тела читает её по имени. Значения пересекают границу подграфа через
`ExecContext.extra` (ключ `__import__<имя>`); без `imports` поведение прежнее
(обратная совместимость). Константы вынесены в источники: `constant_bool`
перенесён, добавлен `constant_string`. UI: z-order контекстное меню на узле,
общая кнопка «Открыть подграф…», порт-affecting `imports`/`type`. Тесты:
`test_graph_map.py`, `test_graph_imports.py`, `test_graph_pr1.py`.

*Шаг 3b-3 — case-структура. ✅ СДЕЛАНО.* Узел `case`: вход `selector:NUMBER`
выбирает ОДНУ из N ветвей (`case_0`..`case_{N-1}`, плюс `default` для селектора
вне диапазона), каждая — отдельный вложенный граф под своим ключом параметра.
Выход `out:BLOCK_LIST` — блоки выбранной ветви (свободный BLOCK_LIST как есть
либо одиночный BLOCK в списке). В отличие от `select` (жадный мультиплексор,
считает обе ветви) здесь исполняется только выбранная ветвь — настоящий
условный поток. Ветви видят внешние переменные через тот же механизм import-
туннелей (`imports`). Навигация по ветвям переиспользует стек холстов
(ключи — это просто параметры подграфа). Инспектор: поле `case_bodies`
разворачивается в кнопки «Открыть ветвь i…» + default. Тесты:
`tests/test_graph_case.py` (10).

*Шаг 3b-4 — shift register. ✅ СДЕЛАНО.* Регистр сдвига — состояние между
итерациями `repeat`. Параметр `registers` (`['имя:тип:начальное', …]`)
объявляет регистры; в теле узел `shift_get` читает значение с предыдущей
итерации (на итерации 0 — начальное), `shift_set` записывает значение для
следующей. `repeat.compute` прокидывает текущее состояние в `ExecContext.extra`
(ключ `__register__<имя>`) и после каждой итерации забирает выход `shift_set`
(по имени) обратно во вход следующей. Это первый узел с состоянием между
проходами — позволяет аккумуляторы, ряды Фибоначчи, бегущие суммы. Без
`registers` поведение прежнее. Тесты: `tests/test_graph_shift.py` (15).

На этом фаза 3b (управляющие структуры: ветвление, цикл, map, внешние
переменные, case, shift register) закрыта.

**Фаза 3d — символьная арифметика (sympy). PR-1 (ядро + алгебра) ✅ СДЕЛАНО.**
Новый `PortType.EXPR` несёт sympy-объекты между узлами (round-trip без потерь, в
отличие от сериализации в LaTeX и обратно); свой цвет провода (пурпурный) и
категория `symbolic`. sympy импортируется лениво (`core/graph/symbolic.py`):
движок графа headless и не падает на загрузке без пакета — символьные узлы
сообщают понятную ошибку только при исполнении. Узлы PR-1:
- источники: `symbol` (переменная с предположениями complex/real/positive),
  `expr_const` (выражение из текста с неявным умножением и `^`→`**`);
- алгебра (EXPR→EXPR): `expand`, `factor`, `simplify`, `together`, `cancel`,
  `trigsimp`, `collect`/`apart` (с входом-переменной);
- арифметика: `expr_binop` (+ − × ÷ ^), `expr_subs` (подстановка NUMBER_DICT),
  `expr_eval` (EXPR→NUMBER, при не-числе → RetryGeneration);
- рендер: `expr_block` (EXPR→BLOCK через FormulaBlock, опц. префикс `f(x) = …`).
Тесты: `tests/test_graph_symbolic.py` (22), включая полный граф со static_task.
Зависимость sympy добавлена в requirements.txt. Дальше PR-2/3/4: мат. анализ
(`diff`/`integrate`/`limit`/`series`), ряды (`sum`/`Sum`), ТФКП
(`re`/`im`/`arg`/`conjugate`/`residue`) — строятся по тому же образцу.

Дальше — шаг 3c (узлы-обёртки: изображения/ОПВС, `random_choice`, английский),
правок ядра не требует.

*Шаг 3c — узлы-обёртки.* image (ОПВС/`render_circuit`), `random_choice`,
английский (`json_dict`, `fill_in_blank`). Правок ядра не требуют.

**Фаза 4 (долгосрок) — сигналы/железо.**
Новые `PortType` (`SIGNAL`/`STREAM`), узлы-источники/приёмники
(`pyserial` / Web Serial), второй планировщик исполнителя (push/непрерывный).

---

## 11. Резюме

Узлов почти достаточно — добавить константы, retry-узел, ветвление, seed и
учесть `fill_in_blank`. Архитектурно аддон встраивается через `constracted = 4`
+ чистый `core/graph/` + Qt-канвас, переиспользуя движок физики как тела узлов и
весь слой окна/views/экспорта без изменений.
