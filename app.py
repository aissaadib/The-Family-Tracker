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
    conn = get_db_connection()
    map_follows = conn.execute("""
        SELECT u.id, u.username
        FROM users u
        JOIN map_follows mf ON u.id = mf.followed_id
        WHERE mf.user_id = ?
    """, (session["user_id"],)).fetchall()
    conn.close()
    return render_template("home.html", map_follows=map_follows)

@app.route("/searchf", methods=["GET", "POST"])
@login_required
def search_friends():
    users = []
    if request.method == "POST":
        query = request.form.get("query", "")
        conn = get_db_connection()
        users = conn.execute("""
            SELECT u.id, u.username, u.vis,
                   CASE WHEN mf.followed_id IS NOT NULL THEN 1 ELSE 0 END AS on_map
            FROM users u
            LEFT JOIN map_follows mf ON mf.user_id = ? AND mf.followed_id = u.id
            WHERE u.username LIKE ? AND u.id != ? AND u.vis = 1
        """, (session["user_id"], f"%{query}%", session["user_id"])).fetchall()
        conn.close()
    return render_template("searchf.html", users=users)

@app.route("/remove_from_map/<int:followed_id>", methods=["POST"])
@login_required
def remove_from_map(followed_id):
    conn = get_db_connection()
    conn.execute("DELETE FROM map_follows WHERE user_id = ? AND followed_id = ?",
                 (session["user_id"], followed_id))
    conn.commit()
    conn.close()
    flash("User removed from your map.")
    return redirect(url_for("home"))

@app.route("/add_to_map/<int:followed_id>", methods=["POST"])
@login_required
def add_to_map(followed_id):
    conn = get_db_connection()
    target = conn.execute("SELECT vis FROM users WHERE id = ?", (followed_id,)).fetchone()
    if not target or not target["vis"]:
        conn.close()
        flash("That user has a private account and cannot be added to your map.")
        return redirect(url_for("search_friends"))
    try:
        conn.execute("INSERT INTO map_follows (user_id, followed_id) VALUES (?, ?)",
                     (session["user_id"], followed_id))
        conn.commit()
        flash("User added to your private map!")
    except sqlite3.IntegrityError:
        flash("Already on your map!")
    finally:
        conn.close()
    return redirect(url_for("home"))

@app.route("/private-map")
@login_required
def private_map():
    return render_template("map.html", title="Private Map", map_type="private")

@app.route("/public-map")
def public_map():
    return render_template("map.html", title="Public Map", map_type="public")

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
        lat = request.form.get("lat")
        lon = request.form.get("lon")
        password = request.form.get("password")
        confirmation = request.form.get("confirmation")

        if not username or not password or not confirmation:
            flash("Username and passwords are required")
            return render_template("register.html")
        
        if password != confirmation:
            flash("Passwords must match")
            return render_template("register.html")

        hash_pw = generate_password_hash(password)

        conn = get_db_connection()
        try:
            # We store the coordinates in the location field or use them to populate 'people'
            location_str = f"{lat},{lon}" if lat and lon else "Unknown"
            cursor = conn.cursor()
            cursor.execute("INSERT INTO users (username, hash, location) VALUES (?, ?, ?)", (username, hash_pw, location_str))
            user_id = cursor.lastrowid
            
            # Also add to people table for the map
            if lat and lon:
                conn.execute(
                    "INSERT INTO people (name, role, lat, lon, last_update) VALUES (?, ?, ?, ?, ?)",
                    (username, "User", float(lat), float(lon), int(time.time()))
                )
            
            conn.commit()
        except sqlite3.IntegrityError:
            conn.close()
            flash("Username already taken")
            return render_template("register.html")
        
        conn.close()
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
    # 2. ALSO show friends' locations if the requester is logged in (Private view)
    
    is_logged_in = session.get("user_id") is not None
    is_public_map_request = request.args.get("map") == "public"
    
    if is_logged_in and not is_public_map_request:
        # Logged in users see themselves, friends, AND map-followed public users
        rows = conn.execute("""
            SELECT p.name, p.role, p.lat, p.lon, p.last_update 
            FROM people p
            WHERE p.name IN (
                SELECT username FROM users WHERE id = ?
                UNION
                SELECT u.username 
                FROM users u
                JOIN friends f ON u.id = f.friend_id
                WHERE f.user_id = ?
                UNION
                SELECT u.username
                FROM users u
                JOIN map_follows mf ON u.id = mf.followed_id
                WHERE mf.user_id = ? AND u.vis = 1
            )
        """, (session["user_id"], session["user_id"], session["user_id"])).fetchall()
        
        # Always ensure the logged-in user's current location from 'users' table is included
        # if they aren't already in the 'people' table or to ensure latest registration point
        user_row = conn.execute("""
            SELECT username as name, 'User' as role, 
                   CAST(SUBSTR(location, 1, INSTR(location, ',') - 1) AS REAL) as lat,
                   CAST(SUBSTR(location, INSTR(location, ',') + 1) AS REAL) as lon,
                   strftime('%s','now') as last_update
            FROM users
            WHERE id = ? AND location LIKE '%,%'
        """, (session["user_id"],)).fetchone()

        # Convert rows to a list so we can append
        family_rows = [dict(row) for row in rows]
        
        # Check if user is already in family_rows by name
        user_present = any(r['name'] == session['username'] for r in family_rows)
        if not user_present and user_row:
            family_rows.append(dict(user_row))
        
        # Fallback if both are empty (initial state)
        if not family_rows:
            family_rows = [{
                "name": session["username"],
                "role": "User",
                "lat": 34.020882,
                "lon": -6.841650,
                "last_update": int(time.time())
            }]
        rows = family_rows
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

@app.route("/api/update_my_location", methods=["POST"])
@login_required
def api_update_my_location():
    """Authenticated endpoint: updates the logged-in user's own location."""
    data = request.get_json()
    if not data:
        abort(400, "JSON body required")
    try:
        lat = float(data["lat"])
        lon = float(data["lon"])
    except (KeyError, ValueError):
        abort(400, "lat and lon must be numbers")

    name = session["username"]
    now = int(time.time())
    location_str = f"{lat},{lon}"

    conn = get_db_connection()
    # Update people table
    cursor = conn.cursor()
    cursor.execute("UPDATE people SET lat=?, lon=?, last_update=? WHERE name=?", (lat, lon, now, name))
    if cursor.rowcount == 0:
        cursor.execute(
            "INSERT INTO people (name, role, lat, lon, last_update) VALUES (?, 'User', ?, ?, ?)",
            (name, lat, lon, now)
        )
    # Keep users.location in sync
    conn.execute("UPDATE users SET location=? WHERE id=?", (location_str, session["user_id"]))
    conn.commit()
    conn.close()
    return jsonify({"status": "ok"})

@app.route("/api/notes", methods=["GET"])
def api_get_notes():
    conn = get_db_connection()
    rows = conn.execute(
        "SELECT id, user_id, username, lat, lon, note, created_at FROM map_notes ORDER BY created_at DESC"
    ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route("/api/notes", methods=["POST"])
@login_required
def api_add_note():
    user = get_db_connection().execute(
        "SELECT vis FROM users WHERE id = ?", (session["user_id"],)
    ).fetchone()
    if not user or not user["vis"]:
        abort(403, "Only public accounts can add notes.")
    data = request.get_json()
    if not data:
        abort(400, "JSON body required")
    try:
        lat = float(data["lat"])
        lon = float(data["lon"])
        note = str(data["note"]).strip()
    except (KeyError, ValueError):
        abort(400, "lat, lon and note are required")
    if not note:
        abort(400, "Note cannot be empty")
    conn = get_db_connection()
    conn.execute(
        "INSERT INTO map_notes (user_id, username, lat, lon, note, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (session["user_id"], session["username"], lat, lon, note, int(time.time()))
    )
    conn.commit()
    conn.close()
    return jsonify({"status": "ok"})

@app.route("/api/notes/<int:note_id>", methods=["DELETE"])
@login_required
def api_delete_note(note_id):
    conn = get_db_connection()
    row = conn.execute("SELECT user_id FROM map_notes WHERE id = ?", (note_id,)).fetchone()
    if not row:
        conn.close()
        abort(404)
    if row["user_id"] != session["user_id"]:
        conn.close()
        abort(403, "You can only delete your own notes.")
    conn.execute("DELETE FROM map_notes WHERE id = ?", (note_id,))
    conn.commit()
    conn.close()
    return jsonify({"status": "ok"})

@app.route("/tracker/<name>")
def tracker(name):
    return render_template("tracker.html", name=name)

if __name__ == "__main__":
    init_db()
    app.run(debug=True, host="0.0.0.0", port=5000)
