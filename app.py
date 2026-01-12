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
    if not data or 'raw_text' not in data:
        return jsonify({"status": "error", "message": "Missing raw_text"}), 400

    raw_text = data.get('raw_text', '')
    assigned_name = data.get('assigned_to', 'Not Assigned')
    
    # 1. Extraction
    phone_pattern = r'(\+?\d{1,3}[\s\d\-\(\)]{10,16})'
    match = re.search(phone_pattern, raw_text)
    if not match:
        return jsonify({"status": "error", "message": "No phone number found"}), 400
    
    clean_phone = "".join(filter(lambda x: x.isdigit() or x == '+', match.group(0)))
    
    # Create both versions for searching to handle the + mismatch
    phone_with_plus = clean_phone if clean_phone.startswith('+') else "+" + clean_phone
    phone_no_plus = clean_phone.replace('+', '')

    # 2. Connect to Master Sheet
    master_sheet = client.open(sheet_name).get_worksheet(0)

    # 3. HIGH PERFORMANCE DUPLICATE CHECK (Using find)
    # We search specifically in Column D (index 4)
    try:
        # Check version 1: With Plus
        dup = master_sheet.find(phone_with_plus, in_column=4)
        if not dup:
            # Check version 2: Without Plus
            dup = master_sheet.find(phone_no_plus, in_column=4)
        
        if dup:
            print(f"⏭️ Duplicate found at Row {dup.row}. Skipping.")
            return jsonify({"status": "ignored", "message": "Duplicate found"}), 200
    except gspread.exceptions.CellNotFound:
        pass

    # 4. Preparation for Update
    formatted_date = get_formatted_date(raw_text)
    
    # Finding actual end of data to avoid Grid Limit errors
    # col_values is necessary once to find the true 'next' row
    actual_last_row = len(master_sheet.col_values(4)) 
    next_row = actual_last_row + 1
    current_grid_rows = master_sheet.row_count

    # 5. Dynamic Grid Expansion
    if next_row > current_grid_rows:
        master_sheet.add_rows(1)
            
    # Prepare the new row data (S.No is actual_last_row because of header)
    new_row = [actual_last_row, formatted_date, "", clean_phone, "", "Whatsapp", "", "", "", "", "", "", "", "", assigned_name]

    # 6. Update using Named Arguments (Fixes Deprecation and 400 Errors)
    try:
        range_name = f"A{next_row}:P{next_row}"
        master_sheet.update(
            values=[new_row], 
            range_name=range_name, 
            value_input_option='USER_ENTERED'
        )
        print(f"✅ Master Sheet updated: Row {next_row}")
    except Exception as e:
        print(f"❌ Master update failed: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

     # 6. Optimized Target Sheet Logic
    try:
        target_name = None
        if "Dattu" in assigned_name:
            target_name = "Dattu's leads"

        if target_name:
            target_sheet = client.open(sheet_name).worksheet(target_name)
            # Use append_row for target sheets as they are usually smaller
            new_row[0] = get_serial_no(target_sheet)
            new_row[14] = ""
            target_sheet.append_row(new_row, value_input_option='USER_ENTERED')
            print(f"✅ Target sheet '{target_name}' updated.")

           

    except Exception as e:

        print(f"⚠️ Target sheet error: {e}")
    
    return jsonify({"status": "success"}), 200

if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
