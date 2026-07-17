/*
 * ============================================================================
 *  ElderCare Guardian  --  ESP32 Wearable Firmware
 * ============================================================================
 *
 *  Reads heart rate (MAX30102) and motion (MPU6050), then POSTs the readings
 *  to the ElderCare Guardian Flask server once per second over Wi-Fi.
 *
 *  HARDWARE WIRING (both sensors share the ESP32 I2C bus)
 *  ----------------------------------------------------------------------------
 *    MAX30102 / MPU6050      ESP32
 *      VIN / VCC      <-->     3V3        (do NOT use 5V on these breakouts)
 *      GND            <-->     GND
 *      SDA            <-->     GPIO 21    (default I2C SDA)
 *      SCL            <-->     GPIO 22    (default I2C SCL)
 *
 *    Both breakouts have different I2C addresses (MAX30102 = 0x57,
 *    MPU6050 = 0x68), so they coexist happily on the same two pins.
 *
 *  REQUIRED ARDUINO LIBRARIES (Library Manager -> Install)
 *  ----------------------------------------------------------------------------
 *    - "SparkFun MAX3010x Pulse and Proximity Sensor Library"  (heart rate)
 *    - "Adafruit MPU6050"  +  "Adafruit Unified Sensor"        (accelerometer)
 *    - ArduinoJson                                             (build payload)
 *    WiFi.h / HTTPClient.h / Wire.h ship with the ESP32 core.
 *
 *  BOARD SETUP
 *    Install the "esp32" boards package (Espressif). Select your board
 *    (e.g. "ESP32 Dev Module"), set the correct port, and flash.
 *
 *  CONFIGURE: set WIFI_SSID, WIFI_PASS and SERVER_URL below before flashing.
 *
 *  NOTE: A MicroPython port is entirely possible (urequests + a MAX30102
 *  driver), but the Arduino C++ libraries above give far more reliable,
 *  battle-tested beat detection out of the box, so we use them here.
 *
 *  This is a student/prototype project -- NOT a certified medical device.
 * ============================================================================
 */

#include <Wire.h>
#include <WiFi.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>

#include "MAX30105.h"          // SparkFun MAX3010x library (works for MAX30102)
#include "heartRate.h"         // SparkFun beat-detection helper
#include <Adafruit_MPU6050.h>
#include <Adafruit_Sensor.h>

// ------------------------- USER CONFIGURATION -------------------------------
const char* WIFI_SSID = "YOUR_WIFI_NAME";
const char* WIFI_PASS = "YOUR_WIFI_PASSWORD";

// The address of the machine running app.py. Use its LAN IP, not localhost,
// because the ESP32 reaches the server across the network.
//   e.g. "http://192.168.1.50:5000/api/sensor-data"
const char* SERVER_URL = "http://192.168.1.50:5000/api/sensor-data";

// Must match a patient/device record on the server (see config.DEFAULT_PATIENT).
const char* DEVICE_ID = "eldercare-001";

const unsigned long POST_INTERVAL_MS = 1000;   // send ~1 reading / second
// ----------------------------------------------------------------------------

MAX30105 particleSensor;
Adafruit_MPU6050 mpu;

// ---- Heart-rate beat detection state (SparkFun rolling-average pattern) ----
const byte RATE_SIZE = 8;          // averaging window for a smoother BPM
byte  rates[RATE_SIZE];            // ring buffer of recent BPM values
byte  rateSpot = 0;
long  lastBeat = 0;                // millis() of the previous detected beat
float beatsPerMinute = 0;
int   beatAvg = 0;

// ---- On-device fall pre-check thresholds (server makes the real decision) ---
const float FREEFALL_G = 0.45;     // magnitude dips toward 0 g in free-fall
const float IMPACT_G   = 2.60;     // then spikes on impact
bool  sawFreefall = false;
unsigned long freefallAt = 0;

unsigned long lastPost = 0;

// ----------------------------------------------------------------------------
void connectWiFi() {
  Serial.print("Connecting to Wi-Fi");
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  while (WiFi.status() != WL_CONNECTED) {
    delay(400);
    Serial.print(".");
  }
  Serial.print("\nWi-Fi connected. IP: ");
  Serial.println(WiFi.localIP());
}

void setup() {
  Serial.begin(115200);
  delay(200);
  Wire.begin();                    // SDA=21, SCL=22 on most ESP32 dev boards

  // ---- MAX30102 ----
  if (!particleSensor.begin(Wire, I2C_SPEED_FAST)) {
    Serial.println("MAX30102 not found. Check wiring/power (use 3V3).");
    while (1) delay(10);
  }
  particleSensor.setup();                 // sensible defaults
  particleSensor.setPulseAmplitudeRed(0x0A);
  particleSensor.setPulseAmplitudeGreen(0);

  // ---- MPU6050 ----
  if (!mpu.begin()) {
    Serial.println("MPU6050 not found. Check wiring/power (use 3V3).");
    while (1) delay(10);
  }
  mpu.setAccelerometerRange(MPU6050_RANGE_8_G);
  mpu.setGyroRange(MPU6050_RANGE_500_DEG);
  mpu.setFilterBandwidth(MPU6050_BAND_21_HZ);

  connectWiFi();
  Serial.println("ElderCare Guardian wearable ready.");
}

// ----------------------------------------------------------------------------
void loop() {
  // ---------- 1. Heart rate: detect individual beats every loop ----------
  long irValue = particleSensor.getIR();
  if (irValue > 50000) {                    // a finger/wrist is present
    if (checkForBeat(irValue)) {
      long delta = millis() - lastBeat;
      lastBeat = millis();
      beatsPerMinute = 60.0 / (delta / 1000.0);
      if (beatsPerMinute > 20 && beatsPerMinute < 255) {
        rates[rateSpot++] = (byte)beatsPerMinute;
        rateSpot %= RATE_SIZE;
        int total = 0;
        for (byte i = 0; i < RATE_SIZE; i++) total += rates[i];
        beatAvg = total / RATE_SIZE;
      }
    }
  } else {
    beatAvg = 0;                            // no contact -> report 0 (invalid)
  }

  // ---------- 2. Motion: read accelerometer, convert to g, get magnitude ----
  sensors_event_t a, g, temp;
  mpu.getEvent(&a, &g, &temp);
  // Adafruit reports m/s^2; divide by 9.81 to express in g (1 g at rest).
  float ax = a.acceleration.x / 9.81;
  float ay = a.acceleration.y / 9.81;
  float az = a.acceleration.z / 9.81;
  float mag = sqrt(ax * ax + ay * ay + az * az);

  // ---------- 3. Lightweight on-device fall pre-check ----------
  // The server runs the authoritative free-fall -> impact state machine; this
  // just sets a hint flag so a clear impact is flagged even between samples.
  bool fallHint = false;
  if (mag < FREEFALL_G) {
    sawFreefall = true;
    freefallAt = millis();
  }
  if (sawFreefall && mag > IMPACT_G && (millis() - freefallAt) < 1200) {
    fallHint = true;
    sawFreefall = false;
  }
  if (sawFreefall && (millis() - freefallAt) > 1200) {
    sawFreefall = false;                    // window expired, reset
  }

  // ---------- 4. POST to the server on a fixed cadence ----------
  if (millis() - lastPost >= POST_INTERVAL_MS) {
    lastPost = millis();

    if (WiFi.status() != WL_CONNECTED) connectWiFi();

    StaticJsonDocument<256> doc;
    doc["device_id"] = DEVICE_ID;
    doc["heart_rate"] = beatAvg;            // averaged BPM (0 if no contact)
    doc["spo2"] = 0;                        // placeholder; SpO2 calc not wired up
    doc["accel_x"] = ax;
    doc["accel_y"] = ay;
    doc["accel_z"] = az;
    if (fallHint) doc["fall"] = true;       // optional hint; server may override

    String body;
    serializeJson(doc, body);

    HTTPClient http;
    http.begin(SERVER_URL);
    http.addHeader("Content-Type", "application/json");
    int code = http.POST(body);
    Serial.printf("POST %s -> HTTP %d  (bpm=%d mag=%.2f%s)\n",
                  SERVER_URL, code, beatAvg, mag, fallHint ? " FALL" : "");
    http.end();
  }

  delay(20);   // ~50 Hz sampling loop for responsive beat + impact detection
}
