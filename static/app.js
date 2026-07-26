const chatForm = document.getElementById("chat-form");
const chatInput = document.getElementById("chat-input");
const chatMessages = document.getElementById("chat-messages");
const typingIndicator = document.getElementById("typing-indicator");
const clearChatButton = document.getElementById("clear-chat");

const attachmentButton = document.getElementById("attachment-button");
const fileInput = document.getElementById("chat-file-input");
const attachmentPreview = document.getElementById("attachment-preview");

let attachedFiles = [];

function scrollChatToBottom() {
  chatMessages.scrollTop = chatMessages.scrollHeight;
}

function escapeHtml(value) {
  const element = document.createElement("div");
  element.textContent = String(value ?? "");
  return element.innerHTML;
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
  typingIndicator.hidden = false;
  scrollChatToBottom();
}

function hideTypingIndicator() {
  typingIndicator.hidden = true;
}

function getDemoReply(message) {
  const normalisedMessage = message.toLowerCase();

  if (
    normalisedMessage.includes("10 minutes") ||
    normalisedMessage.includes("quick")
  ) {
    return "Perfect. We’ll keep this small: one concept, one example, and a quick check at the end.";
  }

  if (
    normalisedMessage.includes("full") ||
    normalisedMessage.includes("planned session")
  ) {
    return "Nice commitment. I’ll guide you through the full lesson, then we’ll finish with a short quiz.";
  }

  if (normalisedMessage.includes("reschedule")) {
    return "That’s okay. Choose a realistic time rather than abandoning the plan completely.";
  }

  if (
    normalisedMessage.includes("confused") ||
    normalisedMessage.includes("understand")
  ) {
    return "Tell me which part feels unclear. I’ll explain it using a simpler example from your material.";
  }

  return "I’ve noted that. Once the Gemma endpoint is connected, this message will be answered using your uploaded course material and current roadmap.";
}

function sendMessage(message) {
  const trimmedMessage = message.trim();

  if (!trimmedMessage) return;

  chatMessages.appendChild(createUserMessage(trimmedMessage));

  chatInput.value = "";
  resizeTextarea();
  scrollChatToBottom();
  showTypingIndicator();

  window.setTimeout(() => {
    hideTypingIndicator();

    const reply = getDemoReply(trimmedMessage);
    chatMessages.appendChild(createAssistantMessage(reply));

    scrollChatToBottom();
  }, 850);
}

function resizeTextarea() {
  chatInput.style.height = "auto";
  chatInput.style.height = `${Math.min(chatInput.scrollHeight, 130)}px`;
}

function renderAttachmentPreview() {
  attachmentPreview.innerHTML = "";

  attachedFiles.forEach((file) => {
    const chip = document.createElement("span");
    chip.className = "file-chip";
    chip.title = file.name;
    chip.textContent = file.name;

    attachmentPreview.appendChild(chip);
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

  attachedFiles = [];
  fileInput.value = "";
  renderAttachmentPreview();
  scrollChatToBottom();
});

resizeTextarea();
scrollChatToBottom();
