"""
OBJETIVO: Integración de IA para Detección de Objetos y Personas en Tiempo Real.
          El servidor captura video en vivo desde un celular con IP Webcam,
          aplica detección de objetos con MobileNet SSD (OpenCV DNN) o Haar
          Cascade, identifica si hay personas u objetos de interés, y publica
          comandos vía MQTT al buzzer conectado a la ESP32.

INTEGRANTES:
Escobedo Ojeda Luis David
Plascencia Rodríguez Diana Carolina
Quintero Frausto Valeria Melissa
Rodríguez López Maria Aurora


PROYECTO: Sistema de Detección de Objetos con ESP32-CAM e IA

MODELO:
    - Algoritmo   : Haar Cascade (detección de rostros/personas, OpenCV)
                    MobileNet SSD v2 opcional (si se tienen los pesos .pb)
    - Framework   : OpenCV DNN / cv2.CascadeClassifier
    - Tipo        : Detección de objetos/personas con bounding boxes
    - Precisión   : Haar ~85-90% frontal | MobileNet mAP~22 COCO
    - Latencia    : ~30-80 ms por frame en CPU
    - Fuente video: IP Webcam (app Android) vía stream MJPEG HTTP
"""

# ============================================================
# IMPORTACIONES
# ============================================================
import paho.mqtt.client as mqtt
import cv2
import numpy as np
import base64
import json
import time
import logging
import os
import urllib.request
from datetime import datetime

# ============================================================
# CONFIGURACIÓN GENERAL
# ============================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("servidor_ia.log", encoding="utf-8")
    ]
)
log = logging.getLogger(__name__)

# --- Broker MQTT ---
MQTT_BROKER    = "broker.emqx.io"   # Broker público gratuito, sin autenticación
MQTT_PORT      = 1883
MQTT_KEEPALIVE = 60
MQTT_CLIENT_ID = "servidor_ia_deteccion_objetos"

# --- Topics MQTT (deben coincidir con main.py de la ESP32) ---
TOPIC_IMAGEN     = "esp32cam/imagen"       # (reservado, no se usa con IP Webcam)
TOPIC_TELEMETRIA = "esp32cam/telemetria"   # ESP32 → Servidor (JSON sensores)
TOPIC_COMANDO    = "esp32cam/comando"      # Servidor → ESP32 (JSON acción)
TOPIC_CMD        = TOPIC_COMANDO           # Alias corto para el loop de video
TOPIC_STATUS     = "esp32cam/status"       # Servidor → ESP32 (estado)

# --- URL de la cámara IP (IP Webcam app) ---
# Abre IP Webcam en tu celular y copia la URL que aparece en pantalla.
# Formato típico: http://192.168.x.x:8080/video
VIDEO_URL = "http://192.168.212.217:8080/video"   

# --- Parámetros del modelo ---
CONFIANZA_MINIMA  = 0.50    # Umbral mínimo de confianza para aceptar detección (0-1)
SKIP_FRAMES       = 2       # Procesar 1 de cada N frames (reduce latencia)
CLASES_DE_ALERTA  = {       # Clases que activan el buzzer (IDs de COCO)
    0 : "person",
    2 : "car",
    15: "cat",
    16: "dog",
    39: "bottle",
    56: "chair",
    67: "cell phone",
}

# --- Rutas de archivos del modelo ---
CARPETA_MODELO   = "modelo"
ARCHIVO_PESOS    = os.path.join(CARPETA_MODELO, "frozen_inference_graph.pb")
ARCHIVO_CONFIG   = os.path.join(CARPETA_MODELO, "ssd_mobilenet_v2_coco.pbtxt")
ARCHIVO_CLASES   = os.path.join(CARPETA_MODELO, "coco_classes.txt")
CARPETA_CAPTURAS = "capturas_detecciones"

os.makedirs(CARPETA_MODELO,   exist_ok=True)
os.makedirs(CARPETA_CAPTURAS, exist_ok=True)

# ============================================================
# DETECTOR HAAR CASCADE (siempre disponible, sin archivos extra)
# Usado en el loop de IP Webcam para detección de rostros/personas
# ============================================================
RUTA_HAAR = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
detector  = cv2.CascadeClassifier(RUTA_HAAR)
if detector.empty():
    print("[ERROR] No se pudo cargar haarcascade_frontalface_default.xml")
    exit(1)
print("[OK] Haar Cascade cargado.")

# ============================================================
# DESCARGA AUTOMÁTICA DEL MODELO (si no existe)
# ============================================================
# URLs directas de los archivos del modelo MobileNet SSD COCO
URLS_MODELO = {
    ARCHIVO_PESOS : (
        "http://download.tensorflow.org/models/object_detection/"
        "ssd_mobilenet_v2_coco_2018_03_29.tar.gz"
        # Nota: se usa el .pbtxt de OpenCV Zoo (ver instrucciones README)
    ),
    ARCHIVO_CONFIG: (
        "https://raw.githubusercontent.com/opencv/opencv_extra/master/"
        "testdata/dnn/ssd_mobilenet_v2_coco_2018_03_29.pbtxt"
    ),
}

COCO_CLASSES = [
    "background","person","bicycle","car","motorcycle","airplane","bus","train",
    "truck","boat","traffic light","fire hydrant","stop sign","parking meter",
    "bench","bird","cat","dog","horse","sheep","cow","elephant","bear","zebra",
    "giraffe","backpack","umbrella","handbag","tie","suitcase","frisbee","skis",
    "snowboard","sports ball","kite","baseball bat","baseball glove","skateboard",
    "surfboard","tennis racket","bottle","wine glass","cup","fork","knife","spoon",
    "bowl","banana","apple","sandwich","orange","broccoli","carrot","hot dog",
    "pizza","donut","cake","chair","couch","potted plant","bed","dining table",
    "toilet","tv","laptop","mouse","remote","keyboard","cell phone","microwave",
    "oven","toaster","sink","refrigerator","book","clock","vase","scissors",
    "teddy bear","hair drier","toothbrush"
]

def descargar_modelo():
    """Descarga el archivo .pbtxt del modelo si no existe."""
    os.makedirs(CARPETA_MODELO, exist_ok=True)

    # Descargar .pbtxt (configuración de la red)
    if not os.path.exists(ARCHIVO_CONFIG):
        log.info("Descargando archivo de configuración del modelo...")
        url_config = (
            "https://raw.githubusercontent.com/opencv/opencv_extra/"
            "master/testdata/dnn/ssd_mobilenet_v2_coco_2018_03_29.pbtxt"
        )
        try:
            urllib.request.urlretrieve(url_config, ARCHIVO_CONFIG)
            log.info(f"Descargado: {ARCHIVO_CONFIG}")
        except Exception as e:
            log.error(f"Error descargando config: {e}")
            return False

    # Guardar lista de clases COCO
    if not os.path.exists(ARCHIVO_CLASES):
        with open(ARCHIVO_CLASES, "w", encoding="utf-8") as f:
            for clase in COCO_CLASSES:
                f.write(clase + "\n")
        log.info(f"Archivo de clases creado: {ARCHIVO_CLASES}")

    # Verificar pesos
    if not os.path.exists(ARCHIVO_PESOS):
        log.warning("="*60)
        log.warning("ARCHIVO DE PESOS NO ENCONTRADO: frozen_inference_graph.pb")
        log.warning("Descarga manual requerida:")
        log.warning("1. Ve a: https://github.com/tensorflow/models/blob/master/")
        log.warning("   research/object_detection/g3doc/tf1_detection_zoo.md")
        log.warning("2. Descarga: ssd_mobilenet_v2_coco_2018_03_29.tar.gz")
        log.warning("3. Extrae frozen_inference_graph.pb y colócalo en ./modelo/")
        log.warning("="*60)
        log.warning("MODO ALTERNATIVO: Usando Haar Cascade como fallback...")
        return False

    return True

# ============================================================
# CARGA DEL MODELO DE IA
# ============================================================
red_neuronal = None
usar_fallback_haar = False

def cargar_modelo():
    """Carga MobileNet SSD. Si no está disponible, usa Haar Cascade."""
    global red_neuronal, usar_fallback_haar

    modelo_ok = descargar_modelo()

    if modelo_ok and os.path.exists(ARCHIVO_PESOS) and os.path.exists(ARCHIVO_CONFIG):
        log.info("Cargando MobileNet SSD (OpenCV DNN)...")
        try:
            red_neuronal = cv2.dnn.readNetFromTensorflow(ARCHIVO_PESOS, ARCHIVO_CONFIG)
            red_neuronal.setPreferableBackend(cv2.dnn.DNN_BACKEND_OPENCV)
            red_neuronal.setPreferableTarget(cv2.dnn.DNN_TARGET_CPU)
            log.info("✓ MobileNet SSD cargado correctamente.")
            log.info(f"  Clases: {len(COCO_CLASSES)} | Umbral confianza: {CONFIANZA_MINIMA}")
            usar_fallback_haar = False
            return True
        except Exception as e:
            log.error(f"Error cargando MobileNet SSD: {e}")

    # Fallback: Haar Cascade para personas (HOG + SVM de OpenCV)
    log.warning("Usando HOG Person Detector como alternativa (sin pesos externos).")
    usar_fallback_haar = True
    return True


# ============================================================
# DETECCIÓN CON MOBILENET SSD
# ============================================================
def detectar_con_dnn(frame: np.ndarray) -> list:
    """
    Aplica MobileNet SSD al frame.
    Retorna lista de dicts: [{"clase": str, "confianza": float, "bbox": [x,y,w,h]}]
    """
    alto, ancho = frame.shape[:2]

    # Preprocesar: convertir a blob 300x300
    blob = cv2.dnn.blobFromImage(
        frame,
        scalefactor=1.0/127.5,
        size=(300, 300),
        mean=(127.5, 127.5, 127.5),
        swapRB=True,
        crop=False
    )
    red_neuronal.setInput(blob)
    detecciones = red_neuronal.forward()

    objetos = []
    # detecciones shape: [1, 1, N, 7]
    # cada fila: [_, clase_id, confianza, x1, y1, x2, y2] (coords normalizadas)
    for i in range(detecciones.shape[2]):
        confianza = float(detecciones[0, 0, i, 2])
        if confianza < CONFIANZA_MINIMA:
            continue

        clase_id = int(detecciones[0, 0, i, 1])
        if clase_id < 0 or clase_id >= len(COCO_CLASSES):
            continue

        nombre_clase = COCO_CLASSES[clase_id]

        x1 = int(detecciones[0, 0, i, 3] * ancho)
        y1 = int(detecciones[0, 0, i, 4] * alto)
        x2 = int(detecciones[0, 0, i, 5] * ancho)
        y2 = int(detecciones[0, 0, i, 6] * alto)

        objetos.append({
            "clase"     : nombre_clase,
            "clase_id"  : clase_id,
            "confianza" : round(confianza, 3),
            "bbox"      : [x1, y1, x2 - x1, y2 - y1]
        })

    return objetos


# ============================================================
# DETECCIÓN CON HOG (fallback sin pesos externos)
# ============================================================
_hog = cv2.HOGDescriptor()
_hog.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())

def detectar_con_hog(frame: np.ndarray) -> list:
    """
    Usa HOG + SVM de OpenCV para detectar personas.
    No requiere archivos externos — siempre disponible.
    """
    frame_pequeno = cv2.resize(frame, (320, 240))
    rects, pesos = _hog.detectMultiScale(
        frame_pequeno,
        winStride=(8, 8),
        padding=(4, 4),
        scale=1.05
    )
    objetos = []
    esc_x = frame.shape[1] / 320
    esc_y = frame.shape[0] / 240
    for (x, y, w, h), peso in zip(rects, pesos):
        objetos.append({
            "clase"    : "person",
            "clase_id" : 0,
            "confianza": round(float(peso[0]), 3),
            "bbox"     : [int(x*esc_x), int(y*esc_y), int(w*esc_x), int(h*esc_y)]
        })
    return objetos


# ============================================================
# FUNCIÓN PRINCIPAL DE IA
# ============================================================
def procesar_imagen_con_ia(datos_base64: str) -> dict:
    """
    Pipeline completo:
      base64 → bytes → numpy array → modelo IA → decisión → dict resultado

    Args:
        datos_base64: Imagen JPEG codificada en base64 (enviada por ESP32)

    Returns:
        dict con claves: objetos_detectados, accion, alerta_clases,
                         tiempo_proceso_ms, num_detecciones
    """
    t_inicio = time.time()

    try:
        # 1. Decodificar base64 → imagen OpenCV
        img_bytes = base64.b64decode(datos_base64)
        img_array = np.frombuffer(img_bytes, dtype=np.uint8)
        frame     = cv2.imdecode(img_array, cv2.IMREAD_COLOR)

        if frame is None:
            return _resultado_error("No se pudo decodificar la imagen")

        # 2. Aplicar modelo
        if not usar_fallback_haar:
            objetos = detectar_con_dnn(frame)
        else:
            objetos = detectar_con_hog(frame)

        # 3. Filtrar clases de alerta
        clases_alerta_detectadas = [
            obj for obj in objetos
            if obj["clase_id"] in CLASES_DE_ALERTA
        ]

        # 4. Decidir acción
        accion = "ALERTA" if clases_alerta_detectadas else "LIBRE"
        tiempo_ms = round((time.time() - t_inicio) * 1000, 2)

        # 5. Anotar y guardar si hay detecciones
        if clases_alerta_detectadas:
            _guardar_captura_anotada(frame, objetos)

        log.info(
            f"IA | Detectados: {len(objetos)} objetos | "
            f"Alerta: {len(clases_alerta_detectadas)} | "
            f"Acción: {accion} | {tiempo_ms}ms"
        )

        return {
            "accion"               : accion,
            "num_detecciones"      : len(objetos),
            "objetos_detectados"   : objetos,
            "alerta_clases"        : [o["clase"] for o in clases_alerta_detectadas],
            "tiempo_proceso_ms"    : tiempo_ms,
        }

    except Exception as e:
        log.error(f"Error en pipeline IA: {e}")
        return _resultado_error(str(e))


def _resultado_error(msg: str) -> dict:
    return {
        "accion": "ERROR", "num_detecciones": 0,
        "objetos_detectados": [], "alerta_clases": [],
        "tiempo_proceso_ms": 0.0, "error": msg
    }


def _guardar_captura_anotada(frame: np.ndarray, objetos: list):
    """Dibuja bounding boxes y guarda la imagen en disco."""
    COLORES = {
        "person": (0, 0, 255), "car": (255, 128, 0),
        "cat": (0, 255, 128),  "dog": (255, 0, 128),
    }
    anotado = frame.copy()
    for obj in objetos:
        x, y, w, h = obj["bbox"]
        color = COLORES.get(obj["clase"], (0, 200, 255))
        cv2.rectangle(anotado, (x, y), (x+w, y+h), color, 2)
        etiqueta = f"{obj['clase']} {obj['confianza']:.0%}"
        cv2.putText(anotado, etiqueta, (x, max(y-6, 12)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:19]
    ruta = os.path.join(CARPETA_CAPTURAS, f"det_{ts}.jpg")
    cv2.imwrite(ruta, anotado)


# ============================================================
# CONSTRUCCIÓN DEL COMANDO PARA ACTUADORES
# ============================================================
def construir_comando(resultado: dict) -> dict:
    """
    Convierte el resultado de la IA en un JSON que la ESP32 interpreta:
        ALERTA → Buzzer ON (con duración y patrón)
        LIBRE  → Buzzer OFF
        ERROR  → Buzzer parpadeante corto
    """
    accion = resultado["accion"]
    clases = resultado.get("alerta_clases", [])
    num    = resultado.get("num_detecciones", 0)

    base = {
        "ts"          : int(time.time()),
        "num_objetos" : num,
        "clases"      : clases,
    }

    if accion == "ALERTA":
        # Patrón de buzzer según qué se detectó
        if "person" in clases:
            patron = "LARGO"        # 1 beep largo = persona detectada
        else:
            patron = "CORTO"        # 2 beeps cortos = otro objeto
        return {**base, "cmd": "ALERTA", "buzzer": 1,
                "patron": patron,
                "mensaje": f"Detectado: {', '.join(set(clases))}"}

    elif accion == "LIBRE":
        return {**base, "cmd": "LIBRE", "buzzer": 0,
                "patron": "NADA", "mensaje": "Sin detecciones"}

    else:
        return {**base, "cmd": "ERROR", "buzzer": 0,
                "patron": "ERROR", "mensaje": "Error en procesamiento IA"}


# ============================================================
# ESTADO GLOBAL
# ============================================================
estado = {
    "frames_recibidos"   : 0,
    "frames_procesados"  : 0,
    "detecciones_totales": 0,
    "alertas_totales"    : 0,
    "ultimo_comando"     : "NINGUNO",
    "conectado_mqtt"     : False,
}

# ============================================================
# CALLBACKS MQTT
# ============================================================
def on_connect(client, userdata, flags, rc):
    codigos = {0:"OK", 1:"Protocolo incorrecto", 2:"ID rechazado",
               3:"Servidor no disponible", 4:"Usuario/contraseña incorrectos"}
    if rc == 0:
        estado["conectado_mqtt"] = True
        log.info(f"✓ Conectado al broker: {MQTT_BROKER}:{MQTT_PORT}")
        client.subscribe([(TOPIC_IMAGEN, 0), (TOPIC_TELEMETRIA, 0)])
        log.info(f"  Suscrito a: {TOPIC_IMAGEN} | {TOPIC_TELEMETRIA}")
        client.publish(TOPIC_STATUS, json.dumps({
            "estado" : "ONLINE",
            "modelo" : "MobileNet SSD v2 COCO" if not usar_fallback_haar else "HOG People Detector",
            "version": "2.0",
            "ts"     : int(time.time())
        }), retain=True)
    else:
        log.error(f"Error MQTT: {codigos.get(rc, 'Desconocido')} (código {rc})")


def on_disconnect(client, userdata, rc):
    estado["conectado_mqtt"] = False
    log.warning(f"Desconectado del broker. Código: {rc}")


def on_message(client, userdata, msg):
    """Callback principal — procesa cada mensaje MQTT entrante."""
    estado["frames_recibidos"] += 1

    # ---- Imagen desde ESP32-CAM ----
    if msg.topic == TOPIC_IMAGEN:
        # Skip-frame: descartar frames intermedios para reducir latencia
        if estado["frames_recibidos"] % SKIP_FRAMES != 0:
            return

        try:
            payload = msg.payload.decode("utf-8")
            # Soporta dos formatos: JSON {"img": "..."} o base64 directo
            try:
                data   = json.loads(payload)
                b64    = data.get("img", payload)
            except json.JSONDecodeError:
                b64 = payload

            resultado = procesar_imagen_con_ia(b64)
            estado["frames_procesados"]  += 1
            estado["detecciones_totales"] += resultado["num_detecciones"]
            if resultado["accion"] == "ALERTA":
                estado["alertas_totales"] += 1

            comando = construir_comando(resultado)
            estado["ultimo_comando"] = comando["cmd"]
            client.publish(TOPIC_COMANDO, json.dumps(comando), qos=1)

        except Exception as e:
            log.error(f"Error procesando imagen: {e}")

    # ---- Telemetría ----
    elif msg.topic == TOPIC_TELEMETRIA:
        try:
            data = json.loads(msg.payload.decode("utf-8"))
            log.info(f"Telemetría: heap={data.get('heap_libre','?')}B | ts={data.get('ts','?')}")
        except Exception as e:
            log.error(f"Error en telemetría: {e}")


# ============================================================
# ESTADÍSTICAS
# ============================================================
def imprimir_estadisticas():
    total = max(estado["frames_procesados"], 1)
    tasa  = round(estado["alertas_totales"] / total * 100, 1)
    log.info("─"*55)
    log.info("  ESTADÍSTICAS DEL SERVIDOR IA")
    log.info(f"  Frames recibidos   : {estado['frames_recibidos']}")
    log.info(f"  Frames procesados  : {estado['frames_procesados']}")
    log.info(f"  Detecciones totales: {estado['detecciones_totales']}")
    log.info(f"  Alertas emitidas   : {estado['alertas_totales']} ({tasa}%)")
    log.info(f"  Último comando     : {estado['ultimo_comando']}")
    log.info(f"  MQTT conectado     : {estado['conectado_mqtt']}")
    log.info("─"*55)


# ============================================================
# MAIN
# ============================================================
if __name__ == "__main__":
    log.info("="*60)
    log.info("  SERVIDOR IA — DETECCIÓN DE OBJETOS (IP WEBCAM + MQTT)")
    log.info("="*60)

    # 1. Cargar modelos DNN opcionales
    cargar_modelo()

    # 2. Configurar cliente MQTT
    client = mqtt.Client(client_id=MQTT_CLIENT_ID, clean_session=True)
    client.on_connect    = on_connect
    client.on_disconnect = on_disconnect
    client.on_message    = on_message

    log.info(f"Conectando a broker MQTT: {MQTT_BROKER}:{MQTT_PORT} ...")
    try:
        client.connect(MQTT_BROKER, MQTT_PORT, MQTT_KEEPALIVE)
    except Exception as e:
        log.error(f"No se pudo conectar al broker: {e}")
        exit(1)

    # loop_start() corre MQTT en un hilo separado para no bloquear el video
    client.loop_start()
    log.info("MQTT corriendo en segundo plano.")

    # 3. Abrir stream de IP Webcam
    log.info(f"Conectando a cámara IP: {VIDEO_URL}")
    cap = cv2.VideoCapture(VIDEO_URL)
    if not cap.isOpened():
        log.error("No se pudo abrir el stream. Verifica VIDEO_URL y que el celular esté en la misma red.")
        client.loop_stop()
        client.disconnect()
        exit(1)
    log.info("[INFO] Cámara IP iniciada")
    log.info("Presiona Q en la ventana de video para detener.\n")

    frame_count  = 0
    t_stats      = time.time()

    try:
        while True:
            ret, frame = cap.read()

            # Si no llega frame, intentar reconectar automáticamente
            if not ret:
                log.error("[ERROR] No se recibió frame. Reintentando conexión...")
                cap.release()
                time.sleep(2)
                cap = cv2.VideoCapture(VIDEO_URL)
                continue

            frame_count += 1
            estado["frames_recibidos"] += 1

            # ── Detección con Haar Cascade ──────────────────────
            gray  = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            gray  = cv2.equalizeHist(gray)          # mejora contraste
            faces = detector.detectMultiScale(
                gray,
                scaleFactor  = 1.1,
                minNeighbors = 5,
                minSize      = (40, 40)
            )

            estado_deteccion = "SIN_PERSONA"
            for (x, y, w, h) in faces:
                cv2.rectangle(frame, (x, y), (x+w, y+h), (0, 255, 0), 2)
                cv2.putText(frame, "Persona", (x, max(y-8, 10)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
                estado_deteccion = "PERSONA_DETECTADA"

            # ── Mostrar estado en pantalla ──────────────────────
            color_estado = (0, 0, 255) if estado_deteccion == "PERSONA_DETECTADA" else (0, 200, 0)
            cv2.putText(frame, estado_deteccion, (10, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, color_estado, 2)
            cv2.putText(frame, f"Frames: {frame_count}", (10, 58),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, (200, 200, 200), 1)

            cv2.imshow("IA EN TIEMPO REAL", frame)

            # ── Publicar estado por MQTT → ESP32 (buzzer) ──────
            # Construir comando completo compatible con main.py de la ESP32
            if estado_deteccion == "PERSONA_DETECTADA":
                comando = {
                    "cmd"        : "ALERTA",
                    "buzzer"     : 1,
                    "patron"     : "LARGO",
                    "num_objetos": len(faces),
                    "clases"     : ["person"],
                    "mensaje"    : f"Persona detectada: {len(faces)}",
                    "ts"         : int(time.time())
                }
                estado["alertas_totales"] += 1
            else:
                comando = {
                    "cmd"        : "LIBRE",
                    "buzzer"     : 0,
                    "patron"     : "NADA",
                    "num_objetos": 0,
                    "clases"     : [],
                    "mensaje"    : "Sin detecciones",
                    "ts"         : int(time.time())
                }

            client.publish(TOPIC_CMD, json.dumps(comando), qos=1)
            estado["ultimo_comando"] = comando["cmd"]
            log.info(f"[MQTT] Estado enviado: {estado_deteccion}")

            # ── Guardar captura si hay detección ───────────────
            if estado_deteccion == "PERSONA_DETECTADA":
                _guardar_captura_anotada(frame, [
                    {"clase": "person", "clase_id": 0,
                     "confianza": 0.9, "bbox": [int(x), int(y), int(w), int(h)]}
                    for (x, y, w, h) in faces
                ])

            # ── Estadísticas periódicas ────────────────────────
            estado["frames_procesados"] += 1
            if time.time() - t_stats >= 30:
                imprimir_estadisticas()
                t_stats = time.time()

            # ── Salir con tecla Q ──────────────────────────────
            if cv2.waitKey(1) & 0xFF == ord('q'):
                log.info("Tecla Q presionada. Cerrando...")
                break

    except KeyboardInterrupt:
        log.info("Interrupción por teclado.")

    finally:
        # Limpieza ordenada
        cap.release()
        cv2.destroyAllWindows()
        client.publish(TOPIC_STATUS, json.dumps({
            "estado": "OFFLINE", "ts": int(time.time())
        }), retain=True)
        client.loop_stop()
        client.disconnect()
        imprimir_estadisticas()
        log.info("Servidor detenido correctamente.")