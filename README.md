# ZEN: Your Adaptive Study Companion

> Beat procrastination. Start with one small study block.

ZEN is a web app for students who are short on time and long on stress. Upload your study materials, tell ZEN when your exam is and how much time you have each day, and it builds a realistic, day-by-day roadmap powered by **Gemma 4**. Every day opens into a short lesson with a quiz, and a built-in chat companion is there when you get stuck or need to reschedule.

The philosophy is simple: **progress over perfection**. ZEN always gives you one small, doable action to start with, rather than a wall of work.

---

## What it does

- **Turns your notes into a plan.** Upload lecture slides or notes and get a study roadmap that fits between today and your deadline.
- **Adapts to you.** The plan takes into account your study level, how you are feeling, and how you like to learn.
- **Teaches as well as schedules.** Each day opens into a Gemma-written lesson with sections, key points, a practice activity and a quiz.
- **Grades your quiz** and gives feedback so you know where to focus next.
- **Chats with you.** Ask ZEN a question about your material, say you only have 10 minutes, or ask to reschedule today's session.
- **Looks after your wellbeing.** A 2-minute breathing reset is one click away for when the pressure builds.
- **Keeps working without the API.** If Gemma is unavailable, ZEN falls back to a built-in planner so the app never dead-ends.

---

## User flow

1. **Land on ZEN.** A calm, friendly chat-style setup screen greets the student.
2. **Tell ZEN about your situation.**
   - What you are studying for (free-text prompt)
   - Upload study materials (`.pptx`, `.docx`, `.txt`)
   - Pick your exam deadline on the calendar
   - Set daily study time (10 to 180 minutes)
   - Choose your current level (Beginner, Intermediate, Advanced)
   - Say how you are feeling (Confident, Steady, Unsure, Anxious)
   - Choose how you like to learn (Quizzes, Flashcards, Notes)
3. **Generate the plan.** ZEN extracts the text from your files and sends it to Gemma 4 with your preferences.
4. **Follow your roadmap.** See your study window, a learning-style summary, and one card per day. Future days are locked so you stay focused on today.
5. **Open today's lesson.** Gemma writes a short lesson tailored to that day's topics and objectives, with a practice activity.
6. **Take the quiz.** Submit your answers and get instant grading and feedback.
7. **Get support along the way.** Chat with ZEN, start an emergency revision quiz, or take a breathing break.

---

## Tech stack

| Layer | Technology |
| --- | --- |
| **AI model** | Gemma 4 (`gemma-4-26b-a4b-it`) via the Google GenAI SDK (`google-genai`) |
| **Backend** | Python, FastAPI, Uvicorn |
| **Templating** | Jinja2 server-rendered pages |
| **Frontend** | HTML, CSS and vanilla JavaScript (no framework) |
| **File parsing** | `python-pptx` for PowerPoint, `python-docx` for Word, plain text for `.txt` |
| **Config** | `python-dotenv` for API keys |
| **Testing** | Python `unittest` |

---

## Project structure

```
gdg_hackathon/
├── app.py                  # FastAPI app: routes, file parsing, Gemma calls, fallback planner
├── templates/
│   ├── index.html          # Setup screen (upload, deadline, preferences)
│   ├── plan.html           # Roadmap, lessons, quiz, chat and emergency quiz
│   └── breathing.html      # 2-minute breathing reset
├── static/
│   ├── app.js              # Form handling and chat behaviour
│   ├── styles.css          # Styling (soft blue palette)
│   └── zen_logo.png
├── study_material/         # Sample slides for demoing
├── tests/                  # Unit tests
└── requirements.txt
```

### Main endpoints

| Method | Route | Purpose |
| --- | --- | --- |
| `GET` | `/` | Setup screen |
| `POST` | `/plan` | Build and display the study roadmap |
| `POST` | `/api/plan` | Generate a plan as JSON |
| `POST` | `/api/lesson` | Generate a lesson for a given day |
| `POST` | `/api/grade` | Grade a quiz and return feedback |
| `POST` | `/api/chat` | Chat with ZEN about your material |
| `GET` | `/breathing-exercise` | Breathing reset page |
| `GET` | `/health` | Health check, including whether Gemma is configured |

---

## Getting started

### Prerequisites

- Python 3.10 or newer
- A Gemma / Gemini API key from [Google AI Studio](https://aistudio.google.com/)

### Run locally

1. Install the dependencies:

   ```bash
   pip install -r requirements.txt
   ```

2. Create a `.env` file in the project root:

   ```
   GEMMA_API_KEY=your_api_key_here
   ```

   `GEMINI_API_KEY` is also accepted.

3. Start the app:

   ```bash
   uvicorn app:app --reload
   ```

4. Open <http://127.0.0.1:8000/>.

### Run the tests

```bash
python -m unittest discover tests
```

---

## Try the demo

1. Open the app.
2. Upload one of the PowerPoint files from `study_material/`.
3. Set a deadline a few days away and 45 minutes of study time per day.
4. Press **Generate plan**.
5. Open today's lesson, take the quiz, then ask ZEN a question in the chat.

---

## Current limitations

- PDF upload is not supported yet; use `.pptx`, `.docx` or `.txt`.
- There are no user accounts or saved history, so the latest plan lives in memory only.
- This is a hackathon prototype, not a production study platform.

## Built for

GDG Hackathon.
