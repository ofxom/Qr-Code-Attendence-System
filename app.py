import os
import secrets
import threading
import json
from datetime import datetime, timedelta, timezone
from functools import wraps
from io import BytesIO
from pathlib import Path

import qrcode
from flask import (
    Flask,
    abort,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
FILE_PATHS = {
    "students": DATA_DIR / "students.json",
    "faculty": DATA_DIR / "faculty.json",
    "sessions": DATA_DIR / "sessions.json",
    "attendance": DATA_DIR / "attendance.json",
}
QR_TOKEN_SECONDS = 30
file_lock = threading.RLock()

app = Flask(__name__)
app.config.update(
    SECRET_KEY=os.environ.get("FLASK_SECRET_KEY") or secrets.token_hex(32),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
)


def save_json(name, data):
    """Write a JSON file atomically. Call while holding file_lock."""
    path = FILE_PATHS[name]
    temporary_path = path.with_suffix(".tmp")
    with temporary_path.open("w", encoding="utf-8") as file:
        json.dump(data, file, indent=2)
    temporary_path.replace(path)


def read_json(name):
    with file_lock:
        with FILE_PATHS[name].open("r", encoding="utf-8") as file:
            return json.load(file)


def initialize_data_files():
    DATA_DIR.mkdir(exist_ok=True)
    for name, path in FILE_PATHS.items():
        if not path.exists():
            with path.open("w", encoding="utf-8") as file:
                json.dump([], file, indent=2)

    faculty = read_json("faculty")
    if not faculty:
        username = os.environ.get("FACULTY_USERNAME", "faculty").strip() or "faculty"
        password = os.environ.get("FACULTY_PASSWORD") or secrets.token_urlsafe(12)
        faculty.append(
            {
                "username": username,
                "password_hash": generate_password_hash(password),
            }
        )
        with file_lock:
            save_json("faculty", faculty)
        if not os.environ.get("FACULTY_PASSWORD"):
            print(
                "\nFirst-time faculty login\n"
                f"Username: {username}\n"
                f"Password: {password}\n"
                "Save this password now. It is not stored in plain text.\n"
            )


def current_user():
    role = session.get("role")
    if role == "student":
        return {"role": role, "id": session.get("roll_number")}
    if role == "faculty":
        return {"role": role, "id": session.get("username")}
    return None


def login_required(role):
    def decorator(view_function):
        @wraps(view_function)
        def wrapped_view(*args, **kwargs):
            user = current_user()
            if not user or user["role"] != role:
                flash("Please log in with the correct account first.", "error")
                return redirect(url_for("login"))
            return view_function(*args, **kwargs)

        return wrapped_view

    return decorator


def utc_now():
    return datetime.now(timezone.utc)


def make_token():
    return secrets.token_urlsafe(32)


def rotate_token_if_needed(attendance_session):
    now = utc_now()
    expires_at = datetime.fromisoformat(attendance_session["token_expires_at"])
    if now >= expires_at:
        attendance_session["current_token"] = make_token()
        attendance_session["token_expires_at"] = (
            now + timedelta(seconds=QR_TOKEN_SECONDS)
        ).isoformat()
        return True
    return False


def owned_session(session_id, faculty_username):
    sessions = read_json("sessions")
    for attendance_session in sessions:
        if (
            attendance_session["id"] == session_id
            and attendance_session["faculty_username"] == faculty_username
        ):
            return attendance_session
    abort(404)


def attendance_for_session(session_id):
    records = read_json("attendance")
    return [record for record in records if record["session_id"] == session_id]


def attendance_summary(roll_number):
    sessions = read_json("sessions")
    records = read_json("attendance")
    closed_session_ids = {
        item["id"] for item in sessions if item["status"] == "closed"
    }
    summary = []
    for attendance_session in sessions:
        if attendance_session["status"] != "closed":
            continue
        total_sessions = sum(
            1
            for item in sessions
            if item["subject"] == attendance_session["subject"]
            and item["status"] == "closed"
        )
        attended = sum(
            1
            for record in records
            if record["roll_number"] == roll_number
            and record["subject"] == attendance_session["subject"]
            and record["session_id"] in closed_session_ids
        )
        if not any(item["subject"] == attendance_session["subject"] for item in summary):
            summary.append(
                {
                    "subject": attendance_session["subject"],
                    "attended": attended,
                    "total": total_sessions,
                    "percentage": round(attended * 100 / total_sessions)
                    if total_sessions
                    else 0,
                }
            )
    return summary


@app.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        role = request.form.get("role", "")
        password = request.form.get("password", "")

        if role == "student":
            roll_number = request.form.get("username", "").strip().upper()
            accounts = read_json("students")
            account = next(
                (student for student in accounts if student["roll_number"] == roll_number),
                None,
            )
            if account and check_password_hash(account["password_hash"], password):
                session.clear()
                session["role"] = "student"
                session["roll_number"] = roll_number
                return redirect(url_for("student_dashboard"))
        elif role == "faculty":
            username = request.form.get("username", "").strip()
            accounts = read_json("faculty")
            account = next(
                (faculty for faculty in accounts if faculty["username"] == username),
                None,
            )
            if account and check_password_hash(account["password_hash"], password):
                session.clear()
                session["role"] = "faculty"
                session["username"] = username
                return redirect(url_for("faculty_dashboard"))

        flash("The username, password, or account type was not correct.", "error")
    return render_template("login.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        roll_number = request.form.get("roll_number", "").strip().upper()
        password = request.form.get("password", "")

        if not name or not roll_number or len(password) < 8:
            flash("Enter your name and roll number. Passwords need 8 characters.", "error")
            return render_template("register.html")

        with file_lock:
            students = read_json("students")
            if any(student["roll_number"] == roll_number for student in students):
                flash("That roll number already has an account. Please log in.", "error")
                return render_template("register.html")
            students.append(
                {
                    "name": name,
                    "roll_number": roll_number,
                    "password_hash": generate_password_hash(password),
                }
            )
            save_json("students", students)

        flash("Account created. You can now log in.", "success")
        return redirect(url_for("login"))
    return render_template("register.html")


@app.route("/register/faculty", methods=["GET", "POST"])
def register_faculty():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        if not username or len(password) < 8:
            flash("Enter a username and a password with at least 8 characters.", "error")
            return render_template("faculty_register.html")

        with file_lock:
            faculty = read_json("faculty")
            if any(account["username"].casefold() == username.casefold() for account in faculty):
                flash("That faculty username already exists. Please log in.", "error")
                return render_template("faculty_register.html")
            faculty.append(
                {
                    "username": username,
                    "password_hash": generate_password_hash(password),
                }
            )
            save_json("faculty", faculty)

        flash("Faculty account created. You can now log in.", "success")
        return redirect(url_for("login"))
    return render_template("faculty_register.html")


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for("login"))


@app.route("/faculty")
@login_required("faculty")
def faculty_dashboard():
    username = session["username"]
    sessions = [
        item
        for item in read_json("sessions")
        if item["faculty_username"] == username
    ]
    records = read_json("attendance")
    for item in sessions:
        item["attendance_count"] = sum(
            1 for record in records if record["session_id"] == item["id"]
        )
    return render_template("faculty_dashboard.html", sessions=sessions)


@app.route("/faculty/sessions", methods=["POST"])
@login_required("faculty")
def create_session():
    subject = request.form.get("subject", "").strip()
    if not subject:
        flash("Enter a subject name before starting attendance.", "error")
        return redirect(url_for("faculty_dashboard"))

    now = utc_now()
    attendance_session = {
        "id": secrets.token_urlsafe(12),
        "subject": subject,
        "faculty_username": session["username"],
        "created_at": now.isoformat(),
        "status": "active",
        "current_token": make_token(),
        "token_expires_at": (now + timedelta(seconds=QR_TOKEN_SECONDS)).isoformat(),
    }
    with file_lock:
        sessions = read_json("sessions")
        sessions.append(attendance_session)
        save_json("sessions", sessions)
    return redirect(url_for("qr_display", session_id=attendance_session["id"]))


@app.route("/faculty/sessions/<session_id>/qr")
@login_required("faculty")
def qr_display(session_id):
    attendance_session = owned_session(session_id, session["username"])
    if attendance_session["status"] != "active":
        flash("This attendance session is already closed.", "error")
        return redirect(url_for("faculty_dashboard"))
    return render_template("qr_display.html", attendance_session=attendance_session)


@app.route("/api/faculty/sessions/<session_id>/qr")
@login_required("faculty")
def current_qr(session_id):
    with file_lock:
        sessions = read_json("sessions")
        attendance_session = next(
            (
                item
                for item in sessions
                if item["id"] == session_id
                and item["faculty_username"] == session["username"]
            ),
            None,
        )
        if not attendance_session:
            abort(404)
        if attendance_session["status"] != "active":
            return jsonify({"active": False})
        token_changed = rotate_token_if_needed(attendance_session)
        if token_changed:
            save_json("sessions", sessions)
        return jsonify(
            {
                "active": True,
                "image_url": url_for("qr_image", session_id=session_id),
                "token_expires_at": attendance_session["token_expires_at"],
            }
        )


@app.route("/faculty/sessions/<session_id>/qr.png")
@login_required("faculty")
def qr_image(session_id):
    with file_lock:
        sessions = read_json("sessions")
        attendance_session = next(
            (
                item
                for item in sessions
                if item["id"] == session_id
                and item["faculty_username"] == session["username"]
                and item["status"] == "active"
            ),
            None,
        )
        if not attendance_session:
            abort(404)
        token_changed = rotate_token_if_needed(attendance_session)
        if token_changed:
            save_json("sessions", sessions)

    image = qrcode.make(attendance_session["current_token"])
    image_file = BytesIO()
    image.save(image_file, format="PNG")
    image_file.seek(0)
    return send_file(image_file, mimetype="image/png", max_age=0)


@app.route("/faculty/sessions/<session_id>/close", methods=["POST"])
@login_required("faculty")
def close_session(session_id):
    with file_lock:
        sessions = read_json("sessions")
        attendance_session = next(
            (
                item
                for item in sessions
                if item["id"] == session_id
                and item["faculty_username"] == session["username"]
            ),
            None,
        )
        if not attendance_session:
            abort(404)
        attendance_session["status"] = "closed"
        attendance_session["closed_at"] = utc_now().isoformat()
        attendance_session["current_token"] = None
        attendance_session["token_expires_at"] = None
        save_json("sessions", sessions)
    flash("Attendance session closed.", "success")
    return redirect(url_for("faculty_dashboard"))


@app.route("/student")
@login_required("student")
def student_dashboard():
    students = read_json("students")
    student = next(
        item for item in students if item["roll_number"] == session["roll_number"]
    )
    return render_template(
        "student_dashboard.html",
        student=student,
        summary=attendance_summary(student["roll_number"]),
    )


@app.route("/scan")
@login_required("student")
def scan_page():
    return render_template("scan_qr.html")


@app.route("/api/attendance", methods=["POST"])
@login_required("student")
def mark_attendance():
    token = request.form.get("token", "")
    if not token:
        return jsonify({"success": False, "message": "No QR token was provided."}), 400

    now = utc_now()
    with file_lock:
        sessions = read_json("sessions")
        attendance_session = next(
            (
                item
                for item in sessions
                if item["status"] == "active"
                and secrets.compare_digest(item["current_token"], token)
            ),
            None,
        )
        if not attendance_session:
            return jsonify(
                {"success": False, "message": "This QR code is expired or invalid."}
            ), 400

        if now >= datetime.fromisoformat(attendance_session["token_expires_at"]):
            rotate_token_if_needed(attendance_session)
            save_json("sessions", sessions)
            return jsonify(
                {"success": False, "message": "This QR code has expired. Scan the new code."}
            ), 400

        records = read_json("attendance")
        roll_number = session["roll_number"]
        if any(
            record["roll_number"] == roll_number
            and record["session_id"] == attendance_session["id"]
            for record in records
        ):
            return jsonify(
                {"success": False, "message": "You already marked attendance for this session."}
            ), 409

        students = read_json("students")
        student = next(
            item for item in students if item["roll_number"] == roll_number
        )
        records.append(
            {
                "session_id": attendance_session["id"],
                "subject": attendance_session["subject"],
                "roll_number": roll_number,
                "student_name": student["name"],
                "date": now.date().isoformat(),
                "time": now.strftime("%H:%M:%S UTC"),
                "marked_at": now.isoformat(),
            }
        )
        save_json("attendance", records)

    return jsonify(
        {
            "success": True,
            "message": f"Attendance marked for {attendance_session['subject']}.",
        }
    )


@app.route("/attendance")
@login_required("student")
def student_attendance():
    roll_number = session["roll_number"]
    records = [
        record
        for record in read_json("attendance")
        if record["roll_number"] == roll_number
    ]
    records.sort(key=lambda item: item["marked_at"], reverse=True)
    return render_template(
        "attendance.html",
        title="My attendance history",
        records=records,
        summary=attendance_summary(roll_number),
        is_faculty=False,
    )


@app.route("/faculty/sessions/<session_id>/attendance")
@login_required("faculty")
def faculty_attendance(session_id):
    attendance_session = owned_session(session_id, session["username"])
    records = attendance_for_session(session_id)
    records.sort(key=lambda item: item["marked_at"], reverse=True)
    all_sessions = read_json("sessions")
    all_records = read_json("attendance")
    students = read_json("students")
    closed_sessions = [
        item
        for item in all_sessions
        if item["subject"] == attendance_session["subject"]
        and item["status"] == "closed"
    ]
    closed_session_ids = {item["id"] for item in closed_sessions}
    attendance_percentages = {}
    for student in students:
        attended_count = sum(
            1
            for record in all_records
            if record["roll_number"] == student["roll_number"]
            and record["subject"] == attendance_session["subject"]
            and record["session_id"] in closed_session_ids
        )
        total_count = len(closed_sessions)
        attendance_percentages[student["roll_number"]] = (
            round(attended_count * 100 / total_count) if total_count else 0
        )
    return render_template(
        "attendance.html",
        title=f"{attendance_session['subject']} attendance",
        records=records,
        summary=[],
        is_faculty=True,
        attendance_percentages=attendance_percentages,
    )


@app.errorhandler(404)
def page_not_found(_error):
    return render_template("login.html"), 404


initialize_data_files()


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "5000")),
        debug=os.environ.get("FLASK_DEBUG") == "1",
    )
