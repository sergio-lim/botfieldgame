from fastapi import FastAPI, WebSocket, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from starlette.middleware.base import BaseHTTPMiddleware
from colorama import Fore, Style, init
from typing import List
import json
import logging

# Configurar logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

app = FastAPI()

# Middleware para logging de todas las peticiones HTTP
class LoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        logger.info(f"HTTP Request: {request.method} {request.url} from {request.client.host if request.client else 'unknown'}")
        response = await call_next(request)
        logger.info(f"HTTP Response: {response.status_code} for {request.method} {request.url}")
        return response

app.add_middleware(LoggingMiddleware)

# Estado del campo
positions = {}  # nickname: (x, y)
colors = {}     # nickname: color_name
energy = {}     # nickname: int
foods = set()   # set of (x, y)
available_colors = ['RED', 'GREEN', 'BLUE', 'YELLOW', 'MAGENTA', 'CYAN', 'WHITE']

# Inicializar colorama (para posibles logs futuros)
init(autoreset=True)

# Templates
templates = Jinja2Templates(directory="templates")

# Generar 6 comidas random al inicio
import random
while len(foods) < 6:
    x = random.randint(0, 9)
    y = random.randint(0, 9)
    foods.add((x, y))

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
        logger.info(f"Disconnected WebSocket from {client_info}. Total: {len(self.active_connections)}")

    async def broadcast(self, message: str):
        logger.debug(f"Broadcasting message to {len(self.active_connections)} connections: {message[:100]}...")
        disconnected = []
        for connection in self.active_connections:
            try:
                await connection.send_text(message)
            except Exception as e:
                client_info = f"{connection.client.host}:{connection.client.port}" if connection.client else "unknown"
                logger.warning(f"Failed to send to {client_info}: {e}")
                disconnected.append(connection)
        for conn in disconnected:
            self.disconnect(conn)

manager = ConnectionManager()

def get_grid():
    logger.debug("Generating grid")
    grid = [['.' for _ in range(10)] for _ in range(10)]
    for nick, (x, y) in positions.items():
        color = colors[nick]
        symbol = nick[0].upper()  # Primera letra del nickname
        grid[y][x] = {"symbol": symbol, "color": color}
    for fx, fy in foods:
        grid[fy][fx] = 'F'
    logger.debug(f"Grid generated with {len(positions)} positions and {len(foods)} foods")
    return grid

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    client_info = f"{websocket.client.host}:{websocket.client.port}" if websocket.client else "unknown"
    logger.info(f"WebSocket connection attempt to /ws from {client_info}")
    await websocket.accept()
    logger.info(f"WebSocket connection accepted to /ws from {client_info}")
    try:
        while True:
            logger.debug(f"Waiting for message from {client_info}")
            data = await websocket.receive_json()
            logger.info(f"Received JSON data from {client_info}: {data}")
            x = data.get('x')
            y = data.get('y')
            nickname = data.get('nickname')
            
            if not (isinstance(x, int) and isinstance(y, int) and isinstance(nickname, str)):
                logger.warning(f"Invalid data from {client_info}: {data}")
                await websocket.send_json({"error": "Datos inválidos"})
                continue
            
            if not (0 <= x < 10 and 0 <= y < 10):
                logger.warning(f"Out of range coordinates from {client_info}: x={x}, y={y}")
                await websocket.send_json({"error": "Coordenadas fuera de rango 0-9"})
                continue
            
            # Asignar color si es nuevo
            if nickname not in colors:
                if available_colors:
                    colors[nickname] = available_colors.pop(0)
                else:
                    colors[nickname] = 'WHITE'  # Default si no hay más colores
                energy[nickname] = 10  # Energía inicial
                logger.info(f"Assigned color {colors[nickname]} to new nickname {nickname} with 10 energy")
            # Actualizar posición
            positions[nickname] = (x, y)
            logger.debug(f"Updated position for {nickname}: ({x}, {y})")
            
            consumed = False
            # Consumir comida si hay
            if (x, y) in foods:
                foods.remove((x, y))
                energy[nickname] += 1
                consumed = True
                logger.info(f"{nickname} consumed food at ({x}, {y}), energy now {energy[nickname]}")
            
            # Perder energía solo si no consumió
            if not consumed:
                energy[nickname] -= 1
            if energy[nickname] <= 0:
                del positions[nickname]
                del colors[nickname]
                del energy[nickname]
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
                        content = 'bot' if occupied else None
                        # Verificar si hay comida
                        if (nx, ny) in foods:
                            content = 'food'
                    else:
                        content = None  # Fuera del mapa
                    surroundings.append({'x': nx, 'y': ny, 'content': content})
            
            # Enviar respuesta
            response = {"positions": surroundings, "energy": energy[nickname]}
            logger.info(f"Sending response to {client_info}")
            await websocket.send_json(response)
            logger.info(f"Response sent to {client_info}")
            
            # Broadcast el grid actualizado a los clientes web
            grid_data = {"grid": get_grid(), "energies": dict(energy)}
            logger.info(f"Broadcasting grid update: {len(manager.active_connections)} connections")
            await manager.broadcast(json.dumps(grid_data))
    except Exception as e:
        logger.error(f"Error in WebSocket /ws from {client_info}: {e}")
        print(f"Error: {e}")

@app.websocket("/ws/web")
async def websocket_web(websocket: WebSocket):
    client_info = f"{websocket.client.host}:{websocket.client.port}" if websocket.client else "unknown"
    logger.info(f"WebSocket connection attempt to /ws/web from {client_info}")
    await websocket.accept()
    await manager.connect(websocket)
    logger.info(f"WebSocket connection accepted to /ws/web from {client_info}. Total connections: {len(manager.active_connections)}")
    try:
        while True:
            logger.debug(f"Waiting for message from /ws/web client {client_info}")
            message = await websocket.receive_text()
            logger.info(f"Received text message from /ws/web client {client_info}: {message}")
    except Exception as e:
        logger.error(f"Error in WebSocket /ws/web from {client_info}: {e}")
        manager.disconnect(websocket)
        logger.info(f"Disconnected /ws/web client {client_info}. Total connections: {len(manager.active_connections)}")

@app.post("/ws")
async def http_ws_endpoint(request: Request):
    client_info = f"{request.client.host}:{request.client.port}" if request.client else "unknown"
    logger.info(f"HTTP POST to /ws from {client_info}")
    try:
        data = await request.json()
        logger.info(f"POST /ws body: {data}")
        
        x = data.get('x')
        y = data.get('y')
        nickname = data.get('nickname')
        
        if not (isinstance(x, int) and isinstance(y, int) and isinstance(nickname, str)):
            logger.warning(f"Invalid data from {client_info}: {data}")
            return {"error": "Datos inválidos"}
        
        if not (0 <= x < 10 and 0 <= y < 10):
            logger.warning(f"Out of range coordinates from {client_info}: x={x}, y={y}")
            return {"error": "Coordenadas fuera de rango 0-9"}
        
        # Asignar color si es nuevo
        if nickname not in colors:
            if available_colors:
                colors[nickname] = available_colors.pop(0)
            else:
                colors[nickname] = 'WHITE'  # Default si no hay más colores
            energy[nickname] = 10  # Energía inicial
            logger.info(f"Assigned color {colors[nickname]} to new nickname {nickname} with 10 energy")
        
        # Actualizar posición
        positions[nickname] = (x, y)
        logger.debug(f"Updated position for {nickname}: ({x}, {y})")
        
        consumed = False
        # Consumir comida si hay
        if (x, y) in foods:
            foods.remove((x, y))
            energy[nickname] += 1
            consumed = True
            logger.info(f"{nickname} consumed food at ({x}, {y}), energy now {energy[nickname]}")
        
        # Perder energía solo si no consumió
        if not consumed:
            energy[nickname] -= 1
        if energy[nickname] <= 0:
            del positions[nickname]
            del colors[nickname]
            del energy[nickname]
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
        logger.info(f"Sending response to {client_info}")
        
        # Broadcast el grid actualizado a los clientes web
        grid_data = {"grid": get_grid(), "energies": dict(energy)}
        logger.info(f"Broadcasting grid update: {len(manager.active_connections)} connections")
        await manager.broadcast(json.dumps(grid_data))
        
        return response
    except Exception as e:
        logger.error(f"Error parsing POST /ws from {client_info}: {e}")
        return {"error": "Invalid JSON"}

@app.get("/", response_class=HTMLResponse)
async def get(request: Request):
    client_info = f"{request.client.host}:{request.client.port}" if request.client else "unknown"
    logger.info(f"Serving index.html to {client_info}")
    return templates.TemplateResponse("index.html", {"request": request})

if __name__ == "__main__":
    import uvicorn
    logger.info("Starting server on 0.0.0.0:8000")
    
    uvicorn.run(app, host="0.0.0.0", port=8000)