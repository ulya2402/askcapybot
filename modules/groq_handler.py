import os
import itertools
import json
import requests
import fitz 
from bs4 import BeautifulSoup
from groq import AsyncGroq, RateLimitError
from serpapi import GoogleSearch

from modules.supabase_handler import get_user_messages, get_user_model, get_user_prompt
from modules.translator import Translator

# --- Konfigurasi Kunci API dan Model ---
# Rotasi untuk Groq API
groq_api_keys_str = os.environ.get("GROQ_API_KEYS", "")
groq_api_keys = [key.strip() for key in groq_api_keys_str.split(',') if key.strip()]
groq_key_cycler = itertools.cycle(groq_api_keys)

# Rotasi untuk SerpApi
serpapi_keys_str = os.environ.get("SERPAPI_API_KEYS", "")
serpapi_keys = [key.strip() for key in serpapi_keys_str.split(',') if key.strip()]
serpapi_key_cycler = itertools.cycle(serpapi_keys)

def load_models_config():
    try:
        with open("models.json", "r") as f:
            return {model['value']: model for model in json.load(f)}
    except FileNotFoundError:
        return {}

models_config = load_models_config()

def scrape_url_content(url: str) -> str:
    """
    Mengambil konten dari URL, mendukung HTML dan PDF.
    """
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()

        content_type = response.headers.get('content-type', '').lower()

        # Jika konten adalah PDF
        if 'application/pdf' in content_type:
            with fitz.open(stream=response.content, filetype="pdf") as doc:
                text = "".join(page.get_text() for page in doc)
            return text
        
        # Jika konten adalah HTML
        elif 'text/html' in content_type:
            soup = BeautifulSoup(response.content, 'lxml')
            for script_or_style in soup(['script', 'style', 'nav', 'footer', 'header', 'aside']):
                script_or_style.decompose()
            return soup.get_text(separator='\n', strip=True)
        
        # Abaikan tipe konten lain
        else:
            print(f"Skipping unsupported content type '{content_type}' for URL {url}")
            return None

    except Exception as e:
        print(f"Error scraping content from {url}: {e}")
        return None


async def get_groq_response(user_id: int, user_message: str, supabase_client, translator: Translator, lang_code: str):
    if not groq_api_keys:
        return {"content": translator.get_text("api_key_not_configured", lang_code), "reasoning": None}

    active_model_id = await get_user_model(supabase_client, user_id)
    model_info = models_config.get(active_model_id, {})
    supports_reasoning = model_info.get("reasoning", False)

    api_params = { "temperature": 0.7, "max_tokens": 4096 }
    if supports_reasoning:
        api_params["reasoning_format"] = "raw"

    base_system_prompt = translator.get_text("system_prompt", lang_code)
    custom_prompt = await get_user_prompt(supabase_client, user_id)
    final_system_prompt = base_system_prompt
    if custom_prompt:
        final_system_prompt = f"{custom_prompt}\n\n[SYSTEM RULE]:\n{base_system_prompt}"

    conversation_history = await get_user_messages(supabase_client, user_id)
    messages = [{"role": "system", "content": final_system_prompt}]
    for message in conversation_history:
        messages.append({"role": message['role'], "content": message['content']})
    messages.append({"role": "user", "content": user_message})

    for _ in range(len(groq_api_keys)):
        current_key = next(groq_key_cycler)
        client = AsyncGroq(api_key=current_key)
        try:
            response = await client.chat.completions.create(messages=messages, model=active_model_id, **api_params)
            full_response = response.choices[0].message.content
            
            reasoning_text, final_content = None, full_response
            if supports_reasoning and "<think>" in full_response and "</think>" in full_response:
                start_tag, end_tag = "<think>", "</think>"
                start_index = full_response.find(start_tag)
                end_index = full_response.find(end_tag)
                if start_index != -1 and end_index != -1:
                    reasoning_text = full_response[start_index + len(start_tag):end_index].strip()
                    final_content = full_response[end_index + len(end_tag):].strip()

            return {"content": final_content, "reasoning": reasoning_text, "sources": []}
        except RateLimitError:
            continue
        except Exception as e:
            print(f"An unexpected error occurred: {e}")
            continue
    
    return {"content": translator.get_text("all_services_busy", lang_code), "reasoning": None, "sources": []}

async def get_rag_response(query: str, translator: Translator, lang_code: str):
    if not groq_api_keys or not serpapi_keys:
        return {"content": translator.get_text("api_key_not_configured", lang_code), "sources": []}

    try:
        # 1. Pencarian (Retrieval)
        search_params = {
            "q": query,
            "api_key": next(serpapi_key_cycler)
        }
        search = GoogleSearch(search_params)
        search_results = search.get_dict()
        organic_results = search_results.get("organic_results", [])
        
        if not organic_results:
            return {"content": "Sorry, I couldn't find any information on the internet.", "sources": []}
        
        top_results = organic_results[:5]
        
        # 2. Pengambilan Konten (Scraping)
        scraped_content = []
        sources = []
        
        max_chars_per_source = 7500 // len(top_results)
        for result in top_results:
            content = scrape_url_content(result['link'])
            if content:
                # Teks dipotong di sini, sebelum digabungkan
                scraped_content.append(f"--- Content from {result['link']} ---\n{content[:max_chars_per_source]}")
                sources.append(result)
        
        if not scraped_content:
            return {"content": "Sorry, I cannot access the content from the search results.", "sources": []}

        # 3. Penggabungan (Augmentation)
        context = "\n\n".join(scraped_content)
        
        rag_prompt = (
            "You are a Senior Research Analyst AI. Your task is to synthesize the provided INTERNET CONTEXT to answer the USER'S QUESTION.\n\n"
            "Follow these strict formatting rules for your response:\n"
            "1.  Start with a direct, concise summary that immediately answers the user's question.\n"
            "2.  Use <b>bold tags</b> for headings or to emphasize key concepts.\n"
            "3.  Use bullet points (•) to list details, benefits, or steps. Do not use numbered lists.\n"
            "4.  The entire response must be a single, cohesive text formatted with Telegram-supported HTML (<b>, <i>, <u>, <s>, <code>, <pre>, <blockquote>).\n"
            "5.  Do NOT invent any information or provide details outside of the provided context.\n\n"
            f"--- INTERNET CONTEXT ---\n{context}\n\n"
            f"--- USER'S QUESTION ---\n{query}"
        )
        
        # 4. Penghasilan Jawaban (Generation)
        client = AsyncGroq(api_key=next(groq_key_cycler))
        response = await client.chat.completions.create(
            messages=[{"role": "user", "content": rag_prompt}],
            model="openai/gpt-oss-120b",
            temperature=0.5,
        )
        final_answer = response.choices[0].message.content
        return {"content": final_answer, "sources": sources}

    except Exception as e:
        print(f"Error in RAG process: {e}")
        return {"content": translator.get_text("stream_error", lang_code), "sources": []}

async def get_groq_vision_response(user_id: int, prompt_text: str, base64_images: list, supabase_client, translator: Translator, lang_code: str):
    if not groq_api_keys:
        return {"content": translator.get_text("api_key_not_configured", lang_code)}
    
    active_model_id = await get_user_model(supabase_client, user_id)
    content_parts = [{"type": "text", "text": prompt_text}]
    for b64_img in base64_images:
        content_parts.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{b64_img}"}
        })
    messages = [{"role": "user", "content": content_parts}]
    api_params = { "temperature": 0.5, "max_tokens": 4096 }
    for _ in range(len(groq_api_keys)):
        current_key = next(groq_key_cycler)
        client = AsyncGroq(api_key=current_key)
        try:
            completion = await client.chat.completions.create(messages=messages, model=active_model_id, **api_params)
            return {"content": completion.choices[0].message.content}
        except RateLimitError:
            continue
        except Exception as e:
            print(f"An unexpected error occurred: {e}")
            return {"content": translator.get_text("stream_error", lang_code)}
            
    return {"content": translator.get_text("all_services_busy", lang_code)}