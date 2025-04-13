import os
import re
import requests
import xml.etree.ElementTree as ET
import google.generativeai as genai
from collections import deque

# === Configuration ===
GEMINI_API_KEY   = "AIzaSyA8qnV3aMpBpoGhiVoqFIxafNUtLoHRbA8"
WOLFRAM_APP_ID_1 = "AYQX66-UVWJ7KYPE2"
WOLFRAM_APP_ID_2 = "XUX56R-PA24H6H9Q4"

genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-2.0-flash")

contextQueue = deque()

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

# === Query Wolfram Alpha (full, with images) ===
def query_wolfram(task):
    """
    Queries the Wolfram Alpha Full Results API and returns a concise response, including plots if available.
    """
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
        # Parse the XML response
        root = ET.fromstring(resp.text)
        outputs = []

        # Extract plaintext result
        result = root.find(".//plaintext")
        if result is not None and result.text.strip():
            outputs.append(result.text.strip())

        # Extract plot image URLs
        for img in root.findall(".//img"):
            img_src = img.attrib.get("src")
            if img_src:
                outputs.append(f"![Plot]({img_src})")

        # Combine results and plots
        return "\n\n".join(outputs) if outputs else "Wolfram returned no relevant results."
    except Exception as e:
        return f"Error parsing Wolfram response: {e}"

# === Add Context to Prompt ===
def add_context_to_prompt(prompt):
    """
    Adds the summarized context from the contextQueue to the prompt.
    """
    if contextQueue:
        context_summary = "\n".join(contextQueue)
        return f"Context:\n{context_summary}\n\n{prompt}"
    return prompt

# === Store Response in Context ===
def store_response_in_context(user_input, response):
    """
    Stores a summarized version of the response in the contextQueue if the user input is related to previous context.
    Keeps only the last 5 responses.
    """
    summary = summarize_response(response)
    contextQueue.append(summary)
    if len(contextQueue) > 5:
        contextQueue.popleft()

def summarize_response(response):
    """
    Uses the Gemini API to summarize the response.
    """
    try:
        system_prompt = "Summarize the following response in a concise manner:"
        resp = model.generate_content(f"{system_prompt}\n\n{response}")
        return resp.text.strip()
    except Exception as e:
        print(f"Error summarizing response: {e}")
        # Fallback to truncating the response if summarization fails
        return response[:200] + "..." if len(response) > 200 else response

def is_related_to_context(user_input):
    """
    Uses the Gemini API to determine if the user input is related to the previous context.
    """
    try:
        system_prompt = """Determine if the following user input is related to the previous context.
Respond with "Yes" or "No" only.

Context:
{context}

User Input:
{user_input}"""
        context_summary = "\n".join(contextQueue) if contextQueue else "No previous context."
        resp = model.generate_content(system_prompt.format(context=context_summary, user_input=user_input))
        return resp.text.strip().lower() == "yes"
    except Exception as e:
        print(f"Error determining context relevance: {e}")
        # Default to not storing if the check fails
        return False

def is_task_computational(task):
    """
    Uses the Gemini API to determine if the task is computational, mathematical, visualization, modeling, graphing, etc.
    Returns True if the task is suitable for Wolfram Alpha, otherwise False.
    """
    try:
        system_prompt = """Determine if the following task is computational, mathematical, visualization, modeling, graphing, or similar.
Respond with "Yes" or "No" only.

Task:
{task}"""
        resp = model.generate_content(system_prompt.format(task=task))
        return resp.text.strip().lower() == "yes"
    except Exception as e:
        print(f"Error determining task type: {e}")
        # Default to False if the check fails
        return False

# === Smart routing logic with task classification ===
def smart_prompt_with_context(prompt):
    """
    Processes the prompt using Wolfram and Gemini, including context from the contextQueue.
    Always updates the context, but only includes it in the new prompt if the new prompt is related to the context.
    """
    # Check if the new prompt is related to the existing context
    if is_related_to_context(prompt):
        prompt_with_context = add_context_to_prompt(prompt)
    else:
        prompt_with_context = prompt

    # Split the tasks from the prompt (with or without context)
    tasks = split_tasks(prompt_with_context)
    responses = []

    for task in tasks:
        try:
            # Determine if the task is computational
            if is_task_computational(task):
                # Directly query Wolfram Alpha Full Results API
                print(f"🔢 [Wolfram] {task}")
                answer = query_wolfram(task)
                if "Wolfram full API failed." in answer or "Error parsing Wolfram response" in answer:
                    raise Exception("Wolfram API failed")
                responses.append(f"📊 **{task}** →\n{answer}")
            else:
                # Use Gemini for non-computational tasks
                print(f"🧠 [Gemini] {task} (Non-computational)")
                gm = model.generate_content(task)
                responses.append(f"🤖 **{task}** → {gm.text.strip()}")
        except Exception as e:
            # Fallback to Gemini if Wolfram fails
            print(f"🧠 [Gemini] {task} (Fallback due to: {e})")
            try:
                gm = model.generate_content(task)
                responses.append(f"🤖 **{task}** → {gm.text.strip()}")
            except Exception as gemini_error:
                # Handle Gemini failure gracefully
                print(f"Error processing task '{task}' with Gemini: {gemini_error}")
                responses.append(f"❌ **{task}** → Error: {gemini_error}")

    # Combine all responses into a single output
    combined_response = "\n\n".join(responses)

    # Always update the context with the new response
    store_response_in_context(prompt, combined_response)

    return combined_response

# === Example Loop ===
if __name__ == "__main__":
    while True:
        user_input = input("\n📝 Prompt ('q' to quit): ")
        if user_input.lower() == 'q':
            break
        print("\n✅ Combined Answer:\n")
        print(smart_prompt_with_context(user_input))
