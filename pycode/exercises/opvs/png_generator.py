import random

from PIL import Image, ImageDraw, ImageFont
from collections import defaultdict

from sympy.physics.units import second

# Настройки ГОСТ
GOST = {
    "gate_width": 60,
    "gate_height": 60,  # Квадратные элементы для соответствия ГОСТ
    "not_radius": 5,
    "layer_spacing": 180,
    "element_spacing": 90,
    "line_width": 2,
    "font_size": 14,
    "horizontal_gap": 40,
    "vertical_gap": 30,
    "track_offset": 30,
    "avoidance_margin": 25,
    "vertical_clearance": 40,
    "track_separation": 15
}


class LogicElement:
    def __init__(self, element_type, inputs=None, name=None):
        self.type = element_type
        self.inputs = inputs or []
        self.name = name
        self.position = (0, 0)
        self.output_pos = (0, 0)
        self.input_positions = []
        self.size = self.get_size()

    def get_size(self):
        if self.type == 'INPUT':
            return (30, 30)
        elif self.type == 'NOT':
            return (GOST["gate_width"] + 10, GOST["gate_height"])
        return (GOST["gate_width"], GOST["gate_height"])

    def get_bounding_box(self):
        """Возвращает прямоугольник, занимаемый элементом"""
        x, y = self.position
        w, h = self.size
        half_w = w // 2
        half_h = h // 2

        if self.type == 'INPUT':
            return (x - 15, y - 15, x + 15, y + 15)
        elif self.type == 'NOT':
            return (x - half_w - 10, y - half_h - 10, x + half_w + 10, y + half_h + 10)
        else:
            return (x - half_w - 10, y - half_h - 10, x + half_w + 10, y + half_h + 10)

    def draw(self, draw):
        x, y = self.position
        w, h = self.size
        half_w = w // 2
        half_h = h // 2

        if self.type == 'INPUT':
            # Входная переменная (кружок по ГОСТу)
            draw.ellipse([x - 8, y - 8, x + 8, y + 8], outline="black", width=GOST["line_width"])
            # Подпись слева от кружка (как требуется)
            draw.text((x - 25, y - 7), self.name, fill="black", font=self.get_font())
            self.output_pos = (x + 8, y)

        elif self.type == 'NOT':
            # Элемент НЕ (прямоугольник + кружок на выходе)
            draw.rectangle(
                [x - half_w, y - half_h, x + half_w, y + half_h],
                outline="black",
                width=GOST["line_width"]
            )

            # Инвертирующий кружок на выходе
            circle_x = x + half_w
            draw.ellipse([circle_x - 5, y - 5, circle_x + 5, y + 5], outline="black", width=GOST["line_width"])

            # Стрелка на выходе
            self.output_pos = (circle_x + 5, y)
            self.input_positions = [(x - half_w + 5, y)]

        elif self.type == 'AND':
            # Конъюнктор И (прямоугольник с "&")
            draw.rectangle(
                [x - half_w, y - half_h, x + half_w, y + half_h],
                outline="black",
                width=GOST["line_width"]
            )

            # Символ "&" по ГОСТ
            draw.text(
                (x - 7, y - 7),
                "&",
                fill="black",
                font=self.get_font()
            )

            # Позиции выводов
            self.output_pos = (x + half_w - 5, y)
            input_offset = 18 if len(self.inputs) > 1 else 0
            self.input_positions = [
                (x - half_w + 5, y + (i - (len(self.inputs) - 1) / 2) * input_offset)
                for i in range(len(self.inputs))
            ]

        elif self.type == 'OR':
            # Дизъюнктор ИЛИ (прямоугольник с "1")
            draw.rectangle(
                [x - half_w, y - half_h, x + half_w, y + half_h],
                outline="black",
                width=GOST["line_width"]
            )

            # Символ "1" по ГОСТ
            draw.text(
                (x - 5, y - 7),
                "1",
                fill="black",
                font=self.get_font()
            )

            # Позиции выводов
            self.output_pos = (x + half_w - 5, y)
            input_offset = 18 if len(self.inputs) > 1 else 0
            self.input_positions = [
                (x - half_w + 5, y + (i - (len(self.inputs) - 1) / 2) * input_offset)
                for i in range(len(self.inputs))
            ]

    def get_font(self):
        try:
            return ImageFont.truetype("arial.ttf", GOST["font_size"])
        except:
            return ImageFont.load_default()

    def get_logic_str(self):
        if self.type == "INPUT":
            return self.name
        elif self.type == "NOT":
            return "not(" + self.inputs[0].get_logic_str() + ")"
        separator = " ^ " if self.type == "AND" else " v "
        return "(" + separator.join([i.get_logic_str() for i in self.inputs]) + ")"

    def __eq__(self, other):
        if self.type == other.type and self.name == other.name and self.inputs == other.inputs:
            return True
        else:
            return False

    def __str__(self):
        return self.type + "(" + (self.name if self.name else ", ".join(map(str, self.inputs))) + ")"

    def __repr__(self):
        return self.type + "(" + (self.name if self.name else ", ".join(map(str, self.inputs))) + ")"


def make_function():
    """Генерация логической функции от 3-4 переменных """
    input_count = random.randint(3, 4)
    inputs = [LogicElement('INPUT', name=chr(ord('A') + i)) for i in range(input_count)]
    unused_elements = inputs.copy()

    noters = []
    first_layer_functions_count = random.randint(2, 3)
    first_layer = []
    for i in range(first_layer_functions_count):
        new_type = random.choice(["AND", "AND", "OR", "OR", "NOT"])
        if new_type != "NOT":
            logic_inputs = random.sample(inputs, k=2)
        else:
            logic_inputs = random.sample(inputs, k=1)
            if logic_inputs not in noters:
                noters.append(logic_inputs)
            else:
                new_type = random.choice(["AND", "OR"])
                logic_inputs = random.sample(inputs, k=2)

        for inp in logic_inputs:
            try:
                unused_elements.remove(inp)
            except ValueError:
                pass
        elem = LogicElement(new_type, inputs=logic_inputs)
        first_layer.append(elem)
        unused_elements.append(elem)

    second_layer_functions_count = random.randint(1, 2)
    second_layer = []
    for i in range(second_layer_functions_count):
        new_type = random.choice(["AND", "AND", "OR", "OR", "NOT"])
        if new_type != "NOT":
            logic_inputs = random.sample(first_layer, k=2)
        else:
            logic_inputs = random.sample(inputs, k=1)
            if logic_inputs not in noters:
                noters.append(logic_inputs)
            else:
                new_type = random.choice(["AND", "OR"])
                logic_inputs = random.sample(inputs, k=2)

        for inp in logic_inputs:
            try:
                unused_elements.remove(inp)
            except ValueError:
                pass

        elem = LogicElement(new_type, inputs=logic_inputs)
        second_layer.append(elem)
        unused_elements.append(elem)

    new_type = random.choice(["AND", "AND", "OR", "OR"])
    third_layer = [LogicElement(new_type, unused_elements)]
    # print(inputs)
    # print(first_layer)
    # print(second_layer)
    # print(third_layer)
    res_tree = inputs + first_layer + second_layer + third_layer
    return res_tree


def calculate_levels(elements):
    """Определение уровней элементов"""
    levels = defaultdict(list)
    for elem in elements:
        if elem.type == 'INPUT':
            level = 0
        else:
            input_levels = [0]
            for inp in elem.inputs:
                inp_level = next((l for l, es in levels.items() if inp in es), 0)
                input_levels.append(inp_level + 1)
            level = max(input_levels)
        levels[level].append(elem)
    return levels


def calculate_positions(elements):
    """Определение позиций элементов на схеме с оптимальной сортировкой внутри уровней"""
    levels = calculate_levels(elements)

    # Расчет позиций
    max_level = max(levels.keys()) if levels else 0
    max_elements = max(len(layer) for layer in levels.values()) if levels else 1

    canvas_width = (max_level + 1) * GOST["layer_spacing"] + 300
    canvas_height = max(600, max_elements * GOST["element_spacing"] + 300)

    # Обрабатываем уровни по порядку от 0 до max_level
    sorted_levels = sorted(levels.keys())

    for level in sorted_levels:
        x = 120 + level * GOST["layer_spacing"]
        start_y = 150

        layer = levels[level]

        if level == 0:
            # Для входов сортируем по имени для порядка A, B, C
            layer.sort(key=lambda e: e.name if hasattr(e, 'name') else '')
        else:
            # Для других уровней сортируем по средней Y-координате входов
            def get_avg_input_y(elem):
                input_ys = []
                for inp in elem.inputs:
                    # Все входы должны иметь позиции, так как их уровни < текущего
                    input_ys.append(inp.position[1])
                return sum(input_ys) / len(input_ys) if input_ys else float('inf')

            # Сортируем элементы по средней Y-координате их входов
            layer.sort(key=lambda e: get_avg_input_y(e))

        # Распределяем элементы по сетке с фиксированным шагом
        for i, elem in enumerate(layer):
            y = start_y + i * GOST["element_spacing"]
            elem.position = (x, y)

    return int(canvas_width), int(canvas_height)


def horizontal_segment_intersects_element(start_x, end_x, y, element):
    """Проверяет, пересекает ли горизонтальный сегмент элемент"""
    box = element.get_bounding_box()
    box_left, box_top, box_right, box_bottom = box

    # Добавляем отступ для безопасного обхода
    box_left -= GOST["avoidance_margin"]
    box_right += GOST["avoidance_margin"]
    box_top -= GOST["avoidance_margin"]
    box_bottom += GOST["avoidance_margin"]

    # Проверяем, что сегмент пересекает X-границы элемента
    segment_left = min(start_x, end_x)
    segment_right = max(start_x, end_x)

    if not (segment_left <= box_right and segment_right >= box_left):
        return False

    # Проверяем, что Y-координата сегмента внутри Y-границ элемента
    return box_top <= y <= box_bottom


def vertical_segment_intersects_element(segment_x, y_start, y_end, element):
    """
    Проверяет, пересекает ли вертикальный сегмент элемент.

    Вертикальный сегмент определяется как линия с фиксированной координатой X,
    проходящая от y_start до y_end (включительно).

    Пересечение происходит, если:
    1. Координата X сегмента находится внутри расширенных границ элемента по горизонтали
    2. Диапазон Y сегмента пересекается с расширенными границами элемента по вертикали

    Аргументы:
        segment_x (int): X-координата вертикального сегмента
        y_start (int): Начальная Y-координата сегмента
        y_end (int): Конечная Y-координата сегмента
        element (LogicElement): Проверяемый элемент

    Возвращает:
        bool: True если сегмент пересекает элемент (с учётом отступа), иначе False
    """
    # Нормализуем Y-координаты (сегмент может идти вверх или вниз)
    seg_y_top = min(y_start, y_end)
    seg_y_bottom = max(y_start, y_end)

    # Получаем границы элемента с расширенным отступом для безопасного обхода
    box = element.get_bounding_box()
    box_left = int(box[0] - GOST["avoidance_margin"])
    box_right = int(box[2] + GOST["avoidance_margin"])
    box_top = int(box[1] - GOST["avoidance_margin"])
    box_bottom = int(box[3] + GOST["avoidance_margin"])

    # Проверка 1: сегмент находится внутри горизонтальных границ элемента
    if not (box_left <= segment_x <= box_right):
        return False

    # Проверка 2: диапазоны Y пересекаются
    # Два отрезка [a1, a2] и [b1, b2] пересекаются, если max(a1, b1) <= min(a2, b2)
    return max(seg_y_top, box_top) <= min(seg_y_bottom, box_bottom)


def horizontal_segments_overlap(seg1, seg2):
    """Проверяет перекрытие двух горизонтальных сегментов"""
    y1, x1_start, x1_end = seg1
    y2, x2_start, x2_end = seg2

    # Проверяем, достаточно ли далеко сегменты по вертикали
    if abs(y1 - y2) < GOST["track_separation"]:
        # Проверяем пересечение по горизонтали
        return max(x1_start, x2_start) <= min(x1_end, x2_end)

    return False


def vertical_segments_overlap(seg1, seg2):
    """
    Проверяет перекрытие двух вертикальных сегментов.
    Сегменты перекрываются, если:
    1. Расстояние по X меньше track_separation
    2. Их проекции по Y пересекаются
    """
    x1, y1_start, y1_end = seg1
    x2, y2_start, y2_end = seg2

    # Нормализуем Y-координаты (y_start <= y_end)
    y1_start, y1_end = min(y1_start, y1_end), max(y1_start, y1_end)
    y2_start, y2_end = min(y2_start, y2_end), max(y2_start, y2_end)

    # Проверяем горизонтальное расстояние
    if abs(x1 - x2) < GOST["track_separation"]:
        # Проверяем вертикальное пересечение
        return max(y1_start, y2_start) <= min(y1_end, y2_end)

    return False


def find_safe_bend_point(start_x, start_y, target_x, horizontal_tracks, min_offset=25):
    """
    Находит безопасную X-координату для точки изгиба первого горизонтального сегмента.

    Алгоритм:
    1. Начинаем с целевой позиции (середина между слоями)
    2. Двигаемся от источника к цели с шагом track_separation
    3. На каждой позиции проверяем сегмент на пересечение с существующими треками
    4. Возвращаем первую безопасную позицию или минимально допустимый отступ

    Возвращает: (safe_x, was_shortened)
    """
    # Определяем направление движения (вправо или влево от источника)
    direction = 1 if target_x > start_x else -1
    step = GOST["track_separation"] * direction

    # Минимально допустимая позиция изгиба (с отступом от элемента-источника)
    min_safe_x = start_x + (40 if direction > 0 else -40)

    # Сначала проверяем целевую позицию
    candidate_x = target_x
    test_seg = (start_y, min(start_x, candidate_x), max(start_x, candidate_x))

    if not any(horizontal_segments_overlap(test_seg, existing) for existing in horizontal_tracks):
        return candidate_x, False  # Целевая позиция безопасна

    # Если конфликт — ищем безопасную позицию ближе к источнику
    current_x = start_x + step
    attempts = 0
    max_attempts = 50

    while attempts < max_attempts and abs(current_x - start_x) <= abs(target_x - start_x):
        # Проверяем минимальный отступ от источника
        if abs(current_x - start_x) < min_offset:
            current_x += step
            attempts += 1
            continue

        test_seg = (start_y, min(start_x, current_x), max(start_x, current_x))
        has_conflict = any(horizontal_segments_overlap(test_seg, existing) for existing in horizontal_tracks)

        if not has_conflict:
            return current_x, True  # Найдена безопасная позиция ближе к источнику

        current_x += step
        attempts += 1

    # Если не нашли безопасную позицию в диапазоне — используем минимально допустимый отступ
    safe_x = start_x + (min_offset if direction > 0 else -min_offset)
    return safe_x, True


def route_connections(elements):
    """
    Трассировка соединений с гарантией строго ортогональных маршрутов
    (только горизонтальные и вертикальные сегменты).

    Ключевые принципы:
    1. Каждый сегмент имеет либо одинаковый X (вертикаль), либо одинаковый Y (горизонталь)
    2. Точки поворота никогда не удаляются — они критичны для ортогональности
    3. Все координаты округляются до целых чисел для предотвращения "дрожания" пикселей
    4. Коррекция маршрутов происходит путём смещения целых сегментов, а не отдельных точек
    """
    levels = calculate_levels(elements)

    # Собираем все соединения
    connections = []
    for elem in elements:
        if elem.type == 'INPUT' or not elem.inputs:
            continue

        for i, input_elem in enumerate(elem.inputs):
            start = input_elem.output_pos
            end = elem.input_positions[i] if i < len(elem.input_positions) else (
                elem.position[0] - elem.size[0] // 2 - 5, elem.position[1])
            # Округляем координаты до целых для предотвращения субпиксельных смещений
            start = (int(round(start[0])), int(round(start[1])))
            end = (int(round(end[0])), int(round(end[1])))
            connections.append((start, end, input_elem, elem))

    # Группируем соединения по парам уровней
    level_connections = defaultdict(list)
    for start, end, src, dest in connections:
        src_level = next((l for l, es in levels.items() if src in es), 0)
        dest_level = next((l for l, es in levels.items() if dest in es), 0)
        if src_level < dest_level:
            level_connections[(src_level, dest_level)].append((start, end, src, dest))

    all_routes = []
    # horizontal_tracks = [] Список горизонтальных сегментов: (y, x_start, x_end)
    horizontal_tracks = []  # (y, x_start, x_end)
    vertical_tracks = []  # (x, y_start, y_end)

    # Обрабатываем сначала смежные уровни
    sorted_level_pairs = sorted(level_connections.keys(), key=lambda x: (x[1] - x[0], x[0]))

    for (src_level, dest_level) in sorted_level_pairs:
        conns = level_connections[(src_level, dest_level)]
        level_diff = dest_level - src_level
        conns.sort(key=lambda x: x[0][1])  # Сортируем по Y-координате старта

        # Координаты центров уровней (целые числа)
        src_center_x = int(120 + src_level * GOST["layer_spacing"])
        dest_center_x = int(120 + dest_level * GOST["layer_spacing"])

        if level_diff == 1:
            # === СЛУЧАЙ 1: СМЕЖНЫЕ УРОВНИ (разница = 1) ===
            # Рассчитываем безопасный канал между элементами

            # Левая граница канала: после выхода источника + отступ
            if src_level == 0:  # Источник - входная переменная (кружок)
                channel_left = src_center_x + 8 + GOST["avoidance_margin"]
            else:  # Источник - логический элемент
                channel_left = src_center_x + GOST["gate_width"] // 2 + GOST["avoidance_margin"]

            # Правая граница канала: перед входом получателя - отступ
            channel_right = dest_center_x - GOST["gate_width"] // 2 - GOST["avoidance_margin"]

            # Защита от некорректных границ
            if channel_left >= channel_right:
                channel_left = src_center_x + 25
                channel_right = dest_center_x - 25

            channel_width = channel_right - channel_left

            for i, (start, end, src, dest) in enumerate(conns):
                # Равномерное распределение треков в канале (целые координаты)
                if len(conns) > 1:
                    track_x = int(channel_left + (i + 0.5) * (channel_width / len(conns)))
                else:
                    track_x = int((channel_left + channel_right) / 2)

                # Базовые Y-координаты для горизонтальных сегментов
                y1, y2 = start[1], end[1]

                # === КОРРЕКЦИЯ ДЛЯ ОРТОГОНАЛЬНОСТИ ===
                # Горизонтальный сегмент 1: от источника до трека — должен иметь постоянный Y
                seg1_y = y1

                # Горизонтальный сегмент 2: от трека до получателя — должен иметь постоянный Y
                seg2_y = y2
                seg2_conflict = False
                for elem in elements:
                    if elem.type == 'INPUT' or elem == src or elem == dest:
                        continue
                    if horizontal_segment_intersects_element(track_x, end[0], seg2_y, elem):
                        seg2_conflict = True
                        break

                if seg2_conflict:
                    # Опускаем ВЕСЬ сегмент ниже (сохраняя горизонтальность)
                    seg2_y = max(start[1], end[1]) + GOST["vertical_clearance"] * (i + 1)

                # === СТРОГО ОРТОГОНАЛЬНЫЙ МАРШРУТ (4 точки) ===
                # Каждый сегмент имеет одинаковую координату по одной оси:
                # 0→1: одинаковый Y = seg1_y (горизонталь)
                # 1→2: одинаковый X = track_x (вертикаль)
                # 2→3: одинаковый Y = seg2_y (горизонталь)
                route = [
                    (start[0], seg1_y),  # Точка 0: выход источника (скорректированный Y для горизонтали)
                    (track_x, seg1_y),  # Точка 1: изгиб в трек (сохраняем Y = seg1_y)
                    (track_x, seg2_y),  # Точка 2: изгиб к получателю (сохраняем X = track_x)
                    (end[0], seg2_y)  # Точка 3: вход получателя (скорректированный Y для горизонтали)
                ]

                # Сохраняем горизонтальные сегменты для будущих проверок
                horizontal_tracks.append((seg1_y, min(start[0], track_x), max(start[0], track_x)))
                horizontal_tracks.append((seg2_y, min(track_x, end[0]), max(track_x, end[0])))
                vertical_tracks.append((track_x, min(start[1], end[1]), max(start[1], end[1])))
                all_routes.append((route, src, dest))

        else:
            # === СЛУЧАЙ 2: НЕСМЕЖНЫЕ УРОВНИ (разница > 1) ===
            # 6-точечный маршрут с подъемом в середине между слоями

            for i, (start, end, src, dest) in enumerate(conns):
                # Базовая точка изгиба по X — середина между слоем источника и СЛЕДУЮЩИМ слоем
                base_bend_x = int(src_center_x + GOST["layer_spacing"] / 2)

                # === ШАГ 1: Проверка и коррекция ПЕРВОГО горизонтального сегмента ===
                # Ищем безопасную точку изгиба, укорачивая сегмент при конфликтах
                bend_x, was_shortened = find_safe_bend_point(
                    start[0], start[1], base_bend_x, horizontal_tracks
                )

                # Если сегмент был укорочен, корректируем минимальный отступ от элемента-источника
                if was_shortened:
                    # Для входов (кружок) минимальный отступ = радиус + отступ
                    if src.type == 'INPUT':
                        min_offset = 8 + GOST["avoidance_margin"]
                    else:
                        min_offset = GOST["gate_width"] // 2 + GOST["avoidance_margin"]

                    # Гарантируем минимальный отступ
                    if bend_x > start[0]:  # Движение вправо
                        bend_x = max(bend_x, start[0] + min_offset)
                    else:  # Движение влево (маловероятно в нашей схеме)
                        bend_x = min(bend_x, start[0] - min_offset)

                # === ШАГ 2: Определяем базовую безопасную высоту НАД всеми промежуточными элементами ===
                base_safe_y = 120 - GOST["track_separation"] # !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!

                # === ШАГ 3: Проверка и коррекция bend_x на пересечение с вертикальными треками ===
                # Вертикальный сегмент подъема: от start[1] до base_safe_y по координате bend_x
                bend_seg_y_start = start[1]
                bend_seg_y_end = base_safe_y
                bend_x_candidate = bend_x
                conflict_attempts = 0

                while conflict_attempts < 30:
                    has_conflict = False
                    for existing_x, ex_y_start, ex_y_end in vertical_tracks:
                        if vertical_segments_overlap(
                                (bend_x_candidate, bend_seg_y_start, bend_seg_y_end),
                                (existing_x, ex_y_start, ex_y_end)
                        ):
                            has_conflict = True
                            break

                    if not has_conflict:
                        break
                    if bend_x_candidate > start[0] + 8:
                        # Сдвигаем вправо с шагом track_separation
                        bend_x_candidate -= GOST["track_separation"]
                    else:
                        bend_x_candidate += GOST["track_separation"]
                    conflict_attempts += 1

                bend_x = bend_x_candidate

                # === ШАГ 4: Определяем X-координату перед входом получателя ===
                dest_input_x = int(dest_center_x - GOST["gate_width"] // 2 - GOST["avoidance_margin"])

                # === ШАГ 5: Проверка и коррекция dest_input_x на пересечение с вертикальными треками и элементами ===
                dest_seg_y_start = min(base_safe_y, end[1])
                dest_seg_y_end = max(base_safe_y, end[1])
                dest_x_candidate = dest_input_x
                conflict_attempts = 0
                flag_2_x = True  # нужно, чтобы пошли влево (-), когда упремся в границу конечного элемента

                while conflict_attempts < 30:
                    has_conflict = False
                    for existing_x, ex_y_start, ex_y_end in vertical_tracks:
                        if vertical_segments_overlap(
                                (dest_x_candidate, dest_seg_y_start, dest_seg_y_end),
                                (existing_x, ex_y_start, ex_y_end)
                        ) or dest_x_candidate >= end[0] - GOST["track_separation"]:
                            has_conflict = True
                            break

                    if not has_conflict:
                        break

                    if flag_2_x and dest_x_candidate < end[0] - GOST["track_separation"]:
                        # Сдвигаем вправо с шагом track_separation
                        dest_x_candidate += GOST["track_separation"]
                        flag_2_x = False
                    else:
                        dest_x_candidate -= GOST["track_separation"]
                        print(dest_x_candidate, conflict_attempts)
                    # dest_x_candidate -= GOST["track_separation"]
                    conflict_attempts += 1

                dest_input_x = dest_x_candidate
                print(dest_x_candidate, end[0], flag_2_x, )
                # === ШАГ 6: Коррекция высоты для избежания конфликтов с горизонтальными треками между слоями ===
                seg_y = base_safe_y
                seg_start_x = min(bend_x, dest_input_x)
                seg_end_x = max(bend_x, dest_input_x)
                test_seg = (seg_y, seg_start_x, seg_end_x)

                conflict_attempts = 0
                while conflict_attempts < 15:
                    has_conflict = False
                    for existing in horizontal_tracks:
                        if horizontal_segments_overlap(test_seg, existing):
                            has_conflict = True
                            break

                    if not has_conflict:
                        break

                    seg_y -= GOST["track_separation"]
                    test_seg = (seg_y, seg_start_x, seg_end_x)
                    conflict_attempts += 1

                # === СТРОГО ОРТОГОНАЛЬНЫЙ МАРШРУТ (6 точек) ===
                route = [
                    (start[0], start[1]),  # Точка 0: выход источника (фиксированная позиция)
                    (bend_x, start[1]),  # Точка 1: горизонталь до точки изгиба (МОЖЕТ БЫТЬ УКОРОЧЕНА)
                    (bend_x, seg_y),  # Точка 2: вертикальный подъем
                    (dest_input_x, seg_y),  # Точка 3: горизонталь над элементами
                    (dest_input_x, end[1]),  # Точка 4: вертикальный спуск
                    (end[0], end[1])  # Точка 5: вход получателя (фиксированная позиция)
                ]
                print(route, base_safe_y)

                # === ШАГ 7: Сохраняем сегменты для будущих проверок ===
                # Горизонтальные сегменты
                horizontal_tracks.append((start[1], min(start[0], bend_x), max(start[0], bend_x)))
                horizontal_tracks.append((seg_y, min(bend_x, dest_input_x), max(bend_x, dest_input_x)))
                horizontal_tracks.append((end[1], min(dest_input_x, end[0]), max(dest_input_x, end[0])))

                # Вертикальные сегменты
                vertical_tracks.append((bend_x, min(start[1], seg_y), max(start[1], seg_y)))
                vertical_tracks.append((dest_input_x, min(seg_y, end[1]), max(seg_y, end[1])))

                all_routes.append((route, src, dest))

    return all_routes


def draw_circuit(elements, filename):
    """Отрисовка схемы с обходом элементов"""
    width, height = calculate_positions(elements)
    img = Image.new('RGB', (int(width), int(height)), 'white')
    draw = ImageDraw.Draw(img)

    # Сначала рисуем элементы
    for elem in elements:
        elem.draw(draw)

    # Рисуем соединения
    routes = route_connections(elements)

    # Рисуем все линии
    for route, src, dest in routes:
        # Рисуем основную линию
        for i in range(len(route) - 1):
            draw.line([route[i], route[i + 1]], fill="black", width=GOST["line_width"])

    # Добавляем заголовок
    title_font = LogicElement('INPUT').get_font()
    draw.text((50, 30), "Логическая схема по ГОСТ 2.743-91", fill="black", font=title_font)

    img.save(filename)
    return img


# === ДЕМОНСТРАЦИЯ ===
if __name__ == "__main__":
    # Строим схему для функции (A AND B) OR (NOT C) AND ABC с A -> AND_ABC
    # circuit = build_circuit("(A AND B) OR (NOT C) AND ABC")
    circ = make_function()
    print(circ)
    print(circ[-1])
    print(circ[-1].get_logic_str())

    # Генерируем изображение
    result_img = draw_circuit(circ, "logic_circuit_gost_russian.png")

    print("Схема успешно создана: logic_circuit_gost_russian.png")
