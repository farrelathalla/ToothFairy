"use client";
import React, { useEffect, useMemo, useRef, useState } from "react";
import { Canvas, useThree } from "@react-three/fiber";
import { OrbitControls, useGLTF } from "@react-three/drei";
import * as THREE from "three";
import { ICDAS_LABEL, applyDamageLayered } from "../lib/damage";

/* Layer metadata. `reach` = the max ICDAS grade whose caries stops in this layer. */
const LAYERS = [
  { name: "Enamel",  color: "#f1eddd", reach: 2, blurb: "Hard outer shell" },
  { name: "Dentine", color: "#e6ca7e", reach: 4, blurb: "Softer middle layer" },
  { name: "Pulp",    color: "#c72e33", reach: 6, blurb: "Nerve & blood supply" },
];
const CAP_OFFSET = [0.001, 0.004, 0.008]; // tiny +X stagger so caps stack concentrically

function layerForGrade(g) {
  if (!g) return -1;                              // healthy: no caries
  return LAYERS.findIndex((l) => g <= l.reach);   // 0/1/2 = enamel/dentine/pulp
}

/* A solid layer, clipped by the sweep plane, with a stencil cap that fills the cut
   face so the section reads as solid enamel/dentine/pulp (not a hollow rim).
   Geometry is pre-normalized (centered + scaled), so the group is identity and the
   world-space clip plane + caps line up exactly. */
function makeLayer(geometry, color, plane, order) {
  const g = new THREE.Group();
  const col = new THREE.Color(color);

  const solid = new THREE.Mesh(
    geometry,
    new THREE.MeshStandardMaterial({
      color: col, roughness: 0.5, metalness: 0.02, side: THREE.DoubleSide,
      clippingPlanes: [plane], clipShadows: true,
    })
  );
  solid.renderOrder = 0;
  g.add(solid);

  // stencil: back faces ++ / front faces -- -> interior of the cut is nonzero.
  // The stencil meshes MUST be clipped by the same plane as the solid, or the cap
  // fills the tooth's full silhouette even when the solid is sliced away (a flat
  // "2D billboard" floating in space). `clone()` does not reliably carry
  // clippingPlanes, so set it explicitly on each.
  const base = new THREE.MeshBasicMaterial({
    depthWrite: false, depthTest: false, colorWrite: false,
    stencilWrite: true, stencilFunc: THREE.AlwaysStencilFunc,
  });
  const back = base.clone();
  back.side = THREE.BackSide;
  back.clippingPlanes = [plane];
  back.stencilFail = back.stencilZFail = back.stencilZPass = THREE.IncrementWrapStencilOp;
  const front = base.clone();
  front.side = THREE.FrontSide;
  front.clippingPlanes = [plane];
  front.stencilFail = front.stencilZFail = front.stencilZPass = THREE.DecrementWrapStencilOp;
  const sBack = new THREE.Mesh(geometry, back);
  const sFront = new THREE.Mesh(geometry, front);
  sBack.renderOrder = sFront.renderOrder = order;
  g.add(sBack, sFront);

  // cap: draws colour only where stencil != 0, then clears the buffer
  const capMat = new THREE.MeshStandardMaterial({
    color: col, roughness: 0.6, metalness: 0.0, side: THREE.DoubleSide,
    stencilWrite: true, stencilRef: 0, stencilFunc: THREE.NotEqualStencilFunc,
    stencilFail: THREE.ReplaceStencilOp, stencilZFail: THREE.ReplaceStencilOp,
    stencilZPass: THREE.ReplaceStencilOp,
  });
  const cap = new THREE.Mesh(new THREE.PlaneGeometry(6, 6), capMat);
  cap.rotation.y = Math.PI / 2;         // face +X, span the Y/Z cut plane
  cap.renderOrder = order + 0.5;
  cap.onAfterRender = (renderer) => renderer.clearStencil();
  g.add(cap);
  g.userData.cap = cap;
  return g;
}

// find a layer node by name prefix (the GLB may suffix duplicates, e.g. "Enamel.002")
function findLayer(nodes, key) {
  for (const n of Object.values(nodes)) {
    if (n && n.isMesh && typeof n.name === "string" && n.name.startsWith(key)) return n;
  }
  return null;
}

function Tooth({ url, tooth, clip, onBounds }) {
  const { nodes } = useGLTF(url);
  const { gl } = useThree();
  const plane = useMemo(() => new THREE.Plane(new THREE.Vector3(-1, 0, 0), 0), []);
  const grade = Math.max(0, Math.min(6, tooth?.severity || 0));

  useEffect(() => { gl.localClippingEnabled = true; }, [gl]);

  // Build the layered, carved, normalized geometry once per tooth/grade.
  const built = useMemo(() => {
    const geo = {};
    for (const L of LAYERS) {
      const src = findLayer(nodes, L.name);
      if (!src) return null;
      geo[L.name] = src.geometry.clone();        // clone -> never mutate the cache
    }

    // 1) carve the crown at runtime from the detection (crown is +Y in these files)
    geo.Enamel.computeBoundingBox();
    const ebox = geo.Enamel.boundingBox.clone();
    const ecenter = ebox.getCenter(new THREE.Vector3());
    const esize = ebox.getSize(new THREE.Vector3());
    const layers = {
      Enamel: { mesh: new THREE.Mesh(geo.Enamel), center: ecenter, box: ebox },
      Dentine: { mesh: new THREE.Mesh(geo.Dentine) },
      Pulp: { mesh: new THREE.Mesh(geo.Pulp) },
    };
    // biteMidY above the tooth -> crownSign = +1 -> carve toward +Y (the crown).
    // Same carve as the main view (full through the thin enamel) so the two match; the
    // slice then reveals how deep the lesion reaches (dentine D3-4, pulp D5-6).
    const biteMidY = ecenter.y + Math.max(esize.y, 1) * 2;
    if (grade > 0 && tooth)
      applyDamageLayered(layers, tooth, biteMidY, { local: true, enamelScale: 1, inner: true });

    // 2) normalize (center + scale to ~2.2) — bake into geometry so the group is
    //    identity and the world clip plane + caps align with the geometry.
    geo.Enamel.computeBoundingBox();
    const bb = geo.Enamel.boundingBox;
    const size = bb.getSize(new THREE.Vector3());
    const center = bb.getCenter(new THREE.Vector3());
    const S = 2.2 / Math.max(size.x, size.y, size.z, 1e-3);
    for (const L of LAYERS) {
      geo[L.name].translate(-center.x, -center.y, -center.z);
      geo[L.name].scale(S, S, S);
      geo[L.name].computeVertexNormals();
    }

    // 3) assemble the clipped + stencil-capped display group
    const grp = new THREE.Group();
    const caps = [];
    for (let i = 0; i < LAYERS.length; i++) {
      const layer = makeLayer(geo[LAYERS[i].name], LAYERS[i].color, plane, (i + 1) * 2);
      grp.add(layer);
      caps.push(layer.userData.cap);
    }
    const xHalf = (size.x * S) / 2; // normalized half-width along the cut axis
    return { grp, caps, xHalf };
  }, [nodes, plane, grade, tooth]);

  // report the usable slider range to the parent
  useEffect(() => { if (built) onBounds?.(built.xHalf); }, [built, onBounds]);

  // move the clip plane + all caps together on slider change. Hide the caps once the
  // plane clears the tooth so no cross-section fill is left floating at the extremes.
  useEffect(() => {
    if (!built) return;
    plane.constant = clip;
    const inside = clip > -built.xHalf * 0.995 && clip < built.xHalf * 0.995;
    built.caps.forEach((cap, i) => {
      cap.position.x = clip + CAP_OFFSET[i];
      cap.visible = inside;
    });
  }, [clip, plane, built]);

  if (!built) return null;
  return <primitive object={built.grp} />;
}

export default function ToothExaminer({ tooth, onClose }) {
  const grade = Math.max(0, Math.min(6, tooth?.severity || 0));
  const url = `/teeth_layer/tooth_${tooth.fdi}.glb`;
  const [xHalf, setXHalf] = useState(1.0);
  const [clip, setClip] = useState(0.0); // start at the mid-cut
  const li = layerForGrade(grade);

  useEffect(() => {
    const h = (e) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [onClose]);

  const range = Math.max(0.15, xHalf * 1.02);

  return (
    <div className="exwrap" onClick={onClose}>
      <div className="expanel" onClick={(e) => e.stopPropagation()}>
        <button className="exclose" onClick={onClose}>✕</button>
        <div className="exhead">
          <div className="extitle">
            <span className="exeyebrow">Cross-section · Tooth {tooth.fdi}{tooth.hidden ? " · 🩻 hidden lesion" : ""}</span>
            <h2 className="exh2">{grade ? `ICDAS D${grade} — ${ICDAS_LABEL[grade]}` : "Healthy tooth"}</h2>
            {tooth.hidden ? <span className="exeyebrow">Surface looks sound — a focal internal cavity found on the panoramic X-ray</span> : null}
          </div>
        </div>

        <div className="excanvas">
          <Canvas
            camera={{ position: [2.9, 1.2, 3.2], fov: 42 }}
            gl={{ localClippingEnabled: true, stencil: true, antialias: true }}
            dpr={[1, 2]}
          >
            <color attach="background" args={["#11151c"]} />
            <hemisphereLight args={[0xffffff, 0x2a323d, 1.0]} />
            <ambientLight intensity={0.4} />
            <directionalLight position={[5, 6, 5]} intensity={1.2} />
            <directionalLight position={[-4, 2, -3]} intensity={0.45} />
            <React.Suspense fallback={null}>
              <Tooth url={url} tooth={tooth} clip={clip} onBounds={setXHalf} />
            </React.Suspense>
            <OrbitControls enablePan={false} minDistance={2.5} maxDistance={9} target={[0, -0.1, 0]} />
          </Canvas>
        </div>

        <div className="exslider">
          <label>Cross-section sweep</label>
          <input
            type="range" min={-range} max={range} step={range / 220}
            value={Math.max(-range, Math.min(range, clip))}
            onChange={(e) => setClip(parseFloat(e.target.value))}
          />
          <div className="exhint">Drag to slice the tooth open · drag the model to rotate</div>
        </div>

        <div className="exlegend">
          {LAYERS.map((L, i) => {
            const reached = li >= 0 && i <= li;
            return (
              <div className={"exrow" + (i === li ? " hit" : "")} key={L.name}>
                <span className="exsw" style={{ background: L.color }} />
                <div className="exmeta">
                  <b>{L.name}</b>
                  <span>{L.blurb}</span>
                </div>
                <span className={"exbadge" + (reached ? " on" : "")}>
                  {i === li ? "caries reaches here" : reached ? "penetrated" : "intact"}
                </span>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
