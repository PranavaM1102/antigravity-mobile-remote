let activeConversationId = "";
let lastStepIndex = 0;
let isPolling = false;
let autoScroll = true;
let isRecording = false;
let speechRecognizer = null;

// DOM Elements
const sessionSelect = document.getElementById("sessionSelect");
const chatContainer = document.getElementById("chatContainer");
const promptInput = document.getElementById("promptInput");
const sendBtn = document.getElementById("sendBtn");
const voiceBtn = document.getElementById("voiceBtn");
const statusDot = document.getElementById("statusDot");
const statusText = document.getElementById("statusText");
const terminalOutput = document.getElementById("terminalOutput");
const termInput = document.getElementById("termInput");
const termRunBtn = document.getElementById("termRunBtn");
const ipList = document.getElementById("ipList");
const tabBtns = document.querySelectorAll(".tab-btn");
const tabPanes = document.querySelectorAll(".tab-pane");

// Initialize Marked parser settings if available
if (typeof marked !== "undefined") {
  marked.setOptions({
    breaks: true,
    gfm: true
  });
}

// Setup Tabs
tabBtns.forEach(btn => {
  btn.addEventListener("click", () => {
    tabBtns.forEach(b => b.classList.remove("active"));
    tabPanes.forEach(p => p.classList.remove("active"));
    btn.classList.add("active");
    const target = btn.getAttribute("data-tab");
    document.getElementById(target + "Pane").classList.add("active");
    if (target === "chat") scrollToBottom();
  });
});

// Auto-expand textarea
promptInput.addEventListener("input", function() {
  this.style.height = "auto";
  this.style.height = Math.min(this.scrollHeight, 100) + "px";
});

// Handle enter key in chat
promptInput.addEventListener("keydown", function(e) {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    sendMessage();
  }
});

// Detect scroll to toggle autoScroll
chatContainer.addEventListener("scroll", () => {
  const threshold = 60;
  const isNearBottom = chatContainer.scrollHeight - chatContainer.scrollTop - chatContainer.clientHeight < threshold;
  autoScroll = isNearBottom;
});

function scrollToBottom() {
  chatContainer.scrollTop = chatContainer.scrollHeight;
}

// Fetch Status & Initialize
async function init() {
  try {
    const res = await fetch("/api/status");
    const data = await res.json();
    activeConversationId = data.active_conversation_id;
    updateStatus("Connected", "online");

    // Populate IPs
    if (data.ips && data.ips.length > 0) {
      ipList.innerHTML = data.ips.map(item => `
        <div class="ip-item">
          <span class="ip-label">${item.type}</span>
          <span class="ip-val">${item.url}</span>
        </div>
      `).join("");
      // Update QR code with the best LAN IP
      const bestIp = data.ips[0].url;
      const qrImg = document.getElementById("qrImage");
      if (qrImg) {
        qrImg.src = `/api/qr?url=${encodeURIComponent(bestIp)}`;
      }
    }

    await loadConversations();
    await fetchTranscript(true);
    startPolling();
  } catch (err) {
    console.error("Init error:", err);
    updateStatus("Offline", "offline");
  }
}

// Load Conversations Dropdown
async function loadConversations() {
  try {
    const res = await fetch("/api/conversations");
    const data = await res.json();
    if (data.conversations) {
      sessionSelect.innerHTML = data.conversations.map(c => `
        <option value="${c.id}" ${c.id === activeConversationId ? "selected" : ""}>
          ${c.is_current ? "⭐ " : ""}${escapeHtml(c.title || c.id.substring(0, 8))}
        </option>
      `).join("");
    }
  } catch (err) {
    console.error("Error loading conversations:", err);
  }
}

sessionSelect.addEventListener("change", (e) => {
  activeConversationId = e.target.value;
  chatContainer.innerHTML = "";
  lastStepIndex = 0;
  fetchTranscript(true);
});

// Fetch and Render Transcript
async function fetchTranscript(forceScroll = false) {
  if (!activeConversationId) return;
  try {
    const res = await fetch(`/api/transcript?id=${activeConversationId}&since=0`);
    if (!res.ok) throw new Error("Network error");
    const data = await res.json();
    updateStatus("Connected", "online");

    if (data.steps) {
      renderMessages(data.steps, forceScroll);
    }
  } catch (err) {
    updateStatus("Connecting...", "offline");
  }
}

function renderMessages(steps, forceScroll = false) {
  chatContainer.innerHTML = "";
  let hasRunningTools = false;

  steps.forEach(step => {
    const wrapper = document.createElement("div");
    wrapper.className = `message-wrapper ${step.sender}`;

    const bubble = document.createElement("div");
    bubble.className = "message-bubble";

    if (step.sender === "user") {
      bubble.textContent = step.text;
    } else if (step.sender === "agent") {
      let html = "";
      if (step.text) {
        html += typeof marked !== "undefined" ? marked.parse(step.text) : escapeHtml(step.text);
      }
      if (step.tool_calls && step.tool_calls.length > 0) {
        step.tool_calls.forEach(tc => {
          if (tc.status === "running") hasRunningTools = true;
          let argSummary = "";
          try {
            if (tc.args) {
              argSummary = tc.args.toolSummary || tc.args.CommandLine || tc.args.Path || JSON.stringify(tc.args).substring(0, 40);
            }
          } catch(e) {}

          const resultText = tc.result || "Executing command...";
          html += `
            <div class="tool-pill" onclick="this.classList.toggle('expanded')">
              <div class="tool-header">
                <div class="tool-name">⚡ ${escapeHtml(tc.name)} <span style="color:var(--text-muted); font-size:10px;">${escapeHtml(argSummary)}</span></div>
                <span class="tool-badge ${tc.status}">${tc.status}</span>
              </div>
              <pre class="tool-body">${escapeHtml(resultText)}</pre>
            </div>
          `;
        });
      }
      bubble.innerHTML = html || "<span style='color:var(--text-muted);'>Processing...</span>";
    } else {
      bubble.textContent = step.text;
    }

    wrapper.appendChild(bubble);

    if (step.time) {
      const meta = document.createElement("div");
      meta.className = "message-meta";
      const dt = new Date(step.time);
      meta.textContent = dt.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
      wrapper.appendChild(meta);
    }

    chatContainer.appendChild(wrapper);
  });

  if (hasRunningTools) {
    updateStatus("Working", "working");
  }

  if (forceScroll || autoScroll) {
    scrollToBottom();
  }
}

// Send Message to Agent
async function sendMessage(textToSend) {
  const content = textToSend || promptInput.value.trim();
  if (!content) return;

  // Haptic feedback
  if (navigator.vibrate) navigator.vibrate(25);

  promptInput.value = "";
  promptInput.style.height = "auto";

  // Optimistic UI update
  const wrapper = document.createElement("div");
  wrapper.className = "message-wrapper user";
  wrapper.innerHTML = `<div class="message-bubble">${escapeHtml(content)}</div>`;
  chatContainer.appendChild(wrapper);
  scrollToBottom();

  updateStatus("Thinking", "working");

  try {
    const res = await fetch("/api/send", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        conversation_id: activeConversationId,
        content: content
      })
    });
    if (!res.ok) throw new Error("Failed to send");

    // Rapid polling burst for 12 seconds
    burstPoll(8, 1500);
  } catch (err) {
    alert("Error sending message: " + err.message);
    updateStatus("Connected", "online");
  }
}

sendBtn.addEventListener("click", () => sendMessage());

function sendQuickPrompt(prompt) {
  sendMessage(prompt);
}

// Burst polling after action
function burstPoll(count, interval) {
  let left = count;
  const timer = setInterval(async () => {
    await fetchTranscript();
    left--;
    if (left <= 0) clearInterval(timer);
  }, interval);
}

// Background polling loop
function startPolling() {
  setInterval(async () => {
    await fetchTranscript();
  }, 2500);
}

function updateStatus(text, dotClass) {
  statusText.textContent = text;
  statusDot.className = "status-dot " + dotClass;
}

// Speech to text (Voice Input)
const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
if (SpeechRecognition) {
  speechRecognizer = new SpeechRecognition();
  speechRecognizer.continuous = false;
  speechRecognizer.interimResults = true;
  speechRecognizer.lang = "en-US";

  speechRecognizer.onstart = () => {
    isRecording = true;
    voiceBtn.classList.add("recording");
    promptInput.placeholder = "Listening...";
  };

  speechRecognizer.onresult = (event) => {
    let transcript = "";
    for (let i = 0; i < event.results.length; i++) {
      transcript += event.results[i][0].transcript;
    }
    promptInput.value = transcript;
    promptInput.style.height = promptInput.scrollHeight + "px";
  };

  speechRecognizer.onerror = (e) => {
    console.error("Speech error:", e);
    stopVoice();
  };

  speechRecognizer.onend = () => {
    stopVoice();
  };

  voiceBtn.addEventListener("click", () => {
    if (isRecording) {
      speechRecognizer.stop();
    } else {
      speechRecognizer.start();
    }
  });
} else {
  voiceBtn.style.opacity = "0.5";
  voiceBtn.title = "Voice recognition not supported in this browser";
}

function stopVoice() {
  isRecording = false;
  voiceBtn.classList.remove("recording");
  promptInput.placeholder = "Command Antigravity...";
}

// Terminal execution
async function runTermCommand(cmd) {
  if (!cmd) return;
  terminalOutput.textContent += `\nPS > ${cmd}\n`;
  terminalOutput.scrollTop = terminalOutput.scrollHeight;
  termInput.value = "";

  try {
    const res = await fetch("/api/exec_terminal", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ command: cmd })
    });
    const data = await res.json();
    if (data.stdout) terminalOutput.textContent += data.stdout;
    if (data.stderr) terminalOutput.textContent += "ERROR: " + data.stderr;
    if (data.error) terminalOutput.textContent += "FAIL: " + data.error + "\n";
  } catch (err) {
    terminalOutput.textContent += `Request failed: ${err.message}\n`;
  }
  terminalOutput.scrollTop = terminalOutput.scrollHeight;
}

function runTermQuick(cmd) {
  runTermCommand(cmd);
}

function clearTerminal() {
  terminalOutput.textContent = "PowerShell Terminal Ready.\n";
}

termRunBtn.addEventListener("click", () => runTermCommand(termInput.value.trim()));
termInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter") {
    runTermCommand(termInput.value.trim());
  }
});

// Start New Conversation
async function startNewConversation() {
  const prompt = document.getElementById("newConvPrompt").value.trim();
  if (!prompt) return;
  try {
    const res = await fetch("/api/new_conversation", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ prompt: prompt, model: "flash" })
    });
    alert("New conversation started! Loading conversations in 3 seconds...");
    setTimeout(async () => {
      await loadConversations();
      tabBtns[0].click();
    }, 3000);
  } catch (e) {
    alert("Failed to start: " + e.message);
  }
}

function escapeHtml(str) {
  if (!str) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

// Start application
init();
