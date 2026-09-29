/**
 * Renders the PWA / favicon PNGs from the brand mark in components/brand/Logo.jsx.
 *
 *   node scripts/render-icons.mjs
 *
 * Uses Playwright's headless Chromium (already a dev dependency) as the SVG rasteriser.
 * "any" icons are the rounded tile on transparency; maskable and Apple icons are full-bleed
 * with the tooth kept inside the maskable safe zone.
 */
import { readFileSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { chromium } from "@playwright/test";

const root = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const logoSrc = readFileSync(path.join(root, "components/brand/Logo.jsx"), "utf8");
const pick = (name) => new RegExp(`export const ${name} =\\s*"([^"]+)"`).exec(logoSrc)[1];
const TOOTH = pick("TOOTH_PATH");
const SPARK = pick("SPARK_PATH");
const SHINE = pick("SHINE_PATH");

/** @param {{bleed:boolean, scale:number}} o */
function svg({ bleed, scale }) {
  const t = (64 - 64 * scale) / 2;
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" width="100%" height="100%">
    <defs><linearGradient id="g" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#3b82f6"/><stop offset="1" stop-color="#1d4ed8"/>
    </linearGradient></defs>
    <rect width="64" height="64" rx="${bleed ? 0 : 17}" fill="url(#g)"/>
    <g transform="translate(${t} ${t}) scale(${scale})">
      <path d="${TOOTH}" fill="#fff" stroke="#fff" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="${SHINE}" fill="none" stroke="#93b4f5" stroke-width="2.4" stroke-linecap="round"/>
      <path d="${SPARK}" fill="#fff" stroke="#377bf2" stroke-width="2.4" paint-order="stroke"/>
    </g>
  </svg>`;
}

const OUT = [
  ["public/icons/icon-192.png", 192, { bleed: false, scale: 0.82 }],
  ["public/icons/icon-512.png", 512, { bleed: false, scale: 0.82 }],
  ["public/icons/maskable-192.png", 192, { bleed: true, scale: 0.66 }],
  ["public/icons/maskable-512.png", 512, { bleed: true, scale: 0.66 }],
  ["public/icons/apple-touch-icon.png", 180, { bleed: true, scale: 0.74 }],
  ["public/favicon-32.png", 32, { bleed: false, scale: 0.9 }],
];

const browser = await chromium.launch();
const page = await browser.newPage();
for (const [file, size, opts] of OUT) {
  await page.setViewportSize({ width: size, height: size });
  await page.setContent(
    `<html><body style="margin:0;background:transparent">${svg(opts)}</body></html>`
  );
  const png = await page.screenshot({ omitBackground: true, clip: { x: 0, y: 0, width: size, height: size } });
  writeFileSync(path.join(root, file), png);
  console.log("wrote", file);
}
await browser.close();
