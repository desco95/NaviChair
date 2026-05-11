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
#   Biblioteca HAL (Hardware Abstraction Layer) que centraliza el control de
#   todos los periféricos del sistema NaviChair. Abstrae la complejidad de los
#   sensores ultrasónicos HC-SR04, giroscopio MPU-6050, sensor PIR, buzzer,
#   pantalla OLED y relevador, permitiendo que el programa principal interactúe
#   con el hardware mediante métodos de alto nivel en español.
#
# ARCHIVO: dispositivos.py
# =============================================================================

from machine import Pin, PWM, I2C, time_pulse_us
import ssd1306
import time
import math

# =============================================================================
# MÓDULO DE SENSORES (LECTURA) — Clase CajaDeGestion
# =============================================================================

class CajaDeGestion:
    """
    Clase que gestiona todos los sensores del sistema NaviChair:
      - 3 sensores ultrasónicos HC-SR04 (izquierda, centro, derecha)
      - Giroscopio/Acelerómetro MPU-6050
      - Sensor PIR de movimiento
    Provee lecturas interpretadas, promedios móviles y resumen global.
    """

    # Dirección I2C del MPU-6050
    _DIRECCION_MPU = 0x68
    # Registro de configuración de energía del MPU-6050
    _REG_PWR_MGMT_1 = 0x6B
    # Registros del acelerómetro (ejes X, Y, Z — 2 bytes cada uno)
    _REG_ACCEL_XOUT_H = 0x3B

    def __init__(self):
        # -----------------------------------------------
        # Sensores ultrasónicos HC-SR04
        # Cada sensor tiene un pin TRIG (salida) y un ECHO (entrada)
        # -----------------------------------------------
        # Izquierda
        self.trig_izq  = Pin(5,  Pin.OUT)
        self.echo_izq  = Pin(18, Pin.IN)

        # Centro (frente)
        self.trig_cen  = Pin(19, Pin.OUT)
        self.echo_cen  = Pin(21, Pin.IN)

        # Derecha
        self.trig_der  = Pin(22, Pin.OUT)
        self.echo_der  = Pin(23, Pin.IN)

        # -----------------------------------------------
        # Giroscopio / Acelerómetro MPU-6050 (I2C)
        # -----------------------------------------------
        self.i2c_sensor = I2C(1, scl=Pin(25), sda=Pin(26), freq=400000)
        # Despertar el MPU-6050 (salir del modo sleep)
        self.i2c_sensor.writeto_mem(self._DIRECCION_MPU,
                                    self._REG_PWR_MGMT_1,
                                    bytes([0x00]))

        # -----------------------------------------------
        # Sensor PIR de movimiento
        # -----------------------------------------------
        self.pir = Pin(27, Pin.IN)

        # -----------------------------------------------
        # Variables internas para promedios móviles
        # Se guardan las últimas N lecturas de distancia (por dirección)
        # -----------------------------------------------
        self._tamano_ventana = 5
        self._historial_izq  = []
        self._historial_cen  = []
        self._historial_der  = []

        # Tiempo de la última detección de movimiento (para inmovilidad)
        self._ultimo_movimiento = time.time()

    # ------------------------------------------------------------------
    # Métodos privados de apoyo
    # ------------------------------------------------------------------

    def _pulso_ultrasonico(self, trig, echo):
        """
        Parámetros : trig (Pin salida), echo (Pin entrada)
        Descripción: Genera un pulso de 10 µs en TRIG y mide el tiempo
                     de respuesta en ECHO para calcular la distancia.
        Retorna    : Distancia en centímetros (float). Devuelve 999 si
                     no se recibe eco (fuera de rango).
        """
        trig.value(0)
        time.sleep_us(2)
        trig.value(1)
        time.sleep_us(10)
        trig.value(0)

        duracion = time_pulse_us(echo, 1, 30000)  # timeout 30 ms
        if duracion < 0:
            return 999.0  # sin eco = fuera de rango
        # Velocidad del sonido ≈ 0.0343 cm/µs; dividir entre 2 (ida y vuelta)
        return (duracion * 0.0343) / 2.0

    def _agregar_a_historial(self, historial, valor):
        """
        Parámetros : historial (lista), valor (float)
        Descripción: Añade el valor a la lista y la mantiene con un
                     máximo de _tamano_ventana elementos (FIFO).
        Retorna    : None
        """
        historial.append(valor)
        if len(historial) > self._tamano_ventana:
            historial.pop(0)

    def _promedio(self, historial):
        """
        Parámetros : historial (lista de floats)
        Descripción: Calcula el promedio simple de los valores almacenados.
        Retorna    : Promedio (float), o 999 si la lista está vacía.
        """
        if not historial:
            return 999.0
        return sum(historial) / len(historial)

    # ------------------------------------------------------------------
    # Métodos públicos — Lecturas de sensores ultrasónicos
    # ------------------------------------------------------------------

    def leer_distancia_izquierda(self):
        """
        Parámetros : Ninguno
        Descripción: Lee el sensor ultrasónico izquierdo, aplica promedio
                     móvil de las últimas 5 muestras para estabilizar la
                     lectura.
        Retorna    : Distancia promediada en centímetros (float).
        """
        valor = self._pulso_ultrasonico(self.trig_izq, self.echo_izq)
        self._agregar_a_historial(self._historial_izq, valor)
        return self._promedio(self._historial_izq)

    def leer_distancia_centro(self):
        """
        Parámetros : Ninguno
        Descripción: Lee el sensor ultrasónico central (frente), aplica
                     promedio móvil de las últimas 5 muestras.
        Retorna    : Distancia promediada en centímetros (float).
        """
        valor = self._pulso_ultrasonico(self.trig_cen, self.echo_cen)
        self._agregar_a_historial(self._historial_cen, valor)
        return self._promedio(self._historial_cen)

    def leer_distancia_derecha(self):
        """
        Parámetros : Ninguno
        Descripción: Lee el sensor ultrasónico derecho, aplica promedio
                     móvil de las últimas 5 muestras.
        Retorna    : Distancia promediada en centímetros (float).
        """
        valor = self._pulso_ultrasonico(self.trig_der, self.echo_der)
        self._agregar_a_historial(self._historial_der, valor)
        return self._promedio(self._historial_der)

    # ------------------------------------------------------------------
    # Métodos públicos — Giroscopio MPU-6050
    # ------------------------------------------------------------------

    def leer_inclinacion_grados(self):
        """
        Parámetros : Ninguno
        Descripción: Lee los registros del acelerómetro MPU-6050 y calcula
                     el ángulo de inclinación resultante (pitch/roll
                     combinado) usando la magnitud vectorial del plano
                     XZ respecto al eje Y.
        Retorna    : Ángulo de inclinación en grados (float, 0–90).
        """
        datos = self.i2c_sensor.readfrom_mem(
            self._DIRECCION_MPU, self._REG_ACCEL_XOUT_H, 6)

        # Convertir bytes a enteros con signo (big-endian, 16 bits)
        def _bytes_a_int(alto, bajo):
            valor = (alto << 8) | bajo
            return valor - 65536 if valor > 32767 else valor

        ax = _bytes_a_int(datos[0], datos[1])
        ay = _bytes_a_int(datos[2], datos[3])
        az = _bytes_a_int(datos[4], datos[5])

        # Normalizar (escala ±2g → dividir entre 16384)
        ax_g = ax / 16384.0
        ay_g = ay / 16384.0
        az_g = az / 16384.0

        # Ángulo de inclinación respecto a la gravedad
        angulo = math.degrees(math.atan2(math.sqrt(ax_g**2 + az_g**2), ay_g))
        return abs(angulo)

    # ------------------------------------------------------------------
    # Métodos públicos — Sensor PIR
    # ------------------------------------------------------------------

    def detectar_movimiento(self):
        """
        Parámetros : Ninguno
        Descripción: Lee el estado digital del sensor PIR. Si detecta
                     movimiento, actualiza el timestamp interno.
        Retorna    : True si hay movimiento activo, False en caso contrario.
        """
        estado = self.pir.value() == 1
        if estado:
            self._ultimo_movimiento = time.time()
        return estado

    def minutos_sin_movimiento(self):
        """
        Parámetros : Ninguno
        Descripción: Calcula cuántos minutos han transcurrido desde la
                     última detección de movimiento del PIR.
        Retorna    : Minutos transcurridos (float).
        """
        segundos = time.time() - self._ultimo_movimiento
        return segundos / 60.0

    # ------------------------------------------------------------------
    # Método de resumen global
    # ------------------------------------------------------------------

    def obtener_resumen_sensores(self):
        """
        Parámetros : Ninguno
        Descripción: Consolida en un diccionario el estado actualizado de
                     todos los sensores del sistema con una sola llamada.
        Retorna    : Diccionario con claves:
                       'dist_izq'     — distancia izquierda (cm)
                       'dist_cen'     — distancia centro (cm)
                       'dist_der'     — distancia derecha (cm)
                       'inclinacion'  — ángulo de inclinación (°)
                       'movimiento'   — True/False
                       'min_inmovil'  — minutos sin movimiento (float)
        """
        return {
            "dist_izq"   : self.leer_distancia_izquierda(),
            "dist_cen"   : self.leer_distancia_centro(),
            "dist_der"   : self.leer_distancia_derecha(),
            "inclinacion": self.leer_inclinacion_grados(),
            "movimiento" : self.detectar_movimiento(),
            "min_inmovil": self.minutos_sin_movimiento()
        }


# =============================================================================
# MÓDULO DE ACTUADORES (ACCIÓN) — Clase CajaDeControl
# =============================================================================

class CajaDeControl:
    """
    Clase que gestiona todos los actuadores del sistema NaviChair:
      - Buzzer (alertas sonoras direccionales)
      - Pantalla OLED SSD1306 (información en tiempo real)
      - Relevador (alerta física ante inclinación extrema)
    Provee comandos de alto nivel y un método de estado seguro.
    """

    # Umbral de distancia para considerar un obstáculo cercano (cm)
    UMBRAL_OBSTACULO_CM = 50
    # Umbral de inclinación peligrosa (grados)
    UMBRAL_INCLINACION_GRADOS = 30
    # Umbral de inmovilidad para alerta (minutos)
    UMBRAL_INMOVILIDAD_MIN = 10

    def __init__(self):
        # -----------------------------------------------
        # Buzzer (PWM para tonos variables)
        # -----------------------------------------------
        self.buzzer = PWM(Pin(13), freq=1000, duty=0)

        # -----------------------------------------------
        # Pantalla OLED 128x64 por I2C
        # -----------------------------------------------
        self.i2c_pantalla = I2C(0, scl=Pin(22), sda=Pin(21), freq=400000)
        self.pantalla = ssd1306.SSD1306_I2C(128, 64, self.i2c_pantalla)

        # -----------------------------------------------
        # Relevador (alerta física)
        # -----------------------------------------------
        self.relevador = Pin(14, Pin.OUT)
        self.relevador.value(0)  # Inactivo al iniciar

    # ------------------------------------------------------------------
    # Métodos privados de apoyo
    # ------------------------------------------------------------------

    def _tono(self, frecuencia_hz, duracion_ms):
        """
        Parámetros : frecuencia_hz (int) — frecuencia del tono en Hz
                     duracion_ms (int)   — duración del tono en milisegundos
        Descripción: Genera un tono en el buzzer durante el tiempo indicado
                     y luego lo apaga.
        Retorna    : None
        """
        self.buzzer.freq(frecuencia_hz)
        self.buzzer.duty(512)       # ~50 % ciclo de trabajo
        time.sleep_ms(duracion_ms)
        self.buzzer.duty(0)

    # ------------------------------------------------------------------
    # Métodos públicos — Buzzer
    # ------------------------------------------------------------------

    def alerta_obstaculo_izquierda(self):
        """
        Parámetros : Ninguno
        Descripción: Emite un tono corto (300 ms) para señalar obstáculo
                     detectado por el sensor izquierdo.
        Retorna    : None
        """
        self._tono(1200, 300)

    def alerta_obstaculo_derecha(self):
        """
        Parámetros : Ninguno
        Descripción: Emite un tono largo (800 ms) para señalar obstáculo
                     detectado por el sensor derecho.
        Retorna    : None
        """
        self._tono(1200, 800)

    def alerta_obstaculo_frente(self):
        """
        Parámetros : Ninguno
        Descripción: Emite 3 tonos continuos para señalar obstáculo
                     detectado por el sensor central (frente).
        Retorna    : None
        """
        for _ in range(3):
            self._tono(1500, 200)
            time.sleep_ms(100)

    def alerta_inclinacion_critica(self):
        """
        Parámetros : Ninguno
        Descripción: Emite una secuencia de tonos urgentes (frecuencia
                     alta, patrón rápido) ante una inclinación peligrosa
                     detectada por el giroscopio.
        Retorna    : None
        """
        for _ in range(5):
            self._tono(2500, 150)
            time.sleep_ms(80)

    def alerta_inmovilidad(self):
        """
        Parámetros : Ninguno
        Descripción: Emite 2 tonos graves para señalar que el usuario lleva
                     más de 10 minutos sin moverse.
        Retorna    : None
        """
        for _ in range(2):
            self._tono(700, 500)
            time.sleep_ms(200)

    # ------------------------------------------------------------------
    # Métodos públicos — Pantalla OLED
    # ------------------------------------------------------------------

    def mostrar_distancias(self, izq, cen, der):
        """
        Parámetros : izq (float) — distancia izquierda en cm
                     cen (float) — distancia centro en cm
                     der (float) — distancia derecha en cm
        Descripción: Actualiza la pantalla OLED con las distancias actuales
                     de los tres sensores ultrasónicos.
        Retorna    : None
        """
        self.pantalla.fill(0)
        self.pantalla.text("NaviChair", 24, 0)
        self.pantalla.text("Izq:{:.0f}cm".format(izq),  0, 16)
        self.pantalla.text("Cen:{:.0f}cm".format(cen),  0, 28)
        self.pantalla.text("Der:{:.0f}cm".format(der),  0, 40)
        self.pantalla.show()

    def mostrar_alerta(self, mensaje_linea1, mensaje_linea2=""):
        """
        Parámetros : mensaje_linea1 (str) — primera línea del mensaje
                     mensaje_linea2 (str) — segunda línea (opcional)
        Descripción: Muestra un mensaje de alerta en la pantalla OLED,
                     limpiando el contenido anterior.
        Retorna    : None
        """
        self.pantalla.fill(0)
        self.pantalla.text("!! ALERTA !!", 16, 0)
        self.pantalla.text(mensaje_linea1, 0, 20)
        self.pantalla.text(mensaje_linea2, 0, 36)
        self.pantalla.show()

    def mostrar_estado_sistema(self, inclinacion, min_inmovil):
        """
        Parámetros : inclinacion (float) — ángulo actual en grados
                     min_inmovil (float) — minutos sin movimiento
        Descripción: Muestra en la pantalla OLED el estado de inclinación
                     y el tiempo de inmovilidad del usuario.
        Retorna    : None
        """
        self.pantalla.fill(0)
        self.pantalla.text("NaviChair OK", 8, 0)
        self.pantalla.text("Incl:{:.1f}g".format(inclinacion), 0, 20)
        self.pantalla.text("Inmov:{:.1f}min".format(min_inmovil), 0, 36)
        self.pantalla.show()

    # ------------------------------------------------------------------
    # Métodos públicos — Relevador
    # ------------------------------------------------------------------

    def activar_alerta_fisica(self):
        """
        Parámetros : Ninguno
        Descripción: Activa el relevador para disparar una señal de alerta
                     física externa (luz, sirena u otro dispositivo
                     conectado al circuito del relevador).
        Retorna    : None
        """
        self.relevador.value(1)

    def desactivar_alerta_fisica(self):
        """
        Parámetros : Ninguno
        Descripción: Desactiva el relevador, cortando la señal de alerta
                     física externa.
        Retorna    : None
        """
        self.relevador.value(0)

    # ------------------------------------------------------------------
    # Estado seguro — apaga todos los actuadores
    # ------------------------------------------------------------------

    def estado_seguro(self):
        """
        Parámetros : Ninguno
        Descripción: Apaga o detiene TODOS los actuadores de forma inmediata.
                     Debe llamarse ante cualquier interrupción o excepción
                     para garantizar que el sistema quede en reposo seguro.
        Retorna    : None
        """
        self.buzzer.duty(0)
        self.relevador.value(0)
        self.pantalla.fill(0)
        self.pantalla.text("ESTADO SEGURO", 4, 24)
        self.pantalla.show()
