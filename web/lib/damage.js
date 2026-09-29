import * as THREE from "three";
import { MeshBVH } from "three-mesh-bvh";

// ICDAS D0..D6 -> visual appearance (enamel white -> brown -> black necrotic)
export const ICDAS_COLORS = [
  "#ece2cf", // D0 healthy enamel
  "#e4d7b6", // D1 first visual change (white/brown spot)
  "#d3bd8e", // D2 distinct change
  "#b2905a", // D3 localized enamel breakdown
  "#835f34", // D4 dark shadow from dentine
  "#4f371f", // D5 distinct cavity, exposed dentine
  "#241610", // D6 extensive cavity, gross destruction
];

export const ICDAS_LABEL = [
  "Healthy", "D1 · initial", "D2 · distinct", "D3 · enamel breakdown",
  "D4 · dentine shadow", "D5 · distinct cavity", "D6 · extensive cavity",
];

// how deep (fraction of crown height) and wide (fraction of crown width) the
// lesion eats, per ICDAS grade.
const DEPTH_FRAC = [0, 0.05, 0.12, 0.24, 0.40, 0.58, 0.78];
// lesion width per grade (fraction of crown width). Bold at D5/D6 so the whole
// occlusal/incisal surface is eaten (gross destruction), contained at low grades.
const RADIUS_FRAC = [0, 0.14, 0.22, 0.38, 0.55, 0.78, 0.98];
// surface roughening amplitude (fraction of crown width). Kept small + biased
// inward so decay reads as pitting/cavitation, not an explosion of spikes.
const JITTER_FRAC = [0, 0.004, 0.008, 0.016, 0.028, 0.042, 0.060];

// --- layered model (enamel/dentine/pulp nested solids) --------------------
// anatomical layer colours (must match the Blender build's material colours)
export const LAYER_COLORS = { Enamel: "#f1eddd", Dentine: "#e6ca7e", Pulp: "#c72e33" };
// HIDDEN / internal caries (found on the panoramic X-ray): the eaten dentine/enamel of the
// focal internal cavity is stained this dark decay colour so the hollow reads as caries.
const INTERNAL_DECAY = "#4d3826";
// How far the caries FRONT penetrates the crown, as a fraction of crown height, per
// ICDAS/ADA grade. The layers are anatomical now (thin enamel, bulk dentine, pulp with
// horns), so the depths follow the ADA table: D1-D2 NON-cavitated (no hole), D3 enamel
// breakdown -> outer dentine, D4 into dentine, D5 inner-third dentine (enamel fully
// cavitated), D6 into pulp. With the thin enamel a shallow carve already exposes dentine.
// Bold destruction: D3-D4 = defined cavity; D5-D6 = crown ground down to a stump,
// exposing a dentine ring + pulp on top (matches rampant caries in the intraoral photo).
const PEN_FRAC = [0, 0, 0.04, 0.24, 0.42, 0.62, 0.84]; // D5/D6 eat most of the crown height
// Depth (fraction of crown height) at which each inner layer starts eroding — tuned to
// the thin-enamel geometry so the deepest EXPOSED layer reads the grade. This is a carve
// threshold, not the exact geometric layer depth. Enamel carves most (inset 0); dentine a
// touch less (0.10) → forms the ground-down top surface; the pulp carves WITH the crown too
// (inset ~0.05, slightly more than the dentine) so it NEVER protrudes as a spike, but sits
// just below the surface → realistic EXPOSED pulp (red) shows at the deep D5–D6 cavities
// while D3–D4 stay capped by dentine. (The pulp body stays solid ⇒ no see-through hole.)
const LAYER_INSET = { Enamel: 0.0, Dentine: 0.10, Pulp: 0.05 };

// HIDDEN / internal caries carve (panoramic-only lesions, §6.5). The lesion has to open
// through the enamel too — otherwise the enamel solid's cross-section cap MASKS the internal
// dentine cavity in the examiner (you'd see enamel, no hollow). So we carve a REAL cavity, but
// keep it FOCAL (small radius = a contained spot on the surface, not a ground-down crown) and
// reach it well into the dentine/pulp so the slice shows a clear dark hollow. Tune here:
//   HIDDEN_PEN    -> how DEEP the internal cavity goes (fraction of crown height)
//   HIDDEN_RADIUS -> how WIDE the cavity/opening is  (fraction of crown width)
// Grade index = the panoramic (radiographic) grade. Both are per-tooth fractions => robust.
const HIDDEN_PEN    = [0, 0.20, 0.26, 0.34, 0.46, 0.58, 0.70]; // D2/D3 reach DENTINE (yellow hollow), D4+ deepen toward pulp
const HIDDEN_RADIUS = [0, 0.24, 0.28, 0.33, 0.40, 0.47, 0.54];

function smoothstep(edge0, edge1, x) {
  const t = Math.min(1, Math.max(0, (x - edge0) / (edge1 - edge0 + 1e-9)));
  return t * t * (3 - 2 * t);
}
// cheap deterministic value-noise in [-1,1]
function hash3(x, y, z) {
  const s = Math.sin(x * 127.1 + y * 311.7 + z * 74.7) * 43758.5453;
  return 2 * (s - Math.floor(s)) - 1;
}

// Snapshot the pristine geometry so we can toggle before/after and re-apply.
export function snapshot(mesh) {
  if (mesh.userData._snap) return;
  const g = mesh.geometry;
  mesh.userData._snap = Float32Array.from(g.attributes.position.array);
  if (!g.attributes.color) {
    const n = g.attributes.position.count;
    g.setAttribute("color", new THREE.BufferAttribute(new Float32Array(n * 3), 3));
  }
}

// Reset a tooth to pristine enamel (severity 0).
export function restore(mesh) {
  snapshot(mesh); // ensures the color attribute exists
  const g = mesh.geometry;
  if (mesh.userData._snap) g.attributes.position.array.set(mesh.userData._snap);
  const col = g.attributes.color;
  const base = new THREE.Color(ICDAS_COLORS[0]);
  for (let i = 0; i < col.count; i++) col.setXYZ(i, base.r, base.g, base.b);
  col.needsUpdate = true;
  g.attributes.position.needsUpdate = true;
  g.computeVertexNormals();
  g.computeBoundingSphere();
}

/**
 * Carve + discolour a tooth from its pristine snapshot according to detection.
 * @param toothInfo { mesh, center(Vector3), box(Box3) }
 * @param det       { severity, caries_ratio, lesions:[{u,v,r,grade}] }
 * @param biteMidY  world Y of the occlusal plane between the arches
 */
export function applyDamage(toothInfo, det, biteMidY) {
  const mesh = toothInfo.mesh;
  snapshot(mesh);
  const sev = Math.max(0, Math.min(6, det.severity | 0));
  if (sev === 0) { restore(mesh); return; }

  const g = mesh.geometry;
  const posAttr = g.attributes.position;
  const colAttr = g.attributes.color;
  posAttr.array.set(mesh.userData._snap); // start from pristine

  const box = toothInfo.box;
  const C = toothInfo.center.clone();
  const size = new THREE.Vector3(); box.getSize(size);
  const crownH = Math.max(size.y, 1e-3);
  const crownW = Math.max(size.x, size.z, 1e-3);
  // crown points toward the occlusal plane (down for upper teeth, up for lower)
  const crownSign = biteMidY - C.y >= 0 ? 1 : -1;
  const crownDir = new THREE.Vector3(0, crownSign, 0);

  const mw = mesh.matrixWorld;
  const inv = new THREE.Matrix4().copy(mw).invert();
  const rot = new THREE.Matrix3().getNormalMatrix(mw);
  const invRot = new THREE.Matrix3().getNormalMatrix(inv);
  const crownDirLocal = crownDir.clone().applyMatrix3(invRot).normalize();

  // world positions
  const N = posAttr.count;
  const wp = new Array(N);
  const tmp = new THREE.Vector3();
  let maxDot = -Infinity;
  for (let i = 0; i < N; i++) {
    tmp.set(posAttr.getX(i), posAttr.getY(i), posAttr.getZ(i)).applyMatrix4(mw);
    wp[i] = tmp.clone();
    const d = tmp.clone().sub(C).dot(crownDir);
    if (d > maxDot) maxDot = d;
  }
  // occlusal tip point = centroid of the crown-most 6% of vertices
  const thresh = maxDot - 0.06 * crownH;
  const tip = new THREE.Vector3(); let tc = 0;
  for (let i = 0; i < N; i++) {
    if (wp[i].clone().sub(C).dot(crownDir) >= thresh) { tip.add(wp[i]); tc++; }
  }
  if (tc) tip.divideScalar(tc); else tip.copy(C).addScaledVector(crownDir, crownH * 0.4);

  // lesion origins on the crown (default: the occlusal tip)
  const lesions = (det.lesions && det.lesions.length ? det.lesions : [{ u: 0.5, v: 0.5, r: 0.6, grade: sev }]);
  const lateralX = new THREE.Vector3(1, 0, 0);
  const lateralZ = new THREE.Vector3(0, 0, 1);
  const origins = lesions.map((l) => {
    const o = tip.clone();
    o.addScaledVector(lateralX, (l.u - 0.5) * crownW * 0.5);
    o.addScaledVector(lateralZ, (l.v - 0.5) * crownW * 0.5);
    const lg = Math.max(1, l.grade || sev);
    return { o, R: crownW * RADIUS_FRAC[lg] * (0.6 + 0.6 * (l.r ?? 0.5)), depth: crownH * DEPTH_FRAC[lg], grade: lg };
  });

  // colours: prefer the ones sampled from the actual photo; blend the decay colour
  // toward the ICDAS ramp so severe teeth still read dark even if the sample was greyish.
  const enamel = new THREE.Color(det.enamel_color || ICDAS_COLORS[0]);
  const decayCol = det.decay_color
    ? new THREE.Color(det.decay_color).lerp(new THREE.Color(ICDAS_COLORS[sev]), 0.4)
    : new THREE.Color(ICDAS_COLORS[sev]);
  const jitter = crownW * JITTER_FRAC[sev];

  const axisPoint = C.clone(); // shrink toward the tooth's long axis
  for (let i = 0; i < N; i++) {
    const p = wp[i];
    // combine lesions: take strongest local decay
    let decay = 0, grade = 0;
    for (const L of origins) {
      const dist = p.distanceTo(L.o);
      const f = smoothstep(L.R, 0, dist); // 1 at origin -> 0 at radius
      if (f > decay) { decay = f; grade = L.grade; }
    }
    // only the crown half can decay (roots stay intact)
    const along = p.clone().sub(C).dot(crownDir) / (crownH * 0.5); // -1..~1
    const crownMask = smoothstep(-0.35, 0.25, along);
    decay *= crownMask;
    if (decay > 0.001) {
      const depth = DEPTH_FRAC[grade] * crownH;
      // carve: pull the crown surface inward (down the crown) + gently toward the axis
      const inward = crownDir.clone().multiplyScalar(-decay * depth);
      const radial = new THREE.Vector3(p.x - axisPoint.x, 0, p.z - axisPoint.z);
      radial.multiplyScalar(-decay * decay * 0.35);
      // inward-biased pitting: |noise| eats into the tooth, never spikes outward
      const nAmt = jitter * decay;
      const pit = crownDir.clone().multiplyScalar(-Math.abs(hash3(p.x * 11, p.y * 11, p.z * 11)) * nAmt);
      const lateral = new THREE.Vector3(
        hash3(p.x * 13 + 1, p.y * 13, p.z * 13),
        0,
        hash3(p.x * 13, p.y * 13, p.z * 13 + 1)
      ).multiplyScalar(nAmt * 0.4);
      p.add(inward).add(radial).add(pit).add(lateral);
    }
    // discolour: blend enamel -> decay colour by local decay strength
    const cmix = Math.min(1, decay * 1.15);
    const c = enamel.clone().lerp(decayCol, cmix);
    colAttr.setXYZ(i, c.r, c.g, c.b);
    // write back to local space
    const lp = p.clone().applyMatrix4(inv);
    posAttr.setXYZ(i, lp.x, lp.y, lp.z);
  }
  posAttr.needsUpdate = true;
  colAttr.needsUpdate = true;
  g.computeVertexNormals();
  g.computeBoundingSphere();
}

// ===========================================================================
//  PER-PATIENT SHAPE MORPH (panoramic tooth-segmentation → real tooth shape)
//
//  The panoramic tooth-seg model gives each FDI tooth its real silhouette (crown+root).
//  `run_tooth_seg_panoramic.py` distils it into a unit-free descriptor per tooth:
//     lenRel / widRel — length & mesio-distal width relative to the arch median, and
//     axis[K]         — the ROOT CURVATURE (lengkung akar): the root centreline's lateral
//                       offset (fraction of tooth height) from crown→apex, signed along the
//                       mesio-distal (arch-tangent) direction.
//  Here we deform the generic layered tooth to match: bend the root to follow axis[], and
//  scale length/width so proportions match. ALL THREE layers are morphed from ONE common
//  frame (the enamel's), so the nesting (enamel⊃dentine⊃pulp) — and hence the realistic
//  cross-section — is preserved. The morph runs BEFORE the caries carve: it rewrites the
//  pristine snapshot the carve starts from, so a new patient's panoramic just re-shapes.
// ===========================================================================

// how far length/width may be pushed toward the real proportions (safety clamps so a noisy
// descriptor can never explode a tooth or make it collide with neighbours)
const LEN_CLAMP = [0.7, 1.4];
const WID_CLAMP = [0.72, 1.20];

// Capture the ORIGINAL (pre-anything) geometry once, so the morph always rebuilds from the
// true GLB pristine — independent of the current carve/morph state. Distinct from `_snap`
// (which the carve treats as "pristine" and the morph overwrites with the shaped tooth).
export function snapshotBase(mesh) {
  if (!mesh.userData._snap0)
    mesh.userData._snap0 = Float32Array.from(mesh.geometry.attributes.position.array);
  return mesh.userData._snap0;
}

function sampleArr(arr, t) {
  if (!arr || !arr.length) return 0;
  const f = Math.min(arr.length - 1, Math.max(0, t * (arr.length - 1)));
  const i = Math.floor(f), j = Math.min(arr.length - 1, i + 1);
  return arr[i] + (arr[j] - arr[i]) * (f - i);
}

const clampf = (v, lo, hi) => Math.min(hi, Math.max(lo, v));

/**
 * Morph a layered tooth to the panoramic-derived real shape, then re-baseline it so the caries
 * carve starts from the shaped tooth. No-op (identity) when `shape` is absent → fully backward
 * compatible with datasets that have no panoramic tooth-seg.
 * @param layers { Enamel:{mesh,center,box}, Dentine:{...}, Pulp:{...} }
 * @param shape  { lenRel, widRel, axis:[...], prof:[...] }  (crown→apex)
 * @param biteMidY world/local Y of the occlusal plane (local when opts.local)
 * @param opts   { local, mdDir:THREE.Vector3, genLenRel, genWidRel, bendGain }
 */
export function applyShapeLayered(layers, shape, biteMidY, opts = {}) {
  const enamel = layers.Enamel;
  if (!enamel) return;
  const names = ["Enamel", "Dentine", "Pulp"];

  // always start each layer from its TRUE pristine base
  for (const nm of names) {
    const info = layers[nm];
    if (!info) continue;
    const base = snapshotBase(info.mesh);
    info.mesh.geometry.attributes.position.array.set(base);
  }

  const finish = () => {
    for (const nm of names) {
      const info = layers[nm];
      if (!info) continue;
      const g = info.mesh.geometry;
      g.attributes.position.needsUpdate = true;
      g.computeBoundingBox();
      info.box = g.boundingBox.clone();
      info.center = info.box.getCenter(new THREE.Vector3());
      g.computeVertexNormals();
      g.computeBoundingSphere();
      // this shaped geometry IS the new pristine the carve starts from; drop cached hull/weld
      info.mesh.userData._snap = Float32Array.from(g.attributes.position.array);
      delete info.mesh.userData._pristineHull;
      delete g.userData._weld;
    }
  };

  if (!shape) { finish(); return; } // no panoramic shape → keep the generic tooth as-is

  // ---- build the common frame from the ENAMEL base ----
  const base = snapshotBase(enamel.mesh);
  let cx = 0, cy = 0, cz = 0, minY = Infinity, maxY = -Infinity, minX = Infinity, maxX = -Infinity, minZ = Infinity, maxZ = -Infinity;
  const nB = base.length / 3;
  for (let i = 0; i < nB; i++) {
    const x = base[i * 3], y = base[i * 3 + 1], z = base[i * 3 + 2];
    cx += x; cy += y; cz += z;
    if (y < minY) minY = y; if (y > maxY) maxY = y;
    if (x < minX) minX = x; if (x > maxX) maxX = x;
    if (z < minZ) minZ = z; if (z > maxZ) maxZ = z;
  }
  const C = new THREE.Vector3(cx / nB, cy / nB, cz / nB);
  const crownSign = biteMidY - C.y >= 0 ? 1 : -1;
  const crownH = Math.max(maxY - minY, 1e-3);
  // along-axis (Y) extremes for crown-anchored length scaling
  const crownAlong = crownSign > 0 ? (maxY - C.y) : (C.y - minY);
  const apexAlong = crownSign > 0 ? (minY - C.y) : (C.y - maxY);
  const totalLen = Math.max(crownAlong - apexAlong, 1e-3);

  const sLen = clampf(shape.lenRel / (opts.genLenRel || 1), LEN_CLAMP[0], LEN_CLAMP[1]);
  const sWid = clampf(shape.widRel / (opts.genWidRel || 1), WID_CLAMP[0], WID_CLAMP[1]);
  const md = opts.mdDir ? opts.mdDir.clone().setY(0).normalize() : null;
  const bendGain = opts.bendGain ?? 1;

  for (const nm of names) {
    const info = layers[nm];
    if (!info) continue;
    const pos = info.mesh.geometry.attributes.position;
    const src = snapshotBase(info.mesh);
    const N = pos.count;
    for (let i = 0; i < N; i++) {
      const x = src[i * 3], y = src[i * 3 + 1], z = src[i * 3 + 2];
      const along = (y - C.y) * crownSign;          // + toward crown tip
      const t = clampf((crownAlong - along) / totalLen, 0, 1); // 0 crown → 1 apex
      // 1) length: scale distance-from-crown, keeping the occlusal/crown plane fixed
      const nAlong = crownAlong + (along - crownAlong) * sLen;
      const dY = (nAlong - along) * crownSign;
      // 2) width: scale the horizontal footprint about the tooth's central axis
      let nx = C.x + (x - C.x) * sWid;
      let nz = C.z + (z - C.z) * sWid;
      // 3) root curvature (lengkung akar): shift sideways along the mesio-distal axis by the
      //    real centreline offset at this height. 0 at the crown, grows toward the apex.
      if (md) {
        const off = sampleArr(shape.axis, t) * crownH * bendGain;
        nx += md.x * off;
        nz += md.z * off;
      }
      pos.setXYZ(i, nx, y + dY, nz);
    }
  }
  finish();
}

// ===========================================================================
//  GINGIVA SKIN (make the gum follow the tooth shape morph, so it ALWAYS fits)
//
//  The gum (gums.glb) is sculpted in Blender to hug the PRISTINE teeth. The per-patient shape
//  morph above then moves the teeth (length/width/root-bend), and a static gum can't follow →
//  roots poke out and interdental gaps open up. Fix: skin the gum to the teeth. Each gum vertex
//  is displaced by a distance-weighted blend of its nearest teeth's OWN morph displacement, so
//  the gum deforms congruently with whatever the morph did — for ANY morph, and identity when no
//  tooth carries a shape. This reads only the teeth's pristine geometry and writes only the gum;
//  the tooth morph/carve is never touched (the gum is a complementary add-on, §6.8).
// ===========================================================================

/**
 * Build a pure per-tooth morph FIELD matching `applyShapeLayered`'s deformation exactly, so the
 * gingiva can be skinned to the SAME morph. Returns `{ C, deform(x,y,z,out) }` — `deform` writes
 * the morphed position of an arbitrary point into `out` (length-3). Identity `deform` when `shape`
 * is absent (so a no-shape tooth just anchors the gum in place). Reads only the tooth's PRISTINE
 * base (`_snap0`), so it's independent of the tooth's current carve/morph state and mutates nothing.
 */
export function buildToothMorphField(enamelMesh, shape, biteMidY, opts = {}) {
  const base = snapshotBase(enamelMesh);
  let cx = 0, cy = 0, cz = 0, minY = Infinity, maxY = -Infinity;
  const n = base.length / 3;
  for (let i = 0; i < n; i++) {
    const y = base[i * 3 + 1];
    cx += base[i * 3]; cy += y; cz += base[i * 3 + 2];
    if (y < minY) minY = y; if (y > maxY) maxY = y;
  }
  const C = new THREE.Vector3(cx / n, cy / n, cz / n);
  if (!shape) return { C, deform: (x, y, z, out) => { out[0] = x; out[1] = y; out[2] = z; } };

  // same frame + scalars as applyShapeLayered (kept in lock-step by construction)
  const crownSign = biteMidY - C.y >= 0 ? 1 : -1;
  const crownH = Math.max(maxY - minY, 1e-3);
  const crownAlong = crownSign > 0 ? (maxY - C.y) : (C.y - minY);
  const apexAlong = crownSign > 0 ? (minY - C.y) : (C.y - maxY);
  const totalLen = Math.max(crownAlong - apexAlong, 1e-3);
  const sLen = clampf(shape.lenRel / (opts.genLenRel || 1), LEN_CLAMP[0], LEN_CLAMP[1]);
  const sWid = clampf(shape.widRel / (opts.genWidRel || 1), WID_CLAMP[0], WID_CLAMP[1]);
  const md = opts.mdDir ? opts.mdDir.clone().setY(0).normalize() : null;
  const bendGain = opts.bendGain ?? 1;
  const axis = shape.axis;

  return {
    C,
    deform(x, y, z, out) {
      const along = (y - C.y) * crownSign;
      const t = clampf((crownAlong - along) / totalLen, 0, 1);
      const nAlong = crownAlong + (along - crownAlong) * sLen;
      const dY = (nAlong - along) * crownSign;
      let nx = C.x + (x - C.x) * sWid;
      let nz = C.z + (z - C.z) * sWid;
      if (md) {
        const off = sampleArr(axis, t) * crownH * bendGain;
        nx += md.x * off; nz += md.z * off;
      }
      out[0] = nx; out[1] = y + dY; out[2] = nz;
    },
  };
}

/**
 * Skin one arch's gingiva to its teeth. Each gum vertex is moved by a distance-weighted blend of
 * the nearest teeth's morph displacement (inverse-distance^power → the 2–3 nearest teeth dominate,
 * giving a smooth transition across interdental papillae). Because the displacement IS each tooth's
 * own morph, the gum keeps its original clearance to every tooth surface ⇒ roots stay covered and
 * the gum never intrudes into a crown, for ANY morph. Re-skins from the pristine gum every call.
 * @param gumMesh  arch gum mesh (Gum_Upper / Gum_Lower)
 * @param fields   per-tooth fields from `buildToothMorphField` for THIS arch
 * @param opts     { power=4, eps=1e-5 }
 */
export function applyShapeGum(gumMesh, fields, opts = {}) {
  if (!gumMesh) return;
  const base = snapshotBase(gumMesh);           // pristine gum, captured once
  const pos = gumMesh.geometry.attributes.position;
  const N = pos.count;
  if (!fields.length) {                          // no morph anywhere → restore pristine gum
    pos.array.set(base); pos.needsUpdate = true;
    gumMesh.geometry.computeVertexNormals(); gumMesh.geometry.computeBoundingSphere();
    return;
  }
  const power = opts.power ?? 4;
  const eps = opts.eps ?? 1e-5;
  const nd = [0, 0, 0];
  for (let i = 0; i < N; i++) {
    const x = base[i * 3], y = base[i * 3 + 1], z = base[i * 3 + 2];
    let wsum = 0, ox = 0, oy = 0, oz = 0;
    for (let f = 0; f < fields.length; f++) {
      const C = fields[f].C;
      const dx = x - C.x, dz = z - C.z, dy = (y - C.y) * 0.5; // de-weight vertical: bind along the arch
      const d2 = dx * dx + dz * dz + dy * dy;
      const w = 1 / (Math.pow(d2, power * 0.5) + eps);
      fields[f].deform(x, y, z, nd);
      ox += w * (nd[0] - x); oy += w * (nd[1] - y); oz += w * (nd[2] - z);
      wsum += w;
    }
    if (wsum > 0) { const iw = 1 / wsum; ox *= iw; oy *= iw; oz *= iw; }
    pos.setXYZ(i, x + ox, y + oy, z + oz);
  }
  pos.needsUpdate = true;
  const g = gumMesh.geometry;
  g.computeVertexNormals(); g.computeBoundingBox(); g.computeBoundingSphere();
}

// ===========================================================================
//  LAYERED destruction (enamel / dentine / pulp nested solids)
//
//  A tooth here is three nested meshes. We carve the crown of each layer by a
//  depth that grows with the caries grade but is offset per layer (LAYER_INSET),
//  so a shallow lesion only dents the enamel, a deeper one pushes the enamel
//  below the dentine surface (dentine shows through the cavity), and a very deep
//  one exposes the pulp. Because all three layers share ONE lesion frame (built
//  from the enamel), the cavities line up and the cross-section matches the
//  outer view. The carve is data-driven from detections.json, so a new patient's
//  image just changes the depths — nothing is baked into the GLB.
// ===========================================================================

// Ensure a mesh has a per-vertex colour attribute filled with `hex`.
function fillColor(mesh, hex) {
  const g = mesh.geometry;
  if (!g.attributes.color) {
    g.setAttribute("color", new THREE.BufferAttribute(new Float32Array(g.attributes.position.count * 3), 3));
  }
  const col = g.attributes.color, c = new THREE.Color(hex);
  for (let i = 0; i < col.count; i++) col.setXYZ(i, c.r, c.g, c.b);
  col.needsUpdate = true;
}

// Build the shared lesion frame from the ENAMEL layer. When `local` is true the
// carve runs in geometry-local space (center/box must be local) — this keeps the
// combined-arch carve invariant to the outer group's scale/rotation.
const IDENTITY = new THREE.Matrix4();
function buildFrame(enamelInfo, det, biteMidY, local) {
  const mesh = enamelInfo.mesh;
  snapshot(mesh);
  const posAttr = mesh.geometry.attributes.position;
  posAttr.array.set(mesh.userData._snap);
  const C = enamelInfo.center.clone();
  const size = new THREE.Vector3(); enamelInfo.box.getSize(size);
  const crownH = Math.max(size.y, 1e-3);
  const crownW = Math.max(size.x, size.z, 1e-3);
  const crownSign = biteMidY - C.y >= 0 ? 1 : -1;
  const crownDir = new THREE.Vector3(0, crownSign, 0);

  const mw = local ? IDENTITY : mesh.matrixWorld;
  const N = posAttr.count, wp = new Array(N), tmp = new THREE.Vector3();
  let maxDot = -Infinity;
  for (let i = 0; i < N; i++) {
    tmp.set(posAttr.getX(i), posAttr.getY(i), posAttr.getZ(i)).applyMatrix4(mw);
    wp[i] = tmp.clone();
    const d = tmp.clone().sub(C).dot(crownDir);
    if (d > maxDot) maxDot = d;
  }
  const thresh = maxDot - 0.06 * crownH;
  const tip = new THREE.Vector3(); let tc = 0;
  for (let i = 0; i < N; i++) {
    if (wp[i].clone().sub(C).dot(crownDir) >= thresh) { tip.add(wp[i]); tc++; }
  }
  if (tc) tip.divideScalar(tc); else tip.copy(C).addScaledVector(crownDir, crownH * 0.4);

  const sev = Math.max(0, Math.min(6, det.severity | 0));
  const lesions = (det.lesions && det.lesions.length) ? det.lesions
    : [{ u: 0.5, v: 0.5, r: 0.6, grade: sev }];
  const lx = new THREE.Vector3(1, 0, 0), lz = new THREE.Vector3(0, 0, 1);
  const origins = lesions.map((l) => {
    const o = tip.clone();
    o.addScaledVector(lx, (l.u - 0.5) * crownW * 0.5);
    o.addScaledVector(lz, (l.v - 0.5) * crownW * 0.5);
    return { o, grade: Math.max(1, l.grade || sev), rBase: 0.6 + 0.6 * (l.r ?? 0.5) };
  });
  return { C, crownDir, crownH, crownW, origins, sev };
}

// Welded-vertex adjacency for Laplacian smoothing, cached on the geometry. Coincident vertices
// (GLB seams / flat-shaded splits) are merged to one representative so smoothing moves them
// together and never tears a seam open.
function weldAdjacency(g) {
  if (g.userData._weld) return g.userData._weld;
  const pos = g.attributes.position, n = pos.count, q = 1e4;
  const key2rep = new Map(), rep = new Int32Array(n);
  for (let i = 0; i < n; i++) {
    const k = Math.round(pos.getX(i) * q) + "," + Math.round(pos.getY(i) * q) + "," + Math.round(pos.getZ(i) * q);
    if (key2rep.has(k)) rep[i] = key2rep.get(k);
    else { key2rep.set(k, i); rep[i] = i; }
  }
  const adjSet = new Map();
  const link = (a, b) => { a = rep[a]; b = rep[b]; if (a === b) return; let s = adjSet.get(a); if (!s) { s = new Set(); adjSet.set(a, s); } s.add(b); };
  const idx = g.index ? g.index.array : null;
  if (idx) for (let i = 0; i < idx.length; i += 3) {
    const a = idx[i], b = idx[i + 1], c = idx[i + 2];
    link(a, b); link(b, a); link(b, c); link(c, b); link(c, a); link(a, c);
  }
  const adj = new Array(n).fill(null), reps = [];
  for (const [r, s] of adjSet) { adj[r] = Array.from(s); reps.push(r); }
  const weld = { rep, adj, reps };
  g.userData._weld = weld;
  return weld;
}

// Smooth the carved crown so the cut loses facets, spikes AND the jagged rim where the cavity
// meets the intact surface — WITHOUT shrinking the cavity (the carve AMOUNT must stay) and
// without touching the roots. Plain Laplacian smooths well but visibly shrinks the cavity;
// TAUBIN barely moved anything here. So we use HC-LAPLACIAN (Humphrey's Classes): each pass does
// a Laplacian step, then pushes back toward the ORIGINAL carved position — killing the spikes/
// facets while cancelling the shrinkage, so depth/size are preserved. It runs on the carved set
// DILATED a few rings (so the rim is included) as a boolean gate whose border sits out in flat
// enamel; non-gated neighbours anchor that border so nothing drifts. Welded vertices share one
// position so seams never tear.
function smoothCarvedRegion(g, decayArr, iters) {
  if (!g.index || iters <= 0) return;
  const { rep, adj, reps } = weldAdjacency(g);
  const pos = g.attributes.position, n = pos.count;

  // gate = carved set (decay>0.02) dilated 3 rings to cover the rim + a margin
  const m = new Uint8Array(n);
  for (const r of reps) if (decayArr[r] > 0.02) m[r] = 1;
  for (let d = 0; d < 3; d++) {
    const nx = Uint8Array.from(m);
    for (const r of reps) { if (m[r]) continue; const nb = adj[r]; if (nb) for (const j of nb) if (m[j]) { nx[r] = 1; break; } }
    m.set(nx);
  }
  const active = reps.filter((r) => m[r]);
  if (!active.length) return;

  const alpha = 0.05, beta = 0.6;              // HC params: low α → follow the smoothed surface; β → anti-shrink
  const o = new Map();                          // original carved positions (the anti-shrink anchor)
  for (const r of active) o.set(r, [pos.getX(r), pos.getY(r), pos.getZ(r)]);

  for (let it = 0; it < iters; it++) {
    const p = new Map();                        // Laplacian target = neighbour average
    for (const r of active) {
      const nb = adj[r]; let sx = 0, sy = 0, sz = 0, c = 0;
      for (const j of nb) { sx += pos.getX(j); sy += pos.getY(j); sz += pos.getZ(j); c++; }
      p.set(r, c ? [sx / c, sy / c, sz / c] : [pos.getX(r), pos.getY(r), pos.getZ(r)]);
    }
    const b = new Map();                        // difference from the α-blend of original & current
    for (const r of active) {
      const pv = p.get(r), oo = o.get(r);
      b.set(r, [pv[0] - (alpha * oo[0] + (1 - alpha) * pos.getX(r)),
                pv[1] - (alpha * oo[1] + (1 - alpha) * pos.getY(r)),
                pv[2] - (alpha * oo[2] + (1 - alpha) * pos.getZ(r))]);
    }
    const np = new Map();                       // final = p − (β·b + (1−β)·avg_nb b)  → smoothed, un-shrunk
    for (const r of active) {
      const pv = p.get(r), bv = b.get(r), nb = adj[r];
      let bx = 0, by = 0, bz = 0, c = 0;
      for (const j of nb) { const bj = b.get(j); if (bj) { bx += bj[0]; by += bj[1]; bz += bj[2]; c++; } }
      const ax = c ? bx / c : 0, ay = c ? by / c : 0, az = c ? bz / c : 0;
      np.set(r, [pv[0] - (beta * bv[0] + (1 - beta) * ax),
                 pv[1] - (beta * bv[1] + (1 - beta) * ay),
                 pv[2] - (beta * bv[2] + (1 - beta) * az)]);
    }
    for (let i = 0; i < rep.length; i++) { const v = np.get(rep[i]); if (v) pos.setXYZ(i, v[0], v[1], v[2]); }
  }
}

// Pristine-enamel containment mesh (a MeshBVH over the ENAMEL layer's UNCARVED positions),
// built once per tooth and cached. This is the exact original tooth silhouette — the boundary
// between "inside the tooth" (a legit cavity reveal, keep) and "outside the tooth" (a pokethrough
// sliver, remove). It never changes with the carve, so it's safe to cache forever.
function getPristineHull(enamelMesh) {
  const cache = enamelMesh.userData;
  if (cache._pristineHull) return cache._pristineHull;
  snapshot(enamelMesh);
  const snap = enamelMesh.userData._snap;
  const eg = enamelMesh.geometry;
  if (!snap || !eg.index) return null;
  const geo = new THREE.BufferGeometry();
  geo.setAttribute("position", new THREE.BufferAttribute(Float32Array.from(snap), 3));
  geo.setIndex(new THREE.BufferAttribute(Uint32Array.from(eg.index.array), 1));
  geo.computeBoundingBox();
  const bvh = new MeshBVH(geo);
  const diag = geo.boundingBox.min.distanceTo(geo.boundingBox.max) || 1;
  const hull = { bvh, geo, index: geo.index, pos: geo.attributes.position, diag };
  cache._pristineHull = hull;
  return hull;
}

// FINAL CONTAINMENT PASS — pull any inner-layer vertex that has ended up OUTSIDE the original
// tooth back to just inside its surface. The carve is a crown-shortening, not a boolean, so on
// curved/thin crowns (worst on the D6 incisors) a "less-receded" dentine/pulp vertex can cross
// outside the enamel and show as the stray yellow/red slivers poking through the intact face.
// The exact test for "is this a real reveal or a sliver" is: a reveal lives INSIDE the pristine
// tooth volume (you're looking into a hollow where enamel was removed); a sliver pokes OUTSIDE
// it. So we test every inner vertex against the pristine-enamel hull and only move the ones that
// are outside — pushing them a hair back under the surface. Everything inside (the whole cavity
// reveal) is left EXACTLY as carved, so the destruction/amount/shape is 100% preserved; only the
// pokethrough is removed. Shape-agnostic (a true inside/outside test), so thin teeth work too.
function clampInnerContainment(outerInfo, innerInfo, opts) {
  const hull = getPristineHull(outerInfo.mesh);
  if (!hull) return;
  const local = !!opts.local;
  const innerMesh = innerInfo.mesh;
  const iPos = innerMesh.geometry.attributes.position;
  // enamel and inner layers share the same geometry frame (no per-node transforms), so in the
  // local path we can compare positions directly. Guard the non-local path just in case.
  const toHull = local ? IDENTITY : new THREE.Matrix4().copy(outerInfo.mesh.matrixWorld).invert().multiply(innerMesh.matrixWorld);
  const fromHull = local ? IDENTITY : new THREE.Matrix4().copy(innerMesh.matrixWorld).invert().multiply(outerInfo.mesh.matrixWorld);
  const gap = 0.004 * hull.diag; // sit a hair under the surface (hide it, avoid z-fight)

  const idx = hull.index, hpos = hull.pos;
  const p = new THREE.Vector3(), a = new THREE.Vector3(), b = new THREE.Vector3(), c = new THREE.Vector3();
  const ab = new THREE.Vector3(), ac = new THREE.Vector3(), fn = new THREE.Vector3(), np = new THREE.Vector3();
  const hit = {};
  for (let i = 0; i < iPos.count; i++) {
    p.set(iPos.getX(i), iPos.getY(i), iPos.getZ(i));
    if (!local) p.applyMatrix4(toHull);
    const r = hull.bvh.closestPointToPoint(p, hit);
    if (!r) continue;
    // outward geometric normal of the hit face → sign of (p - closest)·n tells inside/outside
    const f = hit.faceIndex * 3;
    const ia = idx.getX(f), ib = idx.getX(f + 1), ic = idx.getX(f + 2);
    a.set(hpos.getX(ia), hpos.getY(ia), hpos.getZ(ia));
    b.set(hpos.getX(ib), hpos.getY(ib), hpos.getZ(ib));
    c.set(hpos.getX(ic), hpos.getY(ic), hpos.getZ(ic));
    fn.copy(ab.subVectors(b, a)).cross(ac.subVectors(c, a)).normalize();
    const signed = np.copy(p).sub(hit.point).dot(fn);
    if (signed <= gap) continue;             // inside (or barely at) the surface → a real reveal, keep it
    np.copy(hit.point).addScaledVector(fn, -gap); // move to just UNDER the pristine surface
    if (!local) np.applyMatrix4(fromHull);
    iPos.setXYZ(i, np.x, np.y, np.z);
  }
  iPos.needsUpdate = true;
  innerMesh.geometry.computeVertexNormals();
  innerMesh.geometry.computeBoundingSphere();
}

// Carve one layer's crown using the shared frame. `layerName` selects the inset
// (how deep the caries must reach before this layer starts eroding). `depthScale`
// scales how far this layer recedes — the enamel uses a small scale so its outer
// surface stays mostly closed/white and the caries reads as an internal cavity.
// The carve is SMOOTH (no surface jitter) and colours stay clean anatomical tints
// (no brown discolouration).
function carveLayer(info, frame, layerName, opts) {
  const mesh = info.mesh;
  snapshot(mesh);
  const g = mesh.geometry, posAttr = g.attributes.position;
  fillColor(mesh, LAYER_COLORS[layerName]); // clean colour, no decay staining
  posAttr.array.set(mesh.userData._snap);

  const { C, crownDir, crownH, crownW, origins } = frame;
  const inset = LAYER_INSET[layerName];
  const local = !!opts.local;
  const depthScale = opts.depthScale ?? 1;
  const penA = opts.penArr || PEN_FRAC;      // hidden caries overrides the depth/width tables
  const radA = opts.radArr || RADIUS_FRAC;
  const mw = local ? IDENTITY : mesh.matrixWorld;
  const inv = local ? IDENTITY : new THREE.Matrix4().copy(mw).invert();
  const axisPoint = C.clone();
  // optional decay stain (used by hidden/internal caries so the eaten dentine reads as decay)
  const colAttr = g.attributes.color;
  const baseCol = new THREE.Color(LAYER_COLORS[layerName]);
  const stainCol = opts.stainColor ? new THREE.Color(opts.stainColor) : null;
  const stainStrength = opts.stainStrength ?? 1.5;

  // revealGate [lo,hi]: only let an INNER layer recede LESS than the enamel (i.e. show through
  // the cavity) where the decay is deep (>hi). Where decay is moderate — the intact labial face
  // and the cavity rim — the layer recedes WITH the enamel, so it stays hidden behind it and can't
  // poke through as a sharp sliver. Enamel passes no gate, so its shape is unchanged.
  const revealGate = opts.revealGate || null;
  const N = posAttr.count, p = new THREE.Vector3();
  const decayArr = new Float32Array(N);       // per-vertex decay -> drives the smoothing pass
  for (let i = 0; i < N; i++) {
    p.set(posAttr.getX(i), posAttr.getY(i), posAttr.getZ(i)).applyMatrix4(mw);
    // strongest local decay. For a GATED inner layer the decay field follows the ENAMEL extent
    // (full penA, no inset) so the layer carves the SAME region as the enamel — it is never left
    // un-receded where the enamel receded (which is what let it poke through). Ungated layers
    // (enamel + the hidden-caries branch) keep the original per-layer extent, unchanged.
    let decay = 0, gradeSel = 0;
    for (const L of origins) {
      const pen = revealGate ? penA[L.grade] : Math.max(0, penA[L.grade] - inset);
      if (pen <= 0) continue;
      const frac = pen / Math.max(penA[L.grade], 1e-3);
      const R = crownW * radA[L.grade] * L.rBase * (revealGate ? 1 : (0.5 + 0.5 * frac));
      const f = smoothstep(R, 0, p.distanceTo(L.o));
      if (f > decay) { decay = f; gradeSel = L.grade; }
    }
    const along = p.clone().sub(C).dot(crownDir) / (crownH * 0.5);
    decay *= smoothstep(-0.35, 0.25, along); // crown half only
    decayArr[i] = decay;
    if (decay > 0.001 && penA[gradeSel] > 0) {
      // GATED inner layer: recede like the enamel minus its reveal inset, but the inset only kicks
      // in where the decay is deep (gate) → reveal confined to the cavity centre, no face slivers.
      // Ungated (enamel / hidden branch): original behaviour, eff = penA − inset.
      const eff = revealGate
        ? Math.max(0, penA[gradeSel] - inset * smoothstep(revealGate[0], revealGate[1], decay))
        : Math.max(0, penA[gradeSel] - inset);
      const depth = eff * crownH * depthScale;
      const inward = crownDir.clone().multiplyScalar(-decay * depth);
      const radial = new THREE.Vector3(p.x - axisPoint.x, 0, p.z - axisPoint.z)
        .multiplyScalar(-decay * decay * 0.22); // gentle inward pull, no jitter
      p.add(inward).add(radial);
    }
    if (stainCol && colAttr) {
      const c = baseCol.clone().lerp(stainCol, Math.min(1, decay * stainStrength));
      colAttr.setXYZ(i, c.r, c.g, c.b);
    }
    const lp = p.applyMatrix4(inv);
    posAttr.setXYZ(i, lp.x, lp.y, lp.z);
  }
  // de-facet the cut: HC-Laplacian over the carved crown + its rim (de-spike, keep carve amount)
  smoothCarvedRegion(g, decayArr, opts.smoothIters ?? 6);
  posAttr.needsUpdate = true;
  if (stainCol && colAttr) colAttr.needsUpdate = true;
  g.computeVertexNormals();
  g.computeBoundingSphere();
}

/**
 * Carve a layered tooth (enamel/dentine/pulp) from detection severity.
 * @param layers { Enamel:{mesh,center,box}, Dentine:{mesh,...}, Pulp:{mesh,...} }
 * @param opts   { local, enamelScale, inner, hidden }
 *   enamelScale — how far the enamel surface caves in (small => stays closed/white).
 *   inner       — carve dentine/pulp too (cross-section reveals them); false for the
 *                 main view, where the inner layers are hidden and the tooth stays white.
 *   hidden      — force the internal/occult-caries mode (else taken from det.hidden): the
 *                 enamel surface stays INTACT (with a subsurface shadow) and only the dentine
 *                 (+pulp) are eaten from the inside — decay you can't see from the outside,
 *                 revealed only in the cross-section. Drives the panoramic-only lesions.
 */
export function applyDamageLayered(layers, det, biteMidY, opts = {}) {
  const enamel = layers.Enamel;
  if (!enamel) return;
  const local = !!opts.local;
  const sev = Math.max(0, Math.min(6, det.severity | 0));
  if (sev === 0) { restoreLayered(layers); return; }
  const frame = buildFrame(enamel, det, biteMidY, local);

  if (det.hidden ?? opts.hidden) {
    // HIDDEN / internal caries: a FOCAL, dark-stained cavity that opens through the enamel (so
    // the examiner slice actually shows a hollow — the enamel solid would otherwise mask an
    // internal-only cavity) but stays small/contained, so the surface reads as a dark spot, not
    // the gross ground-down crown of external caries. Uses the HIDDEN_* depth/width tables.
    const h = { local, penArr: HIDDEN_PEN, radArr: HIDDEN_RADIUS };
    carveLayer(enamel, frame, "Enamel", { ...h, stainColor: INTERNAL_DECAY, stainStrength: 1.3 });
    clampInnerContainment(enamel, enamel, h); // tuck any enamel blades poking past the pristine surface
    if (opts.inner !== false) {
      if (layers.Dentine)
        carveLayer(layers.Dentine, frame, "Dentine", { ...h, stainColor: INTERNAL_DECAY, stainStrength: 1.8 });
      if (layers.Pulp)
        carveLayer(layers.Pulp, frame, "Pulp", { ...h });
      // tuck any inner-layer sliver that pokes past its cover on the intact face (keeps the hollow)
      if (layers.Dentine) clampInnerContainment(enamel, layers.Dentine, h);
      if (layers.Pulp) clampInnerContainment(layers.Dentine || enamel, layers.Pulp, h);
    }
    return;
  }

  const si = opts.smoothIters;

  carveLayer(enamel, frame, "Enamel", { local, depthScale: opts.enamelScale ?? 1, smoothIters: si });
  // Clamp the ENAMEL to its OWN pristine silhouette. The carve only removes material (pushes
  // inward / grinds down), so nothing should ever be MORE proud than the original tooth — yet the
  // carve+smooth can flick thin white blades/petals OUTSIDE the surface around the cavity rims.
  // Testing the carved enamel against its pristine hull tucks exactly those blades back flush,
  // leaving the cavity (all inward) untouched. Same proven inside/outside test as the inner layers.
  clampInnerContainment(enamel, enamel, { local });
  if (opts.inner !== false) {
    // reveal gates confine the dentine/pulp reveal to the deep cavity centre so they never poke
    // through the thin-enamel labial face as sharp slivers (pulp deeper than dentine).
    if (layers.Dentine) carveLayer(layers.Dentine, frame, "Dentine", { local, depthScale: 1, smoothIters: si, revealGate: [0.35, 0.72] });
    // (pulp carve below)
    // Carve the pulp too, by the SAME crown-shortening as the dentine (LAYER_INSET.Pulp ≤
    // Dentine). Because the pulp starts nested strictly inside the dentine, carving both
    // together keeps the pulp permanently BELOW the dentine surface → the dentine (a closed
    // solid) always caps it, so the ground-down top reads as enamel rim + yellow dentine,
    // never a protruding red spike. The pulp body below stays solid ⇒ still no see-through.
    if (layers.Pulp) carveLayer(layers.Pulp, frame, "Pulp", { local, depthScale: 1, smoothIters: si, revealGate: [0.55, 0.9] });
    // FINAL PASS: tuck any dentine/pulp sliver that still crosses OUTSIDE its cover on the
    // intact white face (curvature can push it past the enamel even with the reveal gate).
    // Uses the same gate as the carve so the deep-cavity reveal (the eaten look you want) is
    // left untouched — only the stray pokethrough on the face is removed. Order matters:
    // clamp dentine under the carved enamel first, then clamp pulp under the clamped dentine.
    if (layers.Dentine) clampInnerContainment(enamel, layers.Dentine, { local });
    if (layers.Pulp) clampInnerContainment(layers.Dentine || enamel, layers.Pulp, { local });
  }
}

// Reset a layered tooth to pristine (no caries), restoring anatomical colours.
export function restoreLayered(layers) {
  for (const name of ["Enamel", "Dentine", "Pulp"]) {
    const info = layers[name];
    if (!info) continue;
    const mesh = info.mesh, g = mesh.geometry;
    snapshot(mesh);
    if (mesh.userData._snap) g.attributes.position.array.set(mesh.userData._snap);
    fillColor(mesh, LAYER_COLORS[name]);
    g.attributes.position.needsUpdate = true;
    g.computeVertexNormals();
    g.computeBoundingSphere();
  }
}
