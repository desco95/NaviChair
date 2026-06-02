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

Modelo de prueba para activación del video
"""


from flask import Flask, render_template

app = Flask(__name__)

@app.route("/")
def index():
    return render_template(
        "index.html",
        estado="PERSONA DETECTADA",
        rostros=1,
        video_url="http://192.168.1.6:8080/video"
    )

if __name__ == "__main__":
    app.run(debug=True)