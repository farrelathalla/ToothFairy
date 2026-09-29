/**
 * Structure for the advisory documents (diagnosis / recommendation markdown).
 *
 * The advisory agent writes one long markdown document per kind: an `# H1`, an optional intro,
 * then `## ` sections, with GFM footnote citations (`[^1]`) whose definitions — source title,
 * link, and the verbatim quotes `citations.py` verified — sit under a closing `## Rujukan`.
 *
 * This splits that into sections the results screen can page through, and recognises a few
 * shapes worth presenting better than prose — per-tooth tables, per-tooth paragraphs, the
 * visit sequence. Nothing is summarised or dropped: every table cell, paragraph and quote in
 * the source reaches the screen; only its layout changes. Anything unrecognised stays plain
 * markdown.
 */

const H1 = /^#\s+(.+?)\s*$/;
const H2 = /^##\s+(.+?)\s*$/;
const FOOTNOTE_DEF = /^\[\^([^\]\s]+)\]:\s?(.*)$/;
const SOURCES_TITLE = /^(rujukan|referensi|sumber|daftar pustaka)\b/i;
const ALERT_TITLE = /(tanda bahaya|red flag)/i;
const TOOTH_PARA = /^\*\*Gigi\s+(\d{2})\b([^*]*)\*\*\s*[—–:-]?\s*([\s\S]*)$/;
const VISIT_ITEM = /^\d+\.\s+\*\*(.+?)\*\*\s*([\s\S]*)$/;

/** URL-safe id for a section title. */
export function slug(text) {
  return String(text)
    .toLowerCase()
    .normalize("NFKD")
    .replace(/[̀-ͯ]/g, "")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

/** `[^n]` → `[n](#cite-n)`, which the renderers turn into a tappable citation chip. */
export function linkCitations(md) {
  return md.replace(/\[\^([^\]\s]+)\](?!:)/g, "[$1](#cite-$1)");
}

/** Splits a table row on unescaped pipes, trimming the outer ones. */
function cells(row) {
  const out = [];
  let cur = "";
  const s = row.trim().replace(/^\|/, "").replace(/\|$/, "");
  for (let i = 0; i < s.length; i++) {
    if (s[i] === "\\" && s[i + 1] === "|") {
      cur += "|";
      i++;
    } else if (s[i] === "|") {
      out.push(cur.trim());
      cur = "";
    } else cur += s[i];
  }
  out.push(cur.trim());
  return out;
}

const isTableLine = (l) => /^\s*\|.*\|\s*$/.test(l);
const isDivider = (l) => /^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?\s*$/.test(l);

/**
 * Source definition → { id, title, meta, url, quotes }.
 * First line looks like `**Title** — https://…`, `**Title** — DOI: 10.x/y` or `— URL: …`;
 * the indented `> …` lines under it are the verified verbatim quotes.
 */
function parseSource(id, lines) {
  const first = lines[0] || "";
  const bold = /\*\*(.+?)\*\*/.exec(first);
  const title = bold ? bold[1] : first.replace(/[—–-]\s.*$/, "").trim();
  const meta = (bold ? first.slice(bold.index + bold[0].length) : "").replace(/^\s*[—–-]\s*/, "").trim();
  const http = /(https?:\/\/[^\s)>\]]+)/.exec(meta);
  const doi = /\bDOI:?\s*(10\.\S+)/i.exec(meta);
  const url = http ? http[1] : doi ? `https://doi.org/${doi[1]}` : null;

  // One `>` line per verified quote (that is how citations.py writes them).
  const quotes = lines
    .slice(1)
    .map((raw) => raw.trim().replace(/^>\s?/, "").trim())
    .filter(Boolean);
  return { id, title, meta, url, quotes };
}

/** Pulls every footnote definition (and its indented continuation) out of the text. */
function extractSources(lines) {
  const kept = [];
  const sources = [];
  for (let i = 0; i < lines.length; i++) {
    const m = FOOTNOTE_DEF.exec(lines[i]);
    if (!m) {
      kept.push(lines[i]);
      continue;
    }
    const body = [m[2]];
    while (i + 1 < lines.length) {
      const next = lines[i + 1];
      if (/^(?: {2,}|\t)\S/.test(next)) body.push(next);
      else if (next.trim() === "" && /^(?: {2,}|\t)\S/.test(lines[i + 2] || "")) body.push(next);
      else break;
      i++;
    }
    sources.push(parseSource(m[1], body));
  }
  return { lines: kept, sources };
}

/** A section's table whose first column is the tooth → header + rows, plus the text around it. */
function findToothTable(body) {
  const lines = body.split("\n");
  const start = lines.findIndex((l, i) => isTableLine(l) && isDivider(lines[i + 1] || ""));
  if (start < 0) return null;
  const header = cells(lines[start]);
  if (!/^gigi/i.test(header[0] || "")) return null;
  let end = start + 2;
  while (end < lines.length && isTableLine(lines[end])) end++;
  const rows = lines.slice(start + 2, end).map((r) => {
    const c = cells(r);
    while (c.length < header.length) c.push("");
    return c.slice(0, header.length);
  });
  return {
    header,
    rows,
    before: lines.slice(0, start).join("\n").trim(),
    after: lines.slice(end).join("\n").trim(),
  };
}

/** Paragraphs led by `**Gigi 21 (…)**` → one note per tooth; other paragraphs kept around them. */
function findToothNotes(body) {
  const paras = body.split(/\n\s*\n/).map((p) => p.trim()).filter(Boolean);
  const notes = [];
  const before = [];
  const after = [];
  for (const p of paras) {
    const m = TOOTH_PARA.exec(p);
    if (m) notes.push({ fdi: Number(m[1]), label: `Gigi ${m[1]}${m[2]}`.trim(), text: m[3].trim() });
    else (notes.length ? after : before).push(p);
  }
  if (notes.length < 2) return null;
  return { notes, before: before.join("\n\n"), after: after.join("\n\n") };
}

/** An ordered list whose items open with a bold "Kunjungan …" → a visit timeline. */
function findVisits(body) {
  const lines = body.split("\n");
  const items = [];
  const before = [];
  const after = [];
  let cur = null;
  for (const l of lines) {
    const m = VISIT_ITEM.exec(l.trim());
    if (m && /^kunjungan/i.test(m[1])) {
      if (cur) items.push(cur);
      cur = { title: m[1].replace(/[:：]\s*$/, ""), text: m[2].trim() };
    } else if (cur && l.trim() && /^\s{2,}\S/.test(l)) {
      cur.text += " " + l.trim();
    } else if (cur && l.trim() === "") {
      // blank line inside/after the list
    } else if (l.trim()) {
      if (cur) {
        items.push(cur);
        cur = null;
      }
      (items.length ? after : before).push(l);
    }
  }
  if (cur) items.push(cur);
  if (items.length < 2) return null;
  return { items, before: before.join("\n").trim(), after: after.join("\n").trim() };
}

/**
 * @param {string} markdown
 * @returns {{ title: string|null, intro: string, sections: Array<{id:string,title:string,body:string,kind:string,data?:object}>, sources: Array<{id:string,title:string,meta:string,url:string|null,quotes:string[]}> }}
 */
export function parseReport(markdown) {
  const { lines, sources } = extractSources(String(markdown || "").replace(/\r\n?/g, "\n").split("\n"));

  let title = null;
  const intro = [];
  const sections = [];
  let cur = null;

  for (const line of lines) {
    const h2 = H2.exec(line);
    const h1 = !h2 && H1.exec(line);
    if (h1 && title === null && !cur) {
      title = h1[1];
      continue;
    }
    if (h2) {
      cur = { title: h2[1], lines: [] };
      sections.push(cur);
      continue;
    }
    (cur ? cur.lines : intro).push(line);
  }

  const used = new Set();
  const out = sections.map((s) => {
    const body = linkCitations(s.lines.join("\n").trim());
    let id = slug(s.title) || "bagian";
    while (used.has(id)) id += "-2";
    used.add(id);

    if (SOURCES_TITLE.test(s.title)) return { id, title: s.title, body, kind: "sources" };
    const table = findToothTable(body);
    if (table) return { id, title: s.title, body, kind: "teeth-table", data: table };
    const notes = findToothNotes(body);
    if (notes) return { id, title: s.title, body, kind: "tooth-notes", data: notes };
    const visits = findVisits(body);
    if (visits) return { id, title: s.title, body, kind: "visits", data: visits };
    return { id, title: s.title, body, kind: ALERT_TITLE.test(s.title) ? "alert" : "markdown" };
  });

  // Sources with no "Rujukan" heading of their own still get a section.
  if (sources.length && !out.some((s) => s.kind === "sources")) {
    out.push({ id: "rujukan", title: "Rujukan", body: "", kind: "sources" });
  }

  return { title, intro: linkCitations(intro.join("\n").trim()), sections: out, sources };
}

/** Section index holding a given tooth (per-tooth table or notes), or -1. */
export function sectionForTooth(report, fdi) {
  const f = String(fdi);
  return report.sections.findIndex(
    (s) =>
      (s.kind === "teeth-table" && s.data.rows.some((r) => String(r[0]).replace(/\D/g, "") === f)) ||
      (s.kind === "tooth-notes" && s.data.notes.some((n) => String(n.fdi) === f))
  );
}
