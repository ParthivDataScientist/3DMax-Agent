import trimesh
import numpy as np

def create_complex_scene():
    scene = trimesh.Scene()
    
    # 1. Base table (Box)
    base = trimesh.creation.box(extents=[1000, 600, 30])
    base.apply_translation([0, 0, 700])
    scene.add_geometry(base, node_name="table_top", geom_name="table_top")

    # 2. Four legs (Cylinders)
    for i, x in enumerate([-450, 450]):
        for j, y in enumerate([-250, 250]):
            leg = trimesh.creation.cylinder(radius=30, height=700)
            # Center of cylinder height is at z=350, so bottom is at 0
            leg.apply_translation([x, y, 350])
            scene.add_geometry(leg, node_name=f"leg_{i}_{j}", geom_name=f"leg_{i}_{j}")

    # 3. Slanted display panel (Box slightly rotated)
    panel = trimesh.creation.box(extents=[800, 400, 20])
    panel.apply_translation([0, 0, 0])
    # Rotate around X axis
    rot_matrix = trimesh.transformations.rotation_matrix(np.radians(30), [1, 0, 0])
    panel.apply_transform(rot_matrix)
    panel.apply_translation([0, 100, 900])
    scene.add_geometry(panel, node_name="slanted_panel", geom_name="slanted_panel")

    # 4. Spherical decoration (Sphere)
    sphere = trimesh.creation.icosphere(radius=100)
    sphere.apply_translation([-300, -100, 780])
    scene.add_geometry(sphere, node_name="decoration_sphere", geom_name="decoration_sphere")

    # 5. Capsule representing an irregular part
    complex_part = trimesh.creation.capsule(height=200, radius=50)
    complex_part.apply_translation([100, -250, 730])
    # Rotated awkwardly to make it completely non-planar aligned
    rot_matrix2 = trimesh.transformations.rotation_matrix(np.radians(45), [1, 1, 0])
    complex_part.apply_transform(rot_matrix2)
    scene.add_geometry(complex_part, node_name="irregular_mount", geom_name="irregular_mount")

    # Export
    with open("generated_objs/complex_scene.obj", "w") as f:
        # scene.export returns the obj file as a string
        f.write(scene.export(file_type='obj'))
        
    print("Exported to generated_objs/complex_scene.obj")

if __name__ == "__main__":
    create_complex_scene()
