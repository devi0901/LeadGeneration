from flask import Flask, request, jsonify
import re
import dateparser
from datetime import datetime
import gspread
import os
from oauth2client.service_account import ServiceAccountCredentials

app = Flask(__name__)

# 1. Define the scope
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]

# 2. Check for the Render path first, then fall back to your local file
path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "creds.json")

# 3. Authorize using the path
creds = ServiceAccountCredentials.from_json_keyfile_name(path, scope)
client = gspread.authorize(creds)
sheet_name = "Incorp Genius – Lead Qualification & Conversion Tracker"

def get_formatted_date(raw_text):
    date_keywords = r'(Yesterday|Today|Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday|\w{3}, \d{1,2} \w{3})'
    date_match = re.search(date_keywords, raw_text, re.IGNORECASE)
    now = datetime.now()
    current_year = now.year
    parsed_date = now

    if date_match:
        raw_date_str = date_match.group(0)
        is_relative = any(word in raw_date_str.lower() for word in ['yesterday', 'today', 'monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday'])
        
        if is_relative:
            parsed_date = dateparser.parse(raw_date_str, settings={'PREFER_DATES_FROM': 'past', 'RELATIVE_BASE': now})
        else:
            parsed_date = dateparser.parse(raw_date_str, settings={'PREFER_DATES_FROM': 'past', 'RELATIVE_BASE': now}, date_formats=['%a, %d %b', '%d %b'])
            if parsed_date:
                parsed_date = parsed_date.replace(year=current_year)

    return parsed_date.strftime("%b %d, %Y") if parsed_date else now.strftime("%b %d, %Y")

def get_serial_no(sheet):
    all_s_nos = sheet.col_values(1)[1:] 
    numeric_s_nos = [int(n) for n in all_s_nos if str(n).isdigit()]
    return max(numeric_s_nos) + 1 if numeric_s_nos else 1

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json()
    print(data)
    if 'raw_text' not in data:
        return jsonify({"status": "error", "message": "Missing raw_text"}), 400

    raw_text = data.get('raw_text', '')
    assigned_name = data.get('assigned_to', 'Not Assigned')
    
    # --- 1. Updated Phone Extraction (Supports India +91 and US +1) ---
    # This pattern catches numbers with spaces, parentheses, and dashes
    phone_pattern = r'(\+?\d{1,3}[\s\d\-\(\)]{10,16})'
    match = re.search(phone_pattern, raw_text)
    
    if not match:
        return jsonify({"status": "error", "message": "No phone number found"}), 400
    
    # Keep digits and the plus sign for the sheet
    clean_phone = "".join(filter(lambda x: x.isdigit() or x == '+', match.group(0)))
    formatted_date = get_formatted_date(raw_text)

    # 1. Master Sheet Connection
    master_sheet = client.open(sheet_name).get_worksheet(0)
    current_max_rows = master_sheet.row_count

    # 2. Optimized Duplicate Check (Look at last 500 rows only)
    # This is MUCH faster than reading the whole column
    start_row = max(1, current_max_rows - 500)
    check_range = f"D{start_row}:D{current_max_rows}"
    recent_numbers = master_sheet.get(check_range)
    # Flatten list of lists to a simple list
    recent_numbers_list = [item[0] for item in recent_numbers if item]

    if clean_phone in recent_numbers_list:
        return jsonify({"status": "ignored", "message": "Recent Duplicate"}), 200

    # 3. Faster S.No Logic (Just use row count instead of reading Col A)
    # If your sheet is clean, Row Count is a faster proxy for S.No
    s_no = current_max_rows
    next_row = s_no + 1
    # --- 3. Prepare Forced Row Placement ---
    new_row = [s_no, formatted_date, "", clean_phone, "", "Whatsapp", "", "", "", "", "", "", "", "", assigned_name]

    # Dynamic Row Expansion
    current_max_rows = master_sheet.row_count
    if next_row > current_max_rows:
        master_sheet.add_rows(next_row - current_max_rows)

    # Forced update to Columns A-P to avoid horizontal displacement
    range_name = f"A{next_row}:P{next_row}"

    try:
        master_sheet.update(range_name, [new_row], value_input_option='USER_ENTERED')
        print(f"✅ Master Sheet Forced to Row {next_row}")
    except Exception as e:
        print(f"❌ Master update failed: {e}")

    # --- 4. Target Sheet Logic ---
    try:
        if "Anuhya" in assigned_name:
            target_sheet = client.open(sheet_name).worksheet("Anuhya Leads")
        elif "Dattu" in assigned_name:
            target_sheet = client.open(sheet_name).worksheet("Dattu's leads")
        else:
            target_sheet = None

        if target_sheet:
            new_row[0] = get_serial_no(target_sheet)
            new_row[14]=""
            target_sheet.append_row(range_name,[new_row], value_input_option='USER_ENTERED')
            print(f"✅ Updated target sheet: {target_sheet.title}")
            
    except Exception as e:
        print(f"Error updating target sheet: {e}")
    
    return jsonify({"status": "success"}), 200

if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
