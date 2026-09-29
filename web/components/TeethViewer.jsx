"use client";
import React, { useEffect, useMemo, useRef, useState } from "react";
import { Canvas } from "@react-three/fiber";
import { OrbitControls, useGLTF, ContactShadows } from "@react-three/drei";
import * as THREE from "three";
import { buildFdiMap } from "../lib/fdi";
import { applyDamage, restore, applyDamageLayered, restoreLayered, ICDAS_COLORS, ICDAS_LABEL } from "../lib/damage";
import ResultsGallery from "./ResultsGallery";
import ToothExaminer from "./ToothExaminer";
import "../styles/viewer.css";

const SEV_HEX = ICDAS_COLORS;

// Use the Blender-baked layered teeth (enamel/dentine/pulp, carved at runtime) for
// the main 3D view. Flip to false to revert to the single-shell teeth.glb + damage.js.
const USE_LAYERED = true;

function TeethModel({ detections, showDamage, archMode, selected, hover, setSelected, setHover, onReady }) {
  const { scene } = useGLTF("/teeth.glb");
  const groupRef = useRef();
  const stateRef = useRef({ teeth: [], biteMidY: 0, centers: {}, scale: 1 });

  // one-time setup: per-tooth materials, FDI map, per-arch framing data
  useEffect(() => {
    const { teeth, biteMidY } = buildFdiMap(scene);

    for (const t of teeth) {
      const m = new THREE.MeshStandardMaterial({
        vertexColors: true, roughness: 0.5, metalness: 0.0,
        color: 0xffffff, envMapIntensity: 0.7,
      });
      t.mesh.material = m;
      t.mesh.castShadow = true;
      t.mesh.receiveShadow = true;
    }

    // arch centres (in scene-local space, before the group transform)
    const mean = (arr) => arr.reduce((a, c) => a.add(c.center), new THREE.Vector3())
      .multiplyScalar(1 / Math.max(arr.length, 1));
    const upper = teeth.filter((t) => t.upper);
    const lower = teeth.filter((t) => !t.upper);
    const centers = {
      upper: mean(upper), lower: mean(lower), both: mean(teeth),
    };
    const sphere = new THREE.Box3().setFromObject(scene).getBoundingSphere(new THREE.Sphere());
    stateRef.current = { teeth, biteMidY, centers, scale: 3.4 / sphere.radius };
    onReady?.(teeth.map((t) => t.fdi).sort((a, b) => a - b));
  }, [scene, onReady]);

  // reframe when the arch view changes: recenter on the visible arch and orient
  // its occlusal plane toward the camera (upper -> look up, lower -> look down)
  useEffect(() => {
    const { teeth, centers, scale } = stateRef.current;
    if (!teeth.length || !groupRef.current) return;
    for (const t of teeth) {
      t.mesh.visible = archMode === "both" || (archMode === "upper") === t.upper;
    }
    const c = centers[archMode] || centers.both;
    scene.position.set(-c.x, -c.y, -c.z);
    groupRef.current.scale.setScalar(scale);
    // upper -> look up at the occlusal plane; lower -> look down at it;
    // both  -> natural frontal ("smile") view of the closed dentition.
    groupRef.current.rotation.set(
      archMode === "upper" ? -Math.PI / 2 : archMode === "lower" ? Math.PI / 2 : -0.32,
      0, 0
    );
  }, [archMode, scene]);

  // (re)apply damage whenever the toggle / detections change
  useEffect(() => {
    const { teeth, biteMidY } = stateRef.current;
    for (const t of teeth) {
      const det = detections?.teeth?.[String(t.fdi)];
      if (showDamage && det && det.severity > 0) applyDamage(t, det, biteMidY);
      else restore(t.mesh);
    }
  }, [detections, showDamage]);

  // highlight selected / hovered tooth
  useEffect(() => {
    const { teeth } = stateRef.current;
    for (const t of teeth) {
      const m = t.mesh.material;
      if (!m || !m.emissive) continue;
      if (t.fdi === selected) { m.emissive.setHex(0x2a6cff); m.emissiveIntensity = 0.6; }
      else if (t.fdi === hover) { m.emissive.setHex(0x1f7a4d); m.emissiveIntensity = 0.45; }
      else { m.emissive.setHex(0x000000); m.emissiveIntensity = 1; }
    }
  }, [selected, hover]);

  return (
    <group ref={groupRef}>
      <primitive
        object={scene}
        onPointerDown={(e) => {
          e.stopPropagation();
          const fdi = e.object?.userData?.fdi;
          if (fdi) setSelected(fdi);
        }}
        onPointerOver={(e) => {
          e.stopPropagation();
          setHover(e.object?.userData?.fdi ?? null);
          document.body.style.cursor = "pointer";
        }}
        onPointerOut={() => {
          setHover(null);
          document.body.style.cursor = "auto";
        }}
      />
    </group>
  );
}

// ---------------------------------------------------------------------------
// Layered variant: loads teeth_layered.glb (32 teeth x enamel/dentine/pulp,
// PRISTINE) and carves each tooth at runtime from detections. Same geometry as
// the cross-section examiner, so the two views match; nothing is baked, so a new
// patient's detections just re-carve. Meshes are named T<fdi>_<Layer>.
// ---------------------------------------------------------------------------
function LayeredTeethModel({ detections, showDamage, archMode, selected, hover, setSelected, setHover, onReady }) {
  const { scene } = useGLTF("/teeth_layered.glb");
  const groupRef = useRef();
  const stateRef = useRef({ teeth: {}, biteMidY: 0, centers: {}, scale: 1 });

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
      const box = o.geometry.boundingBox.clone();       // LOCAL = arch frame (Y-up)
      const center = box.getCenter(new THREE.Vector3());
      o.material = new THREE.MeshStandardMaterial({
        vertexColors: true, roughness: 0.5, metalness: 0.0, color: 0xffffff, envMapIntensity: 0.7,
      });
      o.castShadow = true; o.receiveShadow = true;
      o.userData.fdi = fdi; o.userData.layer = layer;
      teeth[fdi] = teeth[fdi] || { fdi, upper: Math.floor(fdi / 10) <= 2 };
      teeth[fdi][layer] = { mesh: o, center, box };
      if (layer === "Enamel") enamelCenters.push(center);
    });

    // paint pristine anatomical colours + snapshot pristine geometry. The inner layers
    // stay in the scene: healthy teeth read as solid white (thin enamel covers them),
    // and severe lesions carve through the thin enamel to expose dentine/pulp for real.
    for (const fdi of Object.keys(teeth)) restoreLayered(teeth[fdi]);

    const ys = enamelCenters.map((c) => c.y).sort((a, b) => a - b);
    const biteMidY = (ys[0] + ys[ys.length - 1]) / 2;
    const list = Object.values(teeth);
    const mean = (arr) => arr.reduce((a, t) => a.add(t.Enamel.center), new THREE.Vector3())
      .multiplyScalar(1 / Math.max(arr.length, 1));
    const uppers = list.filter((t) => t.upper), lowers = list.filter((t) => !t.upper);
    const centers = { upper: mean(uppers), lower: mean(lowers), both: mean(list) };
    const sphere = new THREE.Box3().setFromObject(scene).getBoundingSphere(new THREE.Sphere());
    stateRef.current = { teeth, biteMidY, centers, scale: 3.4 / sphere.radius };
    onReady?.(list.map((t) => t.fdi).sort((a, b) => a - b));
  }, [scene, onReady]);

  // reframe on arch change (mirrors the single-shell view)
  useEffect(() => {
    const { teeth, centers, scale } = stateRef.current;
    if (!Object.keys(teeth).length || !groupRef.current) return;
    for (const t of Object.values(teeth)) {
      const vis = archMode === "both" || (archMode === "upper") === t.upper;
      for (const L of ["Enamel", "Dentine", "Pulp"]) if (t[L]) t[L].mesh.visible = vis;
    }
    const c = centers[archMode] || centers.both;
    scene.position.set(-c.x, -c.y, -c.z);
    groupRef.current.scale.setScalar(scale);
    groupRef.current.rotation.set(
      archMode === "upper" ? -Math.PI / 2 : archMode === "lower" ? Math.PI / 2 : -0.32, 0, 0
    );
  }, [archMode, scene]);

  // (re)carve on toggle / detection change — runs in geometry-local space (local=true).
  // Thin enamel + full carve: D1-D2 leave the tooth white, D3+ break through the enamel
  // to expose dentine, D5-D6 reach the pulp — the caries reveal is anatomical, not tinted.
  useEffect(() => {
    const { teeth, biteMidY } = stateRef.current;
    for (const t of Object.values(teeth)) {
      const det = detections?.teeth?.[String(t.fdi)];
      if (showDamage && det && det.severity > 0)
        applyDamageLayered(t, det, biteMidY, { local: true, enamelScale: 1, inner: true });
      else restoreLayered(t);
    }
  }, [detections, showDamage]);

  // highlight selected / hovered tooth across all three of its layers
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
    </group>
  );
}

// Backend base URL (FastAPI). Configurable for deployment; defaults to local dev.
const API_BASE = (typeof process !== "undefined" && process.env.NEXT_PUBLIC_API_URL) || "http://localhost:8000";
const UPLOAD_SLOTS = [
  { key: "front", label: "Front" },
  { key: "up", label: "Upper (occlusal)" },
  { key: "bottom", label: "Lower (occlusal)" },
  { key: "side_left", label: "Side Left" },
  { key: "side_right", label: "Side Right" },
  { key: "panoramic", label: "Panoramic X-ray" },
];

function UploadPanel({ onClose, onGenerated }) {
  const [files, setFiles] = useState({});
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null);
  const nFiles = Object.values(files).filter(Boolean).length;

  const pick = (key, file) => setFiles((f) => ({ ...f, [key]: file || undefined }));

  const generate = async () => {
    setBusy(true); setMsg(null);
    try {
      const fd = new FormData();
      for (const { key } of UPLOAD_SLOTS) if (files[key]) fd.append(key, files[key]);
      const res = await fetch(API_BASE + "/generate", { method: "POST", body: fd });
      if (!res.ok) throw new Error("HTTP " + res.status);
      const entry = await res.json();
      onGenerated(entry);
    } catch (e) {
      setMsg("Couldn't reach the inference backend at " + API_BASE +
        ". Generation runs the AI models server-side — start it (uvicorn inference.server:app) " +
        "or deploy it. The demo captures on the left work fully offline.");
      setBusy(false);
    }
  };

  return (
    <div className="modal" onClick={onClose}>
      <div className="modalcard upl" onClick={(e) => e.stopPropagation()}>
        <div className="modalhead">
          <h2>Upload a patient capture</h2>
          <button className="mclose" onClick={onClose}>✕</button>
        </div>
        <p className="sub">Add any of the 5 standard intraoral views + the panoramic. You can
          upload just one view — teeth not visible in any view are treated as healthy unless the
          panoramic flags a hidden lesion.</p>
        <div className="uplgrid">
          {UPLOAD_SLOTS.map(({ key, label }) => (
            <label key={key} className={"uplslot" + (files[key] ? " has" : "")}>
              <input type="file" accept="image/*" style={{ display: "none" }}
                onChange={(e) => pick(key, e.target.files?.[0])} />
              {files[key] ? (
                <img src={URL.createObjectURL(files[key])} alt={label} />
              ) : <div className="uplplus">+</div>}
              <span className="upllabel">{label}</span>
              {files[key] && <span className="uplname">{files[key].name}</span>}
            </label>
          ))}
        </div>
        {msg && <p className="note warn">{msg}</p>}
        <div className="uplactions">
          <button className="clear" onClick={onClose}>Cancel</button>
          <button className="examine" disabled={busy || nFiles === 0} onClick={generate}>
            {busy ? "Generating… (running the models)" : `Generate 3D · ${nFiles} image${nFiles === 1 ? "" : "s"}`}
          </button>
        </div>
      </div>
    </div>
  );
}

export default function TeethViewer() {
  const [detections, setDetections] = useState(null);
  const [showDamage, setShowDamage] = useState(true);
  const [archMode, setArchMode] = useState("upper");
  const [selected, setSelected] = useState(null);
  const [hover, setHover] = useState(null);
  const [presentFdis, setPresentFdis] = useState([]);
  const [examine, setExamine] = useState(null); // tooth being cross-sectioned
  const [datasets, setDatasets] = useState([]);
  const [datasetId, setDatasetId] = useState(null);
  const [showUpload, setShowUpload] = useState(false);
  const [loadingDet, setLoadingDet] = useState(false);

  // dataset manifest -> pick the default patient (prefers "original")
  useEffect(() => {
    fetch("/results/datasets.json")
      .then((r) => r.json())
      .then((m) => {
        const list = m.datasets || [];
        setDatasets(list);
        const def = list.find((d) => d.id === "original") || list[0];
        setDatasetId((cur) => cur || def?.id || null);
      })
      .catch(() => {
        // no manifest yet: fall back to the legacy single detections.json
        fetch("/detections.json").then((r) => r.json()).then(setDetections).catch(() => {});
      });
  }, []);

  const base = datasetId ? `/results/${datasetId}/` : null;
  const dataset = datasets.find((d) => d.id === datasetId) || null;

  // load the selected patient's detections
  useEffect(() => {
    if (!base) return;
    setLoadingDet(true);
    setSelected(null); setExamine(null); setHover(null);
    fetch(base + "detections.json")
      .then((r) => r.json())
      .then((d) => { setDetections(d); setLoadingDet(false); })
      .catch(() => setLoadingDet(false));
  }, [base]);

  // add a freshly-generated upload to the picker and select it
  const onGenerated = (entry) => {
    setDatasets((ds) => [...ds.filter((d) => d.id !== entry.id), entry]);
    setDatasetId(entry.id);
    setShowUpload(false);
  };

  const affected = useMemo(() => {
    if (!detections) return [];
    return Object.values(detections.teeth)
      .filter((t) => t.severity > 0)
      .sort((a, b) => b.severity - a.severity || a.fdi - b.fdi);
  }, [detections]);

  const sel = selected && detections ? detections.teeth[String(selected)] : null;

  return (
    <div className="wrap">
      <Canvas shadows camera={{ position: [0, 0.5, 7], fov: 42 }} dpr={[1, 2]}>
        <color attach="background" args={["#0e1116"]} />
        <hemisphereLight args={[0xffffff, 0x35404f, 0.9]} />
        <ambientLight intensity={0.35} />
        <directionalLight position={[4, 8, 6]} intensity={1.15} castShadow />
        <directionalLight position={[-6, 4, -3]} intensity={0.5} />
        <directionalLight position={[0, 2, -8]} intensity={0.35} />
        <React.Suspense fallback={null}>
          {USE_LAYERED ? (
            <LayeredTeethModel
              detections={detections} showDamage={showDamage} archMode={archMode}
              selected={selected} hover={hover} setSelected={setSelected}
              setHover={setHover} onReady={setPresentFdis}
            />
          ) : (
            <TeethModel
              detections={detections} showDamage={showDamage} archMode={archMode}
              selected={selected} hover={hover} setSelected={setSelected}
              setHover={setHover} onReady={setPresentFdis}
            />
          )}
        </React.Suspense>
        <ContactShadows position={[0, -2.4, 0]} opacity={0.5} scale={12} blur={2.5} far={4} />
        <OrbitControls enablePan={false} minDistance={4} maxDistance={12} target={[0, 0, 0]} />
      </Canvas>

      {/* ---------- overlay UI ---------- */}
      <div className="panel left">
        <h1>ToothFairy · 3D Reconstruction</h1>
        <p className="sub">Detection-driven caries reconstruction (ICDAS D1–D6)</p>

        {/* ---- patient / dataset picker ---- */}
        <div className="dsblock">
          <div className="dshead">
            <span>Patient capture</span>
            <button className="uploadbtn" onClick={() => setShowUpload(true)}>+ Upload</button>
          </div>
          <div className="dsgrid">
            {datasets.map((d) => (
              <button key={d.id}
                className={"dscard" + (datasetId === d.id ? " on" : "")}
                onClick={() => setDatasetId(d.id)}
                title={`${d.views?.length || 0} view(s)${d.has_panoramic ? " + panoramic" : ""}`}>
                {d.thumb ? <img src={"/" + d.thumb} alt={d.label} loading="lazy" /> : <div className="dsnothumb" />}
                <span className="dslabel">{d.label}</span>
                <span className="dsmeta">{(d.views?.length || 0)}v{d.has_panoramic ? " · 🩻" : ""}</span>
              </button>
            ))}
          </div>
          {dataset && (
            <div className="dsviews">
              {(dataset.views || []).map((v) => <span key={v.key} className="vchip">{v.label}</span>)}
              {dataset.has_panoramic && <span className="vchip pano">Panoramic</span>}
            </div>
          )}
          {loadingDet && <div className="dsloading">Loading detections…</div>}
        </div>

        <label className="toggle">
          <input type="checkbox" checked={showDamage} onChange={(e) => setShowDamage(e.target.checked)} />
          <span>{showDamage ? "Showing detected damage" : "Showing healthy baseline"}</span>
        </label>

        <div className="seg">
          {["upper", "lower", "both"].map((m) => (
            <button key={m} className={"segbtn" + (archMode === m ? " on" : "")}
              onClick={() => setArchMode(m)}>
              {m === "upper" ? "Upper arch" : m === "lower" ? "Lower arch" : "Both"}
            </button>
          ))}
        </div>

        <div className="legend">
          {ICDAS_LABEL.map((lab, i) => (
            <div className="legrow" key={i}>
              <span className="sw" style={{ background: SEV_HEX[i] }} />
              <span>{lab}</span>
            </div>
          ))}
        </div>

        <h2>Affected teeth ({affected.length})</h2>
        <div className="tlist">
          {affected.map((t) => (
            <button
              key={t.fdi}
              className={"trow" + (selected === t.fdi ? " on" : "")}
              onMouseEnter={() => setHover(t.fdi)}
              onMouseLeave={() => setHover(null)}
              onClick={() => setSelected(t.fdi)}
            >
              <span className="dot" style={{ background: SEV_HEX[t.severity] }} />
              <b>{t.fdi}</b>
              <span className="grade">D{t.severity}</span>
              {t.hidden && <span className="hiddenbadge" title="Internal lesion — panoramic X-ray only, not visible on the surface">🩻 hidden</span>}
              <span className="src">{(t.sources || []).join(" · ")}</span>
            </button>
          ))}
        </div>
      </div>

      <div className="panel right">
        {sel ? (
          <>
            <div className="fdibig" style={{ borderColor: SEV_HEX[sel.severity] }}>{sel.fdi}</div>
            <h2>Tooth {sel.fdi}</h2>
            <div className="kv"><span>ICDAS grade</span><b style={{ color: SEV_HEX[sel.severity] }}>{sel.severity ? "D" + sel.severity : "Healthy"}</b></div>
            <div className="kv"><span>{ICDAS_LABEL[sel.severity]}</span></div>
            <div className="kv"><span>Crown affected</span><b>{Math.round((sel.caries_ratio || 0) * 100)}%</b></div>
            <div className="kv"><span>Lesions detected</span><b>{sel.lesions?.length || 0}</b></div>
            <div className="kv"><span>Detected by</span><b>{(sel.sources || []).join(", ") || "—"}</b></div>
            {sel.hidden ? (
              <p className="note hidden">🩻 <b>Hidden internal lesion.</b> Found on the panoramic X-ray —
                the surface looks sound while a focal cavity sits inside the tooth.
                Open the cross-section to see the hollow.</p>
            ) : sel.notes ? <p className="note">{sel.notes}</p> : null}
            <button className="examine" onClick={() => setExamine(sel)}>
              🔎 Examine cross-section
            </button>
            <button className="clear" onClick={() => setSelected(null)}>Clear selection</button>
          </>
        ) : (
          <>
            <h2>Inspect a tooth</h2>
            <p className="sub">Click any tooth in the 3D view, or pick one from the list.</p>
            {hover && detections?.teeth?.[String(hover)] && (
              <div className="hovercard">
                <b>{hover}</b> — {detections.teeth[String(hover)].severity
                  ? "D" + detections.teeth[String(hover)].severity
                  : "Healthy"}
              </div>
            )}
            {detections?.meta && (
              <div className="meta">
                <p><b>Models</b></p>
                <ul>
                  {Object.entries(detections.meta.models).map(([k, v]) => (
                    <li key={k}><span>{k}</span>: {v}</li>
                  ))}
                </ul>
                <p className="note">{detections.meta.note}</p>
              </div>
            )}
          </>
        )}
      </div>
      {hover && !selected ? <div className="hovertag">Tooth {hover}</div> : null}

      <ResultsGallery base={base} key={datasetId} />

      {examine ? <ToothExaminer tooth={examine} onClose={() => setExamine(null)} /> : null}
      {showUpload ? <UploadPanel onClose={() => setShowUpload(false)} onGenerated={onGenerated} /> : null}
    </div>
  );
}

useGLTF.preload(USE_LAYERED ? "/teeth_layered.glb" : "/teeth.glb");
