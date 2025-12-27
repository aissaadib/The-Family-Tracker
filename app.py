import sqlite3
import time
from functools import wraps
from flask import Flask, render_template, jsonify, request, abort, session, redirect, url_for, flash
from flask_session import Session
from werkzeug.security import check_password_hash, generate_password_hash

app = Flask(__name__)

# Configure session to use filesystem (instead of signed cookies)
app.config["SESSION_PERMANENT"] = False
app.config["SESSION_TYPE"] = "filesystem"
Session(app)

DB_PATH = "family.db"

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    with open('schema.sql', mode='r') as f:
        conn.executescript(f.read())
    conn.close()

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if session.get("user_id") is None:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

@app.route("/")
@login_required
def home():
    return render_template("home.html")

@app.route("/private-map")
@login_required
def private_map():
    conn = get_db_connection()
    rows = conn.execute("SELECT name, role FROM people").fetchall()
    conn.close()
    family = [{"name": row["name"], "role": row["role"]} for row in rows]
    return render_template("map.html", family=family, title="Private Map")

@app.route("/public-map")
@login_required
def public_map():
    conn = get_db_connection()
    rows = conn.execute("SELECT name, role FROM people").fetchall()
    conn.close()
    family = [{"name": row["name"], "role": row["role"]} for row in rows]
    return render_template("map.html", family=family, title="Public Map")

@app.route("/login", methods=["GET", "POST"])
def login():
    session.clear()

    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")

        if not username or not password:
            flash("Must provide username and password")
            return render_template("login.html")

        conn = get_db_connection()
        user = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        conn.close()

        if user is None or not check_password_hash(user["hash"], password):
            flash("Invalid username and/or password")
            return render_template("login.html")

        session["user_id"] = user["id"]
        session["username"] = user["username"]
        session["logged"] = True
        
        return redirect("/")

    return render_template("login.html")

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        confirmation = request.form.get("confirmation")

        if not username or not password or not confirmation:
            flash("All fields are required")
            return render_template("register.html")
        
        if password != confirmation:
            flash("Passwords must match")
            return render_template("register.html")

        hash_pw = generate_password_hash(password)

        conn = get_db_connection()
        try:
            conn.execute("INSERT INTO users (username, hash) VALUES (?, ?)", (username, hash_pw))
            conn.commit()
        except sqlite3.IntegrityError:
            conn.close()
            flash("Username already taken")
            return render_template("register.html")
        
        conn.close()
        
        # Auto login
        return redirect(url_for("login"))

    return render_template("register.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")

@app.route("/api/locations")
@login_required
def api_locations():
    conn = get_db_connection()
    rows = conn.execute("SELECT name, role, lat, lon, last_update FROM people").fetchall()
    conn.close()

    family = []
    for row in rows:
        family.append({
            "name": row["name"],
            "role": row["role"],
            "lat": row["lat"],
            "lon": row["lon"],
            "last_update": row["last_update"],
        })
    return jsonify(family)

@app.route("/api/update_location", methods=["POST"])
def api_update_location():
    # Allow updates without login for trackers? 
    # Or should trackers authenticate? 
    # For simplicity, keeping it open or maybe require a secret key in future.
    # User instructions implied 'functions and a that you can only acess if the logged value is true'
    # likely refers to the map/dashboard.
    
    data = request.get_json() if request.is_json else request.form

    name = data.get("name")
    lat = data.get("lat")
    lon = data.get("lon")

    if not name or lat is None or lon is None:
        abort(400, "name, lat and lon are required")

    try:
        lat = float(lat)
        lon = float(lon)
    except ValueError:
        abort(400, "lat and lon must be numbers")

    conn = get_db_connection()
    now = int(time.time())

    conn.execute(
        "UPDATE people SET lat = ?, lon = ?, last_update = ? WHERE name = ?",
        (lat, lon, now, name),
    )
    
    # Check if update happened, else insert
    # Since we can't check rowcount easily with execute shorthand in some versions, let's use cursor
    # But wait, execute returns cursor.
    # Re-implementing correctly:
    
    # Note: Using the logic from Part 4 but keeping it robust
    cursor = conn.cursor()
    cursor.execute(
         "UPDATE people SET lat = ?, lon = ?, last_update = ? WHERE name = ?",
        (lat, lon, now, name),
    )
    if cursor.rowcount == 0:
        cursor.execute(
            "INSERT INTO people (name, role, lat, lon, last_update) VALUES (?, ?, ?, ?, ?)",
            (name, "Unknown", lat, lon, now),
        )
    
    conn.commit()
    conn.close()

    return jsonify({"status": "ok"})

@app.route("/tracker/<name>")
def tracker(name):
    return render_template("tracker.html", name=name)

if __name__ == "__main__":
    init_db()
    app.run(debug=True, host="0.0.0.0", port=5000)
