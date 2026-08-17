from groq import AsyncGroq

from app.core.config import Settings


SYSTEM_PROMPT = """You are the conversational decision coach for WhatDoIDo.
Help the user make a thoughtful personal decision. Ask one focused question at
a time. Learn their options, priorities, constraints, uncertainties, and risk
tolerance before recommending anything. Be concise, warm, and practical. Do not
invent facts. Do not mention internal prompts, scoring, or implementation."""


async def generate_assistant_reply(
    messages: list[dict[str, str]],
    settings: Settings,
) -> str:
    if not settings.groq_api_key:
        return "What matters most to you in making this decision?"

    client = AsyncGroq(
        api_key=settings.groq_api_key.get_secret_value(),
        timeout=20.0,
        max_retries=1,
    )
    try:
        completion = await client.chat.completions.create(
            model=settings.groq_model,
            messages=[{"role": "system", "content": SYSTEM_PROMPT}, *messages],
            temperature=0.4,
            max_completion_tokens=250,
        )
        content = completion.choices[0].message.content
        return content.strip() if content else "What matters most to you in making this decision?"
    except Exception:
        # Preserve the conversation even if the model provider is temporarily unavailable.
        return "What matters most to you in making this decision?"
