"""
OBJETIVO  : Pipeline de Inteligencia Artificial para NaviChair. Recibe
            imágenes de la ESP32-CAM vía MQTT, las procesa con OpenCV
            para detectar rostros en el camino, y publica
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
#              OpenCV, no requiere descarga) para detectar rostros humanos
#              en el campo visual de la silla. Si detecta algo,
#              publica un comando MQTT hacia la ESP32 para activar el buzzer.
#
# MODELO UTILIZADO: Haar Cascade Frontal Face
#   - Precisión aproximada: 80-90% en condiciones de buena iluminación
#   - Tipo de predicción: Detecta rostros humanos en tiempo real.
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
# COMPATIBILIDAD PAHO-MQTT 1.x y 2.x
# paho-mqtt >= 2.0 requiere especificar CallbackAPIVersion en el constructor.
# Se usa importlib.metadata para leer la versión instalada de forma segura,
# ya que paho.mqtt.client no expone __version__ en todas las versiones.
# -----------------------------------------------------------------------
try:
    from importlib.metadata import version as _pkg_version
    _PAHO_VERSION = tuple(int(x) for x in _pkg_version("paho-mqtt").split(".")[:2])
except Exception:
    # Fallback: si no se puede leer la versión, asumir 1.x (comportamiento seguro)
    _PAHO_VERSION = (1, 0)
_PAHO_V2 = _PAHO_VERSION >= (2, 0)

# -----------------------------------------------------------------------
# CONFIGURACIÓN
# -----------------------------------------------------------------------
DIRECCION_BROKER    = "172.20.10.3"
PUERTO_BROKER       = 1883
ID_CLIENTE_IA       = "navichair_ia_processor"

TOPICO_CAMARA       = "navichair/camara"          # Recibe imagen base64
TOPICO_RESULTADO_IA = "navichair/ia/resultado"    # Publica resultado
TOPICO_CMD_BUZZER   = "navichair/cmd/buzzer"      # Activa buzzer si detecta

# Umbral de confianza: si se detectan más de N rostros, activar alerta
UMBRAL_DETECCIONES  = 1

# -----------------------------------------------------------------------
# CARGAR MODELO DE IA
# HaarCascade está incluido en OpenCV, no requiere descarga adicional.
# Detecta rostros de frente (personas mirando hacia la silla).
# -----------------------------------------------------------------------
def cargar_modelo():
    """
    Parámetros : Ninguno
    Descripción: Carga el clasificador Haar Cascade de rostro frontal
                 incluido en OpenCV. No requiere descarga externa.
    Retorna    : Objeto CascadeClassifier de OpenCV listo para usar.
    """
    ruta_cascade = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    clasificador = cv2.CascadeClassifier(ruta_cascade)
    if clasificador.empty():
        print("ERROR: No se pudo cargar el modelo Haar Cascade.")
        print("  Ruta buscada:", ruta_cascade)
        sys.exit(1)
    print("{} Modelo IA cargado: Haar Cascade (rostro/cara)".format(
        marca_de_tiempo()))
    print("  Precisión aprox: 80-90% con buena iluminación")
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
                 y aplica el clasificador para detectar rostros/caras.
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
    # minNeighbors=5: aumentado ligeramente para reducir falsos positivos en rostros
    # minSize=(30,30): tamaño mínimo de la cara a detectar (px)
    detecciones = clasificador.detectMultiScale(
        gris,
        scaleFactor=1.1,
        minNeighbors=5,
        minSize=(30, 30)
    )

    # CORRECCIÓN: detectMultiScale puede retornar tupla vacía () en lugar
    # de lista cuando no hay detecciones. Se normaliza con len() de forma segura.
    cantidad = len(detecciones) if len(detecciones) > 0 else 0

    # Dibujar rectángulos sobre las detecciones (rostros)
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
    cv2.putText(imagen_prueba, "NaviChair - Prueba Rostros",
                (120, 240), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2)

    # Codificar como bytes JPEG para simular lo que enviaría la ESP32-CAM
    _, buffer      = cv2.imencode(".jpg", imagen_prueba)
    imagen_bytes   = buffer.tobytes()

    cantidad, imagen_procesada = procesar_imagen(imagen_bytes, clasificador)

    print("  Resultado: {} rostro(s) encontrado(s)".format(cantidad))
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


def modo_webcam(clasificador):
    """
    Parámetros : clasificador — modelo Haar Cascade cargado
    Descripción: Activa la cámara local (índice 0) y aplica detección
                 de caras en tiempo real cuadro a cuadro. Muestra ventana con las
                 detecciones anotadas. Presionar 'q' para salir.
    Retorna    : None
    """
    print("\n{} === MODO WEBCAM LOCAL ===".format(marca_de_tiempo()))

    cap = cv2.VideoCapture(0)

    # CORRECCIÓN: verificar que la cámara se abrió correctamente
    if not cap.isOpened():
        print("{} ERROR: No se pudo abrir la cámara (índice 0).".format(
            marca_de_tiempo()))
        print("  Verifica que la cámara esté conectada y no esté en uso.")
        return

    print("  Cámara abierta. Presiona 'q' para salir.")

    while True:
        ret, frame = cap.read()
        if not ret:
            print("{} ADVERTENCIA: No se pudo leer fotograma. Deteniendo.".format(
                marca_de_tiempo()))
            break

        gris = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        # Ajustado el minSize a (30, 30) óptimo para rostros
        detecciones = clasificador.detectMultiScale(
            gris,
            scaleFactor=1.1,
            minNeighbors=5,
            minSize=(30, 30)
        )

        for (x, y, w, h) in detecciones:
            cv2.rectangle(frame, (x, y), (x+w, y+h), (0, 255, 0), 2)

        cantidad = len(detecciones)

        if cantidad >= UMBRAL_DETECCIONES:
            print("{} ALERTA: Cara detectada → MQTT ON".format(marca_de_tiempo()))

        cv2.imshow("IA NaviChair - Rostros", frame)

        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    cap.release()
    cv2.destroyAllWindows()


# -----------------------------------------------------------------------
# CALLBACKS MQTT
# -----------------------------------------------------------------------

def al_conectar(cliente, datos_usuario, indicadores, codigo_resultado, propiedades=None):
    """
    Parámetros : cliente, datos_usuario, indicadores — estándar MQTT
                 codigo_resultado — 0 si conexión exitosa
                 propiedades      — parámetro adicional requerido en paho-mqtt 2.x
    Descripción: Callback de conexión. Se suscribe al tópico de imágenes
                 de la cámara cuando la conexión se establece con éxito.
                 La firma acepta el parámetro 'propiedades' para compatibilidad
                 con paho-mqtt >= 2.0 sin romper la versión 1.x.
    Retorna    : None
    """
    # En paho-mqtt 2.x, codigo_resultado es un objeto ReasonCode, no un int.
    # Se convierte a int para la comparación de forma segura.
    codigo = int(codigo_resultado) if hasattr(codigo_resultado, 'value') else codigo_resultado

    if codigo == 0:
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
            print("  → ALERTA: Cara/Rostro detectado. Buzzer activado.")
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

    if "--webcam" in sys.argv:
        modo_webcam(clasificador)
        sys.exit(0)

    # Modo normal: conectar a MQTT y procesar en tiempo real
    # CORRECCIÓN: compatibilidad con paho-mqtt 1.x y 2.x
    # paho-mqtt >= 2.0 requiere CallbackAPIVersion en el constructor.
    if _PAHO_V2:
        cliente_ia = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION1,
            client_id=ID_CLIENTE_IA
        )
    else:
        cliente_ia = mqtt.Client(client_id=ID_CLIENTE_IA)

    cliente_ia.on_connect = al_conectar
    cliente_ia.on_message = construir_callback_mensaje(clasificador)

    print("{} Iniciando pipeline de IA NaviChair (Enfoque: Rostros)...".format(marca_de_tiempo()))
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
