import aiohttp
import json
from bot.config import settings

async def generate_prompt_and_affirmation(goal_text: str) -> dict:
    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {settings.OPENROUTER_API_KEY}",
        "Content-Type": "application/json"
    }
    sys_prompt = (
        "Ты сценарист и психолог. На основе цели пользователя ({goal_text}) напиши короткую поддерживающую аффирмацию (до 5 слов) "
        "и подробный англоязычный промпт для генератора изображений. КРИТИЧЕСКИ ВАЖНО: промпт не должен содержать лиц других людей "
        "(используй ракурсы со спины или силуэты для второстепенных персонажей). Верни строго JSON с ключами: 'prompt', 'affirmation'."
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
                return {"prompt": "A beautiful cinematic shot of achieving a goal, back view, no other faces", "affirmation": "You can do it"}

async def generate_image_with_face(prompt: str, affirmation: str, user_photos: list) -> str:
    # Здесь должен быть вызов модели img2img (например, через OpenRouter, когда появится полная поддержка таких моделей)
    # Возвращаем заглушку, соответствующую архитектуре
    return f"https://via.placeholder.com/1024x1024.png?text={affirmation.replace(' ', '+')}"
