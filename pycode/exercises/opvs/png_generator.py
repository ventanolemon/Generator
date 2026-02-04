from PIL import Image, ImageDraw, ImageFont
from collections import defaultdict

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
    "track_separation": 20
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


def build_circuit(function_tree):
    """Создание схемы из дерева функции"""
    # Создаем элементы
    A = LogicElement('INPUT', name='A')
    B = LogicElement('INPUT', name='B')
    C = LogicElement('INPUT', name='C')
    D = LogicElement('INPUT', name='D')
    F = LogicElement('INPUT', name='F')

    not_c = LogicElement('NOT', inputs=[C])
    and_ab = LogicElement('AND', inputs=[A, B])
    and_ad = LogicElement('AND', inputs=[A, D])
    or_af = LogicElement('OR', inputs=[A, F])

    or_gate = LogicElement('OR', inputs=[and_ab, not_c])
    and_gate = LogicElement('AND', inputs=[and_ab, D])

    and_abc = LogicElement('AND', inputs=[A, or_gate])

    return [A, B, C, D, not_c, and_ab, or_gate, and_abc, F, or_af, and_ad, and_gate]


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


def find_clear_horizontal_path(start_x, end_x, y, elements, levels, src_level, dest_level):
    """Находит безопасный горизонтальный путь, обходящий элементы"""
    # Сначала проверяем, можно ли пройти напрямую
    direct_path_clear = True
    for elem in elements:
        if elem.type == 'INPUT':
            continue

        elem_level = next((l for l, es in levels.items() if elem in es), -1)
        # Проверяем только элементы между уровнями или на целевом уровне
        if src_level <= elem_level <= dest_level:
            if horizontal_segment_intersects_element(start_x, end_x, y, elem):
                direct_path_clear = False
                break

    if direct_path_clear:
        return end_x, None  # Прямой путь свободен

    # Ищем ближайшее препятствие
    obstacles = []
    for elem in elements:
        if elem.type == 'INPUT':
            continue

        elem_level = next((l for l, es in levels.items() if elem in es), -1)
        if src_level <= elem_level <= dest_level:
            if horizontal_segment_intersects_element(start_x, end_x, y, elem):
                box = elem.get_bounding_box()
                obstacles.append((box, elem))

    if not obstacles:
        return end_x, None

    # Находим ближайшее препятствие от начальной точки
    nearest_obstacle = min(obstacles, key=lambda x: abs(x[0][0] - start_x))
    box, elem = nearest_obstacle

    # Возвращаем X-координату перед препятствием и само препятствие
    safe_x = box[0] - GOST["avoidance_margin"] if start_x < box[0] else box[2] + GOST["avoidance_margin"]
    return safe_x, elem


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

                # Проверка вертикального трека на пересечение с элементами
                for level in range(src_level, dest_level + 1):
                    if level not in levels:
                        continue
                    for elem in levels[level]:
                        if elem.type == 'INPUT' or elem == src or elem == dest:
                            continue

                        box = elem.get_bounding_box()
                        elem_left = int(box[0] - GOST["avoidance_margin"])
                        elem_right = int(box[2] + GOST["avoidance_margin"])

                        # Проверяем только по X — Y проверим позже при построении сегментов
                        if elem_left <= track_x <= elem_right:
                            # Смещаем трек вправо за границу элемента
                            track_x = int(elem_right + GOST["track_separation"])
                            if track_x > channel_right - GOST["track_separation"]:
                                track_x = int(channel_right - GOST["track_separation"])
                            break

                # Базовые Y-координаты для горизонтальных сегментов
                y1, y2 = start[1], end[1]

                # === КОРРЕКЦИЯ ДЛЯ ОРТОГОНАЛЬНОСТИ ===
                # Горизонтальный сегмент 1: от источника до трека — должен иметь постоянный Y
                seg1_y = y1
                seg1_conflict = False
                for elem in elements:
                    if elem.type == 'INPUT' or elem == src or elem == dest:
                        continue
                    if horizontal_segment_intersects_element(start[0], track_x, seg1_y, elem):
                        seg1_conflict = True
                        break

                if seg1_conflict:
                    # Поднимаем ВЕСЬ сегмент выше (сохраняя горизонтальность)
                    seg1_y = start[1] #  min(start[1], end[1]) - GOST["vertical_clearance"] * (i + 1)

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
                all_routes.append((route, src, dest))

        else:
            # === СЛУЧАЙ 2: НЕСМЕЖНЫЕ УРОВНИ (разница > 1) ===
            # 5-точечный маршрут с подъемом в середине между слоями

            for i, (start, end, src, dest) in enumerate(conns):
                # Точка изгиба по X — середина между слоем источника и СЛЕДУЮЩИМ слоем (целое число)
                bend_x = int(src_center_x + GOST["layer_spacing"] / 2)

                # Определяем базовую безопасную высоту НАД всеми промежуточными элементами
                min_element_top = float('inf')
                for level in range(src_level + 1, dest_level):
                    if level not in levels:
                        continue
                    for elem in levels[level]:
                        if elem.type == 'INPUT':
                            continue
                        box = elem.get_bounding_box()
                        min_element_top = min(min_element_top, box[1])

                # Базовая безопасная высота (целое число)
                base_safe_y = int(min_element_top - GOST["vertical_clearance"] * 2) if min_element_top != float(
                    'inf') else int(start[1] - 150)

                # X-координата перед входом получателя (целое число)
                dest_input_x = int(dest_center_x - GOST["gate_width"] // 2 - GOST["avoidance_margin"])

                # === ШАГ 1: Проверка и коррекция bend_x на пересечение с вертикальными треками ===
                # Вертикальный сегмент подъема: от start[1] до base_safe_y по координате bend_x
                bend_seg_y_start = min(start[1], base_safe_y)
                bend_seg_y_end = max(start[1], base_safe_y)
                bend_x_candidate = bend_x
                conflict_attempts = 0

                while conflict_attempts < 15:
                    has_conflict = False
                    # Проверяем пересечение с существующими вертикальными треками
                    for existing_x, ex_y_start, ex_y_end in vertical_tracks:
                        if vertical_segments_overlap(
                                (bend_x_candidate, bend_seg_y_start, bend_seg_y_end),
                                (existing_x, ex_y_start, ex_y_end)
                        ):
                            has_conflict = True
                            break

                    if not has_conflict:
                        break

                    # Сдвигаем вправо с шагом track_separation
                    bend_x_candidate += GOST["track_separation"]
                    conflict_attempts += 1

                bend_x = bend_x_candidate

                # === ШАГ 2: Проверка и коррекция dest_input_x на пересечение с вертикальными треками ===
                # Вертикальный сегмент спуска: от base_safe_y до end[1] по координате dest_input_x
                dest_seg_y_start = min(base_safe_y, end[1])
                dest_seg_y_end = max(base_safe_y, end[1])
                dest_x_candidate = dest_input_x
                conflict_attempts = 0

                while conflict_attempts < 15:
                    has_conflict = False
                    for existing_x, ex_y_start, ex_y_end in vertical_tracks:
                        if vertical_segments_overlap(
                                (dest_x_candidate, dest_seg_y_start, dest_seg_y_end),
                                (existing_x, ex_y_start, ex_y_end)
                        ):
                            has_conflict = True
                            break

                    if not has_conflict:
                        break

                    # Сдвигаем вправо с шагом track_separation
                    dest_x_candidate += GOST["track_separation"]
                    conflict_attempts += 1

                dest_input_x = dest_x_candidate

                # === ШАГ 3: Коррекция высоты для избежания конфликтов с горизонтальными треками ===
                # Горизонтальный сегмент над элементами: от bend_x до dest_input_x
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

                    # Поднимаемся ВЫШЕ (уменьшаем Y — движение вверх по изображению)
                    seg_y -= GOST["track_separation"]
                    test_seg = (seg_y, seg_start_x, seg_end_x)
                    conflict_attempts += 1

                # === СТРОГО ОРТОГОНАЛЬНЫЙ МАРШРУТ (6 точек) ===
                # Каждый сегмент имеет одинаковую координату по одной оси:
                # 0→1: одинаковый Y = start[1] (горизонталь до точки изгиба)
                # 1→2: одинаковый X = bend_x (вертикальный подъем)
                # 2→3: одинаковый Y = seg_y (горизонталь над элементами)
                # 3→4: одинаковый X = dest_input_x (вертикальный спуск)
                # 4→5: одинаковый Y = end[1] (горизонталь к входу)
                route = [
                    (start[0], start[1]),  # Точка 0: выход источника (фиксированная позиция)
                    (bend_x, start[1]),  # Точка 1: горизонталь до середины между слоями
                    (bend_x, seg_y),  # Точка 2: вертикальный подъем
                    (dest_input_x, seg_y),  # Точка 3: горизонталь над элементами
                    (dest_input_x, end[1]),  # Точка 4: вертикальный спуск
                    (end[0], end[1])  # Точка 5: вход получателя (фиксированная позиция)
                ]

                # === ШАГ 4: Сохраняем сегменты для будущих проверок ===
                # Горизонтальные сегменты
                horizontal_tracks.append((start[1], min(start[0], bend_x), max(start[0], bend_x)))
                horizontal_tracks.append((seg_y, min(bend_x, dest_input_x), max(bend_x, dest_input_x)))
                horizontal_tracks.append((end[1], min(dest_input_x, end[0]), max(dest_input_x, end[0])))

                # Вертикальные сегменты (для будущих проверок пересечений)
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
    circuit = build_circuit("(A AND B) OR (NOT C) AND ABC")

    # Генерируем изображение
    result_img = draw_circuit(circuit, "logic_circuit_gost_russian.png")

    print("Схема успешно создана: logic_circuit_gost_russian.png")