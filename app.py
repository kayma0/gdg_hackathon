from __future__ import annotations

import json
import os
import math
import re
from io import BytesIO
from pathlib import Path
from typing import List
from google import genai
from google.genai import types

from docx import Document
from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from dotenv import load_dotenv
from pptx import Presentation

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = "gemma-4-26b-a4b-it"
GEMINI_CLIENT = genai.Client() if GEMINI_API_KEY else None

app = FastAPI(title="Study Sprint MVP", version="0.1.0")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "index.html")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/plan", response_class=HTMLResponse)
async def create_plan_page(
    request: Request,
    prompt: str = Form(...),
    deadline: str = Form(...),
    study_minutes_per_day: int = Form(...),
    uploaded_files: List[UploadFile] = File(default_factory=list),
) -> HTMLResponse:
    plan_data = await build_plan_response(
        prompt=prompt,
        deadline=deadline,
        study_minutes_per_day=study_minutes_per_day,
        uploaded_files=uploaded_files,
    )
    return templates.TemplateResponse(
        request,
        "plan.html",
        {
            "plan": plan_data["plan"],
            "study_session": plan_data["study_session"],
            "file_names": plan_data["file_names"],
            "study_minutes_per_day": study_minutes_per_day,
            "deadline": deadline,
        },
    )


@app.post("/api/plan")
async def generate_plan_api(
    request: Request,
    prompt: str = Form(...),
    deadline: str = Form(...),
    study_minutes_per_day: int = Form(...),
    uploaded_files: List[UploadFile] = File(default_factory=list),
) -> JSONResponse:
    plan_data = await build_plan_response(
        prompt=prompt,
        deadline=deadline,
        study_minutes_per_day=study_minutes_per_day,
        uploaded_files=uploaded_files,
    )
    return JSONResponse(plan_data)


@app.post("/api/chat")
async def generate_chat_api(
    message: str = Form(...),
    follow_up: str = Form(default=""),
) -> JSONResponse:
    chat_data = await build_chat_response(message=message, follow_up=follow_up)
    return JSONResponse(chat_data)


async def build_plan_response(
    prompt: str,
    deadline: str,
    study_minutes_per_day: int,
    uploaded_files: List[UploadFile],
) -> dict:
    file_names: List[str] = []
    raw_text = ""

    if uploaded_files:
        for uploaded_file in uploaded_files:
            if not uploaded_file.filename:
                continue
            file_names.append(uploaded_file.filename)
            raw_text += await extract_text_from_upload(uploaded_file) + "\n\n"

    if not raw_text.strip():
        raw_text = load_demo_text_from_folder()
        file_names = [path.name for path in sorted((BASE_DIR / "study_material").glob("*")) if path.is_file()]

    plan = await build_plan_with_gemini(
        prompt=prompt,
        deadline=deadline,
        study_minutes=study_minutes_per_day,
        raw_text=raw_text,
        file_names=file_names,
    )
    study_session = build_study_session(plan["focus_topics"])
    return {"plan": plan, "study_session": study_session, "file_names": file_names}


async def build_plan_with_gemini(
    prompt: str,
    deadline: str,
    study_minutes: int,
    raw_text: str,
    file_names: List[str],
) -> dict:
    if GEMINI_CLIENT is None:
        return build_plan(prompt, deadline, study_minutes, raw_text, file_names)

    try:
        response = GEMINI_CLIENT.models.generate_content(
            model=GEMINI_MODEL,
            config=types.GenerateContentConfig(
                thinking_config=types.ThinkingConfig(thinking_level="high"),
                system_instruction=(
                    "You are a terse but supportive study assistant. Return only valid JSON with keys: "
                    "summary, focus_topics, study_blocks, minimum_win, motivation_note, custom_prompt, daily_time. "
                    "focus_topics must be an array of short strings. study_blocks must be an array of objects with title, focus, time, and goal. "
                    "Keep the plan practical, concise, and centered on progress over perfection."
                )
            ),
            contents=(
                "Create a study plan from the following input.\n"
                f"Prompt: {prompt.strip() or 'Keep it small and realistic.'}\n"
                f"Deadline: {deadline}\n"
                f"Study time per day: {study_minutes} minutes\n"
                f"Source files: {', '.join(file_names) if file_names else 'none'}\n"
                f"Source text:\n{raw_text[:12000]}"
            ),
        )
        plan = parse_plan_response(response.text or "", study_minutes)
        if plan:
            return plan
    except Exception:
        pass

    return build_plan(prompt, deadline, study_minutes, raw_text, file_names)


async def build_chat_response(message: str, follow_up: str = "") -> dict:
    if GEMINI_CLIENT is None:
        return {
            "first_reply": "GEMINI_API_KEY is not configured.",
            "follow_up_reply": "",
        }

    try:
        chat = GEMINI_CLIENT.chats.create(model=GEMINI_MODEL)
        first_reply = chat.send_message(message).text or ""
        follow_up_reply = chat.send_message(follow_up).text if follow_up.strip() else ""
        return {
            "first_reply": first_reply,
            "follow_up_reply": follow_up_reply or "",
        }
    except Exception:
        return {
            "first_reply": "Sorry, the Gemini chat request failed.",
            "follow_up_reply": "",
        }


async def extract_text_from_upload(uploaded_file: UploadFile) -> str:
    contents = await uploaded_file.read()
    suffix = Path(uploaded_file.filename or "").suffix.lower()

    if suffix == ".pptx":
        prs = Presentation(BytesIO(contents))
        return extract_text_from_pptx(prs)

    if suffix == ".docx":
        doc = Document(BytesIO(contents))
        return "\n".join(paragraph.text.strip() for paragraph in doc.paragraphs if paragraph.text.strip())

    if suffix == ".txt":
        return contents.decode("utf-8", errors="ignore")

    return ""


def extract_text_from_pptx(prs: Presentation) -> str:
    text_parts: List[str] = []
    for slide in prs.slides:
        for shape in slide.shapes:
            if hasattr(shape, "text") and shape.text.strip():
                text_parts.append(shape.text.strip())
    return "\n".join(text_parts)


def load_demo_text_from_folder() -> str:
    material_dir = BASE_DIR / "study_material"
    if not material_dir.exists():
        return ""

    collected: List[str] = []
    for file_path in sorted(material_dir.glob("*")):
        if file_path.suffix.lower() == ".pptx":
            prs = Presentation(str(file_path))
            collected.append(f"FILE: {file_path.name}\n{extract_text_from_pptx(prs)}")
    return "\n\n".join(collected)


def build_plan(prompt: str, deadline: str, study_minutes: int, raw_text: str, file_names: List[str]) -> dict:
    topics = extract_topics(raw_text)
    if not topics:
        topics = ["core concepts", "key examples", "review questions"]

    study_minutes = max(10, study_minutes)
    total_blocks = min(4, max(2, math.ceil(study_minutes / 25)))
    duration_per_block = max(10, min(30, math.ceil(study_minutes / total_blocks)))

    blocks: List[dict] = []
    for index, topic in enumerate(topics[:total_blocks], start=1):
        blocks.append(
            {
                "title": f"Session {index}",
                "focus": topic,
                "time": f"{duration_per_block} minutes",
                "goal": f"Review {topic} and jot down 3 key ideas you can explain out loud.",
            }
        )

    summary = build_summary(topics, deadline, file_names)
    minimum_win = build_minimum_win(topics[0])
    motivation_note = "You do not need a perfect plan. Start with one small block and let momentum do the rest."

    return {
        "summary": summary,
        "focus_topics": topics[:4],
        "study_blocks": blocks,
        "minimum_win": minimum_win,
        "motivation_note": motivation_note,
        "custom_prompt": prompt.strip() or "Keep it small and realistic.",
        "daily_time": f"{study_minutes} minutes per day",
    }


def parse_plan_response(raw_response: str, study_minutes: int) -> dict | None:
    cleaned = raw_response.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)

    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        return None

    focus_topics = parsed.get("focus_topics")
    study_blocks = parsed.get("study_blocks")
    if not isinstance(focus_topics, list) or not isinstance(study_blocks, list):
        return None
    if not all(isinstance(topic, str) for topic in focus_topics):
        return None
    if not all(isinstance(block, dict) for block in study_blocks):
        return None

    return {
        "summary": parsed.get("summary") if isinstance(parsed.get("summary"), str) else "Your study plan is ready.",
        "focus_topics": focus_topics[:4],
        "study_blocks": study_blocks[:4],
        "minimum_win": parsed.get("minimum_win") if isinstance(parsed.get("minimum_win"), str) else "Spend 10 minutes reviewing the main topic.",
        "motivation_note": parsed.get("motivation_note") if isinstance(parsed.get("motivation_note"), str) else "Start small and keep moving.",
        "custom_prompt": parsed.get("custom_prompt") if isinstance(parsed.get("custom_prompt"), str) else "Keep it small and realistic.",
        "daily_time": parsed.get("daily_time") if isinstance(parsed.get("daily_time"), str) else f"{study_minutes} minutes per day",
    }


def extract_topics(raw_text: str) -> List[str]:
    cleaned_lines = []
    for line in raw_text.splitlines():
        stripped = re.sub(r"\s+", " ", line).strip()
        if not stripped:
            continue
        stripped = re.sub(r"[^A-Za-z0-9 /&-]", "", stripped)
        if len(stripped) < 4 or len(stripped) > 70:
            continue
        if stripped.lower().startswith(("file:", "slide", "title")):
            continue
        cleaned_lines.append(stripped)

    topics: List[str] = []
    seen = set()
    for line in cleaned_lines[:20]:
        lowered = line.lower()
        if lowered in seen:
            continue
        if lowered.startswith(("memory management", "computer system", "operating system", "process")):
            seen.add(lowered)
            topics.append(line)
            continue
        if len(line.split()) <= 8:
            seen.add(lowered)
            topics.append(line)
            if len(topics) >= 4:
                break

    if not topics:
        return ["core concepts", "review questions", "key examples"]

    return topics


def build_summary(topics: List[str], deadline: str, file_names: List[str]) -> str:
    topic_list = ", ".join(topics[:3])
    if not deadline.strip():
        deadline = "soon"
    source_label = ", ".join(file_names[:2]) if file_names else "your uploaded materials"
    return f"Based on {source_label}, your best next step is to focus on {topic_list} and build a short study rhythm for {deadline}."


def build_minimum_win(first_topic: str) -> str:
    return f"Spend 10 minutes reviewing {first_topic} and write one paragraph in your own words."


def build_study_session(topics: List[str]) -> dict:
    first_topic = topics[0] if topics else "your main concept"
    second_topic = topics[1] if len(topics) > 1 else first_topic
    return {
        "title": f"Mini study session: {first_topic}",
        "explanation": f"A short way to understand {first_topic} is to connect it to one real example and explain it out loud in 30 seconds.",
        "flashcards": [
            {"question": f"What is the main idea behind {first_topic}?", "answer": "Keep your answer short and practical."},
            {"question": f"How does {second_topic} connect to your exam?", "answer": "Link it to a definition, example, or recall question."},
        ],
        "quiz": {
            "question": f"Which part of {first_topic} should you review first when time is limited?",
            "answer": "Start with the idea you can explain most simply and confidently.",
        },
        "open_question": f"In one sentence, explain {first_topic} as if you were teaching it to a friend.",
    }
