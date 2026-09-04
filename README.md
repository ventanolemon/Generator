# Генератор заданий — версия по стандарту

Проект построен по стандарту [task_generator_standard.md](./task_generator_standard.md):
ядро не знает о предметах, добавление нового модуля — это один файл с одним классом.

> **Это ПОЛОВИНА системы.** Второй репозиторий — `ventanolemon/GenerationWeb`:
> сервер, веб-клиент и **та же** копия ядра (`core/`), которую переносят
> руками. Общая документация живёт там:
>
> * `HANDOFF.md` — холодный старт одним файлом: что есть, как запускать,
>   что осталось, чего не трогать;
> * `docs/handbook/` — справочник;
> * `docs/architecture/` — решения с основаниями.
>
> Правку в `core/` переносят в оба репозитория, а расхождение ловит
> `python -m scripts.core_drift ../Generator` (запускается со стороны
> GenerationWeb).

## Запуск

```bash
pip install -r requirements.txt
python main.py
```

Рабочая база создаётся при первом запуске в `data/` копией шаблона
`resources/users_database.db`. Сам шаблон — ПОСТАВКА, он только читается.

Гостевой вход — кнопка «Гостевой вход» на экране авторизации.

## Структура

```
project/
├── core/              # Стандарт (Block, Task, TaskGenerator, Capability, Registry, Repository)
├── ui/
│   ├── views/         # 4 представления: Static, Table, Interactive, Test+Export
│   ├── editors/       # 3 редактора: Group, Test, Fisic + базовый PartitionEditor
│   ├── windows/       # Auth, Generator
│   ├── exporter.py    # Один экспортёр в Word на все предметы
│   └── utils.py
├── exercises/         # Доменные модули
│   ├── linal/         # Оригинальные ex2_d.py, ex3_d.py + generators.py (адаптеры)
│   ├── matan/         # diff/, limits/ + generators.py
│   ├── fisic/         # fisic_generater.py + generators.py
│   ├── opvs/          # png_generator.py (с разделением на render+save), opvs_new.py + generators.py
│   └── english/       # generators.py (InteractiveTask)
├── resources/
│   ├── users_database.db
│   └── words/         # JSON-словари для англ
├── bootstrap.py       # Регистрация всех генераторов в реестре
├── const.py           # Пути проекта
├── main.py            # Точка входа
└── STANDARD.md        # Полное описание архитектурного стандарта
```

## UI: возможности пользователя

Главное окно (`GeneratorWindow`) показывает:
* выбор предмета (комбобокс),
* список разделов выбранного предмета,
* область задания (одно из четырёх представлений в зависимости от типа раздела),
* **панель управления разделами**: «+ Создать», «Изменить», «Удалить».

«Создать» открывает меню с тремя типами:
* **Группа** — раздел, при каждой генерации выбирающий случайного из своих детей
* **Тест** — упорядоченный список заданий с количеством каждого
* **Задача по физике** — текстовое условие с маркерами `#var#`, формула, переменные

Кнопки «Изменить» и «Удалить» активны только когда выбран раздел редактируемого
типа. Встроенные модули (линал, матан, тренажёр английского) удалить нельзя
через UI — они описаны в коде, а не в БД.

После любого изменения реестр автоматически пересобирается.

## Доступные предметы

* **Линейная алгебра** — задания на 2D и 3D плоскости (с экспортом в Word)
* **Производные** — 8 типов задач из папки `matan/diff/`: обычные, логарифмические,
  неявные, параметрически заданные, касательные, по правилу Лопиталя, по формуле
  Тейлора
* **Пределы** — 13 типов задач из папки `matan/limits/`: простейшие, замечательные
  пределы, степени, радикалы, точки разрыва и т.д.
* **Физика / Кинематика / СCУАР** — конструктор задач (текст условия с маркерами
  `#var#` и таблица переменных)
* **Английский** — два типа заданий:
    * *Тренажёр перевода слов* (интерактивная сессия): JSON-словарь
      `{"word": "перевод", ...}` → пользователь вводит слово по русскому переводу
    * *Вставь пропущенное слово* (статичное с динамическим блоком):
      JSON-список `[{"template": "I ___ student", "answers": ["am"]}]`
      → пользователь вводит слова прямо в условии, ответы подсвечиваются
      зелёным/красным по мере набора
    * Для собственного словаря можно указать WAV прямо у слова:
      `{"term": "cat", "translation": "кошка", "audio": "audio/cat.wav"}`.
      Относительный путь считается от JSON-файла; в графовом редакторе WAV
      выбирается в третьем столбце окна «Просмотр/правка».
* **ОПВС** — логические схемы (растровая картинка по ГОСТ), задачи на поиск
  ошибок в C-коде

## Sync БД при старте

Bootstrap при старте проходит таблицу `Subjects` и `Partitions` и обеспечивает,
что для каждого code-only генератора есть соответствующая запись в БД.
Это значит: добавили новый генератор в `bootstrap.CODE_GENERATORS` → запись
в `Partitions` появится автоматически при следующем запуске.

Конфигурация субъектов и привязки генераторов к ним находится в одном месте —
`bootstrap.py`, в константе `CODE_GENERATORS` и функции `sync_database`.

## Как добавить новый модуль

### Если задание — обычное «условие → ответ»

1. Положите оригинальный код-генератор в `exercises/<предмет>/<любое_имя>.py`.
2. Рядом, в `exercises/<предмет>/generators.py`, напишите класс:

```python
from core import TaskGenerator, StaticTask, TextBlock, FormulaBlock, STATIC_DEFAULT
from .my_module import generate_my_task

class MyGenerator(TaskGenerator):
    name = "Моё задание"
    partition_id = 99       # должен совпадать с id строки в Partitions
    capabilities = STATIC_DEFAULT

    def generate(self) -> StaticTask:
        text, answer = generate_my_task()
        return StaticTask(
            statement=[TextBlock(text)],
            answer=[TextBlock(answer)],
        )
```

3. Импортируйте в `bootstrap.py` и зарегистрируйте:

```python
from exercises.my_subject import MyGenerator
registry.register(MyGenerator())
```

4. Добавьте запись в `Partitions` (subject_id, partition_name, constracted=0).

### Если задание — интерактивная сессия

Наследуйте `InteractiveTask`, реализуйте `initial_prompt()`, `submit()`, `is_finished()`.
Поставьте `capabilities = Capability.INTERACTIVE`. Английский — пример.

### Если нужен новый тип контента

Создайте класс, наследующий `Block`, реализуйте три метода:
`render_qt`, `render_plain`, `render_docx`. Все View и экспортёры подхватят его автоматически.

## Что было изменено в оригинальных файлах

Только одно: в `exercises/opvs/png_generator.py` функция `draw_circuit`
была разделена на `render_circuit` (отрисовка в `PIL.Image` без сохранения)
и `draw_circuit` (старый API, теперь делегирующий в `render_circuit + save`).
Старая сигнатура `draw_circuit(elements, filename)` сохранена один в один.

Все остальные генераторы (`get_just_diff`, `get_exercise`, `make_function`,
`generate_fisic_task` и т.д.) **не тронуты**.

## Что было удалено по сравнению со старым проектом

- `pycode/exercises/*/[*]_main.py` — `LinalMain`, `FisicMain`, `MatanMain`.
  Их роль (роутер по partition_id + вставка виджета в layout) полностью
  перешла в `GeneratorRegistry` + `GeneratorWindow`.
- `pycode/exercises/linal/[Second|Third]Window` и `MatanTaskWidget` —
  заменены на универсальный `StaticTaskView`.
- `pycode/group_adder/group_view.py` (`ConstructedGroup`) и
  `pycode/tester/test_view.py` (`ConstructedTest`) — заменены на
  `GroupGenerator` + `TableTaskView` и `TestGenerator` + `TestExportView`.
- `pycode/exercises/fisic/tasks_view_fisic.py` (`ConstructedTasks`) —
  заменён на `TableTaskView`.
- Все f-string SQL-запросы заменены на параметризованные через `Repository`.
```
