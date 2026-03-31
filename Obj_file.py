import trimesh
import numpy as np
from pathlib import Path

OUTPUT_DIR = Path("generated_objs")
OUTPUT_DIR.mkdir(exist_ok=True)


def save_mesh(mesh, name):
    path = OUTPUT_DIR / f"{name}.obj"
    mesh.export(path)
    print(f"Saved: {path}")


# 1️⃣ BOX (your baseline test)
def create_box():
    mesh = trimesh.creation.box(extents=(1200, 600, 900))
    save_mesh(mesh, "box")


# 2️⃣ CYLINDER (tests curved surface)
def create_cylinder():
    mesh = trimesh.creation.cylinder(radius=200, height=800)
    save_mesh(mesh, "cylinder")


# 3️⃣ SPHERE (tests complex curved shape)
def create_sphere():
    mesh = trimesh.creation.icosphere(radius=300)
    save_mesh(mesh, "sphere")


# 4️⃣ FLAT PLATE (edge case: almost 2D)
def create_flat_plate():
    mesh = trimesh.creation.box(extents=(1000, 500, 10))
    save_mesh(mesh, "flat_plate")


# 5️⃣ ANGLED BOX (tests bounding box limitation)
def create_angled_box():
    mesh = trimesh.creation.box(extents=(1000, 500, 300))
    
    # Rotate 45 degrees around Z-axis
    angle = np.radians(45)
    rotation_matrix = trimesh.transformations.rotation_matrix(angle, [0, 0, 1])
    mesh.apply_transform(rotation_matrix)

    save_mesh(mesh, "angled_box")


# 6️⃣ TRIANGLE (very simple test)
def create_triangle():
    vertices = np.array([
        [0, 0, 0],
        [500, 0, 0],
        [250, 400, 0]
    ])

    faces = np.array([
        [0, 1, 2]
    ])

    mesh = trimesh.Trimesh(vertices=vertices, faces=faces)
    save_mesh(mesh, "triangle")


def main():
    create_box()
    create_cylinder()
    create_sphere()
    create_flat_plate()
    create_angled_box()
    create_triangle()


if __name__ == "__main__":
    main()