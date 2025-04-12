import os
import re
import requests
import xml.etree.ElementTree as ET
import google.generativeai as genai

# === Configuration ===
GEMINI_API_KEY   = "AIzaSyA8qnV3aMpBpoGhiVoqFIxafNUtLoHRbA8"
WOLFRAM_APP_ID_1 = "AYQX66-UVWJ7KYPE2"
WOLFRAM_APP_ID_2 = "XUX56R-PA24H6H9Q4"

genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-2.0-flash")

# === Conversation context (basic memory) ===
conversation_history = []

# === Fallback heuristic splitter ===
def heuristic_split(prompt):
    parts = re.split(r"\s+and\s+", prompt, flags=re.IGNORECASE)
    return [p.strip() for p in parts] if len(parts) > 1 else [prompt]

# === Ask Gemini to split the prompt ===
def split_tasks(prompt):
    system_prompt = """Split this request into separate tasks. You MUST respond with ONLY a numbered list.

Example: "Plot sin(x) and explain its period"
1. Plot sin(x)
2. Explain its period

Now split this request:"""
    try:
        resp = genai.GenerativeModel("gemini-2.0-flash") \
                    .generate_content([{"role":"user","parts":[{"text":f"{system_prompt}\n\n{prompt}"}]}])
        tasks = re.findall(
            r"^\s*(?:\d+[\.\)]|\-|\*)\s*(.+?)(?=(?:\n\s*(?:\d+[\.\)]|\-|\*)|\Z))",
            resp.text, re.MULTILINE | re.DOTALL
        )
        tasks = [t.strip() for t in tasks if t.strip()]
        return tasks or heuristic_split(prompt)
    except Exception:
        return heuristic_split(prompt)

# === Check if Wolfram should handle a task ===
def wolfram_should_handle(task):
    try:
        result = requests.get(
            "http://api.wolframalpha.com/v1/result",
            params={"i": task, "appid": WOLFRAM_APP_ID_1}
        )
        if result.status_code != 200:
            return False
        # Consider it non-mathy if the answer looks encyclopedic or too general
        general_patterns = [
            r"is the capital of", r"who is", r"where is", r"define", r"what is .*? (country|state|city|name|location)"
        ]
        if any(re.search(pat, task.lower()) for pat in general_patterns):
            return False
        return True
    except:
        return False

# === Query Wolfram Alpha (focus on concise output) ===
def query_wolfram(task):
    resp = requests.get(
        "http://api.wolframalpha.com/v2/query",
        params={
            "input": task,
            "appid": WOLFRAM_APP_ID_2,
            "format": "plaintext,image"
        }
    )
    if resp.status_code != 200:
        return "Wolfram full API failed."

    try:
        root = ET.fromstring(resp.text)
        outputs = []
        priority_titles = [
            "Result", "Exact result", "Solution", "Value", "Definition", "Decimal approximation"
        ]
        skipped_titles = [
            "Input interpretation", "Basic information", "Plot", "Image", "Number line", "Wikipedia summary"
        ]

        # First, try to get a concise answer from a prioritized pod
        for pod in root.findall(".//pod"):
            title = pod.attrib.get("title", "").strip()

            if title in skipped_titles:
                continue

            if title in priority_titles or pod.attrib.get("primary", "false") == "true":
                for sub in pod.findall("subpod"):
                    txt = sub.findtext("plaintext", "").strip()
                    if txt and len(txt.split()) <= 60:
                        return f"**{title}**: {txt}"

        # Fallback: return any short text from any pod (if above fails)
        for pod in root.findall(".//pod"):
            title = pod.attrib.get("title", "").strip()
            for sub in pod.findall("subpod"):
                txt = sub.findtext("plaintext", "").strip()
                if txt and len(txt.split()) <= 60 and title not in skipped_titles:
                    return f"**{title}**: {txt}"

        return "Wolfram returned no concise result."
    except Exception as e:
        return f"Error parsing Wolfram response: {e}"

# === Smart prompt handler ===
def smart_prompt(prompt):
    tasks = split_tasks(prompt)
    responses = []

    for task in tasks:
        full_context = " ".join(conversation_history + [task])

        if wolfram_should_handle(task):
            print(f"🔢 [Wolfram] {task}")
            answer = query_wolfram(task)
            responses.append(f"📊 **{task}** →\n{answer}")
        else:
            print(f"🧠 [Gemini] {task}")
            gm = model.generate_content([{"role": "user", "parts": [{"text": full_context}]}])
            responses.append(f"🤖 **{task}** → {gm.text.strip()}")

        conversation_history.append(task)

    return "\n\n".join(responses)

# === Main loop ===
if __name__ == "__main__":
    while True:
        user_input = input("\n📝 Prompt ('q' to quit): ")
        if user_input.lower() == 'q':
            break
        print("\n✅ Combined Answer:\n")
        print(smart_prompt(user_input))
