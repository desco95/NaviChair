"""
OBJETIVO  : Puente MQTT entre la ESP32 y el servidor Python. Recibe la
            telemetría de todos los sensores de NaviChair con timestamp,
            la imprime en consola y puede publicar comandos de vuelta
            hacia los actuadores de la ESP32.
INTEGRANTES: Diana Carolina Plascencia Rodríguez
             María Aurora Rodríguez López
             Escobedo Ojeda Luis David
             Quintero Frausto Valeria Melissa Leilani
PROYECTO   : NaviChair — Sistema Inteligente de Asistencia y Monitoreo
             para Silla de Ruedas Manual
"""

# =============================================================================
# PROYECTO: NaviChair — Sistema Inteligente de Asistencia y Monitoreo
#            para Silla de Ruedas Manual
#
# ARCHIVO: mqtt_bridge.py
# DESCRIPCIÓN: Script de servidor que actúa como puente MQTT. Se suscribe
#              a los tópicos de telemetría de la ESP32 (sensores) y puede
#              publicar comandos hacia los actuadores. Registra cada mensaje
#              con marca de tiempo (timestamp). Es el punto de entrada de
#              datos al servidor Python antes de pasar al pipeline de IA.
# =============================================================================

import paho.mqtt.client as mqtt
import json
import datetime

# -----------------------------------------------------------------------
# CONFIGURACIÓN DEL BROKER MQTT
# Cambia DIRECCION_BROKER por la IP de tu computadora en la red local.
# Para encontrarla: en Windows ejecuta "ipconfig", en Linux/Mac "ifconfig"
# -----------------------------------------------------------------------
DIRECCION_BROKER = "localhost"   # o la IP de tu PC, ej: "192.168.1.100"
PUERTO_BROKER    = 1883
ID_CLIENTE       = "navichair_servidor_python"

# -----------------------------------------------------------------------
# TABLA DE TÓPICOS
# Publicación (ESP32 → Servidor):
#   navichair/obstaculos   — distancias de los 3 sensores ultrasónicos
#   navichair/inclinacion  — ángulo del MPU-6050 en grados
#   navichair/inmovilidad  — minutos sin detectar movimiento (PIR)
#   navichair/estado       — resumen JSON completo de todos los sensores
#   navichair/camara       — imagen en base64 de la ESP32-CAM
#
# Suscripción (Servidor → ESP32):
#   navichair/cmd/buzzer   — comando para activar/desactivar el buzzer
#   navichair/cmd/relevador — comando para activar/desactivar el relevador
# -----------------------------------------------------------------------
TOPICOS_SUSCRIPCION = [
    ("navichair/obstaculos",  0),
    ("navichair/inclinacion", 0),
    ("navichair/inmovilidad", 0),
    ("navichair/estado",      0),
    ("navichair/camara",      0),
]


def marca_de_tiempo():
    """
    Parámetros : Ninguno
    Descripción: Genera una cadena con la fecha y hora actual en formato
                 legible para incluir en los registros de consola.
    Retorna    : Cadena de texto con la fecha/hora actual (str).
    """
    ahora = datetime.datetime.now()
    return ahora.strftime("[%Y-%m-%d %H:%M:%S]")


def al_conectar(cliente, datos_usuario, indicadores, codigo_resultado):
    """
    Parámetros : cliente          — instancia del cliente MQTT
                 datos_usuario    — datos de usuario (no usado)
                 indicadores      — flags de conexión
                 codigo_resultado — 0 si la conexión fue exitosa
    Descripción: Callback que se ejecuta cuando el cliente se conecta al
                 broker. Si la conexión es exitosa, se suscribe a todos
                 los tópicos definidos en TOPICOS_SUSCRIPCION.
    Retorna    : None
    """
    if codigo_resultado == 0:
        print("{} Conectado al broker MQTT en {}:{}".format(
            marca_de_tiempo(), DIRECCION_BROKER, PUERTO_BROKER))
        for topico, qos in TOPICOS_SUSCRIPCION:
            cliente.subscribe(topico, qos)
            print("  → Suscrito a: {}".format(topico))
    else:
        print("{} ERROR al conectar. Código: {}".format(
            marca_de_tiempo(), codigo_resultado))


def al_desconectar(cliente, datos_usuario, codigo_resultado):
    """
    Parámetros : cliente          — instancia del cliente MQTT
                 datos_usuario    — datos de usuario
                 codigo_resultado — código de desconexión
    Descripción: Callback que se ejecuta cuando el cliente pierde la
                 conexión con el broker.
    Retorna    : None
    """
    print("{} Desconectado del broker. Código: {}".format(
        marca_de_tiempo(), codigo_resultado))


def al_recibir_mensaje(cliente, datos_usuario, mensaje):
    """
    Parámetros : cliente       — instancia del cliente MQTT
                 datos_usuario — datos de usuario
                 mensaje       — objeto con .topic y .payload
    Descripción: Callback principal. Se ejecuta cada vez que llega un
                 mensaje a cualquiera de los tópicos suscritos. Imprime
                 el tópico, el timestamp y el contenido del mensaje.
                 Si el tópico es 'estado', intenta parsear el JSON para
                 mostrarlo de forma más legible.
    Retorna    : None
    """
    topico  = mensaje.topic
    carga   = mensaje.payload.decode("utf-8", errors="replace")
    tiempo  = marca_de_tiempo()

    # El tópico de cámara puede tener mucho contenido (base64),
    # solo mostramos los primeros 60 caracteres para no saturar la consola
    if topico == "navichair/camara":
        print("{} [{}] imagen recibida ({} bytes)".format(
            tiempo, topico, len(mensaje.payload)))
        return

    # Para el tópico de estado general, intentar mostrar el JSON formateado
    if topico == "navichair/estado":
        try:
            datos = json.loads(carga)
            print("{} [{}] → Izq:{:.0f}cm  Cen:{:.0f}cm  Der:{:.0f}cm  "
                  "Incl:{:.1f}°  Inmov:{:.1f}min".format(
                      tiempo, topico,
                      datos.get("izq", 0), datos.get("cen", 0),
                      datos.get("der", 0), datos.get("incl", 0),
                      datos.get("inmov", 0)))
        except Exception:
            print("{} [{}] → {}".format(tiempo, topico, carga))
        return

    # Para el resto de tópicos, imprimir el valor directamente
    print("{} [{}] → {}".format(tiempo, topico, carga))


def publicar_comando(cliente, topico_comando, valor):
    """
    Parámetros : cliente         — instancia del cliente MQTT conectado
                 topico_comando  — tópico al que se publica (str)
                 valor           — valor a publicar, ej. "ON" o "OFF" (str)
    Descripción: Publica un comando hacia la ESP32 en el tópico indicado.
                 Usado para activar o desactivar actuadores de forma remota.
    Retorna    : None
    """
    resultado = cliente.publish(topico_comando, valor)
    print("{} Comando publicado → [{}] : {}".format(
        marca_de_tiempo(), topico_comando, valor))
    return resultado


# -----------------------------------------------------------------------
# PROGRAMA PRINCIPAL
# -----------------------------------------------------------------------

if __name__ == "__main__":
    # Crear e inicializar el cliente MQTT
    cliente_mqtt = mqtt.Client(client_id=ID_CLIENTE, protocol=mqtt.MQTTv311)

    # Registrar los callbacks
    cliente_mqtt.on_connect    = al_conectar
    cliente_mqtt.on_disconnect = al_desconectar
    cliente_mqtt.on_message    = al_recibir_mensaje

    print("{} Iniciando puente MQTT NaviChair...".format(marca_de_tiempo()))

    try:
        # Conectar al broker
        cliente_mqtt.connect(DIRECCION_BROKER, PUERTO_BROKER, keepalive=60)

        # Mantener el bucle activo escuchando mensajes indefinidamente
        # loop_forever() maneja reconexiones automáticamente
        cliente_mqtt.loop_forever()

    except KeyboardInterrupt:
        print("\n{} Puente MQTT detenido manualmente.".format(marca_de_tiempo()))
        cliente_mqtt.disconnect()

    except ConnectionRefusedError:
        print("{} ERROR: No se pudo conectar al broker en {}:{}".format(
            marca_de_tiempo(), DIRECCION_BROKER, PUERTO_BROKER))
        print("  Verifica que Mosquitto esté corriendo: mosquitto -v")
