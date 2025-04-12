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

# === Detect math vs visualization ===
def is_math_query(text):
    conceptual = [r"what is .*", r"explain .*", r"describe .*", r"how does .*", r"define .*"]
    if any(re.search(p, text.lower()) for p in conceptual):
        return False
    math_kw = [
        "solve", "integral", "derivative", "limit", "differentiate",
        "evaluate", "simplify", "expression", "equation", "factor", "expand",
        "roots", "graph", "calculate", "area", "volume", "log", "ln", "sin", "cos", "tan"
    ]
    return any(w in text.lower() for w in math_kw)

def is_visualization_query(text):
    return bool(re.search(r"\bvisualization\b|\bgraph\b|\bplot\b|\b3d\b", text.lower()))

# === Query Wolfram Alpha (plaintext + images) ===
def query_wolfram(task):
    # Quick check
    quick = requests.get(
        "http://api.wolframalpha.com/v1/result",
        params={"i": task, "appid": WOLFRAM_APP_ID_1}
    )
    if quick.status_code != 200 or "Wolfram" in quick.text:
        return "Wolfram couldn't process this task."

    # Full query with images
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
        for pod in root.findall(".//pod"):
            title = pod.attrib.get("title", "").strip()
            sub = pod.find("subpod")
            # plaintext
            if sub is not None and sub.find("plaintext") is not None:
                text = sub.find("plaintext").text
                if text and text.strip():
                    outputs.append(f"**{title}**: {text.strip()}")
            # image
            if sub is not None and sub.find("img") is not None:
                img = sub.find("img").attrib.get("src")
                if img:
                    outputs.append(f"![{title}]({img})")

        return "\n\n".join(outputs) if outputs else "Wolfram returned no results."
    except Exception as e:
        return f"Error parsing Wolfram response: {e}"

# === Fallback heuristic splitter ===
def heuristic_split(prompt):
    parts = re.split(r"\s+and\s+", prompt, flags=re.IGNORECASE)
    return [p.strip() for p in parts] if len(parts) > 1 else [prompt]

# === Task splitting via Gemini + fallback ===
def split_tasks(prompt):
    system_prompt = """Split this request into separate tasks. You MUST respond with ONLY a numbered list.

Example input: "Calculate 2+2 and explain what addition is"
Example output:
1. Calculate 2+2
2. Explain what addition is

Example input: "Plot sin(x) and explain its period"
Example output:
1. Plot sin(x)
2. Explain its period

Now split this request (respond ONLY with numbered tasks):"""
    try:
        splitter = genai.GenerativeModel("gemini-2.0-flash")
        resp = splitter.generate_content([{
            "role": "user",
            "parts": [{"text": f"{system_prompt}\n\nRequest: {prompt}"}]
        }])
        print("Debug - Raw Gemini response:", resp.text)

        tasks = re.findall(
            r"^\s*(?:\d+[\.\)]|\-|\*)\s*(.+?)(?=(?:\n\s*(?:\d+[\.\)]|\-|\*)|\Z))",
            resp.text, re.MULTILINE | re.DOTALL
        )
        tasks = [t.strip() for t in tasks if t.strip()]
        return tasks or heuristic_split(prompt)
    except Exception as e:
        print("Error in task splitting:", e)
        return heuristic_split(prompt)

# === Smart routing logic ===
def smart_prompt(prompt):
    tasks = split_tasks(prompt)
    final_responses = []

    for task in tasks:
        # Visualization or math → Wolfram (with images)
        if is_visualization_query(task) or is_math_query(task):
            print(f"🔢 Sending to Wolfram (with images): {task}")
            answer = query_wolfram(task)
            final_responses.append(f"📊 **{task}** →\n\n{answer}")
        # Otherwise → Gemini
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
        print("\n✅ Combined Answer:\n")
        print(smart_prompt(user_input))
