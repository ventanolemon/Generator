# План: редизайн UI десктопа + переработка локальной БД

Дорожная карта работ по обновлению интерфейса десктопного приложения
(`Generator`, PyQt6) и архитектуры локальной SQLite-БД. Живой документ —
отмечаем волны по мере готовности, как `docs/graph_addon.md`.

## Принятые решения

- **Рез нагрузки:** backend↔презентация. Один исполнитель (Opus) ведёт слой
  данных/корректности, второй (Fable) — презентацию.
  - **Opus (я):** схема/миграции, `Repository`, безопасность (хэш паролей),
    протоколы-клиенты (sync-хуки, contour-клиент), бутстрап/сессия/роль,
    общая оболочка (TopBar, AppContext, хранилище настроек), тест-гейты
    логики, интеграция веток.
  - **Fable:** система темы и QSS, вёрстка всех окон/диалогов и полировка,
    консолидация каркаса превью, редизайн главных экранов и авторизации,
    Qt-smoke-тесты со скринами.
- **Единственный горячий файл** `ui/windows/generator_window.py` — **целиком
  за Opus** (структура/лейаут/TopBar). Fable создаёт новые окна и правит тему
  в листовых виджетах. Коллизий по файлам нет.
- **Скрытие И удаление** сущностей: скрытие = обратимый флаг (soft-delete),
  удаление = отдельное необратимое действие с подтверждением.
- **Адрес сервера один** для sync и контура: десктоп ходит только в
  `web_layer`, тот проксирует `/api/sync/*` и `/api/contour/*`. Роль
  teacher/admin приходит из сессии (A1) — ею гейтим кнопку контура.

## Модель координации

- Fable работает в изолированном git-worktree; Opus — в основном дереве.
- Один долгоживущий Fable-агент на все волны (единый дизайн-язык).
- Контракты (K1–K4) фиксируются в этом документе ДО параллельной работы —
  каждая сторона кодит против документированного API, не против чужих файлов.
- На границе волны Opus забирает работу Fable, интегрирует, гоняет весь набор
  (`QT_QPA_PLATFORM=offscreen python3 -m unittest discover -s tests`),
  открывает один draft-PR на волну (ветка перезапускается от master).

## Контракты (K1–K4)

### K1 — Тема (`ui/theme.py`, владелец Fable)

- Палитра-токены: `bg`, `surface`, `surface_alt`, `text`, `text_muted`,
  `accent`, `danger`, `success`, `border`. Два варианта: `light`, `dark`.
- `build_qss(palette) -> str`, `apply_theme(app: QApplication, name: str)`
  (читает `ui/theme` из настроек; по умолчанию `dark`).
- **Словарь QSS-классов** (через `widget.setProperty("class", …)` +
  селектор `QWidget[class="…"]`): `title`, `subtitle`, `card`, `toolbar`,
  `toolbtn`, `badge`, `badge-warn`, `badge-error`, `danger`, `muted`.
  Обе стороны используют ровно эти имена.

### K2 — Оболочка (`ui/widgets/top_bar.py` + `ui/app_context.py`, владелец Opus)

- `TopBar(QWidget)`:
  - `add_action(icon: str, tooltip: str, cb, *, roles: set[str] | None = None) -> QToolButton`
    — кнопка в баре; при `roles` показывается только для этих ролей.
  - `add_badge(key: str) -> QLabel` — правая зона статус-бейджей (sync).
  - `set_badge(key, text, level="")` — level ∈ {"", "warn", "error"}.
- `AppContext` (dataclass), пробрасывается в окна вместо россыпи аргументов:
  `repo`, `settings`, `sync_client | None`, `contour_client | None`,
  `user_id_provider`, `user_role_provider`.

### K3 — Настройки (`core/settings.py`, владелец Opus)

- Тонкая обёртка `QSettings` (org=`Generator`, app=`Desktop`).
- Ключи: `net/base_url`, `ui/theme`, `account/last_login`.
- API: `get_base_url()`, `set_base_url()`, `get_theme()`, `set_theme()`.

### K4 — Каркас превью (`ui/views/base_view.py`, владелец Fable)

- `BaseTaskView(QWidget)`: общая шапка (заголовок + кнопка «Сгенерировать
  заново») + прокручиваемый контейнер тела, наполняемый `render_blocks`.
- Хук `build_body() -> Iterable[Block]` переопределяют подклассы.
- От него наследуются `StaticTaskView`/`TableTaskView`/`InteractiveTaskView`/
  `TestExportView` и превью мастера контура (C2).

## Волны

### Волна A — фундамент
| № | Задача | Владелец | Файлы | Зависит | Гейт |
|---|---|---|---|---|---|
| A1 | AppContext + роль в сессии + `core/settings` | Opus | `main.py`, `core/settings.py`, `ui/app_context.py`, конструктор `generator_window.py` | — | старт, роль прокинута |
| A2 | TopBar + перенос «Моя статистика» | Opus | `ui/widgets/top_bar.py`, `generator_window.py` | A1 | кнопка в баре |
| A3 | `theme.py` + миграция QSS (кроме generator_window) | Fable | `theme.py`, `auth_window`, `stats_window`, 4 view, `legend`, `inspector` | K1 | offscreen-скрин |
| A4 | Консолидация `base_view` | Fable | `ui/views/base_view.py` + рефактор 4 view | A3 | view-тесты зелёные |

### Волна B — Настройки + Sync
| № | Задача | Владелец | Файлы | Зависит |
|---|---|---|---|---|
| B1 | Диалог настроек (Соединение/Оформление/Аккаунт-заглушка) | Opus | `ui/windows/settings_window.py`, TopBar | A1–A3 |
| B2 | Sync-хуки в Repository + бутстрап SyncClient + `resolve_conflict()` | Opus | `core/repository.py`, `core/sync/store.py`, `main.py` | A1 |
| B3 | Sync-окно (статус/поток/лог/конфликты) | Fable | `ui/windows/sync_window.py`, бейдж в TopBar | B2 + K2 |

### Волна C — Контур (замкнутый ИИ)
| № | Задача | Владелец | Файлы | Зависит |
|---|---|---|---|---|
| C1 | `core/contour/client.py` + неблокирующий поллер | Opus | `core/contour/{__init__,client}.py` | A1, B1 |
| C2 | Мастер генерации (форма→поллинг→превью→approve/reject) | Fable | `ui/windows/contour_wizard.py`, кнопка в TopBar (teacher/admin) | C1, K4 |

### Волна D — Аккаунт и жизненный цикл
| № | Задача | Владелец | Файлы | Зависит |
|---|---|---|---|---|
| D1 | Хэш паролей + смена (репозиторий) | Opus | `repository.py` (миграция plain→hash, `set_password`) | A1 |
| D2 | Вкладка «Аккаунт»: смена пароля | Fable | `settings_window.py` | D1, B1 |
| D3 | Скрытие (флаг) **и** удаление (необратимо) предметов/заданий | Opus (schema+repo) + Fable (UI) | `repository.py` (`hidden` в Subjects/Partitions, `delete_subject`), `generator_window.py` | A2 |

### Волна E — Редизайн
| № | Задача | Владелец | Файлы | Зависит |
|---|---|---|---|---|
| E1 | Редизайн главных экранов (список→карточки/сайдбар, вынос в TopBar) | Fable | `generator_window.py` layout, новые виджеты | всё выше |
| E2 | Редизайн авторизации + экран регистрации | Fable (+Opus: `create_user`) | `auth_window.py`, новый `register_window.py` | A3, D1 |

## Критический путь

```
A1 → A2 → (B1 ‖ B2) → C1 → D1 → E
      └ A3 → A4 (Fable, параллельно)
              B3 (Fable) после B2-API
              C2 (Fable) после C1
```

Backend-задача волны — критический путь Opus; презентационные задачи Fable
висят на её результате и идут параллельно внутри волны.

## Технические заметки

- **Пароли сейчас plain-text** (`Repository.find_user`: `WHERE login=? AND
  password=?`). D1 вводит `pbkdf2_hmac`; при первом входе старый plain-логин
  прозрачно мигрирует в хэш. Без D1 «смена пароля» бессмысленна.
- **Sync сейчас dormant:** `core/sync/` полностью реализован, но не вызывается
  из UI, а `Repository.upsert_partition/delete_partition` не кладут ничего в
  outbox. B2 добавляет хуки — иначе окно синка показывает пустую очередь.
- **Роль нигде не хранится:** `main.py` знает только `user_id`. A1 добавляет
  `user_role` в сессию — без неё нечем гейтить кнопку контура.
- **Блочный рендер уже общий:** все 4 view используют `render_blocks`/
  `Block.render_qt` (`ui/utils.py`) — дублируется только обвязка (K4 её
  консолидирует).

---

## Статус выполнения

**Все волны A–E завершены** (PR #30). Итог по разделению backend↔презентация:

- **A** ✅ — AppContext, роль сессии, `core/settings`, TopBar, тема, `base_view`.
- **B** ✅ — диалог настроек; синк подключён (хуки правок в outbox,
  `resolve_conflict`, окно синхронизации с бейджем).
- **C** ✅ — клиент контура + неблокирующий поллер; мастер «Генератор через
  ИИ» (форма → поллинг → превью/approve/reject), кнопка гейтится teacher/admin.
- **D** ✅ — PBKDF2-пароли с прозрачной миграцией + смена (вкладка «Аккаунт»);
  скрытие (флаг `hidden`) и необратимое удаление предметов/разделов.
- **E** ✅ — регистрация + навигация вход↔регистрация; сайдбар главного
  экрана, метки типа, пустые состояния (Opus-каркас); дизайн-язык
  «Graphite & Iris» + hero-экраны входа/регистрации (визуальный заход Fable).

Тесты: 9 наборов UI-rework (~130 тестов) + графовый (750) — зелёные.
