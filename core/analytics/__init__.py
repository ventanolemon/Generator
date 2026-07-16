"""
Клиент аналитики (десктоп): агрегаты успеваемости преподавателя/админа.

Протокол — generator_service (GenerationWeb) через web_layer тем же base_url,
что синк/контур/админка: GET /analytics/overview?range_days=&group=.
Идентичность обязательна (аналитика — данные о людях); доступно
преподавателям и администраторам (скоуп считает сервер по владению
предметами: teacher — свои + системные, admin — все).

Чистый Python без Qt (транспорт — urllib или инжектируемый callable).
"""

from .client import AnalyticsClient, AnalyticsError

__all__ = ["AnalyticsClient", "AnalyticsError"]
