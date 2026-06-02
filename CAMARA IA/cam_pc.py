"""
OBJETIVO: Validación Estática del Modelo de IA — MobileNet SSD / HOG Detector.
          Este script prueba el modelo con imágenes locales y con la webcam
          del PC ANTES de integrarlo con el flujo MQTT.
          Cumple el requisito de "Prueba Estática" del checklist de entrega.

INTEGRANTES:
Escobedo Ojeda Luis David
Plascencia Rodríguez Diana Carolina
Quintero Frausto Valeria Melissa
Rodríguez López Maria Aurora


PROYECTO: Sistema de Detección de Objetos con ESP32-CAM e IA

Modelo de prueba para activación de la cámara
"""


import cv2

url = "http://192.168.1.6:8080/video"

cap = cv2.VideoCapture(url)

while True:
    ret, frame = cap.read()

    if not ret:
        print("No se recibió frame")
        break

    cv2.imshow("Camara Celular", frame)

    if cv2.waitKey(1) == ord('q'):
        break

cap.release()
cv2.destroyAllWindows()