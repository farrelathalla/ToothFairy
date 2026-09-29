"""Parse teeth.glb, compute world-space centroid + size of every mesh node, and
propose an FDI mapping by quadrant + arch-position ordering. Prints a table.
"""
import struct, json
from pathlib import Path
import numpy as np

GLB = Path(__file__).resolve().parents[2] / "assets" / "3d" / "teeth.glb"

def load_glb(p):
    f = open(p, "rb"); struct.unpack("<III", f.read(12))
    clen, ctype = struct.unpack("<II", f.read(8)); j = json.loads(f.read(clen))
    # bin chunk
    blen, btype = struct.unpack("<II", f.read(8)); bin_ = f.read(blen)
    return j, bin_

COMP = {5120: ('b', 1), 5121: ('B', 1), 5122: ('h', 2), 5123: ('H', 2),
        5125: ('I', 4), 5126: ('f', 4)}
NC = {'SCALAR': 1, 'VEC2': 2, 'VEC3': 3, 'VEC4': 4, 'MAT4': 16}

def trs(node):
    if "matrix" in node:
        return np.array(node["matrix"], dtype=float).reshape(4, 4).T
    M = np.eye(4)
    t = node.get("translation", [0, 0, 0])
    r = node.get("rotation", [0, 0, 0, 1])
    s = node.get("scale", [1, 1, 1])
    x, y, z, w = r
    R = np.array([
        [1-2*(y*y+z*z), 2*(x*y-z*w),   2*(x*z+y*w)],
        [2*(x*y+z*w),   1-2*(x*x+z*z), 2*(y*z-x*w)],
        [2*(x*z-y*w),   2*(y*z+x*w),   1-2*(x*x+y*y)]])
    M[:3, :3] = R * np.array(s)
    M[:3, 3] = t
    return M

def accessor_minmax(j, idx):
    a = j["accessors"][idx]
    if "min" in a and "max" in a:
        return np.array(a["min"], float), np.array(a["max"], float)
    return None, None

def main():
    j, _ = load_glb(GLB)
    nodes = j["nodes"]
    meshes = []
    def walk(ni, parent):
        n = nodes[ni]
        world = parent @ trs(n)
        if "mesh" in n:
            m = j["meshes"][n["mesh"]]
            mn = np.array([1e9]*3); mx = np.array([-1e9]*3)
            for prim in m["primitives"]:
                pa = prim["attributes"].get("POSITION")
                lo, hi = accessor_minmax(j, pa)
                if lo is not None:
                    mn = np.minimum(mn, lo); mx = np.maximum(mx, hi)
            center_local = (mn + mx) / 2
            cw = (world @ np.append(center_local, 1))[:3]
            size = (mx - mn)
            meshes.append({"node": ni, "name": n.get("name", "?"),
                           "c": cw, "size": float(np.linalg.norm(size))})
        for c in n.get("children", []):
            walk(c, world)
    scene = j.get("scene", 0)
    for ni in j["scenes"][scene]["nodes"]:
        walk(ni, np.eye(4))
    # bounds
    C = np.array([m["c"] for m in meshes])
    print("num mesh nodes:", len(meshes))
    print("X range", C[:,0].min(), C[:,0].max())
    print("Y range", C[:,1].min(), C[:,1].max())
    print("Z range", C[:,2].min(), C[:,2].max())
    print()
    for m in sorted(meshes, key=lambda z: (round(z["c"][1],1), z["c"][0])):
        print(f'{m["node"]:3d} {m["name"][:38]:38s} '
              f'x={m["c"][0]:7.2f} y={m["c"][1]:7.2f} z={m["c"][2]:7.2f} size={m["size"]:.2f}')

if __name__ == "__main__":
    main()
