# =============================================================================
# PROYECTO: NaviChair — Sistema Inteligente de Asistencia y Monitoreo
#            para Silla de Ruedas Manual
#
# INTEGRANTES:
#   - Diana Carolina Plascencia Rodríguez
#   - María Aurora Rodríguez López
#   - Escobedo Ojeda Luis David
#   - Quintero Frausto Valeria Melissa Leilani
#
# DESCRIPCIÓN:
#   Programa principal que orquesta la lógica de decisión del sistema
#   NaviChair. Lee el estado de todos los sensores a través de la
#   biblioteca HAL (dispositivos.py) y activa los actuadores adecuados
#   sin interactuar directamente con el hardware. Además publica eventos
#   de alerta vía MQTT para notificar al cuidador en tiempo real.
#
# ARCHIVO: main.py
# =============================================================================

from dispositivos import CajaDeGestion, CajaDeControl
import time

# -----------------------------------------------------------------------
# IMPORTACIONES MQTT
# Para usar MQTT en MicroPython se requiere la librería umqtt.simple
# que normalmente ya viene incluida en los firmwares ESP32 estándar.
# Si no está disponible, instálala con:
#   import upip; upip.install('micropython-umqtt.simple')
# -----------------------------------------------------------------------
from umqtt.simple import MQTTClient

# -----------------------------------------------------------------------
# CONFIGURACIÓN MQTT
# Cambia estos valores según tu broker y red WiFi
# -----------------------------------------------------------------------
BROKER_MQTT        = "172.20.10.3"   # IP de tu broker (ej. Mosquitto local)
PUERTO_MQTT        = 1883
ID_CLIENTE_MQTT    = "navichair_esp32"
TOPICO_OBSTACULOS  = "navichair/obstaculos"
TOPICO_INCLINACION = "navichair/inclinacion"
TOPICO_INMOVILIDAD = "navichair/inmovilidad"
TOPICO_ESTADO      = "navichair/estado"

# -----------------------------------------------------------------------
# CONFIGURACIÓN DE RED WiFi
# -----------------------------------------------------------------------
SSID_WIFI     = "Iphone David"
CLAVE_WIFI    = "huevitos"


def conectar_wifi():
    """
    Parámetros : Ninguno
    Descripción: Conecta el ESP32 a la red WiFi configurada. Espera hasta
                 establecer la conexión antes de continuar.
    Retorna    : None
    """
    import network
    estacion = network.WLAN(network.STA_IF)
    estacion.active(True)
    if not estacion.isconnected():
        print("Conectando a WiFi...")
        estacion.connect(SSID_WIFI, CLAVE_WIFI)
        while not estacion.isconnected():
            time.sleep(0.5)
    print("WiFi conectado:", estacion.ifconfig())


def conectar_mqtt():
    """
    Parámetros : Ninguno
    Descripción: Crea y conecta el cliente MQTT al broker configurado.
    Retorna    : Instancia de MQTTClient ya conectada.
    """
    cliente = MQTTClient(ID_CLIENTE_MQTT, BROKER_MQTT, port=PUERTO_MQTT)
    cliente.connect()
    print("MQTT conectado a", BROKER_MQTT)
    return cliente


def publicar_alerta(cliente_mqtt, topico, mensaje):
    """
    Parámetros : cliente_mqtt (MQTTClient) — cliente MQTT conectado
                 topico (str)              — tópico de publicación
                 mensaje (str)             — contenido del mensaje
    Descripción: Publica un mensaje en el tópico indicado. Si la
                 conexión falla, imprime el error sin detener el sistema.
    Retorna    : None
    """
    try:
        cliente_mqtt.publish(topico, mensaje)
        print("MQTT [{}] → {}".format(topico, mensaje))
    except Exception as error:
        print("Error MQTT:", error)


# -----------------------------------------------------------------------
# PROGRAMA PRINCIPAL
# -----------------------------------------------------------------------

# Inicializar WiFi y MQTT
conectar_wifi()
cliente_mqtt = conectar_mqtt()

# Inicializar la biblioteca HAL
sensores   = CajaDeGestion()
actuadores = CajaDeControl()

print("NaviChair iniciado correctamente...")
actuadores.mostrar_alerta("NaviChair", "Iniciando...")
time.sleep(2)

# Ciclo principal
while True:
    try:
        # ----------------------------------------------------------
        # 1. Obtener resumen completo de todos los sensores
        # ----------------------------------------------------------
        datos = sensores.obtener_resumen_sensores()

        distancia_izq  = datos["dist_izq"]
        distancia_cen  = datos["dist_cen"]
        distancia_der  = datos["dist_der"]
        inclinacion    = datos["inclinacion"]
        min_inmovil    = datos["min_inmovil"]

        # ----------------------------------------------------------
        # 2. Mostrar distancias en la pantalla de forma continua
        # ----------------------------------------------------------
        actuadores.mostrar_distancias(distancia_izq, distancia_cen, distancia_der)

        # ----------------------------------------------------------
        # 3. Lógica de obstáculos (umbral: 50 cm)
        # ----------------------------------------------------------
        if distancia_cen < CajaDeControl.UMBRAL_OBSTACULO_CM:
            actuadores.alerta_obstaculo_frente()
            actuadores.mostrar_alerta("OBSTACULO FRENTE",
                                      "{:.0f}cm".format(distancia_cen))
            publicar_alerta(cliente_mqtt, TOPICO_OBSTACULOS,
                            "FRENTE:{:.0f}cm".format(distancia_cen))

        elif distancia_izq < CajaDeControl.UMBRAL_OBSTACULO_CM:
            actuadores.alerta_obstaculo_izquierda()
            actuadores.mostrar_alerta("OBSTACULO IZQ",
                                      "{:.0f}cm".format(distancia_izq))
            publicar_alerta(cliente_mqtt, TOPICO_OBSTACULOS,
                            "IZQUIERDA:{:.0f}cm".format(distancia_izq))

        elif distancia_der < CajaDeControl.UMBRAL_OBSTACULO_CM:
            actuadores.alerta_obstaculo_derecha()
            actuadores.mostrar_alerta("OBSTACULO DER",
                                      "{:.0f}cm".format(distancia_der))
            publicar_alerta(cliente_mqtt, TOPICO_OBSTACULOS,
                            "DERECHA:{:.0f}cm".format(distancia_der))

        # ----------------------------------------------------------
        # 4. Lógica de inclinación peligrosa (umbral: 30°)
        # ----------------------------------------------------------
        if inclinacion > CajaDeControl.UMBRAL_INCLINACION_GRADOS:
            actuadores.activar_alerta_fisica()
            actuadores.alerta_inclinacion_critica()
            actuadores.mostrar_alerta("INCLINACION",
                                      "PELIGROSA {:.1f}g".format(inclinacion))
            publicar_alerta(cliente_mqtt, TOPICO_INCLINACION,
                            "PELIGROSA:{:.1f}grados".format(inclinacion))
        else:
            actuadores.desactivar_alerta_fisica()

        # ----------------------------------------------------------
        # 5. Lógica de inmovilidad prolongada (umbral: 10 minutos)
        # ----------------------------------------------------------
        if min_inmovil > CajaDeControl.UMBRAL_INMOVILIDAD_MIN:
            actuadores.alerta_inmovilidad()
            actuadores.mostrar_alerta("INMOVILIDAD",
                                      "{:.0f}min sin mov".format(min_inmovil))
            publicar_alerta(cliente_mqtt, TOPICO_INMOVILIDAD,
                            "INMOVILIDAD:{:.1f}min".format(min_inmovil))

        # ----------------------------------------------------------
        # 6. Publicar estado general periódicamente
        # ----------------------------------------------------------
        estado_json = (
            '{{"izq":{:.0f},"cen":{:.0f},"der":{:.0f},'
            '"incl":{:.1f},"inmov":{:.1f}}}'
        ).format(distancia_izq, distancia_cen, distancia_der,
                 inclinacion, min_inmovil)
        publicar_alerta(cliente_mqtt, TOPICO_ESTADO, estado_json)

        time.sleep(1)  # Ciclo cada 1 segundo

    except KeyboardInterrupt:
        # Interrupción manual: forzar estado seguro antes de salir
        print("Interrupción detectada. Activando estado seguro...")
        actuadores.estado_seguro()
        cliente_mqtt.disconnect()
        break

    except Exception as error_general:
        # Error inesperado: mostrar en pantalla y continuar
        print("Error en ciclo principal:", error_general)
        actuadores.mostrar_alerta("ERROR", str(error_general)[:16])
        time.sleep(2)

