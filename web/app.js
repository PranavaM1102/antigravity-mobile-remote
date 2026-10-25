let activeConversationId = "";
let lastStepIndex = 0;
let isPolling = false;
let autoScroll = true;
let isRecording = false;
let speechRecognizer = null;
let authToken = localStorage.getItem("antigravity_token") || "";
let currentPin = "";
let pendingMessages = [];
let currentSteps = [];
let renderedStepMap = new Map();

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
const pinOverlay = document.getElementById("pinOverlay");
const pinDots = document.getElementById("pinDots");
const pinError = document.getElementById("pinError");
const lockBtn = document.getElementById("lockBtn");

// Initialize Marked parser settings if available
if (typeof marked !== "undefined") {
  marked.setOptions({
    breaks: true,
    gfm: true
  });
}

// Authenticated Fetch Wrapper
async function authFetch(url, options = {}) {
  options.headers = options.headers || {};
  if (authToken) {
    options.headers["X-Auth-Token"] = authToken;
  }
  const res = await fetch(url, options);
  if (res.status === 401) {
    showPinOverlay();
    throw new Error("Authentication required");
  }
  return res;
}

// PIN Handling
function showPinOverlay() {
  currentPin = "";
  updatePinDots();
  pinError.textContent = "";
  pinOverlay.classList.remove("hidden");
}

function hidePinOverlay() {
  pinOverlay.classList.add("hidden");
  currentPin = "";
}

function updatePinDots() {
  const dots = pinDots.querySelectorAll(".pin-dot");
  dots.forEach((dot, idx) => {
    if (idx < currentPin.length) {
      dot.classList.add("filled");
    } else {
      dot.classList.remove("filled");
    }
  });
}

function pressPin(digit) {
  if (currentPin.length < 6) {
    currentPin += digit;
    updatePinDots();
    if (navigator.vibrate) navigator.vibrate(15);
    if (currentPin.length === 4) {
      submitPin();
    }
  }
}

function backspacePin() {
  if (currentPin.length > 0) {
    currentPin = currentPin.slice(0, -1);
    updatePinDots();
    if (navigator.vibrate) navigator.vibrate(10);
  }
}

function clearPin() {
  currentPin = "";
  updatePinDots();
  pinError.textContent = "";
}

async function submitPin() {
  try {
    const res = await fetch("/api/auth", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ pin: currentPin })
    });
    const data = await res.json();
    if (res.ok && data.token) {
      authToken = data.token;
      localStorage.setItem("antigravity_token", authToken);
      hidePinOverlay();
      init();
    } else {
      pinError.textContent = data.error || "Incorrect PIN";
      if (navigator.vibrate) navigator.vibrate([40, 40, 40]);
      setTimeout(clearPin, 600);
    }
  } catch (err) {
    pinError.textContent = "Connection error";
  }
}

// Lock button
lockBtn.addEventListener("click", () => {
  authToken = "";
  localStorage.removeItem("antigravity_token");
  showPinOverlay();
});

// Setup Tabs
tabBtns.forEach(btn => {
  btn.addEventListener("click", () => {
    tabBtns.forEach(b => b.classList.remove("active"));
    tabPanes.forEach(p => p.classList.remove("active"));
    btn.classList.add("active");
    const target = btn.getAttribute("data-tab");
    document.getElementById(target + "Pane").classList.add("active");
    if (target === "chat") scrollToBottom();
    if (target === "info") fetchLimits();
  });
});

// Auto-expand textarea on typing & Enter
promptInput.addEventListener("input", function() {
  this.style.height = "auto";
  this.style.height = Math.min(this.scrollHeight, 120) + "px";
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
    const res = await authFetch("/api/status");
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
      const bestIp = data.ips[0].url;
      const qrImg = document.getElementById("qrImage");
      if (qrImg) {
        qrImg.src = `/api/qr?url=${encodeURIComponent(bestIp)}`;
      }
    }

    await loadConversations();
    await fetchTranscript(true);
    fetchLimits();
    startPolling();
  } catch (err) {
    if (err.message !== "Authentication required") {
      updateStatus("Offline", "offline");
    }
  }
}

async function fetchLimits() {
  const container = document.getElementById("limitsContainer");
  if (!container) return;
  try {
    const res = await authFetch("/api/limits");
    if (!res.ok) return;
    const data = await res.json();
    
    let disksHtml = (data.disks || []).map(d => `
      <div style="display:flex; justify-content:space-between; margin-top:2px;">
        <span style="color:var(--text-muted);">${d.drive} Drive:</span>
        <span style="font-family:var(--font-mono); color:${d.used_pct > 95 ? 'var(--accent-red)' : 'var(--accent-blue)'};">${d.free_gb}GB free of ${d.total_gb}GB (${d.used_pct}%)</span>
      </div>
    `).join("");

    container.innerHTML = `
      <div style="background:var(--bg-tertiary); padding:10px; border-radius:8px; border:1px solid var(--border-color);">
        <div style="display:flex; justify-content:space-between; font-weight:600; margin-bottom:4px;">
          <span>🧠 Model Context Window:</span>
          <span style="color:var(--accent-green);">${data.context_used_pct} used</span>
        </div>
        <div style="background:#0d1117; height:6px; border-radius:3px; overflow:hidden; margin:4px 0 6px 0;">
          <div style="width:${data.context_used_pct}; background:var(--accent-green); height:100%;"></div>
        </div>
        <div style="display:flex; justify-content:space-between; font-size:11px; color:var(--text-muted); font-family:var(--font-mono);">
          <span>Turn Input: ${Number(data.context_tokens).toLocaleString()} tokens</span>
          <span>Max Limit: ${Number(data.context_limit).toLocaleString()} tokens</span>
        </div>
      </div>

      <div style="background:var(--bg-tertiary); padding:10px; border-radius:8px; border:1px solid var(--border-color);">
        <div style="font-weight:600; margin-bottom:6px; color:var(--accent-blue);">⚡ Session Token Consumption:</div>
        <div style="display:flex; justify-content:space-between; margin-bottom:3px;">
          <span style="color:var(--text-muted);">Total Consumed:</span>
          <span style="font-family:var(--font-mono); font-weight:600; color:#fff;">${Number(data.session_total_tokens).toLocaleString()} tokens</span>
        </div>
        <div style="display:flex; justify-content:space-between; margin-bottom:3px;">
          <span style="color:var(--text-muted);">Prompt Input:</span>
          <span style="font-family:var(--font-mono);">${Number(data.session_input_tokens).toLocaleString()}</span>
        </div>
        <div style="display:flex; justify-content:space-between; margin-bottom:3px;">
          <span style="color:var(--text-muted);">Model Output:</span>
          <span style="font-family:var(--font-mono);">${Number(data.session_output_tokens).toLocaleString()}</span>
        </div>
        <div style="display:flex; justify-content:space-between;">
          <span style="color:var(--text-muted);">Cache Read:</span>
          <span style="font-family:var(--font-mono); color:var(--accent-purple);">${Number(data.session_cache_read_tokens).toLocaleString()}</span>
        </div>
      </div>

      <div style="background:var(--bg-tertiary); padding:10px; border-radius:8px; border:1px solid var(--border-color);">
        <div style="font-weight:600; margin-bottom:6px; color:var(--accent-orange);">🖥️ Workstation Hardware Limits:</div>
        <div style="display:flex; justify-content:space-between; margin-bottom:3px;">
          <span style="color:var(--text-muted);">RAM Usage:</span>
          <span style="font-family:var(--font-mono);">${data.ram?.used_gb}GB / ${data.ram?.total_gb}GB (${data.ram?.pct})</span>
        </div>
        ${disksHtml}
      </div>
    `;
  } catch(e) {}
}

// Load Conversations Dropdown
async function loadConversations() {
  try {
    const res = await authFetch("/api/conversations");
    const data = await res.json();
    if (data.conversations) {
      sessionSelect.innerHTML = data.conversations.map(c => `
        <option value="${c.id}" ${c.id === activeConversationId ? "selected" : ""}>
          ${c.is_current ? "⭐ " : ""}${escapeHtml(c.title || c.id.substring(0, 8))}
        </option>
      `).join("");
    }
  } catch (err) {}
}

sessionSelect.addEventListener("change", (e) => {
  activeConversationId = e.target.value;
  chatContainer.innerHTML = "";
  renderedStepMap.clear();
  lastStepIndex = 0;
  fetchTranscript(true);
});

// Fetch and Render Transcript
async function fetchTranscript(forceScroll = false) {
  if (!activeConversationId) return;
  try {
    const res = await authFetch(`/api/transcript?id=${activeConversationId}&since=0`);
    const data = await res.json();
    updateStatus("Connected", "online");

    if (data.steps) {
      renderMessages(data.steps, forceScroll);
    }
  } catch (err) {
    if (err.message !== "Authentication required") {
      updateStatus("Connecting...", "offline");
    }
  }
}

function isUserSelecting() {
  const sel = window.getSelection();
  return sel && sel.toString().trim().length > 0;
}

function getStepHash(step) {
  const toolHash = (step.tool_calls || []).map(t => `${t.name}:${t.status}:${t.result ? t.result.length : 0}`).join('|');
  return `${step.sender}:${step.status}:${step.text || ''}:${toolHash}`;
}

function copyTextToClipboard(text, btn) {
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(text).then(() => {
      showCopiedFeedback(btn);
    }).catch(() => fallbackCopy(text, btn));
  } else {
    fallbackCopy(text, btn);
  }
}

function fallbackCopy(text, btn) {
  const ta = document.createElement("textarea");
  ta.value = text;
  ta.style.position = "fixed";
  ta.style.opacity = "0";
  document.body.appendChild(ta);
  ta.focus();
  ta.select();
  try {
    document.execCommand("copy");
    showCopiedFeedback(btn);
  } catch(e) {
    console.error("Copy failed", e);
  }
  document.body.removeChild(ta);
}

function showCopiedFeedback(btn) {
  if (navigator.vibrate) navigator.vibrate(20);
  const orig = btn.innerHTML;
  btn.innerHTML = "✅ Copied!";
  btn.classList.add("copied");
  setTimeout(() => {
    btn.innerHTML = orig;
    btn.classList.remove("copied");
  }, 1800);
}

function addCopyButtonsToBubble(bubble, rawText) {
  if (rawText && rawText.trim()) {
    const copyMsgBtn = document.createElement("button");
    copyMsgBtn.className = "copy-msg-btn";
    copyMsgBtn.innerHTML = "📋 Copy Response";
    copyMsgBtn.onclick = (e) => {
      e.stopPropagation();
      copyTextToClipboard(rawText, copyMsgBtn);
    };
    bubble.appendChild(copyMsgBtn);
  }

  const preElements = bubble.querySelectorAll("pre:not(.tool-body)");
  preElements.forEach(pre => {
    if (pre.querySelector(".copy-code-btn")) return;
    const btn = document.createElement("button");
    btn.className = "copy-code-btn";
    btn.innerHTML = "📋 Copy Code";
    btn.onclick = (e) => {
      e.stopPropagation();
      const codeEl = pre.querySelector("code");
      const textToCopy = codeEl ? codeEl.innerText : pre.innerText;
      copyTextToClipboard(textToCopy, btn);
    };
    pre.appendChild(btn);
  });
}

function buildMessageElement(step) {
  const wrapper = document.createElement("div");
  wrapper.className = `message-wrapper ${step.sender}`;
  wrapper.setAttribute("data-step-index", step.index);

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
    addCopyButtonsToBubble(bubble, step.text);
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

  return wrapper;
}

function renderMessages(steps, forceScroll = false) {
  if (steps) currentSteps = steps;

  // If user is currently dragging/selecting text, PAUSE updating so selection is not collapsed!
  if (isUserSelecting() && !forceScroll) {
    return;
  }

  // Clear matched pending messages
  if (steps && steps.length > 0) {
    const userStepTexts = steps.filter(s => s.sender === "user").map(s => s.text.trim());
    pendingMessages = pendingMessages.filter(p => !userStepTexts.includes(p.text.trim()) && (Date.now() - p.timestamp < 45000));
  }

  let hasRunningTools = false;
  let hasNewOrChangedNode = false;

  // Remove existing pending elements before reconciling
  const existingPendingEls = chatContainer.querySelectorAll(".message-wrapper.pending");
  existingPendingEls.forEach(el => el.remove());

  currentSteps.forEach(step => {
    if (step.tool_calls && step.tool_calls.some(tc => tc.status === "running")) {
      hasRunningTools = true;
    }

    const newHash = getStepHash(step);
    const existing = renderedStepMap.get(step.index);

    if (existing) {
      if (existing.hash !== newHash) {
        // Content changed (e.g. tool execution finished or stream update)
        const updatedEl = buildMessageElement(step);
        chatContainer.replaceChild(updatedEl, existing.element);
        renderedStepMap.set(step.index, { hash: newHash, element: updatedEl });
        hasNewOrChangedNode = true;
      }
      // If hash matches, DO NOTHING! Element remains untouched in DOM.
    } else {
      // Net new message
      const newEl = buildMessageElement(step);
      chatContainer.appendChild(newEl);
      renderedStepMap.set(step.index, { hash: newHash, element: newEl });
      hasNewOrChangedNode = true;
    }
  });

  // Render pending messages at bottom
  pendingMessages.forEach(p => {
    const wrapper = document.createElement("div");
    wrapper.className = "message-wrapper user pending";
    wrapper.innerHTML = `
      <div class="message-bubble" style="opacity: 0.85;">${escapeHtml(p.text)}</div>
      <div class="message-meta">Sending...</div>
    `;
    chatContainer.appendChild(wrapper);
  });

  if (hasRunningTools) {
    updateStatus("Working", "working");
  }

  // Only scroll if there's genuinely new content and user was already at bottom or forceScroll is true
  if (forceScroll || (hasNewOrChangedNode && autoScroll && !isUserSelecting())) {
    scrollToBottom();
  }
}

// Send Message to Agent
async function sendMessage(textToSend) {
  const content = textToSend || promptInput.value.trim();
  if (!content) return;

  if (navigator.vibrate) navigator.vibrate(25);

  promptInput.value = "";
  promptInput.style.height = "auto";

  // Track in pending messages
  pendingMessages.push({ text: content, timestamp: Date.now() });
  renderMessages(currentSteps, true);
  scrollToBottom();

  updateStatus("Thinking", "working");

  try {
    const res = await authFetch("/api/send", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        conversation_id: activeConversationId,
        content: content
      })
    });
    if (!res.ok) throw new Error("Failed to send");

    burstPoll(8, 1200);
  } catch (err) {
    if (err.message !== "Authentication required") {
      alert("Error sending message: " + err.message);
      updateStatus("Connected", "online");
    }
  }
}

sendBtn.addEventListener("click", () => sendMessage());

function sendQuickPrompt(prompt) {
  sendMessage(prompt);
}

function burstPoll(count, interval) {
  let left = count;
  const timer = setInterval(async () => {
    await fetchTranscript();
    left--;
    if (left <= 0) clearInterval(timer);
  }, interval);
}

function startPolling() {
  if (isPolling) return;
  isPolling = true;
  setInterval(async () => {
    if (authToken && pinOverlay.classList.contains("hidden")) {
      await fetchTranscript();
    }
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

  speechRecognizer.onerror = () => stopVoice();
  speechRecognizer.onend = () => stopVoice();

  voiceBtn.addEventListener("click", () => {
    if (isRecording) {
      speechRecognizer.stop();
    } else {
      speechRecognizer.start();
    }
  });
} else {
  voiceBtn.style.opacity = "0.5";
  voiceBtn.title = "Voice recognition not supported";
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
    const res = await authFetch("/api/exec_terminal", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ command: cmd })
    });
    const data = await res.json();
    if (data.stdout) terminalOutput.textContent += data.stdout;
    if (data.stderr) terminalOutput.textContent += "ERROR: " + data.stderr;
    if (data.error) terminalOutput.textContent += "FAIL: " + data.error + "\n";
  } catch (err) {
    if (err.message !== "Authentication required") {
      terminalOutput.textContent += `Request failed: ${err.message}\n`;
    }
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
  if (e.key === "Enter") runTermCommand(termInput.value.trim());
});

// Start New Conversation
async function startNewConversation() {
  const prompt = document.getElementById("newConvPrompt").value.trim();
  if (!prompt) return;
  try {
    await authFetch("/api/new_conversation", {
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
    if (e.message !== "Authentication required") {
      alert("Failed to start: " + e.message);
    }
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

// Initial check
if (!authToken) {
  showPinOverlay();
} else {
  init();
}
