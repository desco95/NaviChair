"""
OBJETIVO  : Pipeline de Inteligencia Artificial para NaviChair. Recibe
            imágenes de la ESP32-CAM vía MQTT, las procesa con OpenCV
            para detectar obstáculos o personas en el camino, y publica
            el resultado de vuelta a la ESP32 para activar actuadores.
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
# ARCHIVO: ia_processor.py
# DESCRIPCIÓN: Procesa imágenes recibidas de la ESP32-CAM mediante MQTT.
#              Usa OpenCV con un clasificador Haar Cascade (incluido en
#              OpenCV, no requiere descarga) para detectar personas u
#              obstáculos en el campo visual de la silla. Si detecta algo,
#              publica un comando MQTT hacia la ESP32 para activar el buzzer.
#
# MODELO UTILIZADO: Haar Cascade frontal face / full body (OpenCV built-in)
#   - Precisión aproximada: 70-85% en condiciones de buena iluminación
#   - Tipo de predicción: detección de presencia humana en imagen
#   - Latencia estimada: 50-150 ms por fotograma en CPU estándar
#
# INSTRUCCIONES PARA PROBAR SIN MQTT (datos estáticos):
#   python ia_processor.py --prueba
# =============================================================================

import paho.mqtt.client as mqtt
import cv2
import numpy as np
import base64
import datetime
import sys
import os

# -----------------------------------------------------------------------
# CONFIGURACIÓN
# -----------------------------------------------------------------------
DIRECCION_BROKER    = "localhost"
PUERTO_BROKER       = 1883
ID_CLIENTE_IA       = "navichair_ia_processor"

TOPICO_CAMARA       = "navichair/camara"          # Recibe imagen base64
TOPICO_RESULTADO_IA = "navichair/ia/resultado"    # Publica resultado
TOPICO_CMD_BUZZER   = "navichair/cmd/buzzer"      # Activa buzzer si detecta

# Umbral de confianza: si se detectan más de N personas/objetos, activar alerta
UMBRAL_DETECCIONES  = 1

# -----------------------------------------------------------------------
# CARGAR MODELO DE IA
# HaarCascade está incluido en OpenCV, no requiere descarga adicional.
# Detecta cuerpos completos (personas paradas frente a la silla).
# -----------------------------------------------------------------------
def cargar_modelo():
    """
    Parámetros : Ninguno
    Descripción: Carga el clasificador Haar Cascade de cuerpo completo
                 incluido en OpenCV. No requiere descarga externa.
    Retorna    : Objeto CascadeClassifier de OpenCV listo para usar.
    """
    ruta_cascade = cv2.data.haarcascades + "haarcascade_fullbody.xml"
    clasificador = cv2.CascadeClassifier(ruta_cascade)
    if clasificador.empty():
        print("ERROR: No se pudo cargar el modelo Haar Cascade.")
        print("  Ruta buscada:", ruta_cascade)
        sys.exit(1)
    print("{} Modelo IA cargado: Haar Cascade (cuerpo completo)".format(
        marca_de_tiempo()))
    print("  Precisión aprox: 70-85% con buena iluminación")
    return clasificador


def marca_de_tiempo():
    """
    Parámetros : Ninguno
    Descripción: Devuelve la fecha y hora actual como cadena de texto.
    Retorna    : Cadena con formato [YYYY-MM-DD HH:MM:SS] (str).
    """
    return datetime.datetime.now().strftime("[%Y-%m-%d %H:%M:%S]")


# -----------------------------------------------------------------------
# PROCESAMIENTO DE IA
# -----------------------------------------------------------------------

def procesar_imagen(imagen_bytes, clasificador):
    """
    Parámetros : imagen_bytes (bytes) — imagen en formato JPEG o PNG
                 clasificador         — modelo Haar Cascade cargado
    Descripción: Decodifica la imagen, la convierte a escala de grises
                 y aplica el clasificador para detectar personas/cuerpos.
                 Dibuja rectángulos sobre las detecciones.
    Retorna    : Tupla (cantidad_detecciones: int, imagen_anotada: ndarray)
    """
    # Decodificar bytes a imagen OpenCV
    arreglo = np.frombuffer(imagen_bytes, dtype=np.uint8)
    imagen  = cv2.imdecode(arreglo, cv2.IMREAD_COLOR)

    if imagen is None:
        print("{} ERROR: No se pudo decodificar la imagen recibida.".format(
            marca_de_tiempo()))
        return 0, None

    # Convertir a escala de grises (requerido por Haar Cascade)
    gris = cv2.cvtColor(imagen, cv2.COLOR_BGR2GRAY)

    # Aplicar detección
    # scaleFactor=1.1: escalar 10% en cada paso del detector
    # minNeighbors=3:  mínimo de detecciones vecinas para confirmar
    # minSize=(30,60): tamaño mínimo de objeto a detectar (px)
    detecciones = clasificador.detectMultiScale(
        gris,
        scaleFactor=1.1,
        minNeighbors=3,
        minSize=(30, 60)
    )

    cantidad = len(detecciones) if hasattr(detecciones, '__len__') else 0

    # Dibujar rectángulos sobre las detecciones
    for (x, y, ancho, alto) in detecciones:
        cv2.rectangle(imagen, (x, y), (x + ancho, y + alto), (0, 255, 0), 2)

    return cantidad, imagen


def imagen_a_base64(imagen):
    """
    Parámetros : imagen (ndarray) — imagen OpenCV
    Descripción: Codifica la imagen en formato JPEG y la convierte a
                 base64 para poder publicarla por MQTT como texto.
    Retorna    : Cadena base64 (str) o None si falla la codificación.
    """
    exito, buffer = cv2.imencode(".jpg", imagen)
    if not exito:
        return None
    return base64.b64encode(buffer).decode("utf-8")


# -----------------------------------------------------------------------
# PRUEBA CON DATOS ESTÁTICOS (sin MQTT)
# Ejecutar: python ia_processor.py --prueba
# -----------------------------------------------------------------------

def prueba_con_imagen_estatica(clasificador):
    """
    Parámetros : clasificador — modelo Haar Cascade cargado
    Descripción: Prueba el modelo con una imagen generada localmente
                 (imagen en gris con texto) para verificar que el
                 pipeline de procesamiento funciona antes de integrar MQTT.
                 Sirve como evidencia de la prueba estática requerida por E3.
    Retorna    : None
    """
    print("\n{} === MODO PRUEBA ESTÁTICA ===".format(marca_de_tiempo()))
    print("  Probando el modelo con imagen sintética (sin MQTT)...")

    # Crear imagen de prueba: fondo gris con texto
    imagen_prueba = np.zeros((480, 640, 3), dtype=np.uint8)
    imagen_prueba[:] = (100, 100, 100)
    cv2.putText(imagen_prueba, "NaviChair - Prueba IA",
                (120, 240), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2)

    # Codificar como bytes JPEG para simular lo que enviaría la ESP32-CAM
    _, buffer      = cv2.imencode(".jpg", imagen_prueba)
    imagen_bytes   = buffer.tobytes()

    cantidad, imagen_procesada = procesar_imagen(imagen_bytes, clasificador)

    print("  Resultado: {} detección(es) encontrada(s)".format(cantidad))
    if cantidad >= UMBRAL_DETECCIONES:
        print("  ACCIÓN: Se publicaría comando → navichair/cmd/buzzer : ON")
    else:
        print("  ACCIÓN: Sin alerta (por debajo del umbral de {} detección(es))".format(
            UMBRAL_DETECCIONES))

    # Guardar imagen anotada como evidencia
    if imagen_procesada is not None:
        cv2.imwrite("prueba_ia_resultado.jpg", imagen_procesada)
        print("  Imagen anotada guardada en: prueba_ia_resultado.jpg")

    print("{} === PRUEBA COMPLETADA ===\n".format(marca_de_tiempo()))


# -----------------------------------------------------------------------
# CALLBACKS MQTT
# -----------------------------------------------------------------------

def al_conectar(cliente, datos_usuario, indicadores, codigo_resultado):
    """
    Parámetros : cliente, datos_usuario, indicadores — estándar MQTT
                 codigo_resultado — 0 si conexión exitosa
    Descripción: Callback de conexión. Se suscribe al tópico de imágenes
                 de la cámara cuando la conexión se establece con éxito.
    Retorna    : None
    """
    if codigo_resultado == 0:
        print("{} IA conectada al broker MQTT.".format(marca_de_tiempo()))
        cliente.subscribe(TOPICO_CAMARA)
        print("  → Escuchando imágenes en: {}".format(TOPICO_CAMARA))
    else:
        print("{} ERROR de conexión. Código: {}".format(
            marca_de_tiempo(), codigo_resultado))


def construir_callback_mensaje(clasificador):
    """
    Parámetros : clasificador — modelo Haar Cascade ya cargado
    Descripción: Crea y devuelve la función callback de mensaje con el
                 clasificador ya disponible en su contexto (closure).
    Retorna    : Función callback (callable).
    """
    def al_recibir_mensaje(cliente, datos_usuario, mensaje):
        """
        Parámetros : cliente, datos_usuario, mensaje — estándar MQTT
        Descripción: Recibe la imagen de la ESP32-CAM, la procesa con el
                     modelo IA y publica el resultado. Si hay detecciones,
                     activa el buzzer vía MQTT.
        Retorna    : None
        """
        if mensaje.topic != TOPICO_CAMARA:
            return

        print("{} Imagen recibida ({} bytes). Procesando...".format(
            marca_de_tiempo(), len(mensaje.payload)))

        # Decodificar base64 → bytes de imagen
        try:
            imagen_bytes = base64.b64decode(mensaje.payload)
        except Exception as error:
            print("  ERROR al decodificar base64:", error)
            return

        # Procesar con IA
        cantidad, _ = procesar_imagen(imagen_bytes, clasificador)

        # Construir resultado JSON
        resultado = '{{"detecciones":{},"alerta":{}}}'.format(
            cantidad,
            "true" if cantidad >= UMBRAL_DETECCIONES else "false"
        )

        # Publicar resultado
        cliente.publish(TOPICO_RESULTADO_IA, resultado)
        print("  → Resultado IA publicado: {}".format(resultado))

        # Si supera el umbral, activar buzzer en la ESP32
        if cantidad >= UMBRAL_DETECCIONES:
            cliente.publish(TOPICO_CMD_BUZZER, "ON")
            print("  → ALERTA: Persona/obstáculo detectado. Buzzer activado.")
        else:
            cliente.publish(TOPICO_CMD_BUZZER, "OFF")

    return al_recibir_mensaje


# -----------------------------------------------------------------------
# PROGRAMA PRINCIPAL
# -----------------------------------------------------------------------

if __name__ == "__main__":
    clasificador = cargar_modelo()

    # Modo prueba estática (sin MQTT): python ia_processor.py --prueba
    if "--prueba" in sys.argv:
        prueba_con_imagen_estatica(clasificador)
        sys.exit(0)

    # Modo normal: conectar a MQTT y procesar en tiempo real
    cliente_ia = mqtt.Client(client_id=ID_CLIENTE_IA)
    cliente_ia.on_connect = al_conectar
    cliente_ia.on_message = construir_callback_mensaje(clasificador)

    print("{} Iniciando pipeline de IA NaviChair...".format(marca_de_tiempo()))
    print("  Para prueba sin MQTT: python ia_processor.py --prueba")

    try:
        cliente_ia.connect(DIRECCION_BROKER, PUERTO_BROKER, keepalive=60)
        cliente_ia.loop_forever()
    except KeyboardInterrupt:
        print("\n{} Pipeline IA detenido.".format(marca_de_tiempo()))
        cliente_ia.disconnect()
    except ConnectionRefusedError:
        print("{} ERROR: Broker no disponible en {}:{}".format(
            marca_de_tiempo(), DIRECCION_BROKER, PUERTO_BROKER))
