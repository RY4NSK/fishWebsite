from flask import Flask, redirect, render_template, request, jsonify, Response
#import requests
import sqlite3
from datetime import datetime
import json
import cv2
from urllib.parse import urlparse
import time


app = Flask(__name__)

# Path to SQLite database file
DATABASE = "data.db"

# Helper function to initialize the database
def init_db():
    with sqlite3.connect(DATABASE) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS saved_data (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT UNIQUE NOT NULL,
                measurements TEXT NOT NULL
            )
        """)
        conn.commit()

# Helper function to save data to the database
def save_data_to_db(date, measurements):
    with sqlite3.connect(DATABASE) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO saved_data (date, measurements)
            VALUES (?, ?)
        """, (date, json.dumps(measurements)))
        conn.commit()

# Helper function to retrieve all data from the database
def get_all_data_from_db():
    with sqlite3.connect(DATABASE) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT date, measurements FROM saved_data ORDER BY date")
        rows = cursor.fetchall()
    return [{"date": row[0], "measurements": json.loads(row[1])} for row in rows]

# Helper function to check if a date exists in the database
def is_date_in_db(date):
    with sqlite3.connect(DATABASE) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM saved_data WHERE date = ?", (date,))
        return cursor.fetchone() is not None

# Helper function to validate URL
def is_valid_url(url):
    parsed = urlparse(url)
    return parsed.scheme in ["http", "https"] and bool(parsed.netloc)

@app.route('/')
def serve_index():
    return render_template('index.html')

@app.route('/api/load-url', methods=['POST'])
def get_data():
    input_url = request.form.get('urlInput')
    if not input_url or not is_valid_url(input_url):
        return jsonify({"error": "Invalid or missing 'url' query parameter"}), 400

    try:
        # Replace the base URL if necessary
        if input_url.startswith("https://solutions.waterlinkconnect.com"):
            input_url = input_url.replace(
                "https://solutions.waterlinkconnect.com",
                "https://wls-api.waterlinkconnect.com"
            )

        # Fetch data from the modified URL
        import requests
        response = requests.get(input_url)
        response.raise_for_status()
        data = response.json()

        # Format the response data
        new_data = {
            "date": datetime.strptime(data.get("waterTestDate"), "%Y-%m-%dT%H:%M:%S.%f%z").date().isoformat(),
            "measurements": [
                {
                    "name": getFactorName(measurement["testFactorId"]),
                    "value": measurement["value"],
                    "unit": measurement.get("unitOfMeasure", "Unknown Unit"),
                }
                for measurement in data.get("measurements", [])
            ]
        }

        if is_date_in_db(new_data["date"]):
            return jsonify({"error": "Data for this date already exists"}), 409

        # Save to database
        save_data_to_db(new_data["date"], new_data["measurements"])

        return redirect("/")
    
    except requests.RequestException as e:
        return jsonify({"error": str(e)}), 500
    except json.JSONDecodeError:
        return jsonify({"error": "Invalid JSON response from the URL"}), 500

@app.route('/api/saved-data', methods=['GET'])
def get_saved_data():
    return jsonify(get_all_data_from_db())

@app.route('/api/saved-data', methods=['POST'])
def add_saved_data():
    date = request.form.get("entryDate")

    measurements = [
        { "name": 'pH', "value" : request.form.get('phInput'), "unit": '' },
        { "name": 'Alkalinity', "value" : request.form.get('alkalinityInput'), "unit": 'mg/L' },
        { "name": 'Phosphate', "value" : request.form.get('phosphateInput'), "unit": 'mg/L' },
        { "name": 'Salt', "value" : request.form.get('saltInput'), "unit": 'mg/L' },
        { "name": 'Nitrate', "value" : request.form.get('nitrateInput'), "unit": 'mg/L' },
        { "name": 'Nitrite', "value" : request.form.get('nitriteInput'), "unit": 'mg/L' },
        { "name": 'Ammonia', "value" : request.form.get('ammoniaInput'), "unit": 'mg/L' },
        { "name": 'Magnesium (Ions)', "value" : request.form.get('magnesiumInput'), "unit": 'ppm' },
        { "name": 'Calcium (Ions)', "value" : request.form.get('calciumInput'), "unit": 'ppm' }
    ]

    if is_date_in_db(date):
        return jsonify({"error": "Data for this date already exists"}), 409

    save_data_to_db(date, measurements)

    return redirect("/")


@app.route('/api/delete-data', methods=['POST'])
def delete_data():
    try:
        data = request.get_json()

        print("Received data:", data)

        date = data.get('date')

        if not date:
            return jsonify({"error": "Missing required date"}), 400

        with sqlite3.connect(DATABASE) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                DELETE FROM saved_data
                WHERE date = ?
            """, (date, ))
            conn.commit()

        return jsonify({"success": "Date deleted successfully"})

    except Exception as e:
        print(f"Error during deletion: {e}")
        return jsonify({"error": str(e)}), 500
    
# Load test factors once
with open("testfactors.json") as f:
    factors = json.load(f)
    
def getFactorName(id):
    for member in factors["members"]:
        if member["id"] == id:
            return member["name"]
    return "Unknown Factor"

print("initilising start cameras")
camera1 = cv2.VideoCapture(0)  # First camera
camera2 = cv2.VideoCapture(2)  # Second camera

camera1.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
camera1.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
camera2.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
camera2.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)

print("done cameras")

def generate_frames(camera):
    while True:
        success, frame = camera.read()
        if not success:
            break
        else:
            # Set JPEG encoding quality to reduce size and encoding time
            encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), 80]
            ret, buffer = cv2.imencode('.jpg', frame, encode_param)
            frame = buffer.tobytes()  # Convert to bytes
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')

@app.route('/camera1')
def video_feed1():
    return Response(generate_frames(camera1),
                    mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/camera2')
def video_feed2():
    return Response(generate_frames(camera2),
                    mimetype='multipart/x-mixed-replace; boundary=frame')

if __name__ == "__main__":
    init_db()  
    app.run(host="0.0.0.0", port=5000, debug=False)


