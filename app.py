from __future__ import annotations

import json
import math
import os
import re
from datetime import date, datetime, timedelta
from io import BytesIO
from pathlib import Path
from typing import Any, List

from docx import Document
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
from pptx import Presentation
from pydantic import BaseModel


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


class LessonRequest(BaseModel):
    day: int
    study_date: str
    title: str
    topics: list[str]
    objectives: list[str]
    estimated_minutes: int


class GradeRequest(BaseModel):
    lesson: dict[str, Any]
    selected_answers: list[int]

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
    uploaded_files: List[UploadFile] = File(
        default_factory=list
    ),
) -> JSONResponse:
    plan_data = await build_plan_response(
        prompt=prompt,
        start_date=start_date,
        deadline=deadline,
        study_minutes_per_day=(
            study_minutes_per_day
        ),
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


@app.post("/api/lesson")
async def generate_lesson_api(
    lesson_request: LessonRequest,
) -> JSONResponse:
    lesson = await generate_level_with_gemma(
        day=lesson_request.day,
        study_date=lesson_request.study_date,
        title=lesson_request.title,
        topics=lesson_request.topics,
        objectives=lesson_request.objectives,
        estimated_minutes=lesson_request.estimated_minutes,
    )

    return JSONResponse(lesson)


@app.post("/api/grade")
async def grade_lesson_api(
    grade_request: GradeRequest,
) -> JSONResponse:
    quiz = grade_request.lesson.get("quiz", [])
    selected_answers = grade_request.selected_answers

    if not isinstance(quiz, list) or not quiz:
        raise HTTPException(
            status_code=400,
            detail="The lesson does not contain a quiz.",
        )

    results: list[dict[str, Any]] = []
    correct_count = 0

    for index, question in enumerate(quiz):
        selected_answer = (
            selected_answers[index]
            if index < len(selected_answers)
            else -1
        )

        correct_answer = int(
            question.get("correct_answer", 0)
        )

        is_correct = (
            selected_answer == correct_answer
        )

        if is_correct:
            correct_count += 1

        options = question.get("options", [])

        selected_text = (
            options[selected_answer]
            if (
                isinstance(options, list)
                and 0 <= selected_answer < len(options)
            )
            else "No answer selected"
        )

        correct_text = (
            options[correct_answer]
            if (
                isinstance(options, list)
                and 0 <= correct_answer < len(options)
            )
            else ""
        )

        results.append(
            {
                "question": question.get(
                    "question",
                    "",
                ),
                "topic": question.get(
                    "topic",
                    "",
                ),
                "selected_answer": selected_text,
                "correct_answer": correct_text,
                "is_correct": is_correct,
                "explanation": question.get(
                    "explanation",
                    "",
                ),
            }
        )

    total_questions = len(quiz)

    score = round(
        (
            correct_count /
            total_questions
        ) * 100
    )

    weak_topics = list(
        dict.fromkeys(
            result["topic"]
            for result in results
            if (
                not result["is_correct"]
                and result["topic"]
            )
        )
    )

    feedback = await generate_quiz_feedback_with_gemma(
        lesson=grade_request.lesson,
        score=score,
        results=results,
        weak_topics=weak_topics,
    )

    return JSONResponse(
        {
            "score": score,
            "correct_count": correct_count,
            "total_questions": total_questions,
            "results": results,
            "weak_topics": weak_topics,
            "feedback": feedback,
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
    uploaded_files: List[UploadFile],
) -> dict[str, Any]:
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
    )

    return {
        "plan": plan,
        "file_names": file_names,
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
) -> dict[str, Any]:
    if GEMINI_CLIENT is None:
        print(
            "GEMINI_API_KEY is not "
            "configured. Using placeholder "
            "roadmap."
        )

        return generate_placeholder_plan(
            prompt=prompt,
            start_date=start_date,
            deadline=deadline,
            study_minutes_per_day=(
                study_minutes
            ),
            raw_text=raw_text,
            file_names=file_names,
        )

    calendar_dates = get_date_range(
        start_date,
        deadline,
    )

    total_days = len(
        calendar_dates
    )

    date_list = "\n".join(
        (
            f"- Day {index}: "
            f"{study_date.isoformat()} "
            f"({study_date.strftime('%A')})"
        )
        for index, study_date in enumerate(
            calendar_dates,
            start=1,
        )
    )

    system_instruction = """
You are ZEN, an adaptive study companion.

Analyse the supplied school material and generate a realistic,
date-based study roadmap.

You must decide:

- the major topics
- prerequisite order
- how topics should be divided across the available dates
- each date's learning objectives
- concise lesson content
- exactly three quiz questions for every date

The dates supplied by the application are mandatory.

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

ROADMAP START DATE:
{start_date.isoformat()}

FINAL DEADLINE:
{deadline.isoformat()}

TOTAL AVAILABLE CALENDAR DAYS:
{total_days}

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

Create exactly one roadmap entry for every mandatory date.

Do not:
- omit any date
- add extra dates
- change the supplied date order
- create dates after the deadline
- combine two dates into one entry

If there is too much material for the available dates:
- prioritise prerequisites
- prioritise important course concepts
- use concise lessons
- identify what the learner should revisit later

If there are more dates than major topics:
- use extra dates for review
- use extra dates for practice
- use extra dates for weak-topic recovery
- use the final date for preparation and consolidation

Return JSON using this structure:

{{
  "course_title": "string",
  "course_summary": "string",
  "learner_goal": "string",
  "start_date": "{start_date.isoformat()}",
  "deadline": "{deadline.isoformat()}",
  "minutes_per_day": {study_minutes},
  "total_days": {total_days},
  "midpoint_day": {max(1, math.ceil(total_days / 2))},
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
      "study_date": "{start_date.isoformat()}",
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
  ]
}}

Rules:

1. Return exactly {total_days} roadmap entries.
2. Use the mandatory dates exactly as supplied.
3. Create exactly three quiz questions per date.
4. Every quiz question must have four options.
5. correct_answer must be an integer from 0 to 3.
6. Only Day 1 should have status "available".
7. All later days should have status "locked".
8. Base educational content on the supplied material.
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
            raw_response=(
                response.text or ""
            ),
            study_minutes=study_minutes,
            prompt=prompt,
            start_date=start_date,
            deadline=deadline,
        )

        if parsed_plan is not None:
            return parsed_plan

        print(
            "Gemma returned invalid "
            "roadmap JSON. Using "
            "placeholder roadmap."
        )

    except Exception as exc:
        print(
            "Gemma roadmap request "
            f"failed: {exc}"
        )

    return generate_placeholder_plan(
        prompt=prompt,
        start_date=start_date,
        deadline=deadline,
        study_minutes_per_day=(
            study_minutes
        ),
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
        chat = (
            GEMINI_CLIENT.chats.create(
                model=GEMINI_MODEL,
                config=(
                    types.GenerateContentConfig(
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
                ),
            )
        )

        first_response = (
            chat.send_message(
                message
            )
        )

        first_reply = (
            first_response.text or ""
        ).strip()

        follow_up_reply = ""

        if follow_up:
            second_response = (
                chat.send_message(
                    follow_up
                )
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

    except Exception as exc:
        print(
            "Gemma chat request "
            f"failed: {exc}"
        )

        return {
            "first_reply": (
                "Sorry, ZEN could not "
                "complete that chat request."
            ),
            "follow_up_reply": "",
        }


async def generate_level_with_gemma(
    day: int,
    study_date: str,
    title: str,
    topics: list[str],
    objectives: list[str],
    estimated_minutes: int,
) -> dict[str, Any]:
    """
    Generate one finishable learning level based strictly on
    the roadmap topics clicked by the learner.
    """

    if GEMINI_CLIENT is None:
        return generate_placeholder_level(
            day=day,
            study_date=study_date,
            title=title,
            topics=topics,
            objectives=objectives,
            estimated_minutes=estimated_minutes,
        )

    safe_minutes = max(
        10,
        min(estimated_minutes, 90),
    )

    system_instruction = """
You are ZEN, an adaptive study teacher.

The learner has clicked one level from a roadmap that was already
generated from their course material.

Create a focused micro-course that can be completed today.

You must teach only the supplied roadmap topics and objectives.
Do not replace them with unrelated subjects.
Do not create an entire semester course.
Do not mention that you are an AI.

Return valid JSON only.
Do not include markdown fences or text outside the JSON object.
"""

    prompt = f"""
ROADMAP LEVEL:
Day {day}

ASSIGNED DATE:
{study_date}

LEVEL TITLE:
{title}

MANDATORY TOPICS:
{json.dumps(topics, ensure_ascii=False)}

MANDATORY OBJECTIVES:
{json.dumps(objectives, ensure_ascii=False)}

AVAILABLE TIME:
{safe_minutes} minutes

Create a complete but concise one-day learning level.

The learner must be able to finish the explanation, activity and quiz
within {safe_minutes} minutes.

Return this exact JSON structure:

{{
  "day": {day},
  "study_date": "{study_date}",
  "title": "string",
  "estimated_minutes": {safe_minutes},
  "topics": ["string"],
  "welcome": "string",
  "sections": [
    {{
      "heading": "string",
      "explanation": "string",
      "key_points": [
        "string",
        "string"
      ],
      "example": "string"
    }}
  ],
  "practice_activity": {{
    "title": "string",
    "instructions": "string",
    "expected_minutes": 5
  }},
  "quick_recap": [
    "string",
    "string",
    "string"
  ],
  "quiz": [
    {{
      "id": "level-{day}-q-1",
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

Rules:

1. Use the supplied topics exactly as the subject of the lesson.
2. Create 2 to 4 short teaching sections.
3. Create exactly 3 multiple-choice quiz questions.
4. Every question must have exactly 4 options.
5. correct_answer must be an integer from 0 to 3.
6. The whole learning level must fit within {safe_minutes} minutes.
7. Use simple language and concrete examples.
8. The quiz must test the explanations actually taught.
"""

    try:
        response = GEMINI_CLIENT.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                temperature=0.25,
                response_mime_type="application/json",
                thinking_config=types.ThinkingConfig(
                    thinking_level="high"
                ),
            ),
        )

        cleaned = clean_json_response(
            response.text or ""
        )

        parsed = json.loads(cleaned)

        validated = validate_generated_level(
            parsed=parsed,
            day=day,
            study_date=study_date,
            title=title,
            topics=topics,
            estimated_minutes=safe_minutes,
        )

        if validated:
            return validated

    except Exception as exc:
        print(
            f"Gemma level generation failed: {exc}"
        )

    return generate_placeholder_level(
        day=day,
        study_date=study_date,
        title=title,
        topics=topics,
        objectives=objectives,
        estimated_minutes=safe_minutes,
    )


def validate_generated_level(
    parsed: Any,
    day: int,
    study_date: str,
    title: str,
    topics: list[str],
    estimated_minutes: int,
) -> dict[str, Any] | None:
    if not isinstance(parsed, dict):
        return None

    sections = parsed.get("sections", [])
    quiz = parsed.get("quiz", [])
    quick_recap = parsed.get("quick_recap", [])
    activity = parsed.get(
        "practice_activity",
        {},
    )

    if not isinstance(sections, list):
        return None

    if not isinstance(quiz, list):
        return None

    if not isinstance(quick_recap, list):
        quick_recap = []

    if not isinstance(activity, dict):
        activity = {}

    clean_sections = []

    for section in sections[:4]:
        if not isinstance(section, dict):
            continue

        key_points = section.get(
            "key_points",
            [],
        )

        if not isinstance(key_points, list):
            key_points = []

        clean_sections.append(
            {
                "heading": str(
                    section.get(
                        "heading",
                        "Key concept",
                    )
                ),
                "explanation": str(
                    section.get(
                        "explanation",
                        "",
                    )
                ),
                "key_points": [
                    str(point)
                    for point in key_points[:5]
                ],
                "example": str(
                    section.get(
                        "example",
                        "",
                    )
                ),
            }
        )

    clean_quiz = []

    for index, question in enumerate(
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

        correct_answer = safe_integer(
            question.get(
                "correct_answer",
                0,
            ),
            0,
        )

        correct_answer = max(
            0,
            min(correct_answer, 3),
        )

        clean_quiz.append(
            {
                "id": str(
                    question.get(
                        "id",
                        f"level-{day}-q-{index}",
                    )
                ),
                "topic": str(
                    question.get(
                        "topic",
                        topics[0]
                        if topics
                        else title,
                    )
                ),
                "question": str(
                    question.get(
                        "question",
                        "Which answer is correct?",
                    )
                ),
                "options": options,
                "correct_answer": correct_answer,
                "explanation": str(
                    question.get(
                        "explanation",
                        "",
                    )
                ),
            }
        )

    if not clean_sections or len(clean_quiz) != 3:
        return None

    return {
        "day": day,
        "study_date": study_date,
        "title": str(
            parsed.get(
                "title",
                title,
            )
        ),
        "estimated_minutes": estimated_minutes,
        "topics": topics,
        "welcome": str(
            parsed.get(
                "welcome",
                (
                    "This level is designed "
                    "to be completed today."
                ),
            )
        ),
        "sections": clean_sections,
        "practice_activity": {
            "title": str(
                activity.get(
                    "title",
                    "Quick practice",
                )
            ),
            "instructions": str(
                activity.get(
                    "instructions",
                    (
                        "Explain the main idea "
                        "in your own words."
                    ),
                )
            ),
            "expected_minutes": max(
                2,
                min(
                    safe_integer(
                        activity.get(
                            "expected_minutes",
                            5,
                        ),
                        5,
                    ),
                    15,
                ),
            ),
        },
        "quick_recap": [
            str(point)
            for point in quick_recap[:5]
        ],
        "quiz": clean_quiz,
    }


async def generate_quiz_feedback_with_gemma(
    lesson: dict[str, Any],
    score: int,
    results: list[dict[str, Any]],
    weak_topics: list[str],
) -> dict[str, Any]:
    if GEMINI_CLIENT is None:
        return {
            "headline": (
                "Level complete"
                if score >= 70
                else "A little review will help"
            ),
            "summary": (
                f"You scored {score}%. "
                "Review the explanations for any "
                "questions you missed."
            ),
            "next_step": (
                "Continue to the next level."
                if score >= 70
                else (
                    "Review your weakest topic "
                    "before moving on."
                )
            ),
        }

    prompt = f"""
You are ZEN, a supportive learning evaluator.

LESSON TITLE:
{lesson.get("title", "")}

LESSON TOPICS:
{json.dumps(lesson.get("topics", []), ensure_ascii=False)}

SCORE:
{score}%

QUESTION RESULTS:
{json.dumps(results, ensure_ascii=False)}

WEAK TOPICS:
{json.dumps(weak_topics, ensure_ascii=False)}

Give concise, encouraging feedback.

Return valid JSON only:

{{
  "headline": "string",
  "summary": "string",
  "strengths": ["string"],
  "weaknesses": ["string"],
  "next_step": "string"
}}
"""

    try:
        response = GEMINI_CLIENT.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.25,
                response_mime_type="application/json",
            ),
        )

        parsed = json.loads(
            clean_json_response(
                response.text or ""
            )
        )

        if isinstance(parsed, dict):
            return parsed

    except Exception as exc:
        print(
            f"Gemma feedback generation failed: {exc}"
        )

    return {
        "headline": "Level complete",
        "summary": f"You scored {score}%.",
        "strengths": [],
        "weaknesses": weak_topics,
        "next_step": (
            "Review weak topics, then continue."
        ),
    }


def generate_placeholder_level(
    day: int,
    study_date: str,
    title: str,
    topics: list[str],
    objectives: list[str],
    estimated_minutes: int,
) -> dict[str, Any]:
    primary_topic = (
        topics[0]
        if topics
        else title
    )

    return {
        "day": day,
        "study_date": study_date,
        "title": title,
        "estimated_minutes": estimated_minutes,
        "topics": topics,
        "welcome": (
            "This focused level can be "
            "completed in one sitting."
        ),
        "sections": [
            {
                "heading": (
                    f"Understanding {primary_topic}"
                ),
                "explanation": (
                    f"Begin by reviewing the main "
                    f"ideas behind {primary_topic}."
                ),
                "key_points": objectives[:3],
                "example": (
                    "Connect this concept to an "
                    "example from your uploaded notes."
                ),
            }
        ],
        "practice_activity": {
            "title": "Explain it simply",
            "instructions": (
                f"Explain {primary_topic} as though "
                "you were teaching it to a friend."
            ),
            "expected_minutes": 5,
        },
        "quick_recap": objectives[:3],
        "quiz": create_placeholder_quiz(
            day_number=day,
            topic=primary_topic,
            next_topic=(
                topics[1]
                if len(topics) > 1
                else primary_topic
            ),
        ),
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
                presentation = Presentation(
                    str(file_path)
                )

                text = (
                    extract_text_from_pptx(
                        presentation
                    )
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
) -> dict[str, Any]:
    topics = extract_placeholder_topics(
        raw_text
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
                    (
                        "Understand the main "
                        f"ideas behind {topic}."
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
                "quiz": (
                    create_placeholder_quiz(
                        day_number=index,
                        topic=topic,
                        next_topic=next_topic,
                    )
                ),
            }
        )

    source_label = (
        ", ".join(
            file_names[:2]
        )
        if file_names
        else "your provided material"
    )

    total_days = len(
        calendar_dates
    )

    return {
        "course_title": (
            topics[0].title()
            if topics
            else "Study Course"
        ),
        "course_summary": (
            f"ZEN created a "
            f"{total_days}-day dated "
            f"roadmap using "
            f"{source_label}."
        ),
        "learner_goal": (
            prompt.strip()
            or "Make steady study progress."
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
        "focus_topics": (
            topics[:8]
        ),
        "roadmap": roadmap,
    }


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
