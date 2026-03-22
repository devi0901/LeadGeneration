from flask import Flask, request, jsonify
import re
import dateparser
from datetime import datetime
import gspread
import os
import logging
from oauth2client.service_account import ServiceAccountCredentials

# --- CONFIGURATION ---
SPREADSHEET_ID = "1kIRrGLSWxlhh3GgmUK0l6AgyEOqwnydgawQAlycJG4Y"

# Setup high-visibility logging for Render
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger("LeadTracker")

app = Flask(__name__)

# Google Auth - Initialize once to save time
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "creds.json")
creds = ServiceAccountCredentials.from_json_keyfile_name(path, scope)
client = gspread.authorize(creds)

def get_formatted_date(raw_text):
    """Extracts and formats date from raw text."""
    date_keywords = r'(Yesterday|Today|Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday|\w{3}, \d{1,2} \w{3})'
    date_match = re.search(date_keywords, raw_text, re.IGNORECASE)
    now = datetime.now()
    
    if date_match:
        raw_date_str = date_match.group(0)
        parsed_date = dateparser.parse(raw_date_str, settings={'PREFER_DATES_FROM': 'past', 'RELATIVE_BASE': now})
        if parsed_date:
            return parsed_date.strftime("%b %d, %Y")
    
    return now.strftime("%b %d, %Y")

@app.route("/webhook", methods=["POST"])
def webhook():
    logger.info(">>> Incoming Request Received")
    data = request.get_json()
    
    if not data or 'raw_text' not in data:
        logger.error("!!! Failure: No raw_text provided in payload")
        return jsonify({"status": "error", "message": "Missing raw_text"}), 400

    raw_text = data.get('raw_text', '')
    assigned_name = data.get('assigned_to', 'Not Assigned')
    logger.info(f"--- Processing for: {assigned_name} ---")

    # 1. Phone Extraction
    phone_pattern = r'(\+?\d{1,3}[\s\d\-\(\)]{10,16})'
    match = re.search(phone_pattern, raw_text)
    if not match:
        logger.warning("!!! Failure: Could not find a phone number in text")
        return jsonify({"status": "error", "message": "No phone number found"}), 400
    
    clean_phone = "".join(filter(lambda x: x.isdigit() or x == '+', match.group(0)))
    logger.info(f"Target Phone: {clean_phone}")

    try:
        # 2. Connect once
        logger.info("Connecting to Google Sheets via ID...")
        doc = client.open_by_key(SPREADSHEET_ID)
        master_sheet = doc.get_worksheet(0)

        # 3. Speed Check for Duplicates
        logger.info(f"Searching Column D for {clean_phone}...")
        try:
            if master_sheet.find(clean_phone, in_column=4):
                logger.info(f"MATCH FOUND: {clean_phone} is a duplicate. Ending process.")
                return jsonify({"status": "ignored", "message": "Duplicate"}), 200
        except gspread.exceptions.CellNotFound:
            logger.info("No duplicate found. Proceeding with update.")

        # 4. Prepare Data
        formatted_date = get_formatted_date(raw_text)
        # Using a blank string for S.No as append_row adds it to the end
        new_row = ["", formatted_date, "", clean_phone, "", "Whatsapp", "", "", "", "", "", "", "", "", assigned_name]

        # 5. Fast Update
        logger.info("Appending row to Master Sheet...")
        master_sheet.append_row(new_row, value_input_option='USER_ENTERED')
        logger.info("MASTER SHEET SUCCESS")

        # 6. Target Sheet Logic
        if "Dattu" in assigned_name:
            logger.info("Route detected: Dattu's leads. Updating secondary sheet...")
            target_sheet = doc.worksheet("Dattu's leads")
            target_sheet.append_row(new_row, value_input_option='USER_ENTERED')
            logger.info("TARGET SHEET SUCCESS")

        logger.info(">>> Request Completed Successfully")
        return jsonify({"status": "success"}), 200

    except Exception as e:
        logger.error(f"CRITICAL ERROR: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
