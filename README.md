# IoT-Based Home Energy Monitoring and Alert System

![Python](https://img.shields.io/badge/Python-3.9+-blue.svg)
![C++](https://img.shields.io/badge/C++-ESP32-green.svg)
![Docker](https://img.shields.io/badge/Docker-Containerized-blue.svg)

> **Awarded 4th Prize at the FICT FYP Competition (May 2026)**

An end-to-end, industrial-grade IoT and AI solution for real-time residential power tracking. This project transforms a standard ESP32 into an intelligent energy advisor that not only monitors usage but understands human behavior patterns using Machine Learning to detect anomalies and calculate environmental impact.

---

## 📖 Table of Contents
- [Project Overview](#project-overview)
- [System Architecture](#system-architecture)
- [Key Features](#key-features)
- [Hardware Requirements](#hardware-requirements)
- [Software Setup](#software-setup)
- [Machine Learning & Anomaly Detection](#machine-learning--anomaly-detection)
- [The Malaysian Context (July 2025 Tariff)](#the-malaysian-context)
- [Interactive UI (Telegram Bot)](#interactive-ui)

---

## Project Overview
Traditional energy monitors provide raw data but lack context. This system bridges that gap by establishing a **contextual baseline**. It learns when you are typically awake, when you cook, and when you sleep. 

- **Non-invasive Sensing:** Uses clamp-on sensors (no electrical rewiring needed).
- **Financial Accuracy:** Real-time billing based on the latest Malaysian July 2025 tiered tariffs.
- **Sustainability:** Automated carbon footprint and "tree offset" calculations.
- **Proactive Security:** AI-driven Telegram alerts for unusual spikes (potential electrical faults or appliances left on).

---

## System Architecture
The data follows a robust "Hardware-to-Cloud-to-User" loop:
1. **Edge Node (ESP32):** Captures AC signals via CT sensor $\rightarrow$ 16-bit ADC conversion $\rightarrow$ Local True RMS calculation.
2. **Data Ingestion:** Telemetry is published via **MQTT** (Mosquitto).
3. **Storage & Processing:** **Telegraf** structured data ingestion into **InfluxDB** (Time-series database).
4. **Intelligence Engine:** A **Python-based AI Engine** performs real-time inference and handles the Telegram Bot logic.
5. **Visualization:** **Grafana** renders high-density historical dashboards.

---

## Key Features
- **Dual-Core Processing:** Math-heavy RMS sampling is isolated on ESP32 Core 0, while network tasks run on Core 1 to prevent system crashes.
- **NVS Data Persistence:** Internal "Energy Odometer" saves state to flash memory every 15 seconds to ensure data survives power reboots.
- **Wireless Diagnostics:** Headless monitoring via **WebSerial Lite** and **mDNS** (`EnergyMonitor-ESP32.local`).
- **Self-Adapting AI:** A Random Forest Regressor that retrains itself every 7 days to adapt to changing household habits.
- **On-Demand Audits:** Interactive Telegram bot with an **Inline Calendar UI** for custom date-range reporting.

---

## Hardware Requirements
### Components
- **Microcontroller:** ESP32 (30-pin, Type-C)
- **Sensor:** SCT-013-000 (100A/1V) Non-invasive CT Clamp
- **ADC:** ADS1115 (16-bit resolution for precision)
- **Conditioning:** 2x 10kΩ resistors + 1x 10µF capacitor (1.65V DC Bias Circuit)
- **Test Trigger:** Tactile Push Button (For manual anomaly simulation)

---

## Software Setup

### 1. Backend (Docker)
Ensure Docker Desktop is running. This launches the TIG stack (Telegraf, InfluxDB, Grafana) and Mosquitto.
```bash
cd backend
docker-compose up -d
```
- **Grafana:** `http://localhost:3001` (User: `admin`, Pass: `admin`)
- **InfluxDB:** `http://localhost:8086`

### 2. Firmware (ESP32)
1. Open `firmware/HomeEnergyMonitor.ino` in Arduino IDE.
2. Update your WiFi credentials and your laptop's **IPv4 Address** in the code.
3. Upload to the ESP32. Access logs wirelessly at `http://[ESP32_IP]/webserial`.

### 3. Intelligence Bot (Python)
Install dependencies and run the AI engine:
```bash
cd intelligence_bot
pip install pandas scikit-learn python-telegram-bot influxdb-client paho-mqtt requests pytz
python telegram_bot.py
```

---

## Machine Learning & Anomaly Detection
The system uses a **Random Forest Regressor** to predict the "Expected Power" based on the current time and day.
- **Features:** `hour`, `day_of_week`, `minute_of_day`.
- **Dynamic Thresholding:** The model calculates a baseline. If `Actual Power > Expected + (15 * σ) + 50% buffer`, a Telegram alert is sent.
- **Online Learning:** The bot includes a **"🤖 Force AI Retraining"** button to allow the user to update the model immediately after lifestyle changes.

---

## The Malaysian Context
Optimized for the **TNB Domestic Tariff (Restructured July 1, 2025)**.
The algorithm accounts for:
- **Generation/Network/Retail** itemized charges.
- **RE Fund (KWTBB):** 1.6% (waived if $\le$ 300kWh).
- **EE Incentive Rebate:** -RM0.105/kWh (applied if $\le$ 1000kWh).
- **Service Tax (8%):** Applied if usage > 600kWh.

---

## Interactive UI
The Telegram Bot provides:
1. **Live Snapshots:** High-resolution PNGs of Grafana panels.
2. **Interactive Calendar:** Select any date range for a specific audit.
3. **Smart Audit:** Instant calculation of **Carbon Footprint** and **Trees needed to offset** usage.

---
**Developed by Ivan Ling**  
*Final Year Project - Faculty of Information and Communication Technology (FICT), UTAR.*
