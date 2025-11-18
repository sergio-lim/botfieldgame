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
    
    async with websockets.connect(uri) as websocket:
        while True:
            # Enviar datos actuales
            data = {
                "x": x,
                "y": y,
                "nickname": nickname,
                "energy": energy
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
                        print(f"Moviendo hacia comida en ({closest_food['x']}, {closest_food['y']}): nueva posición ({x}, {y})")
                    else:
                        # Movimiento random si no puede ir hacia comida
                        valid_moves = [pos for pos in positions_list if pos['content'] in [None, 'food'] and 0 <= pos['x'] < 10 and 0 <= pos['y'] < 10 and abs(pos['x'] - x) + abs(pos['y'] - y) == 1]
                        if valid_moves:
                            new_pos = random.choice(valid_moves)
                            x, y = new_pos['x'], new_pos['y']
                            print(f"Nueva posición aleatoria: ({x}, {y})")
                        else:
                            print("No hay movimientos disponibles")
                else:
                    # Movimiento random
                    valid_moves = [pos for pos in positions_list if pos['content'] in [None, 'food'] and 0 <= pos['x'] < 10 and 0 <= pos['y'] < 10 and abs(pos['x'] - x) + abs(pos['y'] - y) == 1]
                    if valid_moves:
                        new_pos = random.choice(valid_moves)
                        x, y = new_pos['x'], new_pos['y']
                        print(f"Nueva posición aleatoria: ({x}, {y})")
                    else:
                        print("No hay movimientos disponibles")
                    if valid_moves:
                        new_pos = random.choice(valid_moves)
                        x, y = new_pos['x'], new_pos['y']
                        print(f"Nueva posición aleatoria: ({x}, {y})")
                    else:
                        print("No hay movimientos disponibles")
            else:
                print("No hay posiciones disponibles, manteniendo posición")
            
            # Esperar 2 segundos
            await asyncio.sleep(2)

if __name__ == "__main__":
    asyncio.run(bot())