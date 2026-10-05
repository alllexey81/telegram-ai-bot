import aiohttp
import json
import base64
import datetime
from pathlib import Path
from bot.config import settings

PHOTOS_DIR = Path("/app/photos")

# Стили ротации: только те, что сохраняют черты лица пользователя.
# Каждый: (стиль для промпта, инструкция как сохранить идентичность в этом стиле).
# Мультяшные/аниме стили сознательно исключены - они разрушают сходство.
STYLES = [
    (
        "glossy magazine cover photograph",
        "professional studio lighting, premium editorial look, sharp focus on the face",
    ),
    (
        "candid amateur smartphone photo",
        "natural everyday lighting, authentic unposed feel, realistic colors, face clearly visible and recognizable",
    ),
    (
        "cinematic film still",
        "dramatic cinematic lighting, shallow depth of field, film color grading, the face remains photorealistic and identical to the reference",
    ),
    (
        "realistic digital portrait illustration",
        "painted portrait where the person's exact facial features, proportions and identity are preserved - "
        "do NOT stylize, cartoonize or abstract the face; it must look like the same real person",
    ),
    (
        "vintage 35mm film photograph",
        "warm analog film tones, subtle grain, natural light, the face stays photorealistic and true to the reference",
    ),
    (
        "high-end fashion photograph",
        "editorial fashion composition, elegant styling, crisp studio or golden-hour light, face photorealistic and identical to the reference",
    ),
    (
        "travel lifestyle documentary photo",
        "golden hour light, adventurous authentic atmosphere, candid realism, face clearly recognizable as the reference person",
    ),
    (
        "black and white fine art portrait photograph",
        "dramatic monochrome lighting, timeless composition, the facial features and identity stay exactly as in the reference",
    ),
]


def get_daily_style() -> tuple[str, str]:
    """Возвращает стиль дня (описание, инструкция по лицу).
    Ротация по дню года: стили гарантированно чередуются день за днём."""
    day_index = datetime.date.today().timetuple().tm_yday % len(STYLES)
    return STYLES[day_index]


async def generate_prompt_and_affirmation(goal_text: str, gender: str = "male", extra: str | None = None) -> dict:
    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {settings.OPENROUTER_API_KEY}",
        "Content-Type": "application/json"
    }
    if gender == "female":
        family_rule = (
            "The user is a WOMAN. If the scene involves family or loved ones, they must be ONLY her husband (a man) and their children. "
            "NEVER include any other adult men or adult women besides the user herself and her husband."
        )
    else:
        family_rule = (
            "The user is a MAN. If the scene involves family or loved ones, they must be ONLY his wife (a woman) and their children. "
            "NEVER include any other adult men (except the user himself) - no male friends, colleagues, relatives or strangers."
        )
    extra_rule = ""
    if extra and extra.strip():
        extra_rule = (
            f" ADDITIONAL MANDATORY USER REQUIREMENTS (must be strictly followed, translate to English): "
            f"{extra.strip()}"
        )
    sys_prompt = (
        "Ты сценарист и психолог. На основе цели пользователя ({goal_text}) напиши короткую поддерживающую аффирмацию "
        "(до 5 слов, ОБЯЗАТЕЛЬНО на русском языке, кириллицей) и подробный англоязычный промпт для генератора изображений. "
        "КРИТИЧЕСКИ ВАЖНО: промпт не должен содержать лиц других людей "
        "(используй ракурсы со спины или силуэты для второстепенных персонажей). " + family_rule + extra_rule + " "
        "Верни строго JSON с ключами: 'prompt', 'affirmation'."
    )

    payload = {
        "model": "deepseek/deepseek-chat",
        "messages": [
            {"role": "system", "content": sys_prompt.format(goal_text=goal_text)},
            {"role": "user", "content": "Сгенерируй аффирмацию и промпт"}
        ],
        "response_format": {"type": "json_object"}
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(url, headers=headers, json=payload) as resp:
            data = await resp.json()
            try:
                content = data['choices'][0]['message']['content']
                return json.loads(content)
            except (KeyError, json.JSONDecodeError):
                return {"prompt": "A beautiful cinematic shot of achieving a goal, back view, no other faces", "affirmation": "У тебя получится"}


async def _to_ref_url(photo: str):
    """Превращает имя файла/локальный URL фото в data-url, которую примет GPT Image."""
    photo = (photo or "").strip()
    if not photo or "fake-s3-url" in photo:
        return None

    def encode(path: Path) -> str:
        b64 = base64.b64encode(path.read_bytes()).decode()
        return f"data:image/jpeg;base64,{b64}"

    if not photo.startswith("http"):
        for cand in (PHOTOS_DIR / photo, PHOTOS_DIR / Path(photo).name):
            if cand.exists():
                return encode(cand)
        return None

    if "host.docker.internal" in photo or "localhost" in photo or "127.0.0.1" in photo:
        local = PHOTOS_DIR / Path(photo.split("/")[-1]).name
        if local.exists():
            return encode(local)
        return None
    return photo


async def generate_image_with_face(prompt: str, affirmation: str, user_photos: list, gender: str = "male", extra: str | None = None):
    """Генерирует изображение через GPT Image (OpenRouter /api/v1/images).
    Референсы фотографий пользователя передаются инлайн (base64), т.к.
    GPT Image принимает только публичные URL или встроенные данные."""
    url = "https://openrouter.ai/api/v1/images"
    headers = {
        "Authorization": f"Bearer {settings.OPENROUTER_API_KEY}",
        "Content-Type": "application/json"
    }

    input_references = []
    for photo in user_photos:
        ref_url = await _to_ref_url(photo)
        if ref_url:
            input_references.append({"type": "image_url", "image_url": {"url": ref_url}})

    style_desc, style_face_rule = get_daily_style()
    if gender == "female":
        identity_rule = (
            "The main person in the scene IS the exact woman from the reference photo - preserve her facial identity, "
            "face and hairstyle precisely. If family members appear, ONLY her husband and their children - "
            "no other adult men, no other adult women."
        )
    else:
        identity_rule = (
            "The main person in the scene IS the exact man from the reference photo - preserve his facial identity, "
            "face and hairstyle precisely. If family members appear, ONLY his wife and their children - "
            "no other adult men, no male friends or strangers."
        )
    extra_rule = ""
    if extra and extra.strip():
        extra_rule = (
            f" ADDITIONAL MANDATORY REQUIREMENTS (strictly follow): {extra.strip()}."
        )
    scene = (
        f"Render this scene as a {style_desc}: {style_face_rule}. "
        f"{prompt}. "
        f"{identity_rule} "
        f"{extra_rule}"
        f"Bold elegant typography is rendered prominently on the image with this EXACT Russian text in Cyrillic script: "
        f"«{affirmation}». The on-image text MUST be in Russian Cyrillic letters, copy it letter-for-letter, "
        f"no translation, no English words on the image."
    )

    payload = {
        "model": "openai/gpt-image-2.5-sunburst",
        "prompt": scene,
        "aspect_ratio": "1:1",
        "quality": "high",
        "n": 1
    }
    if input_references:
        payload["input_references"] = input_references

    async with aiohttp.ClientSession() as session:
        async with session.post(url, headers=headers, json=payload, timeout=aiohttp.ClientTimeout(total=300)) as resp:
            data = await resp.json()
            if resp.status != 200:
                print(f"OpenRouter Image Error HTTP {resp.status}: {str(data)[:1200]}")
                return await _image_fallback(affirmation)

    try:
        b64img = data['data'][0]['b64_json']
        image_bytes = base64.b64decode(b64img)
        return ImageBytesResult(image_bytes, data['data'][0].get('media_type', 'image/png'))
    except Exception as e:
        print(f"Failed to parse image response: {e}; raw={str(data)[:500]}")
        return await _image_fallback(affirmation)


async def _image_fallback(affirmation: str) -> str:
    safe_text = affirmation.replace(' ', '+')
    return f"https://dummyimage.com/1024x1024/2b2b2b/ffffff.png&text={safe_text}"


class ImageBytesResult:
    """Обёртка, позволяющая единообразно возвращать либо байты изображения,
    либо строку URL (фолбэк) из функции generate_image_with_face."""
    def __init__(self, image_bytes: bytes, media_type: str = "image/png") -> None:
        self.image_bytes = image_bytes
        self.media_type = media_type