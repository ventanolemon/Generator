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

    not_c = LogicElement('NOT', inputs=[C])
    and_ab = LogicElement('AND', inputs=[A, B])
    or_gate = LogicElement('OR', inputs=[and_ab, not_c])
    and_abc = LogicElement('AND', inputs=[A, or_gate])

    return [A, B, C, not_c, and_ab, or_gate, and_abc]


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


def route_connections(elements):
    """Трассировка соединений с разными алгоритмами для смежных и несмежных уровней"""
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
            connections.append((start, end, input_elem, elem))

    # Группируем соединения по парам уровней
    level_connections = defaultdict(list)
    for start, end, src, dest in connections:
        src_level = next((l for l, es in levels.items() if src in es), 0)
        dest_level = next((l for l, es in levels.items() if dest in es), 0)
        if src_level < dest_level:
            level_connections[(src_level, dest_level)].append((start, end, src, dest))

    all_routes = []
    horizontal_tracks = []  # Список всех горизонтальных сегментов: (y, x_start, x_end)

    # Сортируем пары уровней: сначала смежные (разница 1), потом несмежные
    sorted_level_pairs = sorted(level_connections.keys(), key=lambda x: (x[1] - x[0], x[0]))

    # Обрабатываем соединения в отсортированном порядке
    for (src_level, dest_level) in sorted_level_pairs:
        conns = level_connections[(src_level, dest_level)]
        level_diff = dest_level - src_level

        # Сортируем соединения по Y-координате начала
        conns.sort(key=lambda x: x[0][1])

        # Определяем X-координату для вертикальных треков
        src_x = 120 + src_level * GOST["layer_spacing"]
        dest_x = 120 + dest_level * GOST["layer_spacing"]
        mid_x = (src_x + dest_x) // 2

        # Распределяем треки с фиксированным шагом
        for i, (start, end, src, dest) in enumerate(conns):
            # Уникальная X-координата для каждого трека
            track_x = mid_x + (i - len(conns) // 2) * GOST["track_offset"]

            if level_diff == 1:
                # Для смежных уровней используем простой 4-точечный маршрут
                route = [
                    start,
                    (track_x, start[1]),  # Горизонтальный отвод
                    (track_x, end[1]),  # Вертикальное перемещение
                    end  # Подключение к элементу
                ]

                # Проверяем вертикальный сегмент на пересечения
                for level in range(src_level + 1, dest_level):
                    for elem in levels[level]:
                        if elem.type == 'INPUT':
                            continue

                        box = elem.get_bounding_box()
                        box_left, box_top, box_right, box_bottom = box

                        if (box_left <= track_x <= box_right and
                                min(start[1], end[1]) <= box_bottom and
                                max(start[1], end[1]) >= box_top):
                            # Смещаем трек за правую границу элемента
                            track_x = box_right + GOST["avoidance_margin"]

                            route = [
                                start,
                                (track_x, start[1]),  # Обновленный горизонтальный отвод
                                (track_x, end[1]),  # Обновленное вертикальное перемещение
                                end  # Подключение к элементу
                            ]
                            break

                # Добавляем горизонтальные сегменты в общий список
                horizontal_tracks.append((start[1], min(start[0], track_x), max(start[0], track_x)))
                horizontal_tracks.append((end[1], min(track_x, end[0]), max(track_x, end[0])))

                all_routes.append((route, src, dest))

            else:
                # Для несмежных уровней используем 5-сегментный маршрут с обходом
                safe_x, obstacle = find_clear_horizontal_path(
                    start[0], track_x, start[1], elements, levels, src_level, dest_level
                )

                if obstacle is None:
                    # Прямой путь свободен - используем стандартный маршрут
                    route = [
                        start,
                        (track_x, start[1]),  # Горизонтальный отвод
                        (track_x, end[1]),  # Вертикальное перемещение
                        end  # Подключение к элементу
                    ]

                    # Проверяем вертикальный сегмент на пересечения
                    for level in range(src_level + 1, dest_level):
                        for elem in levels[level]:
                            if elem.type == 'INPUT':
                                continue

                            box = elem.get_bounding_box()
                            box_left, box_top, box_right, box_bottom = box

                            if (box_left <= track_x <= box_right and
                                    min(start[1], end[1]) <= box_bottom and
                                    max(start[1], end[1]) >= box_top):
                                track_x = box_right + GOST["avoidance_margin"]

                                route = [
                                    start,
                                    (track_x, start[1]),  # Обновленный горизонтальный отвод
                                    (track_x, end[1]),  # Обновленное вертикальное перемещение
                                    end  # Подключение к элементу
                                ]
                                break

                    # Проверяем горизонтальные сегменты на пересечение с другими треками
                    y1 = start[1]
                    y2 = end[1]

                    # Проверяем первый горизонтальный сегмент
                    test_seg1 = (y1, min(start[0], track_x), max(start[0], track_x))
                    while any(horizontal_segments_overlap(test_seg1, existing) for existing in horizontal_tracks):
                        y1 += GOST["track_separation"]
                        test_seg1 = (y1, min(start[0], track_x), max(start[0], track_x))

                    # Проверяем второй горизонтальный сегмент
                    test_seg2 = (y2, min(track_x, end[0]), max(track_x, end[0]))
                    while any(horizontal_segments_overlap(test_seg2, existing) for existing in horizontal_tracks):
                        y2 += GOST["track_separation"]
                        test_seg2 = (y2, min(track_x, end[0]), max(track_x, end[0]))

                    # Обновляем маршрут с новыми Y-координатами
                    route = [
                        start,
                        (track_x, y1),
                        (track_x, y2),
                        end
                    ]

                    # Добавляем горизонтальные сегменты в общий список
                    horizontal_tracks.append((y1, min(start[0], track_x), max(start[0], track_x)))
                    horizontal_tracks.append((y2, min(track_x, end[0]), max(track_x, end[0])))

                    all_routes.append((route, src, dest))
                    continue

                # Если есть препятствие на горизонтальном пути - строим 5-сегментный маршрут
                obstacle_box = obstacle.get_bounding_box()

                # 1. Горизонтальный сегмент до препятствия
                point1 = (safe_x, start[1])

                # 2. Вертикальный сегмент вверх над препятствием
                safe_y_above = obstacle_box[1] - GOST["vertical_clearance"]

                # Проверяем, не пересекаем ли другие элементы при подъеме
                current_y = start[1]
                while current_y > safe_y_above:
                    clear_path = True
                    for elem in elements:
                        if elem.type == 'INPUT':
                            continue

                        elem_level = next((l for l, es in levels.items() if elem in es), -1)
                        if src_level <= elem_level <= dest_level:
                            box = elem.get_bounding_box()
                            if (box[0] <= safe_x <= box[2] and
                                    min(current_y, safe_y_above) <= box[3] and
                                    max(current_y, safe_y_above) >= box[1]):
                                clear_path = False
                                safe_y_above = box[1] - GOST["vertical_clearance"]
                                break

                    if clear_path:
                        break

                point2 = (safe_x, safe_y_above)

                # 3. Горизонтальный сегмент до нужного слоя
                layer_x = 120 + dest_level * GOST["layer_spacing"] - GOST["horizontal_gap"]
                point3 = (layer_x, safe_y_above)

                # 4. Вертикальный сегмент вниз до высоты входа
                point4 = (layer_x, end[1])

                # 5. Горизонтальный сегмент к элементу
                route = [
                    start,  # Начало
                    point1,  # 1. Горизонтальный до препятствия
                    point2,  # 2. Вертикальный вверх
                    point3,  # 3. Горизонтальный до слоя
                    point4,  # 4. Вертикальный вниз
                    end  # 5. Горизонтальный к элементу
                ]

                # Проверяем третий горизонтальный сегмент (point2 -> point3) на пересечение с другими треками
                current_y = safe_y_above
                test_seg = (current_y, min(safe_x, layer_x), max(safe_x, layer_x))

                while any(horizontal_segments_overlap(test_seg, existing) for existing in horizontal_tracks):
                    current_y += GOST["track_separation"]
                    test_seg = (current_y, min(safe_x, layer_x), max(safe_x, layer_x))

                # Обновляем Y-координату для сегментов 2, 3, 4
                point2 = (safe_x, current_y)
                point3 = (layer_x, current_y)
                point4 = (layer_x, end[1])

                route = [
                    start,
                    point1,
                    point2,
                    point3,
                    point4,
                    end
                ]

                # Добавляем горизонтальные сегменты в общий список
                horizontal_tracks.append((start[1], min(start[0], safe_x), max(start[0], safe_x)))
                horizontal_tracks.append((current_y, min(safe_x, layer_x), max(safe_x, layer_x)))
                horizontal_tracks.append((end[1], min(layer_x, end[0]), max(layer_x, end[0])))

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