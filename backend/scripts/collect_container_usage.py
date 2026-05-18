#!/usr/bin/env python
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.config import get_settings  # noqa: E402
from app.services.container_usage_service import ContainerUsageService  # noqa: E402


def main() -> int:
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s: %(message)s')
    service = ContainerUsageService(get_settings())
    result = service.collect_all_running()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if result.get('failed') else 0


if __name__ == '__main__':
    raise SystemExit(main())
