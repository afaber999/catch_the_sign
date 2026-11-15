"use strict";

const $ = (id) => document.getElementById(id);
const state = {
  voices: [], levels: [], defaultVoice: "", rounds: 20, round: 0, completed: 0, firstTry: 0,
  current: null, attempts: 0, revealed: false, phase: "ready",
  roundRequest: 0, audioRequest: 0, audio: null, audioUrl: null, controller: null,
};

function showError(message) {
  $("error").textContent = message;
  $("error").hidden = !message;
}

function showScreen(name) {
  for (const screen of ["ready", "exercise", "success", "complete"]) {
    $(`${screen}-screen`).hidden = screen !== name;
  }
}

function updateProgress() {
  $("completed").textContent = state.completed;
  $("total").textContent = state.rounds;
  $("first-try").textContent = state.firstTry;
  $("progress-fill").style.width = `${100 * state.completed / state.rounds}%`;
  $("progress-track").setAttribute("aria-valuemax", state.rounds);
  $("progress-track").setAttribute("aria-valuenow", state.completed);
}

function selectedVoices() {
  if (!$("random-mode").checked) return $("voice-select").value ? [$("voice-select").value] : [];
  return [...document.querySelectorAll("#voice-list input:checked:not(:disabled)")].map((input) => input.value);
}

function voiceSelectionError() {
  const level = state.levels.find((item) => item.level === Number($("level-select").value));
  if (level && level.native_only && !state.voices.some((voice) => voice.native_english)) {
    return "No native English voices are available. Add one or choose level 4 or 5.";
  }
  return "Select at least one voice in Your setup.";
}

function updateLevel(initial = false) {
  const level = state.levels.find((item) => item.level === Number($("level-select").value));
  if (!level) return;
  $("level-description").textContent = level.description;
  const compatible = state.voices.filter((voice) => !level.native_only || voice.native_english);
  const select = $("voice-select");
  const previous = select.value;
  select.replaceChildren();
  const placeholder = document.createElement("option");
  placeholder.value = "";
  placeholder.textContent = compatible.length ? "Choose a voice" : "No native English voices available";
  select.append(placeholder);
  for (const voice of compatible) {
    const option = document.createElement("option");
    option.value = voice.name;
    option.textContent = voiceLabel(voice);
    select.append(option);
  }
  if (compatible.some((voice) => voice.name === previous)) {
    select.value = previous;
  } else if (compatible.some((voice) => voice.name === state.defaultVoice)) {
    select.value = state.defaultVoice;
  } else if (!initial && compatible.length) {
    select.value = compatible[0].name;
  } else {
    select.value = "";
  }
  select.disabled = !compatible.length;
  for (const label of $("voice-list").children) {
    const input = label.querySelector("input");
    const allowed = compatible.some((voice) => voice.name === input.value);
    label.hidden = !allowed;
    input.disabled = !allowed;
  }
  if (!compatible.length) {
    showError("No native English voices are available. Add one or choose level 4 or 5.");
  } else if (!select.value && !$("random-mode").checked) {
    showError("The default voice is unavailable. Choose a voice to begin.");
  } else {
    showError("");
  }
}

function voiceLabel(voice) {
  if (voice.display_name !== voice.name) {
    return voice.accent ? `${voice.display_name} · ${voice.accent}` : voice.display_name;
  }
  const match = voice.name.match(/^([a-z]{2,3})_([A-Z]{2})-([^-]+)-(?:x_low|low|medium|high)(?:-speaker-\d+)?$/);
  if (!match) return voice.display_name;
  try {
    const language = new Intl.DisplayNames(["en"], { type: "language" }).of(`${match[1]}-${match[2]}`);
    const speaker = match[3][0].toUpperCase() + match[3].slice(1);
    return `${language} · ${speaker}`;
  } catch (_) {
    return voice.display_name;
  }
}

async function postJson(path, data, signal) {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
    signal,
  });
  if (!response.ok) {
    let message = "Something went wrong. Please try again.";
    try { message = (await response.json()).error || message; } catch (_) { /* no JSON error body */ }
    throw new Error(message);
  }
  return response;
}

function stopAudio() {
  state.audioRequest++;
  if (state.controller) state.controller.abort();
  state.controller = null;
  if (state.audio) {
    state.audio.pause();
    state.audio.removeAttribute("src");
    state.audio.load();
    state.audio = null;
  }
  if (state.audioUrl) URL.revokeObjectURL(state.audioUrl);
  state.audioUrl = null;
  $("signal").classList.remove("playing");
}

async function playCurrent() {
  if (!state.current || state.phase !== "exercise") return;
  showError("");
  stopAudio();
  const request = state.audioRequest;
  const controller = new AbortController();
  state.controller = controller;
  $("play").disabled = true;
  $("signal-status").textContent = "PREPARING AUDIO";
  $("play-hint").textContent = "Preparing your signal...";
  try {
    const response = await postJson("/api/audio", state.current, controller.signal);
    const blob = await response.blob();
    if (request !== state.audioRequest) return;
    state.audioUrl = URL.createObjectURL(blob);
    const audio = new Audio(state.audioUrl);
    state.audio = audio;
    audio.addEventListener("ended", () => {
      if (request !== state.audioRequest) return;
      $("signal").classList.remove("playing");
      $("signal-status").textContent = "READY TO COPY";
      $("play-hint").textContent = "Tap play to listen again.";
    });
    audio.addEventListener("error", () => {
      if (request !== state.audioRequest) return;
      $("signal").classList.remove("playing");
      $("signal-status").textContent = "AUDIO ERROR";
      $("play-hint").textContent = "Tap play to try again.";
      showError("The browser could not play this recording.");
    });
    await audio.play();
    if (request !== state.audioRequest) return;
    $("signal").classList.add("playing");
    $("signal-status").textContent = "PLAYING";
    $("play-hint").textContent = "Listen closely.";
  } catch (error) {
    if (request !== state.audioRequest || error.name === "AbortError") return;
    $("signal-status").textContent = "READY TO PLAY";
    $("play-hint").textContent = "Tap play to hear the call sign.";
    if (error.name !== "NotAllowedError") showError(error.message);
  } finally {
    if (request === state.audioRequest) {
      state.controller = null;
      $("play").disabled = false;
    }
  }
}

async function nextRound() {
  const voices = selectedVoices();
  if (!voices.length) {
    showError(voiceSelectionError());
    return;
  }
  stopAudio();
  showError("");
  const request = ++state.roundRequest;
  for (const id of ["start", "next", "again"]) $(id).disabled = true;
  $("play").disabled = true;
  $("signal-status").textContent = "FINDING A SIGNAL";
  $("play-hint").textContent = "Getting the next round ready...";
  try {
    const response = await postJson("/api/round", { voices, level: Number($("level-select").value) });
    const round = await response.json();
    if (request !== state.roundRequest) return;
    state.round++;
    state.current = round;
    state.attempts = 0;
    state.revealed = false;
    state.phase = "exercise";
    $("noise-status").textContent = round.noise ? "NOISE ON" : "NO ADDED NOISE";
    $("round-badge").textContent = `ROUND ${String(state.round).padStart(2, "0")} / ${state.rounds}`;
    const voice = state.voices.find((item) => item.name === round.voice);
    $("current-voice").textContent = (voice ? voiceLabel(voice) : round.voice).toUpperCase();
    $("restart").hidden = false;
    $("answer").value = "";
    $("feedback").textContent = "Listen, then enter what you heard.";
    $("feedback").className = "";
    showScreen("exercise");
    $("answer").focus();
    playCurrent();
  } catch (error) {
    if (request !== state.roundRequest) return;
    $("signal-status").textContent = "STANDBY";
    $("noise-status").textContent = "NO ADDED NOISE";
    $("play-hint").textContent = "Try starting the round again.";
    showError(error.message);
  } finally {
    if (request === state.roundRequest) {
      for (const id of ["start", "next", "again"]) $(id).disabled = false;
    }
  }
}

function beginSession() {
  if (!selectedVoices().length) {
    showError(voiceSelectionError());
    return;
  }
  state.roundRequest++;
  stopAudio();
  state.round = 0;
  state.completed = 0;
  state.firstTry = 0;
  state.current = null;
  state.phase = "ready";
  $("round-badge").textContent = "READY WHEN YOU ARE";
  $("current-voice").textContent = "VOICE NOT SELECTED";
  $("signal-status").textContent = "STANDBY";
  $("play-hint").textContent = "Your next signal is waiting.";
  updateProgress();
  showScreen("ready");
  nextRound();
}

function revealAnswer() {
  if (!state.current || state.phase !== "exercise") return;
  state.revealed = true;
  state.current.speed = state.current.retry_speed;
  $("feedback").textContent = `The call sign is ${state.current.call_sign}. Enter it to continue.`;
  $("feedback").className = "warning";
  $("answer").value = "";
  $("answer").focus();
  playCurrent();
}

function playSuccess() {
  try {
    const AudioContext = window.AudioContext || window.webkitAudioContext;
    if (!AudioContext) return;
    const context = new AudioContext();
    const oscillator = context.createOscillator();
    const volume = context.createGain();
    oscillator.frequency.value = 880;
    volume.gain.setValueAtTime(0.08, context.currentTime);
    volume.gain.exponentialRampToValueAtTime(0.001, context.currentTime + 0.15);
    oscillator.connect(volume);
    volume.connect(context.destination);
    oscillator.start();
    oscillator.stop(context.currentTime + 0.15);
    oscillator.onended = () => context.close();
  } catch (_) { /* Sound is optional if the browser blocks audio. */ }
}

$("answer-form").addEventListener("submit", (event) => {
  event.preventDefault();
  if (!state.current || state.phase !== "exercise") return;
  const answer = $("answer").value.trim().toUpperCase();
  if (!answer) {
    $("feedback").textContent = "Enter the call sign first.";
    $("feedback").className = "warning";
    return;
  }
  if (answer.includes("?")) {
    revealAnswer();
    return;
  }
  state.attempts++;
  if (answer !== state.current.call_sign) {
    state.current.speed = state.current.retry_speed;
    $("feedback").textContent = "Not quite. Listen again at a slower speed.";
    $("feedback").className = "warning";
    $("answer").select();
    playCurrent();
    return;
  }
  stopAudio();
  showError("");
  playSuccess();
  state.completed++;
  if (state.attempts === 1 && !state.revealed) state.firstTry++;
  updateProgress();
  $("play").disabled = true;
  $("signal-status").textContent = "GOOD COPY";
  $("play-hint").textContent = "Signal copied.";
  if (state.completed === state.rounds) {
    state.phase = "complete";
    $("final-result").textContent = `You completed ${state.rounds} rounds, with ${state.firstTry} first-try copies.`;
    showScreen("complete");
    $("again").focus();
  } else {
    state.phase = "success";
    $("correct-answer").textContent = state.current.call_sign;
    showScreen("success");
    $("next").focus();
  }
});

$("start").addEventListener("click", beginSession);
$("again").addEventListener("click", beginSession);
$("next").addEventListener("click", nextRound);
$("play").addEventListener("click", playCurrent);
$("reveal").addEventListener("click", revealAnswer);
$("restart").addEventListener("click", () => {
  if (state.phase === "complete" || window.confirm("Start a new session? Current progress will be lost.")) beginSession();
});
$("voice-select").addEventListener("change", () => {
  if ($("voice-select").value) showError("");
});
$("level-select").addEventListener("change", () => updateLevel());
$("random-mode").addEventListener("change", () => {
  $("single-voice").hidden = $("random-mode").checked;
  $("voice-pool").hidden = !$("random-mode").checked;
  if (selectedVoices().length) showError("");
});

async function loadVoices() {
  try {
    const response = await fetch("/api/voices");
    if (!response.ok) throw new Error("Could not load voices.");
    const data = await response.json();
    if (!Array.isArray(data.levels)) {
      throw new Error("Restart the web trainer to load the latest difficulty levels.");
    }
    state.voices = data.voices;
    state.levels = data.levels;
    state.defaultVoice = data.default;
    state.rounds = data.rounds;
    updateProgress();
    const levelSelect = $("level-select");
    levelSelect.replaceChildren();
    for (const level of state.levels) {
      const option = document.createElement("option");
      option.value = level.level;
      option.textContent = `${level.level} — ${level.name}`;
      levelSelect.append(option);
    }
    for (const voice of state.voices) {
      const label = document.createElement("label");
      label.className = "voice-option";
      const checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkbox.value = voice.name;
      checkbox.checked = true;
      const name = document.createElement("span");
      name.textContent = voiceLabel(voice);
      label.append(checkbox, name);
      $("voice-list").append(label);
    }
    if (!state.voices.length) {
      showError("No valid recordings found. Generate or add indexed voices to alphabet_wavs, then refresh.");
      $("play-hint").textContent = "Add a voice to get started.";
      return;
    }
    levelSelect.disabled = false;
    $("random-mode").disabled = false;
    $("start").disabled = false;
    updateLevel(true);
  } catch (error) {
    showError(`Could not load voices: ${error.message}`);
  }
}

loadVoices();
