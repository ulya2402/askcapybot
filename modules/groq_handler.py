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

async def needs_web_search(user_message: str) -> bool:
    try:
        current_key = next(key_cycler)
        client = AsyncGroq(api_key=current_key)
        
        prompt = f"""
        You are a smart assistant that decides if a user's query requires an internet search.
        Answer with only 'yes' or 'no'.

        Respond 'yes' if the query:
        1. Asks for current, recent, or real-time information (e.g., "what happened yesterday", "latest news", "weather in Jakarta").
        2. Explicitly asks to search the web (e.g., "search for", "find on the internet", "Google this").
        3. Asks about a very specific or niche topic that is likely not in general knowledge.

        Respond 'no' if the query is a general knowledge question that does not require up-to-date information (e.g., "what is photosynthesis?", "capital of France").

        User Query: "{user_message}"
        Decision:
        """
        
        response = await client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model="llama3-8b-8192",
            temperature=0.0,
            max_tokens=10,
        )
        
        decision = response.choices[0].message.content.strip().lower()
        print(f"Web search check for query '{user_message[:50]}...': {decision}")
        return 'yes' in decision
    except Exception as e:
        print(f"Error during web search check: {e}")
        return False

async def get_groq_search_response(user_message: str, translator: Translator, lang_code: str):
    for _ in range(len(api_keys)):
        current_key = next(key_cycler)
        client = AsyncGroq(api_key=current_key)
        try:
            response = await client.chat.completions.create(
                model="compound-beta",
                messages=[{"role": "user", "content": user_message}]
            )
            
            content = response.choices[0].message.content
            search_results = []
            if response.choices[0].message.executed_tools:
                # PERUBAHAN DI SINI: Mengakses atribut .results, bukan .get()
                search_results = response.choices[0].message.executed_tools[0].search_results.results

            return {"content": content, "reasoning": None, "sources": search_results}
        except RateLimitError:
            print(f"Rate limit exceeded for key ending in ...{current_key[-4:]} during web search. Rotating key.")
            continue
        except Exception as e:
            print(f"An unexpected error occurred with key ...{current_key[-4:]} during web search: {e}")
            continue
    
    return {"content": translator.get_text("all_services_busy", lang_code), "reasoning": None, "sources": []}
# --- AKHIR FUNGSI YANG DIPERBARUI ---

async def get_groq_response(user_id: int, user_message: str, supabase_client, translator: Translator, lang_code: str):
    if not api_keys:
        print("Error: GROQ_API_KEYS not found or is empty in .env file.")
        return {"content": translator.get_text("api_key_not_configured", lang_code), "reasoning": None, "sources": []}

    if await needs_web_search(user_message):
        return await get_groq_search_response(user_message, translator, lang_code)

    active_model_id = await get_user_model(supabase_client, user_id)
    model_info = models_config.get(active_model_id, {})
    supports_reasoning = model_info.get("reasoning", False)

    api_params = { "temperature": 0.7, "max_tokens": 4096, "top_p": 1, "stop": None, "stream": True }
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
            
            reasoning_text, final_content = None, full_raw_response
            if supports_reasoning and "<think>" in full_raw_response and "</think>" in full_raw_response:
                start_tag, end_tag = "<think>", "</think>"
                start_index = full_raw_response.find(start_tag)
                end_index = full_raw_response.find(end_tag)
                if start_index != -1 and end_index != -1:
                    reasoning_text = full_raw_response[start_index + len(start_tag):end_index].strip()
                    final_content = full_raw_response[end_index + len(end_tag):].strip()

            return {"content": final_content, "reasoning": reasoning_text, "sources": []}
        except RateLimitError:
            print(f"Rate limit exceeded for key ending in ...{current_key[-4:]}. Rotating key.")
            continue
        except Exception as e:
            print(f"An unexpected error occurred with key ...{current_key[-4:]}: {e}")
            continue
    
    return {"content": translator.get_text("all_services_busy", lang_code), "reasoning": None, "sources": []}


async def get_groq_vision_response(user_id: int, prompt_text: str, base64_images: list, supabase_client, translator: Translator, lang_code: str):
    if not api_keys:
        print("Error: GROQ_API_KEYS not found or is empty in .env file.")
        return {"content": translator.get_text("api_key_not_configured", lang_code)}

    active_model_id = await get_user_model(supabase_client, user_id)
    
    content_parts = [{"type": "text", "text": prompt_text}]
    for b64_img in base64_images:
        content_parts.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{b64_img}"}
        })

    messages = [{"role": "user", "content": content_parts}]
    
    api_params = {
        "temperature": 0.5,
        "max_tokens": 4096,
        "top_p": 1,
        "stop": None,
        "stream": False,
    }

    for _ in range(len(api_keys)):
        current_key = next(key_cycler)
        client = AsyncGroq(api_key=current_key)
        
        try:
            completion = await client.chat.completions.create(messages=messages, model=active_model_id, **api_params)
            return {"content": completion.choices[0].message.content}
        except RateLimitError:
            print(f"Rate limit exceeded for key ending in ...{current_key[-4:]}. Rotating key.")
            continue
        except Exception as e:
            print(f"An unexpected error occurred with key ...{current_key[-4:]}: {e}")
            return {"content": translator.get_text("stream_error", lang_code)}
            
    return {"content": translator.get_text("all_services_busy", lang_code)}