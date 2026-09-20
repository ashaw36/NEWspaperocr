"""Unicode-safe OpenCV file I/O for Windows paths."""

from pathlib import Path

import cv2
import numpy as np


def read_image(path):
    data = np.fromfile(str(Path(path)), dtype=np.uint8)
    if data.size == 0:
        return None
    return cv2.imdecode(data, cv2.IMREAD_COLOR)


def write_image(path, image) -> bool:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    extension = target.suffix or ".png"
    success, encoded = cv2.imencode(extension, image)
    if not success:
        return False
    encoded.tofile(str(target))
    return True
