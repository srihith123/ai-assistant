import os
import re
import html
import requests
import xml.etree.ElementTree as ET
import google.generativeai as genai

# === Configuration ===
GEMINI_API_KEY = "AIzaSyA8qnV3aMpBpoGhiVoqFIxafNUtLoHRbA8"
WOLFRAM_APP_ID_1 = "AYQX66-UVWJ7KYPE2"
WOLFRAM_APP_ID_2 = "XUX56R-PA24H6H9Q4"

genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-2.0-flash")

# === Function to detect if task is mathy ===
def is_math_query(text):
    conceptual_patterns = [
        r"what is .*",
        r"explain .*",
        r"describe .*",
        r"how does .*",
        r"define .*"
    ]
    if any(re.search(pattern, text.lower()) for pattern in conceptual_patterns):
        return False

    math_keywords = [
        "solve", "integral", "derivative", "limit", "differentiate",
        "evaluate", "simplify", "expression", "equation", "factor", "expand",
        "roots", "graph", "calculate", "area", "volume", "log", "ln", "sin", "cos", "tan"
    ]
    
    has_math_keywords = any(word in text.lower() for word in math_keywords)
    has_numbers = bool(re.search(r"\d", text))
    has_math_symbols = bool(re.search(r"[+\-*/^=]", text))
    
    return (has_math_keywords and (has_numbers or has_math_symbols))

# === Query Wolfram Alpha ===
def query_wolfram(task):
    # Step 1: Quick check if it's solvable
    quick_url = "http://api.wolframalpha.com/v1/result"
    quick_params = {
        "i": task,
        "appid": WOLFRAM_APP_ID_1
    }
    quick_response = requests.get(quick_url, params=quick_params)

    if quick_response.status_code != 200 or "Wolfram" in quick_response.text:
        return "Wolfram couldn't process this task."

    # Step 2: Use Full API to get detailed response
    full_url = "http://api.wolframalpha.com/v2/query"
    full_params = {
        "input": task,
        "appid": WOLFRAM_APP_ID_2,
        "format": "plaintext"
    }
    full_response = requests.get(full_url, params=full_params)

    if full_response.status_code != 200:
        return "Wolfram full API failed."

    try:
        root = ET.fromstring(full_response.text)
        results = []
        for pod in root.findall(".//pod"):
            title = pod.attrib.get("title", "")
            subpod = pod.find("subpod")
            plaintext = subpod.find("plaintext").text if subpod is not None else None
            if plaintext and plaintext.strip():
                results.append(f"**{title}**: {plaintext.strip()}")

        return "\n".join(results) if results else "Wolfram returned no readable results."

    except Exception as e:
        return f"Error parsing Wolfram response: {e}"

# === Ask Gemini to split the prompt ===
def split_tasks(prompt):
    system_prompt = (
        "You are a task splitter. Given a user's request that may contain multiple subtasks, "
        "split it into clean, short individual tasks. Respond with answering all tasks and returning the answer for all tasks correctly."
    )
    try:
        splitter = genai.GenerativeModel("gemini-2.0-flash")
        messages = [
            {
                "role": "user",
                "parts": [{"text": f"{system_prompt}\n\nUser request: {prompt}"}]
            }
        ]
        response = splitter.generate_content(messages)
        
        print("Debug - Raw Gemini response:", response.text)
        
        tasks = re.findall(r"\d+\.\s*(.*)", response.text)
        if tasks:
            print("Debug - Extracted tasks:", tasks)
            return tasks
        else:
            print("Warning: No tasks were extracted from Gemini's response")
            return [prompt]
    except Exception as e:
        print(f"Error in task splitting: {e}")
        return [prompt]

# === Clean task before Wolfram ===
def clean_task_for_wolfram(task):
    task = re.sub(r"<.*?>", "", task)         # Remove HTML tags
    task = html.unescape(task)                # Unescape HTML entities
    task = task.strip().rstrip(":")           # Trim and remove trailing colon
    return task

# === Smart routing logic ===
def smart_prompt(prompt):
    tasks = split_tasks(prompt)
    final_responses = []

    for task in tasks:
        clean_task = clean_task_for_wolfram(task)

        if is_math_query(clean_task):
            print(f"🔢 Sending to Wolfram: {clean_task}")
            answer = query_wolfram(clean_task)
            final_responses.append(f"📊 **{task}** → {answer}")
        else:
            print(f"🧠 Sending to Gemini: {task}")
            response = model.generate_content(task)
            final_responses.append(f"🤖 **{task}** → {response.text.strip()}")

    return "\n\n".join(final_responses)

# === Example Loop ===
if __name__ == "__main__":
    while True:
        user_input = input("\n📝 Prompt ('q' to quit): ")
        if user_input.lower() == 'q':
            break
        result = smart_prompt(user_input)
        print("\n✅ Combined Answer:\n")
        print(result)
