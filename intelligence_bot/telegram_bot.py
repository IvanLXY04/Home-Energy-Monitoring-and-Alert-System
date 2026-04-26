import logging
import requests
import re
import os
import joblib
import pandas as pd
import paho.mqtt.client as mqtt
import asyncio
import time
import calendar  # NEW: For calendar calculations
from datetime import datetime
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler, CallbackQueryHandler
from influxdb_client import InfluxDBClient
from sklearn.ensemble import RandomForestRegressor

# --- CONFIGURE YOUR DETAILS HERE ---
TELEGRAM_BOT_TOKEN = "YOUR_TELEGRAMBOT_TOKEN"
GRAFANA_URL = "YOUR_GRAFANA_URL"
GRAFANA_API_KEY = "YOUR_GRAFANA_API_KEY"
GRAFANA_DASHBOARD_UID = "YOUR_GRAFANA_UID"

# InfluxDB Connection Details
INFLUX_URL = "YOUR_INFLUXDB_URL"
INFLUX_TOKEN = "YOUR_INFLUXDB_TOKEN"
INFLUX_ORG = "my-org"
INFLUX_BUCKET = "home_energy"

# MQTT Broker Configuration (AI Listener)
MQTT_BROKER = "localhost" 
MQTT_TOPIC = "home/energy/power"

# AI Model Files
MODEL_FILE = 'energy_model.pkl'
THRESHOLD_FILE = 'std_dev.txt'

# Malaysian Environmental Factors
MALAYSIA_GRID_EMISSION = 0.674  # kg CO2 per kWh
TREE_ABSORPTION_YEAR = 22.0     # kg CO2 absorbed by one mature tree per year

# Dashboard Panels Mapping
PANELS = {
    "Live Power Reading":       {"id": "1", "range": "5m",  "caption": "The most recent power reading."},
    "Energy This Week":         {"id": "6", "range": "7d",  "caption": "Usage over the last 7 days."},
    "Energy Today (24h)":       {"id": "3", "range": "24h", "caption": "Total energy consumed today."},
    "Cost Today (24h)":         {"id": "4", "range": "24h", "caption": "Estimated cost for today."},
    "Power Graph (6h)":         {"id": "2", "range": "6h",  "caption": "Power usage over the last 6 hours."},
    "Power & Current (6h)":     {"id": "5", "range": "6h",  "caption": "Combined Power and Current (6h)."},
    "Energy This Month (30d)":  {"id": "7", "range": "30d", "caption": "Usage over the last 30 days."},
    "Cost This Month (30d)":    {"id": "9", "range": "30d", "caption": "Estimated cost for the last 30 days."},
    "System Overview":          {"id": "12", "range": "6h",  "caption": "Holistic view of Power, Current, and Cost accumulation."}
}

# Special Buttons
AUDIT_BUTTON = "📊 Smart Energy Audit"
CUSTOM_AUDIT_BUTTON = "📅 Custom Audit Range"
CUSTOM_OVERVIEW_BUTTON = "🖼️ Custom Overview Range" # NEW BUTTON
RETRAIN_BUTTON = "🤖 Force AI Retraining" #force learning

# --- CONVERSATION STATES ---
START_DATE, END_DATE = range(2)

# --- TELEGRAM CHAT ID FOR AI ALERTS ---
# This ensures the AI knows where to send spontaneous anomaly alerts
ALERT_CHAT_ID = "958134833" 

# -----------------------------------

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# --- NEW: CALENDAR GENERATOR HELPER ---
def create_calendar(year=None, month=None):
    now = datetime.now()
    if year is None: year = now.year
    if month is None: month = now.month

    keyboard = []
    # Row 1: Month and Year - MUST BE callback_data
    row = [InlineKeyboardButton(f"{calendar.month_name[month]} {year}", callback_data="ignore")]
    keyboard.append(row)
    
    # Row 2: Days of the week
    row = []
    for day in ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]:
        row.append(InlineKeyboardButton(day, callback_data="ignore"))
    keyboard.append(row)

    # Calendar Rows
    my_calendar = calendar.monthcalendar(year, month)
    for week in my_calendar:
        row = []
        for day in week:
            if day == 0:
                row.append(InlineKeyboardButton(" ", callback_data="ignore"))
            else:
                row.append(InlineKeyboardButton(str(day), callback_data=f"calendar-day-{year}-{month}-{day}"))
        keyboard.append(row)

    # Navigation Row
    row = [
        InlineKeyboardButton("< Prev", callback_data=f"prev-m-{year}-{month}"),
        InlineKeyboardButton("Next >", callback_data=f"next-m-{year}-{month}")
    ]
    keyboard.append(row)
    return InlineKeyboardMarkup(keyboard)
# ---------------------------------------

# --- TIERED COST LOGIC ---
def calculate_malaysian_cost(kwh):
    cost = 0.0
    rem = kwh
    if rem > 0: b = min(rem, 200.0); cost += b * 0.218; rem -= b
    if rem > 0: b = min(rem, 100.0); cost += b * 0.441; rem -= b
    if rem > 0: b = min(rem, 300.0); cost += b * 0.516; rem -= b
    if rem > 0: b = min(rem, 300.0); cost += b * 0.546; rem -= b
    if rem > 0: cost += rem * 0.571
    if kwh > 300: cost += (cost * 0.016) # RE Fund
    if kwh > 600: cost += 10.0; cost += (cost * 0.08) # Retail + SST
    return max(cost, 3.0) if kwh > 0 else 0.0

# --- AI MANAGER: AUTOMATED RETRAINING ---
def retrain_model_auto():
    logger.info("🤖 AI: Starting automated self-adaptation from InfluxDB...")
    try:
        client = InfluxDBClient(url=INFLUX_URL, token=INFLUX_TOKEN, org=INFLUX_ORG)
        query_api = client.query_api()
        query = f'from(bucket: "{INFLUX_BUCKET}") |> range(start: -7d) |> filter(fn: (r) => r._measurement == "mqtt_consumer") |> filter(fn: (r) => r._field == "power") |> pivot(rowKey:["_time"], columnKey: ["_field"], valueColumn: "_value")'
        
        df = query_api.query_data_frame(query)
        client.close()

        if df.empty:
            logger.warning("🤖 AI: No data found for training.")
            return

        df['_time'] = pd.to_datetime(df['_time'])
        df['hour'] = df['_time'].dt.hour
        df['day_of_week'] = df['_time'].dt.weekday
        df['minute_of_day'] = (df['hour'] * 60) + df['_time'].dt.minute

        X = df[['hour', 'day_of_week', 'minute_of_day']]
        y = df['power']
        
        model = RandomForestRegressor(n_estimators=100, random_state=42)
        model.fit(X, y)

        std_dev = (y - model.predict(X)).std()
        joblib.dump(model, MODEL_FILE)
        with open(THRESHOLD_FILE, "w") as f: f.write(str(std_dev))
        logger.info(f"✅ AI: Retraining complete. Current Volatility: {std_dev:.2f}W")
    except Exception as e:
        logger.error(f"❌ AI Training Error: {e}")

# --- AI MANAGER: ANOMALY CHECKER ---
def check_anomaly_ai(current_power):
    if not os.path.exists(MODEL_FILE): return False, 0, 0
    try:
        model = joblib.load(MODEL_FILE)
        with open(THRESHOLD_FILE, "r") as f: std_dev = float(f.read())
        
        now = datetime.now()
        h, d, m = now.hour, now.weekday(), (now.hour * 60) + now.minute
        input_df = pd.DataFrame([[h, d, m]], columns=['hour', 'day_of_week', 'minute_of_day'])
        
        # --- IMPROVED DYNAMIC LOGIC ---
        # We now use a much larger Sigma (15.0) AND a 50% percentage buffer
        # This prevents alerts for small variations like turning on an extra LED bulb.
        expected = model.predict(input_df)[0]
        percentage_buffer = expected * 0.50 
        dynamic_threshold = expected + (15.0 * std_dev) + percentage_buffer
        
        # Logic: Only alert if it's ABOVE the dynamic threshold AND above a safe minimum (200W)
        if current_power > dynamic_threshold and current_power > 200: # Ignore noise below 200W
            return True, expected, dynamic_threshold
        return False, expected, dynamic_threshold
    except:
        return False, 0, 0

# --- AUDIT REPORT GENERATOR ---
def generate_audit_report(start_range="-30d", end_range="now()", is_custom=False):
    try:
        client = InfluxDBClient(url=INFLUX_URL, token=INFLUX_TOKEN, org=INFLUX_ORG)
        query_api = client.query_api()

        # Handle formatting for custom timestamps vs durations
        s = f"{start_range}T00:00:00Z" if is_custom else start_range
        e = f"{end_range}T23:59:59Z" if is_custom else end_range

        # --- ANALYSIS 1: Total Consumption ---
        total_query = f'from(bucket: "{INFLUX_BUCKET}") |> range(start: {s}, stop: {e}) |> filter(fn: (r) => r._field == "energy_interval_kwh") |> sum()'
        total_result = query_api.query(total_query)
        
        total_kwh = 0
        for table in total_result:
            for record in table.records:
                total_kwh = record.get_value()

        # --- ANALYSIS 2: Peak Hour Detection ---
        pattern_query = f'from(bucket: "{INFLUX_BUCKET}") |> range(start: {s}, stop: {e}) |> filter(fn: (r) => r._field == "power") |> aggregateWindow(every: 1h, fn: mean)'
        pattern_result = query_api.query(pattern_query)
        
        hourly_data = {} 
        for table in pattern_result:
            for record in table.records:
 		# Convert UTC to local hour (Add 8)
                hour = (record.get_time().hour + 8) % 24
                val = record.get_value() or 0
                hourly_data[hour] = hourly_data.get(hour, []) + [val]

        # Calculate average power for every hour of the day (0-23)
        avg_hourly_power = {h: sum(v)/len(v) for h, v in hourly_data.items() if v}

        # Sort to find peak and non-peak
        sorted_hours = sorted(avg_hourly_power.items(), key=lambda item: item[1])
        
        if sorted_hours:
            peak_hour = sorted_hours[-1][0]      # Hour with highest usage
            non_peak_hour = sorted_hours[0][0]   # Hour with lowest usage
            peak_power = sorted_hours[-1][1]
        else:
            peak_hour, non_peak_hour, peak_power = 0, 0, 0

        # --- CALCULATIONS ---
        cost = calculate_malaysian_cost(total_kwh)
        co2 = total_kwh * MALAYSIA_GRID_EMISSION
        trees = co2 / TREE_ABSORPTION_YEAR
        daily_avg = total_kwh / 30.0
        
        range_label = f"{start_range} to {end_range}" if is_custom else "LAST 30 DAYS"

        # --- DYNAMIC RECOMMENDATION LOGIC ---
        peak_time_str = f"{peak_hour:02d}:00"
        non_peak_str = f"{non_peak_hour:02d}:00"
        
        analysis_text = f"Your highest usage usually occurs around *{peak_time_str}* ({peak_power:.1f}W average)."
        
        if total_kwh == 0:
            advice = "No data found to analyze."
        else:
            advice = f"1. *Shift Loads:* Your quietest time is *{non_peak_str}*. Try running heavy appliances (Washing Machine/Heaters) then to reduce stress on your internal wiring.\n"
            advice += f"2. *Peak Management:* At {peak_time_str}, ensure unnecessary lights and fans are off.\n"
            
            if daily_avg > 10:
                advice += "3. *High Load Note:* Your AC is likely the cause. Setting it to 24°C instead of 18°C can save up to 20% of your bill."
            else:
                advice += "3. *Standby Power:* You have a good baseline, but unplugging chargers at night can still save you RM 1-2 per month."

        # --- FORMAT REPORT ---
        report = (
            f"📜 *ENERGY AUDIT: {range_label}*\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"⚡ *Usage:* {total_kwh:.3f} kWh\n"
            f"💵 *Est. Bill:* RM {cost:.2f}\n"
            f"🕒 *Peak Hour:* {peak_hour:02d}:00 ({peak_power:.1f}W avg)\n\n"
            "🌍 *ENVIRONMENTAL IMPACT*\n"
            f"☁️ Carbon Footprint: {co2:.2f} kg CO2\n"
            f"🌳 Offset needed: {trees:.1f} trees\n\n"
            "💡 *SUGGESTIONS TO CONSERVE*\n"
            f"{advice}\n"
            "━━━━━━━━━━━━━━━━━━━━"
        )
        client.close()
        return report
    except Exception as e:
        logger.error(f"Audit Error: {e}")
        return f"⚠️ Error analyzing database: {str(e)}"

# --- TELEGRAM BOT HANDLERS ---
def get_keyboard():
    keys = list(PANELS.keys())
    layout = [keys[i:i + 2] for i in range(0, len(keys), 2)]
    layout.append([AUDIT_BUTTON, CUSTOM_AUDIT_BUTTON])
    layout.append([CUSTOM_OVERVIEW_BUTTON]) # Add new button to keyboard
    layout.append([RETRAIN_BUTTON])
    return layout

MARKUP = ReplyKeyboardMarkup(get_keyboard(), one_time_keyboard=False, resize_keyboard=True)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("🏠 *Home Energy AI Monitor* is active.\nSelect an option:", reply_markup=MARKUP, parse_mode="Markdown")

# --- NEW: CALENDAR INTERACTION HANDLERS ---
async def start_custom_audit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['mode'] = 'audit' # Set mode for Audit
    await update.message.reply_text("📅 *Custom Range Audit*\nPick START Date:", reply_markup=create_calendar(), parse_mode="Markdown")
    return START_DATE

async def start_custom_overview(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['mode'] = 'overview' # Set mode for Overview
    await update.message.reply_text("📅 *Custom Overview Range*\nPick START Date:", reply_markup=create_calendar(), parse_mode="Markdown")
    return START_DATE

async def handle_calendar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "ignore":
        return None

    # Handle Month Navigation
    if data.startswith("prev-m") or data.startswith("next-m"):
        _, _, y, m = data.split("-")
        y, m = int(y), int(m)
        if data.startswith("prev-m"):
            m -= 1
            if m == 0:
                m = 12
                y -= 1
        else:
            m += 1
            if m == 13:
                m = 1
                y += 1
        await query.edit_message_reply_markup(reply_markup=create_calendar(y, m))
        return None

    # Handle Day Selection
    if data.startswith("calendar-day"):
        _, _, y, m, d = data.split("-")
        selected_date = f"{y}-{int(m):02d}-{int(d):02d}"
        
        state = context.user_data.get('conv_state', START_DATE)

        if state == START_DATE:
            context.user_data['start_date'] = selected_date
            context.user_data['conv_state'] = END_DATE
            await query.edit_message_text(
                text=f"✅ *Start Date:* {selected_date}\n\n📅 *Pick END Date:*", 
                reply_markup=create_calendar(), 
                parse_mode="Markdown"
            )
            return END_DATE
        
        else:
            import pytz
            start_d = context.user_data['start_date']
            mode = context.user_data.get('mode', 'audit')
            
            malaysia_tz = pytz.timezone("Asia/Kuala_Lumpur")
            
            if mode == 'audit':
                await query.edit_message_text(text=f"🔎 *Analyzing Audit: {start_d} to {selected_date}...*")
                report = generate_audit_report(start_range=start_d, end_range=selected_date, is_custom=True)
                await context.bot.send_message(chat_id=query.message.chat_id, text=report, parse_mode="Markdown", reply_markup=MARKUP)
            
            else:
                await query.edit_message_text(text=f"📊 *Generating Overview: {start_d} to {selected_date}...*", parse_mode="Markdown")
                
                # Convert dates to epoch milliseconds for Grafana
                start_dt = malaysia_tz.localize(datetime.strptime(start_d, "%Y-%m-%d"))
                start_ts = int(start_dt.timestamp() * 1000)
                
                end_dt = malaysia_tz.localize(datetime.strptime(selected_date, "%Y-%m-%d").replace(hour=23, minute=59, second=59))
                end_ts = int(end_dt.timestamp() * 1000)
                
                panel_id = PANELS["System Overview"]["id"]
                render_url = (
                    f"{GRAFANA_URL}/render/d-solo/{GRAFANA_DASHBOARD_UID}/?orgId=1"
                    f"&panelId={panel_id}&from={start_ts}&to={end_ts}"
                    f"&width=1000&height=500&tz=Asia%2FKuala_Lumpur&maxDataPoints=800"
                )
                headers = {"Authorization": f"Bearer {GRAFANA_API_KEY}"}
                
                try:
                    response = requests.get(render_url, headers=headers, timeout=60)
                    if response.status_code == 200 and 'image/png' in response.headers.get('Content-Type', ''):
                        await context.bot.send_photo(
                            chat_id=query.message.chat_id, 
                            photo=response.content, 
                            caption=f"Holistic view from {start_d} to {selected_date}.", 
                            reply_markup=MARKUP
                        )
                    else:
                        await context.bot.send_message(
                            chat_id=query.message.chat_id, 
                            text=f"❌ Grafana Error! Code: {response.status_code}", 
                            reply_markup=MARKUP
                        )
                except Exception as e:
                    await context.bot.send_message(
                        chat_id=query.message.chat_id, 
                        text=f"⚠️ Bot Error: {str(e)}", 
                        reply_markup=MARKUP
                    )

            context.user_data.clear()
            return ConversationHandler.END


async def cancel_custom(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Canceled.", reply_markup=MARKUP)
    context.user_data.clear()
    return ConversationHandler.END
# -------------------------------------------

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = update.message.text
    chat_id = update.message.chat_id
    logger.info(f"Received request for '{text}'")

   # -------------------------------------------
    if text == RETRAIN_BUTTON:
        await update.message.reply_text("🧠 *AI is analyzing historical data to update its baseline...*", parse_mode="Markdown")
        retrain_model_auto()
        await update.message.reply_text("✅ *Baseline Updated!* The AI has adapted to your recent energy habits.", parse_mode="Markdown")
        return
   # -------------------------------------------

    if text == AUDIT_BUTTON:
        await update.message.reply_text("🔎 *Analyzing patterns...*", parse_mode="Markdown")
        await update.message.reply_text(generate_audit_report(), parse_mode="Markdown")
        return
   # -------------------------------------------

    panel_info = PANELS.get(text)
    if not panel_info: return
    await context.bot.send_message(chat_id=chat_id, text=f"📊 Generating '{text}'...")
    render_url = (
        f"{GRAFANA_URL}/render/d-solo/{GRAFANA_DASHBOARD_UID}/?orgId=1"
        f"&panelId={panel_info['id']}"
        f"&from=now-{panel_info['range']}"
        f"&to=now"
        f"&width=1000"
        f"&height=500"
        f"&tz=UTC"
        f"&maxDataPoints=800" # Add this line
    )
    headers = {"Authorization": f"Bearer {GRAFANA_API_KEY}"}
    try:
        response = requests.get(render_url, headers=headers, timeout=45)
        if response.status_code == 200:
            await context.bot.send_photo(chat_id=chat_id, photo=response.content, caption=panel_info['caption'])
        else:
            await context.bot.send_message(chat_id=chat_id, text=f"❌ Grafana Error! Code: {response.status_code}")
    except Exception as e: logger.error(f"Bot Error: {e}")


last_ai_alert_time = 0 
def run_mqtt_listener(bot_app):
    def on_message(client, userdata, msg):
        global last_ai_alert_time
        import json
        try:
            data = json.loads(msg.payload.decode())
            power = data.get("power", 0)
            is_anomaly, exp, limit = check_anomaly_ai(power)
            current_time = time.time()
            if is_anomaly and (current_time - last_ai_alert_time > 300):
                alert_text = (f"🚨 *AI ANOMALY DETECTED* 🚨\n━━━━━━━━━━━━━━━━━━━━\n"
                              f"⚠️ *Unusual Power:* {power:.1f} W\n🤖 *AI Expected:* {exp:.1f} W\n🛑 *Confidence Limit:* {limit:.1f} W")
                last_ai_alert_time = current_time 
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop.run_until_complete(bot_app.bot.send_message(chat_id=ALERT_CHAT_ID, text=alert_text, parse_mode="Markdown"))
        except Exception as e: logger.error(f"MQTT Logic Error: {e}")
    mqtt_client = mqtt.Client()
    mqtt_client.on_message = on_message
    mqtt_client.connect(MQTT_BROKER, 1883, 60)
    mqtt_client.subscribe(MQTT_TOPIC)
    mqtt_client.loop_start()

def main() -> None:
    if not os.path.exists(MODEL_FILE): retrain_model_auto()
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    # Updated ConversationHandler to handle both Custom Audit and Custom Overview
    custom_audit_handler = ConversationHandler(
        entry_points=[
            MessageHandler(filters.Regex(f"^{re.escape(CUSTOM_AUDIT_BUTTON)}$"), start_custom_audit),
            MessageHandler(filters.Regex(f"^{re.escape(CUSTOM_OVERVIEW_BUTTON)}$"), start_custom_overview)
        ],
        states={
            START_DATE: [CallbackQueryHandler(handle_calendar)],
            END_DATE: [CallbackQueryHandler(handle_calendar)],
        },
        fallbacks=[CommandHandler("cancel", cancel_custom)],
    )
    application.add_handler(custom_audit_handler)

    application.add_handler(CommandHandler("start", start))
    all_keys = list(PANELS.keys()) + [AUDIT_BUTTON, CUSTOM_AUDIT_BUTTON, CUSTOM_OVERVIEW_BUTTON, RETRAIN_BUTTON]
    pattern = f'^({"|".join(re.escape(k) for k in all_keys)})$'
    application.add_handler(MessageHandler(filters.Regex(pattern), handle_message))
    
    async def retrain_job(context): retrain_model_auto()
    application.job_queue.run_repeating(retrain_job, interval=604800, first=60)
    run_mqtt_listener(application)
    application.run_polling()

if __name__ == "__main__":
    main()