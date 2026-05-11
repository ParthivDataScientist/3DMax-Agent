from typing import Dict, Any
from .component_optimizer import ComponentOptimizer
from .luminy_planner import LuminyPlanner

class FabricationSolver:
    def __init__(self):
        self.optimizer = ComponentOptimizer()
        self.planner = LuminyPlanner(self.optimizer)
        
    def solve(self, width_mm: float, height_mm: float) -> Dict[str, Any]:
        combo, blocking_panels = self.planner.solve_assembly(width_mm, height_mm)
        
        # Aggregate components
        luminy_frames = {}
        posts = {}
        fillers = {}
        
        for c in combo:
            if c.component_type == 'luminy_frame':
                size_str = f"{int(c.width_mm)} x {int(c.height_mm)}"
                luminy_frames[size_str] = luminy_frames.get(size_str, 0) + 1
            elif c.component_type == 'standard_post':
                size_str = f"{int(c.width_mm)} x {int(c.height_mm)}"
                posts[size_str] = posts.get(size_str, 0) + 1
            elif c.component_type == 'custom_filler':
                size_str = f"{int(c.width_mm)} x {int(c.height_mm)}"
                fillers[size_str] = {"w": c.width_mm, "h": c.height_mm, "q": fillers.get(size_str, {}).get("q", 0) + 1}
                
        bp_agg = {}
        for bp in blocking_panels:
            size_str = f"{int(bp['width_mm'])} x {int(bp['height_mm'])}"
            bp_agg[size_str] = bp_agg.get(size_str, 0) + 1
            
        res_frames = [{"size": k, "quantity": v} for k, v in luminy_frames.items()]
        res_bps = [{"size": k, "quantity": v} for k, v in bp_agg.items()]
        res_posts = [{"size": k, "quantity": v} for k, v in posts.items()]
        res_fillers = [{"width_mm": v["w"], "height_mm": v["h"], "quantity": v["q"]} for v in fillers.values()]
        
        return {
            "assembly_type": "Luminy Wall Assembly",
            "detected_geometry": {
                "width_mm": width_mm,
                "height_mm": height_mm
            },
            "recommended_solution": {
                "luminy_frames": res_frames,
                "blocking_panels": res_bps,
                "custom_fillers": res_fillers,
                "posts": res_posts
            },
            "status": "FABRICATION_POSSIBLE",
            "notes": [
                "Verify filler tolerance before production"
            ]
        }
