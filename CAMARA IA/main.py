"""
OBJETIVO: Nodo de captura y actuación en el pipeline de IA.
          Captura frames con la cámara OV2640, los publica vía MQTT
          al servidor Python (base64 JPEG), y recibe comandos para
          controlar el buzzer según los resultados de la detección.

INTEGRANTES:
Escobedo Ojeda Luis David
Plascencia Rodríguez Diana Carolina
Quintero Frausto Valeria Melissa
Rodríguez López Maria Aurora

PROYECTO: Sistema de Detección de Objetos con ESP32-CAM e IA
"""

# ============================================================
# IMPORTACIONES
# ============================================================
import camera
import network
import ujson as json
import ubinascii
import time
import machine
from umqtt.simple import MQTTClient

# ============================================================
# CONFIGURACIÓN — EDITAR ANTES DE SUBIR A LA ESP32
# ============================================================
WIFI_SSID      = "Alumnos-TecNM-D-UF"        
WIFI_PASSWORD  = ""        

MQTT_BROKER    = "broker.emqx.io"       # Broker público EMQX (gratuito)
MQTT_PORT      = 1883
MQTT_CLIENT_ID = "esp32wrover_cam_{}".format(machine.unique_id().hex()[-4:])

# Topics (deben coincidir exactamente con servidor_ia.py)
TOPIC_IMAGEN     = b"esp32cam/imagen"
TOPIC_TELEMETRIA = b"esp32cam/telemetria"
TOPIC_COMANDO    = b"esp32cam/comando"
TOPIC_STATUS     = b"esp32cam/status"

# ============================================================
# CONFIGURACIÓN DEL BUZZER
# ============================================================
PIN_BUZZER = 14        # GPIO14 → Buzzer (activo 3.3V directo, o pasivo con transistor)
buzzer = machine.Pin(PIN_BUZZER, machine.Pin.OUT)
buzzer.value(0)        # Asegurar apagado al inicio

# ============================================================
# PATRONES DE BUZZER
# Cada patrón es una lista de tuplas (estado, ms):
#   (1, 300) = encender 300ms | (0, 200) = apagar 200ms
# ============================================================
PATRONES_BUZZER = {
    "LARGO" : [(1, 800), (0, 200)],               # Persona detectada
    "CORTO" : [(1, 150), (0, 100), (1, 150), (0, 100)],  # Otro objeto
    "ERROR" : [(1, 80), (0, 80), (1, 80), (0, 80), (1, 80), (0, 300)],
    "NADA"  : [],                                  # Sin sonido
}

def reproducir_patron(nombre_patron: str):
    """Ejecuta el patrón de buzzer indicado (bloqueante, duración corta)."""
    patron = PATRONES_BUZZER.get(nombre_patron, [])
    for estado, ms in patron:
        buzzer.value(estado)
        time.sleep_ms(ms)
    buzzer.value(0)    # Siempre apagar al terminar


# ============================================================
# CONEXIÓN Wi-Fi
# ============================================================
def conectar_wifi() -> str:
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if not wlan.isconnected():
        print("Conectando a Wi-Fi:", WIFI_SSID)
        wlan.connect(WIFI_SSID, WIFI_PASSWORD)
        timeout = 0
        while not wlan.isconnected():
            time.sleep(1)
            print(".", end="")
            timeout += 1
            if timeout > 25:
                print("\nTimeout Wi-Fi. Reiniciando...")
                machine.reset()
    print("\nWi-Fi OK — IP:", wlan.ifconfig()[0])
    return wlan.ifconfig()[0]


# ============================================================
# INICIALIZACIÓN DE CÁMARA
# Pines estándar para ESP32-WROVER-DEV con módulo OV2640
# ============================================================
def inicializar_camara() -> bool:
    try:
        camera.init(
            1,
            d0=4,  d1=5,  d2=18, d3=19,
            d4=36, d5=39, d6=34, d7=35,
            format     = camera.JPEG,
            framesize  = camera.FRAME_QVGA,   # 240x240: balance latencia/calidad
            xclk_freq  = camera.XCLK_20MHz,
            href=23,   vsync=25,
            reset=-1,  pwdn=-1,
            sioc=27,   siod=26,
            xclk=0,    pclk=22
        )
        camera.quality(20)      # 10=max calidad | 63=min (menor tamaño = menos latencia)
        camera.brightness(1)    # +1 brillo para detección con poca luz
        camera.contrast(1)
        print("Cámara inicializada (240x240 JPEG, quality=12).")
        return True
    except Exception as e:
        print("Error al inicializar cámara:", e)
        return False


# ============================================================
# CALLBACK MQTT — RECIBE COMANDOS DEL SERVIDOR IA
# ============================================================
def on_message(topic, msg):
    """Procesa comandos JSON enviados por el servidor Python."""
    try:
        if topic == TOPIC_COMANDO:
            data    = json.loads(msg.decode("utf-8"))
            cmd     = data.get("cmd",    "LIBRE")
            patron  = data.get("patron", "NADA")
            clases  = data.get("clases", [])
            num     = data.get("num_objetos", 0)

            print("CMD recibido: {} | Objetos: {} | Clases: {}".format(cmd, num, clases))

            # Ejecutar patrón de buzzer según comando
            reproducir_patron(patron)

        elif topic == TOPIC_STATUS:
            data = json.loads(msg.decode("utf-8"))
            print("Status servidor:", data.get("estado", "?"),
                  "| Modelo:", data.get("modelo", "?"))

    except Exception as e:
        print("Error en on_message:", e)


# ============================================================
# CAPTURA Y PUBLICACIÓN DE IMAGEN
# ============================================================
def capturar_y_publicar(client) -> bool:
    """
    Toma una foto, la codifica en base64 y la publica en MQTT.
    El servidor Python la recibe, aplica IA y devuelve un comando.
    """
    try:
        foto = camera.capture()
        if not foto:
            print("capture() retornó None")
            return False

        # Convertir bytes → base64 UTF-8
        b64 = ubinascii.b2a_base64(foto).decode("utf-8").strip()

        # Publicar como JSON con metadatos mínimos
        payload = json.dumps({
            "img" : b64,
            "ts"  : time.time(),
            "id"  : MQTT_CLIENT_ID
        })

        client.publish(TOPIC_IMAGEN, payload)
        print("Imagen enviada: {} bytes JPEG → {} bytes payload".format(
              len(foto), len(payload)))
        return True

    except Exception as e:
        print("Error capturar_y_publicar:", e)
        return False


# ============================================================
# PUBLICACIÓN DE TELEMETRÍA
# ============================================================
def publicar_telemetria(client):
    """Envía datos de estado del dispositivo al servidor."""
    try:
        data = {
            "dispositivo" : MQTT_CLIENT_ID,
            "heap_libre"  : machine.mem_free(),
            "ts"          : time.time()
        }
        client.publish(TOPIC_TELEMETRIA, json.dumps(data))
    except Exception as e:
        print("Error telemetría:", e)


# ============================================================
# PROGRAMA PRINCIPAL
# ============================================================
def main():
    print("="*50)
    print("  ESP32-WROVER-DEV — Captura + Buzzer")
    print("  Broker: {}".format(MQTT_BROKER))
    print("="*50)

    # 1. Wi-Fi
    conectar_wifi()

    # 2. Cámara
    if not inicializar_camara():
        print("Fallo crítico en cámara. Reiniciando en 5s...")
        time.sleep(5)
        machine.reset()

    # 3. MQTT
    print("Conectando MQTT a {}:{}".format(MQTT_BROKER, MQTT_PORT))
    client = MQTTClient(
        client_id = MQTT_CLIENT_ID,
        server    = MQTT_BROKER,
        port      = MQTT_PORT,
        keepalive = 60
    )
    client.set_callback(on_message)

    try:
        client.connect()
        print("MQTT conectado. ID:", MQTT_CLIENT_ID)
    except Exception as e:
        print("Error conectando MQTT:", e)
        time.sleep(5)
        machine.reset()

    # Suscribirse a comandos del servidor IA
    client.subscribe(TOPIC_COMANDO)
    client.subscribe(TOPIC_STATUS)

    # Beep de inicio: sistema listo
    reproducir_patron("CORTO")
    print("Sistema listo. Iniciando captura...")

    # ---- LOOP PRINCIPAL ----
    INTERVALO_IMAGEN     = 1200   # ms entre capturas (aprox. 0.8 fps — estable para MQTT)
    INTERVALO_TELEMETRIA = 15000  # ms entre telemetrías
    ultimo_imagen     = 0
    ultimo_telemetria = 0
    errores_consecutivos = 0

    while True:
        ahora = time.ticks_ms()

        # Revisar mensajes entrantes (comandos del servidor IA)
        try:
            client.check_msg()
            errores_consecutivos = 0
        except Exception as e:
            print("Error check_msg:", e)
            errores_consecutivos += 1

        # Capturar y enviar imagen al servidor IA
        if time.ticks_diff(ahora, ultimo_imagen) >= INTERVALO_IMAGEN:
            capturar_y_publicar(client)
            ultimo_imagen = ahora

        # Publicar telemetría periódica
        if time.ticks_diff(ahora, ultimo_telemetria) >= INTERVALO_TELEMETRIA:
            publicar_telemetria(client)
            ultimo_telemetria = ahora

        # Reconectar automáticamente si hay errores acumulados
        if errores_consecutivos >= 5:
            print("Múltiples errores MQTT. Reconectando...")
            errores_consecutivos = 0
            try:
                client.disconnect()
            except:
                pass
            time.sleep(2)
            try:
                client.connect()
                client.subscribe(TOPIC_COMANDO)
                client.subscribe(TOPIC_STATUS)
                print("Reconexión exitosa.")
            except Exception as e:
                print("Error en reconexión:", e)
                time.sleep(5)
                machine.reset()

        time.sleep_ms(50)   # Pausa mínima — evita WDT reset


# ============================================================
# ARRANQUE SEGURO
# ============================================================
if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("Error fatal en main():", e)
        time.sleep(3)
        machine.reset()
