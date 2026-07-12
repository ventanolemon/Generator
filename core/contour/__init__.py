"""
Клиент LLM-контура (десктоп): создание джоб, поллинг статуса, approve/reject.

Протокол — contour_service (GenerationWeb): POST /contour/jobs (202, job_id),
GET /contour/jobs/{id} (поллинг 2–5 с), POST .../approve | .../reject.
Десктоп ходит через web_layer тем же base_url, что и синхронизация
(system_topology §5: клиенты не ходят мимо web_layer).

Чистый Python без Qt (транспорт — urllib или инжектируемый callable);
Qt-поллер поверх этого клиента — ui/contour_poller.py.
"""

from .client import ContourClient, ContourError

__all__ = ["ContourClient", "ContourError"]
