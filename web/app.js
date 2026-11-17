"use strict";

/* ============================================================
   Kick Studio — UI controller
   ============================================================ */

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));

const TOKEN = new URLSearchParams(location.search).get("token") || "";
const EMPTY_IMG =
  "data:image/svg+xml;charset=utf-8," +
  encodeURIComponent(
    '<svg xmlns="http://www.w3.org/2000/svg" width="96" height="96">' +
      '<rect width="96" height="96" fill="#0a1018"/>' +
      '<circle cx="48" cy="39" r="14" fill="#1d2937"/>' +
      '<path d="M20 84c3-16 14-24 28-24s25 8 28 24" fill="#1d2937"/>' +
      "</svg>"
  );

const PAGE_META = {
  live: {
    eyebrow: "LIVE DVR",
    title: "ضبط زنده",
    subtitle: "از ابتدای پخش زنده، با کیفیت دلخواه ضبط کنید.",
  },  download: {
    eyebrow: "DOWNLOAD",
    title: "دانلود VOD و کلیپ",
    subtitle: "لینک مستقیم بدهید یا فهرست کانال را بارگذاری کنید.",
  },
  auto: {
    eyebrow: "AUTO RECORDER",
    title: "ضبط خودکار",
    subtitle: "هر استریمر با تنظیمات خودش، به‌محض لایو شدن ضبط می‌شود.",
  },
  settings: {
    eyebrow: "SETTINGS",
    title: "تنظیمات",
    subtitle: "مسیر ذخیره، FFmpeg و رفتار برنامه را مدیریت کنید.",
  },
  logs: {
    eyebrow: "LOGS",
    title: "گزارش‌ها",
    subtitle: "رویدادهای برنامه، Kick و FFmpeg را زنده ببینید.",
  },
};

const BASE_PROFILE = {
  mode: "copy",
  encoder: "auto",
  max_height: 0,
  video_bitrate: 0,
  crf: 20,
  audio_bitrate: 160,
  fps: 0,
  preset: "veryfast",
  extra_args: "",
};

const ENCODE_BASE = {
  ...BASE_PROFILE,
  mode: "encode",
};

const PROFILE_PRESETS = [
  { id: "copy", label: "کپی مستقیم — کیفیت اصلی", profile: { ...BASE_PROFILE } },
  { id: "2160", label: "4K · CRF 20", profile: { ...ENCODE_BASE, max_height: 2160, crf: 20 } },
  { id: "1440", label: "1440p · CRF 20", profile: { ...ENCODE_BASE, max_height: 1440, crf: 20 } },
  { id: "1080", label: "1080p · CRF 20", profile: { ...ENCODE_BASE, max_height: 1080, crf: 20 } },
  {
    id: "1080x6",
    label: "1080p · 6 Mbps",
    profile: { ...ENCODE_BASE, max_height: 1080, video_bitrate: 6000, crf: 20 },
  },
  { id: "720", label: "720p · CRF 21", profile: { ...ENCODE_BASE, max_height: 720, crf: 21 } },
  {
    id: "720x3",
    label: "720p · 3 Mbps",
    profile: { ...ENCODE_BASE, max_height: 720, video_bitrate: 3000, crf: 21 },
  },
  { id: "480", label: "480p · CRF 23", profile: { ...ENCODE_BASE, max_height: 480, crf: 23 } },
  { id: "360", label: "360p · CRF 25", profile: { ...ENCODE_BASE, max_height: 360, crf: 25 } },
];

const MAX_HEIGHTS = [0, 2160, 1440, 1080, 900, 720, 600, 540, 480, 360, 240];
const AUDIO_BITRATES = [0, 96, 128, 160, 192, 256, 320];
const FPS_OPTIONS = [0, 24, 25, 30, 48, 50, 60, 120, 144];
const X264_PRESETS = [
  "ultrafast",
  "superfast",
  "veryfast",
  "faster",
  "fast",
  "medium",
  "slow",
  "slower",
  "veryslow",
];

const SESSION_STATE_LABEL = {
  resolving: "آماده‌سازی",
  recording: "در حال ضبط",
  waiting: "انتظار",
  finalizing: "نهایی‌سازی",
  completed: "ذخیره شد",
  error: "خطا",
  stopped: "متوقف",
};
const DOWNLOAD_STATE_LABEL = {
  queued: "در صف",
  resolving: "بررسی لینک",
  running: "در حال دانلود",
  stopping: "توقف",
  finalizing: "ساخت MP4",
  completed: "کامل شد",
  error: "خطا",
  stopped: "متوقف",
  canceled: "لغو شد",
};
const ACTIVE_LIVE = new Set(["resolving", "recording", "waiting"]);
const BUSY_LIVE = new Set(["resolving", "recording", "waiting", "finalizing"]);
const ACTIVE_DL = new Set(["queued", "resolving", "running", "stopping", "finalizing"]);

const UI = {};
const profileControls = {};

let appState = null;
let connected = false;
let refreshing = false;
let connectionNotified = false;
let activePage = "live";
let liveProbe = null;
let liveProbeUrl = "";
let liveVariants = [];
let dlProbe = null;
let dlVariants = [];
let dlItems = [];
let dlTab = "vod";
let settingsDirty = false;
let autoDirty = false;
let liveStartMode = "start";
let foldersInitialized = false;
const folderTouched = { live: false, dl: false };
let modalCleanup = null;
let modalOnClose = null;
let installPending = false;
let logsLoading = false;
const logState = { entries: [] };

/* ---------------------------------------------------------- utilities */
const ESC_MAP = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };

function esc(value) {
  return String(value == null ? "" : value).replace(/[&<>"']/g, (ch) => ESC_MAP[ch]);
}
const escAttr = esc;

function clone(value) {
  return JSON.parse(JSON.stringify(value));
}

function normalizeProfile(raw) {
  const data = { ...BASE_PROFILE, ...(raw && typeof raw === "object" ? raw : {}) };
  data.mode = data.mode === "encode" ? "encode" : "copy";
  data.encoder = ["auto", "libx264", "h264_nvenc", "h264_qsv", "h264_amf"].includes(data.encoder)
    ? data.encoder
    : "auto";
  data.max_height = Number(data.max_height) || 0;
  data.video_bitrate = Math.max(0, Number(data.video_bitrate) || 0);
  data.crf = Math.min(51, Math.max(0, Number(data.crf) || 0));
  data.audio_bitrate = Math.max(0, Number(data.audio_bitrate) || 0);
  data.fps = Number(data.fps) || 0;
  data.preset = X264_PRESETS.includes(data.preset) ? data.preset : "veryfast";
  data.extra_args = String(data.extra_args || "");
  return data;
}

function profileEqual(a, b) {
  const keys = Object.keys(BASE_PROFILE);
  return keys.every((key) => {
    if (key === "extra_args") return String(a[key] || "").trim() === String(b[key] || "").trim();
    if (typeof BASE_PROFILE[key] === "number") return Number(a[key] || 0) === Number(b[key] || 0);
    return String(a[key] || "") === String(b[key] || "");
  });
}

function profileSummary(profile) {
  const p = normalizeProfile(profile);
  if (p.mode === "copy") return t("کپی مستقیم (کیفیت اصلی)");
  const bits = ["H.264"];
  if (p.max_height) bits.push(`${p.max_height}p`);
  if (p.video_bitrate) bits.push(`${(p.video_bitrate / 1000).toFixed(1)} Mbps`);
  else bits.push(`CRF ${p.crf}`);
  if (p.audio_bitrate) bits.push(`AAC ${p.audio_bitrate}k`);
  else bits.push(t("صوت کپی"));
  if (p.fps) bits.push(`${p.fps} FPS`);
  return bits.join(" · ");
}

function fmtBytes(value) {
  const num = Number(value) || 0;
  if (num <= 0) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let v = num;
  let i = 0;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i += 1;
  }
  return `${i === 0 ? Math.round(v) : v.toFixed(1)} ${units[i]}`;
}

function fmtDur(seconds) {
  let total = Math.max(0, Math.floor(Number(seconds) || 0));
  const h = Math.floor(total / 3600);
  total -= h * 3600;
  const m = Math.floor(total / 60);
  const s = total - m * 60;
  const pad = (n) => String(n).padStart(2, "0");
  return h ? `${pad(h)}:${pad(m)}:${pad(s)}` : `${pad(m)}:${pad(s)}`;
}

function fmtCount(value) {
  try {
    return Number(value || 0).toLocaleString(currentLocale());
  } catch {
    return String(Number(value || 0));
  }
}

function fmtDate(iso) {
  if (!iso) return "";
  try {
    return new Date(iso).toLocaleDateString(currentLocale(), { month: "short", day: "numeric" });
  } catch {
    return "";
  }
}

function splitLines(text) {
  return String(text || "")
    .split(/[\r\n]+/)
    .map((line) => line.trim())
    .filter(Boolean);
}

function serverNow() {
  if (!appState || !appState.app) return Date.now() / 1000;
  const drift = Number(appState.app.server_time || 0) - Date.now() / 1000;
  return Date.now() / 1000 + drift;
}

function fmtRel(ts) {
  const value = Number(ts) || 0;
  if (!value) return "—";
  const diff = serverNow() - value;
  if (diff < 8) return t("همین حالا");
  if (diff < 60) return `${fmtCount(Math.floor(diff))} ${t("ثانیه پیش")}`;
  if (diff < 3600) return `${fmtCount(Math.floor(diff / 60))} ${t("دقیقه پیش")}`;
  return new Date(value * 1000).toLocaleTimeString(currentLocale(), {
    hour: "2-digit",
    minute: "2-digit",
  });
}

function imgSrc(url) {
  if (!url) return EMPTY_IMG;
  return `/api/image?token=${encodeURIComponent(TOKEN)}&url=${encodeURIComponent(url)}`;
}

function emptyBlock(text, icon = "i-info", small = false) {
  return `<div class="empty${small ? " small" : ""}"><svg><use href="#${icon}"/></svg><span>${esc(
    t(text)
  )}</span></div>`;
}

/* --------------------------------------------------------------- API */
async function api(path, body) {
  const options = {
    method: body === undefined ? "GET" : "POST",
    headers: { "X-Token": TOKEN },
    cache: "no-store",
  };
  if (body !== undefined) {
    options.headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(body);
  }
  let response;
  try {
    response = await fetch(path, options);
  } catch {
    throw new Error("ارتباط با سرویس داخلی برنامه برقرار نشد.");
  }
  let data = null;
  try {
    data = await response.json();
  } catch {
    data = null;
  }
  if (!response.ok || !data || data.ok === false) {
    const error = new Error((data && data.error) || t("خطای سرور ({status})", { status: response.status }));
    error.code = data && data.code;
    error.status = response.status;
    throw error;
  }
  return data;
}

async function withLoading(button, task) {
  if (!button) return task();
  if (button.dataset.busy === "1") return undefined;
  button.dataset.busy = "1";
  button.classList.add("loading");
  button.disabled = true;
  try {
    return await task();
  } finally {
    button.dataset.busy = "0";
    button.classList.remove("loading");
    button.disabled = false;
  }
}

/* ------------------------------------------------------------ toasts */
const TOAST_ICON = { success: "i-check", error: "i-alert", warn: "i-alert", info: "i-info" };

function toast(message, level = "info") {
  const root = $("#toasts");
  if (!root) return;
  while (root.children.length >= 5) root.firstElementChild.remove();
  const el = document.createElement("div");
  el.className = `toast ${level}`;
  el.style.transition = "opacity .2s ease, transform .2s ease";
  el.innerHTML =
    `<span class="toast-icon"><svg><use href="#${TOAST_ICON[level] || "i-info"}"/></svg></span>` +
    `<span>${esc(t(message))}</span>`;
  root.appendChild(el);
  setTimeout(() => {
    el.style.opacity = "0";
    el.style.transform = "translateY(6px)";
    setTimeout(() => el.remove(), 220);
  }, 4400);
}

function showError(error) {
  const message = error && error.message ? error.message : String(error || "خطای نامشخص");
  toast(message, "error");
}
/* ---------------------------------------------------------- profiles */
function presetForProfile(profile) {
  const target = normalizeProfile(profile);
  return PROFILE_PRESETS.find((preset) => profileEqual(preset.profile, target)) || null;
}

function populateProfileSelect(select, customLabel) {
  if (!select) return;
  const options = PROFILE_PRESETS.map(
    (preset) => `<option value="${preset.id}">${esc(t(preset.label))}</option>`
  );
  options.push(`<option value="custom">${esc(customLabel || t("سفارشی — تنظیمات پیشرفته"))}</option>`);
  select.innerHTML = options.join("");
  select.dataset.ready = "1";
}

const MIN_VIDEO_BITRATE = 200;
const MAX_VIDEO_BITRATE = 80000;
const DEFAULT_VIDEO_BITRATE = 6000;

function populateAdvanced(root, key) {
  const maxHeight = $$(`select[data-pf="${key}"][data-key="max_height"]`, root);
  const audio = $$(`select[data-pf="${key}"][data-key="audio_bitrate"]`, root);
  const fps = $$(`select[data-pf="${key}"][data-key="fps"]`, root);
  const preset = $$(`select[data-pf="${key}"][data-key="preset"]`, root);

  maxHeight.forEach((el) => {
    el.innerHTML = MAX_HEIGHTS.map((height) =>
      height
        ? `<option value="${height}">${height}p</option>`
        : `<option value="0">${esc(t("بدون تغییر (منبع)"))}</option>`
    ).join("");
    el.dataset.ready = "1";
  });
  audio.forEach((el) => {
    el.innerHTML = AUDIO_BITRATES.map((rate) =>
      rate
        ? `<option value="${rate}">${rate} kbps</option>`
        : `<option value="0">${esc(t("کپی صدا"))}</option>`
    ).join("");
    el.dataset.ready = "1";
  });
  fps.forEach((el) => {
    el.innerHTML = FPS_OPTIONS.map((value) =>
      value
        ? `<option value="${value}">${value} FPS</option>`
        : `<option value="0">${esc(t("نرخ منبع"))}</option>`
    ).join("");
    el.dataset.ready = "1";
  });
  preset.forEach((el) => {
    el.innerHTML = X264_PRESETS.map(
      (value) => `<option value="${value}">${esc(value)}</option>`
    ).join("");
    el.dataset.ready = "1";
  });
}

/* Rate-control helpers: CRF mode stores video_bitrate = 0. */
function rateScope(control) {
  const modes = $(`[data-rate-modes="${control.key}"]`, control.root);
  if (!modes) return null;
  return modes.closest(".advanced") || modes.parentElement || control.root;
}

function rateElements(control) {
  const scope = rateScope(control);
  return {
    modes: scope ? $(`[data-rate-modes="${control.key}"]`, scope) : null,
    scope,
    hint: scope ? $(`[data-rate-hint="${control.key}"]`, scope) : null,
    summary: scope ? $(`[data-rate-summary="${control.key}"]`, scope) : null,
    bitrate: $(`[data-pf="${control.key}"][data-key="video_bitrate"]`, control.root),
  };
}

function syncRateUi(control) {
  const elements = rateElements(control);
  if (!elements.modes) return;
  const profile = normalizeProfile(control.profile);
  const mode = profile.video_bitrate > 0 ? "bitrate" : "crf";

  $$("[data-rate-mode]", elements.modes).forEach((button) => {
    button.classList.toggle("active", button.dataset.rateMode === mode);
  });
  $$("[data-rate-field]", elements.scope).forEach((field) => {
    field.classList.toggle("is-off", field.dataset.rateField !== mode);
  });
  if (elements.bitrate) {
    const valid =
      elements.bitrate.value === "" ||
      (Number(elements.bitrate.value) >= MIN_VIDEO_BITRATE &&
        Number(elements.bitrate.value) <= MAX_VIDEO_BITRATE);
    elements.bitrate.classList.toggle("invalid", !valid);
  }
  if (elements.hint) {
    elements.hint.textContent = profile.video_bitrate
      ? `${t("معادل")} ${(profile.video_bitrate / 1000).toFixed(1)} Mbps`
      : t("برای 1080p حدود ۴ تا ۸ مگابیت و برای 720p حدود ۲ تا ۴ مگابیت مناسب است.");
  }
  if (elements.summary) {
    const label = $("small", elements.summary);
    const value = $("b", elements.summary);
    if (label) label.textContent = t("خروجی نهایی");
    if (value) value.textContent = profileSummary(profile);
  }
}

function readProfileFields(control) {
  const profile = normalizeProfile(control.profile);
  $$(`[data-pf="${control.key}"][data-key]`, control.root).forEach((el) => {
    const key = el.dataset.key;
    if (key === "extra_args" || key === "preset") profile[key] = el.value;
    else profile[key] = Number(el.value || 0) || 0;
  });
  return profile;
}

function syncProfileFields(control) {
  const profile = normalizeProfile(control.profile);
  $$(`[data-pf="${control.key}"][data-key]`, control.root).forEach((el) => {
    const value = profile[el.dataset.key];
    el.value = value == null ? "" : String(value);
  });
  syncRateUi(control);
}

function createProfileControl(key, select, root, initialProfile, onChange, customLabel) {
  if (!select) return null;
  populateProfileSelect(select, customLabel);
  populateAdvanced(root, key);

  const control = {
    key,
    select,
    root,
    profile: normalizeProfile(initialProfile),
    dirty: false,
    set(profile) {
      this.profile = normalizeProfile(profile);
      this.sync();
    },
    get() {
      return clone(this.profile);
    },
    refresh() {
      populateProfileSelect(this.select, customLabel);
      populateAdvanced(this.root, this.key);
      this.sync();
    },
    sync() {
      const preset = presetForProfile(this.profile);
      const value = preset ? preset.id : "custom";
      if (select.querySelector(`option[value="${value}"]`)) select.value = value;
      syncProfileFields(this);
    },
  };

  const fire = (user) => {
    if (typeof onChange === "function") onChange(control.get(), Boolean(user));
    updateProfileSummaries();
  };

  select.addEventListener("change", () => {
    control.dirty = true;
    if (select.value !== "custom") {
      const preset = PROFILE_PRESETS.find((item) => item.id === select.value);
      if (preset) {
        control.profile = normalizeProfile(preset.profile);
        syncProfileFields(control);
      }
    }
    fire(true);
  });

  const onField = (event) => {
    const el = event.target;
    if (!el || !el.matches || !el.matches(`[data-pf="${key}"][data-key]`)) return;
    control.profile = readProfileFields(control);
    control.profile.mode = "encode";
    control.dirty = true;
    if (select.querySelector('option[value="custom"]')) select.value = "custom";
    syncRateUi(control);
    fire(true);
  };
  root.addEventListener("input", onField);
  root.addEventListener("change", onField);

  const elements = rateElements(control);
  if (elements.modes) {
    elements.modes.addEventListener("click", (event) => {
      const button = event.target.closest("[data-rate-mode]");
      if (!button) return;
      const mode = button.dataset.rateMode === "bitrate" ? "bitrate" : "crf";
      const current = Number(control.profile.video_bitrate) || 0;
      control.profile.video_bitrate = mode === "bitrate" ? current || DEFAULT_VIDEO_BITRATE : 0;
      control.profile.mode = "encode";
      control.dirty = true;
      if (select.querySelector('option[value="custom"]')) select.value = "custom";
      syncProfileFields(control);
      fire(true);
    });
  }

  if (elements.bitrate) {
    elements.bitrate.addEventListener("change", () => {
      let value = Math.round(Number(elements.bitrate.value) || 0);
      if (value > 0 && value < MIN_VIDEO_BITRATE) value = MIN_VIDEO_BITRATE;
      if (value > MAX_VIDEO_BITRATE) value = MAX_VIDEO_BITRATE;
      elements.bitrate.value = value ? String(value) : "";
      control.profile = readProfileFields(control);
      control.profile.video_bitrate = value;
      control.profile.mode = value ? "encode" : "copy";
      syncProfileFields(control);
      fire(true);
    });
  }

  profileControls[key] = control;
  control.sync();
  return control;
}

function updateProfileSummaries() {
  if (profileControls.live && UI.liveProfileSummary) {
    UI.liveProfileSummary.textContent = profileSummary(profileControls.live.profile);
  }
  if (profileControls.dl && UI.dlProfileSummary) {
    UI.dlProfileSummary.textContent = profileSummary(profileControls.dl.profile);
  }
}

function initProfileControls() {
  createProfileControl("live", UI.liveProfile, document, BASE_PROFILE, updateProfileSummaries);
  createProfileControl("dl", UI.dlProfile, document, BASE_PROFILE, updateProfileSummaries);
  createProfileControl(
    "auto",
    UI.autoProfile,
    document,
    BASE_PROFILE,
    null,
    t("سفارشی (پروفایل پیش‌فرض)")
  );
  createProfileControl("set", UI.setProfile, document, BASE_PROFILE, (profile, user) => {
    if (user) settingsDirty = true;
  }, t("سفارشی (حفظ شود)"));
  updateProfileSummaries();
}

function applyDefaultProfile(settings, force) {
  const profile = normalizeProfile(settings && settings.default_output);
  ["live", "dl", "auto", "set"].forEach((key) => {
    const control = profileControls[key];
    if (!control) return;
    if (force || !control.dirty) {
      control.set(profile);
      control.dirty = false;
    }
  });
  updateProfileSummaries();
}

/* ------------------------------------------------------------ sources */
function fillSourceSelect(select, variants) {
  if (!select) return;
  const previous = select.value;
  const list = Array.isArray(variants) ? variants : [];
  const options = [
    `<option value="auto">${esc(t("خودکار — بهترین کیفیت"))}</option>`,
    `<option value="worst">${esc(t("کم‌ترین کیفیت"))}</option>`,
  ];
  list.forEach((variant) => {
    const label = variant.label || variant.name || `${variant.height || "?"}p`;
    const codec = variant.codec && variant.codec !== "h264" ? ` · ${variant.codec.toUpperCase()}` : "";
    options.push(`<option value="v:${escAttr(variant.id)}">${esc(label + codec)}</option>`);
  });
  select.innerHTML = options.join("");
  if (Array.from(select.options).some((option) => option.value === previous)) {
    select.value = previous;
  } else {
    select.value = "auto";
  }
}

function sourceFromSelect(select, variants) {
  const value = select ? select.value : "auto";
  if (!value || value === "auto" || value === "best") return { mode: "auto" };
  if (value === "worst") return { mode: "worst" };
  if (value.startsWith("v:")) {
    const id = value.slice(2);
    const variant = (variants || []).find((item) => String(item.id) === id);
    if (variant) {
      return {
        mode: "variant",
        height: Number(variant.height) || 0,
        bandwidth: Number(variant.bandwidth) || 0,
        variant_id: String(variant.id),
      };
    }
  }
  if (value.startsWith("h:")) {
    return { mode: "height", height: Number(value.slice(2)) || 0 };
  }
  if (/^\d+$/.test(value)) return { mode: "height", height: Number(value) || 0 };
  return { mode: "auto" };
}

function sourceFromFixed(value) {
  if (value === "auto" || value === "best") return { mode: "auto" };
  if (value === "worst") return { mode: "worst" };
  return { mode: "height", height: Number(value) || 0 };
}

function sourceToFixedValue(source) {
  const mode = (source && source.mode) || "auto";
  if (mode === "auto" || mode === "best" || mode === "variant") return "auto";
  if (mode === "worst") return "worst";
  const height = Number(source.height) || 0;
  return [360, 480, 720, 1080].includes(height) ? String(height) : "auto";
}

function sourceSummary(source) {
  const mode = (source && source.mode) || "auto";
  if (mode === "worst") return t("کم‌ترین کیفیت");
  if (mode === "height") return `${t("حداکثر")} ${Number(source.height) || 0}p`;
  if (mode === "variant") return `${t("کیفیت")} ${Number(source.height) || t("انتخابی")}`;
  return t("بهترین کیفیت");
}

/* ------------------------------------------------------------- modals */
function closeModal() {
  const root = $("#modal-root");
  const cleanup = modalCleanup;
  const callback = modalOnClose;
  modalCleanup = null;
  modalOnClose = null;
  if (cleanup) {
    try {
      cleanup();
    } catch {
      /* ignore */
    }
  }
  if (root) {
    root.classList.add("hidden");
    root.innerHTML = "";
  }
  if (callback) {
    try {
      callback();
    } catch {
      /* ignore */
    }
  }
}

function openModal(options) {
  const { title, subtitle = "", body = "", actions = [], onClose = null, width = "" } = options || {};
  closeModal();
  const root = $("#modal-root");
  root.innerHTML =
    '<div class="modal" role="dialog" aria-modal="true">' +
    '<div class="modal-head"><div>' +
    `<h3>${esc(t(title))}</h3>` +
    (subtitle ? `<p>${esc(t(subtitle))}</p>` : "") +
    "</div>" +
    '<button class="modal-close" type="button" data-modal-close><svg><use href="#i-x"/></svg></button>' +
    "</div>" +
    `<div class="modal-body">${body}</div>` +
    (actions.length
      ? `<div class="modal-actions">${actions
          .map(
            (action, index) =>
              `<button class="btn ${action.variant || "ghost"}" type="button" data-modal-action="${index}">${esc(
                t(action.label)
              )}</button>`
          )
          .join("")}</div>`
      : "") +
    "</div>";
  root.classList.remove("hidden");

  const modal = $(".modal", root);
  if (width) modal.style.width = width;

  const onKey = (event) => {
    if (event.key === "Escape") closeModal();
  };
  document.addEventListener("keydown", onKey);
  const onBackdrop = (event) => {
    if (event.target === root) closeModal();
  };
  root.addEventListener("mousedown", onBackdrop);
  modalCleanup = () => {
    document.removeEventListener("keydown", onKey);
    root.removeEventListener("mousedown", onBackdrop);
  };
  modalOnClose = onClose;

  const closeButton = $("[data-modal-close]", root);
  if (closeButton) closeButton.addEventListener("click", () => closeModal());

  actions.forEach((action, index) => {
    const button = $(`[data-modal-action="${index}"]`, root);
    if (!button) return;
    button.addEventListener("click", async () => {
      if (action.onClick) {
        try {
          const result = await action.onClick({ close: closeModal, modal, root });
          if (result === false) return;
        } catch (error) {
          showError(error);
          return;
        }
      }
      closeModal();
    });
  });

  requestAnimationFrame(() => {
    const first = $("input:not([type=hidden]), select, textarea", root);
    if (first) first.focus();
  });
  return { root, modal, close: closeModal };
}

function confirmDialog(options) {
  const { title, message, confirmLabel = t("تأیید"), danger = false, subtitle = "" } = options || {};
  return new Promise((resolve) => {
    let settled = false;
    const finish = (value) => {
      if (settled) return;
      settled = true;
      closeModal();
      resolve(value);
    };
    openModal({
      title,
      subtitle,
      body: `<p style="color:var(--muted);font-size:11.5px;line-height:1.9">${esc(t(message))}</p>`,
      onClose: () => finish(false),
      actions: [
        { label: t("انصراف"), variant: "ghost", onClick: () => finish(false) },
        { label: confirmLabel, variant: danger ? "danger" : "primary", onClick: () => finish(true) },
      ],
    });
  });
}

function askText(options) {
  const { title, label = t("مسیر"), value = "", placeholder = "" } = options || {};
  return new Promise((resolve) => {
    let settled = false;
    const finish = (result) => {
      if (settled) return;
      settled = true;
      closeModal();
      resolve(result);
    };
    const dialog = openModal({
      title,
      body:
        '<div class="field" style="margin-bottom:0"><label>' +
        `${esc(t(label))}</label><div class="input-wrap">` +
        '<svg class="input-icon"><use href="#i-folder"/></svg>' +
        `<input id="ask-input" type="text" dir="ltr" value="${escAttr(value)}" placeholder="${escAttr(
          placeholder
        )}"></div></div>`,
      onClose: () => finish(null),
      actions: [
        { label: t("انصراف"), variant: "ghost", onClick: () => finish(null) },
        {
          label: t("تأیید"),
          variant: "primary",
          onClick: () => {
            const input = $("#ask-input", dialog.root);
            finish((input && input.value.trim()) || null);
          },
        },
      ],
    });
    const input = $("#ask-input", dialog.root);
    if (input) {
      input.addEventListener("keydown", (event) => {
        if (event.key === "Enter") {
          event.preventDefault();
          finish(input.value.trim() || null);
        }
      });
    }
  });
}

async function chooseFolder(initial) {
  try {
    if (window.pywebview && window.pywebview.api && window.pywebview.api.choose_folder) {
      const result = await window.pywebview.api.choose_folder();
      if (result) return String(result);
      return null;
    }
  } catch {
    /* fall back to text input */
  }
  return askText({
    title: t("انتخاب پوشه"),
    label: t("مسیر کامل پوشه"),
    value: initial || "",
  });
}

async function openPath(path) {
  if (!path) {
    toast(t("مسیری برای باز کردن وجود ندارد."), "warn");
    return;
  }
  try {
    await api("/api/open", { path });
  } catch (error) {
    showError(error);
  }
}
/* --------------------------------------------------------- state core */
async function refreshState(initial = false) {
  if (refreshing) return;
  refreshing = true;
  try {
    const data = await api("/api/state");
    applyState(data, initial);
  } catch (error) {
    connected = false;
    updateConnectionUi();
    if (!connectionNotified) {
      connectionNotified = true;
      toast(error.message || t("ارتباط با سرویس داخلی قطع شد."), "error");
    }
  } finally {
    refreshing = false;
  }
}

function applyState(data, initial = false) {
  const first = !appState;
  appState = data;
  connected = true;
  connectionNotified = false;

  if (first && data.settings && data.settings.language) {
    const serverLanguage = data.settings.language;
    if (serverLanguage !== currentLanguage()) applyLanguage(serverLanguage, { refresh: false });
  }

  if (first || initial) applyDefaultProfile(data.settings, true);
  applySettings(data.settings, first || initial);
  applyAutoSettings(data.auto, first || initial);
  applyTools(data.tools);
  applyStats(data.stats, data);
  renderSessions();
  renderDownloads();
  renderAuto();
  updateLiveStartState();
  if (liveProbe) updatePreviewTime();

  if (!foldersInitialized) {
    if (!folderTouched.live && UI.liveFolder) UI.liveFolder.value = data.settings.download_dir || "";
    if (!folderTouched.dl && UI.dlFolder) UI.dlFolder.value = data.settings.download_dir || "";
    foldersInitialized = true;
  }

  if (installPending) {
    if (data.tools && data.tools.installing) {
      /* progress is already rendered by applyTools */
    } else if (data.tools && data.tools.ok) {
      installPending = false;
      toast(t("FFmpeg با موفقیت نصب شد."), "success");
    } else {
      installPending = false;
      toast((data.tools && data.tools.error) || t("نصب FFmpeg ناموفق بود."), "error");
    }
  }
  updateConnectionUi();
}

function updateConnectionUi() {
  if (!UI.topStatus) return;
  UI.topStatus.classList.toggle("ok", connected);
  UI.topStatus.classList.toggle("bad", !connected);
  const label = UI.topStatus.querySelector("span:last-child");
  if (label) label.textContent = connected ? t("متصل") : t("قطع");
}

function shortVersion(version) {
  const text = String(version || "").replace(/^ffmpeg version\s*/i, "").trim();
  return text.length > 44 ? `${text.slice(0, 44)}…` : text || "FFmpeg";
}

function applyTools(tools) {
  if (!tools || !UI.toolChip) return;
  const ok = Boolean(tools.ok);
  const dot = $(".dot", UI.toolChip);
  if (dot) {
    dot.classList.toggle("ok", ok);
    dot.classList.toggle("bad", !ok);
  }
  UI.toolChipTitle.textContent = ok ? t("FFmpeg آماده") : t("FFmpeg نصب نشده");
  UI.toolChipSub.textContent = ok ? shortVersion(tools.version) : t("از تنظیمات نصب کنید");

  if (UI.statFfmpeg) {
    UI.statFfmpeg.textContent = ok ? t("آماده") : t("نصب نشده");
    UI.statFfmpeg.className = ok ? "green" : "red";
  }
  if (UI.infoFfmpeg) UI.infoFfmpeg.textContent = ok ? shortVersion(tools.version) : tools.error || "—";
  if (UI.infoEncoders) {
    const map = {
      libx264: "x264",
      h264_nvenc: "NVENC",
      h264_qsv: "QSV",
      h264_amf: "AMF",
    };
    const names = (tools.encoders || []).map((name) => map[name] || name);
    UI.infoEncoders.textContent = names.length ? names.join(" · ") : "—";
  }

  if (UI.ffmpegStatus) {
    UI.ffmpegStatus.classList.remove("ok", "bad");
    if (tools.installing) {
      UI.ffmpegStatus.textContent = tools.install_message || t("در حال نصب FFmpeg…");
    } else if (ok) {
      UI.ffmpegStatus.classList.add("ok");
      UI.ffmpegStatus.textContent = `${shortVersion(tools.version)} · ${t("{n} انکودر H.264", {
        n: (tools.encoders || []).length,
      })}`;
    } else {
      UI.ffmpegStatus.classList.add("bad");
      UI.ffmpegStatus.textContent = tools.error || t("FFmpeg در دسترس نیست.");
    }
  }
  if (UI.ffmpegProgress) {
    UI.ffmpegProgress.classList.toggle("hidden", !tools.installing);
    const fill = $(".progress-fill", UI.ffmpegProgress);
    if (fill) fill.style.width = `${Math.max(0, Math.min(100, Number(tools.install_progress) || 0))}%`;
  }
  if (UI.ffmpegInstall) UI.ffmpegInstall.disabled = ok || Boolean(tools.installing);
}

function applySettings(settings, force) {
  if (!settings) return;
  if (UI.infoVersion && appState && appState.app) UI.infoVersion.textContent = appState.app.version || "3.0";
  if (UI.infoDownloadDir) UI.infoDownloadDir.textContent = settings.download_dir || "—";
  if (UI.setCookieHint) {
    UI.setCookieHint.textContent = t(
      settings.kick_cookie_set
        ? "کوکی ذخیره شده است. برای حذف، «clear» را وارد و ذخیره کنید."
        : "اگر مقداردهی شده باشد، در درخواست‌های Kick استفاده می‌شود."
    );
  }
  if (!force && settingsDirty) return;
  if (UI.setDownloadDir) UI.setDownloadDir.value = settings.download_dir || "";
  if (UI.setFfmpeg) UI.setFfmpeg.value = settings.ffmpeg_path || "";
  if (UI.setMaxDownloads) UI.setMaxDownloads.value = String(settings.max_downloads || 2);
  if (UI.setKeepParts) UI.setKeepParts.checked = Boolean(settings.keep_parts);
  if (profileControls.set && (force || !profileControls.set.dirty)) {
    profileControls.set.set(settings.default_output);
    profileControls.set.dirty = false;
  }
}

function applyAutoSettings(auto, force) {
  if (!auto) return;
  if (UI.autoEnabled) UI.autoEnabled.checked = Boolean(auto.enabled);
  if (!force && autoDirty) return;
  if (UI.autoInterval) UI.autoInterval.value = String(auto.poll_interval || 25);
  if (UI.autoGap) UI.autoGap.value = String(auto.session_gap || 90);
  if (UI.autoMax) UI.autoMax.value = String(auto.max_active || 3);
}

function applyStats(stats, data) {
  if (!stats) return;
  if (UI.statActive) UI.statActive.textContent = fmtCount(stats.active_sessions || 0);
  if (UI.statAuto) UI.statAuto.textContent = fmtCount(stats.active_auto || 0);
  if (UI.statSpace) UI.statSpace.textContent = stats.free_space_text || "—";
  if (UI.infoSpace) UI.infoSpace.textContent = stats.free_space_text || "—";
  if (UI.navAutoCount && data.auto) {
    const count = (data.auto.streamers || []).length;
    UI.navAutoCount.textContent = String(count);
  }
}

/* -------------------------------------------------------- live preview */
function renderLivePreview(probe) {
  if (!probe || probe.type !== "channel" || !probe.channel) {
    resetLivePreview();
    return;
  }
  const channel = probe.channel;
  liveProbe = probe;
  liveVariants = Array.isArray(probe.variants) ? probe.variants : [];

  if (!probe.live) {
    UI.livePreview.classList.add("hidden");
    UI.liveOffline.classList.remove("hidden");
    const label = channel.username || channel.slug || t("این کانال");
    UI.liveOfflineTitle.textContent = `${label} ${t("الان لایو نیست.")}`;
    updateLiveStartState();
    return;
  }

  UI.liveOffline.classList.add("hidden");
  UI.livePreview.classList.remove("hidden");
  UI.liveAvatar.src = imgSrc(channel.avatar);
  UI.liveName.textContent = channel.username || channel.slug || "Channel";
  UI.liveStreamTitle.textContent = probe.title || channel.title || "—";
  UI.liveViewers.textContent = fmtCount(channel.viewers || 0);
  UI.liveCategory.textContent = (channel.categories || []).join(
    currentLanguage() === "en" ? " · " : "، "
  );
  UI.liveDvrBadge.classList.toggle("hidden", !probe.has_dvr);
  fillSourceSelect(UI.liveSource, liveVariants);

  if (UI.liveStartMode) {
    liveStartMode = probe.has_dvr ? liveStartMode : "now";
    syncStartModeUi();
  }
  updatePreviewTime();
  updateLiveStartState();
}

function resetLivePreview() {
  liveProbe = null;
  liveProbeUrl = "";
  liveVariants = [];
  if (UI.livePreview) UI.livePreview.classList.add("hidden");
  if (UI.liveOffline) UI.liveOffline.classList.add("hidden");
  liveStartMode = "start";
  syncStartModeUi();
  updateLiveStartState();
}

function syncStartModeUi() {
  if (!UI.liveStartMode) return;
  $$("[data-start-mode]", UI.liveStartMode).forEach((button) => {
    const isStart = button.dataset.startMode === "start";
    button.disabled = isStart && Boolean(liveProbe) && !liveProbe.has_dvr;
    button.classList.toggle("active", button.dataset.startMode === liveStartMode);
  });
  if (UI.liveStartModeHint) {
    UI.liveStartModeHint.textContent =
      liveProbe && !liveProbe.has_dvr
        ? t("DVR در دسترس نیست؛ از زمان حال ضبط می‌شود.")
        : t("برای حالت «از ابتدا»، DVR باید در دسترس باشد.");
  }
}

function updatePreviewTime() {
  if (!UI.liveTime || !liveProbe || !liveProbe.channel) return;
  const started = Number(liveProbe.channel.started_ts) || 0;
  UI.liveTime.textContent = started ? fmtDur(serverNow() - started) : "—";
}

function activeSessionForSlug(slug) {
  if (!appState || !slug) return null;
  return (
    (appState.sessions || []).find(
      (session) => session.slug === slug && BUSY_LIVE.has(session.state)
    ) || null
  );
}

function updateLiveStartState() {
  if (!UI.liveStart) return;
  const url = UI.liveUrl ? UI.liveUrl.value.trim() : "";
  let enabled = false;
  let hint = t("ابتدا کانال را بررسی کنید.");
  if (
    liveProbe &&
    liveProbe.type === "channel" &&
    liveProbe.live &&
    liveProbe.channel &&
    url &&
    liveProbeUrl === url
  ) {
    const active = activeSessionForSlug(liveProbe.channel.slug);
    if (active) {
      hint = t("ضبط این کانال همین حالا فعال است.");
    } else {
      enabled = true;
      if (liveStartMode !== "start") {
        hint = t("ضبط از همین لحظه شروع می‌شود و تا پایان پخش ادامه دارد.");
      } else {
        hint = liveProbe.has_dvr
          ? t("DVR در دسترس است؛ می‌توانید از ابتدای پخش ضبط کنید.")
          : t("DVR در دسترس نیست؛ از زمان حال ضبط می‌شود.");
      }
    }
  } else if (liveProbe && liveProbe.type === "channel" && !liveProbe.live) {
    hint = t("کانال آفلاین است؛ پس از لایو شدن دوباره بررسی کنید.");
  }
  UI.liveStart.disabled = !enabled;
  if (UI.liveStartHint) UI.liveStartHint.textContent = hint;
}
/* ----------------------------------------------------------- rendering */
function stateChip(state, labels) {
  let cls = "offline";
  if (["recording", "running"].includes(state)) cls = "recording";
  else if (["resolving", "waiting", "queued", "stopping", "finalizing"].includes(state)) cls = "waiting";
  else if (state === "completed") cls = "recording";
  else if (state === "error") cls = "error";
  return `<span class="status-chip ${cls}">${esc(t(labels[state] || state || "—"))}</span>`;
}

function kvBlock(items) {
  return items
    .filter((item) => item && item.value !== undefined && item.value !== null && item.value !== "")
    .map(
      (item) =>
        `<div class="kv"><small>${esc(item.label)}</small><b>${esc(item.value)}</b></div>`
    )
    .join("");
}

function progressBlock(state, mediaSeconds, duration, finalizing = false) {
  const media = Number(mediaSeconds) || 0;
  const total = Number(duration) || 0;
  let percent = 0;
  if (state === "completed") percent = 100;
  else if (total > 0 && media > 0) percent = Math.min(100, (media / total) * 100);
  const indeterminate =
    percent <= 0 &&
    ["resolving", "waiting", "queued", "recording", "running", "stopping", "finalizing"].includes(
      state
    );
  return (
    `<div class="progress ${indeterminate ? "indeterminate" : ""} ${
      finalizing || state === "finalizing" ? "warn" : ""
    }"><div class="progress-fill" style="width:${percent.toFixed(1)}%"></div></div>`
  );
}

function logsBlock(logs, error) {
  const lines = Array.isArray(logs) ? logs.slice(-3) : [];
  const parts = [];
  if (error) parts.push(`<div class="err">${esc(t("خطا"))}: ${esc(error)}</div>`);
  lines.forEach((line) => parts.push(`<div>${esc(line)}</div>`));
  if (!parts.length) return "";
  return `<div class="session-logs">${parts.join("")}</div>`;
}

function liveCardClass(state) {
  if (ACTIVE_LIVE.has(state)) return "active";
  if (state === "finalizing") return "finalizing";
  if (state === "completed") return "completed";
  if (state === "error") return "error";
  return "";
}

function downloadCardClass(state) {
  if (["queued", "resolving", "running", "stopping"].includes(state)) return "active";
  if (state === "finalizing") return "finalizing";
  if (state === "completed") return "completed";
  if (state === "error") return "error";
  return "";
}

function sessionCard(session) {
  const state = session.state || "stopped";
  const title =
    (session.channel && session.channel.username) ||
    session.title ||
    session.slug ||
    t("ضبط زنده");
  const filePath = state === "completed" ? session.output_path || "" : "";
  const openTarget = filePath || session.folder || "";
  const active = BUSY_LIVE.has(state);
  const meta = [];
  if (session.slug) meta.push(`<span dir="ltr">@${esc(session.slug)}</span>`);
  if (session.auto_id) meta.push(`<span>${esc(t("ضبط خودکار"))}</span>`);
  if (session.source_label)
    meta.push(`<span>${esc(t("منبع:"))} <b>${esc(session.source_label)}</b></span>`);
  if (session.profile_label) meta.push(`<span><b>${esc(session.profile_label)}</b></span>`);
  if (session.has_dvr) meta.push("<span>DVR</span>");
  if (session.from_start) meta.push(`<span>${esc(t("از ابتدا"))}</span>`);
  if (session.parts) meta.push(`<span>${fmtCount(session.parts)} ${esc(t("بخش"))}</span>`);

  const actions = [];
  if (active) {
    actions.push(
      `<button class="btn danger sm" type="button" data-session-stop="${escAttr(
        session.id
      )}" title="${escAttr(t("توقف"))}"><svg><use href="#i-stop"/></svg><span>${esc(
        t("توقف")
      )}</span></button>`
    );
  }
  if (openTarget) {
    actions.push(
      `<button class="btn ghost sm" type="button" data-open-path="${escAttr(
        openTarget
      )}" title="${escAttr(t("باز کردن مسیر"))}"><svg><use href="#i-folder"/></svg></button>`
    );
  }

  const stats = kvBlock([
    { label: t("مدت"), value: fmtDur(session.elapsed) },
    { label: t("ضبط‌شده"), value: fmtDur(session.media_seconds) },
    { label: t("حجم"), value: fmtBytes(session.size) },
    { label: t("بخش‌ها"), value: session.parts ? fmtCount(session.parts) : "" },
    { label: t("سرعت"), value: session.progress && session.progress.speed ? session.progress.speed : "" },
    { label: t("بیتریت"), value: session.progress && session.progress.bitrate ? session.progress.bitrate : "" },
  ]);

  return (
    `<article class="session-card ${liveCardClass(state)}">` +
    '<div class="session-head"><div class="session-title">' +
    '<div class="session-orb"><svg><use href="#i-live"/></svg></div>' +
    `<div><h3>${esc(title)}</h3><div class="meta">${meta.join("")}${stateChip(
      state,
      SESSION_STATE_LABEL
    )}</div></div></div>` +
    `<div class="session-actions">${actions.join("")}</div></div>` +
    `<div class="session-progress">${progressBlock(state, session.media_seconds, 0)}</div>` +
    `<div class="session-stats">${stats}</div>` +
    logsBlock(session.logs, session.error) +
    (openTarget
      ? `<div class="session-output" title="${escAttr(openTarget)}"><b>${esc(t("مسیر:"))}</b> ${esc(openTarget)}</div>`
      : "") +
    "</article>"
  );
}

function renderSessions() {
  if (!UI.liveSessions) return;
  const sessions = (appState && appState.sessions) || [];
  if (!sessions.length) {
    UI.liveSessions.innerHTML = emptyBlock(
      t("هنوز ضبطی شروع نشده است. یک کانال را بررسی و ضبط را آغاز کنید."),
      "i-live"
    );
    return;
  }
  UI.liveSessions.innerHTML = sessions.map(sessionCard).join("");
}

function downloadCard(job) {
  const state = job.state || "queued";
  const active = ACTIVE_DL.has(state);
  const title = job.title || job.url || t("دانلود");
  const kindLabel = { vod: "VOD", clip: t("کلیپ"), direct: t("لینک مستقیم") }[job.kind] || t("رسانه");
  const openTarget = state === "completed" ? job.output_path || "" : "";
  const meta = [`<span>${esc(kindLabel)}</span>`];
  if (job.channel) meta.push(`<span dir="ltr">@${esc(job.channel)}</span>`);
  if (job.profile_label) meta.push(`<span><b>${esc(job.profile_label)}</b></span>`);
  meta.push(stateChip(state, DOWNLOAD_STATE_LABEL));

  const actions = [];
  if (active) {
    actions.push(
      `<button class="btn danger sm" type="button" data-download-stop="${escAttr(
        job.id
      )}" title="${escAttr(t("توقف"))}"><svg><use href="#i-stop"/></svg><span>${esc(
        t("توقف")
      )}</span></button>`
    );
  }
  if (openTarget) {
    actions.push(
      `<button class="btn ghost sm" type="button" data-open-path="${escAttr(
        openTarget
      )}" title="${escAttr(t("باز کردن فایل"))}"><svg><use href="#i-folder"/></svg></button>`
    );
  }

  const percent =
    job.duration > 0 && job.media_seconds > 0
      ? `${Math.min(100, Math.round((job.media_seconds / job.duration) * 100))}%`
      : state === "completed"
      ? "100%"
      : "";
  const stats = kvBlock([
    { label: t("مدت"), value: fmtDur(job.elapsed) },
    {
      label: t("دانلودشده"),
      value:
        job.duration > 0
          ? `${fmtDur(job.media_seconds)} / ${fmtDur(job.duration)}`
          : fmtDur(job.media_seconds),
    },
    { label: t("حجم"), value: fmtBytes(job.size) },
    { label: t("پیشرفت"), value: percent },
    { label: t("سرعت"), value: job.speed || "" },
    { label: t("بیت‌ریت"), value: job.bitrate || "" },
  ]);

  return (
    `<article class="session-card ${downloadCardClass(state)}">` +
    '<div class="session-head"><div class="session-title">' +
    '<div class="session-orb download"><svg><use href="#i-download"/></svg></div>' +
    `<div><h3>${esc(title)}</h3><div class="meta">${meta.join("")}</div></div></div>` +
    `<div class="session-actions">${actions.join("")}</div></div>` +
    `<div class="session-progress">${progressBlock(
      state,
      job.media_seconds,
      job.duration
    )}</div>` +
    `<div class="session-stats">${stats}</div>` +
    logsBlock(job.logs, job.error) +
    (openTarget
      ? `<div class="session-output" title="${escAttr(openTarget)}"><b>${esc(t("فایل:"))}</b> ${esc(openTarget)}</div>`
      : "") +
    "</article>"
  );
}

function renderDownloads() {
  if (!UI.downloadsList) return;
  const jobs = (appState && appState.downloads) || [];
  if (!jobs.length) {
    UI.downloadsList.innerHTML = emptyBlock(
      "هنوز دانلودی ثبت نشده است. لینک VOD یا کلیپ را وارد کنید.",
      "i-download"
    );
    return;
  }
  UI.downloadsList.innerHTML = jobs.map(downloadCard).join("");
}
/* ---------------------------------------------------------------- auto */
function autoStatus(item) {
  const status = item.status || {};
  if (status.error) return { cls: "error", label: "خطا" };
  if (status.recording) return { cls: "recording", label: "در حال ضبط" };
  if (status.waiting_slot) return { cls: "waiting", label: "در صف" };
  if (status.live) return { cls: "live", label: "لایو" };
  if (status.session_state === "waiting") return { cls: "waiting", label: "انتظار" };
  return { cls: "offline", label: "آفلاین" };
}

function autoCard(item) {
  const status = item.status || {};
  const chip = autoStatus(item);
  const name = item.name || item.slug || "استریمر";
  const initial = String(name).trim().charAt(0).toUpperCase() || "K";
  const bits = [];
  if (status.title) bits.push(status.title);
  if (status.live) bits.push(`${fmtCount(status.viewers || 0)} ${t("بیننده")}`);
  bits.push(sourceSummary(item.source));
  bits.push(profileSummary(item.output));
  if (item.folder) bits.push(item.folder);
  if (status.error) bits.push(status.error);

  const actions = [];
  if (status.recording && status.session_id) {
    actions.push(
      `<button class="btn danger sm" type="button" data-auto-stop="${escAttr(
        status.session_id
      )}" title="${escAttr(t("توقف ضبط"))}"><svg><use href="#i-stop"/></svg></button>`
    );
  } else if (status.live) {
    actions.push(
      `<button class="btn primary sm" type="button" data-auto-restart="${escAttr(
        item.id
      )}" title="${escAttr(t("ضبط دوباره از ابتدا"))}"><svg><use href="#i-refresh"/></svg><span>${esc(
        t("ضبط مجدد")
      )}</span></button>`
    );
  }
  actions.push(
    `<button class="btn ghost sm" type="button" data-auto-edit="${escAttr(
      item.id
    )}" title="ویرایش"><svg><use href="#i-edit"/></svg></button>`
  );
  actions.push(
    `<button class="btn ghost sm" type="button" data-auto-folder="${escAttr(
      item.id
    )}" title="پوشه ذخیره"><svg><use href="#i-folder"/></svg></button>`
  );
  actions.push(
    `<button class="btn ghost sm" type="button" data-auto-remove="${escAttr(
      item.id
    )}" title="حذف"><svg><use href="#i-trash"/></svg></button>`
  );
  actions.push(
    `<label class="switch" title="فعال/غیرفعال"><input type="checkbox" data-auto-toggle="${escAttr(
      item.id
    )}" ${item.enabled ? "checked" : ""}><span class="switch-ui"></span></label>`
  );

  return (
    `<article class="auto-card ${status.recording ? "recording" : ""} ${
      item.enabled ? "" : "disabled"
    }">` +
    `<div class="auto-avatar">${
      item.avatar ? `<img src="${escAttr(imgSrc(item.avatar))}" alt="">` : esc(initial)
    }</div>` +
    '<div class="auto-info"><div class="auto-name-line">' +
    `<h3>${esc(name)}</h3><span class="slug">@${esc(item.slug)}</span>` +
    `<span class="status-chip ${chip.cls}">${chip.label}</span>` +
    "</div>" +
    `<div class="auto-sub" title="${escAttr(bits.join(" · "))}">${bits
      .map((bit) => esc(bit))
      .join(" · ")}</div>` +
    "</div>" +
    `<div class="auto-actions">${actions.join("")}</div>` +
    "</article>"
  );
}

function renderAutoActivity(entries) {
  if (!UI.autoActivity) return;
  const list = Array.isArray(entries) ? entries.slice(-30) : [];
  if (!list.length) {
    UI.autoActivity.innerHTML = emptyBlock("رویدادی برای ضبط خودکار ثبت نشده است.", "i-robot", true);
    return;
  }
  UI.autoActivity.innerHTML = list
    .map(
      (entry) =>
        `<div class="activity-line ${esc(entry.level || "info")}">` +
        `<time>${esc(entry.time || "")}</time><span class="lv"></span>` +
        `<span>${esc(entry.message || "")}</span></div>`
    )
    .join("");
}

function renderAuto() {
  if (!UI.autoList || !appState || !appState.auto) return;
  const auto = appState.auto;
  const streamers = auto.streamers || [];

  if (UI.autoMeta) {
    const parts = [t(auto.running ? "سرویس فعال" : "سرویس متوقف")];
    parts.push(
      `${fmtCount(auto.active || 0)}/${fmtCount(auto.max_active || 0)} ${t("ضبط")}`
    );
    if (auto.scanning) parts.push(t("در حال بررسی…"));
    else if (auto.next_scan) {
      const left = Math.max(0, Math.round(auto.next_scan - serverNow()));
      parts.push(
        left > 0
          ? t("بررسی بعدی: {n} ثانیه", { n: fmtCount(left) })
          : t("بررسی در راه است")
      );
    }
    if (auto.last_scan) parts.push(t("آخرین بررسی: {time}", { time: fmtRel(auto.last_scan) }));
    UI.autoMeta.textContent = parts.join(" · ");
  }

  if (!streamers.length) {
    UI.autoList.innerHTML = emptyBlock(
      "هنوز استریمری اضافه نشده است. لینک کانال را وارد کنید و «افزودن» را بزنید.",
      "i-robot"
    );
  } else {
    UI.autoList.innerHTML = streamers.map(autoCard).join("");
  }
  renderAutoActivity(auto.activity);
}

function autoSourceOptions(selected) {
  const values = [
    ["auto", "بهترین کیفیت"],
    ["1080", "حداکثر 1080p"],
    ["720", "حداکثر 720p"],
    ["480", "حداکثر 480p"],
    ["360", "حداکثر 360p"],
    ["worst", "کم‌ترین کیفیت"],
  ];
  return values
    .map(
      ([value, label]) =>
        `<option value="${value}" ${value === selected ? "selected" : ""}>${esc(t(label))}</option>`
    )
    .join("");
}

function openAutoEdit(id) {
  if (!appState || !appState.auto) return;
  const item = (appState.auto.streamers || []).find((entry) => String(entry.id) === String(id));
  if (!item) {
    toast("استریمر در فهرست پیدا نشد.", "warn");
    return;
  }
  const selectedSource = sourceToFixedValue(item.source);
  const body =
    '<div class="settings-grid">' +
    '<div class="field"><label>کیفیت منبع</label>' +
    `<select data-modal-source>${autoSourceOptions(selectedSource)}</select>` +
    '<small class="hint">کیفیت دریافتی از Kick برای این استریمر.</small></div>' +
    '<div class="field"><label>پوشه ذخیره (اختیاری)</label><div class="input-row">' +
    '<div class="input-wrap"><svg class="input-icon"><use href="#i-folder"/></svg>' +
    `<input id="modal-folder" type="text" dir="ltr" value="${escAttr(
      item.folder || ""
    )}" placeholder="پوشه پیش‌فرض"></div>` +
    '<button class="btn ghost" type="button" data-modal-choose title="انتخاب پوشه"><svg><use href="#i-folder"/></svg></button>' +
    "</div></div></div>" +
    '<div class="field"><label>پروفایل خروجی</label>' +
    '<select data-profile-select="modal"></select>' +
    '<small class="hint" id="modal-profile-summary"></small></div>' +
    '<div class="settings-grid four">' +
    '<div class="field"><label>حداکثر ارتفاع</label><select data-pf="modal" data-key="max_height"></select></div>' +
    '<div class="field"><label>بیت‌ریت ویدیو (kbps)</label><input data-pf="modal" data-key="video_bitrate" type="number" min="0" step="100" placeholder="0 = CRF"></div>' +
    '<div class="field"><label>CRF (کیفیت)</label><input data-pf="modal" data-key="crf" type="number" min="0" max="51"></div>' +
    '<div class="field"><label>بیت‌ریت صدا (kbps)</label><select data-pf="modal" data-key="audio_bitrate"></select></div>' +
    '<div class="field"><label>محدودیت FPS</label><select data-pf="modal" data-key="fps"></select></div>' +
    '<div class="field"><label>Preset</label><select data-pf="modal" data-key="preset"></select></div>' +
    '<div class="field span-2"><label>آرگومان‌های اضافه FFmpeg</label><input data-pf="modal" data-key="extra_args" type="text" placeholder="-tune film …"></div>' +
    "</div>";

  const dialog = openModal({
    title: t("ویرایش {name}", { name: item.name || item.slug }),
    subtitle: "کیفیت منبع، پروفایل خروجی و پوشه اختصاصی این استریمر",
    body,
    actions: [
      { label: "انصراف", variant: "ghost" },
      {
        label: "ذخیره تغییرات",
        variant: "primary",
        onClick: async () => {
          const sourceValue = $("[data-modal-source]", dialog.root).value;
          const folderInput = $("#modal-folder", dialog.root);
          const folder = folderInput ? folderInput.value.trim() : "";
          const output = profileControls.modal ? profileControls.modal.get() : item.output;
          await api("/api/auto/update", {
            id: item.id,
            source: sourceFromFixed(sourceValue),
            output,
            folder,
          });
          toast("تنظیمات استریمر ذخیره شد.", "success");
          await refreshState();
        },
      },
    ],
  });

  const modalRoot = dialog.modal;
  const summary = $("#modal-profile-summary", modalRoot);
  profileControls.modal = null;
  const control = createProfileControl(
    "modal",
    $('[data-profile-select="modal"]', modalRoot),
    modalRoot,
    item.output,
    (profile) => {
      if (summary) summary.textContent = profileSummary(profile);
    }
  );
  if (control && summary) summary.textContent = profileSummary(item.output);

  const choose = $("[data-modal-choose]", modalRoot);
  if (choose) {
    choose.addEventListener("click", async () => {
      const path = await chooseFolder($("#modal-folder", modalRoot).value);
      if (path) $("#modal-folder", modalRoot).value = path;
    });
  }
}
/* ------------------------------------------------------------ downloads */
function mediaCard(item) {
  const kind = item.is_live ? "vod" : dlTab === "clip" ? "clip" : "vod";
  const title = item.title || item.url || "رسانه";
  const meta = [];
  const duration = item.duration_text || (item.duration ? fmtDur(item.duration) : "");
  if (duration) meta.push(`<span><svg><use href="#i-clock"/></svg>${esc(duration)}</span>`);
  if (item.channel_name || item.channel) {
    meta.push(`<span dir="ltr">@${esc(item.channel_name || item.channel)}</span>`);
  }
  if (item.created_at) meta.push(`<span>${esc(fmtDate(item.created_at))}</span>`);
  if (item.creator) meta.push(`<span>${esc(item.creator)}</span>`);
  if (item.category) meta.push(`<span>${esc(item.category)}</span>`);

  const chip = item.is_live
    ? '<span class="status-chip live">LIVE</span>'
    : kind === "clip"
    ? '<span class="status-chip">کلیپ</span>'
    : '<span class="status-chip">VOD</span>';

  return (
    `<label class="media-card" data-url="${escAttr(item.url || "")}" data-title="${escAttr(
      title
    )}" data-kind="${kind}">` +
    `<input type="checkbox" value="${escAttr(item.url || "")}">` +
    '<span class="media-check"></span>' +
    '<div class="media-thumb">' +
    (item.thumbnail
      ? `<img src="${escAttr(imgSrc(item.thumbnail))}" alt="">`
      : '<div style="display:grid;place-items:center;height:100%;color:#33465a"><svg><use href="#i-film"/></svg></div>') +
    (item.is_live ? '<span class="live-mini">LIVE</span>' : "") +
    "</div>" +
    `<div class="media-info"><h4>${esc(title)}</h4><div class="media-meta">${meta.join("")}</div></div>` +
    `<div class="media-side"><span class="media-views">${fmtCount(item.views || 0)} ${t("بازدید")}</span>${chip}</div>` +
    "</label>"
  );
}

function renderMediaList() {
  if (!UI.dlList) return;
  if (!dlItems.length) {
    UI.dlList.innerHTML = emptyBlock(
      dlTab === "clip"
        ? "کلیپی بارگذاری نشده است. لینک کانال را وارد کنید و «بارگذاری فهرست کانال» را بزنید."
        : "فهرستی بارگذاری نشده است. لینک کانال را وارد کنید و «بارگذاری فهرست کانال» را بزنید.",
      dlTab === "clip" ? "i-clip" : "i-film"
    );
    updateSelectedCount();
    return;
  }
  UI.dlList.innerHTML = dlItems.map(mediaCard).join("");
  updateSelectedCount();
}

function selectedMedia() {
  if (!UI.dlList) return [];
  return $$('input[type="checkbox"]:checked', UI.dlList).map((input) => {
    const card = input.closest(".media-card");
    return {
      url: card.dataset.url || input.value,
      title: card.dataset.title || "",
      kind: card.dataset.kind || "vod",
    };
  });
}

function updateSelectedCount() {
  if (!UI.dlSelected) return;
  const count = selectedMedia().length;
  UI.dlSelected.textContent = count
    ? t("{n} مورد انتخاب شده", { n: fmtCount(count) })
    : t("موردی انتخاب نشده");
  if (UI.dlSelectAll) {
    UI.dlSelectAll.classList.toggle("hidden", !dlItems.length);
    const label = UI.dlSelectAll.querySelector("span");
    if (label)
      label.textContent =
        count && count === dlItems.length ? t("لغو انتخاب") : t("انتخاب همه");
  }
  $$(".media-card", UI.dlList).forEach((card) => {
    const input = $('input[type="checkbox"]', card);
    card.classList.toggle("selected", Boolean(input && input.checked));
  });
}

function resetDlList() {
  dlItems = [];
  renderMediaList();
}

/* ---------------------------------------------------------------- probe */
function renderProbeResult(probe) {
  if (!UI.dlProbeResult) return;
  if (!probe) {
    UI.dlProbeResult.classList.add("hidden");
    UI.dlProbeResult.innerHTML = "";
    return;
  }
  const typeLabel = {
    channel: probe.live ? "کانال لایو" : "کانال آفلاین",
    vod: "ویدیو (VOD)",
    clip: "کلیپ",
    direct: "لینک مستقیم",
  }[probe.type] || "رسانه";
  const channel = probe.channel || {};
  const image = probe.thumbnail || channel.avatar || "";
  const tags = [`<span class="probe-tag ${probe.live ? "green" : ""}">${esc(typeLabel)}</span>`];
  if (Array.isArray(probe.variants) && probe.variants.length) {
    tags.push(`<span class="probe-tag green">${fmtCount(probe.variants.length)} ${t("کیفیت‌ها")}</span>`);
  }
  if (probe.duration_text) tags.push(`<span class="probe-tag">${esc(probe.duration_text)}</span>`);
  if (probe.has_dvr) tags.push('<span class="probe-tag green">DVR</span>');
  if (channel.username) tags.push(`<span class="probe-tag" dir="ltr">@${esc(channel.username)}</span>`);
  if (channel.categories && channel.categories.length) {
    const sep = currentLanguage() === "en" ? ", " : "، ";
    tags.push(`<span class="probe-tag">${esc(channel.categories.join(sep))}</span>`);
  }

  UI.dlProbeResult.innerHTML =
    '<div class="probe-head">' +
    (image ? `<img src="${escAttr(imgSrc(image))}" alt="">` : "") +
    '<div class="probe-info"><h4>' +
    `${esc(probe.title || "رسانه Kick")}</h4><p>${
      probe.live ? "این کانال همین حالا لایو است" : "برای دانلود آماده است"
    }</p></div></div>` +
    `<div class="probe-tags">${tags.join("")}</div>`;
  UI.dlProbeResult.classList.remove("hidden");
}

/* ----------------------------------------------------------------- logs */
const LEVEL_LABEL = { info: "INFO", success: "OK", warn: "WARN", error: "ERROR" };

function renderLogs() {
  if (!UI.logList) return;
  const entries = logState.entries;
  if (!entries.length) {
    UI.logList.innerHTML = emptyBlock("گزارشی برای نمایش وجود ندارد.", "i-logs", true);
    return;
  }
  const previousTop = UI.logList.scrollTop;
  const atBottom =
    UI.logList.scrollHeight - UI.logList.scrollTop - UI.logList.clientHeight < 48;
  UI.logList.innerHTML = entries
    .map(
      (entry) =>
        `<div class="log-line ${esc(entry.level || "info")}">` +
        `<span class="ts">${esc(entry.time || "")}</span>` +
        `<span class="lvl">${esc(LEVEL_LABEL[entry.level] || "INFO")}</span>` +
        `<span class="src">[${esc(entry.source || "app")}]</span>` +
        `<span class="msg">${esc(entry.message || "")}</span></div>`
    )
    .join("");
  if (UI.logAutoscroll && UI.logAutoscroll.checked && atBottom) {
    UI.logList.scrollTop = UI.logList.scrollHeight;
  } else {
    UI.logList.scrollTop = previousTop;
  }
}

async function loadLogs(reset = false) {
  if (logsLoading || !UI.logList) return;
  logsLoading = true;
  try {
    const level = UI.logFilter ? UI.logFilter.value : "all";
    const query = new URLSearchParams({ limit: "800", level });
    const data = await api(`/api/logs?${query.toString()}`);
    logState.entries = data.logs || [];
    renderLogs();
    if (reset && UI.logList) UI.logList.scrollTop = UI.logList.scrollHeight;
  } catch (error) {
    if (reset) showError(error);
  } finally {
    logsLoading = false;
  }
}
/* ---------------------------------------------------------- page & live */
function pageFromHash() {
  const page = (location.hash || "").replace(/^#/, "").trim();
  return PAGE_META[page] ? page : "live";
}

function activatePage(page, silent = false) {
  if (!PAGE_META[page]) page = "live";
  activePage = page;
  $$(".nav-item[data-page]").forEach((item) => {
    item.classList.toggle("active", item.dataset.page === page);
  });
  $$(".page").forEach((section) => {
    section.classList.toggle("active", section.id === `page-${page}`);
  });
  const meta = PAGE_META[page];
  if (UI.pageEyebrow) UI.pageEyebrow.textContent = t(meta.eyebrow);
  if (UI.pageTitle) UI.pageTitle.textContent = t(meta.title);
  if (UI.pageSubtitle) UI.pageSubtitle.textContent = t(meta.subtitle);
  if (!silent) {
    try {
      history.replaceState(null, "", `#${page}`);
    } catch {
      /* ignore */
    }
    const content = $(".content");
    if (content) content.scrollTop = 0;
  }
  if (page === "logs") loadLogs(true);
}

async function probeLive() {
  const url = UI.liveUrl.value.trim();
  if (!url) {
    toast("لینک کانال را وارد کنید.", "warn");
    return;
  }
  await withLoading(UI.liveProbeBtn, async () => {
    try {
      const probe = await api("/api/probe", { url });
      if (probe.type !== "channel") {
        resetLivePreview();
        toast("این لینک کانال نیست. برای VOD و کلیپ از صفحه دانلود استفاده کنید.", "info");
        return;
      }
      liveProbeUrl = url;
      renderLivePreview(probe);
      if (probe.live) toast("کانال لایو است و آماده ضبط می‌باشد.", "success");
      else toast("این کانال الان لایو نیست.", "warn");
    } catch (error) {
      resetLivePreview();
      showError(error);
    }
  });
  updateLiveStartState();
}

async function startLive() {
  const url = UI.liveUrl.value.trim();
  if (!url) return;
  if (!liveProbe || !liveProbe.live || liveProbeUrl !== url) {
    toast("ابتدا کانال را دوباره بررسی کنید.", "warn");
    return;
  }
  const body = {
    url,
    source: sourceFromSelect(UI.liveSource, liveVariants),
    output: profileControls.live ? profileControls.live.get() : BASE_PROFILE,
    folder: UI.liveFolder.value.trim(),
    from_start: liveStartMode === "start",
  };
  await withLoading(UI.liveStart, async () => {
    try {
      await api("/api/live/start", body);
      toast("ضبط زنده آغاز شد.", "success");
      await refreshState();
    } catch (error) {
      showError(error);
    }
  });
  updateLiveStartState();
}

async function stopLiveSession(id) {
  try {
    await api("/api/live/stop", { id });
    toast("درخواست توقف ثبت شد؛ در حال نهایی‌سازی فایل.", "info");
    await refreshState();
  } catch (error) {
    showError(error);
  }
}

function extractChannelSlug(text) {
  const line = splitLines(text)[0];
  if (!line) return null;
  const value = line.trim();
  if (/^[A-Za-z0-9_-]{1,64}$/.test(value)) return value.toLowerCase();
  try {
    const parsed = new URL(value.includes("://") ? value : `https://${value}`);
    if (!/(^|\.)kick\.com$/i.test(parsed.hostname)) return null;
    const parts = parsed.pathname.split("/").filter(Boolean);
    if (!parts.length) return null;
    const first = parts[0].toLowerCase();
    if (["video", "videos", "categories", "clips", "search", "auth", "dashboard"].includes(first)) {
      return null;
    }
    return first.replace(/[^A-Za-z0-9_-]/g, "").toLowerCase() || null;
  } catch {
    return null;
  }
}

/* ------------------------------------------------------------- downloads */
function switchDlTab(tab) {
  dlTab = tab === "clip" ? "clip" : "vod";
  $$("[data-dl-tab]").forEach((button) => {
    button.classList.toggle("active", button.dataset.dlTab === dlTab);
  });
  if (UI.dlRange) UI.dlRange.classList.toggle("hidden", dlTab !== "clip");
  dlProbe = null;
  dlVariants = [];
  renderProbeResult(null);
  fillSourceSelect(UI.dlSource, []);
  resetDlList();
}

async function probeDownload() {
  const lines = splitLines(UI.dlUrls.value);
  if (!lines.length) {
    toast("حداقل یک لینک وارد کنید.", "warn");
    return;
  }
  const url = lines[0];
  await withLoading(UI.dlProbeBtn, async () => {
    try {
      const probe = await api("/api/probe", { url });
      dlProbe = probe;
      dlVariants = Array.isArray(probe.variants) ? probe.variants : [];
      renderProbeResult(probe);
      if (dlVariants.length) fillSourceSelect(UI.dlSource, dlVariants);
      if (probe.type === "channel" && probe.live) {
        toast("این کانال لایو است؛ برای ضبط از صفحه «ضبط زنده» استفاده کنید.", "info");
      } else if (probe.live) {
        toast("این آیتم در حال پخش زنده است.", "info");
      } else {
        toast("لینک بررسی شد و آماده دانلود است.", "success");
      }
      if (lines.length > 1) {
        toast("فقط اولین لینک بررسی شد؛ بقیه هنگام دانلود بررسی می‌شوند.", "info");
      }
    } catch (error) {
      dlProbe = null;
      dlVariants = [];
      renderProbeResult(null);
      showError(error);
    }
  });
}

async function loadChannelList() {
  const slug = extractChannelSlug(UI.dlUrls.value);
  if (!slug) {
    toast("یک لینک کانال Kick وارد کنید تا فهرست بارگذاری شود.", "warn");
    return;
  }
  await withLoading(UI.dlLoadBtn, async () => {
    try {
      let data;
      if (dlTab === "clip") {
        data = await api("/api/channel/clips", {
          url: `https://kick.com/${slug}`,
          sort: "date",
          range: UI.dlRange ? UI.dlRange.value : "week",
          pages: 2,
        });
      } else {
        data = await api("/api/channel/vods", {
          url: `https://kick.com/${slug}`,
          limit: 60,
        });
      }
      dlItems = Array.isArray(data.items) ? data.items : [];
      renderMediaList();
      toast(
        dlItems.length
          ? t("{n} مورد از کانال بارگذاری شد.", { n: fmtCount(dlItems.length) })
          : "موردی برای این کانال پیدا نشد.",
        dlItems.length ? "success" : "info"
      );
    } catch (error) {
      showError(error);
    }
  });
}

async function startDownloads() {
  let items = selectedMedia();
  if (!items.length) {
    items = splitLines(UI.dlUrls.value).map((url) => ({ url }));
  }
  if (!items.length) {
    toast("یک لینک وارد کنید یا از فهرست کانال چند مورد انتخاب کنید.", "warn");
    return;
  }
  const body = {
    items,
    source: sourceFromSelect(UI.dlSource, dlVariants),
    output: profileControls.dl ? profileControls.dl.get() : BASE_PROFILE,
    folder: UI.dlFolder.value.trim(),
  };
  await withLoading(UI.dlStart, async () => {
    try {
      const data = await api("/api/downloads/start", body);
      toast(
        t("{n} دانلود در صف قرار گرفت.", { n: fmtCount((data.jobs || []).length) }),
        "success"
      );
      $$('input[type="checkbox"]', UI.dlList).forEach((input) => {
        input.checked = false;
      });
      updateSelectedCount();
      await refreshState();
    } catch (error) {
      showError(error);
    }
  });
}

function bindAdvancedToggle(button, panel) {
  if (!button || !panel) return;
  button.addEventListener("click", () => {
    const open = panel.classList.toggle("hidden");
    button.classList.toggle("open", !open);
  });
}
/* ---------------------------------------------------------------- auto */
async function addAutoStreamer() {
  const url = UI.autoUrl.value.trim();
  if (!url) {
    toast("لینک کانال را وارد کنید.", "warn");
    return;
  }
  await withLoading(UI.autoAdd, async () => {
    try {
      await api("/api/auto/add", {
        url,
        source: sourceFromFixed(UI.autoSource.value),
        output: profileControls.auto ? profileControls.auto.get() : BASE_PROFILE,
        folder: "",
      });
      UI.autoUrl.value = "";
      toast("استریمر به فهرست ضبط خودکار اضافه شد.", "success");
      await refreshState();
    } catch (error) {
      showError(error);
    }
  });
}

async function saveAutoGlobal() {
  const patch = {
    poll_interval: Math.max(10, Math.min(600, Number(UI.autoInterval.value) || 25)),
    session_gap: Math.max(10, Math.min(1800, Number(UI.autoGap.value) || 90)),
    max_auto_recordings: Math.max(1, Math.min(20, Number(UI.autoMax.value) || 3)),
  };
  await withLoading(UI.autoSaveGlobal, async () => {
    try {
      await api("/api/settings", patch);
      autoDirty = false;
      toast("تنظیمات ضبط خودکار ذخیره شد.", "success");
      await refreshState();
    } catch (error) {
      showError(error);
    }
  });
}

async function setAutoEnabled(enabled) {
  try {
    await api("/api/auto/enabled", { enabled });
    toast(enabled ? "ضبط خودکار فعال شد." : "ضبط خودکار غیرفعال شد.", enabled ? "success" : "info");
    await refreshState();
  } catch (error) {
    showError(error);
  }
}

async function removeAutoStreamer(id) {
  const item = ((appState && appState.auto && appState.auto.streamers) || []).find(
    (entry) => String(entry.id) === String(id)
  );
  const ok = await confirmDialog({
    title: "حذف از ضبط خودکار",
    message: t("«{name}» از فهرست حذف شود؟ ضبط فعال آن نیز متوقف می‌شود.", {
      name: item ? item.name || item.slug : id,
    }),
    confirmLabel: "حذف",
    danger: true,
  });
  if (!ok) return;
  try {
    await api("/api/auto/remove", { id });
    toast("استریمر از فهرست حذف شد.", "success");
    await refreshState();
  } catch (error) {
    showError(error);
  }
}

function bindAuto() {
  UI.autoEnabled.addEventListener("change", () => setAutoEnabled(UI.autoEnabled.checked));
  UI.autoAdd.addEventListener("click", addAutoStreamer);
  UI.autoUrl.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      addAutoStreamer();
    }
  });
  UI.autoSaveGlobal.addEventListener("click", saveAutoGlobal);
  UI.autoCheck.addEventListener("click", async () => {
    try {
      await api("/api/auto/check", {});
      toast("بررسی فوری استریمرها آغاز شد.", "info");
      await refreshState();
    } catch (error) {
      showError(error);
    }
  });

  [UI.autoInterval, UI.autoGap, UI.autoMax].forEach((input) => {
    if (input) input.addEventListener("input", () => (autoDirty = true));
  });

  UI.autoList.addEventListener("click", async (event) => {
    const edit = event.target.closest("[data-auto-edit]");
    if (edit) {
      openAutoEdit(edit.dataset.autoEdit);
      return;
    }
    const remove = event.target.closest("[data-auto-remove]");
    if (remove) {
      removeAutoStreamer(remove.dataset.autoRemove);
      return;
    }
    const folder = event.target.closest("[data-auto-folder]");
    if (folder) {
      const id = folder.dataset.autoFolder;
      const item = ((appState && appState.auto && appState.auto.streamers) || []).find(
        (entry) => String(entry.id) === String(id)
      );
      const path =
        (item && item.folder) || (appState && appState.settings && appState.settings.download_dir) || "";
      openPath(path);
      return;
    }
    const stop = event.target.closest("[data-auto-stop]");
    if (stop) {
      try {
        await api("/api/live/stop", { id: stop.dataset.autoStop });
        toast("ضبط خودکار این استریمر متوقف می‌شود.", "info");
        await refreshState();
      } catch (error) {
        showError(error);
      }
      return;
    }
    const restart = event.target.closest("[data-auto-restart]");
    if (restart) {
      try {
        await api("/api/auto/restart", { id: restart.dataset.autoRestart });
        toast("ضبط دوباره از ابتدا آغاز شد.", "success");
        await refreshState();
      } catch (error) {
        showError(error);
      }
    }
  });

  UI.autoList.addEventListener("change", async (event) => {
    const toggle = event.target.closest("[data-auto-toggle]");
    if (!toggle) return;
    try {
      await api("/api/auto/update", { id: toggle.dataset.autoToggle, enabled: toggle.checked });
      toast(toggle.checked ? "استریمر فعال شد." : "استریمر غیرفعال شد.", "info");
      await refreshState();
    } catch (error) {
      showError(error);
      await refreshState();
    }
  });
}

/* ------------------------------------------------------------ settings */
function setHint(element, text, timeout = 4200) {
  if (!element) return;
  element.textContent = text;
  if (element._hintTimer) clearTimeout(element._hintTimer);
  element._hintTimer = setTimeout(() => {
    element.textContent = "";
  }, timeout);
}

async function saveSettings() {
  const cookieRaw = UI.setCookie.value.trim();
  const patch = {
    download_dir: UI.setDownloadDir.value.trim(),
    ffmpeg_path: UI.setFfmpeg.value.trim(),
    max_downloads: Math.max(1, Math.min(8, Number(UI.setMaxDownloads.value) || 2)),
    keep_parts: Boolean(UI.setKeepParts.checked),
    default_output: profileControls.set ? profileControls.set.get() : BASE_PROFILE,
  };
  if (!patch.download_dir) delete patch.download_dir;
  if (cookieRaw) patch.kick_cookie = cookieRaw === "clear" ? "" : cookieRaw;

  await withLoading(UI.setSave, async () => {
    try {
      const data = await api("/api/settings", patch);
      settingsDirty = false;
      UI.setCookie.value = "";
      applySettings(data.settings, true);
      applyTools(data.tools);
      setHint(UI.settingsSaveHint, "تنظیمات با موفقیت ذخیره شد.");
      toast("تنظیمات ذخیره شد.", "success");
      await refreshState();
    } catch (error) {
      showError(error);
    }
  });
}

async function installFfmpeg() {
  if (appState && appState.tools && appState.tools.ok) {
    toast("FFmpeg از قبل آماده است.", "info");
    return;
  }
  if (installPending) {
    toast("نصب FFmpeg در حال انجام است.", "info");
    return;
  }
  await withLoading(UI.ffmpegInstall, async () => {
    try {
      await api("/api/tools/install-ffmpeg", {});
      installPending = true;
      toast("دانلود FFmpeg آغاز شد؛ پیشرفت در همین صفحه نمایش داده می‌شود.", "info");
      await refreshState();
    } catch (error) {
      showError(error);
    }
  });
}

function bindSettings() {
  UI.setSave.addEventListener("click", saveSettings);
  UI.ffmpegInstall.addEventListener("click", installFfmpeg);
  UI.setOpenFolder.addEventListener("click", () => {
    const path =
      UI.setDownloadDir.value.trim() ||
      (appState && appState.settings && appState.settings.download_dir) ||
      "";
    openPath(path);
  });

  [UI.setDownloadDir, UI.setFfmpeg, UI.setMaxDownloads, UI.setKeepParts, UI.setCookie].forEach(
    (input) => {
      if (!input) return;
      input.addEventListener("input", () => (settingsDirty = true));
      input.addEventListener("change", () => (settingsDirty = true));
    }
  );
}

/* ------------------------------------------------------------ language */
function applyLanguage(code, options = {}) {
  const next = setLanguage(code);
  if (UI.langSwitch) {
    $$("[data-lang]", UI.langSwitch).forEach((button) => {
      const active = button.dataset.lang === next;
      button.classList.toggle("active", active);
      button.setAttribute("aria-pressed", active ? "true" : "false");
    });
  }
  if (options.refresh !== false) refreshLocalizedUi();
  return next;
}

function refreshLocalizedUi() {
  activatePage(activePage, true);
  Object.keys(profileControls).forEach((key) => {
    const control = profileControls[key];
    if (control && typeof control.refresh === "function") control.refresh();
  });
  if (appState) {
    applySettings(appState.settings, false);
    applyTools(appState.tools);
    applyStats(appState.stats, appState);
    renderSessions();
    renderDownloads();
    renderAuto();
  }
  renderMediaList();
  renderProbeResult(dlProbe);
  if (liveProbe) renderLivePreview(liveProbe);
  else syncStartModeUi();
  updateLiveStartState();
  updateConnectionUi();
  renderLogs();
}

function changeLanguage(code) {
  const next = applyLanguage(code);
  if (appState && appState.settings) appState.settings.language = next;
  api("/api/settings", { language: next }).catch(() => {
    /* the local choice is already applied */
  });
}

function bindLanguage() {
  if (!UI.langSwitch) return;
  UI.langSwitch.addEventListener("click", (event) => {
    const button = event.target.closest("[data-lang]");
    if (!button) return;
    const code = button.dataset.lang;
    if (!code || code === currentLanguage()) return;
    changeLanguage(code);
  });
}

/* ---------------------------------------------------------------- logs */
function bindLogs() {
  UI.logFilter.addEventListener("change", () => loadLogs(true));
  UI.logAutoscroll.addEventListener("change", () => {
    if (UI.logAutoscroll.checked && UI.logList) UI.logList.scrollTop = UI.logList.scrollHeight;
  });
  UI.logClear.addEventListener("click", async () => {
    try {
      await api("/api/logs/clear", {});
      logState.entries = [];
      renderLogs();
      toast("گزارش‌ها پاک شد.", "success");
    } catch (error) {
      showError(error);
    }
  });
}

/* --------------------------------------------------------------- global */
function cacheElements() {
  UI.topStatus = $("#top-status");
  UI.pageEyebrow = $("#page-eyebrow");
  UI.pageTitle = $("#page-title");
  UI.pageSubtitle = $("#page-subtitle");
  UI.btnRefresh = $("#btn-refresh");
  UI.btnOpenDownloads = $("#btn-open-downloads");
  UI.toolChip = $("#tool-chip");
  UI.toolChipTitle = $("#tool-chip-title");
  UI.toolChipSub = $("#tool-chip-sub");
  UI.navAutoCount = $("#nav-auto-count");
  UI.langSwitch = $("#lang-switch");

  UI.liveUrl = $("#live-url");
  UI.liveProbeBtn = $("#live-probe");
  UI.livePreview = $("#live-preview");
  UI.liveAvatar = $("#live-avatar");
  UI.liveName = $("#live-name");
  UI.liveStreamTitle = $("#live-stream-title");
  UI.liveViewers = $("#live-viewers");
  UI.liveTime = $("#live-time");
  UI.liveCategory = $("#live-category");
  UI.liveDvrBadge = $("#live-dvr-badge");
  UI.liveOffline = $("#live-offline");
  UI.liveOfflineTitle = $("#live-offline-title");
  UI.liveSource = $("#live-source");
  UI.liveProfile = $("#live-profile");
  UI.liveProfileSummary = $("#live-profile-summary");
  UI.liveAdvancedToggle = $("#live-advanced-toggle");
  UI.liveAdvanced = $("#live-advanced");
  UI.liveFolder = $("#live-folder");
  UI.liveStartMode = $("#live-start-mode");
  UI.liveStartModeHint = $("#live-start-mode-hint");
  UI.liveStart = $("#live-start");
  UI.liveStartHint = $("#live-start-hint");
  UI.liveSessions = $("#live-sessions");
  UI.liveClear = $("#live-clear");
  UI.statFfmpeg = $("#stat-ffmpeg");
  UI.statActive = $("#stat-active");
  UI.statAuto = $("#stat-auto");
  UI.statSpace = $("#stat-space");

  UI.dlUrls = $("#dl-urls");
  UI.dlProbeBtn = $("#dl-probe");
  UI.dlLoadBtn = $("#dl-load");
  UI.dlRange = $("#dl-range");
  UI.dlSelectAll = $("#dl-select-all");
  UI.dlSelected = $("#dl-selected");
  UI.dlStart = $("#dl-start");
  UI.dlProbeResult = $("#dl-probe-result");
  UI.dlList = $("#dl-list");
  UI.dlSource = $("#dl-source");
  UI.dlProfile = $("#dl-profile");
  UI.dlProfileSummary = $("#dl-profile-summary");
  UI.dlAdvancedToggle = $("#dl-advanced-toggle");
  UI.dlAdvanced = $("#dl-advanced");
  UI.dlFolder = $("#dl-folder");
  UI.dlClear = $("#dl-clear");
  UI.downloadsList = $("#downloads-list");

  UI.autoEnabled = $("#auto-enabled");
  UI.autoUrl = $("#auto-url");
  UI.autoSource = $("#auto-source");
  UI.autoProfile = $("#auto-profile");
  UI.autoAdd = $("#auto-add");
  UI.autoList = $("#auto-list");
  UI.autoActivity = $("#auto-activity");
  UI.autoInterval = $("#auto-interval");
  UI.autoGap = $("#auto-gap");
  UI.autoMax = $("#auto-max");
  UI.autoSaveGlobal = $("#auto-save-global");
  UI.autoCheck = $("#auto-check");
  UI.autoMeta = $("#auto-meta");

  UI.setDownloadDir = $("#set-download-dir");
  UI.setOpenFolder = $("#set-open-folder");
  UI.setFfmpeg = $("#set-ffmpeg");
  UI.ffmpegInstall = $("#ffmpeg-install");
  UI.ffmpegStatus = $("#ffmpeg-status");
  UI.ffmpegProgress = $("#ffmpeg-progress");
  UI.setMaxDownloads = $("#set-max-downloads");
  UI.setProfile = $("#set-profile");
  UI.setKeepParts = $("#set-keep-parts");
  UI.setCookie = $("#set-cookie");
  UI.setCookieHint = $("#set-cookie-hint");
  UI.setSave = $("#set-save");
  UI.settingsSaveHint = $("#settings-save-hint");
  UI.infoVersion = $("#info-version");
  UI.infoFfmpeg = $("#info-ffmpeg");
  UI.infoEncoders = $("#info-encoders");
  UI.infoDownloadDir = $("#info-download-dir");
  UI.infoSpace = $("#info-space");

  UI.logFilter = $("#log-filter");
  UI.logAutoscroll = $("#log-autoscroll");
  UI.logClear = $("#log-clear");
  UI.logList = $("#log-list");
}

function bindNavigation() {
  $$(".nav-item[data-page]").forEach((item) => {
    item.addEventListener("click", () => activatePage(item.dataset.page));
  });
  window.addEventListener("hashchange", () => activatePage(pageFromHash(), true));
}

function bindLive() {
  UI.liveProbeBtn.addEventListener("click", probeLive);
  UI.liveUrl.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      probeLive();
    }
  });
  UI.liveUrl.addEventListener("input", updateLiveStartState);
  UI.liveStart.addEventListener("click", startLive);
  UI.liveFolder.addEventListener("input", () => (folderTouched.live = true));
  if (UI.liveStartMode) {
    UI.liveStartMode.addEventListener("click", (event) => {
      const button = event.target.closest("[data-start-mode]");
      if (!button || button.disabled) return;
      liveStartMode = button.dataset.startMode === "now" ? "now" : "start";
      syncStartModeUi();
      updateLiveStartState();
    });
  }
  bindAdvancedToggle(UI.liveAdvancedToggle, UI.liveAdvanced);
  UI.liveClear.addEventListener("click", async () => {
    const ok = await confirmDialog({
      title: "پاک کردن تاریخچه ضبط",
      message: "تمام ضبط‌های پایان‌یافته از فهرست حذف می‌شوند. فایل‌های ذخیره‌شده حذف نمی‌شوند.",
      confirmLabel: "پاک کن",
      danger: true,
    });
    if (!ok) return;
    try {
      await api("/api/live/clear", {});
      toast("تاریخچه ضبط پاک شد.", "success");
      await refreshState();
    } catch (error) {
      showError(error);
    }
  });
  UI.liveSessions.addEventListener("click", async (event) => {
    const open = event.target.closest("[data-open-path]");
    if (open) {
      openPath(open.dataset.openPath);
      return;
    }
    const stop = event.target.closest("[data-session-stop]");
    if (stop) stopLiveSession(stop.dataset.sessionStop);
  });
}

function bindDownload() {
  $$("[data-dl-tab]").forEach((button) => {
    button.addEventListener("click", () => switchDlTab(button.dataset.dlTab));
  });
  UI.dlProbeBtn.addEventListener("click", probeDownload);
  UI.dlLoadBtn.addEventListener("click", loadChannelList);
  UI.dlStart.addEventListener("click", startDownloads);
  UI.dlFolder.addEventListener("input", () => (folderTouched.dl = true));
  UI.dlList.addEventListener("change", updateSelectedCount);
  UI.dlSelectAll.addEventListener("click", () => {
    const inputs = $$('input[type="checkbox"]', UI.dlList);
    const selectAll = inputs.some((input) => !input.checked);
    inputs.forEach((input) => (input.checked = selectAll));
    updateSelectedCount();
  });
  UI.dlRange.addEventListener("change", () => {
    if (dlTab === "clip" && dlItems.length) loadChannelList();
  });
  UI.dlClear.addEventListener("click", async () => {
    const ok = await confirmDialog({
      title: "پاک کردن تاریخچه دانلود",
      message: "تمام دانلودهای پایان‌یافته از فهرست حذف می‌شوند. فایل‌های ذخیره‌شده حذف نمی‌شوند.",
      confirmLabel: "پاک کن",
      danger: true,
    });
    if (!ok) return;
    try {
      await api("/api/downloads/clear", {});
      toast("تاریخچه دانلود پاک شد.", "success");
      await refreshState();
    } catch (error) {
      showError(error);
    }
  });
  UI.downloadsList.addEventListener("click", async (event) => {
    const open = event.target.closest("[data-open-path]");
    if (open) {
      openPath(open.dataset.openPath);
      return;
    }
    const stop = event.target.closest("[data-download-stop]");
    if (stop) {
      try {
        await api("/api/downloads/stop", { id: stop.dataset.downloadStop });
        toast("درخواست توقف دانلود ثبت شد.", "info");
        await refreshState();
      } catch (error) {
        showError(error);
      }
    }
  });
  bindAdvancedToggle(UI.dlAdvancedToggle, UI.dlAdvanced);
}

function bindGlobal() {
  UI.btnRefresh.addEventListener("click", () =>
    withLoading(UI.btnRefresh, async () => {
      await refreshState();
      toast("همه‌چیز به‌روز شد.", "info");
    })
  );
  UI.btnOpenDownloads.addEventListener("click", () => {
    const path =
      (appState && appState.stats && appState.stats.download_dir) ||
      (appState && appState.settings && appState.settings.download_dir) ||
      "";
    openPath(path);
  });

  $$("[data-choose]").forEach((button) => {
    button.addEventListener("click", async () => {
      const target = document.getElementById(button.dataset.choose);
      if (!target) return;
      const path = await chooseFolder(target.value);
      if (path) {
        target.value = path;
        target.dispatchEvent(new Event("input", { bubbles: true }));
        target.dispatchEvent(new Event("change", { bubbles: true }));
      }
    });
  });

  document.addEventListener(
    "error",
    (event) => {
      const img = event.target;
      if (img && img.tagName === "IMG" && !img.dataset.fallback) {
        img.dataset.fallback = "1";
        img.src = EMPTY_IMG;
      }
    },
    true
  );
}

function init() {
  applyLanguage(currentLanguage(), { refresh: false });
  cacheElements();
  initProfileControls();
  bindNavigation();
  bindLive();
  bindDownload();
  bindAuto();
  bindSettings();
  bindLanguage();
  bindLogs();
  bindGlobal();
  renderMediaList();
  renderProbeResult(null);
  activatePage(pageFromHash(), true);
  refreshState();

  setInterval(() => {
    if (!document.hidden) refreshState();
  }, 1200);

  setInterval(() => {
    if (!document.hidden && activePage === "logs") loadLogs();
  }, 2400);

  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) refreshState();
  });
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", init);
} else {
  init();
}







