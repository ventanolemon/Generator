"""
Адаптеры модуля физики.

Физика — конструктор: каждый раздел в БД хранит свой JSON-конфиг
в поле generation_parametrs. Один и тот же FisicConstructorGenerator
обслуживает все физические разделы — он получает конфиг через
configure() при создании из реестра.
"""

from __future__ import annotations
import json

from core import (
    TaskGenerator, StaticTask, TextBlock, Capability, STATIC_DEFAULT
)
from .fisic_generater import generate_fisic_task


class FisicConstructorGenerator(TaskGenerator):
    """
    Универсальный генератор для физических задач.

    Принимает JSON-конфиг (поле generation_parametrs из БД)
    через configure(). Каждый раздел физики использует свой инстанс
    с разным конфигом, поэтому используется как фабрика, не как готовый объект.
    """

    name = "Физическая задача"
    capabilities = STATIC_DEFAULT

    def __init__(self, partition_id: int, name: str, config: str):
        self.partition_id = partition_id
        self.name = name
        # Прогоняем входной конфиг через нормализатор: если это валидный JSON
        # с известной структурой — приведём числа к float и отфильтруем
        # строковые значения в forbidden. Если нет — оставим как есть.
        self._config = self._normalize_raw(config)

    @staticmethod
    def _normalize_raw(raw: str) -> str:
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return raw
        if not isinstance(data, dict):
            return raw
        return json.dumps(
            FisicConstructorGenerator._normalize_config(data),
            ensure_ascii=False,
        )

    def configure(self, params: dict) -> None:
        # Конфиг приходит из БД через Repository как dict (после json.loads).
        # generate_fisic_task ожидает JSON-строку, поэтому сериализуем обратно.
        # При этом нормализуем числовые поля: в БД встречаются "0" вместо 0
        # в forbidden и т.п. — приводим всё к float, иначе старый генератор падает.
        if "raw" in params:
            try:
                params = json.loads(params["raw"])
            except (json.JSONDecodeError, TypeError):
                self._config = params["raw"]
                return

        normalized = self._normalize_config(params) if params else params
        if normalized:
            self._config = json.dumps(normalized, ensure_ascii=False)

    @staticmethod
    def _normalize_config(cfg: dict) -> dict:
        """
        Привести числовые поля к float и убрать строки из forbidden.
        Делается копия, оригинальный dict не мутируется.
        """
        if not isinstance(cfg, dict):
            return cfg
        out = dict(cfg)
        variables = out.get("variables")
        if isinstance(variables, dict):
            new_vars = {}
            for vname, vinfo in variables.items():
                if not isinstance(vinfo, dict):
                    new_vars[vname] = vinfo
                    continue
                v = dict(vinfo)
                # min / max → float
                for key in ("min", "max"):
                    if key in v:
                        try:
                            v[key] = float(v[key])
                        except (TypeError, ValueError):
                            v[key] = 0.0
                # forbidden: список — каждый элемент в float; не-числа отбрасываем
                forbidden = v.get("forbidden", [])
                if not isinstance(forbidden, list):
                    forbidden = [forbidden]
                cleaned = []
                for item in forbidden:
                    try:
                        cleaned.append(float(item))
                    except (TypeError, ValueError):
                        # пустые строки и мусор — игнорируем
                        continue
                v["forbidden"] = cleaned
                new_vars[vname] = v
            out["variables"] = new_vars
        return out

    def generate(self) -> StaticTask:
        condition, solution = generate_fisic_task(self._config)
        return StaticTask(
            statement=[TextBlock(condition)],
            answer=[TextBlock(solution)],
            meta={"partition_id": self.partition_id},
        )


def make_factory():
    """
    Возвращает фабрику для регистрации в GeneratorRegistry.

    Используется так:
        registry.register_factory(partition_id, factory_for(partition))
    """
    def factory(partition_id: int, partition_name: str, raw_config: str):
        return FisicConstructorGenerator(
            partition_id=partition_id,
            name=partition_name,
            config=raw_config,
        )
    return factory
