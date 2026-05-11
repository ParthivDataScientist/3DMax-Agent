from dataclasses import dataclass
from typing import List

@dataclass
class ComponentOption:
    name: str
    width_mm: float
    height_mm: float
    component_type: str # 'luminy_frame', 'blocking_panel', 'custom_filler', 'standard_post'
    
class FabricationRules:
    @staticmethod
    def is_valid_assembly(width_mm: float, height_mm: float, components: List[ComponentOption]) -> bool:
        total_width = sum(c.width_mm for c in components)
        # Check if the assembly meets the exact width
        if abs(total_width - width_mm) > 1.0:
            return False
        return True

    @staticmethod
    def calculate_score(components: List[ComponentOption]) -> float:
        score = 0.0
        for c in components:
            if c.component_type == 'luminy_frame':
                score += 100 # Prefer luminy frames
            elif c.component_type == 'standard_post':
                score += 50
            elif c.component_type == 'blocking_panel':
                score += 40
            elif c.component_type == 'custom_filler':
                score -= 10 # Penalize custom fillers
        
        # Penalize for number of components (prefer fewer modules)
        score -= len(components) * 5
        return score
