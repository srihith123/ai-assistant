# main.py
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from your_script_filename import smart_prompt_with_context  # Replace with your actual script name (no .py)

app = FastAPI()

# Allow CORS for all origins (adjust in prod)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

class PromptRequest(BaseModel):
    prompt: str

@app.post("/ask")
async def ask(prompt_request: PromptRequest):
    prompt = prompt_request.prompt
    result = smart_prompt_with_context(prompt)
    return {"response": result}
