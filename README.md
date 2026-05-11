# 🦽 NaviChair — Sistema Inteligente de Asistencia y Monitoreo para Silla de Ruedas Manual

**Instituto Tecnológico de León · Ingeniería en Sistemas Computacionales · Sistemas Programables**

## Integrantes

| Nombre | Rol principal |
|---|---|
| Diana Carolina Plascencia Rodríguez | HAL + MQTT en ESP32 |
| María Aurora Rodríguez López | Servidor Python + Pipeline IA |
| Escobedo Ojeda Luis David | Firebase + Dashboard web |
| Quintero Frausto Valeria Melissa Leilani | Integración, repositorio y reporte |

---

## Descripción del proyecto

NaviChair es un sistema IoT que convierte una silla de ruedas manual en un dispositivo inteligente capaz de:

- Detectar obstáculos a izquierda, frente y derecha mediante sensores ultrasónicos
- Alertar ante inclinaciones peligrosas del terreno con el giroscopio MPU-6050
- Detectar inmovilidad prolongada del usuario con un sensor PIR
- Procesar imágenes de la ESP32-CAM en un servidor Python con OpenCV para identificar personas u obstáculos
- Registrar todos los eventos en Firebase con timestamps
- Mostrar el estado en tiempo real y permitir control remoto desde una interfaz web

---

## Arquitectura del sistema

```
ESP32 (sensores + actuadores)
    ↕ MQTT
PC / Servidor Python
    ├── mqtt_bridge.py     → Recibe telemetría, publica comandos
    ├── ia_processor.py    → Procesa imágenes con OpenCV
    └── firebase_logger.py → Almacena eventos en Firebase
         ↕ Firebase Realtime DB
    interfaz/index.html    → Dashboard web del cuidador
```

---

## Estructura del repositorio

```
/
├── esp32/
│   ├── dispositivos.py    → Biblioteca HAL (CajaDeGestion + CajaDeControl)
│   └── main.py            → Programa principal del microcontrolador
├── servidor/
│   ├── mqtt_bridge.py     → Puente MQTT (telemetría + comandos)
│   ├── ia_processor.py    → Pipeline de IA con OpenCV
│   └── firebase_logger.py → Logger de eventos en Firebase
├── interfaz/
│   └── index.html         → Dashboard web
└── README.md
```

---

## Hardware requerido

| Componente | Cantidad | Función |
|---|---|---|
| ESP32 | 1 | Microcontrolador principal |
| ESP32-CAM | 1 | Transmisión de video e IA |
| Sensor HC-SR04 | 3 | Distancia izquierda, centro, derecha |
| MPU-6050 | 1 | Inclinación de la silla |
| Sensor PIR | 1 | Detección de movimiento del usuario |
| Buzzer activo | 1 | Alertas sonoras direccionales |
| Pantalla OLED 128x64 | 1 | Estado visual en tiempo real |
| Relevador 5V | 1 | Alerta física externa |

---

## Tabla de tópicos MQTT

| Tópico | Dirección | Contenido |
|---|---|---|
| `navichair/obstaculos` | ESP32 → Servidor | Distancia y dirección del obstáculo |
| `navichair/inclinacion` | ESP32 → Servidor | Ángulo en grados del MPU-6050 |
| `navichair/inmovilidad` | ESP32 → Servidor | Minutos sin movimiento (PIR) |
| `navichair/estado` | ESP32 → Servidor | JSON con todos los sensores |
| `navichair/camara` | ESP32-CAM → Servidor | Imagen en base64 |
| `navichair/ia/resultado` | Servidor → Firebase | Detecciones del modelo IA |
| `navichair/cmd/buzzer` | Servidor/Web → ESP32 | "ON" o "OFF" |
| `navichair/cmd/relevador` | Servidor/Web → ESP32 | "ON" o "OFF" |

---

## Instalación y ejecución

### 1. Dependencias del servidor Python

```bash
pip install paho-mqtt opencv-python firebase-admin numpy
```

### 2. Instalar y ejecutar Mosquitto (broker MQTT)

**Windows:**
1. Descargar desde https://mosquitto.org/download/
2. Ejecutar: `mosquitto -v`

**Linux/Mac:**
```bash
sudo apt install mosquitto mosquitto-clients   # Ubuntu/Debian
mosquitto -v
```

### 3. Configurar Firebase

1. Crear proyecto en https://console.firebase.google.com
2. Activar **Realtime Database**
3. Ir a **Project Settings → Service Accounts → Generate new private key**
4. Guardar el archivo JSON como `servidor/credencial_firebase.json`
5. Copiar la URL de la base de datos y pegarla en `firebase_logger.py`

### 4. Configurar la interfaz web

Abrir `interfaz/index.html` y reemplazar los valores de `configuracionFirebase` con los de tu proyecto Firebase Console → Project Settings → Your apps → Web app.

### 5. Flashear la ESP32

1. Instalar Thonny o uPyCraft
2. Instalar MicroPython en la ESP32
3. Subir `esp32/dispositivos.py` y `esp32/main.py` al dispositivo
4. Verificar que los pines en `dispositivos.py` coincidan con tu conexión física

### 6. Ejecutar el servidor

Abrir tres terminales distintas:

```bash
# Terminal 1 — Puente MQTT
python servidor/mqtt_bridge.py

# Terminal 2 — Pipeline IA
python servidor/ia_processor.py

# Terminal 3 — Logger Firebase
python servidor/firebase_logger.py
```

### 7. Probar la IA sin hardware (prueba estática requerida por E3)

```bash
python servidor/ia_processor.py --prueba
```

---

## Conexiones de hardware (pines ESP32)

| Componente | Pin TRIG/SCL/Signal | Pin ECHO/SDA |
|---|---|---|
| HC-SR04 Izquierda | GPIO 5 (TRIG) | GPIO 18 (ECHO) |
| HC-SR04 Centro | GPIO 19 (TRIG) | GPIO 21 (ECHO) |
| HC-SR04 Derecha | GPIO 22 (TRIG) | GPIO 23 (ECHO) |
| MPU-6050 (I2C) | GPIO 25 (SCL) | GPIO 26 (SDA) |
| PIR | GPIO 27 | — |
| Buzzer | GPIO 13 | — |
| OLED (I2C) | GPIO 22 (SCL) | GPIO 21 (SDA) |
| Relevador | GPIO 14 | — |

> ⚠️ Nota: Los pines SCL/SDA del OLED y los pines TRIG/ECHO del HC-SR04 central comparten números en el mapeo. Ajusta los pines en `dispositivos.py` según tu conexión física real para evitar conflictos.

---

## Modelo de IA

- **Librería:** OpenCV 4.x (incluida en `pip install opencv-python`)
- **Modelo:** Haar Cascade — `haarcascade_fullbody.xml` (incluido en OpenCV, sin descarga adicional)
- **Precisión aproximada:** 70-85% en condiciones de buena iluminación
- **Tipo de predicción:** Detección de presencia de personas en el campo visual de la silla
- **Latencia:** 50-150 ms por fotograma en CPU estándar

---

## Eventos registrados en Firebase

| Tipo | Nodo Firebase | Descripción |
|---|---|---|
| `telemetria` | `/telemetria` | Lecturas periódicas de todos los sensores |
| `alerta` | `/alertas` | Obstáculo, inclinación o inmovilidad detectados |
| `resultado_ia` | `/resultados_ia` | Detecciones del modelo de visión artificial |
| Estado actual | `/estado_actual` | Última lectura (sobreescrita en cada ciclo) |
| Comandos | `/comandos` | Escritura del dashboard → leída por firebase_logger.py |
