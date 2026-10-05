import datetime
import pathlib
import uuid

PHOTOS_DIR = pathlib.Path("/app/photos")


def save_generated(user_id: int, image_bytes: bytes) -> str:
    """Сохраняет сгенерированную картинку в photos/generated/<user_id>/
    и возвращает путь относительно /app/photos (для отображения в админке)."""
    d = PHOTOS_DIR / "generated" / str(user_id)
    d.mkdir(parents=True, exist_ok=True)
    name = datetime.datetime.utcnow().strftime("%Y%m%d_%H%M%S") + f"_{uuid.uuid4().hex[:6]}.png"
    (d / name).write_bytes(image_bytes)
    return f"generated/{user_id}/{name}"
