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

# === Fallback heuristic splitter ===
def heuristic_split(prompt):
    parts = re.split(r"\s+and\s+", prompt, flags=re.IGNORECASE)
    return [p.strip() for p in parts] if len(parts) > 1 else [prompt]

# === Ask Gemini to split the prompt ===
def split_tasks(prompt):
    system_prompt = """Split this request into separate tasks.
Make each task a basic task that can be run by the Wolfram Full Results API.
You MUST respond with ONLY a numbered list.

Example: "Plot sin(x) and explain its period"
1. Plot sin(x)
2. Explain the period of the sin(x) function

Example: "Graph the derivative of x"
1. Plot the derivative of x

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

# === Quick‐check Wolfram to decide routing ===
def wolfram_can_compute(task):
    quick = requests.get(
        "http://api.wolframalpha.com/v1/result",
        params={"i": task, "appid": WOLFRAM_APP_ID_1}
    )
    # 200 OK and response not containing “Wolfram” boilerplate means computable
    return quick.status_code == 200 and "Wolfram" not in quick.text

# === Query Wolfram Alpha (full, with images) ===
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

    # Optional: log raw XML for debugging
    # print("DEBUG Wolfram XML:", resp.text)

    try:
        root = ET.fromstring(resp.text)
        outputs = []
        for pod in root.findall(".//pod"):
            title = pod.attrib.get("title", "").strip()
            for sub in pod.findall("subpod"):
                img = sub.find("img")
                if img is not None and img.attrib.get("src"):
                    outputs.append(f"**{title}**:\n![{title}]({img.attrib['src']})")
                txt = sub.findtext("plaintext", "").strip()
                if txt:
                    outputs.append(f"**{title}**: {txt}")
        return "\n\n".join(outputs) if outputs else "Wolfram returned no results."
    except Exception as e:
        return f"Error parsing Wolfram response: {e}"

# === Smart routing logic ===
def smart_prompt(prompt):
    tasks = split_tasks(prompt)
    responses = []

    for task in tasks:
        try:
            # Directly query Wolfram Alpha Full Results API
            print(f"🔢 [Wolfram] {task}")
            answer = query_wolfram(task)
            if "Wolfram full API failed." in answer or "Error parsing Wolfram response" in answer:
                raise Exception("Wolfram API failed")
            responses.append(f"📊 **{task}** →\n{answer}")
        except Exception as e:
            # Fall back to Gemini if Wolfram fails
            print(f"🧠 [Gemini] {task} (Fallback due to: {e})")
            gm = model.generate_content(task)
            responses.append(f"🤖 **{task}** → {gm.text.strip()}")

    return "\n\n".join(responses)

# === Example Loop ===
if __name__ == "__main__":
    while True:
        user_input = input("\n📝 Prompt ('q' to quit): ")
        if user_input.lower() == 'q':
            break
        print("\n✅ Combined Answer:\n")
        print(smart_prompt(user_input))
