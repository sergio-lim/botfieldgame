from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from starlette.middleware.base import BaseHTTPMiddleware
from colorama import Fore, Style, init
from typing import List
import json
import logging
import time
from datetime import datetime
import asyncio
import random

# Configurar logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    asyncio.create_task(regenerate_food())
    asyncio.create_task(regenerate_poison())
    # Start the activity monitor together with the regeneration tasks so
    # background tasks are created when the app lifecycle starts.
    asyncio.create_task(monitor_activity())
    # Prune any existing child items (e.g. bananas) that are not adjacent to trees.
    # This protects against residual state from previous runs or hot-reloads.
    try:
        valid_cells = cells_near_trees()
        foods[:] = [f for f in foods if not (isinstance(f, dict) and f.get('type') == TREE_SPAWN_ID and (f['x'], f['y']) not in valid_cells)]
    except Exception:
        # If pruning fails for any reason, continue — it's non-fatal.
        logger.debug("Failed to prune stray spawned items on startup")
    yield

app = FastAPI(lifespan=lifespan)

# Middleware para logging de todas las peticiones HTTP
class LoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        logger.debug(f"HTTP Request: {request.method} {request.url} from {request.client.host if request.client else 'unknown'}")
        response = await call_next(request)
        logger.debug(f"HTTP Response: {response.status_code} for {request.method} {request.url}")
        return response

app.add_middleware(LoggingMiddleware)

# Estado del campo
positions = {}  # nickname: (x, y)
colors = {}     # nickname: color_name
energy = {}     # nickname: int
foods = []   # list of {'x': int, 'y': int, 'value': int}
paths = {}      # nickname: list of [x, y]
remembered = {}  # nickname: set of (x, y)
available_colors = ['RED', 'GREEN', 'BLUE', 'YELLOW', 'MAGENTA', 'CYAN', 'TEAL', 'WHITE']

# Récord de tiempo
record = {"name": "", "time": 0, "date": "", "start_energy": 0}
start_times = {}  # nickname: start_time
start_energies = {}  # nickname: start_energy

# Tracking de actividad de bots
last_bot_request_time = None

# Inicializar colorama (para posibles logs futuros)
init(autoreset=True)

# Cargar récord si existe
try:
    with open("records.json", "r") as f:
        record = json.load(f)
except FileNotFoundError:
    pass

# Cargar leaderboard si existe
leaderboard = {}  # nickname: best_seconds
try:
    with open("leaderboard.json", "r") as f:
        leaderboard = json.load(f)
except FileNotFoundError:
    pass

# Cargar definiciones de items
with open("items.json", "r") as f:
    ITEMS = json.load(f)["items"]

FOOD_DEF = ITEMS["food"]
POISON_DEF = ITEMS["poison"]
TREE_DEF = ITEMS["banana_tree"]
# Resolve the item type that the tree spawns from its own definition
TREE_SPAWN_ID = TREE_DEF["spawns"]          # "food"
TREE_SPAWN_DEF = ITEMS[TREE_SPAWN_ID]       # same object as FOOD_DEF, driven by items.json

# Banana trees — static objects on the map
trees = []  # list of {'x': int, 'y': int, 'type': 'banana_tree'}

def spawn_trees():
    """Place banana trees randomly at startup, avoiding overlaps. Count is random between 1 and max_on_map."""
    trees.clear()
    count = random.randint(1, TREE_DEF['max_on_map'])
    attempts_total = 0
    while len(trees) < count and attempts_total < 500:
        tx, ty = random.randint(0, 9), random.randint(0, 9)
        if not any(t['x'] == tx and t['y'] == ty for t in trees):
            trees.append({'x': tx, 'y': ty, 'type': 'banana_tree'})
        attempts_total += 1

spawn_trees()

def cells_near_trees():
    """Return the 4 orthogonally adjacent cells to any tree (no diagonals)."""
    candidates = set()
    for t in trees:
        for dx, dy in [(0, 1), (0, -1), (1, 0), (-1, 0)]:
            nx, ny = t['x'] + dx, t['y'] + dy
            if 0 <= nx < 10 and 0 <= ny < 10:
                if not any(tr['x'] == nx and tr['y'] == ny for tr in trees):
                    candidates.add((nx, ny))
    return candidates

# Generar comidas iniciales cerca de los árboles
import random
foods = [f for f in foods if isinstance(f, dict)]  # Limpiar viejos tuples si existen
# Bananas are not pre-spawned; they appear only via regenerate_food()
# Spawn initial poison items
for i in range(POISON_DEF['max_on_map']):
    attempts = 0
    while attempts < 100:
        px, py = random.randint(0, 9), random.randint(0, 9)
        occupied_by_tree = any(t['x'] == px and t['y'] == py for t in trees)
        if not any(f.get('x') == px and f.get('y') == py for f in foods if isinstance(f, dict)) and not occupied_by_tree:
            foods.append({'x': px, 'y': py, 'type': 'poison', 'value': POISON_DEF['energy_value']})
            break
        attempts += 1

# Función para regenerar comida (bananas solo cerca de árboles)
async def regenerate_food():
    while True:
        await asyncio.sleep(TREE_SPAWN_DEF['respawn_interval_seconds'])
        current_bananas = [f for f in foods if isinstance(f, dict) and f.get('type') == TREE_SPAWN_ID]
        if len(current_bananas) < TREE_SPAWN_DEF['max_on_map']:
            occupied = {(f['x'], f['y']) for f in foods if isinstance(f, dict)}
            occupied |= set(positions.values())
            occupied |= {(t['x'], t['y']) for t in trees}
            candidates = [c for c in cells_near_trees() if c not in occupied]
            if candidates:
                cx, cy = random.choice(candidates)
                foods.append({'x': cx, 'y': cy, 'type': TREE_SPAWN_ID, 'value': TREE_SPAWN_DEF['energy_value']})
                logger.debug(f"Regenerated {TREE_SPAWN_DEF['label']} at ({cx}, {cy}) near a {TREE_DEF['label']}")

# Función para regenerar veneno
async def regenerate_poison():
    while True:
        await asyncio.sleep(POISON_DEF['respawn_interval_seconds'])
        current_poison = [f for f in foods if isinstance(f, dict) and f.get('type') == 'poison']
        if len(current_poison) < POISON_DEF['max_on_map']:
            attempts = 0
            while attempts < 100:
                x = random.randint(0, 9)
                y = random.randint(0, 9)
                pos = (x, y)
                if not any(f.get('x') == x and f.get('y') == y for f in foods if isinstance(f, dict)) and pos not in positions.values():
                    foods.append({'x': x, 'y': y, 'type': 'poison', 'value': POISON_DEF['energy_value']})
                    logger.debug(f"Regenerated poison at ({x}, {y})")
                    break
                attempts += 1

# Templates
templates = Jinja2Templates(directory="templates")

# Manager para conexiones WebSocket de la web
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        client_info = f"{websocket.client.host}:{websocket.client.port}" if websocket.client else "unknown"
        logger.debug(f"Connecting WebSocket from {client_info}")
        self.active_connections.append(websocket)
        logger.info(f"Connected WebSocket from {client_info}. Total: {len(self.active_connections)}")
        
        # Enviar el grid actual al nuevo cliente
        grid_data = {"grid": get_grid()}
        await websocket.send_text(json.dumps(grid_data))

    def disconnect(self, websocket: WebSocket):
        client_info = f"{websocket.client.host}:{websocket.client.port}" if websocket.client else "unknown"
        logger.debug(f"Disconnecting WebSocket from {client_info}")
        self.active_connections.remove(websocket)
        logger.debug(f"Disconnected WebSocket from {client_info}. Total: {len(self.active_connections)}")

    async def broadcast(self, message: str):
        logger.debug(f"Broadcasting message to {len(self.active_connections)} connections: {message[:100]}...")
        disconnected = []
        for connection in self.active_connections:
            try:
                await connection.send_text(message)
            except Exception as e:
                client_info = f"{connection.client.host}:{connection.client.port}" if connection.client else "unknown"
                logger.debug(f"Failed to send to {client_info}: {e}")
                disconnected.append(connection)
        for conn in disconnected:
            self.disconnect(conn)

manager = ConnectionManager()

def get_grid():
    logger.debug("Generating grid")
    grid = [['.' for _ in range(10)] for _ in range(10)]
    # Draw trees first (static, below everything else)
    for t in trees:
        grid[9 - t['y']][t['x']] = TREE_DEF['symbol']
    for nick, (x, y) in positions.items():
        color = colors[nick]
        if nick == 'orion':
            symbol = '🦖'
        elif nick == 'Xenon':
            symbol = '🗿'
        else:
            symbol = nick[0].upper()  # Primera letra del nickname
        grid[9 - y][x] = {"symbol": symbol, "color": color}
    for f in foods:
        if isinstance(f, dict):
            item_def = ITEMS.get(f.get('type', 'food'), FOOD_DEF)
            grid[9 - f['y']][f['x']] = item_def['symbol']
    
    # Marcar caminos recorridos con color tenue
    for nick, path in paths.items():
        color = colors.get(nick, 'WHITE')
        dim_color = f"{color}_dim"
        for px, py in path:
            if grid[9 - py][px] == '.':
                grid[9 - py][px] = {"symbol": "", "color": dim_color}
    
    logger.debug(f"Grid generated with {len(positions)} positions and {len(foods)} foods")
    return grid

def reset_field():
    global foods, positions, colors, energy, paths, start_times, start_energies, last_bot_request_time
    # Trees are NOT re-spawned on reset — they persist from startup
    # Bananas are not pre-filled; regenerate_food() will populate them over time
    foods = []
    for i in range(POISON_DEF['max_on_map']):
        attempts = 0
        while attempts < 100:
            px, py = random.randint(0, 9), random.randint(0, 9)
            occupied_by_tree = any(t['x'] == px and t['y'] == py for t in trees)
            if not any(f.get('x') == px and f.get('y') == py for f in foods if isinstance(f, dict)) and not occupied_by_tree:
                foods.append({'x': px, 'y': py, 'type': 'poison', 'value': POISON_DEF['energy_value']})
                break
            attempts += 1
    positions.clear()
    colors.clear()
    energy.clear()
    paths.clear()
    start_times.clear()
    start_energies.clear()
    last_bot_request_time = None
    logger.info("Campo reiniciado por inactividad")

async def monitor_activity():
    while True:
        await asyncio.sleep(1)
        if last_bot_request_time is not None:
            elapsed = time.time() - last_bot_request_time
            if elapsed > 5 and elapsed <= 10:
                reset_field()
                logger.info("Campo reiniciado por inactividad (>5s sin peticiones, habiendo tenido en últimos 10s)")

def build_broadcast():
    """Build the full grid broadcast payload including leaderboard and live times."""
    now = time.time()
    live_times = {nick: round(now - start_times[nick], 1) for nick in positions if nick in start_times}
    return {
        "grid": get_grid(),
        "energies": dict(energy),
        "record": record,
        "positions": {nick: list(pos) for nick, pos in positions.items()},
        "leaderboard": leaderboard,
        "live_times": live_times,
        "trees": [{"x": t["x"], "y": t["y"]} for t in trees],
    }

def update_leaderboard(nickname: str):
    """Update leaderboard with this bot's current session time if it's a personal best."""
    duration = round(time.time() - start_times.get(nickname, time.time()), 1)
    if duration > leaderboard.get(nickname, 0):
        leaderboard[nickname] = duration
        with open("leaderboard.json", "w") as f:
            json.dump(leaderboard, f)
        logger.debug(f"Leaderboard updated: {nickname} = {duration}s")

# --- Bot WebSocket Protocol ---
# Bots connect to WS /ws and send JSON each turn:
#   {
#     "nickname": str,          # bot's unique name
#     "x":        int (0-9),    # current x position (x+1 = right, x-1 = left)
#     "y":        int (0-9),    # current y position (y+1 = up,   y-1 = down)
#     "energy":   int           # bot's current energy (managed by the bot itself)
#   }
#
# The server responds with:
#   {
#     "positions": [            # up to 24 cells in a 5x5 area around the bot (radius 2),
#                               # excluding the bot's own cell
#       {
#         "x": int,
#         "y": int,
#         "content": null       # empty cell
#                  | {          # item on the cell (e.g. food)
#                      "type":       str,   # item id, matches key in items.json (e.g. "food")
#                      "value":      int,   # energy gained/lost when consumed
#                      "walkable":   bool,  # whether the bot can step on this cell
#                      "consumable": bool,  # whether the item is used up on contact
#                      "symbol":     str,   # display emoji/character
#                      "label":      str    # human-readable name
#                    }
#                  | {          # another bot occupying the cell
#                      "type":     "bot",
#                      "walkable": false
#                    }
#                  | {          # outside the 10x10 map boundary
#                      "type":     "void",
#                      "walkable": false
#                    }
#       }, ...
#     ]
#   }
#
# Item definitions and their full properties are in items.json.
#
# On death (energy <= 0) the server sends:
#   {"positions": []}
# and closes the loop for that bot.
#
# On invalid input the server sends:
#   {"error": "..."}
# ------------------------------
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    client_info = f"{websocket.client.host}:{websocket.client.port}" if websocket.client else "unknown"
    logger.debug(f"WebSocket connection attempt to /ws from {client_info}")
    await websocket.accept()
    logger.debug(f"WebSocket connection accepted to /ws from {client_info}")
    try:
        while True:
            logger.debug(f"Waiting for message from {client_info}")
            data = await websocket.receive_json()
            last_bot_request_time = time.time()
            logger.debug(f"Received JSON data from {client_info}: {data}")
            x = data.get('x')
            y = data.get('y')
            nickname = data.get('nickname')
            bot_energy = data.get('energy')
            
            if not (isinstance(x, int) and isinstance(y, int) and isinstance(nickname, str) and isinstance(bot_energy, int)):
                logger.debug(f"Invalid data from {client_info}: {data}")
                await websocket.send_json({"error": "Datos inválidos"})
                continue
            
            if not (0 <= x < 10 and 0 <= y < 10):
                logger.debug(f"Out of range coordinates from {client_info}: x={x}, y={y}")
                await websocket.send_json({"error": "Coordenadas fuera de rango 0-9"})
                continue
            
            if nickname not in colors:
                if available_colors:
                    colors[nickname] = available_colors.pop(0)
                else:
                    colors[nickname] = 'WHITE'
                start_times[nickname] = time.time()
                start_energies[nickname] = bot_energy
                logger.info(f"Assigned color {colors[nickname]} to new nickname {nickname}")
            # Actualizar posición y energía reportada por el bot
            positions[nickname] = (x, y)
            energy[nickname] = bot_energy
            logger.debug(f"Updated position for {nickname}: ({x}, {y}), energy: {bot_energy}")
            
            # Eliminar comida si el bot está sobre ella (actualiza el estado del campo)
            for f in list(foods):
                if isinstance(f, dict) and f['x'] == x and f['y'] == y:
                    foods.remove(f)
                    logger.debug(f"{nickname} stepped on food at ({x}, {y}), removed from field")
                    break
            if energy[nickname] <= 0:
                # Calcular tiempo de vida
                duration = time.time() - start_times.get(nickname, time.time())
                start_energy = start_energies.get(nickname, 10)
                if duration > record["time"]:
                    record["name"] = nickname
                    record["time"] = duration
                    record["date"] = datetime.now().isoformat()
                    record["start_energy"] = start_energy
                    with open("records.json", "w") as f:
                        json.dump(record, f)
                    logger.info(f"New record: {nickname} survived {duration:.2f} seconds")
                update_leaderboard(nickname)
                del positions[nickname]
                del colors[nickname]
                del energy[nickname]
                del start_times[nickname]
                del start_energies[nickname]
                logger.info(f"{nickname} died due to low energy")
                # Enviar respuesta de muerte
                response = {"positions": []}
                await websocket.send_json(response)
                # Broadcast el grid actualizado
                await manager.broadcast(json.dumps(build_broadcast()))
                break  # Salir del loop para este bot muerto
            
            # Calcular las 24 posiciones alrededor en radio 2
            surroundings = []
            for dx in range(-2, 3):
                for dy in range(-2, 3):
                    if dx == 0 and dy == 0:
                        continue  # No incluir la posición propia
                    nx, ny = x + dx, y + dy
                    if 0 <= nx < 10 and 0 <= ny < 10:
                        # Verificar si hay un árbol en esta posición
                        tree_here = next((t for t in trees if t['x'] == nx and t['y'] == ny), None)
                        # Verificar si hay un bot en esta posición
                        occupied = any(pos == (nx, ny) for pos in positions.values())
                        # Verificar si hay un item en esta posición
                        item_here = next((f for f in foods if isinstance(f, dict) and f['x'] == nx and f['y'] == ny), None)
                        if tree_here:
                            content = {
                                'type': 'banana_tree',
                                'walkable': TREE_DEF['walkable'],
                                'consumable': TREE_DEF['consumable'],
                                'symbol': TREE_DEF['symbol'],
                                'label': TREE_DEF['label']
                            }
                        elif item_here:
                            item_def = ITEMS.get(item_here.get('type', 'food'), FOOD_DEF)
                            content = {
                                'type': item_here.get('type', 'food'),
                                'value': item_here['value'],
                                'walkable': item_def['walkable'],
                                'consumable': item_def['consumable'],
                                'symbol': item_def['symbol'],
                                'label': item_def['label']
                            }
                        elif occupied:
                            bot_def = ITEMS['bot']
                            content = {
                                'type': 'bot',
                                'walkable': bot_def['walkable']
                            }
                        else:
                            content = None
                    else:
                        void_def = ITEMS['void']
                        content = {
                            'type': 'void',
                            'walkable': void_def['walkable']
                        }
                    surroundings.append({'x': nx, 'y': ny, 'content': content})
            
            # Enviar respuesta
            response = {"positions": surroundings}
            logger.debug(f"Sending response to {client_info}")
            await websocket.send_json(response)
            logger.debug(f"Response sent to {client_info}")
            
            # Broadcast el grid actualizado a los clientes web
            logger.debug(f"Broadcasting grid update: {len(manager.active_connections)} connections")
            await manager.broadcast(json.dumps(build_broadcast()))
    except Exception as e:
        import traceback
        logger.debug(f"Error in WebSocket /ws from {client_info}: {e}")
        print(traceback.format_exc())
        print(f"Error: {e}")

@app.websocket("/ws/web")
async def websocket_web(websocket: WebSocket):
    client_info = f"{websocket.client.host}:{websocket.client.port}" if websocket.client else "unknown"
    logger.debug(f"WebSocket connection attempt to /ws/web from {client_info}")
    await websocket.accept()
    await manager.connect(websocket)
    logger.debug(f"WebSocket connection accepted to /ws/web from {client_info}. Total connections: {len(manager.active_connections)}")
    try:
        while True:
            logger.debug(f"Waiting for message from /ws/web client {client_info}")
            message = await websocket.receive_text()
            logger.debug(f"Received text message from /ws/web client {client_info}: {message}")
    except Exception as e:
        logger.debug(f"Error in WebSocket /ws/web from {client_info}: {e}")
        manager.disconnect(websocket)
        logger.debug(f"Disconnected /ws/web client {client_info}. Total connections: {len(manager.active_connections)}")

@app.post("/ws")
async def http_ws_endpoint(request: Request):
    client_info = f"{request.client.host}:{request.client.port}" if request.client else "unknown"
    logger.debug(f"HTTP POST to /ws from {client_info}")
    try:
        data = await request.json()
        last_bot_request_time = time.time()
        logger.debug(f"POST /ws body: {data}")
        
        x = data.get('x')
        y = data.get('y')
        nickname = data.get('nickname')
        bot_energy = data.get('energy')
        
        if not (isinstance(x, int) and isinstance(y, int) and isinstance(nickname, str) and isinstance(bot_energy, int)):
            logger.debug(f"Invalid data from {client_info}: {data}")
            return {"error": "Datos inválidos"}
        
        if not (0 <= x < 10 and 0 <= y < 10):
            logger.debug(f"Out of range coordinates from {client_info}: x={x}, y={y}")
            return {"error": "Coordenadas fuera de rango 0-9"}
        
        # Asignar color si es nuevo
        if nickname not in colors:
            if available_colors:
                colors[nickname] = available_colors.pop(0)
            else:
                colors[nickname] = 'WHITE'
            start_times[nickname] = time.time()
            start_energies[nickname] = bot_energy
            logger.info(f"Assigned color {colors[nickname]} to new nickname {nickname}")
        
        # Actualizar posición y energía reportada por el bot
        positions[nickname] = (x, y)
        energy[nickname] = bot_energy
        logger.debug(f"Updated position for {nickname}: ({x}, {y}), energy: {bot_energy}")
        
        # Eliminar comida si el bot está sobre ella (actualiza el estado del campo)
        for f in list(foods):
            if isinstance(f, dict) and f['x'] == x and f['y'] == y:
                foods.remove(f)
                logger.debug(f"{nickname} stepped on food at ({x}, {y}), removed from field")
                break
        
        if energy[nickname] <= 0:
            update_leaderboard(nickname)
            del positions[nickname]
            del colors[nickname]
            del energy[nickname]
            del start_times[nickname]
            del start_energies[nickname]
            logger.info(f"{nickname} died due to low energy")
        
        # Calcular las 24 posiciones alrededor en radio 2
        surroundings = []
        for dx in range(-2, 3):
            for dy in range(-2, 3):
                if dx == 0 and dy == 0:
                    continue  # No incluir la posición propia
                nx, ny = x + dx, y + dy
                if 0 <= nx < 10 and 0 <= ny < 10:
                    # Verificar si hay un árbol en esta posición
                    tree_here = next((t for t in trees if t['x'] == nx and t['y'] == ny), None)
                    # Verificar si hay un bot en esta posición
                    occupied = any(pos == (nx, ny) for pos in positions.values())
                    # Verificar si hay un item en esta posición
                    item_here = next((f for f in foods if isinstance(f, dict) and f['x'] == nx and f['y'] == ny), None)
                    if tree_here:
                        content = {
                            'type': 'banana_tree',
                            'walkable': TREE_DEF['walkable'],
                            'consumable': TREE_DEF['consumable'],
                            'symbol': TREE_DEF['symbol'],
                            'label': TREE_DEF['label']
                        }
                    elif item_here:
                        item_def = ITEMS.get(item_here.get('type', 'food'), FOOD_DEF)
                        content = {
                            'type': item_here.get('type', 'food'),
                            'value': item_here['value'],
                            'walkable': item_def['walkable'],
                            'consumable': item_def['consumable'],
                            'symbol': item_def['symbol'],
                            'label': item_def['label']
                        }
                    elif occupied:
                        bot_def = ITEMS['bot']
                        content = {
                            'type': 'bot',
                            'walkable': bot_def['walkable']
                        }
                    else:
                        content = None
                else:
                    void_def = ITEMS['void']
                    content = {
                        'type': 'void',
                        'walkable': void_def['walkable']
                    }
                surroundings.append({'x': nx, 'y': ny, 'content': content})
        
        # Enviar respuesta
        response = {"positions": surroundings}
        logger.debug(f"Sending response to {client_info}")
        
        # Broadcast el grid actualizado a los clientes web
        logger.debug(f"Broadcasting grid update: {len(manager.active_connections)} connections")
        await manager.broadcast(json.dumps(build_broadcast()))
        
        return response
    except Exception as e:
        logger.debug(f"Error parsing POST /ws from {client_info}: {e}")
        return {"error": "Invalid JSON"}

@app.post("/kick")
async def kick_bot(request: Request):
    data = await request.json()
    nickname = data.get("nickname")
    if not isinstance(nickname, str) or nickname not in positions:
        return {"error": "Bot not found"}
    update_leaderboard(nickname)
    del positions[nickname]
    if nickname in colors:
        available_colors.insert(0, colors.pop(nickname))
    energy.pop(nickname, None)
    paths.pop(nickname, None)
    remembered.pop(nickname, None)
    start_times.pop(nickname, None)
    start_energies.pop(nickname, None)
    logger.info(f"{nickname} was kicked by admin")
    await manager.broadcast(json.dumps(build_broadcast()))
    return {"ok": True}

@app.get("/", response_class=HTMLResponse)
async def get(request: Request):
    client_info = f"{request.client.host}:{request.client.port}" if request.client else "unknown"
    logger.debug(f"Serving index.html to {client_info}")
    return templates.TemplateResponse(request, "index.html")

if __name__ == "__main__":
    import uvicorn
    logger.debug("Starting server on 0.0.0.0:8001")
    
    async def main():
        # Ensure foods list is clean when starting directly; do NOT pre-populate
        # bananas here — they must be produced only by trees via regenerate_food().
        global foods
        foods = [f for f in foods if isinstance(f, dict)]

        # Server startup will trigger the lifespan manager which creates the
        # regeneration and monitoring background tasks.
        config = uvicorn.Config(app, host="0.0.0.0", port=8001, log_level="warning")
        server = uvicorn.Server(config)
        await server.serve()

    asyncio.run(main())