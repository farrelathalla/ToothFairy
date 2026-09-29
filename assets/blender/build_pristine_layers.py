# Build PRISTINE, watertight, layered (enamel/dentine/pulp) teeth from teeth.glb.
# NO destruction is baked here -- the app carves each tooth at runtime from
# detections.json, so a new patient's image just changes the carve (no re-bake).
#
# Outputs (identical geometry, placed differently):
#   web/public/teeth_layer/tooth_<fdi>.glb  -- one tooth, centered + crown->+Y,
#        nodes named Enamel/Dentine/Pulp        (consumed by ToothExaminer)
#   web/public/teeth_layered.glb             -- all 32 teeth in ARCH position,
#        nodes named T<fdi>_Enamel/_Dentine/_Pulp (consumed by the main 3D view)
#
# MCP body: sets `result`. Runs in the user's live Blender; cleans up after itself.
import bpy, bmesh, math, os
from mathutils import Matrix, Vector

# Repo root: set TOOTHFAIRY_REPO, else derive from this file (assets/blender/x.py -> ../..).
REPO = os.environ.get("TOOTHFAIRY_REPO") or os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__ if "__file__" in dir() else os.getcwd()))))
GLB = os.path.join(REPO, "web", "public", "teeth.glb")
OUTDIR = os.path.join(REPO, "web", "public", "teeth_layer")
COMBINED = os.path.join(REPO, "web", "public", "teeth_layered.glb")
os.makedirs(OUTDIR, exist_ok=True)

ONLY_FDI = []            # empty -> all 32
# ANATOMICAL layers via INWARD NORMAL OFFSET of the real tooth surface (not uniform
# scaling): dentine = tooth pushed in by a thin enamel thickness (so dentine is the
# bulk, filling crown core + whole root); pulp = pushed in further, which naturally
# forms horns under the cusps and canals down the roots. Deciduous/pediatric ratios
# (ref: gigi sulung) -> thin enamel, LARGE pulp with horns near the surface.
# Offsets are fractions of each tooth's own crown half-width, so any input tooth works.
ENAMEL_FRAC = 0.20       # enamel thickness (thin cap)
DENTINE_FRAC = 0.24      # dentine thickness; pulp starts at (ENAMEL+DENTINE)*R inward
DECIMATE = 0.45          # keep files light; enough verts for a smooth runtime carve
VOX_FRAC = 0.012         # voxel remesh size as a fraction of the tooth's bbox diagonal

COLORS = {"Enamel": (0.945, 0.930, 0.870, 1), "Dentine": (0.902, 0.792, 0.494, 1),
          "Pulp": (0.780, 0.180, 0.200, 1)}

def mat(key):
    m = bpy.data.materials.new(key)
    m.use_nodes = True
    b = m.node_tree.nodes.get("Principled BSDF")
    if b:
        b.inputs["Base Color"].default_value = COLORS[key]
        if "Roughness" in b.inputs: b.inputs["Roughness"].default_value = 0.45
    m.diffuse_color = COLORS[key]
    return m

def vbounds(me):
    xs = [v.co.x for v in me.vertices]; ys = [v.co.y for v in me.vertices]; zs = [v.co.z for v in me.vertices]
    return Vector((min(xs), min(ys), min(zs))), Vector((max(xs), max(ys), max(zs)))

# ---- import teeth.glb, bake world transforms into vertices ----
before = set(bpy.data.objects.keys())
bpy.ops.import_scene.gltf(filepath=GLB)
new = [bpy.data.objects[n] for n in (set(bpy.data.objects.keys()) - before)]
meshes = []
for ob in new:
    if ob.type != "MESH":
        continue
    ob.data.transform(ob.matrix_world.copy())     # bake Z-up upright world into verts
    ob.parent = None
    ob.matrix_world = Matrix.Identity(4)
    lo, hi = vbounds(ob.data)
    meshes.append({"ob": ob, "c": (lo + hi) / 2, "diag": (hi - lo).length})

diags = sorted(m["diag"] for m in meshes); med = diags[len(diags) // 2]
meshes = [m for m in meshes if m["diag"] > med * 0.25]   # drop the degenerate sliver

# Blender frame after glTF import: up=Z, +X=patient-left, front/back=Y.
zs = sorted(m["c"].z for m in meshes); xs = sorted(m["c"].x for m in meshes)
midZ = (zs[0] + zs[-1]) / 2; midX = (xs[0] + xs[-1]) / 2
quads = {1: [], 2: [], 3: [], 4: []}
for m in meshes:
    upper = m["c"].z > midZ; left = m["c"].x > midX
    q = 1 if (upper and not left) else 2 if (upper and left) else 3 if (not upper and left) else 4
    m["upper"] = upper; quads[q].append(m)
fdi_of = {}
for q in (1, 2, 3, 4):
    arr = sorted(quads[q], key=lambda m: abs(m["c"].x - midX) + m["c"].y)
    for i, m in enumerate(arr):
        fdi_of[id(m["ob"])] = q * 10 + (i + 1)

def bake_mod(ob):
    dg = bpy.context.evaluated_depsgraph_get()
    nm = bpy.data.meshes.new_from_object(ob.evaluated_get(dg))
    ob.modifiers.clear(); old = ob.data; ob.data = nm
    if old.users == 0: bpy.data.meshes.remove(old)

def watertight(ob, vs):
    md = ob.modifiers.new("rm", "REMESH"); md.mode = "VOXEL"; md.voxel_size = vs; md.adaptivity = 0.0
    bake_mod(ob)

def decimate(ob, ratio):
    md = ob.modifiers.new("dec", "DECIMATE"); md.ratio = ratio
    bake_mod(ob)

def offset_inward(src_data, key, dist, voxel):
    # Push every vertex inward along its normal by `dist`, then voxel-remesh to heal
    # the self-intersections into a clean watertight solid. In CONCAVE regions (root
    # furcations, cervical) the normal points such that this can bulge outward -- the
    # caller must clip the result to a container so it stays inside the tooth.
    me = src_data.copy()
    bm = bmesh.new(); bm.from_mesh(me); bm.normal_update()
    for v in bm.verts:
        v.co -= v.normal * dist
    bm.to_mesh(me); bm.free()
    ob = bpy.data.objects.new(key, me)
    bpy.context.scene.collection.objects.link(ob)
    md = ob.modifiers.new("rm", "REMESH"); md.mode = "VOXEL"; md.voxel_size = voxel; md.adaptivity = 0.0
    bake_mod(ob)
    if len(ob.data.vertices) < 8:          # layer collapsed to nothing -> skip it
        bpy.data.objects.remove(ob, do_unlink=True); return None
    return ob

def clip_to(ob, container):
    # Boolean-INTERSECT so `ob` is strictly inside `container` (no dentine/pulp poking
    # out of the enamel at the roots/furcation). Where the offset bulged out, the layer
    # is clipped back to the surface -- which reads correctly (roots have no enamel).
    md = ob.modifiers.new("clip", "BOOLEAN"); md.operation = "INTERSECT"
    md.object = container; md.solver = "EXACT"
    bake_mod(ob)

def finish_layer(ob, key):
    decimate(ob, DECIMATE)
    if len(ob.data.vertices) < 8:
        bpy.data.objects.remove(ob, do_unlink=True); return None
    ob.data.materials.clear(); ob.data.materials.append(mat(key))
    return ob

def select_only(objs, active):
    for o in bpy.context.view_layer.objects:
        try: o.select_set(False)
        except Exception: pass
    for o in objs: o.select_set(True)
    bpy.context.view_layer.objects.active = active

written = []; errors = {}; info = {}; arch_layers = []
def process(m):
    ob = m["ob"]; fdi = fdi_of[id(ob)]; c = m["c"]; upper = m["upper"]
    ang = 90 if upper else -90
    # centre at origin, rotate so the crown points to +Y (examiner's expected frame)
    ob.data.transform(Matrix.Translation(-c))
    ob.data.transform(Matrix.Rotation(math.radians(ang), 4, "X"))
    vox = max(0.005, m["diag"] * VOX_FRAC)
    watertight(ob, vox)
    decimate(ob, DECIMATE)
    ob.name = "Enamel"; ob.data.materials.clear(); ob.data.materials.append(mat("Enamel"))
    # representative crown half-width -> offset distances scale with each tooth
    e_lo, e_hi = vbounds(ob.data)
    Ravg = 0.25 * ((e_hi.x - e_lo.x) + (e_hi.z - e_lo.z))
    t_e = ENAMEL_FRAC * Ravg
    t_p = (ENAMEL_FRAC + DENTINE_FRAC) * Ravg
    dentine = offset_inward(ob.data, "Dentine", t_e, vox)
    if dentine:
        clip_to(dentine, ob)                    # dentine strictly inside the enamel
        dentine = finish_layer(dentine, "Dentine")
    pulp = offset_inward(ob.data, "Pulp", t_p, vox)
    if pulp:
        clip_to(pulp, dentine if dentine else ob)  # pulp strictly inside the dentine
        pulp = finish_layer(pulp, "Pulp")
    named = [(ob, "Enamel")] + ([(dentine, "Dentine")] if dentine else []) \
            + ([(pulp, "Pulp")] if pulp else [])
    layers = [o for o, _ in named]

    # (1) per-tooth centered file for the examiner (yup=False keeps crown -> +Y)
    select_only(layers, ob)
    out = os.path.join(OUTDIR, "tooth_%d.glb" % fdi)
    bpy.ops.export_scene.gltf(filepath=out, export_format="GLB",
        use_selection=True, export_apply=True, export_yup=False)

    # (2) transform the SAME meshes back into arch position for the combined file
    Rinv = Matrix.Rotation(math.radians(-ang), 4, "X")
    for L, key in named:
        L.data.transform(Rinv)
        L.data.transform(Matrix.Translation(c))
        L.name = "T%d_%s" % (fdi, key)
        arch_layers.append(L)

    lo, hi = vbounds(ob.data)
    info[fdi] = {"verts": len(ob.data.vertices), "upper": upper,
                 "bbox": [round(v, 2) for v in (*lo, *hi)]}
    written.append("tooth_%d.glb" % fdi)

try:
    for m in meshes:
        fdi = fdi_of[id(m["ob"])]
        if ONLY_FDI and fdi not in ONLY_FDI:
            bpy.data.objects.remove(m["ob"], do_unlink=True); continue
        try:
            process(m)
        except Exception:
            import traceback; errors[fdi] = traceback.format_exc().splitlines()[-1]

    # (3) combined arch file for the main 3D view (yup=True -> standard glTF Y-up,
    #     same frame the app already uses for teeth.glb)
    if arch_layers:
        select_only(arch_layers, arch_layers[0])
        bpy.ops.export_scene.gltf(filepath=COMBINED, export_format="GLB",
            use_selection=True, export_apply=True, export_yup=True)
finally:
    for o in list(bpy.data.objects):
        if o.name not in before:
            try: bpy.data.objects.remove(o, do_unlink=True)
            except Exception: pass
    for coll in (bpy.data.meshes, bpy.data.materials):
        for dta in list(coll):
            if dta.users == 0:
                try: coll.remove(dta)
                except Exception: pass

result = {"written": sorted(written), "count": len(written), "errors": errors,
          "combined": os.path.basename(COMBINED), "arch_objs": len(arch_layers),
          "sample": {k: info[k] for k in list(info)[:4]}}
