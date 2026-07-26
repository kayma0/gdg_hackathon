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

<<<<<<< Updated upstream
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = "gemma-4-26b-a4b-it"
=======
GEMMA_API_KEY = os.getenv("GEMMA_API_KEY", "").strip()
GEMMA_MODEL = "gemma-4-26b-a4b-it"
GEMMA_CLIENT = genai.Client() if GEMMA_API_KEY else None
>>>>>>> Stashed changes

GEMINI_CLIENT = (
    genai.Client(api_key=GEMINI_API_KEY)
    if GEMINI_API_KEY
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
            GEMINI_CLIENT is not None
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

<<<<<<< Updated upstream
    plan = await build_plan_with_gemma(
=======
    # TEMPORARY:
    # Replace this function call with the Gemma function later.
    plan = generate_placeholder_plan()
    plan=await build_plan_with_gemma(
>>>>>>> Stashed changes
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
<<<<<<< Updated upstream
) -> dict[str, Any]:
    """
    Ask Gemma to generate the roadmap.

    If the API is unavailable or returns invalid JSON,
    ZEN uses a placeholder plan so the UI does not crash.
    """

    if GEMINI_CLIENT is None:
        print(
            "GEMINI_API_KEY is not configured. "
            "Using placeholder roadmap."
        )

        return generate_placeholder_plan(
            prompt=prompt,
            deadline=deadline,
            study_minutes_per_day=study_minutes,
            raw_text=raw_text,
            file_names=file_names,
        )

    system_instruction = """
You are ZEN, an adaptive study companion.

Analyse the supplied school material and generate a realistic,
day-by-day study roadmap.

You must decide:

- the major topics
- prerequisite order
- how topics should be divided across study days
- each day's learning objectives
- concise lesson content
- three quiz questions for every day

Return valid JSON only.
Do not return markdown.
Do not include text outside the JSON object.
"""

    source_files = (
        ", ".join(file_names)
        if file_names
        else "No filenames supplied"
    )

    user_prompt = f"""
LEARNER REQUEST:
{prompt.strip() or "Help me make steady progress."}

DEADLINE:
{deadline.strip() or "Not specified"}

STUDY TIME PER DAY:
{study_minutes} minutes

SOURCE FILES:
{source_files}

COURSE MATERIAL:
--- START MATERIAL ---
{raw_text[:12000]}
--- END MATERIAL ---

Return JSON using this exact structure:

{{
  "course_title": "string",
  "course_summary": "string",
  "learner_goal": "string",
  "deadline": "string",
  "minutes_per_day": {study_minutes},
  "total_days": 4,
  "midpoint_day": 2,
  "current_day": 1,
  "streak": 0,
  "completed_days": [],
  "weak_topics": [],
  "focus_topics": [
    "string"
  ],
  "roadmap": [
    {{
      "day": 1,
      "title": "string",
      "status": "available",
      "estimated_minutes": {study_minutes},
      "topics": [
        "string"
      ],
      "objectives": [
        "string"
      ],
      "lesson": {{
        "introduction": "string",
        "explanation": "string",
        "example": "string",
        "recap": [
          "string"
        ]
      }},
      "quiz": [
        {{
          "id": "day-1-q-1",
          "topic": "string",
          "question": "string",
          "options": [
            "string",
            "string",
            "string",
            "string"
          ],
          "correct_answer": 0,
          "explanation": "string"
        }}
      ]
    }}
  ],
  "summary": "string",
  "study_blocks": [
    {{
      "title": "string",
      "focus": "string",
      "time": "string",
      "goal": "string"
    }}
  ],
  "minimum_win": "string",
  "motivation_note": "string",
  "custom_prompt": "string",
  "daily_time": "string"
}}

Important rules:

1. Create exactly three quiz questions per day.
2. Every quiz question must have exactly four options.
3. correct_answer must be an integer from 0 to 3.
4. Only Day 1 should have status "available".
5. All later days should have status "locked".
6. Keep the plan realistic for the learner's available time.
7. Base the educational content on the supplied material.
"""

    try:
        response = (
            GEMINI_CLIENT.models.generate_content(
                model=GEMINI_MODEL,
                contents=user_prompt,
                config=types.GenerateContentConfig(
                    system_instruction=(
                        system_instruction
                    ),
                    temperature=0.2,
                    thinking_config=(
                        types.ThinkingConfig(
                            thinking_level="high"
                        )
                    ),
                ),
            )
        )

        parsed_plan = parse_plan_response(
            response.text or "",
            study_minutes=study_minutes,
            prompt=prompt,
            deadline=deadline,
        )

        if parsed_plan is not None:
            return parsed_plan

        print(
            "Gemma returned invalid roadmap JSON. "
            "Using placeholder roadmap."
        )

    except Exception as exc:
        print(
            f"Gemma roadmap request failed: {exc}"
        )

    return generate_placeholder_plan(
        prompt=prompt,
        deadline=deadline,
        study_minutes_per_day=study_minutes,
        raw_text=raw_text,
        file_names=file_names,
    )


def clean_json_response(
    raw_response: str,
) -> str:
    cleaned = raw_response.strip()

    cleaned = re.sub(
        r"^```(?:json)?\s*",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )

    cleaned = re.sub(
        r"\s*```$",
        "",
        cleaned,
    )

    return cleaned.strip()


def parse_plan_response(
    raw_response: str,
    study_minutes: int,
    prompt: str,
    deadline: str,
) -> dict[str, Any] | None:
    cleaned = clean_json_response(
        raw_response
    )

    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        print(
            f"Could not parse Gemma JSON: {exc}"
        )
        print(
            f"Gemma response preview: "
            f"{raw_response[:500]}"
        )
        return None

    if not isinstance(parsed, dict):
        return None

    roadmap = parsed.get("roadmap")

    if not isinstance(roadmap, list):
        return None

    if not roadmap:
        return None

    valid_days: list[dict[str, Any]] = []

    for index, day in enumerate(
        roadmap,
        start=1,
    ):
        if not isinstance(day, dict):
            continue

        topics = day.get("topics", [])
        objectives = day.get(
            "objectives",
            [],
        )
        quiz = day.get("quiz", [])
        lesson = day.get("lesson", {})

        if not isinstance(topics, list):
            topics = []

        if not isinstance(objectives, list):
            objectives = []

        if not isinstance(quiz, list):
            quiz = []

        if not isinstance(lesson, dict):
            lesson = {}

        valid_questions: list[
            dict[str, Any]
        ] = []

        for question_index, question in enumerate(
            quiz[:3],
            start=1,
        ):
            if not isinstance(question, dict):
                continue

            options = question.get(
                "options",
                [],
            )

            if not isinstance(options, list):
                options = []

            options = [
                str(option)
                for option in options[:4]
            ]

            while len(options) < 4:
                options.append(
                    f"Option {len(options) + 1}"
                )

            correct_answer = question.get(
                "correct_answer",
                0,
            )

            if not isinstance(
                correct_answer,
                int,
            ):
                correct_answer = 0

            correct_answer = max(
                0,
                min(correct_answer, 3),
            )

            valid_questions.append(
                {
                    "id": str(
                        question.get(
                            "id",
                            (
                                f"day-{index}-q-"
                                f"{question_index}"
                            ),
                        )
                    ),
                    "topic": str(
                        question.get(
                            "topic",
                            topics[0]
                            if topics
                            else "Core concept",
                        )
                    ),
                    "question": str(
                        question.get(
                            "question",
                            "Review this topic.",
                        )
                    ),
                    "options": options,
                    "correct_answer": (
                        correct_answer
                    ),
                    "explanation": str(
                        question.get(
                            "explanation",
                            "",
                        )
                    ),
                }
            )

        while len(valid_questions) < 3:
            question_number = (
                len(valid_questions) + 1
            )

            valid_questions.append(
                {
                    "id": (
                        f"day-{index}-q-"
                        f"{question_number}"
                    ),
                    "topic": (
                        topics[0]
                        if topics
                        else "Core concept"
                    ),
                    "question": (
                        "Which statement best "
                        "matches this topic?"
                    ),
                    "options": [
                        "The central idea",
                        "An unrelated detail",
                        "A file name",
                        "A deadline",
                    ],
                    "correct_answer": 0,
                    "explanation": (
                        "The first option describes "
                        "the central idea."
                    ),
                }
            )

        valid_days.append(
            {
                "day": index,
                "title": str(
                    day.get(
                        "title",
                        f"Study Day {index}",
                    )
                ),
                "status": (
                    "available"
                    if index == 1
                    else "locked"
                ),
                "estimated_minutes": int(
                    day.get(
                        "estimated_minutes",
                        study_minutes,
                    )
                ),
                "topics": [
                    str(topic)
                    for topic in topics
                ],
                "objectives": [
                    str(objective)
                    for objective in objectives
                ],
                "lesson": {
                    "introduction": str(
                        lesson.get(
                            "introduction",
                            "",
                        )
                    ),
                    "explanation": str(
                        lesson.get(
                            "explanation",
                            "",
                        )
                    ),
                    "example": str(
                        lesson.get(
                            "example",
                            "",
                        )
                    ),
                    "recap": [
                        str(item)
                        for item in lesson.get(
                            "recap",
                            [],
                        )
                    ]
                    if isinstance(
                        lesson.get("recap", []),
                        list,
                    )
                    else [],
                },
                "quiz": valid_questions,
            }
        )

    if not valid_days:
        return None

    focus_topics = parsed.get(
        "focus_topics",
        [],
    )

    if not isinstance(focus_topics, list):
        focus_topics = []

    if not focus_topics:
        for day in valid_days:
            focus_topics.extend(
                day["topics"]
            )

    focus_topics = list(
        dict.fromkeys(
            str(topic)
            for topic in focus_topics
            if str(topic).strip()
        )
    )[:6]

    if not focus_topics:
        focus_topics = ["Core concepts"]

    total_days = len(valid_days)

    study_blocks = parsed.get(
        "study_blocks",
        [],
    )

    if not isinstance(study_blocks, list):
        study_blocks = []

    if not study_blocks:
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
                "goal": (
                    day["objectives"][0]
                    if day["objectives"]
                    else "Complete today's lesson."
                ),
            }
            for day in valid_days
        ]

    return {
        "course_title": str(
            parsed.get(
                "course_title",
                "ZEN Study Roadmap",
            )
        ),
        "course_summary": str(
            parsed.get(
                "course_summary",
                parsed.get(
                    "summary",
                    "Your roadmap is ready.",
                ),
            )
        ),
        "learner_goal": str(
            parsed.get(
                "learner_goal",
                prompt.strip()
                or "Make steady progress.",
            )
        ),
        "deadline": str(
            parsed.get(
                "deadline",
                deadline,
            )
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
        "focus_topics": focus_topics,
        "roadmap": valid_days,
        "summary": str(
            parsed.get(
                "summary",
                "Your study roadmap is ready.",
            )
        ),
        "study_blocks": study_blocks,
        "minimum_win": str(
            parsed.get(
                "minimum_win",
                (
                    "Spend 10 minutes reviewing "
                    "the first topic."
                ),
            )
        ),
        "motivation_note": str(
            parsed.get(
                "motivation_note",
                (
                    "Start small and keep "
                    "moving forward."
                ),
            )
        ),
        "custom_prompt": str(
            parsed.get(
                "custom_prompt",
                prompt.strip()
                or "Keep it realistic.",
            )
        ),
        "daily_time": str(
            parsed.get(
                "daily_time",
                f"{study_minutes} minutes per day",
            )
        ),
    }


# ---------------------------------------------------------
# Gemma chat
# ---------------------------------------------------------

async def build_chat_response(
    message: str,
    follow_up: str = "",
) -> dict[str, str]:
    if GEMINI_CLIENT is None:
        return {
            "first_reply": (
                "The ZEN chat interface is working, "
                "but GEMINI_API_KEY is not configured."
            ),
            "follow_up_reply": "",
        }

    try:
        chat = GEMINI_CLIENT.chats.create(
            model=GEMINI_MODEL,
=======
) -> dict:
    if GEMMA_CLIENT is None:
        return build_plan(prompt, deadline, study_minutes, raw_text, file_names)

    try:
        response=GEMMA_CLIENT.models.generate_content(
            model=GEMMA_MODEL,
>>>>>>> Stashed changes
            config=types.GenerateContentConfig(
                system_instruction=(
                    "You are ZEN, a supportive and "
                    "concise study companion. Help "
                    "the learner understand concepts, "
                    "stay focused and take the next "
                    "small study action."
                ),
                temperature=0.4,
            ),
        )

        first_response = chat.send_message(
            message
        )

        first_reply = (
            first_response.text or ""
        ).strip()

        follow_up_reply = ""

        if follow_up:
            second_response = chat.send_message(
                follow_up
            )

            follow_up_reply = (
                second_response.text or ""
            ).strip()

<<<<<<< Updated upstream
        return {
            "first_reply": (
                first_reply
                or "I could not generate a reply."
            ),
            "follow_up_reply": (
                follow_up_reply
            ),
        }

    except Exception as exc:
        print(
            f"Gemma chat request failed: {exc}"
        )

        return {
            "first_reply": (
                "Sorry, ZEN could not complete "
                "that chat request."
            ),
            "follow_up_reply": "",
        }

=======
async def build_chat_response(message: str, follow_up: str="") -> dict:
    if GEMMA_CLIENT is None:
        return {
            "first_reply": "GEMMA_API_KEY is not configured.",
            "follow_up_reply": "",
        }

    try:
        chat=GEMMA_CLIENT.chats.create(model=GEMMA_MODEL)
        first_reply=chat.send_message(message).text or ""
        follow_up_reply=chat.send_message(
            follow_up).text if follow_up.strip() else ""
        return {
            "first_reply": first_reply,
            "follow_up_reply": follow_up_reply or "",
        }
    except Exception:
        return {
            "first_reply": "Sorry, the Gemma chat request failed.",
            "follow_up_reply": "",
        }
>>>>>>> Stashed changes

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
