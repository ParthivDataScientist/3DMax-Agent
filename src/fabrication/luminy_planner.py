from typing import List, Dict, Any, Tuple
from .component_optimizer import ComponentOptimizer
from .fabrication_rules import ComponentOption, FabricationRules

class LuminyPlanner:
    def __init__(self, optimizer: ComponentOptimizer):
        self.optimizer = optimizer

    def solve_assembly(self, target_width: float, target_height: float) -> Tuple[List[ComponentOption], List[Dict[str, Any]]]:
        # Fetch available components
        frames = self.optimizer.get_luminy_frames(target_height)
        posts = self.optimizer.get_standard_posts(target_height)
        fillers = self.optimizer.get_custom_fillers()
        
        # We need to find combinations of frames, posts, fillers that equal target_width.
        # This is essentially a bounded knapsack or coin change problem, but we want exact match
        # and we prioritize standard luminy frames.
        
        components = []
        for f in frames:
            components.append({'type': 'luminy_frame', 'data': f})
        for p in posts:
            components.append({'type': 'standard_post', 'data': p})
        for c in fillers:
            components.append({'type': 'custom_filler', 'data': c})
            
        best_combo = None
        best_score = -9999
        
        # Simple greedy + backtracking approach to find the exact width
        def backtrack(remaining_width: float, current_combo: List[ComponentOption], index: int):
            nonlocal best_combo, best_score
            
            if abs(remaining_width) < 1.0: # found a match
                score = FabricationRules.calculate_score(current_combo)
                if score > best_score:
                    best_score = score
                    best_combo = list(current_combo)
                return
                
            if remaining_width < 0 or index >= len(components):
                return
                
            comp = components[index]
            w = comp['data']['width_mm']
            h = comp['data'].get('height_mm', target_height)
            if h is None:
                h = target_height
                
            # Try taking this component
            # If it's a filler, we might use it only once ideally
            max_qty = 5 if comp['type'] != 'custom_filler' else 2
            
            for qty in range(max_qty + 1):
                if remaining_width - (w * qty) >= -0.5:
                    added = [ComponentOption(comp['data']['name'], w, h, comp['type']) for _ in range(qty)]
                    backtrack(remaining_width - (w * qty), current_combo + added, index + 1)

        backtrack(target_width, [], 0)
        
        # If no combo found with standard sizes, add a custom filler of exact remaining size if possible
        # Or just return empty and let solver handle it.
        # Actually, let's just make one option with largest frames and a custom filler.
        if not best_combo:
            best_combo = self._greedy_fallback(target_width, target_height, frames, posts)
            
        # Determine blocking panels. A blocking panel is typically added when we have a luminy frame.
        blocking_panels_needed = []
        blocking_panels = self.optimizer.get_blocking_panels()
        for c in best_combo:
            if c.component_type == 'luminy_frame':
                # simplified logic for blocking panel: if width >= 1410 we might need 2, else 1
                bp = blocking_panels[0] if blocking_panels else None
                if bp:
                    qty = 2 if c.width_mm >= 1410 else 1
                    for _ in range(qty):
                        blocking_panels_needed.append({
                            'name': bp['name'],
                            'width_mm': bp['width_mm'],
                            'height_mm': bp['height_mm']
                        })
            
        return best_combo, blocking_panels_needed

    def _greedy_fallback(self, target_width: float, target_height: float, frames: List[Dict], posts: List[Dict]) -> List[ComponentOption]:
        remaining = target_width
        combo = []
        for f in frames:
            w = f['width_mm']
            while remaining - w >= 0:
                combo.append(ComponentOption(f['name'], w, f['height_mm'], 'luminy_frame'))
                remaining -= w
                
        for p in posts:
            w = p['width_mm']
            while remaining - w >= 0:
                combo.append(ComponentOption(p['name'], w, p['height_mm'], 'standard_post'))
                remaining -= w
                
        if remaining > 0:
            combo.append(ComponentOption(f"Custom Wooden Frame W{int(remaining)} x H{int(target_height)}", remaining, target_height, 'custom_filler'))
            
        return combo
