# IoT-Based Home Energy Monitoring and Alert System

![Python](https://img.shields.io/badge/Python-3.9+-blue.svg)
![C++](https://img.shields.io/badge/C++-ESP32-green.svg)
![Docker](https://img.shields.io/badge/Docker-Containerized-blue.svg)

An open-source, AI-driven IoT solution that empowers homeowners with real-time energy insights, a dynamic Grafana dashboard, and proactive anomaly detection using a Random Forest algorithm and an interactive Telegram Bot.

## Features
* **Edge Processing:** High-precision True RMS calculation and Malaysian Tiered Tariff billing computed locally on an ESP32.
* **Data Persistence:** NVS Energy Odometer prevents data loss during power outages.
* **Intelligent Anomaly Detection:** Context-aware dynamic thresholding ($15\sigma$) using a self-retraining Random Forest Regressor.
* **Interactive UI:** Telegram Bot integration for on-demand Grafana snapshots, carbon auditing, and proactive alerting.
* **Headless Diagnostics:** WebSerial Lite for wireless maintenance.

## System Architecture
*(See `/docs/System_Architecture.png` for the full block diagram)*
The system captures AC signals via an SCT-013 CT sensor, processes them on an ESP32, and publishes telemetry via MQTT. A Dockerized TIG stack (Telegraf, InfluxDB, Grafana) handles storage and visualization, while a Python AI engine conducts real-time inference and bot management.

## Quick Start Setup
1. **Backend:** Navigate to `/backend` and run `docker-compose up -d`.
2. **Hardware:** Wire the components as per `/hardware/schematic.png`. Rename `config.h.example` to `config.h` in the `/firmware` folder, enter your WiFi credentials, and flash the ESP32.
3. **AI & Bot:** Navigate to `/intelligence_bot`. Copy `.env.example` to `.env` and fill in your API keys. Run `pip install -r requirements.txt`, then start the engine with `python bot.py`.
