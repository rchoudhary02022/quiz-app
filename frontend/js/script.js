const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];

// When FastAPI serves this page, keep API calls same-origin. Live Server uses the local API host.
const API_BASE = window.location.port === "8000" ? window.location.origin : "http://127.0.0.1:8000";
let sourceMode = "topic";
let difficulty = "Medium";
let selectedFile = null;
let activeQuiz = null;
let currentQuestion = 0;
let maxUploadMb = 10;

function escapeHTML(value) {
  return String(value).replace(/[&<>"']/g, (char) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  })[char]);
}

function setMessage(text, isError = false) {
  const message = $("#formMessage");
  message.textContent = text;
  message.style.color = isError ? "#ff9d86" : "#d8ff66";
}

function getSettings() {
  return {
    question_count: Number($("#questionCount").value),
    difficulty,
    language: $("#language").value,
    question_type: $("#questionType").value
  };
}

$$('.source-tab').forEach((tab) => {
  tab.addEventListener('click', () => {
    $$('.source-tab').forEach((item) => item.classList.remove('active'));
    tab.classList.add('active');
    sourceMode = tab.dataset.mode;
    $('#topicPane').classList.toggle('hidden', sourceMode !== 'topic');
    $('#filePane').classList.toggle('hidden', sourceMode !== 'file');
    setMessage('');
  });
});

$('#topicInput').addEventListener('input', (event) => {
  $('#charCount').textContent = `${event.target.value.length} / 500`;
});

$$('.difficulty button').forEach((button) => {
  button.addEventListener('click', () => {
    $$('.difficulty button').forEach((item) => item.classList.remove('selected'));
    button.classList.add('selected');
    difficulty = button.dataset.level;
  });
});

$('#fileInput').addEventListener('change', (event) => {
  const file = event.target.files[0];
  if (!file) return;
  const extension = file.name.slice(file.name.lastIndexOf('.')).toLowerCase();
  if (!['.pdf', '.docx', '.txt'].includes(extension)) {
    setMessage('Choose a PDF, DOCX or TXT file. Legacy .doc files are not supported.', true);
    event.target.value = '';
    selectedFile = null;
    return;
  }
  if (file.size > maxUploadMb * 1024 * 1024) {
    setMessage(`File is larger than ${maxUploadMb} MB. Please choose a smaller file.`, true);
    event.target.value = '';
    selectedFile = null;
    return;
  }
  selectedFile = file;
  $('#fileName').textContent = `✓ ${file.name}`;
  setMessage('');
});

const dropzone = $('#dropzone');
['dragenter', 'dragover'].forEach((name) => dropzone.addEventListener(name, (event) => {
  event.preventDefault();
  dropzone.style.borderColor = 'var(--lime)';
}));
['dragleave', 'drop'].forEach((name) => dropzone.addEventListener(name, (event) => {
  event.preventDefault();
  dropzone.style.borderColor = '';
}));
dropzone.addEventListener('drop', (event) => {
  const file = event.dataTransfer.files[0];
  if (!file) return;
  const transfer = new DataTransfer();
  transfer.items.add(file);
  $('#fileInput').files = transfer.files;
  $('#fileInput').dispatchEvent(new Event('change'));
});

async function readApiError(response) {
  let detail = `Request failed (${response.status})`;
  try {
    const data = await response.json();
    if (typeof data.detail === 'string') detail = data.detail;
    else if (Array.isArray(data.detail)) detail = data.detail.map((item) => item.msg).join(', ');
  } catch (_) { /* Keep the HTTP status fallback. */ }
  return detail;
}

async function generateQuiz() {
  const topic = $('#topicInput').value.trim();
  const button = $('#generateBtn');
  const buttonLabel = button.querySelector('span');
  const settings = getSettings();

  if (sourceMode === 'topic' && topic.length < 3) {
    setMessage('Enter a topic with at least 3 characters.', true);
    $('#topicInput').focus();
    return;
  }
  if (sourceMode === 'file' && !selectedFile) {
    setMessage('Choose your notes file before generating the quiz.', true);
    return;
  }

  button.disabled = true;
  buttonLabel.textContent = 'GENERATING…';
  setMessage('Connecting to Quizora AI. This can take a few seconds.');

  try {
    let response;
    if (sourceMode === 'topic') {
      response = await fetch(`${API_BASE}/api/quizzes/generate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ topic, ...settings })
      });
    } else {
      const form = new FormData();
      form.append('file', selectedFile);
      form.append('question_count', String(settings.question_count));
      form.append('difficulty', settings.difficulty);
      form.append('language', settings.language);
      form.append('question_type', settings.question_type);
      response = await fetch(`${API_BASE}/api/quizzes/generate-from-file`, {
        method: 'POST',
        body: form
      });
    }

    if (!response.ok) throw new Error(await readApiError(response));
    activeQuiz = await response.json();
    renderQuiz(activeQuiz);
    setMessage('Quiz generated successfully. Your session is ready.');
    $('#quizWorkspace').scrollIntoView({ behavior: 'smooth', block: 'start' });
  } catch (error) {
    const message = error instanceof TypeError
      ? 'Cannot reach the backend. Start FastAPI at http://127.0.0.1:8000 and try again.'
      : error.message;
    setMessage(message, true);
  } finally {
    button.disabled = false;
    buttonLabel.textContent = 'Generate my quiz';
  }
}

function renderQuiz(quiz) {
  const workspace = $('#quizWorkspace');
  workspace.innerHTML = `
    <div class="quiz-workspace-head">
      <div><div class="eyebrow">YOUR GENERATED SESSION</div><h2>${escapeHTML(quiz.title)}</h2>
      <p>${quiz.question_count} QUESTIONS <i>·</i> ${escapeHTML(quiz.difficulty).toUpperCase()} <i>·</i> ${escapeHTML(quiz.language).toUpperCase()}</p></div>
      <span class="quiz-id">ID / ${escapeHTML(quiz.quiz_id.slice(0, 8).toUpperCase())}</span>
    </div>
    <div class="quiz-progress"><span id="quizProgressBar"></span></div>
    <div class="question-navigation" id="questionNavigation" aria-label="Question navigation"></div>
    <form id="quizForm"><div class="quiz-question-list" id="quizQuestionView"></div>
      <div class="quiz-submit-row"><span id="answeredCount">0 / ${quiz.questions.length} ANSWERED</span><div class="question-controls"><button type="button" class="question-control" id="previousQuestion">← PREVIOUS</button><button type="button" class="question-control" id="nextQuestion">NEXT →</button><button type="submit" class="quiz-submit">SUBMIT QUIZ <b>↗</b></button></div></div>
    </form>
    <div id="quizResult" class="quiz-result hidden"></div>`;

  workspace.classList.remove('hidden');
  activeQuiz.answers = {};
  currentQuestion = 0;
  drawCurrentQuestion();
  $('#previousQuestion').addEventListener('click', () => { currentQuestion--; drawCurrentQuestion(); });
  $('#nextQuestion').addEventListener('click', () => { currentQuestion++; drawCurrentQuestion(); });
  $('#questionNavigation').addEventListener('click', (event) => {
    const button = event.target.closest('[data-index]');
    if (!button) return;
    currentQuestion = Number(button.dataset.index);
    drawCurrentQuestion();
  });
  $('#quizForm').addEventListener('change', (event) => {
    const choice = event.target.closest('input[name="quizAnswer"]');
    if (!choice) return;
    activeQuiz.answers[activeQuiz.questions[currentQuestion].id] = Number(choice.value);
    drawCurrentQuestion();
  });
  $('#quizForm').addEventListener('submit', submitQuiz);
}

function drawCurrentQuestion() {
  const quiz = activeQuiz;
  if (!quiz) return;
  const question = quiz.questions[currentQuestion];
  const selected = quiz.answers[question.id];
  $('#quizQuestionView').innerHTML = `<article class="quiz-question"><div class="quiz-question-meta"><span>QUESTION ${String(currentQuestion + 1).padStart(2, '0')}</span><span>${currentQuestion + 1} / ${quiz.questions.length}</span></div><h3>${escapeHTML(question.question)}</h3><div class="quiz-options">${question.options.map((option, index) => `<label class="quiz-option"><input type="radio" name="quizAnswer" value="${index}" ${selected === index ? 'checked' : ''}><span class="option-letter">${String.fromCharCode(65 + index)}</span><span>${escapeHTML(option)}</span></label>`).join('')}</div></article>`;
  $('#questionNavigation').innerHTML = quiz.questions.map((item, index) => `<button type="button" class="question-dot ${index === currentQuestion ? 'current' : ''} ${quiz.answers[item.id] !== undefined ? 'answered' : ''}" data-index="${index}" aria-label="Question ${index + 1}">${String(index + 1).padStart(2, '0')}</button>`).join('');
  const answered = Object.keys(quiz.answers).length;
  $('#answeredCount').textContent = `${answered} / ${quiz.questions.length} ANSWERED`;
  $('#quizProgressBar').style.width = `${((currentQuestion + 1) / quiz.questions.length) * 100}%`;
  $('#previousQuestion').disabled = currentQuestion === 0;
  $('#nextQuestion').classList.toggle('hidden', currentQuestion === quiz.questions.length - 1);
}

async function submitQuiz(event) {
  event.preventDefault();
  if (!activeQuiz) return;
  if (Object.keys(activeQuiz.answers).length !== activeQuiz.questions.length) {
    const unansweredIndex = activeQuiz.questions.findIndex((question) => activeQuiz.answers[question.id] === undefined);
    currentQuestion = unansweredIndex;
    drawCurrentQuestion();
    $('#answeredCount').textContent = `ANSWER QUESTION ${unansweredIndex + 1} BEFORE SUBMITTING`;
    return;
  }

  const button = $('#quizForm .quiz-submit');
  button.disabled = true;
  button.querySelector('b').textContent = '…';
  const answers = activeQuiz.questions.map((question) => ({ question_id: question.id, selected_index: activeQuiz.answers[question.id] }));

  try {
    const response = await fetch(`${API_BASE}/api/quizzes/${activeQuiz.quiz_id}/submit`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ answers })
    });
    if (!response.ok) throw new Error(await readApiError(response));
    renderResult(await response.json());
    loadHistory();
  } catch (error) {
    $('#quizResult').classList.remove('hidden');
    $('#quizResult').innerHTML = `<p class="quiz-error">${escapeHTML(error.message)}</p>`;
  } finally {
    button.disabled = false;
    button.querySelector('b').textContent = '↗';
  }
}

function renderResult(result) {
  const resultBox = $('#quizResult');
  const reviewHTML = result.reviews.map((review, index) => `
    <article class="review-item ${review.is_correct ? 'is-correct' : 'is-wrong'}">
      <div class="review-heading"><span>Q${String(index + 1).padStart(2, '0')}</span><b>${review.is_correct ? 'CORRECT' : 'REVIEW THIS'}</b></div>
      <h4>${escapeHTML(review.question)}</h4>
      <p class="review-answer">Correct answer: <strong>${escapeHTML(review.options[review.correct_index])}</strong></p>
      <p class="review-explanation">${escapeHTML(review.explanation)}</p>
    </article>`).join('');
  resultBox.innerHTML = `
    <div class="result-summary"><div class="result-score"><strong>${result.percentage}%</strong><span>${result.score} / ${result.total} CORRECT</span></div>
    <div><div class="eyebrow">SESSION COMPLETE</div><h3>${escapeHTML(result.feedback)}</h3><p>Review the explanations below to strengthen your understanding.</p></div></div>
    <div class="review-list">${reviewHTML}</div>
    <button class="quiz-retry" id="quizRetry">CREATE ANOTHER QUIZ ↗</button>`;
  resultBox.classList.remove('hidden');
  $('#quizForm').classList.add('quiz-completed');
  $('#quizRetry').addEventListener('click', () => {
    $('#quizWorkspace').classList.add('hidden');
    $('#quizWorkspace').innerHTML = '';
    activeQuiz = null;
    $('#create').scrollIntoView({ behavior: 'smooth' });
  });
}

async function loadHistory() {
  const message = $('#historyMessage');
  const list = $('#historyList');
  if (!message || !list) return;
  message.textContent = 'Loading recent quizzes…';
  try {
    const response = await fetch(`${API_BASE}/api/quizzes/history/list`);
    if (!response.ok) throw new Error(await readApiError(response));
    const items = await response.json();
    message.textContent = items.length ? '' : 'No quizzes yet. Generate your first quiz to see it here.';
    list.innerHTML = items.map((item) => `<article class="history-item"><div><span class="eyebrow">${escapeHTML(item.source_type).toUpperCase()} · ${escapeHTML(item.difficulty).toUpperCase()}</span><h3>${escapeHTML(item.title)}</h3><p>${item.question_count} QUESTIONS · ${new Date(item.created_at).toLocaleString()} · ${item.attempts} ATTEMPTS</p></div><div class="history-score">${item.best_score === null ? 'NOT ATTEMPTED' : `${item.best_score}% BEST`}<button type="button" data-quiz-id="${escapeHTML(item.quiz_id)}">RETAKE ↗</button></div></article>`).join('');
  } catch (error) {
    message.textContent = `Quiz history is unavailable: ${error.message}`;
  }
}

async function loadApiConfiguration() {
  try {
    const response = await fetch(`${API_BASE}/api/health`);
    if (!response.ok) return;
    const config = await response.json();
    maxUploadMb = Number(config.max_upload_mb) || 10;
    const uploadHint = $('#dropzone em');
    if (uploadHint) uploadHint.textContent = `PDF, DOCX or TXT · Max ${maxUploadMb} MB`;
  } catch (_) { /* The generation and history actions show their own connection errors. */ }
}

$('#historyList').addEventListener('click', async (event) => {
  const button = event.target.closest('[data-quiz-id]');
  if (!button) return;
  try {
    const response = await fetch(`${API_BASE}/api/quizzes/${encodeURIComponent(button.dataset.quizId)}`);
    if (!response.ok) throw new Error(await readApiError(response));
    activeQuiz = await response.json();
    renderQuiz(activeQuiz);
    $('#quizWorkspace').scrollIntoView({ behavior: 'smooth', block: 'start' });
  } catch (error) { $('#historyMessage').textContent = `Could not open this quiz: ${error.message}`; }
});
$('#historyRefresh').addEventListener('click', loadHistory);

$('#generateBtn').addEventListener('click', generateQuiz);
loadHistory();
loadApiConfiguration();

$('#menuToggle').addEventListener('click', () => $('.nav-links').classList.toggle('open'));
$$('.nav-links a').forEach((link) => link.addEventListener('click', () => $('.nav-links').classList.remove('open')));

document.addEventListener('mousemove', (event) => {
  const glow = $('#cursorGlow');
  if (glow && window.innerWidth > 700) {
    glow.style.left = `${event.clientX}px`;
    glow.style.top = `${event.clientY}px`;
  }
});

// Interactive particle silhouette in the hero visual.
(() => {
  const canvas = document.getElementById('particleCanvas');
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  let width = 0, height = 0, particles = [];
  const pointer = { x: -1000, y: -1000, active: false };
  const dpr = Math.min(window.devicePixelRatio || 1, 2);

  function insidePortrait(x, y) {
    const head = (((x - .56) / .19) ** 2 + ((y - .30) / .25) ** 2) < 1;
    const neck = x > .49 && x < .65 && y > .48 && y < .68;
    const shoulders = (((x - .57) / .39) ** 2 + ((y - .91) / .35) ** 2) < 1 && y > .62;
    return (head || neck || shoulders) && !(x < .27 && y > .73) && y < 1.08;
  }
  function resize() {
    const rect = canvas.getBoundingClientRect();
    width = rect.width; height = rect.height;
    canvas.width = Math.floor(width * dpr); canvas.height = Math.floor(height * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    particles = [];
    const step = width < 600 ? 7 : 5.2;
    for (let y = 0; y < height; y += step) for (let x = 0; x < width; x += step) {
      if (insidePortrait(x / width, y / height) && Math.random() > .13) {
        const jitter = (Math.random() - .5) * 3;
        particles.push({ x: x + jitter, y: y + jitter, ox: x + jitter, oy: y + jitter, r: Math.random() * 1.15 + .35, a: Math.random() * .52 + .34, phase: Math.random() * Math.PI * 2 });
      }
    }
  }
  function draw(time) {
    ctx.clearRect(0, 0, width, height);
    const t = time * .00035;
    for (const p of particles) {
      let x = p.ox + Math.sin(t + p.phase) * .9;
      let y = p.oy + Math.cos(t * .8 + p.phase) * .8;
      if (pointer.active) {
        const dx = x - pointer.x, dy = y - pointer.y, distance = Math.hypot(dx, dy);
        if (distance < 105 && distance > .1) {
          const force = (1 - distance / 105) * 18;
          x += dx / distance * force; y += dy / distance * force;
        }
      }
      ctx.beginPath(); ctx.fillStyle = `rgba(239,236,229,${p.a})`;
      ctx.arc(x, y, p.r, 0, Math.PI * 2); ctx.fill();
    }
    requestAnimationFrame(draw);
  }
  canvas.addEventListener('pointermove', (event) => {
    const rect = canvas.getBoundingClientRect();
    pointer.x = event.clientX - rect.left; pointer.y = event.clientY - rect.top; pointer.active = true;
  });
  canvas.addEventListener('pointerleave', () => { pointer.active = false; });
  window.addEventListener('resize', resize);
  resize(); requestAnimationFrame(draw);
})();
