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

app = FastAPI()

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

# Templates
templates = Jinja2Templates(directory="templates")

# Generar 15 comidas random al inicio
import random
foods = [f for f in foods if isinstance(f, dict)]  # Limpiar viejos tuples si existen
foods = [{'x': i % 10, 'y': i // 10, 'value': 5} for i in range(15)]

# Función para regenerar comida
async def regenerate_food():
    while True:
        await asyncio.sleep(35)
        foods[:] = [f for f in foods if isinstance(f, dict)]  # Limpiar viejos tuples
        if len(foods) < 15:
            # Encontrar posición vacía
            attempts = 0
            while attempts < 100:  # Evitar loop infinito
                x = random.randint(0, 9)
                y = random.randint(0, 9)
                pos = (x, y)
                if not any(f.get('x') == x and f.get('y') == y for f in foods if isinstance(f, dict)) and pos not in positions.values():
                    foods.append({'x': x, 'y': y, 'value': 5})
                    logger.debug(f"Regenerated food at ({x}, {y})")
                    break
                attempts += 1

# Iniciar regeneración en startup
@app.on_event("startup")
async def startup_event():
    asyncio.create_task(regenerate_food())

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
    for nick, (x, y) in positions.items():
        color = colors[nick]
        if nick == 'orion':
            symbol = '🦖'
        elif nick == 'Xenon':
            symbol = '🗿'
        else:
            symbol = nick[0].upper()  # Primera letra del nickname
        grid[y][x] = {"symbol": symbol, "color": color}
    for f in foods:
        if isinstance(f, dict):
            grid[f['y']][f['x']] = '🍌'
    
    # Marcar caminos recorridos con color tenue
    for nick, path in paths.items():
        color = colors.get(nick, 'WHITE')
        dim_color = f"{color}_dim"
        for px, py in path:
            if grid[py][px] == '.':
                grid[py][px] = {"symbol": "", "color": dim_color}
    
    logger.debug(f"Grid generated with {len(positions)} positions and {len(foods)} foods")
    return grid

def reset_field():
    global foods, positions, colors, energy, paths, start_times, start_energies, last_bot_request_time
    foods = [{'x': i % 10, 'y': i // 10, 'value': 5} for i in range(10)]
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
            
            if not (isinstance(x, int) and isinstance(y, int) and isinstance(nickname, str)):
                logger.debug(f"Invalid data from {client_info}: {data}")
                await websocket.send_json({"error": "Datos inválidos"})
                continue
            
            if not (0 <= x < 10 and 0 <= y < 10):
                logger.debug(f"Out of range coordinates from {client_info}: x={x}, y={y}")
                await websocket.send_json({"error": "Coordenadas fuera de rango 0-9"})
                continue
            
            # Asignar color si es nuevo
            if nickname not in colors:
                if available_colors:
                    colors[nickname] = available_colors.pop(0)
                else:
                    colors[nickname] = 'WHITE'  # Default si no hay más colores
                energy[nickname] = 10  # Energía inicial
                paths[nickname] = [[x, y]]  # Inicializar camino
                remembered[nickname] = set()  # Inicializar recordadas
                start_times[nickname] = time.time()
                start_energies[nickname] = 10
                logger.info(f"Assigned color {colors[nickname]} to new nickname {nickname} with 10 energy")
            # Actualizar posición
            positions[nickname] = (x, y)
            logger.debug(f"Updated position for {nickname}: ({x}, {y})")
            
            # Actualizar camino
            paths[nickname] = data.get('path', paths.get(nickname, []))
            
            # Actualizar comidas recordadas
            remembered[nickname] = set(tuple(pos) for pos in data.get("remembered", []))
            
            consumed = False
            # Consumir comida objetivo si especificada
            if 'target_food' in data:
                tx, ty = data['target_food']
                for f in list(foods):  # copy to avoid modification during iteration
                    if isinstance(f, dict) and f['x'] == tx and f['y'] == ty:
                        foods.remove(f)
                        energy[nickname] += f['value']
                        consumed = True
                        logger.debug(f"{nickname} consumed target food at ({tx}, {ty}), energy +{f['value']}, now {energy[nickname]}")
                        break
            
            # Consumir comida si hay en la posición (por si acaso)
            for f in list(foods):
                if isinstance(f, dict) and f['x'] == x and f['y'] == y:
                    foods.remove(f)
                    energy[nickname] += f['value']
                    consumed = True
                    logger.debug(f"{nickname} consumed food at ({x}, {y}), energy +{f['value']}, now {energy[nickname]}")
                    break
            
            # Perder energía solo si no consumió
            if not consumed:
                energy[nickname] -= 1
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
                del positions[nickname]
                del colors[nickname]
                del energy[nickname]
                del paths[nickname]
                del remembered[nickname]
                del start_times[nickname]
                del start_energies[nickname]
                logger.info(f"{nickname} died due to low energy")
                # Remover bot del juego
                del positions[nickname]
                # Enviar respuesta de muerte
                response = {"positions": [], "energy": 0}
                await websocket.send_json(response)
                # Broadcast el grid actualizado
                grid_data = {"grid": get_grid(), "energies": dict(energy), "record": record, "remembered": {nick: list(rem) for nick, rem in remembered.items()}}
                await manager.broadcast(json.dumps(grid_data))
                break  # Salir del loop para este bot muerto
            
            # Calcular las 24 posiciones alrededor en radio 2
            surroundings = []
            for dx in range(-2, 3):
                for dy in range(-2, 3):
                    if dx == 0 and dy == 0:
                        continue  # No incluir la posición propia
                    nx, ny = x + dx, y + dy
                    if 0 <= nx < 10 and 0 <= ny < 10:
                        # Verificar si hay un bot en esta posición
                        occupied = any(pos == (nx, ny) for pos in positions.values())
                        content = 'bot' if occupied else None
                        # Verificar si hay comida
                        food_here = next((f for f in foods if isinstance(f, dict) and f['x'] == nx and f['y'] == ny), None)
                        if food_here:
                            content = {'type': 'food', 'value': food_here['value']}
                        elif occupied:
                            content = {'type': 'bot'}
                        else:
                            content = None
                    else:
                        content = None  # Fuera del mapa
                    surroundings.append({'x': nx, 'y': ny, 'content': content})
            
            # Enviar respuesta
            response = {"positions": surroundings, "energy": energy[nickname]}
            logger.debug(f"Sending response to {client_info}")
            await websocket.send_json(response)
            logger.debug(f"Response sent to {client_info}")
            
            # Broadcast el grid actualizado a los clientes web
            grid_data = {"grid": get_grid(), "energies": dict(energy), "record": record, "remembered": {nick: list(rem) for nick, rem in remembered.items()}}
            logger.debug(f"Broadcasting grid update: {len(manager.active_connections)} connections")
            await manager.broadcast(json.dumps(grid_data))
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
        
        if not (isinstance(x, int) and isinstance(y, int) and isinstance(nickname, str)):
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
                colors[nickname] = 'WHITE'  # Default si no hay más colores
            energy[nickname] = 30  # Energía inicial
            paths[nickname] = [[x, y]]  # Inicializar camino
            logger.info(f"Assigned color {colors[nickname]} to new nickname {nickname} with 30 energy")
        
        # Actualizar posición
        positions[nickname] = (x, y)
        logger.debug(f"Updated position for {nickname}: ({x}, {y})")
        
        # Actualizar camino
        paths[nickname] = data.get('path', paths.get(nickname, []))
        
        consumed = False
        # Consumir comida si hay
        if (x, y) in foods:
            foods.remove((x, y))
            energy[nickname] += 1
            consumed = True
            logger.debug(f"{nickname} consumed food at ({x}, {y}), energy now {energy[nickname]}")
        
        # Perder energía solo si no consumió
        if not consumed:
            energy[nickname] -= 1
        if energy[nickname] <= 0:
            del positions[nickname]
            del colors[nickname]
            del energy[nickname]
            del paths[nickname]
            logger.info(f"{nickname} died due to low energy")
            # No broadcast aquí, ya que se hará después
        
        # Calcular las 24 posiciones alrededor en radio 2
        surroundings = []
        for dx in range(-2, 3):
            for dy in range(-2, 3):
                if dx == 0 and dy == 0:
                    continue  # No incluir la posición propia
                nx, ny = x + dx, y + dy
                if 0 <= nx < 10 and 0 <= ny < 10:
                    # Verificar si hay un bot en esta posición
                    occupied = any(pos == (nx, ny) for pos in positions.values())
                    if (nx, ny) in foods:
                        content = 'food'
                    elif occupied:
                        content = 'bot'
                    else:
                        content = None
                else:
                    content = None  # Fuera del mapa
                surroundings.append({'x': nx, 'y': ny, 'content': content})
        
        # Enviar respuesta
        response = {"positions": surroundings, "energy": energy[nickname]}
        logger.debug(f"Sending response to {client_info}")
        
        # Broadcast el grid actualizado a los clientes web
        grid_data = {"grid": get_grid(), "energies": dict(energy)}
        logger.debug(f"Broadcasting grid update: {len(manager.active_connections)} connections")
        await manager.broadcast(json.dumps(grid_data))
        
        return response
    except Exception as e:
        logger.debug(f"Error parsing POST /ws from {client_info}: {e}")
        return {"error": "Invalid JSON"}

@app.get("/", response_class=HTMLResponse)
async def get(request: Request):
    client_info = f"{request.client.host}:{request.client.port}" if request.client else "unknown"
    logger.debug(f"Serving index.html to {client_info}")
    return templates.TemplateResponse("index.html", {"request": request})

if __name__ == "__main__":
    import uvicorn
    logger.debug("Starting server on 0.0.0.0:8000")
    
    async def main():
        # Inicializar comida
        global foods
        foods = [f for f in foods if isinstance(f, dict)] + [{'x': random.randint(0,9), 'y': random.randint(0,9), 'value':5} for _ in range(10)]
        
        # Lanzar tasks
        asyncio.create_task(regenerate_food())
        asyncio.create_task(monitor_activity())
        
        config = uvicorn.Config(app, host="0.0.0.0", port=8000, log_level="warning")
        server = uvicorn.Server(config)
        await server.serve()
    
    asyncio.run(main())