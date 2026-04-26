# Hardware Bill of Materials (BOM)

| Component | Specification / Details | Purpose |
| :--- | :--- | :--- |
| **Microcontroller** | ESP32 (DoIt DevKit V1, 30-pin) | Edge processing, WiFi, MQTT |
| **Current Sensor** | YHDC SCT-013-000 (100A/50mA) | Non-invasive AC line monitoring |
| **ADC** | Adafruit ADS1115 (16-bit) | High-precision analog to digital conversion |
| **Audio Jack** | CJMCU-TRRS 3.5mm Breakout | Secure connection for the CT sensor |
| **Resistors** | 10 kΩ (x2) | Creates the 1.65V DC voltage divider |
| **Capacitor** | 10 µF Electrolytic | Smooths the reference voltage |
| **Power Supply** | 5V / 3A Standalone DC Adapter | Ensures 24/7 reliability |