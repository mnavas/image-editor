from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

CONFIG_PATH = Path.home() / ".config" / "image-editor" / "config.json"


@dataclass
class Config:
    last_dir: str = ""            # folder of the last opened/saved image
    jpeg_quality: int = 95        # default export quality for JPEG
    proxy_max_side: int = 2000    # longest side of the live-preview proxy

    @staticmethod
    def load() -> "Config":
        if CONFIG_PATH.exists():
            try:
                data = json.loads(CONFIG_PATH.read_text())
                return Config(
                    last_dir=data.get("last_dir", ""),
                    jpeg_quality=data.get("jpeg_quality", 95),
                    proxy_max_side=data.get("proxy_max_side", 2000),
                )
            except Exception:
                pass
        return Config()

    def save(self) -> None:
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(
            json.dumps(
                {
                    "last_dir": self.last_dir,
                    "jpeg_quality": self.jpeg_quality,
                    "proxy_max_side": self.proxy_max_side,
                },
                indent=2,
            )
        )
