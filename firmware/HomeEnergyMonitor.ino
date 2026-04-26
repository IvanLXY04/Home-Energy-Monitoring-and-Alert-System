// =================================================================
//     IoT-Based Home Energy Monitoring and Alert System
// =================================================================

// --- BLYNK AND DEVICE CREDENTIALS ---
#define BLYNK_TEMPLATE_ID "blynk_template_ID"           //replace with your own
#define BLYNK_TEMPLATE_NAME "Home Energy Monitoring"
#define BLYNK_AUTH_TOKEN "blynk_auth_token"		//replace with your own

// --- LIBRARIES ---
#include <ESPmDNS.h>
#include <Wire.h>
#include <Adafruit_ADS1X15.h>
#include <WiFi.h>
#include <BlynkSimpleEsp32.h>
#include <PubSubClient.h>
#include <Preferences.h>
#include <WiFiClientSecure.h>      // TELEGRAM: Required for secure HTTPS connections
#include <UniversalTelegramBot.h> // TELEGRAM: The main bot library
#include <AsyncTCP.h>              // NEW: Required for WebSerial
#include <ESPAsyncWebServer.h>     // NEW: Required for WebSerial
#include <WebSerial.h>             // NEW: WebSerial Library for Browser Monitoring

// --- HARDWARE PINOUT ---
const int SDA_PIN = 21;
const int SCL_PIN = 22;
const int ANOMALY_BUTTON_PIN = 18; // ANOMALY: Pin for the manual test button

// --- WIFI CREDENTIALS ---
char ssid[] = "wifi_ssid";	//replace with your own
char pass[] = "wifi_password";  //replace with your own

// --- MQTT BROKER CONFIGURATION ---
const char* mqtt_server_ip = "wifi_ip";   //replace with your own
(ipv4 during FYP2)
const int mqtt_port = mqtt_port;	  //replace with your own
const char* mqtt_topic = "mqtt_topic";    //replace with your own

// --- TELEGRAM BOT CONFIGURATION ---
#define TELEGRAM_BOT_TOKEN "telegram_bot_token" //replace with your own
String telegramChatId = "telegramChatId";       //replace with your own

// --- ADC & CT SENSOR CONFIGURATION ---
Adafruit_ADS1115 ads;
const float ADC_VOLTS_PER_BIT = 2.048 / 32767.0;
const float CT_AMPS_PER_VOLT = 100.0;

// --- CALIBRATION & PROJECT SETTINGS ---
const float CALIBRATION_FACTOR = 1.350;
const float MAINS_VOLTAGE = 230.0;
const float POWER_FACTOR = 0.85;      // Average Home Power Factor for Inductive Loads 
const long SEND_INTERVAL_MS = 5000;
const float ANOMALY_THRESHOLD_W = 4500.0; // Increased for whole home monitoring (prevents false alerts)
//const long ALERT_COOLDOWN_MS = 300000;    // TELEGRAM: Cooldown in ms (300,000 = 5 minutes) to prevent spamming alerts
const long ALERT_COOLDOWN_MS = 15000;  

// --- NVS: Non-Volatile Storage ---
Preferences preferences;
const char* NVS_KEY = "totalKWh";      // Key to store our energy value
long readingsCounter = 0;              // Counter to track when to save data
//const int SAVE_EVERY_N_READINGS = 30;  // Save data every 30 readings (~2.5 minutes)
const int SAVE_EVERY_N_READINGS = 5;  // Save data every 5 readings

// --- GLOBAL VARIABLES ---
double totalKWh = 0;
double totalCost = 0;
unsigned long lastAlertTime = 0; // TELEGRAM: Timestamp for the last alert sent

// --- CLIENTS ---
BlynkTimer timer;
WiFiClient espClient;
PubSubClient mqttClient(espClient);
WiFiClientSecure secured_client;            // TELEGRAM: Secure client for HTTPS
UniversalTelegramBot bot(TELEGRAM_BOT_TOKEN, secured_client); // TELEGRAM: Bot object
AsyncWebServer server(80);                  // Server for WebSerial on Port 80

// =================================================================
//                         TIERED COST FUNCTION
// =================================================================
/**
 * @brief Calculates cost based on the July 2025 TNB Structure
 * RE Fund (1.6%) applied ONLY if usage > 300 kWh.
 */
double calculateTieredCost(double kwh) {
  // 1. Base Rates (Generation + Network)
  double energyRate = (kwh <= 1500.0) ? 0.2703 : 0.3703;
  double capacityRate = 0.0455;
  double networkRate = 0.1285;
  
  double totalVariableRate = energyRate + capacityRate + networkRate;
  double billAmount = kwh * totalVariableRate;

  // 2. Automatic Fuel Adjustment (AFA) & Retail Charge
  // Waived/Not applicable if <= 600 kWh
  if (kwh > 600.0) {
    billAmount += (kwh * -0.027); // AFA Rate based on your screenshot
    billAmount += 10.00;          // Retail Charge
  }

  // 3. Energy Efficiency Incentive (Rebate)
  // Rebate if total consumption <= 1,000 kWh
  if (kwh <= 1000.0) {
    billAmount -= (kwh * 0.1050);
  }

  // 4. RE Fund (KWTBB) - 1.6%
  // Applies to total bill EXCEPT if consumption is 300 kWh and below
  if (kwh > 300.0) {
    billAmount += (billAmount * 0.016);
  }

  // 5. Service Tax (SST) - 8%
  // Applies only if usage > 600 kWh
  if (kwh > 600.0) {
    billAmount += (billAmount * 0.08);
  }

  // Minimum bill is RM 3.00
  if (billAmount > 0 && billAmount < 3.00) billAmount = 3.00;

  return billAmount;
}

// --- MQTT RECONNECT FUNCTION ---
void reconnectMQTT() {
  while (!mqttClient.connected()) {
    Serial.print("Attempting MQTT connection...");
    String clientId = "ESP32Client-" + String(random(0xffff), HEX);
    if (mqttClient.connect(clientId.c_str())) {
      Serial.println("connected");
      WebSerial.println("MQTT Connected to Backend."); // NEW: Log to browser
    } else {
      Serial.print("failed, rc="); Serial.print(mqttClient.state()); Serial.println(" try again in 5 seconds");
      delay(5000);
    }
  }
}

// --- SETUP ---
void setup() {
  Serial.begin(115200);
  Serial.println("\n\n--- Booting Home Energy Monitor (Robust Version) ---");

  // ANOMALY: Initialize the button pin with an internal pull-up resistor.
  pinMode(ANOMALY_BUTTON_PIN, INPUT_PULLUP);
  Wire.begin(SDA_PIN, SCL_PIN);
  ads.setGain(GAIN_TWO);
  if (!ads.begin()) {
    Serial.println("FATAL: Failed to initialize ADS1115. Check I2C wiring. Halting.");
    while (1);
  } else {
    Serial.println("ADS1115 Initialized Successfully!");
  }

  preferences.begin("energy-monitor", false);
  totalKWh = preferences.getDouble(NVS_KEY, 0.0);

  Serial.print("Connecting to WiFi...");
  WiFi.begin(ssid, pass);
  while (WiFi.status() != WL_CONNECTED) {
    delay(500); Serial.print(".");
  }
  Serial.println("\nWiFi connected!");

    // --- mDNS ---
  if (!MDNS.begin("EnergyMonitor-ESP32")) {
    Serial.println("Error setting up MDNS responder!");
  } else {
    Serial.println("mDNS responder started: EnergyMonitor-ESP32.local");
  }

  // WebSerial Browser Monitor
  WebSerial.begin(&server);
  server.begin();  

  WebSerial.print("NVS Load Successful. Last known energy: ");
  WebSerial.println(totalKWh, 5);
  
  Serial.print("Loaded last known energy value: ");
  Serial.println(totalKWh, 5);

  // Add mDNS service for HTTP (so browsers find it easier)
  MDNS.addService("http", "tcp", 80);

  // TELEGRAM: Necessary for ESP32 to verify Telegram's servers
  //secured_client.setCACert(TELEGRAM_CERTIFICATE_ROOT);
  // NEW: SSL Security Fix for Telegram (Ensures messages aren't blocked)
  secured_client.setInsecure(); 

  Blynk.config(BLYNK_AUTH_TOKEN);
  mqttClient.setServer(mqtt_server_ip, mqtt_port);

  timer.setInterval(SEND_INTERVAL_MS, sendData);

  bot.sendMessage(telegramChatId, "Energy Monitoring System Online!", ""); // NEW: Boot notification
}

// --- LOOP ---
void loop() {
  Blynk.run();
  if (!mqttClient.connected()) {
    reconnectMQTT();
  }
  mqttClient.loop();
  timer.run();
}

// --- CUSTOM FUNCTIONS ---
float calculateIrms(int samples) {
  double sum_of_squares = 0;
  long sum_of_samples = 0;
  for (int i = 0; i < samples; i++) {
    int16_t sample = ads.readADC_SingleEnded(0);
    sum_of_samples += sample;
    sum_of_squares += (double)sample * sample;
  }

  // Use the statistical RMS formula to automatically remove the DC bias
  double avg_of_samples = (double)sum_of_samples / samples;
  double avg_of_squares = sum_of_squares / samples;
  double rms_adc_squared = avg_of_squares - (avg_of_samples * avg_of_samples);
  double rms_adc = sqrt(rms_adc_squared);

  // Convert the pure AC RMS ADC reading into an RMS voltage
  double rms_voltage = rms_adc * ADC_VOLTS_PER_BIT;

  // Convert the RMS voltage into the actual RMS current using the CT sensor's ratio
  double rms_current = rms_voltage * CT_AMPS_PER_VOLT * CALIBRATION_FACTOR;

  // Simple noise filter: if the calculated current is very low, just treat it as zero.
  // This prevents tiny fluctuations from showing up as power usage.
  if (rms_current < 0.05) return 0.0;
  return (float)rms_current;
}

void sendData() {
  float currentRMS = calculateIrms(1000);

  // The Safety Gate (Sanity Check) ---
  // If current is over 90A, it is physically impossible for a 32A home switch.
  // This detects if the sensor is unplugged/floating and prevents a system crash.
  if (currentRMS > 90.0 || isnan(currentRMS)) {
    Serial.println("!! CRITICAL: SENSOR FLOATING OR UNPLUGGED - DATA DROPPED !!");
    WebSerial.println("!! SENSOR FAULT: Floating Input Detected. Data Dropped. !!");
    return; // Exit the function immediately. Do not process MQTT, Blynk, or Alerts.
  }
  // --------------------------------------------

  // ANOMALY: Check if the test button is pressed.
  if (digitalRead(ANOMALY_BUTTON_PIN) == LOW) {
    Serial.println(">>> ANOMALY BUTTON PRESSED! Injecting fake current spike.");
    WebSerial.println("!!! ANOMALY BUTTON PRESSED !!!"); // NEW: Log to browser
    currentRMS += 30.0;     // Add a large amount of fake current to simulate a massive surge.
  }

  float power = currentRMS * MAINS_VOLTAGE * POWER_FACTOR;
  
  double intervalInHours = SEND_INTERVAL_MS / 3600000.0;
  double kWhInInterval = (power * intervalInHours) / 1000.0;
  totalKWh += kWhInInterval;
  // Call the new tiered cost function instead of simple multiplication
  totalCost = calculateTieredCost(totalKWh);
  
  // TELEGRAM: Check for anomaly and send alert if needed
  if (power > ANOMALY_THRESHOLD_W) {
    // Check if cooldown period has passed to prevent spam
    if (millis() - lastAlertTime > ALERT_COOLDOWN_MS || lastAlertTime == 0) {
      String message = "⚠️ *Home High Power Alert!* ⚠️\n\n";
      message += "Usage has exceeded " + String(ANOMALY_THRESHOLD_W, 0) + "W\n";
      message += "*Current Usage:* " + String(power, 1) + " W";
      if (bot.sendMessage(telegramChatId, message, "Markdown")) {
         WebSerial.println(">> Telegram Alert Sent.");
      }
      Serial.println(">>> SENT TELEGRAM ALERT!");
      lastAlertTime = millis();
    }
  }

  char jsonPayload[200];
  snprintf(jsonPayload, 200, 
    "{\"current\":%.3f,\"power\":%.2f,\"totalKWh\":%.5f,\"totalCost\":%.2f,\"energy_interval_kwh\":%.8f}", 
    currentRMS, power, totalKWh, totalCost, kWhInInterval);
  mqttClient.publish(mqtt_topic, jsonPayload);

  Serial.printf("P: %.1f W | I: %.3f A | Total Energy: %.5f kWh | Total Cost: RM %.2f\n", power, currentRMS, totalKWh, totalCost);
  WebSerial.printf("P: %.1f W | I: %.3f A | Total Energy: %.5f kWh | Total Cost: RM %.2f\n", power, currentRMS, totalKWh, totalCost);

  Blynk.virtualWrite(V0, MAINS_VOLTAGE);
  Blynk.virtualWrite(V1, currentRMS);
  Blynk.virtualWrite(V2, power);
  Blynk.virtualWrite(V3, totalKWh);
  Blynk.virtualWrite(V4, totalCost);
  
  readingsCounter++;
  if (readingsCounter >= SAVE_EVERY_N_READINGS) {
    readingsCounter = 0;
    preferences.putDouble(NVS_KEY, totalKWh);
    Serial.println(">>> Saved accumulated energy to flash memory.");
    WebSerial.println(">> Data backed up to NVS."); 
  }
}