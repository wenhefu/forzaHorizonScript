from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import re

from window_capture import Frame


def timestamp_slug() -> str:
    return datetime.now(timezone.utc).astimezone().strftime("%Y%m%d-%H%M%S-%f")[:-3]


def safe_slug(value: str, fallback: str = "sample") -> str:
    text = re.sub(r"[^0-9A-Za-z._-]+", "-", value.strip())[:80].strip("-")
    return text or fallback


def frame_to_pil(frame: Frame):
    import numpy as np
    from PIL import Image

    arr = np.frombuffer(frame.bgra, dtype=np.uint8).reshape((frame.height, frame.width, 4))
    rgba = arr[:, :, [2, 1, 0, 3]]
    return Image.fromarray(rgba, "RGBA")


def pil_to_frame(image) -> Frame:
    import numpy as np

    rgba = image.convert("RGBA")
    arr = np.array(rgba)
    bgra = arr[:, :, [2, 1, 0, 3]].tobytes()
    return Frame(rgba.width, rgba.height, bgra)


def load_frame_from_image(path: str | Path, max_width: int | None = None) -> Frame:
    from PIL import Image

    image = Image.open(path).convert("RGBA")
    if max_width and image.width > max_width:
        scale = max_width / float(image.width)
        image = image.resize((max_width, max(1, int(image.height * scale))))
    return pil_to_frame(image)


def resize_frame(frame: Frame, max_width: int | None = None, scale: float | None = None) -> Frame:
    image = frame_to_pil(frame)
    if max_width and image.width > max_width:
        factor = max_width / float(image.width)
    elif scale:
        factor = float(scale)
    else:
        return frame
    size = (max(1, int(image.width * factor)), max(1, int(image.height * factor)))
    return pil_to_frame(image.resize(size))


def crop_frame(frame: Frame, bbox: tuple[float, float, float, float], pad: float = 0.0) -> Frame:
    from v3.types import clamp_bbox

    x1, y1, x2, y2 = clamp_bbox((bbox[0] - pad, bbox[1] - pad, bbox[2] + pad, bbox[3] + pad))
    image = frame_to_pil(frame)
    box = (
        max(0, int(x1 * image.width)),
        max(0, int(y1 * image.height)),
        min(image.width, int(x2 * image.width)),
        min(image.height, int(y2 * image.height)),
    )
    if box[2] <= box[0] or box[3] <= box[1]:
        return frame
    return pil_to_frame(image.crop(box))


def save_frame_png(frame: Frame, path: str | Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    frame_to_pil(frame).save(path, "PNG")
