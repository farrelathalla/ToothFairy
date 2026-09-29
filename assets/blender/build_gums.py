# Build PINK GUMS — natural gingiva that FULLY covers the roots and never intrudes into a tooth.
#
# (Rewritten 2026-07-13. The two previous approaches both failed the dentist's spec:
#   * build_gums_OLD_tube.py.bak      — swept a fat elliptical tube -> unnatural swollen roll.
#   * build_gums_OLD_rootblob.py.bak  — built the gum FROM inflated tooth ROOTS + voxel remesh.
#     Thin roots poked THROUGH the thin inflated layer (akar keluar gusi) and the lumpy voxel
#     surface dipped INTO the crowns (gusi masuk ke dalam gigi). Rejected by the dentist.
# Target look: a smooth solid pink ridge, every root buried, crowns
# emerging cleanly at a scalloped margin with interdental papillae.)
#
# THE ROBUST IDEA (what makes this satisfy both hard requirements by construction):
#   gum  =  SOLID arch ridge (a blob big enough to fully ENCLOSE every root)   MINUS   the TEETH
#   1. Ridge  : per tooth, an ellipsoid centred on the ROOT, wide enough buccolingually to sit
#      OUTSIDE the root, tall enough to reach from a papilla height (just past the cervical line,
#      toward the crown) down past the apex; union them + a connective bar -> VOXEL remesh ->
#      ONE smooth solid that contains all roots.  => a root can NEVER be exposed: it lives inside
#      the solid.
#   2. Subtract: the full teeth (enamel, slightly inflated so there's a hairline socket gap),
#      voxel-remeshed into a clean manifold cutter, EXACT boolean DIFFERENCE.  => the gum can
#      NEVER intrude into a tooth: that volume is carved away.  The crowns emerge, and the
#      interdental embrasures (no tooth to carve there) stay high -> natural papillae + scallop.
#
# Both operands are voxel-remeshed manifolds, so the EXACT boolean is stable (the old fragmenting
# boolean subtracted NON-manifold clipped-crown shells — not this).
#
# Output: web/public/gums.glb -> Gum_Upper / Gum_Lower (same arch frame as teeth_layered.glb).
# MCP body: sets `result`. Runs in the user's live Blender; cleans up after itself.
import bpy, bmesh, os, re, math
from mathutils import Vector, Matrix

# Repo root: set TOOTHFAIRY_REPO, else derive from this file (assets/blender/x.py -> ../..).
REPO = os.environ.get("TOOTHFAIRY_REPO") or os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__ if "__file__" in dir() else os.getcwd()))))
GLB = os.path.join(REPO, "web", "public", "teeth_layered.glb")
OUT = os.path.join(REPO, "web", "public", "gums.glb")

# --- tunables (fractions of each tooth's own height H unless noted; overridable from a driver) ---
CROWN_FRAC  = globals().get("CROWN_FRAC", 0.35)  # cervical plane = crown_tip + CROWN_FRAC*(apex-crown_tip). Larger => gumline sits higher up the tooth (more root covered / less crown shown)
PAPILLA     = globals().get("PAPILLA", 0.08)     # how far the ridge rises PAST the cervical toward the crown (fraction H) -> interdental papilla height; over a tooth face the tooth-subtraction trims it back to the neck => scallop
PAD_BL      = globals().get("PAD_BL", 0.05)      # buccolingual padding (absolute units) added to each tooth NECK half-width so the ridge sits just OUTSIDE the root -> roots covered but the gum doesn't bulge past the (wider) crown. Must be enough that the inflated tooth cutter can't pierce the lingual wall (pinholes)
WIDEN       = globals().get("WIDEN", 1.14)       # buccolingual widening of the ridge cross-section (fuller wall, no lingual pokethrough)
BASE_EXT    = globals().get("BASE_EXT", 0.10)    # extend the ridge apically PAST the apex (absolute) -> a solid gum mass behind the roots, apex well inside the blob (not at its narrowing pole)
NECK_BAND   = globals().get("NECK_BAND", 0.14)   # half-thickness (fraction H) of the band around the cervical plane used to measure the tooth's NECK width -> the ridge is sized to the NECK/root, not the crown, so crowns emerge proud of the gum (image3)
CUT_INFLATE = globals().get("CUT_INFLATE", 1.022)# inflate the tooth cutter about each tooth centre -> a hairline socket gap so the gum hugs, not z-fights, the tooth (kept small so it doesn't punch through the wall)
VOX         = globals().get("VOX", 0.028)        # voxel remesh size (smaller = finer/heavier)
SMOOTH_ITERS= globals().get("SMOOTH_ITERS", 10)
N_RING      = globals().get("N_RING", 28)        # cross-section resolution of the swept wall
INTERP      = globals().get("INTERP", 4)         # loft subdivisions between adjacent tooth stations (higher = smoother arch)
GUM_COLOR = (0.86, 0.44, 0.46, 1.0)

UPPER_SEQ = [18, 17, 16, 15, 14, 13, 12, 11, 21, 22, 23, 24, 25, 26, 27, 28]
LOWER_SEQ = [48, 47, 46, 45, 44, 43, 42, 41, 31, 32, 33, 34, 35, 36, 37, 38]


def gum_material():
    m = bpy.data.materials.new("Gingiva")
    m.use_nodes = True
    b = m.node_tree.nodes.get("Principled BSDF")
    if b:
        b.inputs["Base Color"].default_value = GUM_COLOR
        if "Roughness" in b.inputs:
            b.inputs["Roughness"].default_value = 0.62
    m.diffuse_color = GUM_COLOR
    return m


# ---- self-clean leftovers (empties survive a mesh-only purge and name-clash the next build) ----
for ob in list(bpy.data.objects):
    if ob.type == "MESH" or ob.name.startswith(("Gum", "GumRoot", "GumBase", "GumBar", "Crown", "Cutter", "T")):
        bpy.data.objects.remove(ob, do_unlink=True)
for me in list(bpy.data.meshes):
    if me.users == 0:
        bpy.data.meshes.remove(me)

# ---- import teeth, bake world transforms into vertices ----
before = set(bpy.data.objects.keys())
bpy.ops.import_scene.gltf(filepath=GLB)
imported = [bpy.data.objects[n] for n in (set(bpy.data.objects.keys()) - before)]
enamel = {}
for ob in imported:
    if ob.type != "MESH":
        continue
    ob.data.transform(ob.matrix_world.copy())
    ob.matrix_world = Matrix.Identity(4)
    m = re.match(r"T(\d+)_Enamel$", ob.name)
    if m:
        enamel[int(m.group(1))] = ob


def tooth_stats(fdi, upper):
    """Return (cx, cy, cervz, apexz, crownFace_z, H, rx, ry) for one tooth.
    upper: crown = LOW z, apex = HIGH z.   lower: crown = HIGH z, apex = LOW z."""
    vs = enamel[fdi].data.vertices
    xs = [v.co.x for v in vs]; ys = [v.co.y for v in vs]; zs = [v.co.z for v in vs]
    cx, cy = sum(xs) / len(xs), sum(ys) / len(ys)
    zlo, zhi = min(zs), max(zs); H = zhi - zlo
    if upper:
        cervz = zlo + CROWN_FRAC * H
        apexz = zhi
        crownFace = cervz - PAPILLA * H          # toward crown = lower z
    else:
        cervz = zhi - CROWN_FRAC * H
        apexz = zlo
        crownFace = cervz + PAPILLA * H          # toward crown = higher z
    # size the ridge to the NECK/root width (band around the cervical plane), NOT the crown width,
    # so the gum hugs the roots and the wider crowns emerge proud of the gumline.
    band = NECK_BAND * H
    nxs = [v.co.x for v in vs if abs(v.co.z - cervz) < band]
    nys = [v.co.y for v in vs if abs(v.co.z - cervz) < band]
    if len(nxs) < 6:
        nxs, nys = xs, ys
    rx = (max(nxs) - min(nxs)) / 2 * WIDEN + PAD_BL
    ry = (max(nys) - min(nys)) / 2 * WIDEN + PAD_BL
    return cx, cy, cervz, apexz, crownFace, H, rx, ry


def build_ridge(seq, upper):
    """Solid gum ridge = ONE smooth SWEPT wall lofted along the arch's centreline (NOT a union of
    per-tooth spheres, which beads into a corn-cob). Each station cross-section is an ellipse in the
    (buccolingual, vertical) plane sized to the tooth NECK; lofting between stations gives a
    continuous smooth labial surface. The tooth-subtraction later carves the scallop / papillae /
    crown emergence into it."""
    fdis = [f for f in seq if f in enamel]
    raw = []
    for f in fdis:
        cx, cy, cervz, apexz, crownFace, H, rx, ry = tooth_stats(f, upper)
        base = apexz + (BASE_EXT if upper else -BASE_EXT)   # apical extent (past the apex)
        zc = (crownFace + base) / 2.0
        wh = abs(base - crownFace) / 2.0                    # vertical half-height (covers root->margin)
        wb = max(rx, ry)                                    # buccolingual half-width (neck-sized)
        raw.append((Vector((cx, cy, zc)), wb, wh))
    # densify the centreline for a smooth loft
    nodes = []
    for i in range(len(raw) - 1):
        (ca, wba, wha), (cb, wbb, whb) = raw[i], raw[i + 1]
        for s in range(1 + INTERP):
            t = s / (1 + INTERP)
            nodes.append((ca.lerp(cb, t), wba + (wbb - wba) * t, wha + (whb - wha) * t))
    nodes.append(raw[-1])
    ZUP = Vector((0, 0, 1))
    bm = bmesh.new(); rings = []
    for i, (C, WB, WH) in enumerate(nodes):
        prev = nodes[max(0, i - 1)][0]; nxt = nodes[min(len(nodes) - 1, i + 1)][0]
        T = (nxt - prev); T.z = 0
        if T.length < 1e-6:
            T = Vector((1, 0, 0))
        T.normalize()
        B = T.cross(ZUP).normalized()          # buccolingual (in-plane, perpendicular to the arch)
        ring = []
        for k in range(N_RING):
            a = 2 * math.pi * k / N_RING
            p = C + B * (WB * math.cos(a)) + ZUP * (WH * math.sin(a))
            ring.append(bm.verts.new(p))
        rings.append(ring)
    for i in range(len(rings) - 1):
        r0, r1 = rings[i], rings[i + 1]
        for k in range(N_RING):
            k2 = (k + 1) % N_RING
            bm.faces.new((r0[k], r0[k2], r1[k2], r1[k]))
    bm.faces.new(list(reversed(rings[0]))); bm.faces.new(rings[-1])
    bm.normal_update()
    me = bpy.data.meshes.new("GumRidge")
    bm.to_mesh(me); bm.free()
    ob = bpy.data.objects.new("GumRidge", me)
    bpy.context.collection.objects.link(ob)
    return ob


def build_cutter(seq):
    """Union of the arch's teeth (enamel), each slightly inflated about its own centre, as one
    voxel-remeshed manifold -> a clean cutter for the boolean."""
    fdis = [f for f in seq if f in enamel]
    parts = []
    for f in fdis:
        src = enamel[f]
        cp = src.copy(); cp.data = src.data.copy(); cp.name = "Cutter_%d" % f
        bpy.context.collection.objects.link(cp)
        me = cp.data
        xs = [v.co.x for v in me.vertices]; ys = [v.co.y for v in me.vertices]; zs = [v.co.z for v in me.vertices]
        cx, cy, cz = sum(xs) / len(xs), sum(ys) / len(ys), sum(zs) / len(zs)
        T = Matrix.Translation((cx, cy, cz))
        me.transform(T @ Matrix.Diagonal((CUT_INFLATE, CUT_INFLATE, CUT_INFLATE, 1.0)) @ T.inverted())
        parts.append(cp)
    bpy.ops.object.select_all(action="DESELECT")
    for p in parts:
        p.select_set(True)
    bpy.context.view_layer.objects.active = parts[0]
    bpy.ops.object.join()
    cutter = bpy.context.view_layer.objects.active
    cutter.name = "Cutter"
    rm = cutter.modifiers.new("rm", "REMESH")
    rm.mode = "VOXEL"; rm.voxel_size = VOX
    bpy.context.view_layer.objects.active = cutter
    bpy.ops.object.modifier_apply(modifier="rm")
    return cutter


def voxel_apply(ob, vox):
    rm = ob.modifiers.new("rm", "REMESH")
    rm.mode = "VOXEL"; rm.voxel_size = vox; rm.use_smooth_shade = True
    bpy.context.view_layer.objects.active = ob
    bpy.ops.object.modifier_apply(modifier="rm")


def build_arch(seq, upper):
    fdis = [f for f in seq if f in enamel]
    if len(fdis) < 3:
        return None

    gum = build_ridge(seq, upper)
    voxel_apply(gum, VOX)                     # ridge -> single smooth manifold solid
    gum.name = "Gum_Upper" if upper else "Gum_Lower"

    cutter = build_cutter(seq)                # teeth union -> manifold cutter
    mod = gum.modifiers.new("cut", "BOOLEAN")
    mod.operation = "DIFFERENCE"; mod.solver = "EXACT"; mod.object = cutter
    bpy.context.view_layer.objects.active = gum
    bpy.ops.object.modifier_apply(modifier="cut")
    bpy.data.objects.remove(cutter, do_unlink=True)

    if SMOOTH_ITERS > 0:
        sm = gum.modifiers.new("sm", "SMOOTH")
        sm.iterations = SMOOTH_ITERS; sm.factor = 0.3
        bpy.context.view_layer.objects.active = gum
        bpy.ops.object.modifier_apply(modifier="sm")

    bpy.ops.object.select_all(action="DESELECT")
    gum.select_set(True); bpy.context.view_layer.objects.active = gum
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.mesh.normals_make_consistent(inside=False)
    bpy.ops.object.mode_set(mode="OBJECT")

    gum.data.materials.clear()
    gum.data.materials.append(gum_material())
    for p in gum.data.polygons:
        p.use_smooth = True
    return gum


gums = [g for g in (build_arch(UPPER_SEQ, True), build_arch(LOWER_SEQ, False)) if g]

bpy.ops.object.select_all(action="DESELECT")
for g in gums:
    g.select_set(True)
bpy.context.view_layer.objects.active = gums[0]
bpy.ops.export_scene.gltf(filepath=OUT, use_selection=True, export_yup=True, export_apply=True)

info = {g.name: len(g.data.vertices) for g in gums}

for ob in list(imported) + gums:
    try:
        bpy.data.objects.remove(ob, do_unlink=True)
    except Exception:
        pass

result = {"exported": OUT, "gums": info}
