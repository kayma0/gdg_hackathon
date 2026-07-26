from __future__ import annotations

import asyncio
import json
import math
import os
import re
from datetime import date, datetime, timedelta
from io import BytesIO
from pathlib import Path
from typing import Any, List

from dotenv import load_dotenv
from fastapi import (
    FastAPI,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
)
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from google import genai
from google.genai import types

try:
    from docx import Document
except ImportError:
    Document = None

try:
    from pptx import Presentation
except ImportError:
    Presentation = None


# ---------------------------------------------------------
# Application setup
# ---------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent

load_dotenv(BASE_DIR / ".env")

GEMINI_API_KEY = os.getenv(
    "GEMINI_API_KEY",
    "",
).strip()

GEMINI_MODEL = "gemma-4-26b-a4b-it"

GEMINI_CLIENT = (
    genai.Client(api_key=GEMINI_API_KEY)
    if GEMINI_API_KEY
    else None
)

app = FastAPI(
    title="ZEN Study Companion",
    version="0.2.0",
)

app.mount(
    "/static",
    StaticFiles(
        directory=BASE_DIR / "static"
    ),
    name="static",
)

templates = Jinja2Templates(
    directory=BASE_DIR / "templates"
)


LEARNING_STYLE_LIBRARY: dict[str, dict[str, str]] = {
    "visual": {
        "label": "Visual",
        "summary": "Use diagrams, mind maps, colour cues and simple sketches.",
        "day_hint": "Draw a quick diagram before you start the recap.",
        "objective": "Turn {topic} into a simple visual map.",
    },
    "quizzes": {
        "label": "Quizzes",
        "summary": "Finish each study block with short knowledge checks.",
        "day_hint": "End with 3 quick questions to test recall.",
        "objective": "Test yourself on {topic} with a short quiz.",
    },
    "flashcards": {
        "label": "Flashcards",
        "summary": "Convert key ideas into question-and-answer cards.",
        "day_hint": "Make 3 flashcards for the biggest ideas.",
        "objective": "Turn {topic} into flashcard prompts and answers.",
    },
    "audio": {
        "label": "Audio",
        "summary": "Read ideas aloud and explain them in plain language.",
        "day_hint": "Say the idea out loud before writing anything down.",
        "objective": "Explain {topic} out loud in your own words.",
    },
    "notes": {
        "label": "Notes",
        "summary": "Use concise summaries, bullets and clean written recall.",
        "day_hint": "Rewrite the topic as a 3-bullet summary.",
        "objective": "Condense {topic} into a short set of notes.",
    },
}


# ---------------------------------------------------------
# Page routes
# ---------------------------------------------------------

@app.get(
    "/",
    response_class=HTMLResponse,
)
async def index(
    request: Request,
) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "request": request,
        },
    )


@app.get(
    "/health",
)
async def health() -> dict[str, str]:
    return {
        "status": "ok",
        "application": "ZEN",
        "gemma_configured": str(
            GEMINI_CLIENT is not None
        ).lower(),
    }


@app.post(
    "/plan",
    response_class=HTMLResponse,
)
async def create_plan_page(
    request: Request,
    prompt: str = Form(...),
    start_date: str = Form(...),
    deadline: str = Form(...),
    study_minutes_per_day: int = Form(...),
    learning_styles: List[str] = Form(default_factory=list),
    uploaded_files: List[UploadFile] = File(
        default_factory=list
    ),
) -> HTMLResponse:
    plan_data = await build_plan_response(
        prompt=prompt,
        start_date=start_date,
        deadline=deadline,
        study_minutes_per_day=(
            study_minutes_per_day
        ),
        learning_styles=learning_styles,
        uploaded_files=uploaded_files,
    )

    return templates.TemplateResponse(
        request,
        "plan.html",
        {
            "request": request,
            "plan": plan_data["plan"],
            "file_names": plan_data[
                "file_names"
            ],
            "learning_styles": plan_data[
                "learning_styles"
            ],
            "study_minutes_per_day": (
                study_minutes_per_day
            ),
            "start_date": start_date,
            "deadline": deadline,
        },
    )


@app.post(
    "/api/plan",
)
async def generate_plan_api(
    prompt: str = Form(...),
    start_date: str = Form(...),
    deadline: str = Form(...),
    study_minutes_per_day: int = Form(...),
    learning_styles: List[str] = Form(default_factory=list),
    uploaded_files: List[UploadFile] = File(
        default_factory=list
    ),
) -> JSONResponse:
    plan_data = await build_plan_response(
        prompt=prompt,
        start_date=start_date,
        deadline=deadline,
        study_minutes_per_day=study_minutes_per_day,
        learning_styles=learning_styles,
        uploaded_files=uploaded_files,
    )

    return JSONResponse(plan_data)


# ---------------------------------------------------------
# Chat API
# ---------------------------------------------------------

@app.post(
    "/api/chat",
)
async def chat_api(
    request: Request,
) -> JSONResponse:
    try:
        body = await request.json()
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail=(
                "The request must contain "
                "valid JSON."
            ),
        ) from exc

    message = str(
        body.get(
            "message",
            "",
        )
    ).strip()

    follow_up = str(
        body.get(
            "follow_up",
            "",
        )
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
            "reply": chat_data[
                "first_reply"
            ],
            "follow_up_reply": chat_data[
                "follow_up_reply"
            ],
        }
    )


# ---------------------------------------------------------
# Date helpers
# ---------------------------------------------------------

def parse_iso_date(
    value: str,
    field_name: str,
) -> date:
    try:
        return datetime.strptime(
            value,
            "%Y-%m-%d",
        ).date()
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=(
                f"{field_name} must use "
                "the YYYY-MM-DD format."
            ),
        ) from exc


def validate_date_range(
    start_date: str,
    deadline: str,
) -> tuple[date, date]:
    parsed_start = parse_iso_date(
        start_date,
        "Start date",
    )

    parsed_deadline = parse_iso_date(
        deadline,
        "Deadline",
    )

    if parsed_deadline < parsed_start:
        raise HTTPException(
            status_code=400,
            detail=(
                "The deadline cannot be "
                "before the start date."
            ),
        )

    return (
        parsed_start,
        parsed_deadline,
    )


def get_date_range(
    start: date,
    end: date,
) -> list[date]:
    number_of_days = (
        end - start
    ).days + 1

    return [
        start + timedelta(days=index)
        for index in range(
            number_of_days
        )
    ]


def format_display_date(
    study_date: date,
) -> str:
    return study_date.strftime(
        "%a, %d %B %Y"
    )


def format_short_display_date(
    study_date: date,
) -> str:
    return study_date.strftime(
        "%d %b %Y"
    )


def safe_integer(
    value: Any,
    default: int,
) -> int:
    try:
        return int(value)
    except (
        TypeError,
        ValueError,
    ):
        return default


# ---------------------------------------------------------
# Main plan-building flow
# ---------------------------------------------------------

async def build_plan_response(
    prompt: str,
    start_date: str,
    deadline: str,
    study_minutes_per_day: int,
    learning_styles: List[str],
    uploaded_files: List[UploadFile],
) -> dict[str, Any]:
    selected_learning_styles = normalize_learning_styles(
        learning_styles
    )

    parsed_start, parsed_deadline = (
        validate_date_range(
            start_date,
            deadline,
        )
    )

    study_minutes_per_day = max(
        10,
        min(
            study_minutes_per_day,
            180,
        ),
    )

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
                f"FILE: "
                f"{uploaded_file.filename}\n"
                f"{extracted_text}"
            )

    raw_text = "\n\n".join(
        extracted_sections
    )

    if not raw_text.strip():
        raw_text = (
            load_demo_text_from_folder()
        )

        material_directory = (
            BASE_DIR / "study_material"
        )

        if material_directory.exists():
            file_names = [
                path.name
                for path in sorted(
                    material_directory.glob(
                        "*"
                    )
                )
                if path.is_file()
            ]

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
        start_date=parsed_start,
        deadline=parsed_deadline,
        study_minutes=(
            study_minutes_per_day
        ),
        raw_text=raw_text,
        file_names=file_names,
        learning_styles=selected_learning_styles,
    )

    plan = decorate_plan_with_learning_styles(
        plan=plan,
        learning_styles=selected_learning_styles,
    )

    focus_topics = plan.get(
        "focus_topics",
        ["Core concepts"],
    )

    study_session = (
        build_placeholder_study_session(
            focus_topics,
            selected_learning_styles,
        )
    )

    return {
        "plan": plan,
        "file_names": file_names,
        "learning_styles": selected_learning_styles,
    }


# ---------------------------------------------------------
# Gemma roadmap generation
# ---------------------------------------------------------

async def build_plan_with_gemma(
    prompt: str,
    start_date: date,
    deadline: date,
    study_minutes: int,
    raw_text: str,
    file_names: List[str],
    learning_styles: List[str],
) -> dict[str, Any]:
    placeholder_plan = generate_placeholder_plan(
        prompt=prompt,
        start_date=start_date,
        deadline=deadline,
        study_minutes_per_day=study_minutes,
        raw_text=raw_text,
        file_names=file_names,
        learning_styles=learning_styles,
    )

    if GEMINI_CLIENT is None:
        print(
            "GEMINI_API_KEY is not configured. Using placeholder roadmap."
        )
        return placeholder_plan

    calendar_dates = get_date_range(
        start_date,
        deadline,
    )
    date_list = "\n".join(
        (
            f"- Day {index}: {study_date.isoformat()} ({study_date.strftime('%A')})"
        )
        for index, study_date in enumerate(
            calendar_dates,
            start=1,
        )
    )
    source_files = ", ".join(file_names) if file_names else "No filenames supplied"

    system_instruction = (
        "You are ZEN, a supportive study companion. "
        "Create a realistic dated study roadmap and return valid JSON only. "
        f"Adapt the plan to these learning styles: {', '.join(learning_styles) if learning_styles else 'balanced mix'}."
    )
    user_prompt = f"""
LEARNER REQUEST:
{prompt.strip() or 'Help me make steady progress.'}

ROADMAP START DATE:
{start_date.isoformat()}

FINAL DEADLINE:
{deadline.isoformat()}

STUDY TIME PER DAY:
{study_minutes} minutes

SOURCE FILES:
{source_files}

MANDATORY ROADMAP DATES:
{date_list}

COURSE MATERIAL:
--- START MATERIAL ---
{raw_text[:12000]}
--- END MATERIAL ---
"""

    try:
        response = await asyncio.wait_for(
            asyncio.to_thread(
                GEMINI_CLIENT.models.generate_content,
                model=GEMINI_MODEL,
                contents=user_prompt,
                config=types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    temperature=0.2,
                    thinking_config=types.ThinkingConfig(
                        thinking_level="high"
                    ),
                ),
            ),
            timeout=8,
        )
        parsed_plan = parse_plan_response(
            raw_response=response.text or "",
            study_minutes=study_minutes,
            prompt=prompt,
            start_date=start_date,
            deadline=deadline,
        )
        if parsed_plan is not None:
            merged_plan = dict(placeholder_plan)
            merged_plan.update(
                {
                    key: value
                    for key, value in parsed_plan.items()
                    if key
                    in {
                        "summary",
                        "focus_topics",
                        "study_blocks",
                        "minimum_win",
                        "motivation_note",
                        "custom_prompt",
                        "daily_time",
                    }
                }
            )
            return merged_plan
    except asyncio.TimeoutError:
        print("Gemma roadmap request timed out after 8 seconds.")

    except Exception as exc:
        print(f"Gemma roadmap request failed: {exc!r}")

    return placeholder_plan
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
    start_date: date,
    deadline: date,
) -> dict[str, Any] | None:
    cleaned = clean_json_response(
        raw_response
    )

    try:
        parsed = json.loads(
            cleaned
        )
    except json.JSONDecodeError as exc:
        print(
            "Could not parse Gemma "
            f"JSON: {exc}"
        )

        print(
            "Gemma response preview: "
            f"{raw_response[:500]}"
        )

        return None

    if not isinstance(
        parsed,
        dict,
    ):
        return None

    generated_roadmap = parsed.get(
        "roadmap"
    )

    if not isinstance(
        generated_roadmap,
        list,
    ):
        return None

    calendar_dates = get_date_range(
        start_date,
        deadline,
    )

    valid_days: list[
        dict[str, Any]
    ] = []

    for index, expected_date in enumerate(
        calendar_dates,
        start=1,
    ):
        if (
            index - 1 <
            len(generated_roadmap)
            and isinstance(
                generated_roadmap[
                    index - 1
                ],
                dict,
            )
        ):
            day = generated_roadmap[
                index - 1
            ]
        else:
            day = {}

        topics = day.get(
            "topics",
            [],
        )

        objectives = day.get(
            "objectives",
            [],
        )

        quiz = day.get(
            "quiz",
            [],
        )

        lesson = day.get(
            "lesson",
            {},
        )

        if not isinstance(
            topics,
            list,
        ):
            topics = []

        if not isinstance(
            objectives,
            list,
        ):
            objectives = []

        if not isinstance(
            quiz,
            list,
        ):
            quiz = []

        if not isinstance(
            lesson,
            dict,
        ):
            lesson = {}

        clean_topics = [
            str(topic)
            for topic in topics
            if str(topic).strip()
        ]

        if not clean_topics:
            clean_topics = [
                "Core concepts"
            ]

        clean_objectives = [
            str(objective)
            for objective in objectives
            if str(objective).strip()
        ]

        if not clean_objectives:
            clean_objectives = [
                (
                    "Understand the key "
                    "ideas assigned to "
                    "this date."
                ),
                (
                    "Complete a short "
                    "knowledge check."
                ),
            ]

        valid_questions: list[
            dict[str, Any]
        ] = []

        for question_index, question in enumerate(
            quiz[:3],
            start=1,
        ):
            if not isinstance(
                question,
                dict,
            ):
                continue

            options = question.get(
                "options",
                [],
            )

            if not isinstance(
                options,
                list,
            ):
                options = []

            clean_options = [
                str(option)
                for option in options[:4]
            ]

            while len(
                clean_options
            ) < 4:
                clean_options.append(
                    (
                        "Option "
                        f"{len(clean_options) + 1}"
                    )
                )

            correct_answer = safe_integer(
                question.get(
                    "correct_answer",
                    0,
                ),
                0,
            )

            correct_answer = max(
                0,
                min(
                    correct_answer,
                    3,
                ),
            )

            valid_questions.append(
                {
                    "id": str(
                        question.get(
                            "id",
                            (
                                f"day-{index}-"
                                f"q-{question_index}"
                            ),
                        )
                    ),
                    "topic": str(
                        question.get(
                            "topic",
                            clean_topics[0],
                        )
                    ),
                    "question": str(
                        question.get(
                            "question",
                            (
                                "Which statement "
                                "best matches "
                                "today's topic?"
                            ),
                        )
                    ),
                    "options": clean_options,
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

        while len(
            valid_questions
        ) < 3:
            question_number = (
                len(valid_questions) + 1
            )

            valid_questions.append(
                {
                    "id": (
                        f"day-{index}-"
                        f"q-{question_number}"
                    ),
                    "topic": (
                        clean_topics[0]
                    ),
                    "question": (
                        "Which statement "
                        "best matches "
                        "today's topic?"
                    ),
                    "options": [
                        "The central idea",
                        "An unrelated detail",
                        "A filename",
                        "A deadline",
                    ],
                    "correct_answer": 0,
                    "explanation": (
                        "The first option "
                        "describes the "
                        "central idea."
                    ),
                }
            )

        recap = lesson.get(
            "recap",
            [],
        )

        if not isinstance(
            recap,
            list,
        ):
            recap = []

        estimated_minutes = safe_integer(
            day.get(
                "estimated_minutes",
                study_minutes,
            ),
            study_minutes,
        )

        estimated_minutes = max(
            10,
            min(
                estimated_minutes,
                180,
            ),
        )

        valid_days.append(
            {
                "day": index,
                "study_date": (
                    expected_date.isoformat()
                ),
                "display_date": (
                    format_display_date(
                        expected_date
                    )
                ),
                "weekday_short": (
                    expected_date.strftime(
                        "%a"
                    )
                ),
                "month_short": (
                    expected_date.strftime(
                        "%b"
                    ).upper()
                ),
                "day_number": (
                    expected_date.strftime(
                        "%d"
                    )
                ),
                "title": str(
                    day.get(
                        "title",
                        (
                            f"Study Day "
                            f"{index}"
                        ),
                    )
                ),
                "status": (
                    "available"
                    if index == 1
                    else "locked"
                ),
                "estimated_minutes": (
                    estimated_minutes
                ),
                "topics": clean_topics,
                "objectives": (
                    clean_objectives
                ),
                "lesson": {
                    "introduction": str(
                        lesson.get(
                            "introduction",
                            (
                                "Today's "
                                "learning session"
                            ),
                        )
                    ),
                    "explanation": str(
                        lesson.get(
                            "explanation",
                            (
                                "Review the "
                                "assigned topics "
                                "and explain them "
                                "in your own words."
                            ),
                        )
                    ),
                    "example": str(
                        lesson.get(
                            "example",
                            (
                                "Find an example "
                                "inside your "
                                "uploaded material."
                            ),
                        )
                    ),
                    "recap": [
                        str(item)
                        for item in recap
                    ],
                },
                "quiz": valid_questions,
            }
        )

    focus_topics = parsed.get(
        "focus_topics",
        [],
    )

    if not isinstance(
        focus_topics,
        list,
    ):
        focus_topics = []

    if not focus_topics:
        for roadmap_day in valid_days:
            focus_topics.extend(
                roadmap_day["topics"]
            )

    focus_topics = list(
        dict.fromkeys(
            str(topic)
            for topic in focus_topics
            if str(topic).strip()
        )
    )[:8]

    if not focus_topics:
        focus_topics = [
            "Core concepts"
        ]

    total_days = len(
        valid_days
    )

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
                "Your dated roadmap is ready.",
            )
        ),
        "learner_goal": str(
            parsed.get(
                "learner_goal",
                (
                    prompt.strip()
                    or "Make steady progress."
                ),
            )
        ),
        "start_date": (
            start_date.isoformat()
        ),
        "deadline": (
            deadline.isoformat()
        ),
        "start_display_date": (
            format_short_display_date(
                start_date
            )
        ),
        "deadline_display_date": (
            format_short_display_date(
                deadline
            )
        ),
        "start_month": (
            start_date.strftime(
                "%b"
            ).upper()
        ),
        "start_day_number": (
            start_date.strftime(
                "%d"
            )
        ),
        "minutes_per_day": (
            study_minutes
        ),
        "total_days": total_days,
        "midpoint_day": max(
            1,
            math.ceil(
                total_days / 2
            ),
        ),
        "current_day": 1,
        "streak": 0,
        "completed_days": [],
        "weak_topics": [],
        "focus_topics": focus_topics,
        "roadmap": valid_days,
    }


def normalize_learning_styles(learning_styles: List[str]) -> List[str]:
    selected: list[str] = []
    seen: set[str] = set()

    for raw_style in learning_styles:
        style = str(raw_style).strip().lower()

        if not style:
            continue

        if style not in LEARNING_STYLE_LIBRARY:
            continue

        if style in seen:
            continue

        seen.add(style)
        selected.append(style)

    return selected or ["balanced"]


def build_learning_style_guidance(
    learning_styles: List[str],
) -> dict[str, Any]:
    selected = normalize_learning_styles(learning_styles)

    if selected == ["balanced"]:
        return {
            "title": "Balanced study mode",
            "summary": (
                "The roadmap will mix visuals, recall, summaries and quick checks so the plan stays flexible."
            ),
            "highlights": [
                {
                    "label": "Balanced",
                    "description": (
                        "A mix of short explanations, quick practice and clear recap steps."
                    ),
                }
            ],
            "primary_label": "Balanced",
        }

    highlights: list[dict[str, str]] = []
    for style in selected:
        profile = LEARNING_STYLE_LIBRARY[style]
        highlights.append(
            {
                "label": profile["label"],
                "description": profile["summary"],
            }
        )

    primary_label = ", ".join(
        LEARNING_STYLE_LIBRARY[style]["label"]
        for style in selected
    )

    summary = (
        "This roadmap will emphasise "
        f"{primary_label.lower()} so the next page shows the ideas "
        "in the format you learn best."
    )

    return {
        "title": "Learning style roadmap",
        "summary": summary,
        "highlights": highlights,
        "primary_label": primary_label,
    }


def build_style_hint(
    style_key: str,
    topic: str,
) -> str:
    if style_key == "balanced":
        return (
            f"Balanced cue: review {topic} with a short summary, example and recall check."
        )

    profile = LEARNING_STYLE_LIBRARY[style_key]

    return profile["day_hint"].replace("your topic", topic)


def build_style_objective(
    style_key: str,
    topic: str,
) -> str:
    if style_key == "balanced":
        return (
            f"Understand the main ideas behind {topic}."
        )

    profile = LEARNING_STYLE_LIBRARY[style_key]
    return profile["objective"].format(topic=topic)


def decorate_plan_with_learning_styles(
    plan: dict[str, Any],
    learning_styles: List[str],
) -> dict[str, Any]:
    selected = normalize_learning_styles(learning_styles)
    roadmap = plan.get("roadmap", [])

    for day_number, day in enumerate(roadmap, start=1):
        style_key = selected[(day_number - 1) % len(selected)]
        topic = day.get("topics", ["the topic"])[0]

        day["style_key"] = style_key
        day["style_label"] = (
            "Balanced"
            if style_key == "balanced"
            else LEARNING_STYLE_LIBRARY[style_key]["label"]
        )
        day["style_hint"] = build_style_hint(
            style_key,
            topic,
        )

        objectives = list(day.get("objectives", []))
        if objectives:
            objectives[0] = build_style_objective(
                style_key,
                topic,
            )
            day["objectives"] = objectives

        lesson = day.get("lesson", {})
        if isinstance(lesson, dict):
            lesson["explanation"] = (
                f"Use a {day['style_label'].lower()} approach to study {topic}. "
                f"{day['style_hint']}"
            )
            day["lesson"] = lesson

        quiz_items = day.get("quiz", [])
        if isinstance(quiz_items, list) and quiz_items:
            quiz_items[0]["explanation"] = (
                f"This question fits a {day['style_label'].lower()} review style."
            )
            day["quiz"] = quiz_items

    plan["learning_styles"] = selected
    plan["learning_style_guidance"] = build_learning_style_guidance(
        selected
    )

    if plan.get("study_blocks"):
        study_blocks = list(plan["study_blocks"])
        for index, block in enumerate(study_blocks):
            style_key = selected[index % len(selected)]
            style_label = (
                "Balanced"
                if style_key == "balanced"
                else LEARNING_STYLE_LIBRARY[style_key]["label"]
            )
            block["style_label"] = style_label
            block["style_hint"] = build_style_hint(
                style_key,
                str(block.get("focus", "the topic")),
            )
        plan["study_blocks"] = study_blocks

    return plan


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
                "The ZEN chat interface "
                "is working, but the "
                "Gemma API key is not "
                "configured."
            ),
            "follow_up_reply": "",
        }

    try:
        chat = await asyncio.to_thread(
            GEMINI_CLIENT.chats.create,
            model=GEMINI_MODEL,
            config=types.GenerateContentConfig(
                system_instruction=(
                    "You are ZEN, a "
                    "supportive and concise "
                    "study companion. Help "
                    "the learner understand "
                    "concepts, stay focused "
                    "and take the next small "
                    "study action."
                ),
                temperature=0.4,
            )
        )

        first_response = await asyncio.wait_for(
            asyncio.to_thread(
                chat.send_message,
                message,
            ),
            timeout=8,
        )

        first_reply = (
            first_response.text or ""
        ).strip()

        follow_up_reply = ""

        if follow_up:
            second_response = await asyncio.wait_for(
                asyncio.to_thread(
                    chat.send_message,
                    follow_up,
                ),
                timeout=8,
            )

            follow_up_reply = (
                second_response.text or ""
            ).strip()

        return {
            "first_reply": (
                first_reply
                or "I could not generate "
                "a reply."
            ),
            "follow_up_reply": (
                follow_up_reply
            ),
        }

    except asyncio.TimeoutError:
        print("Gemma chat request timed out after 8 seconds.")

    except Exception as exc:
        print(
            "Gemma chat request "
            f"failed: {exc!r}"
        )

        return {
            "first_reply": (
                "Sorry, ZEN could not "
                "complete that chat request."
            ),
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
            if Presentation is None:
                return ""

            presentation = Presentation(
                BytesIO(contents)
            )

            return extract_text_from_pptx(
                presentation
            )

        if suffix == ".docx":
            if Document is None:
                return ""

            document = Document(
                BytesIO(contents)
            )

            return "\n".join(
                paragraph.text.strip()
                for paragraph
                in document.paragraphs
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
                "Could not read "
                f"{uploaded_file.filename}: "
                f"{exc}"
            ),
        ) from exc

    return ""


def extract_text_from_pptx(
    presentation: Any,
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
                + "\n".join(
                    slide_parts
                )
            )

    return "\n\n".join(
        text_parts
    )


def load_demo_text_from_folder() -> str:
    material_directory = (
        BASE_DIR / "study_material"
    )

    if not material_directory.exists():
        return ""

    collected: list[str] = []

    for file_path in sorted(
        material_directory.glob("*")
    ):
        suffix = (
            file_path.suffix.lower()
        )

        try:
            if suffix == ".pptx":
                if Presentation is None:
                    continue

                presentation = Presentation(
                    str(file_path)
                )

                text = (
                    extract_text_from_pptx(
                        presentation
                    )
                )

            elif suffix == ".docx":
                if Document is None:
                    continue

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
                    f"FILE: "
                    f"{file_path.name}\n"
                    f"{text}"
                )

        except Exception as exc:
            print(
                "Could not read "
                f"{file_path.name}: {exc}"
            )

    return "\n\n".join(
        collected
    )


# ---------------------------------------------------------
# Placeholder dated roadmap
# ---------------------------------------------------------

def generate_placeholder_plan(
    prompt: str,
    start_date: date,
    deadline: date,
    study_minutes_per_day: int,
    raw_text: str,
    file_names: list[str],
    learning_styles: List[str] | None = None,
) -> dict[str, Any]:
    topics = extract_placeholder_topics(
        raw_text
    )
    selected_learning_styles = normalize_learning_styles(
        learning_styles or []
    )

    study_minutes = max(
        10,
        min(
            study_minutes_per_day,
            180,
        ),
    )

    calendar_dates = get_date_range(
        start_date,
        deadline,
    )

    total_days = len(calendar_dates)

    roadmap: list[
        dict[str, Any]
    ] = []

    for index, study_date in enumerate(
        calendar_dates,
        start=1,
    ):
        topic = topics[
            (index - 1) % len(topics)
        ]

        next_topic = topics[
            index % len(topics)
        ]

        is_final_day = (
            index == len(
                calendar_dates
            )
        )

        if is_final_day:
            title = (
                "Final review and "
                "course consolidation"
            )

            day_topics = [
                topic,
                "Final review",
            ]
        else:
            title = (
                f"Understanding {topic}"
                if index > 1
                else (
                    "Getting started "
                    f"with {topic}"
                )
            )

            day_topics = [
                topic,
                next_topic,
            ]

        roadmap.append(
            {
                "day": index,
                "study_date": (
                    study_date.isoformat()
                ),
                "display_date": (
                    format_display_date(
                        study_date
                    )
                ),
                "weekday_short": (
                    study_date.strftime(
                        "%a"
                    )
                ),
                "month_short": (
                    study_date.strftime(
                        "%b"
                    ).upper()
                ),
                "day_number": (
                    study_date.strftime(
                        "%d"
                    )
                ),
                "title": title,
                "status": (
                    "available"
                    if index == 1
                    else "locked"
                ),
                "estimated_minutes": (
                    study_minutes
                ),
                "topics": day_topics,
                "objectives": [
                    build_style_objective(
                        selected_learning_styles[
                            (index - 1)
                            % len(selected_learning_styles)
                        ],
                        topic,
                    ),
                    (
                        f"Connect {topic} to "
                        "an example from the "
                        "material."
                    ),
                    (
                        "Complete a short "
                        "knowledge check."
                    ),
                ],
                "lesson": {
                    "introduction": (
                        f"Introduction to "
                        f"{topic}"
                    ),
                    "explanation": (
                        "Review the key ideas "
                        f"connected to {topic} "
                        "and explain them in "
                        "your own words."
                    ),
                    "example": (
                        "Find one example of "
                        f"{topic} inside your "
                        "uploaded material."
                    ),
                    "recap": [
                        (
                            "State the main "
                            f"meaning of {topic}."
                        ),
                        (
                            f"Explain how {topic} "
                            f"connects to "
                            f"{next_topic}."
                        ),
                        (
                            "Write down one "
                            "question you still "
                            "have."
                        ),
                    ],
                },
                "quiz": [
                    {
                        "id": (
                            f"day-{index}-q-1"
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
                            f"day-{index}-q-2"
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
                            f"day-{index}-q-3"
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
                "style_key": selected_learning_styles[
                    (index - 1)
                    % len(selected_learning_styles)
                ],
                "style_label": (
                    "Balanced"
                    if selected_learning_styles[
                        (index - 1)
                        % len(selected_learning_styles)
                    ] == "balanced"
                    else LEARNING_STYLE_LIBRARY[
                        selected_learning_styles[
                            (index - 1)
                            % len(selected_learning_styles)
                        ]
                    ]["label"]
                ),
                "style_hint": build_style_hint(
                    selected_learning_styles[
                        (index - 1)
                        % len(selected_learning_styles)
                    ],
                    topic,
                ),
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
            "style_label": day["style_label"],
            "style_hint": day["style_hint"],
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
            deadline.isoformat()
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
        "learning_styles": selected_learning_styles,
        "learning_style_guidance": build_learning_style_guidance(
            selected_learning_styles
        ),
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


def create_placeholder_quiz(
    day_number: int,
    topic: str,
    next_topic: str,
) -> list[dict[str, Any]]:
    return [
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
                "A filename",
                "A study deadline",
            ],
            "correct_answer": 0,
            "explanation": (
                "The first option "
                "describes the core "
                "concept."
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
                "Skip the topic",
                "Only read the title",
            ],
            "correct_answer": 0,
            "explanation": (
                "Explaining a topic in "
                "your own words reveals "
                "gaps in understanding."
            ),
        },
        {
            "id": (
                f"day-{day_number}-q-3"
            ),
            "topic": next_topic,
            "question": (
                f"Why should {next_topic} "
                "connect to earlier topics?"
            ),
            "options": [
                (
                    "It builds logical "
                    "understanding"
                ),
                (
                    "It makes the "
                    "deadline longer"
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
    ]


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

        cleaned_lines.append(
            cleaned
        )

    topics: list[str] = []
    seen: set[str] = set()

    for line in cleaned_lines:
        lowered = line.lower()

        if lowered in seen:
            continue

        if len(
            line.split()
        ) > 9:
            continue

        seen.add(
            lowered
        )

        topics.append(
            line
        )

        if len(topics) >= 8:
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
    learning_styles: list[str] | None = None,
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
    selected_learning_styles = normalize_learning_styles(
        learning_styles or []
    )
    primary_style = selected_learning_styles[0]
    style_label = (
        "Balanced"
        if primary_style == "balanced"
        else LEARNING_STYLE_LIBRARY[primary_style]["label"]
    )
    style_hint = build_style_hint(
        primary_style,
        first_topic,
    )

    return {
        "title": (
            f"Mini study session: {first_topic}"
        ),
        "explanation": (
            "Begin by identifying the main idea "
            f"behind {first_topic}. Then connect it "
            "to one example from your material. "
            f"Style focus: {style_label}. {style_hint}"
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
        "style_label": style_label,
        "style_hint": style_hint,
    }
