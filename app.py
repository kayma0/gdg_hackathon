from __future__ import annotations

import json
import math
import os
import re
from io import BytesIO
from pathlib import Path
from typing import Any, List

from docx import Document
from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from google import genai
from google.genai import types
from pptx import Presentation


# ---------------------------------------------------------
# Application setup
# ---------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent

load_dotenv(BASE_DIR / ".env")


GEMMA_API_KEY = os.getenv("GEMMA_API_KEY", "").strip()
GEMMA_MODEL = "gemma-4-26b-a4b-it"
GEMMA_CLIENT = genai.Client() if GEMMA_API_KEY else None

GEMMA_CLIENT = (
    genai.Client(api_key=GEMMA_API_KEY)
    if GEMMA_API_KEY
    else None
)

app = FastAPI(
    title="ZEN Study Companion",
    version="0.1.0",
)

app.mount(
    "/static",
    StaticFiles(directory=BASE_DIR / "static"),
    name="static",
)

templates = Jinja2Templates(
    directory=BASE_DIR / "templates"
)


# ---------------------------------------------------------
# Page routes
# ---------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "request": request,
        },
    )


@app.get("/chat", response_class=HTMLResponse)
async def chat_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "chat.html",
        {
            "request": request,
        },
    )


@app.get("/health")
async def health() -> dict[str, str]:
    return {
        "status": "ok",
        "application": "ZEN",
        "gemma_configured": str(
            GEMMA_CLIENT is not None
        ).lower(),
    }


@app.post("/plan", response_class=HTMLResponse)
async def create_plan_page(
    request: Request,
    prompt: str = Form(...),
    deadline: str = Form(...),
    study_minutes_per_day: int = Form(...),
    uploaded_files: List[UploadFile] = File(
        default_factory=list
    ),
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
            "request": request,
            "plan": plan_data["plan"],
            "study_session": plan_data[
                "study_session"
            ],
            "file_names": plan_data["file_names"],
            "study_minutes_per_day": (
                study_minutes_per_day
            ),
            "deadline": deadline,
        },
    )


@app.post("/api/plan")
async def generate_plan_api(
    prompt: str = Form(...),
    deadline: str = Form(...),
    study_minutes_per_day: int = Form(...),
    uploaded_files: List[UploadFile] = File(
        default_factory=list
    ),
) -> JSONResponse:
    plan_data = await build_plan_response(
        prompt=prompt,
        deadline=deadline,
        study_minutes_per_day=study_minutes_per_day,
        uploaded_files=uploaded_files,
    )

    return JSONResponse(plan_data)


# ---------------------------------------------------------
# Chat API
# ---------------------------------------------------------

@app.post("/api/chat")
async def chat_api(
    request: Request,
) -> JSONResponse:
    """
    Receives JSON from the chat UI:

    {
        "message": "Explain memory management",
        "follow_up": ""
    }
    """

    try:
        body = await request.json()
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail="The request must contain valid JSON.",
        ) from exc

    message = str(
        body.get("message", "")
    ).strip()

    follow_up = str(
        body.get("follow_up", "")
    ).strip()

    if not message:
        raise HTTPException(
            status_code=400,
            detail="A message is required.",
        )

    chat_data = await build_chat_response(
        message=message,
        follow_up=follow_up,
    )

    return JSONResponse(
        {
            "reply": chat_data["first_reply"],
            "follow_up_reply": chat_data[
                "follow_up_reply"
            ],
        }
    )


# ---------------------------------------------------------
# Main plan-building flow
# ---------------------------------------------------------

async def build_plan_response(
    prompt: str,
    deadline: str,
    study_minutes_per_day: int,
    uploaded_files: List[UploadFile],
) -> dict[str, Any]:
    file_names: list[str] = []
    extracted_sections: list[str] = []

    for uploaded_file in uploaded_files:
        if not uploaded_file.filename:
            continue

        extracted_text = (
            await extract_text_from_upload(
                uploaded_file
            )
        )

        if extracted_text.strip():
            file_names.append(
                uploaded_file.filename
            )

            extracted_sections.append(
                f"FILE: {uploaded_file.filename}\n"
                f"{extracted_text}"
            )

    raw_text = "\n\n".join(
        extracted_sections
    )

    # When the user uploads nothing, use files from
    # the study_material directory.
    if not raw_text.strip():
        raw_text = load_demo_text_from_folder()

        material_directory = (
            BASE_DIR / "study_material"
        )

        if material_directory.exists():
            file_names = [
                path.name
                for path in sorted(
                    material_directory.glob("*")
                )
                if path.is_file()
            ]

    # Final fallback so that the UI can still be tested.
    if not raw_text.strip():
        raw_text = (
            "Introduction\n"
            "Core concepts\n"
            "Worked examples\n"
            "Practice questions\n"
            "Revision"
        )

    plan = await build_plan_with_gemma(
        prompt=prompt,
        deadline=deadline,
        study_minutes=study_minutes_per_day,
        raw_text=raw_text,
        file_names=file_names,
    )

    focus_topics = plan.get(
        "focus_topics",
        ["Core concepts"],
    )

    study_session = (
        build_placeholder_study_session(
            focus_topics
        )
    )

    return {
        "plan": plan,
        "study_session": study_session,
        "file_names": file_names,
    }


# ---------------------------------------------------------
# Gemma roadmap generation
# ---------------------------------------------------------

async def build_plan_with_gemma(
    prompt: str,
    deadline: str,
    study_minutes: int,
    raw_text: str,
    file_names: List[str],
) -> dict:
    if GEMMA_CLIENT is None:
        return generate_placeholder_plan(
            prompt=prompt,
            deadline=deadline,
            study_minutes_per_day=study_minutes,
            raw_text=raw_text,
            file_names=file_names,
        )

    try:
        response = GEMMA_CLIENT.models.generate_content(
            model=GEMMA_MODEL,
            config=types.GenerateContentConfig(
                thinking_config=types.ThinkingConfig(
                    thinking_level="high"
                ),
                system_instruction=(
                    "You are ZEN, a supportive and "
                    "concise study companion. Help "
                    "the learner understand concepts, "
                    "stay focused and take the next "
                    "small study action."
                ),
            ),
            contents=(
                "Create a short study plan from the following input.\n"
                f"Prompt: {prompt.strip() or 'Keep it small and realistic.'}\n"
                f"Deadline: {deadline}\n"
                f"Study time per day: {study_minutes} minutes\n"
                f"Source files: {', '.join(file_names) if file_names else 'none'}\n"
                f"Source text:\n{raw_text[:12000]}"
            ),
        )
        plan = parse_plan_response(response.text or "", study_minutes)
        if plan is not None:
            return plan
    except Exception:
        pass

    return generate_placeholder_plan(
        prompt=prompt,
        deadline=deadline,
        study_minutes_per_day=study_minutes,
        raw_text=raw_text,
        file_names=file_names,
    )


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


async def build_chat_response(message: str, follow_up: str = "") -> dict:
    if GEMMA_CLIENT is None:
        return {
            "first_reply": "GEMINI_API_KEY is not configured.",
            "follow_up_reply": "",
        }

    try:
        chat = GEMMA_CLIENT.chats.create(model=GEMMA_MODEL)
        first_reply = chat.send_message(message).text or ""
        follow_up_reply = chat.send_message(follow_up).text if follow_up.strip() else ""

        return {
            "first_reply": first_reply,
            "follow_up_reply": follow_up_reply or "",
        }
    except Exception:
        return {
            "first_reply": "Sorry, the Gemma chat request failed.",
            "follow_up_reply": "",
        }

# ---------------------------------------------------------
# File extraction
# ---------------------------------------------------------

async def extract_text_from_upload(
    uploaded_file: UploadFile,
) -> str:
    contents = await uploaded_file.read()

    suffix = Path(
        uploaded_file.filename or ""
    ).suffix.lower()

    try:
        if suffix == ".pptx":
            presentation = Presentation(
                BytesIO(contents)
            )

            return extract_text_from_pptx(
                presentation
            )

        if suffix == ".docx":
            document = Document(
                BytesIO(contents)
            )

            return "\n".join(
                paragraph.text.strip()
                for paragraph in document.paragraphs
                if paragraph.text.strip()
            )

        if suffix == ".txt":
            return contents.decode(
                "utf-8",
                errors="ignore",
            )

    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Could not read "
                f"{uploaded_file.filename}: {exc}"
            ),
        ) from exc

    return ""


def extract_text_from_pptx(
    presentation: Presentation,
) -> str:
    text_parts: list[str] = []

    for slide_number, slide in enumerate(
        presentation.slides,
        start=1,
    ):
        slide_parts: list[str] = []

        for shape in slide.shapes:
            shape_text = getattr(
                shape,
                "text",
                "",
            )

            if (
                shape_text
                and shape_text.strip()
            ):
                slide_parts.append(
                    shape_text.strip()
                )

        if slide_parts:
            text_parts.append(
                f"SLIDE {slide_number}\n"
                + "\n".join(slide_parts)
            )

    return "\n\n".join(text_parts)


def load_demo_text_from_folder() -> str:
    material_dir = (
        BASE_DIR / "study_material"
    )

    if not material_dir.exists():
        return ""

    collected: list[str] = []

    for file_path in sorted(
        material_dir.glob("*")
    ):
        suffix = file_path.suffix.lower()

        try:
            if suffix == ".pptx":
                presentation = Presentation(
                    str(file_path)
                )

                text = extract_text_from_pptx(
                    presentation
                )

            elif suffix == ".docx":
                document = Document(
                    str(file_path)
                )

                text = "\n".join(
                    paragraph.text.strip()
                    for paragraph
                    in document.paragraphs
                    if paragraph.text.strip()
                )

            elif suffix == ".txt":
                text = file_path.read_text(
                    encoding="utf-8",
                    errors="ignore",
                )

            else:
                continue

            if text.strip():
                collected.append(
                    f"FILE: {file_path.name}\n"
                    f"{text}"
                )

        except Exception as exc:
            print(
                f"Could not read "
                f"{file_path.name}: {exc}"
            )

    return "\n\n".join(collected)


# ---------------------------------------------------------
# Placeholder roadmap
# ---------------------------------------------------------

def generate_placeholder_plan(
    prompt: str,
    deadline: str,
    study_minutes_per_day: int,
    raw_text: str,
    file_names: list[str],
) -> dict[str, Any]:
    """
    Used only when Gemma is unavailable or its response
    cannot be parsed.
    """

    topics = extract_placeholder_topics(
        raw_text
    )

    study_minutes = max(
        10,
        min(study_minutes_per_day, 180),
    )

    total_days = determine_placeholder_days(
        deadline
    )

    roadmap: list[dict[str, Any]] = []

    for day_number in range(
        1,
        total_days + 1,
    ):
        topic = topics[
            (day_number - 1) % len(topics)
        ]

        next_topic = topics[
            day_number % len(topics)
        ]

        roadmap.append(
            {
                "day": day_number,
                "title": build_day_title(
                    day_number,
                    topic,
                ),
                "status": (
                    "available"
                    if day_number == 1
                    else "locked"
                ),
                "estimated_minutes": (
                    study_minutes
                ),
                "topics": [
                    topic,
                    next_topic,
                ],
                "objectives": [
                    (
                        "Understand the main "
                        f"ideas behind {topic}."
                    ),
                    (
                        f"Connect {topic} to an "
                        "example from the material."
                    ),
                    (
                        "Complete a short "
                        "knowledge check."
                    ),
                ],
                "lesson": {
                    "introduction": (
                        f"Introduction to {topic}"
                    ),
                    "explanation": (
                        "Review the key ideas "
                        f"connected to {topic} and "
                        "explain them in your own "
                        "words."
                    ),
                    "example": (
                        f"Find one example of {topic} "
                        "inside your uploaded material."
                    ),
                    "recap": [
                        (
                            "State the main meaning "
                            f"of {topic}."
                        ),
                        (
                            f"Explain how {topic} "
                            f"connects to {next_topic}."
                        ),
                        (
                            "Write down one question "
                            "you still have."
                        ),
                    ],
                },
                "quiz": [
                    {
                        "id": (
                            f"day-{day_number}-q-1"
                        ),
                        "topic": topic,
                        "question": (
                            "What is the main idea "
                            f"behind {topic}?"
                        ),
                        "options": [
                            "The central definition",
                            "An unrelated detail",
                            "A file name",
                            "A study deadline",
                        ],
                        "correct_answer": 0,
                        "explanation": (
                            "The first option "
                            "describes the core concept."
                        ),
                    },
                    {
                        "id": (
                            f"day-{day_number}-q-2"
                        ),
                        "topic": topic,
                        "question": (
                            "What is a useful way "
                            f"to review {topic}?"
                        ),
                        "options": [
                            (
                                "Explain it using "
                                "your own words"
                            ),
                            "Ignore all examples",
                            (
                                "Skip the topic "
                                "completely"
                            ),
                            "Only read the title",
                        ],
                        "correct_answer": 0,
                        "explanation": (
                            "Explaining a topic in "
                            "your own words helps "
                            "reveal gaps."
                        ),
                    },
                    {
                        "id": (
                            f"day-{day_number}-q-3"
                        ),
                        "topic": next_topic,
                        "question": (
                            f"Why should {next_topic} "
                            "be connected to earlier "
                            "topics?"
                        ),
                        "options": [
                            (
                                "It helps build a "
                                "logical understanding"
                            ),
                            (
                                "It makes the deadline "
                                "longer"
                            ),
                            (
                                "It removes the "
                                "course files"
                            ),
                            (
                                "It changes the "
                                "file format"
                            ),
                        ],
                        "correct_answer": 0,
                        "explanation": (
                            "Connections between "
                            "topics support deeper "
                            "understanding."
                        ),
                    },
                ],
            }
        )

    source_label = (
        ", ".join(file_names[:2])
        if file_names
        else "your provided material"
    )

    course_title = (
        topics[0].title()
        if topics
        else "Study Course"
    )

    summary = (
        f"ZEN created a {total_days}-day "
        f"study roadmap using {source_label}."
    )

    study_blocks = [
        {
            "title": (
                f"Day {day['day']}: "
                f"{day['title']}"
            ),
            "focus": ", ".join(
                day["topics"]
            ),
            "time": (
                f"{day['estimated_minutes']} "
                "minutes"
            ),
            "goal": day["objectives"][0],
        }
        for day in roadmap
    ]

    return {
        "course_title": course_title,
        "course_summary": summary,
        "learner_goal": (
            prompt.strip()
            or "Make steady study progress."
        ),
        "deadline": (
            deadline.strip()
            or "No deadline provided"
        ),
        "minutes_per_day": study_minutes,
        "total_days": total_days,
        "midpoint_day": max(
            1,
            math.ceil(total_days / 2),
        ),
        "current_day": 1,
        "streak": 0,
        "completed_days": [],
        "weak_topics": [],
        "focus_topics": topics[:6],
        "roadmap": roadmap,
        "summary": summary,
        "custom_prompt": (
            prompt.strip()
            or "Keep the plan realistic."
        ),
        "study_blocks": study_blocks,
        "minimum_win": (
            "Spend 10 minutes reviewing "
            f"{topics[0]} and write three "
            "key ideas."
        ),
        "motivation_note": (
            "Start with one manageable session. "
            "Progress matters more than perfection."
        ),
        "daily_time": (
            f"{study_minutes} minutes per day"
        ),
    }


def determine_placeholder_days(
    deadline: str,
) -> int:
    match = re.search(
        r"\d+",
        deadline or "",
    )

    if not match:
        return 4

    requested_days = int(
        match.group()
    )

    return max(
        2,
        min(requested_days, 10),
    )


def extract_placeholder_topics(
    raw_text: str,
) -> list[str]:
    cleaned_lines: list[str] = []

    for line in raw_text.splitlines():
        cleaned = re.sub(
            r"\s+",
            " ",
            line,
        ).strip()

        cleaned = re.sub(
            r"[^A-Za-z0-9 /&()'-]",
            "",
            cleaned,
        ).strip()

        if len(cleaned) < 4:
            continue

        if len(cleaned) > 80:
            continue

        lowered = cleaned.lower()

        if lowered.startswith(
            (
                "file:",
                "slide ",
                "title:",
            )
        ):
            continue

        cleaned_lines.append(cleaned)

    topics: list[str] = []
    seen: set[str] = set()

    for line in cleaned_lines:
        lowered = line.lower()

        if lowered in seen:
            continue

        if len(line.split()) > 9:
            continue

        seen.add(lowered)
        topics.append(line)

        if len(topics) >= 6:
            break

    if not topics:
        return [
            "Core concepts",
            "Key examples",
            "Practice questions",
            "Revision",
        ]

    return topics


def build_day_title(
    day_number: int,
    topic: str,
) -> str:
    if day_number == 1:
        return (
            f"Getting started with {topic}"
        )

    return f"Understanding {topic}"


# ---------------------------------------------------------
# Placeholder study session
# ---------------------------------------------------------

def build_placeholder_study_session(
    topics: list[str],
) -> dict[str, Any]:
    first_topic = (
        topics[0]
        if topics
        else "the first topic"
    )

    second_topic = (
        topics[1]
        if len(topics) > 1
        else first_topic
    )

    return {
        "title": (
            f"Mini study session: {first_topic}"
        ),
        "explanation": (
            "Begin by identifying the main idea "
            f"behind {first_topic}. Then connect it "
            "to one example from your material."
        ),
        "flashcards": [
            {
                "question": (
                    "What is the main idea behind "
                    f"{first_topic}?"
                ),
                "answer": (
                    "Describe the concept briefly "
                    "in your own words."
                ),
            },
            {
                "question": (
                    f"How does {second_topic} "
                    "connect to the course?"
                ),
                "answer": (
                    "Connect it to a definition, "
                    "example or process."
                ),
            },
        ],
        "quiz": {
            "question": (
                "What should you review first "
                f"about {first_topic}?"
            ),
            "answer": (
                "Start with its main definition "
                "and one clear example."
            ),
        },
        "open_question": (
            f"Explain {first_topic} as though "
            "you were teaching it to a friend."
        ),
    }
