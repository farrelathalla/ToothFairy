/**
 * Standalone mode — the app running with no backend reachable.
 *
 * ToothFairy ships as an installable PWA that clinics use on tablets and phones, often on
 * poor connectivity. This module lets the whole product be exercised from the browser alone:
 * it implements the same routes `lib/api.js` would call over HTTP, backed by `localStorage`,
 * and resolves results against the analysis datasets bundled in `public/results/`.
 *
 * It is enabled by `NEXT_PUBLIC_STANDALONE` (see `lib/api.js`) and is intentionally the only
 * place that knows about it — every screen, form and component is unchanged, which is what
 * makes this useful as a walkthrough of the real UI rather than a separate mock app.
 *
 * What it deliberately does *not* do: run the models. There is no inference in a browser, so
 * an analysis resolves to one of the bundled reference datasets and replays a realistic
 * progress sequence while it does.
 */

const USER_KEY = "tf_standalone_user";
const CASES_KEY = "tf_standalone_cases";

/** The bundled dataset a standalone analysis resolves to. */
const REFERENCE_DATASET = "set3";

/** Stages replayed while an analysis "runs", mirroring the real pipeline's reporting. */
const STAGES = [
  [8, "Menyiapkan gambar"],
  [24, "Deteksi FDI & segmentasi gigi"],
  [46, "Grading karies (RF-DETR ICDAS)"],
  [68, "Analisis panoramik (karies tersembunyi)"],
  [84, "Menyusun rekonstruksi 3D"],
  [94, "Menyusun diagnosis"],
  [100, "Selesai"],
];

/** How long the replayed analysis takes, in milliseconds. */
const RUN_DURATION = 7000;

class OfflineError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

// --- storage ---------------------------------------------------------------

function read(key, fallback) {
  try {
    const raw = localStorage.getItem(key);
    return raw ? JSON.parse(raw) : fallback;
  } catch {
    return fallback;
  }
}

function write(key, value) {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch {
    /* private browsing / quota */
  }
}

const readCases = () => read(CASES_KEY, []);
const writeCases = (cases) => write(CASES_KEY, cases);

/** Clears the local session and case history. */
export function reset() {
  try {
    localStorage.removeItem(USER_KEY);
    localStorage.removeItem(CASES_KEY);
  } catch {
    /* private browsing */
  }
}

// --- helpers ---------------------------------------------------------------

function newCaseId() {
  const stamp = new Date().toISOString().replace(/[-:T.]/g, "").slice(0, 14);
  return `case-${stamp}-${Math.random().toString(16).slice(2, 8)}`;
}

/** Derives a display name from an email local part: `budi.santoso` → `Budi Santoso`. */
function nameFromEmail(email) {
  const local = String(email || "").split("@")[0] || "Dokter";
  return (
    local
      .split(/[._-]+/)
      .filter(Boolean)
      .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
      .join(" ") || "Dokter"
  );
}

/** Advances a running case along the replayed stage timeline. */
function project(kase) {
  if (kase.status !== "running" || !kase.started_at) return kase;

  const elapsed = Date.now() - kase.started_at;
  const ratio = Math.min(1, elapsed / RUN_DURATION);
  const index = Math.min(STAGES.length - 1, Math.floor(ratio * STAGES.length));
  const [progress, stage] = STAGES[index];

  if (ratio >= 1) {
    return { ...kase, status: "done", progress: 100, stage: "Selesai" };
  }
  return { ...kase, progress, stage };
}

/** Reads a case, persisting any status transition the projection just made. */
function loadCase(id) {
  const cases = readCases();
  const index = cases.findIndex((c) => c.id === id);
  if (index < 0) throw new OfflineError("Kasus tidak ditemukan", 404);

  const projected = project(cases[index]);
  if (projected.status !== cases[index].status || projected.progress !== cases[index].progress) {
    cases[index] = projected;
    writeCases(cases);
  }
  return projected;
}

function saveCase(updated) {
  const cases = readCases();
  const index = cases.findIndex((c) => c.id === updated.id);
  if (index < 0) throw new OfflineError("Kasus tidak ditemukan", 404);
  cases[index] = updated;
  writeCases(cases);
  return updated;
}

/**
 * The advisory documents for the reference dataset, generated ahead of time and served as a
 * static asset so no key or network call is needed here.
 */
let advisoryPromise = null;
function loadAdvisory() {
  if (!advisoryPromise) {
    advisoryPromise = fetch("/standalone/advisory.json")
      .then((r) => (r.ok ? r.json() : {}))
      .catch(() => ({}));
  }
  return advisoryPromise;
}

async function withAdvisory(kase) {
  if (kase.status !== "done") return kase;
  const advisory = await loadAdvisory();
  return {
    ...kase,
    diagnosis_md: advisory.diagnosis_md ?? null,
    recommendation_md: advisory.recommendation_md ?? null,
    sanity_md: advisory.sanity_md ?? null,
  };
}

// --- routes ----------------------------------------------------------------

/**
 * Handles one request. Returns `undefined` for any route this module does not implement, so
 * the caller can fall through to a real network call.
 */
export async function handle(path, { method = "GET", body } = {}) {
  const route = path.split("?")[0];

  if (route === "/auth/login" && method === "POST") {
    const email = String(body?.email || "").trim();
    // Standalone mode has no account store to check against; any well-formed sign-in opens
    // a local session. Sessions and cases live only in this browser.
    const user = {
      id: 1,
      email,
      name: nameFromEmail(email),
      role: "doctor",
      is_active: true,
      created_at: new Date().toISOString(),
    };
    write(USER_KEY, user);
    return { token: "standalone", user };
  }

  if (route === "/auth/logout" && method === "POST") {
    try {
      localStorage.removeItem(USER_KEY);
    } catch {
      /* private browsing */
    }
    return { ok: true };
  }

  if (route === "/auth/me" && method === "GET") {
    const user = read(USER_KEY, null);
    if (!user) throw new OfflineError("Sesi tidak valid, silakan masuk kembali", 401);
    return user;
  }

  if (route === "/cases" && method === "GET") {
    return readCases().map(project);
  }

  if (route === "/cases" && method === "POST") {
    const now = new Date().toISOString();
    const kase = {
      id: newCaseId(),
      doctor_id: 1,
      patient_name: body?.patient_name?.trim() || null,
      anamnesa: body?.anamnesa || {},
      status: "draft",
      progress: 0,
      stage: null,
      dataset_id: null,
      error: null,
      diagnosis_md: null,
      recommendation_md: null,
      sanity_md: null,
      created_at: now,
      updated_at: now,
      images: [],
    };
    writeCases([kase, ...readCases()]);
    return kase;
  }

  const match = route.match(/^\/cases\/([^/]+)(\/[a-z]+)?$/);
  if (!match) return undefined;

  const [, id, action] = match;
  const kase = loadCase(id);

  if (!action && method === "GET") return withAdvisory(kase);

  if (action === "/status" && method === "GET") {
    return {
      status: kase.status,
      progress: kase.progress,
      stage: kase.stage,
      error: kase.error,
      dataset_id: kase.dataset_id,
    };
  }

  if (action === "/images" && method === "POST") {
    // Photos are not persisted: browser storage is far too small for clinical images, and
    // keeping them would leave identifiable data in localStorage.
    //
    // `images` therefore stays empty rather than carrying url-less rows. PatientPhotos treats
    // a non-empty list as the authoritative source and would render broken <img> tags for it;
    // leaving it empty is what makes the component fall back to the reference dataset's own
    // source photos, which is the only thing there is to show here.
    return saveCase({
      ...kase,
      status: kase.status === "draft" ? "uploaded" : kase.status,
      images: [],
      updated_at: new Date().toISOString(),
    });
  }

  if (action === "/run" && method === "POST") {
    saveCase({
      ...kase,
      status: "running",
      progress: 0,
      stage: STAGES[0][1],
      error: null,
      dataset_id: REFERENCE_DATASET,
      started_at: Date.now(),
      updated_at: new Date().toISOString(),
    });
    return { status: "queued", case_id: id };
  }

  if (!action && method === "DELETE") {
    writeCases(readCases().filter((c) => c.id !== id));
    return null;
  }

  return undefined;
}
