"""Create display-only tube surfaces and categorical colour arrays."""
import colorsys
import hashlib
import math
import numpy as np
from .vtkio import poly


def category_rgb(value):
    if value is None:
        return (150, 150, 150)
    hue = int.from_bytes(hashlib.sha256(str(value).encode()).digest()[:4], 'big') / 2**32
    return tuple(round(v * 255) for v in colorsys.hsv_to_rgb(hue, .58, .9))


def tubes(points, ends, radius, check):
    # Emit a separate lightweight mesh. The original polylines remain in scene.vtm.
    sides = 8
    if len(points) * sides > 200000:
        raise ValueError('Tube display exceeds its vertex budget. Reduce the view or use lines.')
    coords, faces, owners = [], [], []
    start = 0
    for owner, end in enumerate(ends):
        check()
        line = np.asarray(points[start:end], dtype=float)
        start = end
        line = line[np.r_[True, np.any(np.diff(line, axis=0) != 0, axis=1)]]
        if len(line) < 2:
            continue
        directions = np.diff(line, axis=0)
        directions /= np.linalg.norm(directions, axis=1)[:, None]
        previous = None
        for i, point in enumerate(line):
            tangent = directions[min(i, len(directions)-1)].copy()
            if 0 < i < len(line)-1:
                mean = tangent + directions[i-1]
                if np.linalg.norm(mean) > 1e-9:
                    tangent = mean / np.linalg.norm(mean)
            normal = previous
            if normal is None or abs(np.dot(normal, tangent)) > .99:
                normal = np.eye(3)[np.argmin(np.abs(tangent))]
            normal = normal - tangent * np.dot(normal, tangent)
            normal /= np.linalg.norm(normal)
            previous = normal
            cross = np.cross(tangent, normal)
            base = len(coords)
            for j in range(sides):
                angle = 2*math.pi*j/sides
                coords.append(point + radius * (normal*math.cos(angle) + cross*math.sin(angle)))
                if i:
                    k = (j+1) % sides
                    faces.extend((base-sides+j, base-sides+k, base+k, base+j))
                    owners.append(owner)
    if not faces:
        return None
    return coords, faces, owners
