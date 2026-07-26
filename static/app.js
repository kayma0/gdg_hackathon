const chatForm = document.getElementById("chat-form");
const chatInput = document.getElementById("chat-input");
const chatMessages = document.getElementById("chat-messages");
const typingIndicator = document.getElementById("typing-indicator");
const clearChatButton = document.getElementById("clear-chat");

const attachmentButton = document.getElementById("attachment-button");
const fileInput = document.getElementById("chat-file-input");
const attachmentPreview = document.getElementById("attachment-preview");

const lessonOverlay = document.getElementById("lesson-overlay");
const lessonCloseButton = document.getElementById("lesson-close-button");
const lessonTitle = document.getElementById("lesson-title");
const lessonLoading = document.getElementById("lesson-loading");
const lessonContent = document.getElementById("lesson-content");
const lessonError = document.getElementById("lesson-error");
const materialContextInput = document.getElementById("chat-material-context");

let attachedFiles = [];
let activeLesson = null;

function escapeHtml(value) {
  const element = document.createElement("div");
  element.textContent = String(value ?? "");
  return element.innerHTML;
}

function scrollChatToBottom() {
  if (!chatMessages) return;
  chatMessages.scrollTop = chatMessages.scrollHeight;
}

function createUserMessage(message) {
  const row = document.createElement("article");
  row.className = "message-row user-message";

  row.innerHTML = `
    <div class="message-content">
      <div class="message-bubble">
        <p>${escapeHtml(message)}</p>
      </div>
    </div>
  `;

  return row;
}

function createAssistantMessage(message) {
  const row = document.createElement("article");
  row.className = "message-row assistant-message";

  row.innerHTML = `
    <div class="message-avatar">Z</div>

    <div class="message-content">
      <div class="message-meta">
        <strong>ZEN</strong>
        <span>Study companion</span>
      </div>

      <div class="message-bubble">
        <p>${escapeHtml(message)}</p>
      </div>
    </div>
  `;

  return row;
}

function showTypingIndicator() {
  if (!typingIndicator) return;
  typingIndicator.hidden = false;
  scrollChatToBottom();
}

function hideTypingIndicator() {
  if (!typingIndicator) return;
  typingIndicator.hidden = true;
}

async function sendMessage(message) {
  const trimmedMessage = message.trim();

  if (!trimmedMessage || !chatMessages) return;

  chatMessages.appendChild(createUserMessage(trimmedMessage));

  chatInput.value = "";
  resizeTextarea();
  scrollChatToBottom();
  showTypingIndicator();

  const formData = new FormData();
  formData.append("message", trimmedMessage);

  const materialContext = materialContextInput?.value || "";
  if (materialContext) {
    formData.append("context", materialContext);
  }

  attachedFiles.forEach((file) => {
    formData.append("uploaded_files", file);
  });

  try {
    const response = await fetch("/api/chat", {
      method: "POST",
      body: formData,
    });

    const payload = await response.json();
    const reply = payload.reply || "I’m here. Ask me about the material and I’ll explain it in a simple way.";

    if (!response.ok) {
      throw new Error(payload.detail || "ZEN could not reply.");
    }

    hideTypingIndicator();

    chatMessages.appendChild(createAssistantMessage(reply));
    scrollChatToBottom();
  } catch (error) {
    hideTypingIndicator();
    chatMessages.appendChild(
      createAssistantMessage(
        "ZEN couldn’t reach the Gemini service right now. Please try again in a moment.",
      ),
    );
    scrollChatToBottom();
  }
}

function resizeTextarea() {
  if (!chatInput) return;

  chatInput.style.height = "auto";
  chatInput.style.height = `${Math.min(chatInput.scrollHeight, 130)}px`;
}

function renderAttachmentPreview() {
  if (!attachmentPreview) return;

  attachmentPreview.innerHTML = "";

  attachedFiles.forEach((file) => {
    const chip = document.createElement("span");
    chip.className = "file-chip";
    chip.title = file.name;
    chip.textContent = file.name;

    attachmentPreview.appendChild(chip);
  });
}

function openLessonPanel() {
  lessonOverlay.hidden = false;
  document.body.classList.add("lesson-open");
}

function closeLessonPanel() {
  lessonOverlay.hidden = true;
  document.body.classList.remove("lesson-open");
}

function showLessonLoading(title) {
  lessonTitle.textContent = title;
  lessonLoading.hidden = false;
  lessonContent.hidden = true;
  lessonError.hidden = true;
  lessonError.textContent = "";
}

function showLessonError(message) {
  lessonLoading.hidden = true;
  lessonContent.hidden = true;
  lessonError.hidden = false;

  lessonError.innerHTML = `
    <h3>ZEN could not prepare this level</h3>
    <p>${escapeHtml(message)}</p>
  `;
}

function renderLesson(lesson) {
  activeLesson = lesson;

  lessonTitle.textContent = lesson.title;
  lessonLoading.hidden = true;
  lessonError.hidden = true;
  lessonContent.hidden = false;

  const topicTags = lesson.topics
    .map((topic) => `<span>${escapeHtml(topic)}</span>`)
    .join("");

  const sections = lesson.sections
    .map(
      (section, index) => `
        <section class="course-section">
          <div class="course-section-number">
            ${index + 1}
          </div>

          <div>
            <h3>${escapeHtml(section.heading)}</h3>

            <p>${escapeHtml(section.explanation)}</p>

            ${
              section.key_points.length
                ? `
                  <ul>
                    ${section.key_points
                      .map((point) => `<li>${escapeHtml(point)}</li>`)
                      .join("")}
                  </ul>
                `
                : ""
            }

            ${
              section.example
                ? `
                  <div class="ink-example">
                    <strong>Example</strong>
                    <p>${escapeHtml(section.example)}</p>
                  </div>
                `
                : ""
            }
          </div>
        </section>
      `,
    )
    .join("");

  const recap = lesson.quick_recap
    .map((point) => `<li>${escapeHtml(point)}</li>`)
    .join("");

  const quiz = lesson.quiz
    .map(
      (question, questionIndex) => `
        <fieldset
          class="lesson-quiz-question"
          data-question-index="${questionIndex}"
        >
          <legend>
            ${questionIndex + 1}.
            ${escapeHtml(question.question)}
          </legend>

          <p class="quiz-topic">
            Topic: ${escapeHtml(question.topic)}
          </p>

          <div class="lesson-options">
            ${question.options
              .map(
                (option, optionIndex) => `
                  <label class="lesson-option">
                    <input
                      type="radio"
                      name="lesson-question-${questionIndex}"
                      value="${optionIndex}"
                    />

                    <span>
                      ${escapeHtml(option)}
                    </span>
                  </label>
                `,
              )
              .join("")}
          </div>
        </fieldset>
      `,
    )
    .join("");

  lessonContent.innerHTML = `
    <div class="lesson-cover">
      <div>
        <p class="handwritten-label">
          Day ${lesson.day} ·
          ${escapeHtml(lesson.study_date)}
        </p>

        <h2>${escapeHtml(lesson.title)}</h2>

        <p>${escapeHtml(lesson.welcome)}</p>
      </div>

      <div class="lesson-time-note">
        <strong>${lesson.estimated_minutes}</strong>
        <span>minutes</span>
      </div>
    </div>

    <div class="lesson-topic-tags">
      ${topicTags}
    </div>

    <div class="course-sections">
      ${sections}
    </div>

    <section class="practice-paper">
      <p class="section-label">
        Practice
      </p>

      <h3>
        ${escapeHtml(lesson.practice_activity.title)}
      </h3>

      <p>
        ${escapeHtml(lesson.practice_activity.instructions)}
      </p>

      <span>
        About
        ${lesson.practice_activity.expected_minutes}
        minutes
      </span>
    </section>

    ${
      recap
        ? `
          <section class="recap-paper">
            <p class="section-label">
              Quick recap
            </p>

            <ul>${recap}</ul>
          </section>
        `
        : ""
    }

    <form
      class="lesson-quiz-form"
      id="lesson-quiz-form"
    >
      <div class="quiz-heading">
        <p class="section-label">
          Knowledge check
        </p>

        <h2>Finish the level quiz</h2>

        <p>
          Answer all three questions to complete
          this learning level.
        </p>
      </div>

      ${quiz}

      <button
        class="submit-button lesson-submit-button"
        type="submit"
      >
        Submit quiz
      </button>
    </form>

    <div
      class="lesson-results"
      id="lesson-results"
      hidden
    ></div>
  `;

  const quizForm = document.getElementById("lesson-quiz-form");

  quizForm.addEventListener("submit", submitLessonQuiz);
}

async function generateLesson(button) {
  let topics;
  let objectives;

  try {
    topics = JSON.parse(button.dataset.topics);
    objectives = JSON.parse(button.dataset.objectives);
  } catch {
    topics = [];
    objectives = [];
  }

  const level = {
    day: Number(button.dataset.day),
    study_date: button.dataset.studyDate,
    title: button.dataset.title,
    topics,
    objectives,
    estimated_minutes: Number(button.dataset.minutes),
  };

  openLessonPanel();
  showLessonLoading(`Writing Day ${level.day}…`);

  try {
    const response = await fetch("/api/lesson", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(level),
    });

    const data = await response.json();

    if (!response.ok) {
      throw new Error(data.detail || "Lesson generation failed.");
    }

    renderLesson(data);
  } catch (error) {
    showLessonError(error.message || "Gemma could not generate this lesson.");
  }
}

async function submitLessonQuiz(event) {
  event.preventDefault();

  const form = event.currentTarget;

  const selectedAnswers = activeLesson.quiz.map((_, questionIndex) => {
    const selected = form.querySelector(
      `input[name="lesson-question-${questionIndex}"]:checked`,
    );

    return selected ? Number(selected.value) : -1;
  });

  if (selectedAnswers.some((answer) => answer === -1)) {
    window.alert("Please answer all three questions.");
    return;
  }

  const submitButton = form.querySelector('button[type="submit"]');

  submitButton.disabled = true;
  submitButton.textContent = "ZEN is checking your answers…";

  try {
    const response = await fetch("/api/grade", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        lesson: activeLesson,
        selected_answers: selectedAnswers,
      }),
    });

    const data = await response.json();

    if (!response.ok) {
      throw new Error(data.detail || "Grading failed.");
    }

    renderQuizResults(data);

    form.querySelectorAll("input").forEach((input) => {
      input.disabled = true;
    });

    submitButton.hidden = true;
  } catch (error) {
    window.alert(error.message || "ZEN could not grade the quiz.");

    submitButton.disabled = false;
    submitButton.textContent = "Submit quiz";
  }
}

function renderQuizResults(data) {
  const resultsBox = document.getElementById("lesson-results");

  const resultItems = data.results
    .map(
      (result, index) => `
        <div class="graded-answer ${
          result.is_correct ? "answer-correct" : "answer-incorrect"
        }">
          <strong>
            Question ${index + 1}:
            ${result.is_correct ? "Correct" : "Review this"}
          </strong>

          ${
            !result.is_correct
              ? `
                <p>
                  Correct answer:
                  ${escapeHtml(result.correct_answer)}
                </p>
              `
              : ""
          }

          <p>
            ${escapeHtml(result.explanation)}
          </p>
        </div>
      `,
    )
    .join("");

  const feedback = data.feedback || {};

  resultsBox.hidden = false;

  resultsBox.innerHTML = `
    <section class="score-paper">
      <div class="score-circle">
        <strong>${data.score}%</strong>
        <span>score</span>
      </div>

      <div>
        <p class="section-label">
          Gemma feedback
        </p>

        <h2>
          ${escapeHtml(feedback.headline || "Level complete")}
        </h2>

        <p>
          ${escapeHtml(
            feedback.summary ||
              `You answered ${data.correct_count} of ${data.total_questions} correctly.`,
          )}
        </p>
      </div>
    </section>

    <div class="graded-answer-list">
      ${resultItems}
    </div>

    <section class="next-step-note">
      <strong>Next step</strong>

      <p>
        ${escapeHtml(
          feedback.next_step || "Continue to the next roadmap level.",
        )}
      </p>
    </section>

    <button
      type="button"
      class="submit-button finish-level-button"
      id="finish-level-button"
    >
      Finish this level
    </button>
  `;

  document
    .getElementById("finish-level-button")
    .addEventListener("click", () => {
      closeLessonPanel();
    });

  resultsBox.scrollIntoView({
    behavior: "smooth",
    block: "start",
  });
}

chatForm?.addEventListener("submit", (event) => {
  event.preventDefault();
  sendMessage(chatInput.value);
});

chatInput?.addEventListener("input", resizeTextarea);

chatInput?.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    sendMessage(chatInput.value);
  }
});

document.querySelectorAll(".quick-action").forEach((button) => {
  button.addEventListener("click", () => {
    sendMessage(button.dataset.message || button.textContent);
  });
});

document.querySelectorAll(".demo-prompt-chip").forEach((button) => {
  button.addEventListener("click", () => {
    const demoPrompts = document.getElementById("demo-prompts");
    if (demoPrompts) demoPrompts.hidden = true;
    sendMessage(button.dataset.message || button.textContent.trim());
  });
});

document.querySelectorAll(".level-button").forEach((button) => {
  button.addEventListener("click", () => {
    generateLesson(button);
  });
});

attachmentButton?.addEventListener("click", () => {
  fileInput.click();
});

fileInput?.addEventListener("change", () => {
  attachedFiles = Array.from(fileInput.files || []);

  renderAttachmentPreview();
});

clearChatButton?.addEventListener("click", () => {
  const confirmed = window.confirm("Clear the current chat?");

  if (!confirmed) return;

  chatMessages.innerHTML = "";

  chatMessages.appendChild(
    createAssistantMessage(
      "Chat cleared. Tell me what you want to work on next.",
    ),
  );
});

lessonCloseButton?.addEventListener("click", closeLessonPanel);

lessonOverlay?.addEventListener("click", (event) => {
  if (event.target === lessonOverlay) {
    closeLessonPanel();
  }
});

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && lessonOverlay && !lessonOverlay.hidden) {
    closeLessonPanel();
  }
});

resizeTextarea();
scrollChatToBottom();
