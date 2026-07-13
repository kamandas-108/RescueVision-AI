import os
import re
from flask import Flask, render_template, request, jsonify, session, redirect, url_for
import google.generativeai as genai
import psycopg2
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__, template_folder='.')
app.secret_key = os.getenv("FLASK_SECRET_KEY", "rescuevision-secret-key-1029")

# Configure Gemini API
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

# Database Helper Function
def get_db_connection():
    conn = psycopg2.connect(os.getenv("NEON_DB_STRING"))
    return conn

# Initialize Database Schema
def init_db():
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                username VARCHAR(50) UNIQUE NOT NULL,
                email VARCHAR(100) UNIQUE NOT NULL,
                password_hash VARCHAR(255) NOT NULL
            );
        """)
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"Database initialization error: {e}")

init_db()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/auth/signup', methods=['POST'])
def signup():
    data = request.get_json()
    username = data.get('username')
    email = data.get('email')
    password = data.get('password')
    
    if not username or not email or not password:
        return jsonify({"success": False, "error": "Missing fields"}), 400
        
    hashed_pw = generate_password_hash(password)
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO users (username, email, password_hash) VALUES (%s, %s, %s)",
            (username, email, hashed_pw)
        )
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({"success": True, "message": "Account created!"})
    except psycopg2.IntegrityError:
        return jsonify({"success": False, "error": "Username or Email already exists."}), 400
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/auth/login', methods=['POST'])
def login():
    data = request.get_json()
    email = data.get('email')
    password = data.get('password')
    
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT id, username, password_hash FROM users WHERE email = %s", (email,))
        user = cur.fetchone()
        cur.close()
        conn.close()
        
        if user and check_password_hash(user[2], password):
            session['user_id'] = user[0]
            session['username'] = user[1]
            return jsonify({"success": True, "username": user[1]})
        return jsonify({"success": False, "error": "Invalid email or password."}), 401
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/auth/logout', methods=['POST'])
def logout():
    session.clear()
    return jsonify({"success": True})

@app.route('/api/analyze', methods=['POST'])
def analyze_disaster():
    if 'user_id' not in session:
        return jsonify({"error": "Unauthorized. Please log in first."}), 401

    report_text = request.form.get('report_text', '')
    image_file = request.files.get('image_file')

    # Default mock/simulated geospatial coordinates to populate the map reactively based on text
    lat, lng = 34.0522, -118.2437  # Default to dynamic central zone
    
    if "riverside" in report_text.lower():
        lat, lng = 33.9533, -117.3962
    elif "mountain" in report_text.lower() or "hill" in report_text.lower():
        lat, lng = 34.2500, -118.6000

    prompt = f"""
    You are an emergency crisis AI response system. Analyze the following emergency inputs and return structural information.
    
    Text Report: "{report_text}"
    Has uploaded image: { 'Yes' if image_file else 'No' }

    Extract the details and structure them EXACTLY like this layout:
    Location: [Extracted location]
    Disaster: [Flood / Fire / Earthquake / Landslide]
    Severity: [Critical / Moderate / Safe]
    People Affected: [Estimated number]
    Priority: [Immediate Rescue / Urgent / Monitoring]
    
    Then provide a "Resource Recommendation Plan" based on the severity:
    - Recommended Supplies: [e.g., 4 Rescue Boats, 2 Medical Teams, 100 Food Kits]
    - Priority Score: [Number between 0-100]
    """

    try:
        model = genai.GenerativeModel('gemini-2.5-flash')
        response = model.generate_content(prompt)
        text_output = response.text

        # Parsing using simple regex structural mapping
        def extract(pattern, string):
            match = re.search(pattern, string, re.IGNORECASE)
            return match.group(1).strip() if match else "Unknown"

        location = extract(r"Location:\s*(.*)", text_output)
        disaster = extract(r"Disaster:\s*(.*)", text_output)
        severity = extract(r"Severity:\s*(.*)", text_output)
        people = extract(r"People Affected:\s*(.*)", text_output)
        priority = extract(r"Priority:\s*(.*)", text_output)
        
        resources = extract(r"Recommended Supplies:\s*(.*)", text_output)
        score = extract(r"Priority Score:\s*(\d+)", text_output)
        if score == "Unknown": score = "85"

        return jsonify({
            "success": True,
            "analysis": {
                "location": location,
                "disaster": disaster,
                "severity": severity,
                "people": people,
                "priority": priority
            },
            "resources": {
                "recommended": resources if resources != "Unknown" else "5 Rescue Teams, 20 Medical Kits",
                "score": score
            },
            "map_coords": {"lat": lat, "lng": lng}
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
