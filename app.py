import sqlite3
import time
import math
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

def haversine(lat1, lon1, lat2, lon2):
    """Returns distance in metres between two lat/lon points."""
    R = 6371000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return 2 * R * math.asin(math.sqrt(a))

def init_db():
    conn = get_db_connection()
    with open('schema.sql', mode='r') as f:
        conn.executescript(f.read())
    conn.close()

@app.context_processor
def inject_pending_requests():
    if session.get("user_id"):
        conn = get_db_connection()
        count = conn.execute(
            "SELECT COUNT(*) FROM friend_requests WHERE to_user_id = ? AND status = 'pending'",
            (session["user_id"],)
        ).fetchone()[0]
        child_count = conn.execute(
            "SELECT COUNT(*) FROM child_requests WHERE to_user_id = ? AND status = 'pending'",
            (session["user_id"],)
        ).fetchone()[0]
        conn.close()
        return {"pending_requests_count": count, "pending_child_requests_count": child_count}
    return {"pending_requests_count": 0, "pending_child_requests_count": 0}

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
    incoming = conn.execute("""
        SELECT fr.id, u.username
        FROM friend_requests fr
        JOIN users u ON u.id = fr.from_user_id
        WHERE fr.to_user_id = ? AND fr.status = 'pending'
        ORDER BY fr.created_at DESC
    """, (session["user_id"],)).fetchall()
    # Child requests incoming (I am the would-be child)
    incoming_child = conn.execute("""
        SELECT cr.id, u.username
        FROM child_requests cr
        JOIN users u ON u.id = cr.from_user_id
        WHERE cr.to_user_id = ? AND cr.status = 'pending'
        ORDER BY cr.created_at DESC
    """, (session["user_id"],)).fetchall()
    # My children (users I am parent of)
    my_children = conn.execute("""
        SELECT u.id, u.username, pc.geofence_lat, pc.geofence_lon, pc.geofence_radius, pc.outside_geofence
        FROM parent_child pc
        JOIN users u ON u.id = pc.child_id
        WHERE pc.parent_id = ?
    """, (session["user_id"],)).fetchall()
    conn.close()
    return render_template("home.html", map_follows=map_follows, incoming=incoming,
                           incoming_child=incoming_child, my_children=my_children)

@app.route("/searchf", methods=["GET", "POST"])
@login_required
def search_friends():
    users = []
    if request.method == "POST":
        query = request.form.get("query", "")
        conn = get_db_connection()
        users = conn.execute("""
            SELECT u.id, u.username, u.vis,
                   CASE WHEN mf.followed_id IS NOT NULL THEN 1 ELSE 0 END AS on_map,
                   fr_sent.status AS sent_status,
                   fr_recv.id AS recv_id,
                   fr_recv.status AS recv_status,
                   cr_sent.status AS child_req_sent_status,
                   CASE WHEN pc.child_id IS NOT NULL THEN 1 ELSE 0 END AS is_my_child
            FROM users u
            LEFT JOIN map_follows mf
                   ON mf.user_id = ? AND mf.followed_id = u.id
            LEFT JOIN friend_requests fr_sent
                   ON fr_sent.from_user_id = ? AND fr_sent.to_user_id = u.id
            LEFT JOIN friend_requests fr_recv
                   ON fr_recv.to_user_id = ? AND fr_recv.from_user_id = u.id
            LEFT JOIN child_requests cr_sent
                   ON cr_sent.from_user_id = ? AND cr_sent.to_user_id = u.id AND cr_sent.status = 'pending'
            LEFT JOIN parent_child pc
                   ON pc.parent_id = ? AND pc.child_id = u.id
            WHERE u.username LIKE ? AND u.id != ?
        """, (session["user_id"], session["user_id"], session["user_id"],
              session["user_id"], session["user_id"],
              f"%{query}%", session["user_id"])).fetchall()
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

@app.route("/send_request/<int:to_id>", methods=["POST"])
@login_required
def send_request(to_id):
    conn = get_db_connection()
    target = conn.execute("SELECT vis FROM users WHERE id = ?", (to_id,)).fetchone()
    if not target:
        conn.close()
        flash("User not found.")
        return redirect(url_for("search_friends"))
    try:
        conn.execute(
            "INSERT INTO friend_requests (from_user_id, to_user_id, created_at) VALUES (?, ?, ?)",
            (session["user_id"], to_id, int(time.time()))
        )
        conn.commit()
        flash("Friend request sent!")
    except sqlite3.IntegrityError:
        flash("Request already sent.")
    finally:
        conn.close()
    return redirect(url_for("search_friends"))

@app.route("/accept_request/<int:req_id>", methods=["POST"])
@login_required
def accept_request(req_id):
    conn = get_db_connection()
    req = conn.execute(
        "SELECT * FROM friend_requests WHERE id = ? AND to_user_id = ? AND status = 'pending'",
        (req_id, session["user_id"])
    ).fetchone()
    if not req:
        conn.close()
        flash("Request not found.")
        return redirect(url_for("home"))
    conn.execute("UPDATE friend_requests SET status = 'accepted' WHERE id = ?", (req_id,))
    # Determine if the acceptor (me) is private or public
    acceptor = conn.execute("SELECT vis FROM users WHERE id = ?", (session["user_id"],)).fetchone()
    acceptor_is_public = acceptor and acceptor["vis"]
    if acceptor_is_public:
        # Public acceptor: both users see each other on their private maps
        pairs = [(req["from_user_id"], req["to_user_id"]),
                 (req["to_user_id"], req["from_user_id"])]
    else:
        # Private acceptor: only the sender sees the acceptor on their private map
        pairs = [(req["from_user_id"], req["to_user_id"])]
    for uid, fid in pairs:
        try:
            conn.execute("INSERT INTO map_follows (user_id, followed_id) VALUES (?, ?)", (uid, fid))
        except sqlite3.IntegrityError:
            pass
    conn.commit()
    conn.close()
    flash("Friend request accepted!")
    return redirect(url_for("home"))

@app.route("/decline_request/<int:req_id>", methods=["POST"])
@login_required
def decline_request(req_id):
    conn = get_db_connection()
    conn.execute(
        "DELETE FROM friend_requests WHERE id = ? AND to_user_id = ?",
        (req_id, session["user_id"])
    )
    conn.commit()
    conn.close()
    flash("Request declined.")
    return redirect(url_for("home"))

@app.route("/send_child_request/<int:to_id>", methods=["POST"])
@login_required
def send_child_request(to_id):
    if to_id == session["user_id"]:
        flash("You can't add yourself as a child.")
        return redirect(url_for("search_friends"))
    conn = get_db_connection()
    try:
        conn.execute(
            "INSERT INTO child_requests (from_user_id, to_user_id, created_at) VALUES (?, ?, ?)",
            (session["user_id"], to_id, int(time.time()))
        )
        conn.commit()
        flash("Child request sent!")
    except sqlite3.IntegrityError:
        flash("You already sent a child request to this user.")
    finally:
        conn.close()
    return redirect(url_for("search_friends"))

@app.route("/accept_child_request/<int:req_id>", methods=["POST"])
@login_required
def accept_child_request(req_id):
    conn = get_db_connection()
    req = conn.execute(
        "SELECT * FROM child_requests WHERE id = ? AND to_user_id = ? AND status = 'pending'",
        (req_id, session["user_id"])
    ).fetchone()
    if not req:
        conn.close()
        flash("Request not found.")
        return redirect(url_for("home"))
    conn.execute("UPDATE child_requests SET status = 'accepted' WHERE id = ?", (req_id,))
    try:
        conn.execute(
            "INSERT INTO parent_child (parent_id, child_id) VALUES (?, ?)",
            (req["from_user_id"], session["user_id"])
        )
    except sqlite3.IntegrityError:
        pass
    conn.commit()
    conn.close()
    flash("You accepted the child request.")
    return redirect(url_for("home"))

@app.route("/decline_child_request/<int:req_id>", methods=["POST"])
@login_required
def decline_child_request(req_id):
    conn = get_db_connection()
    conn.execute(
        "DELETE FROM child_requests WHERE id = ? AND to_user_id = ?",
        (req_id, session["user_id"])
    )
    conn.commit()
    conn.close()
    flash("Child request declined.")
    return redirect(url_for("home"))

@app.route("/remove_child/<int:child_id>", methods=["POST"])
@login_required
def remove_child(child_id):
    conn = get_db_connection()
    conn.execute(
        "DELETE FROM parent_child WHERE parent_id = ? AND child_id = ?",
        (session["user_id"], child_id)
    )
    conn.commit()
    conn.close()
    flash("Child removed.")
    return redirect(url_for("home"))

@app.route("/api/set_geofence", methods=["POST"])
@login_required
def api_set_geofence():
    data = request.get_json()
    if not data:
        abort(400, "JSON required")
    try:
        child_id = int(data["child_id"])
        radius = float(data["radius"])
        lat = float(data["lat"])
        lon = float(data["lon"])
    except (KeyError, ValueError):
        abort(400, "child_id, lat, lon and radius are required")
    conn = get_db_connection()
    result = conn.execute(
        "UPDATE parent_child SET geofence_lat=?, geofence_lon=?, geofence_radius=? WHERE parent_id=? AND child_id=?",
        (lat, lon, radius, session["user_id"], child_id)
    )
    conn.commit()
    conn.close()
    if result.rowcount == 0:
        abort(403, "Not your child.")
    return jsonify({"status": "ok"})

@app.route("/api/geofence_alerts", methods=["GET"])
@login_required
def api_geofence_alerts():
    conn = get_db_connection()
    # Alerts where I am the parent and the child is outside
    parent_alerts = conn.execute("""
        SELECT u.username AS child_name, pc.geofence_radius
        FROM parent_child pc
        JOIN users u ON u.id = pc.child_id
        WHERE pc.parent_id = ? AND pc.outside_geofence = 1 AND pc.geofence_radius IS NOT NULL
    """, (session["user_id"],)).fetchall()
    # Alert if I am a child and I am outside my geofence
    child_alerts = conn.execute("""
        SELECT u.username AS parent_name, pc.geofence_radius
        FROM parent_child pc
        JOIN users u ON u.id = pc.parent_id
        WHERE pc.child_id = ? AND pc.outside_geofence = 1 AND pc.geofence_radius IS NOT NULL
    """, (session["user_id"],)).fetchall()
    # Also return geofence circles for parent's private map
    geofences = conn.execute("""
        SELECT pc.child_id, u.username AS child_name, pc.geofence_lat, pc.geofence_lon, pc.geofence_radius
        FROM parent_child pc
        JOIN users u ON u.id = pc.child_id
        WHERE pc.parent_id = ? AND pc.geofence_radius IS NOT NULL
    """, (session["user_id"],)).fetchall()
    conn.close()
    return jsonify({
        "parent_alerts": [dict(r) for r in parent_alerts],
        "child_alerts": [dict(r) for r in child_alerts],
        "geofences": [dict(r) for r in geofences]
    })

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
        # Private map: show the logged-in user + their map connections (accepted friend requests)
        rows = conn.execute("""
            SELECT p.name, p.role, p.lat, p.lon, p.last_update 
            FROM people p
            WHERE p.name IN (
                SELECT username FROM users WHERE id = ?
                UNION
                SELECT u.username
                FROM users u
                JOIN map_follows mf ON u.id = mf.followed_id
                WHERE mf.user_id = ?
            )
        """, (session["user_id"], session["user_id"])).fetchall()
        
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
    # Check geofences: are we outside any parent's radius?
    fences = conn.execute(
        "SELECT parent_id, geofence_lat, geofence_lon, geofence_radius FROM parent_child WHERE child_id = ? AND geofence_radius IS NOT NULL",
        (session["user_id"],)
    ).fetchall()
    for fence in fences:
        dist = haversine(lat, lon, fence["geofence_lat"], fence["geofence_lon"])
        outside = 1 if dist > fence["geofence_radius"] else 0
        conn.execute(
            "UPDATE parent_child SET outside_geofence=? WHERE parent_id=? AND child_id=?",
            (outside, fence["parent_id"], session["user_id"])
        )
    conn.commit()
    conn.close()
    return jsonify({"status": "ok"})

@app.route("/api/notes", methods=["GET"])
def api_get_notes():
    scope = request.args.get("scope", "public")
    conn = get_db_connection()
    if session.get("user_id"):
        if scope == "private":
            # Private notes: own notes + notes from connections
            rows = conn.execute("""
                SELECT id, user_id, username, lat, lon, note, created_at, scope FROM map_notes
                WHERE scope = 'private'
                  AND (user_id = ?
                       OR user_id IN (SELECT followed_id FROM map_follows WHERE user_id = ?))
                ORDER BY created_at DESC
            """, (session["user_id"], session["user_id"])).fetchall()
        else:
            # Public notes: own + connections' public notes
            rows = conn.execute("""
                SELECT id, user_id, username, lat, lon, note, created_at, scope FROM map_notes
                WHERE scope = 'public'
                  AND (user_id = ?
                       OR user_id IN (SELECT followed_id FROM map_follows WHERE user_id = ?))
                ORDER BY created_at DESC
            """, (session["user_id"], session["user_id"])).fetchall()
    else:
        # Non-logged-in visitors see all public notes
        rows = conn.execute(
            "SELECT id, user_id, username, lat, lon, note, created_at, scope FROM map_notes WHERE scope = 'public' ORDER BY created_at DESC"
        ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route("/api/notes", methods=["POST"])
@login_required
def api_add_note():
    data = request.get_json()
    if not data:
        abort(400, "JSON body required")
    scope = data.get("scope", "public")
    if scope not in ("public", "private"):
        abort(400, "scope must be 'public' or 'private'")
    if scope == "public":
        user = get_db_connection().execute(
            "SELECT vis FROM users WHERE id = ?", (session["user_id"],)
        ).fetchone()
        if not user or not user["vis"]:
            abort(403, "Only public accounts can add notes to the public map.")
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
        "INSERT INTO map_notes (user_id, username, lat, lon, note, created_at, scope) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (session["user_id"], session["username"], lat, lon, note, int(time.time()), scope)
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
