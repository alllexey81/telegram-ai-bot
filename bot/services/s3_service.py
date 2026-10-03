import aioboto3
from bot.config import settings

async def upload_photo(file_bytes: bytes, filename: str) -> str:
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
