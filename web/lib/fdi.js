import * as THREE from "three";

// ---------------------------------------------------------------------------
// Auto-map the 33 GLB meshes to FDI tooth codes purely from world geometry.
//
// Layout discovered from teeth.glb (see inference/inspect_glb.py):
//   * Y separates arches:  upper (maxilla) high Y, lower (mandible) low Y
//   * +X is the patient's LEFT (verified against the "LL"/"UL" node names)
//   * Z runs front->back: incisors high Z, molars low Z
//   * The per-quadrant metric  (|x - midX| - z)  increases monotonically from
//     the central incisor (pos 1) to the third molar (pos 8).
//   * One mesh is a degenerate sliver (bbox << teeth) -> skipped.
//
// FDI quadrants:  1 = upper-right, 2 = upper-left, 3 = lower-left, 4 = lower-right
// ---------------------------------------------------------------------------

export function collectToothMeshes(root) {
  const meshes = [];
  root.updateWorldMatrix(true, true);
  root.traverse((o) => {
    if (!o.isMesh || !o.geometry) return;
    o.geometry.computeBoundingBox();
    const box = o.geometry.boundingBox.clone().applyMatrix4(o.matrixWorld);
    const center = new THREE.Vector3();
    box.getCenter(center);
    const size = new THREE.Vector3();
    box.getSize(size);
    meshes.push({ mesh: o, center, diag: size.length(), box });
  });
  return meshes;
}

export function buildFdiMap(root) {
  let meshes = collectToothMeshes(root);
  // drop degenerate slivers (the 33rd junk mesh has diag ~0.03 vs ~2 for teeth)
  const diags = meshes.map((m) => m.diag).sort((a, b) => a - b);
  const medDiag = diags[Math.floor(diags.length / 2)];
  meshes = meshes.filter((m) => m.diag > medDiag * 0.25);

  const ys = meshes.map((m) => m.center.y).sort((a, b) => a - b);
  const xs = meshes.map((m) => m.center.x).sort((a, b) => a - b);
  const midY = (ys[0] + ys[ys.length - 1]) / 2;
  const midX = (xs[0] + xs[xs.length - 1]) / 2;
  const biteMidY = midY; // occlusal plane between the arches

  // group into quadrants
  const quads = { 1: [], 2: [], 3: [], 4: [] };
  for (const m of meshes) {
    const upper = m.center.y > midY;
    const left = m.center.x > midX; // +X = patient left
    let q;
    if (upper && !left) q = 1;
    else if (upper && left) q = 2;
    else if (!upper && left) q = 3;
    else q = 4;
    quads[q].push(m);
  }

  const fdiByUuid = new Map();
  const teeth = [];
  for (const q of [1, 2, 3, 4]) {
    const arr = quads[q];
    // order along the arch: (|x-midX| - z) ascending  => central incisor .. molar
    arr.sort(
      (a, b) =>
        Math.abs(a.center.x - midX) - a.center.z -
        (Math.abs(b.center.x - midX) - b.center.z)
    );
    arr.forEach((m, i) => {
      const pos = i + 1; // 1..8
      const fdi = q * 10 + pos;
      fdiByUuid.set(m.mesh.uuid, fdi);
      m.mesh.userData.fdi = fdi;
      teeth.push({ fdi, mesh: m.mesh, center: m.center, box: m.box, upper: q <= 2 });
    });
  }
  return { fdiByUuid, teeth, biteMidY, midX };
}
