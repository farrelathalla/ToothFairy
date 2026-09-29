"use client";
import React, { useEffect, useRef, useState } from "react";
import { Canvas } from "@react-three/fiber";
import { OrbitControls, useGLTF, ContactShadows } from "@react-three/drei";
import * as THREE from "three";

import { applyDamageLayered, restoreLayered, applyShapeLayered, snapshotBase, buildToothMorphField, applyShapeGum } from "@/lib/damage";
import "../../styles/viewer.css";

// anatomical order along the arch, in the panoramic +x direction (patient right → left), so a
// tooth's mesio-distal (arch-tangent) axis and the sign of its root-curvature offset line up.
const UPPER_SEQ = [18, 17, 16, 15, 14, 13, 12, 11, 21, 22, 23, 24, 25, 26, 27, 28];
const LOWER_SEQ = [48, 47, 46, 45, 44, 43, 42, 41, 31, 32, 33, 34, 35, 36, 37, 38];

// Per-tooth shape metadata for the panoramic shape morph: the mesio-distal axis (from arch
// neighbours) and the generic tooth's own length/width relative to the arch median (so the
// real lenRel/widRel can be transferred as a ratio). Computed once from the pristine GLB.
function buildShapeMeta(teeth) {
  const meta = {};
  const H = (t) => { const s = new THREE.Vector3(); t.Enamel.box.getSize(s); return s; };
  for (const seq of [UPPER_SEQ, LOWER_SEQ]) {
    const present = seq.filter((f) => teeth[f]?.Enamel);
    const sizes = present.map((f) => H(teeth[f]));
    const medLen = median(sizes.map((s) => s.y));
    const medWid = median(sizes.map((s) => Math.max(s.x, s.z)));
    present.forEach((f, k) => {
      const c = teeth[f].Enamel.center;
      const prev = teeth[present[Math.max(0, k - 1)]].Enamel.center;
      const next = teeth[present[Math.min(present.length - 1, k + 1)]].Enamel.center;
      const md = new THREE.Vector3(next.x - prev.x, 0, next.z - prev.z);
      if (md.lengthSq() < 1e-9) md.set(1, 0, 0);
      md.normalize();
      const s = H(teeth[f]);
      meta[f] = {
        mdDir: md,
        genLenRel: s.y / (medLen || 1),
        genWidRel: Math.max(s.x, s.z) / (medWid || 1),
      };
    });
  }
  return meta;
}
function median(a) { if (!a.length) return 0; const s = [...a].sort((x, y) => x - y); return s[s.length >> 1]; }

// Layered teeth (enamel/dentine/pulp), carved at runtime from detections. Extracted
// verbatim from the original TeethViewer so the carve behaviour is unchanged (CLAUDE.md §6).
const GLB_URL = "/teeth_layered.glb";
// Pink gingiva (gusi), built in Blender from the same arch frame (blender/build_gums.py). Two
// meshes, Gum_Upper / Gum_Lower, whose coronal edge sits at the teeth's cervical line.
const GUM_URL = "/gums.glb";

function LayeredTeethModel({ detections, archMode, showGum, selected, hover, setSelected, setHover, onReady }) {
  const { scene } = useGLTF(GLB_URL);
  const { scene: gumScene } = useGLTF(GUM_URL);
  const groupRef = useRef();
  const stateRef = useRef({ teeth: {}, biteMidY: 0, centers: {}, scale: 1, gum: {} });

  // one-time setup: group meshes by FDI, own materials, arch framing data
  useEffect(() => {
    const teeth = {};
    const enamelCenters = [];
    scene.traverse((o) => {
      if (!o.isMesh || !o.geometry) return;
      const mm = /^T(\d+)_(Enamel|Dentine|Pulp)$/.exec(o.name);
      if (!mm) return;
      const fdi = +mm[1], layer = mm[2];
      o.geometry.computeBoundingBox();
      const box = o.geometry.boundingBox.clone();
      const center = box.getCenter(new THREE.Vector3());
      o.material = new THREE.MeshStandardMaterial({
        vertexColors: true, roughness: 0.5, metalness: 0.0, color: 0xffffff, envMapIntensity: 0.7,
      });
      o.castShadow = true; o.receiveShadow = true;
      o.userData.fdi = fdi; o.userData.layer = layer;
      teeth[fdi] = teeth[fdi] || { fdi, upper: Math.floor(fdi / 10) <= 2 };
      teeth[fdi][layer] = { mesh: o, center, box };
      snapshotBase(o); // capture the true GLB pristine before any morph/carve
      if (layer === "Enamel") enamelCenters.push(center);
    });

    for (const fdi of Object.keys(teeth)) restoreLayered(teeth[fdi]);
    stateRef.current.shapeMeta = buildShapeMeta(teeth);

    const ys = enamelCenters.map((c) => c.y).sort((a, b) => a - b);
    const biteMidY = (ys[0] + ys[ys.length - 1]) / 2;
    const list = Object.values(teeth);
    const mean = (arr) => arr.reduce((a, t) => a.add(t.Enamel.center), new THREE.Vector3())
      .multiplyScalar(1 / Math.max(arr.length, 1));
    const uppers = list.filter((t) => t.upper), lowers = list.filter((t) => !t.upper);
    const centers = { upper: mean(uppers), lower: mean(lowers), both: mean(list) };
    const sphere = new THREE.Box3().setFromObject(scene).getBoundingSphere(new THREE.Sphere());

    // gingiva: grab the two arch meshes, keep their pink GLB material, and make them
    // non-pickable so they never steal a tooth click/hover.
    const gum = {};
    gumScene.traverse((o) => {
      if (!o.isMesh) return;
      const arch = /Upper/i.test(o.name) ? "upper" : /Lower/i.test(o.name) ? "lower" : null;
      if (!arch) return;
      o.raycast = () => {};
      // Explicit coral-pink gingiva material; DoubleSide so it lights correctly regardless of
      // the boolean-cut face winding (and shows the socket walls).
      o.material = new THREE.MeshStandardMaterial({
        color: 0xd46b72, roughness: 0.62, metalness: 0.0, side: THREE.DoubleSide, envMapIntensity: 0.6,
      });
      o.castShadow = true; o.receiveShadow = true;
      gum[arch] = o;
    });

    stateRef.current = { teeth, biteMidY, centers, scale: 3.4 / sphere.radius, gum, gumScene };
    onReady?.(list.map((t) => t.fdi).sort((a, b) => a - b));
  }, [scene, gumScene, onReady]);

  // reframe on arch change; also hides gigi ompong (missing teeth) — kept here (not the carve
  // effect) so visibility survives an archMode toggle. Depends on detections so a new patient's
  // missing set re-applies.
  useEffect(() => {
    const { teeth, centers, scale, gum = {}, gumScene: gs } = stateRef.current;
    if (!Object.keys(teeth).length || !groupRef.current) return;
    for (const t of Object.values(teeth)) {
      const det = detections?.teeth?.[String(t.fdi)];
      const missing = !!det && (det.present === false || det.missing === true);
      const vis = !missing && (archMode === "both" || (archMode === "upper") === t.upper);
      for (const L of ["Enamel", "Dentine", "Pulp"]) if (t[L]) t[L].mesh.visible = vis;
    }
    const c = centers[archMode] || centers.both;
    scene.position.set(-c.x, -c.y, -c.z);
    // gingiva shares the teeth's frame -> same recentre so it tracks the arch, then per-arch
    // visibility gated on the "gusi" toggle.
    if (gs) gs.position.set(-c.x, -c.y, -c.z);
    if (gum.upper) gum.upper.visible = showGum && (archMode === "upper" || archMode === "both");
    if (gum.lower) gum.lower.visible = showGum && (archMode === "lower" || archMode === "both");
    groupRef.current.scale.setScalar(scale);
    groupRef.current.rotation.set(
      archMode === "upper" ? -Math.PI / 2 : archMode === "lower" ? Math.PI / 2 : -0.32, 0, 0
    );
  }, [archMode, scene, detections, showGum]);

  // (re)shape from the panoramic tooth-seg, then (re)carve, on detection change. The shape morph
  // rebuilds each tooth from its true pristine and re-baselines the carve, so switching patients
  // re-shapes AND re-carves cleanly.
  useEffect(() => {
    const { teeth, biteMidY, shapeMeta = {}, gum = {} } = stateRef.current;
    for (const t of Object.values(teeth)) {
      const det = detections?.teeth?.[String(t.fdi)];
      const m = shapeMeta[t.fdi] || {};
      // bendGain slightly >1: the panoramic projection foreshortens the true root curve, so we
      // restore a bit of it — keeps lengkung akar clearly legible while staying proportional.
      applyShapeLayered(t, det?.shape || null, biteMidY, { local: true, bendGain: 1.3, ...m });
      if (det && det.severity > 0)
        applyDamageLayered(t, det, biteMidY, { local: true, enamelScale: 1, inner: true });
      else restoreLayered(t);
    }
    // Skin the gingiva to the SAME shape morph so it always fits the (morphed) teeth — the gum is
    // a complementary add-on and follows the teeth, never the other way round. Uses the identical
    // per-tooth field the morph uses (bendGain 1.3, same shapeMeta), so the fit is exact.
    for (const [arch, seq] of [["upper", UPPER_SEQ], ["lower", LOWER_SEQ]]) {
      if (!gum[arch]) continue;
      const fields = [];
      for (const fdi of seq) {
        const t = teeth[fdi];
        if (!t?.Enamel) continue;
        const det = detections?.teeth?.[String(fdi)];
        const m = shapeMeta[fdi] || {};
        fields.push(buildToothMorphField(t.Enamel.mesh, det?.shape || null, biteMidY, { bendGain: 1.3, ...m }));
      }
      applyShapeGum(gum[arch], fields);
    }
  }, [detections]);

  // highlight selected / hovered tooth across all three layers
  useEffect(() => {
    const { teeth } = stateRef.current;
    for (const t of Object.values(teeth)) {
      const hex = t.fdi === selected ? 0x2a6cff : t.fdi === hover ? 0x1f7a4d : 0x000000;
      const inten = t.fdi === selected ? 0.6 : t.fdi === hover ? 0.45 : 1;
      for (const L of ["Enamel", "Dentine", "Pulp"]) {
        const m = t[L]?.mesh.material;
        if (m && m.emissive) { m.emissive.setHex(hex); m.emissiveIntensity = inten; }
      }
    }
  }, [selected, hover]);

  return (
    <group ref={groupRef}>
      <primitive
        object={scene}
        onPointerDown={(e) => { e.stopPropagation(); const fdi = e.object?.userData?.fdi; if (fdi) setSelected(fdi); }}
        onPointerOver={(e) => { e.stopPropagation(); setHover(e.object?.userData?.fdi ?? null); document.body.style.cursor = "pointer"; }}
        onPointerOut={() => { setHover(null); document.body.style.cursor = "auto"; }}
      />
      <primitive object={gumScene} />
    </group>
  );
}

/**
 * Reusable 3D dentition viewer.
 * @param {object}   detections    parsed detections.json (drives the carve)
 * @param {string}   archMode      "upper" | "lower" | "both"
 * @param {number}   selected      selected FDI (highlighted blue)
 * @param {(fdi:number)=>void} onSelectTooth  called when a tooth is clicked
 */
export default function Teeth3D({ detections, archMode = "upper", selected, onSelectTooth, onReady }) {
  const [hover, setHover] = useState(null);
  const [showGum, setShowGum] = useState(false);

  return (
    <div className="relative h-full w-full">
      <Canvas shadows camera={{ position: [0, 0.5, 7], fov: 42 }} dpr={[1, 2]}>
        <color attach="background" args={["#0e1116"]} />
        <hemisphereLight args={[0xffffff, 0x35404f, 0.9]} />
        <ambientLight intensity={0.35} />
        <directionalLight position={[4, 8, 6]} intensity={1.15} castShadow />
        <directionalLight position={[-6, 4, -3]} intensity={0.5} />
        <directionalLight position={[0, 2, -8]} intensity={0.35} />
        <React.Suspense fallback={null}>
          <LayeredTeethModel
            detections={detections}
            archMode={archMode}
            showGum={showGum}
            selected={selected}
            hover={hover}
            setSelected={(fdi) => onSelectTooth?.(fdi)}
            setHover={setHover}
            onReady={onReady}
          />
        </React.Suspense>
        <ContactShadows position={[0, -2.4, 0]} opacity={0.5} scale={12} blur={2.5} far={4} />
        <OrbitControls enablePan={false} minDistance={4} maxDistance={12} target={[0, 0, 0]} />
      </Canvas>
      {hover && hover !== selected ? (
        <div className="pointer-events-none absolute left-3 top-3 rounded-full bg-black/60 px-2.5 py-1 text-xs text-white">
          Gigi {hover}
        </div>
      ) : null}
      <button
        type="button"
        aria-pressed={showGum}
        onClick={() => setShowGum((v) => !v)}
        className={
          "absolute right-3 top-3 rounded-full px-3 py-1.5 text-xs font-medium shadow transition-colors " +
          (showGum ? "bg-[#d46b72] text-white" : "bg-black/60 text-white hover:bg-black/70")
        }
      >
        {showGum ? "Gusi: Aktif" : "Gusi: Nonaktif"}
      </button>
    </div>
  );
}

useGLTF.preload(GLB_URL);
useGLTF.preload(GUM_URL);
