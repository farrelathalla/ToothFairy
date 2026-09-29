# Render a preview of teeth_layered.glb + gums.glb from a frontal "both" view (like image.png),
# to eyeball the gum. Writes PNG(s) to the scratchpad. MCP body: sets `result`.
import bpy, os, math
from mathutils import Vector

# Repo root: set TOOTHFAIRY_REPO, else derive from this file (assets/blender/x.py -> ../..).
REPO = os.environ.get("TOOTHFAIRY_REPO") or os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__ if "__file__" in dir() else os.getcwd()))))
TEETH = os.path.join(REPO, "web", "public", "teeth_layered.glb")
GUMS = os.path.join(REPO, "web", "public", "gums.glb")
OUTDIR = r"C:\Users\PKL\AppData\Local\Temp\claude\C--Users-PKL-Desktop-ToothFairy-NAIA-Think-Tank-Project\223b5819-42bd-491b-9991-f09d26acce0b\scratchpad"

# wipe scene
for ob in list(bpy.data.objects):
    bpy.data.objects.remove(ob, do_unlink=True)
for me in list(bpy.data.meshes):
    if me.users == 0:
        bpy.data.meshes.remove(me)

def imp(path):
    before = set(bpy.data.objects.keys())
    bpy.ops.import_scene.gltf(filepath=path)
    return [bpy.data.objects[n] for n in (set(bpy.data.objects.keys()) - before)]

teeth = imp(TEETH)
gums = imp(GUMS)

# white teeth material
tm = bpy.data.materials.new("Teeth")
tm.use_nodes = True
tm.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (0.92, 0.90, 0.87, 1)
for ob in teeth:
    if ob.type == "MESH":
        ob.data.materials.clear(); ob.data.materials.append(tm)

# pink gum material
gm = bpy.data.materials.new("Gum")
gm.use_nodes = True
gm.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (0.83, 0.42, 0.45, 1)
for ob in gums:
    if ob.type == "MESH":
        ob.data.materials.clear(); ob.data.materials.append(gm)

# overall bounds
allobs = [o for o in teeth + gums if o.type == "MESH"]
mn = Vector((1e9, 1e9, 1e9)); mx = Vector((-1e9, -1e9, -1e9))
for o in allobs:
    for c in o.bound_box:
        w = o.matrix_world @ Vector(c)
        for i in range(3):
            mn[i] = min(mn[i], w[i]); mx[i] = max(mx[i], w[i])
ctr = (mn + mx) / 2
size = (mx - mn)

# camera. After glTF(Y-up) import into Blender(Z-up): Blender Z = tooth vertical axis,
# Blender X = left-right (arch width), Blender -Y = the app's front (viewer side).
cam_data = bpy.data.cameras.new("Cam")
cam = bpy.data.objects.new("Cam", cam_data)
bpy.context.collection.objects.link(cam)
diag = max(size.x, size.z) * 2.2
offsets = {
    "front":  Vector((0, -diag, size.z * 0.25)),   # from front (-Y), slight elevation
    "front2": Vector((0, diag, size.z * 0.25)),     # from the other Y side
    "occl":   Vector((0, 0, diag)),                  # occlusal top-down
    "iso":    Vector((diag * 0.5, -diag * 0.8, size.z * 0.4)),
}
bpy.context.scene.camera = cam

# lights
for pos, e in [((3, 5, 6), 900), ((-5, 3, 4), 500), ((0, 2, -6), 300), ((0, 8, 0), 400)]:
    ld = bpy.data.lights.new("L", "AREA"); ld.energy = e; ld.size = 8
    lo = bpy.data.objects.new("L", ld); lo.location = ctr + Vector(pos)
    lo.rotation_euler = (ctr - lo.location).normalized().to_track_quat('-Z', 'Y').to_euler()
    bpy.context.collection.objects.link(lo)

world = bpy.context.scene.world
if not world:
    world = bpy.data.worlds.new("W"); bpy.context.scene.world = world
world.use_nodes = True
world.node_tree.nodes["Background"].inputs["Color"].default_value = (0.05, 0.06, 0.08, 1)
world.node_tree.nodes["Background"].inputs["Strength"].default_value = 0.6

sc = bpy.context.scene
sc.render.engine = 'BLENDER_EEVEE_NEXT' if 'BLENDER_EEVEE_NEXT' in [e.identifier for e in bpy.types.RenderSettings.bl_rna.properties['engine'].enum_items] else 'BLENDER_EEVEE'
sc.render.resolution_x = 900
sc.render.resolution_y = 800
sc.render.film_transparent = False

tag = globals().get("TAG", "current")
views = globals().get("VIEWS", ["front", "iso"])
outs = []
for v in views:
    cam.location = ctr + offsets[v]
    dirv = (ctr - cam.location).normalized()
    cam.rotation_euler = dirv.to_track_quat('-Z', 'Z').to_euler()
    out = os.path.join(OUTDIR, "gum_%s_%s.png" % (tag, v))
    sc.render.filepath = out
    bpy.ops.render.render(write_still=True)
    outs.append(out)

result = {"rendered": outs, "center": list(ctr), "size": list(size)}
