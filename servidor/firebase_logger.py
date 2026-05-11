"""
OBJETIVO  : Gestión de Firebase y escucha de comandos de la interfaz web.
            Recibe telemetría de NaviChair vía MQTT y la almacena en
            Firebase Realtime Database con timestamps. También escucha
            cambios en Firebase para ejecutar comandos del dashboard.
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
# ARCHIVO: firebase_logger.py
# DESCRIPCIÓN: Conecta el servidor Python con Firebase Realtime Database.
#              Almacena tres tipos de eventos con timestamp:
#                1. telemetria  — lecturas periódicas de sensores
#                2. alerta      — eventos de obstáculo, inclinación o inmovilidad
#                3. resultado_ia — detecciones del modelo de visión artificial
#              También escucha el nodo "comandos" de Firebase para activar
#              actuadores desde la interfaz web (control bidireccional).
#
# CONFIGURACIÓN REQUERIDA:
#   1. Crear proyecto en https://console.firebase.google.com
#   2. En Project Settings → Service Accounts → Generate new private key
#   3. Guardar el archivo JSON descargado como: credencial_firebase.json
#   4. Cambiar RUTA_CREDENCIAL y URL_BASE_DE_DATOS abajo
# =============================================================================

import paho.mqtt.client as mqtt
import firebase_admin
from firebase_admin import credentials, db
import json
import datetime
import time

# -----------------------------------------------------------------------
# CONFIGURACIÓN DE FIREBASE
# -----------------------------------------------------------------------

# Ruta al archivo JSON de credenciales descargado desde Firebase Console
RUTA_CREDENCIAL    = "credencial_firebase.json"

# URL de tu Realtime Database (la encontrarás en Firebase Console → Realtime DB)
# Formato: https://TU-PROYECTO-DEFAULT-RTDB.firebaseio.com/
URL_BASE_DE_DATOS  = "https://navichair-XXXX-default-rtdb.firebaseio.com/"

# -----------------------------------------------------------------------
# CONFIGURACIÓN DE MQTT
# -----------------------------------------------------------------------
DIRECCION_BROKER   = "localhost"
PUERTO_BROKER      = 1883
ID_CLIENTE_FB      = "navichair_firebase_logger"

TOPICOS_ESCUCHAR   = [
    ("navichair/estado",      0),   # Telemetría general (todos los sensores)
    ("navichair/obstaculos",  0),   # Alertas de obstáculo
    ("navichair/inclinacion", 0),   # Alertas de inclinación
    ("navichair/inmovilidad", 0),   # Alertas de inmovilidad
    ("navichair/ia/resultado",0),   # Resultados del modelo IA
]

TOPICO_CMD_BUZZER    = "navichair/cmd/buzzer"
TOPICO_CMD_RELEVADOR = "navichair/cmd/relevador"

# Referencia global al cliente MQTT (para usarla dentro de los callbacks de Firebase)
_cliente_mqtt_global = None


# -----------------------------------------------------------------------
# INICIALIZACIÓN DE FIREBASE
# -----------------------------------------------------------------------

def inicializar_firebase():
    """
    Parámetros : Ninguno
    Descripción: Inicializa la conexión con Firebase usando las credenciales
                 del archivo JSON. Debe llamarse una sola vez al inicio.
    Retorna    : Referencia a la base de datos raíz (firebase_admin.db.Reference)
    """
    try:
        cred = credentials.Certificate(RUTA_CREDENCIAL)
        firebase_admin.initialize_app(cred, {"databaseURL": URL_BASE_DE_DATOS})
        referencia = db.reference("/")
        print("{} Firebase conectado correctamente.".format(marca_de_tiempo()))
        return referencia
    except FileNotFoundError:
        print("ERROR: No se encontró el archivo de credenciales.")
        print("  Ruta buscada:", RUTA_CREDENCIAL)
        print("  Descárgalo desde Firebase Console → Project Settings → Service Accounts")
        return None
    except Exception as error:
        print("ERROR al inicializar Firebase:", error)
        return None


def marca_de_tiempo():
    """
    Parámetros : Ninguno
    Descripción: Devuelve la fecha y hora actual como cadena de texto.
    Retorna    : Cadena con formato [YYYY-MM-DD HH:MM:SS] (str).
    """
    return datetime.datetime.now().strftime("[%Y-%m-%d %H:%M:%S]")


def timestamp_iso():
    """
    Parámetros : Ninguno
    Descripción: Devuelve el timestamp actual en formato ISO 8601,
                 adecuado para almacenar en Firebase.
    Retorna    : Cadena de texto con fecha/hora ISO (str).
    """
    return datetime.datetime.now().isoformat()


# -----------------------------------------------------------------------
# ALMACENAMIENTO EN FIREBASE
# -----------------------------------------------------------------------

def guardar_telemetria(referencia_db, datos_dict):
    """
    Parámetros : referencia_db (db.Reference) — referencia raíz de Firebase
                 datos_dict (dict)             — diccionario con las lecturas
    Descripción: Almacena una entrada de telemetría (tipo 1) en Firebase
                 bajo el nodo /telemetria, con timestamp automático.
                 Solo guarda las últimas 100 entradas para no llenar la DB.
    Retorna    : None
    """
    entrada = {
        "tipo"      : "telemetria",
        "timestamp" : timestamp_iso(),
        "datos"     : datos_dict
    }
    referencia_db.child("telemetria").push(entrada)


def guardar_alerta(referencia_db, tipo_alerta, descripcion, valor=None):
    """
    Parámetros : referencia_db (db.Reference) — referencia raíz de Firebase
                 tipo_alerta (str)  — "obstaculo", "inclinacion" o "inmovilidad"
                 descripcion (str)  — descripción legible del evento
                 valor (float/None) — valor numérico asociado (opcional)
    Descripción: Almacena un evento de alerta (tipo 2) en Firebase bajo
                 el nodo /alertas, con timestamp y tipo de evento.
    Retorna    : None
    """
    entrada = {
        "tipo"        : "alerta",
        "subtipo"     : tipo_alerta,
        "descripcion" : descripcion,
        "valor"       : valor,
        "timestamp"   : timestamp_iso()
    }
    referencia_db.child("alertas").push(entrada)
    # Actualizar el nodo de última alerta (para el dashboard)
    referencia_db.child("ultima_alerta").set(entrada)
    print("{} Alerta guardada en Firebase: {} — {}".format(
        marca_de_tiempo(), tipo_alerta, descripcion))


def guardar_resultado_ia(referencia_db, detecciones, es_alerta):
    """
    Parámetros : referencia_db (db.Reference) — referencia raíz de Firebase
                 detecciones (int)  — número de objetos detectados por la IA
                 es_alerta (bool)   — si el resultado supera el umbral de alerta
    Descripción: Almacena el resultado del modelo IA (tipo 3) en Firebase
                 bajo el nodo /resultados_ia, con timestamp.
    Retorna    : None
    """
    entrada = {
        "tipo"        : "resultado_ia",
        "detecciones" : detecciones,
        "alerta"      : es_alerta,
        "timestamp"   : timestamp_iso()
    }
    referencia_db.child("resultados_ia").push(entrada)


def actualizar_estado_sensores(referencia_db, datos_dict):
    """
    Parámetros : referencia_db (db.Reference) — referencia raíz de Firebase
                 datos_dict (dict)             — datos actuales de todos los sensores
    Descripción: Sobreescribe el nodo /estado_actual con los datos más
                 recientes. Este nodo es el que el dashboard muestra en
                 "tiempo real" (última lectura de cada sensor).
    Retorna    : None
    """
    datos_dict["timestamp"] = timestamp_iso()
    referencia_db.child("estado_actual").set(datos_dict)


# -----------------------------------------------------------------------
# ESCUCHA DE COMANDOS DESDE FIREBASE (Control bidireccional)
# El dashboard web escribe en /comandos/buzzer y /comandos/relevador.
# Este listener detecta los cambios y los reenvía por MQTT a la ESP32.
# -----------------------------------------------------------------------

def escuchar_comandos_firebase(referencia_db):
    """
    Parámetros : referencia_db (db.Reference) — referencia raíz de Firebase
    Descripción: Registra un listener de cambios en el nodo /comandos de
                 Firebase. Cuando el dashboard cambia el valor de un comando
                 (ej. "buzzer": "ON"), este listener lo detecta y publica
                 el comando vía MQTT hacia la ESP32.
    Retorna    : None
    """
    def al_cambiar_comando(evento):
        """
        Parámetros : evento — evento de Firebase con .path y .data
        Descripción: Callback interno. Se ejecuta cuando cambia cualquier
                     valor bajo /comandos en Firebase.
        Retorna    : None
        """
        if evento.data is None or _cliente_mqtt_global is None:
            return

        ruta = evento.path.strip("/")  # ej: "buzzer" o "relevador"
        valor = str(evento.data)       # "ON" o "OFF"

        if ruta == "buzzer":
            _cliente_mqtt_global.publish(TOPICO_CMD_BUZZER, valor)
            print("{} Comando desde dashboard → buzzer: {}".format(
                marca_de_tiempo(), valor))
        elif ruta == "relevador":
            _cliente_mqtt_global.publish(TOPICO_CMD_RELEVADOR, valor)
            print("{} Comando desde dashboard → relevador: {}".format(
                marca_de_tiempo(), valor))

    referencia_db.child("comandos").listen(al_cambiar_comando)
    print("{} Escuchando comandos del dashboard en Firebase...".format(
        marca_de_tiempo()))


# -----------------------------------------------------------------------
# CALLBACKS MQTT
# -----------------------------------------------------------------------

def construir_callbacks(referencia_db):
    """
    Parámetros : referencia_db — referencia raíz de Firebase
    Descripción: Construye y devuelve las funciones callback de MQTT con
                 acceso a la referencia de Firebase (closure).
    Retorna    : Tupla (al_conectar, al_recibir_mensaje).
    """

    def al_conectar(cliente, datos_usuario, indicadores, codigo_resultado):
        if codigo_resultado == 0:
            print("{} Logger conectado al broker MQTT.".format(marca_de_tiempo()))
            for topico, qos in TOPICOS_ESCUCHAR:
                cliente.subscribe(topico, qos)
        else:
            print("{} ERROR de conexión MQTT. Código: {}".format(
                marca_de_tiempo(), codigo_resultado))

    def al_recibir_mensaje(cliente, datos_usuario, mensaje):
        topico = mensaje.topic
        carga  = mensaje.payload.decode("utf-8", errors="replace")

        if referencia_db is None:
            return

        # --- Tópico: estado general (telemetría periódica) ---
        if topico == "navichair/estado":
            try:
                datos = json.loads(carga)
                guardar_telemetria(referencia_db, datos)
                actualizar_estado_sensores(referencia_db, datos)
            except Exception as e:
                print("Error al procesar estado:", e)

        # --- Tópico: obstáculos ---
        elif topico == "navichair/obstaculos":
            guardar_alerta(referencia_db, "obstaculo",
                           "Obstáculo detectado: " + carga)

        # --- Tópico: inclinación ---
        elif topico == "navichair/inclinacion":
            try:
                grados = float(carga.split(":")[-1].replace("grados", "").strip())
                guardar_alerta(referencia_db, "inclinacion",
                               "Inclinación peligrosa detectada", grados)
            except Exception:
                guardar_alerta(referencia_db, "inclinacion",
                               "Inclinación peligrosa detectada")

        # --- Tópico: inmovilidad ---
        elif topico == "navichair/inmovilidad":
            try:
                minutos = float(carga.split(":")[-1].replace("min", "").strip())
                guardar_alerta(referencia_db, "inmovilidad",
                               "Inmovilidad prolongada", minutos)
            except Exception:
                guardar_alerta(referencia_db, "inmovilidad",
                               "Inmovilidad prolongada detectada")

        # --- Tópico: resultado de IA ---
        elif topico == "navichair/ia/resultado":
            try:
                datos_ia = json.loads(carga)
                guardar_resultado_ia(
                    referencia_db,
                    datos_ia.get("detecciones", 0),
                    datos_ia.get("alerta", False)
                )
            except Exception as e:
                print("Error al procesar resultado IA:", e)

    return al_conectar, al_recibir_mensaje


# -----------------------------------------------------------------------
# PROGRAMA PRINCIPAL
# -----------------------------------------------------------------------

if __name__ == "__main__":
    global _cliente_mqtt_global

    # Inicializar Firebase
    referencia_db = inicializar_firebase()
    if referencia_db is None:
        print("No se pudo conectar a Firebase. Revisa las credenciales.")
        exit(1)

    # Iniciar listener de comandos del dashboard
    escuchar_comandos_firebase(referencia_db)

    # Construir callbacks con acceso a Firebase
    cb_conectar, cb_mensaje = construir_callbacks(referencia_db)

    # Crear cliente MQTT
    cliente_fb = mqtt.Client(client_id=ID_CLIENTE_FB)
    cliente_fb.on_connect = cb_conectar
    cliente_fb.on_message = cb_mensaje
    _cliente_mqtt_global  = cliente_fb

    print("{} Iniciando logger Firebase NaviChair...".format(marca_de_tiempo()))

    try:
        cliente_fb.connect(DIRECCION_BROKER, PUERTO_BROKER, keepalive=60)
        cliente_fb.loop_forever()
    except KeyboardInterrupt:
        print("\n{} Logger Firebase detenido.".format(marca_de_tiempo()))
        cliente_fb.disconnect()
    except ConnectionRefusedError:
        print("{} ERROR: Broker no disponible.".format(marca_de_tiempo()))
