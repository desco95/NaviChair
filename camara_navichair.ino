// =============================================================================
// PROYECTO: NaviChair — Módulo de Cámara ESP32-CAM
// ARCHIVO: camara_navichair.ino
// DESCRIPCIÓN: Captura imágenes con el sensor OV2640, las codifica en
//              Base64 y las publica vía MQTT en navichair/camara para
//              que el servidor Python las procese con el modelo de IA.
// INTEGRANTES:
//   - Diana Carolina Plascencia Rodríguez
//   - María Aurora Rodríguez López
//   - Escobedo Ojeda Luis David
//   - Quintero Frausto Valeria Melissa Leilani
// =============================================================================

#include "esp_camera.h"
#include <WiFi.h>
#include <PubSubClient.h>
#include "Base64.h"

// -----------------------------------------------------------------------
// CONFIGURACIÓN DE RED Y MQTT
// -----------------------------------------------------------------------
const char* SSID_WIFI     = "iPhone David";
const char* CLAVE_WIFI    = "huevitos";
const char* BROKER_MQTT   = "172.20.10.3";
const int   PUERTO_MQTT   = 1883;
const char* ID_CLIENTE    = "navichair_espcam";
const char* TOPICO_CAMARA = "navichair/camara";

// -----------------------------------------------------------------------
// PINES AI THINKER ESP32-CAM — no cambiar
// -----------------------------------------------------------------------
#define PWDN_GPIO_NUM     32
#define RESET_GPIO_NUM    -1
#define XCLK_GPIO_NUM      0
#define SIOD_GPIO_NUM     26
#define SIOC_GPIO_NUM     27
#define Y9_GPIO_NUM       35
#define Y8_GPIO_NUM       34
#define Y7_GPIO_NUM       39
#define Y6_GPIO_NUM       36
#define Y5_GPIO_NUM       21
#define Y4_GPIO_NUM       19
#define Y3_GPIO_NUM       18
#define Y2_GPIO_NUM        5
#define VSYNC_GPIO_NUM    25
#define HREF_GPIO_NUM     23
#define PCLK_GPIO_NUM     22

WiFiClient   clienteWifi;
PubSubClient clienteMQTT(clienteWifi);

// -----------------------------------------------------------------------
// INICIALIZAR CÁMARA
// -----------------------------------------------------------------------
void configurarCamara() {
  camera_config_t config;
  config.ledc_channel = LEDC_CHANNEL_0;
  config.ledc_timer   = LEDC_TIMER_0;
  config.pin_d0 = Y2_GPIO_NUM;
  config.pin_d1 = Y3_GPIO_NUM;
  config.pin_d2 = Y4_GPIO_NUM;
  config.pin_d3 = Y5_GPIO_NUM;
  config.pin_d4 = Y6_GPIO_NUM;
  config.pin_d5 = Y7_GPIO_NUM;
  config.pin_d6 = Y8_GPIO_NUM;
  config.pin_d7 = Y9_GPIO_NUM;
  config.pin_xclk     = XCLK_GPIO_NUM;
  config.pin_pclk     = PCLK_GPIO_NUM;
  config.pin_vsync    = VSYNC_GPIO_NUM;
  config.pin_href     = HREF_GPIO_NUM;
  config.pin_sscb_sda = SIOD_GPIO_NUM;
  config.pin_sscb_scl = SIOC_GPIO_NUM;
  config.pin_pwdn     = PWDN_GPIO_NUM;
  config.pin_reset    = RESET_GPIO_NUM;
  config.xclk_freq_hz = 20000000;
  config.pixel_format = PIXFORMAT_JPEG;
  config.frame_size   = FRAMESIZE_QQVGA; // CORREGIDO: 160x120 (antes QVGA 320x240)
  config.jpeg_quality = 10;              // CORREGIDO: más compresión (antes 15)
  config.fb_count     = 1;

  if (esp_camera_init(&config) != ESP_OK) {
    Serial.println("ERROR: No se pudo iniciar la camara.");
    return;
  }
  Serial.println("Camara OV2640 inicializada — QQVGA JPEG");
}

// -----------------------------------------------------------------------
// CONECTAR WIFI
// -----------------------------------------------------------------------
void conectarWifi() {
  WiFi.begin(SSID_WIFI, CLAVE_WIFI);
  Serial.print("Conectando a WiFi");
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println("\nWiFi conectado: " + WiFi.localIP().toString());
}

// -----------------------------------------------------------------------
// CONECTAR MQTT
// -----------------------------------------------------------------------
void conectarMQTT() {
  while (!clienteMQTT.connected()) {
    Serial.print("Conectando a MQTT...");
    if (clienteMQTT.connect(ID_CLIENTE)) {
      Serial.println("conectado.");
    } else {
      Serial.print("fallo rc=");
      Serial.print(clienteMQTT.state());
      Serial.println(" reintentando en 3s");
      delay(3000);
    }
  }
}

// -----------------------------------------------------------------------
// SETUP
// -----------------------------------------------------------------------
void setup() {
  Serial.begin(115200);
  configurarCamara();
  conectarWifi();
  clienteMQTT.setServer(BROKER_MQTT, PUERTO_MQTT);
  clienteMQTT.setBufferSize(150000); // CORREGIDO: 100KB (antes 30000)
  conectarMQTT();
  Serial.println("NaviChair CAM lista. Transmitiendo...");
}

// -----------------------------------------------------------------------
// LOOP — captura y publica cada 500ms (~2 fps)
// -----------------------------------------------------------------------
void loop() {
  if (!clienteMQTT.connected()) conectarMQTT();
  clienteMQTT.loop();

  camera_fb_t* fotograma = esp_camera_fb_get();
  if (!fotograma) {
    Serial.println("Error al capturar imagen.");
    delay(500);
    return;
  }

  // Codificar a Base64
  String imagenB64 = base64::encode(fotograma->buf, fotograma->len);
  esp_camera_fb_return(fotograma);

  // Publicar en MQTT
  bool ok = clienteMQTT.publish(
    TOPICO_CAMARA,
    (uint8_t*)imagenB64.c_str(),
    imagenB64.length()
  );

  if (ok) Serial.printf("Frame publicado — %d bytes\n", imagenB64.length());
  else    Serial.println("Error al publicar. Verifica buffer o conexion.");

  delay(500); // CORREGIDO: 500ms (antes 350ms) para dar más tiempo al broker
}
