# ELDERCARE
hii ! this is a project i did for my summer nit internship 

#title :Wearable emergency monitoring system for elderly people. Real-time heart rate monitoring and fall detection using ESP32, MAX30102 and MPU6050 sensors, with a Flask web dashboard and automated family alerts.

#aim: I am using this project to fimaliar myself with hardware/IoT tech 
tech stack : 
front end:HTML/CSS/JS
backend:Python + Flask

Hardware:
ESP32 DevKit (WiFi + BT, dual-core, main microcontroller)
MAX30102 (heart rate / SpO2 sensor, I2C)
MPU6050 (accelerometer/gyroscope for fall detection, I2C)
Breadboard prototype (moving to perfboard + LiPo battery + enclosure for the final wearable)

Firmware (ESP32 side):
Arduino C++ (via Arduino IDE)
Libraries: SparkFun MAX3010x Pulse and Proximity Sensor Library, Adafruit MPU6050 + Adafruit Unified Sensor, ArduinoJson, WiFi.h, HTTPClient.h, Wire.h
Posts sensor JSON payloads over Wi-Fi to the Flask server once per second
