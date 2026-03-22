from flask import Flask, request, jsonify
import re
import dateparser
from datetime import datetime
import gspread
import os
from oauth2client.service_account import ServiceAccountCredentials

app = Flask(__name__)

# 1. Define the scope and authorize once
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "creds.json")
creds = ServiceAccountCredentials.from_json_keyfile_name(path, scope)
client = gspread.authorize(creds)

# CHANGE THIS: Use the ID from your browser URL (the long string of letters/numbers)
SPREADSHEET_ID = "1kIRrGLSWxlhh3GgmUK0l6AgyEOqwnydgawQAlycJG4Y"

def get_formatted_date(raw_text):
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
    data = request.get_json()
    if not data or 'raw_text' not in data:
        return jsonify({"status": "error", "message": "Missing raw_text"}), 400

    raw_text = data.get('raw_text', '')
    assigned_name = data.get('assigned_to', 'Not Assigned')
    
    # 1. Phone Extraction
    phone_pattern = r'(\+?\d{1,3}[\s\d\-\(\)]{10,16})'
    match = re.search(phone_pattern, raw_text)
    if not match:
        return jsonify({"status": "error", "message": "No phone number found"}), 400
    
    clean_phone = "".join(filter(lambda x: x.isdigit() or x == '+', match.group(0)))

    try:
        # 2. Open Spreadsheet ONCE (Using ID is much faster than Name)
        doc = client.open_by_key(SPREADSHEET_ID)
        master_sheet = doc.get_worksheet(0)

        # 3. Fast Duplicate Check (Searching Column D only)
        try:
            if master_sheet.find(clean_phone, in_column=4):
                print(f"⏭️ Duplicate {clean_phone} found. Skipping.")
                return jsonify({"status": "ignored", "message": "Duplicate found"}), 200
        except gspread.exceptions.CellNotFound:
            pass

        # 4. Prepare Row Data
        formatted_date = get_formatted_date(raw_text)
        # We leave S.No (index 0) empty or use a formula; append_row is very fast.
        new_row = ["", formatted_date, "", clean_phone, "", "Whatsapp", "", "", "", "", "", "", "", "", assigned_name]

        # 5. Fast Update using append_row
        master_sheet.append_row(new_row, value_input_option='USER_ENTERED')
        print(f"✅ Master Sheet updated for {clean_phone}")

        # 6. Target Sheet Update (re-using the 'doc' connection)
        if "Dattu" in assigned_name:
            target_sheet = doc.worksheet("Dattu's leads")
            target_sheet.append_row(new_row, value_input_option='USER_ENTERED')
            print("✅ Target sheet updated.")

        return jsonify({"status": "success"}), 200

    except Exception as e:
        print(f"❌ Error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
