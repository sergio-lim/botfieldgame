# Bot Field Game

Un servidor WebSocket en Python con FastAPI para un campo de bots 10x10, con visualización web en tiempo real.

## Instalación

1. Instala las dependencias:
   pip install -r requirements.txt

## Ejecución

Ejecuta el servidor:
python main.py

El servidor estará en http://localhost:8000

Abre http://localhost:8000 en tu navegador para ver el campo en tiempo real.

## Uso

Los bots se conectan via WebSocket a /ws

Envían JSON: {"x": int, "y": int, "nickname": str}

El servidor asigna un color único al nickname, registra la posición, y devuelve una lista de posiciones a 1 paso en cada dirección (arriba, abajo, izquierda, derecha) dentro del rango, excluyendo posiciones ocupadas por otros bots para evitar choques.

La página web se actualiza automáticamente mostrando las posiciones de los bots coloreadas.

## Bot de ejemplo

Hay un bot de ejemplo en `bot.py` que se conecta al servidor, envía su posición inicial aleatoria, recibe la lista de movimientos disponibles (posiciones a 1 paso en cada dirección), elige uno aleatoriamente para la próxima posición, y repite cada 2 segundos.

Para ejecutarlo (en otra terminal, después de iniciar el servidor):
python bot.py

## Ejemplo

Conectar con un cliente WebSocket, enviar {"x": 5, "y": 5, "nickname": "Bot1"}

Recibir {"moves": [[4,5],[6,5],[5,4],[5,6]]}

Y en la web se muestra el grid con 'B' en rojo en (5,5)