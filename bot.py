import asyncio
import websockets
import json
import random
import os

async def bot():
    # Usar variable de entorno para la URL del WebSocket, por defecto localhost
    ws_url = os.getenv("WEBSOCKET_URL", "ws://localhost:8000/ws")
    nickname = "orion"
    energy = 10  # Energía inicial
    energy_threshold = 10  # Umbral para custodiar comida
    
    # Posición inicial aleatoria
    x = random.randint(0, 9)
    y = random.randint(0, 9)
    
    known_foods = set()  # recordar posiciones de comida vistas
    current_direction = (1, 0)  # Dirección inicial: derecha (dx, dy)
    
    async with websockets.connect(ws_url) as websocket:
        while True:
            # Enviar datos actuales
            data = {
                "x": x,
                "y": y,
                "nickname": nickname,
                "energy": energy,
                "remembered": list(known_foods)
            }
            await websocket.send(json.dumps(data))
            print(f"Enviado: {data}")
            
            # Recibir respuesta
            response_str = await websocket.recv()
            response = json.loads(response_str)
            print(f"Recibido: {response}")
            
            # Actualizar energía
            if 'energy' in response:
                energy = response['energy']
            
            # Si hay positions disponibles, elegir movimiento
            if "positions" in response and response["positions"]:
                positions_list = response["positions"]
                
                # Encontrar comidas visibles
                foods = [pos for pos in positions_list if pos['content'] and pos['content']['type'] == 'food']
                
                # Actualizar memoria de comidas
                for f in foods:
                    known_foods.add((f['x'], f['y']))
                
                # Remover comidas recordadas que ya no existen (si el bot está en esa posición y no la ve)
                if (x, y) in known_foods and not any(f['x'] == x and f['y'] == y for f in foods):
                    known_foods.discard((x, y))
                
                candidates = [pos for pos in positions_list if (pos['content'] is None or pos['content']['type'] == 'food') and abs(pos['x'] - x) <= 1 and abs(pos['y'] - y) <= 1 and not (pos['x'] == x and pos['y'] == y)]
                if not candidates:
                    print("No hay movimientos disponibles")
                    await asyncio.sleep(2)
                    continue
                
                # Encontrar el objetivo más cercano: visible o recordado
                all_targets = known_foods | {(f['x'], f['y']) for f in foods}
                if all_targets:
                    closest = min(all_targets, key=lambda p: abs(p[0] - x) + abs(p[1] - y))
                    cx, cy = closest
                    dist_to_closest = abs(cx - x) + abs(cy - y)
                    
                    # Verificar si es visible
                    is_visible = any(f['x'] == cx and f['y'] == cy for f in foods)
                    
                    if is_visible and energy > energy_threshold and dist_to_closest <= 3:
                        # Custodiar: moverse aleatoriamente alrededor de la comida
                        print(f"Custodiando comida en ({cx}, {cy}) - moviendo alrededor")
                        new_pos = random.choice(candidates)
                    else:
                        # Ir hacia el objetivo más cercano
                        new_pos = min(candidates, key=lambda p: abs(p['x'] - cx) + abs(p['y'] - cy))
                        print(f"Yendo a comida en ({cx}, {cy}) {'visible' if is_visible else 'recordada'}")
                else:
                    # No hay objetivos: modo supervivencia - explorar sistemáticamente
                    preferred = [pos for pos in candidates if pos['x'] - x == current_direction[0] and pos['y'] - y == current_direction[1]]
                    if preferred:
                        new_pos = random.choice(preferred)
                        print(f"Explorando en dirección {current_direction}")
                    else:
                        new_pos = random.choice(candidates)
                        # Actualizar dirección al movimiento elegido
                        current_direction = (new_pos['x'] - x, new_pos['y'] - y)
                        print(f"Cambiando dirección a {current_direction}")
                
                # Actualizar posición
                x, y = new_pos['x'], new_pos['y']
                x = max(0, min(9, x))
                y = max(0, min(9, y))
            else:
                print("No hay posiciones disponibles, manteniendo posición")
            
            # Esperar 2 segundos
            await asyncio.sleep(2)

if __name__ == "__main__":
    asyncio.run(bot())