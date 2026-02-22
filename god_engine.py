import pygame
import numpy as np
import random
import sys

# --- SETTINGS ---
WIDTH, HEIGHT = 800, 600
CELL_SIZE = 4
COLS, ROWS = WIDTH // CELL_SIZE, HEIGHT // CELL_SIZE
FPS = 60

# --- MATTER TYPES (The "DNA" of the world) ---
EMPTY = 0
SAND = 1
WATER = 2
WOOD = 3
FIRE = 4
ACID = 5
LIFE = 6  # Simple "Life" that grows

# Colors
COLORS = {
    EMPTY: (0, 0, 0),
    SAND: (194, 178, 128),
    WATER: (0, 105, 148),
    WOOD: (139, 69, 19),
    FIRE: (255, 69, 0),
    ACID: (0, 255, 0),
    LIFE: (255, 105, 180) # Hot Pink for Life
}

def main():
    pygame.init()
    screen = pygame.display.set_mode((WIDTH, HEIGHT))
    pygame.display.set_caption("God Engine: [1:Sand] [2:Water] [3:Wood] [4:Fire] [5:Acid] [6:Life]")
    clock = pygame.time.Clock()

    # The "World" Matrix
    grid = np.zeros((ROWS, COLS), dtype=int)
    
    current_material = SAND
    running = True
    
    print("Controls:")
    print("Left Click: Draw")
    print("1-6: Change Material")
    print("C: Clear World")
    
    while running:
        screen.fill((0, 0, 0))
        
        # --- INPUT HANDLING ---
        for event in pygame.event.get():
            if event.type == pygame.QUIT: running = False
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_1: current_material = SAND
                if event.key == pygame.K_2: current_material = WATER
                if event.key == pygame.K_3: current_material = WOOD
                if event.key == pygame.K_4: current_material = FIRE
                if event.key == pygame.K_5: current_material = ACID
                if event.key == pygame.K_6: current_material = LIFE
                if event.key == pygame.K_c: grid.fill(EMPTY)

        # Draw with Mouse
        if pygame.mouse.get_pressed()[0]:
            mx, my = pygame.mouse.get_pos()
            gx, gy = mx // CELL_SIZE, my // CELL_SIZE
            brush_size = 2
            for i in range(-brush_size, brush_size+1):
                for j in range(-brush_size, brush_size+1):
                    if 0 <= gx+i < COLS and 0 <= gy+j < ROWS:
                        # Overwrite logic
                        if grid[gy+j, gx+i] == EMPTY or current_material in [FIRE, ACID]:
                            grid[gy+j, gx+i] = current_material

        # --- PHYSICS ENGINE ---
        new_grid = grid.copy()
        
        # We iterate carefully to simulate cellular automata
        for y in range(ROWS):
            for x in range(COLS):
                cell = grid[y, x]
                if cell == EMPTY: continue
                
                # SAND: Falls down, piles up
                if cell == SAND:
                    if y < ROWS-1:
                        if grid[y+1, x] == EMPTY:
                            new_grid[y+1, x] = SAND
                            new_grid[y, x] = EMPTY
                        elif grid[y+1, x] == WATER:
                            new_grid[y+1, x] = SAND
                            new_grid[y, x] = WATER
                        elif x > 0 and grid[y+1, x-1] == EMPTY:
                            new_grid[y+1, x-1] = SAND
                            new_grid[y, x] = EMPTY
                        elif x < COLS-1 and grid[y+1, x+1] == EMPTY:
                            new_grid[y+1, x+1] = SAND
                            new_grid[y, x] = EMPTY

                # WATER: Falls, flows sideways
                elif cell == WATER:
                    if y < ROWS-1:
                        if grid[y+1, x] == EMPTY:
                            new_grid[y+1, x] = WATER
                            new_grid[y, x] = EMPTY
                        else:
                            # Flow left/right randomly
                            dir = random.choice([-1, 1])
                            if 0 <= x+dir < COLS and grid[y, x+dir] == EMPTY:
                                new_grid[y, x+dir] = WATER
                                new_grid[y, x] = EMPTY

                # FIRE: Burns Wood and Life, dies randomly
                elif cell == FIRE:
                    if random.random() < 0.05: new_grid[y, x] = EMPTY
                    # Check neighbors
                    for dy in [-1, 0, 1]:
                        for dx in [-1, 0, 1]:
                            if 0 <= y+dy < ROWS and 0 <= x+dx < COLS:
                                neighbor = grid[y+dy, x+dx]
                                if neighbor in [WOOD, LIFE]:
                                    new_grid[y+dy, x+dx] = FIRE

                # ACID: Destroys everything except Acid/Empty
                elif cell == ACID:
                    if y < ROWS-1:
                        neighbor = grid[y+1, x]
                        if neighbor != EMPTY and neighbor != ACID:
                            new_grid[y+1, x] = EMPTY
                            if random.random() < 0.1: new_grid[y, x] = EMPTY # Acid consumed

                # LIFE: Grows into water, dies to Fire/Acid
                elif cell == LIFE:
                    # Grow slowly if touching water
                    has_water = False
                    for dy in [-1, 0, 1]:
                        for dx in [-1, 0, 1]:
                            if 0 <= y+dy < ROWS and 0 <= x+dx < COLS:
                                if grid[y+dy, x+dx] == WATER:
                                    has_water = True
                                    if random.random() < 0.05: # Drink water
                                        new_grid[y+dy, x+dx] = LIFE 
                    
                    # Die if crowded (Game of Life ruleish) or random old age
                    if random.random() < 0.001: 
                        new_grid[y, x] = SAND # Turn to dust

        grid = new_grid

        # --- RENDER ---
        # Drawing rectangles (Optimization: Use surfarray for massive grids)
        for y in range(ROWS):
            for x in range(COLS):
                val = grid[y, x]
                if val != EMPTY:
                    color = COLORS[val]
                    pygame.draw.rect(screen, color, (x*CELL_SIZE, y*CELL_SIZE, CELL_SIZE, CELL_SIZE))

        pygame.display.flip()
        clock.tick(FPS)

    pygame.quit()
    sys.exit()

if __name__ == "__main__":
    main()