import json
from datetime import datetime
from typing import Optional, Any

class Logger:
    def log(self, message: str, type_: str = "info", payload: Optional[Any] = None):
        entry = {
            "timestamp": datetime.now().isoformat(),
            "type": type_,
            "message": message,
            "payload": payload
        }
        print(json.dumps(entry))

logger = Logger()
