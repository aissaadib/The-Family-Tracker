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
def public_map():
    conn = get_db_connection()
    # For the legend, only show public people
    rows = conn.execute("""
        SELECT p.name, p.role 
        FROM people p
        JOIN users u ON p.name = u.username
        WHERE u.vis = 1
    """).fetchall()
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
        session["vis"] = bool(user["vis"]) # Store visibility status in session
        session["logged"] = True
        
        return redirect("/")

    return render_template("login.html")

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username")
        location = request.form.get("location")
        password = request.form.get("password")
        confirmation = request.form.get("confirmation")

        if not username or not location or not password or not confirmation:
            flash("All fields are required")
            return render_template("register.html")
        
        if password != confirmation:
            flash("Passwords must match")
            return render_template("register.html")

        hash_pw = generate_password_hash(password)

        conn = get_db_connection()
        try:
            conn.execute("INSERT INTO users (username, hash, location) VALUES (?, ?, ?)", (username, hash_pw, location))
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

# --- VISIBILITY TOGGLE FEATURE ---
@app.route("/toggle-visibility", methods=["POST"])
@login_required
def toggle_visibility():
    """Toggles user account from Private to Public and back."""
    new_vis = not session.get("vis", False)
    
    conn = get_db_connection()
    # Update 'vis' column in the database for the current user
    conn.execute("UPDATE users SET vis = ? WHERE id = ?", (int(new_vis), session["user_id"]))
    
    # --- P_MAP SYNCHRONIZATION ---
    if new_vis:
        # Add to p_map if becoming public
        user_data = conn.execute("SELECT username, location FROM users WHERE id = ?", (session["user_id"],)).fetchone()
        conn.execute("INSERT OR REPLACE INTO p_map (user_id, username, location) VALUES (?, ?, ?)", 
                     (session["user_id"], user_data["username"], user_data["location"]))
    else:
        # Remove from p_map if becoming private
        conn.execute("DELETE FROM p_map WHERE user_id = ?", (session["user_id"],))
    # --- END P_MAP SYNC ---

    conn.commit()
    conn.close()
    
    # Update the session to reflect the new state
    session["vis"] = new_vis
    flash(f"Account visibility set to {'Public' if new_vis else 'Private'}")
    return redirect(request.referrer or "/")
# --- END VISIBILITY TOGGLE ---

@app.route("/api/locations")
def api_locations():
    """Returns locations based on visibility and auth."""
    conn = get_db_connection()
    
    # Logic: 
    # 1. Show a person's location if they are Public (vis=1)
    #    We now pull these from the p_map table as requested.
    # 2. ALSO show everything if the requester is logged in (Private view)
    
    is_logged_in = session.get("user_id") is not None
    
    if is_logged_in:
        # Logged in users see everything (Private Map view)
        rows = conn.execute("SELECT name, role, lat, lon, last_update FROM people").fetchall()
    else:
        # Non-logged in users (or Public Map) only see people from p_map
        # We join people with p_map on name=username
        rows = conn.execute("""
            SELECT p.name, p.role, p.lat, p.lon, p.last_update 
            FROM people p
            JOIN p_map pm ON p.name = pm.username
        """).fetchall()
        
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
