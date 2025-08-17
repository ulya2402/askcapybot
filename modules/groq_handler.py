import os
import itertools
import json
from groq import AsyncGroq, RateLimitError
from modules.supabase_handler import get_user_messages, get_user_model
from modules.translator import Translator

api_keys_str = os.environ.get("GROQ_API_KEYS", "")
api_keys = [key.strip() for key in api_keys_str.split(',') if key.strip()]
key_cycler = itertools.cycle(api_keys)

def load_models_config():
    try:
        with open("models.json", "r") as f:
            return {model['value']: model for model in json.load(f)}
    except FileNotFoundError:
        return {}

models_config = load_models_config()

async def get_groq_response(user_id: int, user_message: str, supabase_client, translator: Translator, lang_code: str):
    if not api_keys:
        print("Error: GROQ_API_KEYS not found or is empty in .env file.")
        return {"content": translator.get_text("api_key_not_configured", lang_code), "reasoning": None}

    active_model_id = await get_user_model(supabase_client, user_id)
    model_info = models_config.get(active_model_id, {})
    supports_reasoning = model_info.get("reasoning", False)

    api_params = {
        "temperature": 0.7,
        "max_tokens": 4096,
        "top_p": 1,
        "stop": None,
        "stream": True,
    }

    if supports_reasoning:
        api_params["reasoning_format"] = "raw"

    conversation_history = await get_user_messages(supabase_client, user_id)
    system_prompt = translator.get_text("system_prompt", lang_code)
    messages = [{"role": "system", "content": system_prompt}]
    for message in conversation_history:
        messages.append({"role": message['role'], "content": message['content']})
    messages.append({"role": "user", "content": user_message})

    for _ in range(len(api_keys)):
        current_key = next(key_cycler)
        client = AsyncGroq(api_key=current_key)
        
        try:
            stream = await client.chat.completions.create(messages=messages, model=active_model_id, **api_params)
            
            full_raw_response = ""
            async for chunk in stream:
                content = chunk.choices[0].delta.content
                if content:
                    full_raw_response += content
            
            reasoning_text = None
            final_content = full_raw_response
            
            if supports_reasoning and "<think>" in full_raw_response and "</think>" in full_raw_response:
                start_tag = "<think>"
                end_tag = "</think>"
                start_index = full_raw_response.find(start_tag)
                end_index = full_raw_response.find(end_tag)
                
                if start_index != -1 and end_index != -1:
                    reasoning_text = full_raw_response[start_index + len(start_tag):end_index].strip()
                    final_content = full_raw_response[end_index + len(end_tag):].strip()

            return {"content": final_content, "reasoning": reasoning_text}

        except RateLimitError:
            print(f"Rate limit exceeded for key ending in ...{current_key[-4:]}. Rotating key.")
            continue
        except Exception as e:
            print(f"An unexpected error occurred with key ...{current_key[-4:]}: {e}")
            continue
    
    return {"content": translator.get_text("all_services_busy", lang_code), "reasoning": None}
