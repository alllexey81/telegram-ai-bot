import pathlib
from bot.config import settings

PHOTOS_DIR = pathlib.Path("/app/photos")
PHOTOS_DIR.mkdir(parents=True, exist_ok=True)


def public_photo_url(filename: str) -> str:
    """Возвращает публичный URL фотографии, доступный для скачивания
    как локальному пользователю, так и серверам OpenRouter.

    Файлы лежат в /app/photos (примонтированная папка проекта).
    Контейнер photo_server раздаёт эту папку как корень на порту 8000,
    поэтому файл доступен по /{filename} (без префикса /photos/).
    """
    clean = filename.replace("\\", "/").split("/")[-1].replace("..", "")
    return f"http://host.docker.internal:8000/{clean}"


async def upload_photo(file_bytes: bytes, filename: str) -> str:
    # Локальное хранение фотографий (раздаются photo_server, S3 не требуется
    # для работы бота на этой машине).
    clean = filename.replace("\\", "/").split("/")[-1].replace("..", "")
    (PHOTOS_DIR / clean).write_bytes(file_bytes)
    return public_photo_url(clean)


# Оригинальная реализация загрузки в S3 (на случай полной облачной настройки).
async def upload_photo_s3(file_bytes: bytes, filename: str) -> str:
    import aioboto3
    session = aioboto3.Session()
    async with session.client(
        's3',
        endpoint_url=settings.S3_ENDPOINT_URL,
        aws_access_key_id=settings.S3_ACCESS_KEY,
        aws_secret_access_key=settings.S3_SECRET_KEY
    ) as s3:
        await s3.put_object(
            Bucket=settings.S3_BUCKET_NAME,
            Key=filename,
            Body=file_bytes
        )
        return f"{settings.S3_ENDPOINT_URL}/{settings.S3_BUCKET_NAME}/{filename}"