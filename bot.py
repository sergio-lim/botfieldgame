import asyncio
import websockets
import json
import random

async def bot():
    uri = "ws://localhost:8000/ws"
    nickname = "orion"
    energy = 10  # Energía inicial
    
    # Posición inicial aleatoria
    x = random.randint(0, 9)
    y = random.randint(0, 9)
    
    visited = set()  # Conjunto de posiciones visitadas
    path = [[x, y]]  # Lista del camino recorrido
    visited.add((x, y))  # Agregar posición inicial
    
    async with websockets.connect(uri) as websocket:
        while True:
            # Enviar datos actuales
            data = {
                "x": x,
                "y": y,
                "nickname": nickname,
                "energy": energy,
                "path": path
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
            
            # Si hay positions disponibles, elegir una vacía adyacente aleatoriamente para la próxima posición
            if "positions" in response and response["positions"]:
                positions_list = response["positions"]
                # Encontrar comidas visibles
                foods = [pos for pos in positions_list if pos['content'] == 'food']
                if foods:
                    # Encontrar la comida más cercana
                    closest_food = min(foods, key=lambda f: abs(f['x'] - x) + abs(f['y'] - y))
                    # Encontrar movimientos adyacentes válidos
                    candidates = [pos for pos in positions_list if pos['content'] in [None, 'food'] and 0 <= pos['x'] < 10 and 0 <= pos['y'] < 10 and abs(pos['x'] - x) + abs(pos['y'] - y) == 1]
                    if candidates:
                        # Elegir el que tenga menor distancia a la comida más cercana
                        new_pos = min(candidates, key=lambda p: abs(p['x'] - closest_food['x']) + abs(p['y'] - closest_food['y']))
                        x, y = new_pos['x'], new_pos['y']
                        visited.add((x, y))
                        path.append([x, y])
                        print(f"Moviendo hacia comida en ({closest_food['x']}, {closest_food['y']}): nueva posición ({x}, {y})")
                    else:
                        # Movimiento random si no puede ir hacia comida
                        valid_moves = [pos for pos in positions_list if pos['content'] in [None, 'food'] and 0 <= pos['x'] < 10 and 0 <= pos['y'] < 10 and abs(pos['x'] - x) + abs(pos['y'] - y) == 1]
                        if valid_moves:
                            new_pos = random.choice(valid_moves)
                            x, y = new_pos['x'], new_pos['y']
                            visited.add((x, y))
                            path.append([x, y])
                            print(f"Nueva posición aleatoria: ({x}, {y})")
                        else:
                            print("No hay movimientos disponibles")
                else:
                    # Movimiento para explorar: elegir la posición adyacente más lejana a cualquier posición del camino
                    valid_moves = [pos for pos in positions_list if pos['content'] in [None, 'food'] and 0 <= pos['x'] < 10 and 0 <= pos['y'] < 10 and abs(pos['x'] - x) + abs(pos['y'] - y) == 1]
                    if valid_moves:
                        # Calcular distancia mínima a cualquier posición del camino para cada movimiento válido
                        move_scores = []
                        for pos in valid_moves:
                            nx, ny = pos['x'], pos['y']
                            if path:
                                min_dist = min(abs(nx - px) + abs(ny - py) for px, py in path)
                            else:
                                min_dist = 0  # Si no hay camino, distancia 0
                            move_scores.append((min_dist, pos))
                        # Elegir el movimiento con la mayor distancia mínima (más exploratorio)
                        max_dist = max(score[0] for score in move_scores)
                        best_moves = [pos for dist, pos in move_scores if dist == max_dist]
                        new_pos = random.choice(best_moves)
                        x, y = new_pos['x'], new_pos['y']
                        visited.add((x, y))
                        path.append([x, y])
                        print(f"Nueva posición exploratoria: ({x}, {y}) con distancia {max_dist}")
                    else:
                        print("No hay movimientos disponibles")
            else:
                print("No hay posiciones disponibles, manteniendo posición")
            
            # Esperar 2 segundos
            await asyncio.sleep(2)

if __name__ == "__main__":
    asyncio.run(bot())