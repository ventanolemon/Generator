"""
GraphScene — сцена редактора. Держит GraphDocument и зеркалит его в графические
элементы. Тянет провода мышью, удаляет выделенное, принимает drop из палитры.

GraphCanvasView — QGraphicsView с зумом колесом и панорамой.
"""

from __future__ import annotations
import json
from typing import Optional

from PyQt6.QtCore import QPointF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import (
    QGraphicsScene, QGraphicsView, QGraphicsPathItem, QMenu,
)

from core.graph import DocEdge, GraphDocument, find_converter, is_compatible
from core.graph.routing import EdgeSpec, route_edges

from . import style
from .comment import CommentItem
from .frame import FRAMEABLE_TYPES, InnerNodeItem, LoopFrameItem, make_frame_item
from .items import EdgeItem, NodeItem, PortItem, can_connect


class GraphScene(QGraphicsScene):
    """Сцена, отражающая GraphDocument."""

    changed_doc = pyqtSignal()          # граф изменился (узел/провод add/remove)
    selection_node = pyqtSignal(object) # выбран узел (node_id) или None

    def __init__(self, doc: Optional[GraphDocument] = None, parent=None):
        super().__init__(parent)
        self.doc = doc or GraphDocument()
        self.registry = self.doc.registry
        self._entries = {e["type_id"]: e for e in self.registry.palette()}
        self.node_items: dict[str, NodeItem] = {}
        self.edge_items: list[EdgeItem] = []
        self.comment_items: dict[str, CommentItem] = {}
        # Форма проводов: ортогональная (основной режим, по умолчанию) или
        # кубическая. Читается EdgeItem.update_path; хранится в meta, поэтому
        # переживает сохранение. Трассы ортогональных проводов кладёт
        # совместный роутер (core/graph/routing.py, см. _do_reroute).
        self.orthogonal_edges = True
        self._reroute_pending = False
        # Подсветка веток «условие»/«ответ» — режим ЧТЕНИЯ, поэтому
        # включается, а не живёт всегда: при разводке нужнее цвет типа
        # порта, при разборе чужого графа — ветка, и в одном цвете они не
        # совмещаются. В meta не пишется: это настройка ГЛАЗ, а не графа,
        # и уехав по синку она меняла бы вид холста у другого человека.
        self.show_branches = False
        self._branch_map = None
        # Точки ветвления сетей — их считает роутер (§7.2 плана), а сцена
        # только рисует. Отдельной сущности в документе для них нет и не
        # заводится: это геометрия укладки, а не часть графа, и попав в
        # документ она засорила бы диффы синка.
        self._junction_items: list = []

        self.setBackgroundBrush(style.SCENE_BG)
        self.setSceneRect(0, 0, 2400, 1600)

        # временный провод при протягивании
        self._drag_from: Optional[PortItem] = None
        self._temp_edge: Optional[QGraphicsPathItem] = None

        self.selectionChanged.connect(self._on_selection)
        # Любое изменение графа может сменить финальный узел — обновляем метки.
        self.changed_doc.connect(self._update_result_marks)
        # …и потребовать перекладки трасс (добавление/удаление проводов,
        # пересборка портов). Коалесцируется в request_reroute.
        self.changed_doc.connect(self.request_reroute)
        self.rebuild()

    # ---------- Полная перерисовка из модели ----------

    def rebuild(self) -> None:
        self.blockSignals(True)
        self.clear()
        self.node_items.clear()
        self.edge_items.clear()
        self.comment_items.clear()
        # Форма проводов — из meta (переживает сохранение/undo). Ортогональ —
        # режим по умолчанию: явный False в meta выключает.
        self.orthogonal_edges = bool(self.doc.meta.get("orthogonal_edges", True))
        for c in self.doc.comments():
            self._spawn_comment_item(c.get("id"))
        for nid in self.doc.nodes:
            self._spawn_node_item(nid)
        for e in list(self.doc.edges):
            self._spawn_edge_item(e.from_node, e.from_port, e.to_node, e.to_port)
        self.blockSignals(False)
        self._update_result_marks()
        self.request_reroute()

    # ---------- Рамки-комментарии (аннотации) ----------

    def _spawn_comment_item(self, comment_id: str) -> Optional[CommentItem]:
        if not comment_id:
            return None
        item = CommentItem(self.doc, comment_id)
        self.addItem(item)
        self.comment_items[comment_id] = item
        return item

    def add_comment(self, pos: QPointF) -> CommentItem:
        """Создать рамку-комментарий с левым-верхним углом в pos."""
        data = self.doc.add_comment(x=pos.x(), y=pos.y())
        item = self._spawn_comment_item(data["id"])
        self.changed_doc.emit()
        return item

    def _remove_comment_item(self, item: CommentItem) -> None:
        self.doc.remove_comment(item.comment_id)
        self.comment_items.pop(item.comment_id, None)
        if item.scene():
            self.removeItem(item)

    # ---------- Форма проводов ----------

    def set_orthogonal(self, flag: bool) -> None:
        """Переключить провода между ортогональной (основной) и кубической
        формой. Ортогональ — умолчание, поэтому в meta пишется явный False."""
        flag = bool(flag)
        if flag == self.orthogonal_edges:
            return
        self.orthogonal_edges = flag
        if flag:
            self.doc.meta.pop("orthogonal_edges", None)
        else:
            self.doc.meta["orthogonal_edges"] = False
        for e in self.edge_items:
            e.update_path()
        for f in self.frames():
            for e in f.inner_edges:
                e.update_path()
        self.request_reroute()
        self.changed_doc.emit()

    # ---------- Ветки «условие» и «ответ» ----------

    def set_show_branches(self, flag: bool) -> None:
        """Включить/выключить подсветку веток задания."""
        flag = bool(flag)
        if flag == self.show_branches:
            return
        self.show_branches = flag
        self.refresh_branches()

    def refresh_branches(self) -> None:
        """
        Пересчитать ветки и перерисовать холст.

        Пересчёт целиком, без попыток обновить точечно: ветка узла зависит
        от ВСЕГО пути до финала, поэтому один новый провод способен
        перекрасить половину графа — «затронутые» узлы тут и есть весь
        граф.
        """
        self._branch_map = self.doc.branches() if self.show_branches else None
        for item in self.node_items.values():
            item.update()
        for e in self.edge_items:
            e.update()
        for f in self.frames():
            for e in f.inner_edges:
                e.update()

    def branch_of_node(self, node_id: str):
        return self._branch_map.nodes.get(node_id) if self._branch_map else None

    def branch_of_edge(self, edge_tuple):
        if not self._branch_map:
            return None
        src_node, src_port, dst_node, dst_port = edge_tuple
        key = f"{src_node}:{src_port}->{dst_node}:{dst_port}"
        return self._branch_map.edges.get(key)

    # ---------- Совместная укладка ортогональных проводов ----------

    def request_reroute(self) -> None:
        """Переложить трассы всех проводов (коалесцируется на тик событий:
        перенос узла двигает десятки проводов — роутер зовём один раз)."""
        if self._reroute_pending or not self.orthogonal_edges:
            return
        self._reroute_pending = True
        QTimer.singleShot(0, self._do_reroute)

    def _do_reroute(self) -> None:
        self._reroute_pending = False
        if not self.orthogonal_edges:
            return
        # Препятствия: тела узлов верхнего уровня и рамки циклов целиком
        # (внутренние узлы накрыты рамкой). Провода внутри рамок роутер не
        # трогает — у них локальная геометрия и одиночный фолбэк.
        rects: dict[str, tuple] = {}
        for nid, item in self.node_items.items():
            r = item.sceneBoundingRect()
            rects[nid] = (r.x(), r.y(), r.width(), r.height())

        specs: list[EdgeSpec] = []
        for e in self.edge_items:
            p1 = e.src.scene_center()
            p2 = e.dst.scene_center()
            # Ручные перегибы живут в meta документа, а не в проводе
            # (§7.2): конфликт синка по расположению безвреден, по
            # логике — осмыслен, и смешивать их нельзя. Сюда они
            # приезжают только на время укладки.
            bends = self.doc.edge_bends(
                e.src.node_id, e.src.port.name,
                e.dst.node_id, e.dst.port.name)
            specs.append(EdgeSpec(
                key=id(e),
                src=(p1.x(), p1.y()),
                dst=(p2.x(), p2.y()),
                net=(e.src.node_id, e.src.port.name),
                src_node=e.src.node_id,
                dst_node=e.dst.node_id,
                bends=tuple((p[0], p[1]) for p in bends),
            ))

        result = route_edges(rects, specs)
        for e in self.edge_items:
            e.set_route(result.routes.get(id(e)))
        self._draw_junctions(result.junctions)

    def _draw_junctions(self, by_net: dict) -> None:
        """
        Кружки в местах, где сеть расходится.

        Без них веер читается как несколько проводов, случайно легших
        друг на друга: развилка и перекрёсток выглядят одинаково, а это
        разные вещи — в одном месте сигнал ветвится, в другом просто
        пересекаются два чужих провода.

        Цвет берётся у самой сети: точка принадлежит сигналу, а не
        холсту, и серый кружок на цветном проводе читался бы как чужой.
        """
        for item in self._junction_items:
            self.removeItem(item)
        self._junction_items.clear()
        if not by_net:
            return

        colors = {(e.src.node_id, e.src.port.name): style.port_color(e.src.port.type)
                  for e in self.edge_items}
        radius = 4.0
        for net, points in by_net.items():
            color = colors.get(net)
            if color is None:
                continue
            for (x, y) in points:
                dot = self.addEllipse(x - radius, y - radius, 2 * radius,
                                      2 * radius, QPen(color, 1.0), color)
                # Над проводами, но под узлами: точка обязана быть видна
                # на проводе и не наезжать на тела.
                dot.setZValue(0.5)
                self._junction_items.append(dot)

    # ---------- Раскладка узлов по слоям ----------

    def auto_layout_layers(self) -> None:
        """Расставить узлы холста по слоям (источники слева → потребители
        справа) и синхронизировать графические элементы с моделью."""
        pos = self.doc.apply_layered_layout()
        for nid, (x, y) in pos.items():
            item = self.node_items.get(nid)
            if item is not None:
                item.setPos(x, y)
        for e in self.edge_items:
            e.update_path()
        self.changed_doc.emit()

    def _update_result_marks(self) -> None:
        """
        Пометить узлы относительно финала графа: единственный свободный выход
        TASK — финал («ВЫХОД»), несколько — конфликт, а во вложенном теле
        цикла/ветви любой узел-задание запрещён.
        """
        if getattr(self.doc, "is_subgraph", False):
            roles = {nid: "forbidden" for nid in self.doc.task_node_ids()}
        else:
            sinks = self.doc.task_sink_ids()
            if len(sinks) == 1:
                roles = {sinks[0]: "result"}
            else:
                roles = {nid: "conflict" for nid in sinks}
        for nid, item in self.node_items.items():
            item.set_result_role(roles.get(nid))
        # Ветки считаются от финала — значит, пересчитывать их надо там же,
        # где пересчитывается сам финал. Отдельного вызова у правок графа
        # нет и заводить его нельзя: забытая ветвь означала бы устаревшую
        # раскраску, то есть ровно ту ложь, ради ухода от которой ветку и
        # решили не хранить.
        if self.show_branches:
            self.refresh_branches()
        # Внутри рамок циклов узлы-задания запрещены (это тела-подграфы).
        for f in self.frames():
            inner_roles = {nid: "forbidden" for nid in f.body_doc.task_node_ids()}
            for nid, item in f.inner_nodes.items():
                item.set_result_role(inner_roles.get(nid))

    def _spawn_node_item(self, node_id: str) -> NodeItem:
        node = self.doc.nodes[node_id]
        entry = self._entries[node.type]
        # Развёрнутый цикл — рамка-структура с телом внутри; битое тело
        # (или невозможность создать рамку) откатывает к компактному узлу.
        if node.type in FRAMEABLE_TYPES and self.doc.is_node_expanded(node_id):
            frame = make_frame_item(self.doc, node_id, entry)
            if frame is not None:
                self.addItem(frame)
                frame.populate(self)
                self.node_items[node_id] = frame
                return frame
        item = NodeItem(self.doc, node_id, entry)
        self.addItem(item)
        self.node_items[node_id] = item
        return item

    # ---------- Рамки циклов ----------

    def set_frame_expanded(self, node_id: str, expanded: bool) -> None:
        """Развернуть цикл в рамку на холсте / свернуть обратно в узел."""
        node = self.doc.nodes.get(node_id)
        if node is None or node.type not in FRAMEABLE_TYPES:
            return
        if self.doc.is_node_expanded(node_id) == expanded:
            return
        self.doc.set_node_expanded(node_id, expanded)
        self.rebuild()
        again = self.node_items.get(node_id)
        if again is not None:
            again.setSelected(True)
        self.changed_doc.emit()

    def frames(self) -> list[LoopFrameItem]:
        return [it for it in self.node_items.values()
                if isinstance(it, LoopFrameItem)]

    def frame_of_inner(self, item: NodeItem) -> Optional[LoopFrameItem]:
        return item.frame if isinstance(item, InnerNodeItem) else None

    def find_frame_by_body(self, body_doc) -> Optional[LoopFrameItem]:
        for f in self.frames():
            if f.body_doc is body_doc:
                return f
        return None

    def commit_frames(self) -> None:
        """Сериализовать тела всех развёрнутых рамок обратно в params."""
        for f in self.frames():
            f.commit_body()

    def all_node_items(self) -> list[NodeItem]:
        """Все элементы-узлы: корневые, рамки и внутренние узлы рамок."""
        out: list[NodeItem] = list(self.node_items.values())
        for f in self.frames():
            out.extend(f.inner_nodes.values())
        return out

    def all_movable_items(self) -> list:
        """Всё, что можно перетаскивать (узлы + комментарии) — для фиксации
        перемещения в истории по отпусканию мыши."""
        return self.all_node_items() + list(self.comment_items.values())

    def add_node_to_frame(self, frame: LoopFrameItem, type_id: str) -> NodeItem:
        item = frame.add_inner_node(self, type_id)
        self.changed_doc.emit()
        return item

    def target_frame_for_add(self) -> Optional[LoopFrameItem]:
        """Рамка-адресат для добавления из палитры: выделена сама или её узел."""
        for it in self.selectedItems():
            if isinstance(it, LoopFrameItem):
                return it
            if isinstance(it, InnerNodeItem):
                return it.frame
        return None

    def _find_port(self, node_id: str, port_name: str, is_output: bool) -> Optional[PortItem]:
        item = self.node_items.get(node_id)
        if item is None:
            return None
        ports = item.out_ports if is_output else item.in_ports
        for p in ports:
            if p.port.name == port_name:
                return p
        return None

    def _spawn_edge_item(self, fn, fp, tn, tp) -> Optional[EdgeItem]:
        src = self._find_port(fn, fp, is_output=True)
        dst = self._find_port(tn, tp, is_output=False)
        if src is None or dst is None:
            return None
        edge = EdgeItem(src, dst)
        self.addItem(edge)
        self.edge_items.append(edge)
        src.node_item.edges.append(edge)
        dst.node_item.edges.append(edge)
        return edge

    # ---------- Добавление узла (из палитры) ----------

    def add_node(self, type_id: str, pos: QPointF) -> NodeItem:
        node = self.doc.add_node(type_id, x=pos.x(), y=pos.y())
        item = self._spawn_node_item(node.id)
        self.changed_doc.emit()
        return item

    # ---------- Удаление выделенного ----------

    def delete_selected(self) -> None:
        removed = False
        for it in list(self.selectedItems()):
            if isinstance(it, CommentItem):
                self._remove_comment_item(it)
                removed = True
            elif isinstance(it, InnerNodeItem):
                if it.scene():                    # мог уйти вместе с рамкой
                    it.frame.remove_inner_node(self, it)
                    removed = True
            elif isinstance(it, NodeItem):
                self._remove_node_item(it)
                removed = True
            elif isinstance(it, EdgeItem):
                if it.scene():
                    owner = self._inner_edge_owner(it)
                    if owner is not None:
                        owner.remove_inner_edge(self, it)
                    else:
                        self._remove_edge_item(it)
                    removed = True
        if removed:
            self.changed_doc.emit()

    def _inner_edge_owner(self, edge: EdgeItem) -> Optional[LoopFrameItem]:
        for f in self.frames():
            if edge in f.inner_edges:
                return f
        return None

    def _remove_node_item(self, item: NodeItem) -> None:
        if isinstance(item, LoopFrameItem):
            item.clear_inner(self)
        for e in list(item.edges):
            self._remove_edge_item(e)
        self.doc.remove_node(item.node_id)
        self.node_items.pop(item.node_id, None)
        if item.scene():
            self.removeItem(item)

    # ---------- Копирование / вставка ----------

    def copy_selection(self) -> dict | None:
        """
        Снимок выделенных узлов и проводов МЕЖДУ ними (для буфера обмена).
        Провода к невыделенным узлам не копируются. None — если ничего не выбрано.
        """
        sel_ids = [it.node_id for it in self.selectedItems()
                   if isinstance(it, NodeItem) and not it.is_inner]
        if not sel_ids:
            return None
        sel = set(sel_ids)
        nodes = []
        for nid in sel_ids:
            n = self.doc.nodes[nid]
            nodes.append({"id": n.id, "type": n.type,
                          "params": json.loads(json.dumps(n.params)),
                          "x": n.x, "y": n.y})
        edges = [
            {"from_node": e.from_node, "from_port": e.from_port,
             "to_node": e.to_node, "to_port": e.to_port}
            for e in self.doc.edges
            if e.from_node in sel and e.to_node in sel
        ]
        return {"nodes": nodes, "edges": edges}

    def paste(self, clip: dict, dx: float = 30.0, dy: float = 30.0) -> list[str]:
        """
        Вставить узлы из буфера со свежими id и сдвигом. Возвращает новые id
        (их выделяем). Внутренние провода переносятся на новые id.
        """
        if not clip or not clip.get("nodes"):
            return []
        id_map: dict[str, str] = {}
        new_items: list[NodeItem] = []
        for n in clip["nodes"]:
            new_id = self.doc.unique_id(n["type"])
            id_map[n["id"]] = new_id
            self.doc.add_node(n["type"], params=dict(n.get("params") or {}),
                              x=float(n.get("x", 0)) + dx,
                              y=float(n.get("y", 0)) + dy, node_id=new_id)
            new_items.append(self._spawn_node_item(new_id))
        for e in clip.get("edges", []):
            fn = id_map.get(e["from_node"]); tn = id_map.get(e["to_node"])
            if fn and tn:
                self.doc.add_edge(fn, e["from_port"], tn, e["to_port"])
                self._spawn_edge_item(fn, e["from_port"], tn, e["to_port"])
        # Выделяем вставленное (удобно тащить дальше).
        self.clearSelection()
        for it in new_items:
            it.setSelected(True)
        if new_items:
            self.changed_doc.emit()
        return list(id_map.values())

    def select_all(self) -> None:
        """Выделить все узлы и провода на холсте."""
        for it in self.node_items.values():
            it.setSelected(True)
        for e in self.edge_items:
            e.setSelected(True)

    def _remove_edge_item(self, edge: EdgeItem) -> None:
        fn, fp, tn, tp = edge.as_doc_tuple()
        self.doc.remove_edge(DocEdge(fn, fp, tn, tp))
        for owner in (edge.src.node_item, edge.dst.node_item):
            if edge in owner.edges:
                owner.edges.remove(edge)
        if edge in self.edge_items:
            self.edge_items.remove(edge)
        if edge.scene():
            self.removeItem(edge)

    # ---------- Протягивание провода ----------

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            port = self._port_at(event.scenePos())
            if port is not None:
                self._drag_from = port
                self._temp_edge = QGraphicsPathItem()
                self._temp_edge.setPen(QPen(style.port_color(port.port.type), 2, Qt.PenStyle.DashLine))
                self._temp_edge.setZValue(3)
                self.addItem(self._temp_edge)
                self._apply_drag_highlights(port)
                event.accept()
                return
        super().mousePressEvent(event)

    # ---------- Подсветка совместимых портов при протягивании ----------

    def _all_port_items(self) -> list[PortItem]:
        return [it for it in self.items() if isinstance(it, PortItem)]

    def _drop_kind(self, drag_from: PortItem, cand: PortItem):
        """Совместимость кандидата с источником drag: 'ok' | 'convert' | None."""
        if cand is drag_from or cand.is_output == drag_from.is_output:
            return None
        out_p, in_p = ((drag_from, cand) if drag_from.is_output else (cand, drag_from))
        if out_p.node_id == in_p.node_id:
            return None
        # Провод через границу рамки невозможен (как в _commit_connection).
        if self.frame_of_inner(out_p.node_item) is not self.frame_of_inner(in_p.node_item):
            return None
        if is_compatible(out_p.port.type, in_p.port.type):
            return "ok"
        if find_converter(out_p.port.type, in_p.port.type):
            return "convert"
        return None

    def _apply_drag_highlights(self, drag_from: PortItem) -> None:
        for p in self._all_port_items():
            p.set_drop_highlight(self._drop_kind(drag_from, p))

    def _clear_drag_highlights(self) -> None:
        for p in self._all_port_items():
            p.set_drop_highlight(None)

    def mouseMoveEvent(self, event):
        if self._temp_edge is not None and self._drag_from is not None:
            p1 = self._drag_from.scene_center()
            p2 = event.scenePos()
            dx = max(40.0, abs(p2.x() - p1.x()) * 0.5)
            path = QPainterPath(p1)
            path.cubicTo(p1.x() + dx, p1.y(), p2.x() - dx, p2.y(), p2.x(), p2.y())
            self._temp_edge.setPath(path)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._temp_edge is not None and self._drag_from is not None:
            self.removeItem(self._temp_edge)
            self._temp_edge = None
            self._clear_drag_highlights()
            target = self._port_at(event.scenePos())
            drag_from = self._drag_from
            self._drag_from = None
            if can_connect(drag_from, target):
                self._commit_connection(drag_from, target)
            elif target is not None and self._drop_kind(drag_from, target) == "convert":
                self._suggest_converter(drag_from, target, event)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    # ---------- Вставка узла-конвертера ----------

    def _converter_ports(self, type_id: str, src_type, dst_type):
        """Вход (совместимый с src) и выход (совместимый с dst) узла-конвертера."""
        ins, outs = self.doc.safe_ports(type_id, {})
        inp = next((p for p in ins if is_compatible(src_type, p.type)), None)
        outp = next((p for p in outs if is_compatible(p.type, dst_type)), None)
        return inp, outp

    def _suggest_converter(self, drag_from: PortItem, target: PortItem, event) -> None:
        out_p, in_p = ((drag_from, target) if drag_from.is_output
                       else (target, drag_from))
        # Вставка в тело рамки пока не поддержана — подсказку не показываем.
        if (self.frame_of_inner(out_p.node_item) is not None
                or self.frame_of_inner(in_p.node_item) is not None):
            return
        type_id = find_converter(out_p.port.type, in_p.port.type)
        if type_id is None:
            return
        entry = self._entries.get(type_id, {})
        name = entry.get("display_name", type_id)
        menu = QMenu()
        act = menu.addAction(
            f"Вставить «{name}» ({out_p.port.type.value} → {in_p.port.type.value})"
        )
        if menu.exec(event.screenPos()) is act:
            self.insert_converter(out_p, in_p, type_id)

    def insert_converter(self, out_port: PortItem, in_port: PortItem,
                         type_id: str) -> bool:
        """Вставить узел-конвертер между выходом out_port и входом in_port."""
        inp, outp = self._converter_ports(type_id, out_port.port.type,
                                          in_port.port.type)
        if inp is None or outp is None:
            return False
        n_out = self.doc.nodes[out_port.node_id]
        n_in = self.doc.nodes[in_port.node_id]
        node = self.doc.add_node(type_id, x=(n_out.x + n_in.x) / 2,
                                 y=(n_out.y + n_in.y) / 2)
        self._spawn_node_item(node.id)
        # Вытеснить старый провод на этом входе.
        for e in list(self.edge_items):
            if e.dst.node_id == in_port.node_id and e.dst.port.name == in_port.port.name:
                self._remove_edge_item(e)
        self.doc.add_edge(out_port.node_id, out_port.port.name, node.id, inp.name)
        self.doc.add_edge(node.id, outp.name, in_port.node_id, in_port.port.name)
        # add_edge уже мог протолкнуть типы дальше по цепочке (см.
        # GraphDocument.propagate_types_from_node) — перерисовываем сцену из
        # модели целиком, а не точечно, чтобы отразить любые каскадные правки.
        self.doc.prune_invalid_edges()
        self.rebuild()
        self.changed_doc.emit()
        return True

    def _commit_connection(self, a: PortItem, b: PortItem) -> None:
        src, dst = (a, b) if a.is_output else (b, a)
        # Контексты концов: None — корневой холст, рамка — её тело. Провод
        # через границу рамки невозможен — это делают туннели (imports/outputs).
        src_frame = self.frame_of_inner(src.node_item)
        dst_frame = self.frame_of_inner(dst.node_item)
        if src_frame is not dst_frame:
            return
        if src_frame is not None:
            src_frame.add_inner_edge(self, src, dst)
            self.changed_doc.emit()
            return
        # вытеснить существующий провод на этом входе (модель + сцена)
        for e in list(self.edge_items):
            if e.dst.node_id == dst.node_id and e.dst.port.name == dst.port.name:
                self._remove_edge_item(e)
        self.doc.add_edge(src.node_id, src.port.name, dst.node_id, dst.port.name)
        # Новый провод мог ретайпить узел(ы) дальше по цепочке (elem_type и
        # т.п., см. GraphDocument.propagate_types_from_node внутри add_edge) —
        # перестраиваем сцену из модели целиком, чтобы это увидеть сразу, без
        # отдельного клика по инспектору.
        self.doc.prune_invalid_edges()
        self.rebuild()
        self.changed_doc.emit()

    def mouseDoubleClickEvent(self, event):
        # Двойной клик по проводу — подписать его. Провода проверяются
        # ПЕРВЫМИ: узел под курсором двойной клик уже занимает (разворот
        # тела цикла), а провод не занимал ничего.
        edge = next((it for it in self.items(event.scenePos())
                     if isinstance(it, EdgeItem)), None)
        if edge is not None:
            self.edit_edge_note(edge)
            event.accept()
            return
        # Двойной клик по компактному узлу цикла — развернуть в рамку.
        for it in self.items(event.scenePos()):
            node = self._climb_to_node(it)
            if node is None:
                continue
            if (not node.is_frame and not node.is_inner
                    and self.doc.nodes.get(node.node_id) is not None
                    and self.doc.nodes[node.node_id].type in FRAMEABLE_TYPES):
                from PyQt6.QtCore import QTimer
                nid = node.node_id
                QTimer.singleShot(0, lambda n=nid: self.set_frame_expanded(n, True))
                event.accept()
                return
            break
        super().mouseDoubleClickEvent(event)

    def edit_edge_note(self, edge: EdgeItem) -> None:
        """
        Спросить подпись провода и записать её в документ.

        Диалогом, а не полем прямо на холсте: подпись правят редко (это
        пояснение, а не параметр), а поле поверх трассы пришлось бы
        перекладывать вместе с ней на каждом движении узла.
        """
        from PyQt6.QtWidgets import QInputDialog
        tup = edge.as_doc_tuple()
        current = self.doc.edge_note(*tup)
        text, ok = QInputDialog.getText(
            None, "Подпись провода",
            f"{tup[0]}:{tup[1]} → {tup[2]}:{tup[3]}",
            text=current)
        if not ok or text.strip() == current:
            return
        self.doc.set_edge_note(*tup, text)
        edge.prepareGeometryChange()
        edge.update()
        self.changed_doc.emit()

    def _port_at(self, scene_pos: QPointF) -> Optional[PortItem]:
        for it in self.items(scene_pos):
            if isinstance(it, PortItem):
                return it
        return None

    # ---------- Параметры узла изменились извне (инспектор) ----------

    def refresh_node(self, node_id: str) -> None:
        if node_id not in self.node_items:
            return
        # Если изменённый параметр был TYPE_PARAM узла (elem_type/value_type/
        # type), протолкнуть новый тип по подключённым проводам ПЕРЕД
        # обрезкой — иначе prune_invalid_edges снёс бы провод, который
        # проброс типа как раз делает снова валидным (см.
        # GraphDocument.propagate_types_from_node).
        self.doc.propagate_types_from_node(node_id)
        # Смена динамических портов могла сделать часть рёбер висячими —
        # обрезаем их в модели и полностью перерисовываем сцену из модели.
        self.doc.prune_invalid_edges()
        self.rebuild()
        # Сохраняем выделение узла, чтобы инспектор продолжал его показывать.
        again = self.node_items.get(node_id)
        if again is not None:
            again.setSelected(True)
        self.changed_doc.emit()

    def refresh_inner_node(self, frame: LoopFrameItem, node_id: str) -> None:
        """Перестроить тело рамки после смены портов внутреннего узла."""
        frame.refresh_inner(self, node_id)
        again = frame.inner_nodes.get(node_id)
        if again is not None:
            again.setSelected(True)
        self._update_result_marks()
        self.changed_doc.emit()

    def _on_selection(self) -> None:
        """Выбран один узел → (его документ, id): внутренние узлы рамок
        принадлежат документу тела, остальные — документу холста."""
        sel = [it for it in self.selectedItems() if isinstance(it, NodeItem)]
        if len(sel) != 1:
            self.selection_node.emit(None)
            return
        item = sel[0]
        owner = item.frame.body_doc if isinstance(item, InnerNodeItem) else self.doc
        self.selection_node.emit((owner, item.node_id))

    # ---------- Порядок наложения узлов (z-order) ----------

    def _normalize_z(self) -> None:
        """
        Пере-нумеровать узлы целыми z = 1..N в текущем порядке наложения
        (по zValue, затем по порядку вставки). Провода остаются на z=0 —
        узлы всегда выше них. Делает шаги вперёд/назад однозначными.
        Рамки циклов — фон (z=0.5) и в нумерации не участвуют.
        """
        items = [it for it in self.node_items.values() if not it.is_frame]
        idx = {it: i for i, it in enumerate(items)}
        ordered = sorted(items, key=lambda it: (it.zValue(), idx[it]))
        for i, it in enumerate(ordered, start=1):
            it.setZValue(float(i))

    def node_to_front(self, item: NodeItem) -> None:
        item.setZValue(len(self.node_items) + 10.0)
        self._normalize_z()

    def node_to_back(self, item: NodeItem) -> None:
        item.setZValue(-10.0)
        self._normalize_z()

    def raise_node(self, item: NodeItem) -> None:
        """На один слой вперёд (выше)."""
        item.setZValue(item.zValue() + 1.5)
        self._normalize_z()

    def lower_node(self, item: NodeItem) -> None:
        """На один слой назад (ниже)."""
        item.setZValue(item.zValue() - 1.5)
        self._normalize_z()

    @staticmethod
    def _climb_to_node(item) -> Optional[NodeItem]:
        while item is not None and not isinstance(item, NodeItem):
            item = item.parentItem()
        return item

    def _canvas_context_menu(self, event) -> None:
        """Меню пустого холста: комментарий и раскладка по слоям."""
        menu = QMenu()
        a_comment = menu.addAction("Добавить комментарий здесь")
        a_layout = menu.addAction("Разложить узлы по слоям")
        chosen = menu.exec(event.screenPos())
        if chosen is a_comment:
            self.add_comment(event.scenePos())
        elif chosen is a_layout:
            self.auto_layout_layers()
        event.accept()

    def _comment_context_menu(self, comment: CommentItem, event) -> None:
        menu = QMenu()
        a_edit = menu.addAction("Изменить текст…")
        a_del = menu.addAction("Удалить комментарий")
        chosen = menu.exec(event.screenPos())
        if chosen is a_edit:
            comment.edit_text()
        elif chosen is a_del:
            self._remove_comment_item(comment)
            self.changed_doc.emit()
        event.accept()

    def contextMenuEvent(self, event):
        node = None
        for it in self.items(event.scenePos()):
            node = self._climb_to_node(it)
            if node is not None:
                break
        if node is None:
            # Комментарий под курсором — его собственное меню.
            comment = next((it for it in self.items(event.scenePos())
                            if isinstance(it, CommentItem)), None)
            if comment is not None:
                self._comment_context_menu(comment, event)
                return
            # Пустой холст — добавить комментарий / разложить по слоям.
            self._canvas_context_menu(event)
            return

        menu = QMenu()
        # Рамка: только свернуть; внутренний узел: без z-операций.
        a_collapse = a_expand = None
        if node.is_frame:
            a_collapse = menu.addAction("Свернуть тело в узел")
        elif (not node.is_inner
              and self.doc.nodes.get(node.node_id) is not None
              and self.doc.nodes[node.node_id].type in FRAMEABLE_TYPES):
            a_expand = menu.addAction("Развернуть тело на холсте")

        a_front = a_back = a_fwd = a_bwd = None
        if not node.is_frame and not node.is_inner:
            if not menu.isEmpty():
                menu.addSeparator()
            a_front = menu.addAction("На передний план")
            a_back = menu.addAction("На задний план")
            menu.addSeparator()
            a_fwd = menu.addAction("Переместить вперёд")
            a_bwd = menu.addAction("Переместить назад")
        if menu.isEmpty():
            event.accept()
            return

        chosen = menu.exec(event.screenPos())
        if chosen is None:
            event.accept()
            return
        if chosen is a_collapse:
            self.set_frame_expanded(node.node_id, False)
        elif chosen is a_expand:
            self.set_frame_expanded(node.node_id, True)
        elif chosen is a_front:
            self.node_to_front(node)
        elif chosen is a_back:
            self.node_to_back(node)
        elif chosen is a_fwd:
            self.raise_node(node)
        elif chosen is a_bwd:
            self.lower_node(node)
        event.accept()


class GraphCanvasView(QGraphicsView):
    """Вид с зумом и панорамой.

    Панорама: зажать пробел — курсор превращается в «руку», ЛКМ тянет холст.
    Отпустить пробел — возврат к рамочному выделению.

    Сочетания клавиш редактирования транслируются сигналами наружу (редактор их
    связывает с undo/redo/copy/paste): сам вид о документе и истории не знает.

    Смена dragMode (рамка ⇄ рука) выполняется ТОЛЬКО при отпущенной ЛКМ:
    переключение во время зажатой кнопки оставляет QGraphicsView в застрявшем
    hand-scroll — тогда узлы перестают двигаться при выделении (это тот самый
    баг: выделил узел, панорамировал холст, а узлы больше не таскаются).
    Желаемый режим хранится в _space_held, применяется _sync_drag_mode() по
    отпусканию кнопки / клавиши / потере фокуса.
    """

    copy_requested = pyqtSignal()
    paste_requested = pyqtSignal()
    undo_requested = pyqtSignal()
    redo_requested = pyqtSignal()
    moved_nodes = pyqtSignal()     # узлы перетащили (по отпусканию ЛКМ)

    def __init__(self, scene: GraphScene, parent=None):
        super().__init__(scene, parent)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self._zoom = 1.0
        self._space_held = False       # зажат ли пробел (желаемый режим — рука)
        self._left_down = False        # зажата ли ЛКМ (нельзя менять dragMode)
        self._press_positions: dict = {}   # для определения реального перемещения

    def _sync_drag_mode(self) -> None:
        """Привести dragMode к желаемому (рука при зажатом пробеле, иначе рамка).

        Пока ЛКМ нажата — откладываем: смена режима на середине жеста оставляет
        Qt в застрявшем hand-scroll, и узлы перестают перетаскиваться."""
        if self._left_down:
            return
        want_pan = self._space_held
        is_pan = self.dragMode() == QGraphicsView.DragMode.ScrollHandDrag
        if want_pan and not is_pan:
            self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
            self.viewport().setCursor(Qt.CursorShape.OpenHandCursor)
        elif not want_pan and is_pan:
            self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
            self.viewport().unsetCursor()

    def wheelEvent(self, event):
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        new_zoom = self._zoom * factor
        if 0.3 <= new_zoom <= 3.0:
            self._zoom = new_zoom
            self.scale(factor, factor)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._left_down = True
        # Запомнить позиции узлов (включая внутренние узлы рамок) до
        # возможного перетаскивания. В режиме панорамы это не перенос — пропуск.
        sc = self.scene()
        if (event.button() == Qt.MouseButton.LeftButton
                and not self._space_held and isinstance(sc, GraphScene)):
            self._press_positions = {
                it: (it.x(), it.y()) for it in sc.all_movable_items()
            }
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        if event.button() == Qt.MouseButton.LeftButton:
            self._left_down = False
        # Если какой-то узел реально сместился — зафиксировать в истории.
        if self._press_positions:
            moved = False
            for it, (px, py) in self._press_positions.items():
                try:
                    if it.scene() is not None and (abs(it.x() - px) > 0.5
                                                   or abs(it.y() - py) > 0.5):
                        moved = True
                        break
                except RuntimeError:
                    continue       # элемент удалён вместе с C++-объектом
            self._press_positions = {}
            if moved:
                self.moved_nodes.emit()
        # Кнопка отпущена — можно применить отложенную смену режима (напр. пробел
        # отпустили ещё во время панорамы).
        self._sync_drag_mode()

    def focusOutEvent(self, event):
        # Потеря фокуса (Alt+Tab, контекстное меню, клик мимо) во время
        # панорамы — Qt не пришлёт keyRelease пробела; принудительно выходим из
        # режима руки, чтобы узлы не «застряли» неподвижными.
        self._space_held = False
        self._left_down = False
        self._sync_drag_mode()
        super().focusOutEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            sc = self.scene()
            if isinstance(sc, GraphScene):
                sc.delete_selected()
                event.accept()
                return
        # Сочетания клавиш редактирования (Ctrl+C/V/Z, Ctrl+Shift+Z).
        mods = event.modifiers()
        ctrl = mods & Qt.KeyboardModifier.ControlModifier
        shift = mods & Qt.KeyboardModifier.ShiftModifier
        if ctrl:
            k = event.key()
            if k == Qt.Key.Key_A:
                sc = self.scene()
                if isinstance(sc, GraphScene):
                    sc.select_all()
                event.accept(); return
            if k == Qt.Key.Key_C:
                self.copy_requested.emit(); event.accept(); return
            if k == Qt.Key.Key_V:
                self.paste_requested.emit(); event.accept(); return
            if k == Qt.Key.Key_Z and not shift:
                self.undo_requested.emit(); event.accept(); return
            if (k == Qt.Key.Key_Z and shift) or k == Qt.Key.Key_Y:
                self.redo_requested.emit(); event.accept(); return
        # Пробел — включить «руку» для панорамы (игнорируем автоповтор).
        if event.key() == Qt.Key.Key_Space and not event.isAutoRepeat():
            self._space_held = True
            self._sync_drag_mode()
            event.accept()
            return
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        # Отпустили пробел — вернуть рамочное выделение и обычный курсор.
        if event.key() == Qt.Key.Key_Space and not event.isAutoRepeat():
            self._space_held = False
            self._sync_drag_mode()
            event.accept()
            return
        super().keyReleaseEvent(event)
