from flask import Flask, render_template, request, redirect, url_for, session, jsonify, flash, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
from functools import wraps
from sqlalchemy import inspect, text
from email.message import EmailMessage
import logging
import os
import smtplib
import socket

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "shiftflow-dev-secret-change-me")
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = os.environ.get("SESSION_COOKIE_SECURE", "false").lower() == "true"
database_url = os.environ.get("DATABASE_URL")
if database_url:
    if database_url.startswith("postgres://"):
        database_url = "postgresql://" + database_url[len("postgres://"):]
    if database_url.startswith("postgresql://"):
        database_url = "postgresql+psycopg://" + database_url[len("postgresql://"):]
    app.config["SQLALCHEMY_DATABASE_URI"] = database_url
else:
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + os.path.join(app.instance_path, "shiftflow.db")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["MAIL_SERVER"] = os.environ.get("SHIFT_FLOW_SMTP_HOST", "")
app.config["MAIL_PORT"] = int(os.environ.get("SHIFT_FLOW_SMTP_PORT", "587"))
app.config["MAIL_USERNAME"] = os.environ.get("SHIFT_FLOW_SMTP_USERNAME", "")
app.config["MAIL_PASSWORD"] = os.environ.get("SHIFT_FLOW_SMTP_PASSWORD", "")
app.config["MAIL_FROM"] = os.environ.get("SHIFT_FLOW_MAIL_FROM", app.config["MAIL_USERNAME"])
app.config["MAIL_USE_TLS"] = os.environ.get("SHIFT_FLOW_SMTP_USE_TLS", "true").lower() == "true"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

os.makedirs(app.instance_path, exist_ok=True)
db = SQLAlchemy(app)


def send_email(recipient, subject, body):
    """Send an email when SMTP is configured; otherwise leave local development unaffected."""
    if not app.config["MAIL_SERVER"] or not app.config["MAIL_FROM"]:
        logger.info("Email skipped because SMTP is not configured: %s", subject)
        return False

    message = EmailMessage()
    message["From"] = app.config["MAIL_FROM"]
    message["To"] = recipient
    message["Subject"] = subject
    message.set_content(body)

    try:
        with smtplib.SMTP(app.config["MAIL_SERVER"], app.config["MAIL_PORT"], timeout=10) as smtp:
            smtp.ehlo()
            if app.config["MAIL_USE_TLS"]:
                smtp.starttls()
                smtp.ehlo()
            if app.config["MAIL_USERNAME"] and app.config["MAIL_PASSWORD"]:
                smtp.login(app.config["MAIL_USERNAME"], app.config["MAIL_PASSWORD"])
            smtp.send_message(message)
        return True
    except (OSError, smtplib.SMTPException) as error:
        logger.exception("Could not send email to %s: %s", recipient, error)
        return False


def notify_shift_assigned(shift, worker):
    send_email(
        worker.email,
        "New ShiftFlow shift awaiting your response",
        f"Hello {worker.name},\n\n"
        f"A new shift has been assigned to you:\n"
        f"Date: {shift.date}\nTime: {shift.start} - {shift.end}\n"
        f"Position: {shift.position}\n\n"
        "Log in to ShiftFlow to accept or decline this shift.\n"
    )


def notify_manager_response(shift, manager, worker):
    status_line = f"declined this shift.\nReason: {shift.decline_reason}" if shift.decision == "Declined" else "accepted this shift."
    send_email(
        manager.email,
        f"ShiftFlow shift {shift.decision.lower()}",
        f"Hello {manager.name},\n\n{worker.name} has {status_line}\n\n"
        f"Date: {shift.date}\nTime: {shift.start} - {shift.end}\n"
        f"Position: {shift.position}\n"
    )

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(160), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False)  # manager / worker
    position = db.Column(db.String(100), default="Crew Member")
    created_at = db.Column(db.DateTime, default=datetime.now)

class Shift(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.String(10), nullable=False)
    start = db.Column(db.String(5), nullable=False)
    end = db.Column(db.String(5), nullable=False)
    position = db.Column(db.String(100), nullable=False)
    manager_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    worker_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    decision = db.Column(db.String(20), default="Pending")
    decline_reason = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.now)

class Attendance(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    worker_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    shift_id = db.Column(db.Integer, db.ForeignKey("shift.id"), nullable=True)
    clock_in = db.Column(db.DateTime, nullable=True)
    clock_out = db.Column(db.DateTime, nullable=True)

def login_required(role=None):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if "user_id" not in session:
                return redirect(url_for("login"))
            if role and session.get("role") != role:
                return redirect(url_for("dashboard"))
            return fn(*args, **kwargs)
        return wrapper
    return decorator

def get_local_ip():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/mobile")
def mobile_access():
    access_url = f"http://{get_local_ip()}:5000"
    return render_template("mobile_access.html", access_url=access_url)

@app.route("/link")
def mobile_link():
    return redirect(f"http://{get_local_ip()}:5000")

@app.route("/register", methods=["GET", "POST"])
@login_required("manager")
def register():
    if request.method == "POST":
        name = request.form["name"].strip()
        email = request.form["email"].strip().lower()
        password = request.form["password"]
        role = request.form["role"]
        position = request.form.get("position", "Crew Member").strip()

        if role not in ["manager", "worker"]:
            flash("Invalid account type.")
            return redirect(url_for("register"))
        if User.query.filter_by(email=email).first():
            flash("That email is already registered.")
            return redirect(url_for("register"))
        if len(password) < 6:
            flash("Password must be at least 6 characters.")
            return redirect(url_for("register"))

        user = User(
            name=name,
            email=email,
            password_hash=generate_password_hash(password),
            role=role,
            position=position
        )
        db.session.add(user)
        db.session.commit()
        flash("Account created successfully.")
        return redirect(url_for("login"))
    return render_template("register.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form["email"].strip().lower()
        password = request.form["password"]
        user = User.query.filter_by(email=email).first()

        if not user:
            flash("No account was found for that email.")
            return redirect(url_for("login"))

        if not check_password_hash(user.password_hash, password):
            flash("Incorrect password.")
            return redirect(url_for("login"))

        session["user_id"] = user.id
        session["role"] = user.role
        session["name"] = user.name
        return redirect(url_for("dashboard"))

    return render_template("login.html")

@app.route("/health")
def health():
    return "ShiftFlow is running correctly."


@app.route("/service-worker.js")
def service_worker():
    return send_from_directory(app.static_folder, "service-worker.js", mimetype="application/javascript")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))

@app.route("/dashboard")
@login_required()
def dashboard():
    if session["role"] == "manager":
        shifts = Shift.query.filter_by(manager_id=session["user_id"]).order_by(Shift.date, Shift.start).all()
        staff = User.query.filter_by(role="worker").order_by(User.name).all()
        return render_template("manager_dashboard.html", shifts=shifts, staff=staff)
    shifts = Shift.query.filter_by(worker_id=session["user_id"]).order_by(Shift.date, Shift.start).all()
    pending_notifications = Shift.query.filter_by(worker_id=session["user_id"], decision="Pending").order_by(Shift.date, Shift.start).all()
    available = Shift.query.filter(Shift.worker_id.is_(None)).order_by(Shift.date, Shift.start).all()
    attendance = Attendance.query.filter_by(worker_id=session["user_id"]).order_by(Attendance.id.desc()).first()
    return render_template("worker_dashboard.html", shifts=shifts, available=available, attendance=attendance, pending_notifications=pending_notifications)

@app.route("/staff")
@login_required("manager")
def staff():
    workers = User.query.filter_by(role="worker").order_by(User.name).all()
    return render_template("staff.html", workers=workers)

@app.route("/staff/add", methods=["POST"])
@login_required("manager")
def add_staff():
    name = request.form["name"].strip()
    email = request.form["email"].strip().lower()
    position = request.form.get("position", "Crew Member").strip()
    temporary_password = request.form.get("password", "ShiftFlow123")
    if User.query.filter_by(email=email).first():
        flash("A user with that email already exists.")
        return redirect(url_for("staff"))
    worker = User(
        name=name,
        email=email,
        password_hash=generate_password_hash(temporary_password),
        role="worker",
        position=position
    )
    db.session.add(worker)
    db.session.commit()
    flash(f"Worker added. Temporary password: {temporary_password}")
    return redirect(url_for("staff"))

@app.route("/staff/delete/<int:user_id>", methods=["POST"])
@login_required("manager")
def delete_staff(user_id):
    worker = User.query.filter_by(id=user_id, role="worker").first_or_404()
    Shift.query.filter_by(worker_id=worker.id).update({"worker_id": None, "decision": "Pending"})
    Attendance.query.filter_by(worker_id=worker.id).delete()
    db.session.delete(worker)
    db.session.commit()
    flash("Worker removed.")
    return redirect(url_for("staff"))

@app.route("/shifts")
@login_required("manager")
def shifts():
    manager_shifts = Shift.query.filter_by(manager_id=session["user_id"]).order_by(Shift.date, Shift.start).all()
    workers = User.query.filter_by(role="worker").order_by(User.name).all()
    return render_template("shifts.html", shifts=manager_shifts, workers=workers)

@app.route("/shifts/create", methods=["POST"])
@login_required("manager")
def create_shift():
    date = request.form["date"]
    start = request.form["start"]
    end = request.form["end"]
    position = request.form["position"].strip()
    worker_id = request.form.get("worker_id")
    if end <= start:
        flash("End time must be later than start time.")
        return redirect(url_for("shifts"))

    worker_id = int(worker_id) if worker_id else None
    shift = Shift(
        date=date, start=start, end=end, position=position,
        manager_id=session["user_id"], worker_id=worker_id,
        decision="Pending" if worker_id else "Pending",
        decline_reason=None
    )
    db.session.add(shift)
    db.session.commit()
    if worker_id:
        worker = db.session.get(User, worker_id)
        if worker:
            notify_shift_assigned(shift, worker)
        flash("Shift created and sent to the worker for confirmation.")
    else:
        flash("Shift created.")
    return redirect(url_for("shifts"))

@app.route("/shifts/<int:shift_id>/delete", methods=["POST"])
@login_required("manager")
def delete_shift(shift_id):
    shift = Shift.query.filter_by(id=shift_id, manager_id=session["user_id"]).first_or_404()
    Attendance.query.filter_by(shift_id=shift.id).delete()
    db.session.delete(shift)
    db.session.commit()
    flash("Shift deleted.")
    return redirect(url_for("shifts"))

@app.route("/shifts/<int:shift_id>/accept", methods=["POST"])
@login_required("worker")
def accept_shift(shift_id):
    shift = Shift.query.get_or_404(shift_id)
    if shift.worker_id != session["user_id"]:
        flash("This shift is not assigned to you.")
        return redirect(url_for("dashboard"))
    shift.decision = "Accepted"
    shift.decline_reason = None
    db.session.commit()
    worker = db.session.get(User, session["user_id"])
    manager = db.session.get(User, shift.manager_id)
    if worker and manager:
        notify_manager_response(shift, manager, worker)
    flash("Shift accepted.")
    return redirect(url_for("dashboard"))

@app.route("/shifts/<int:shift_id>/decline", methods=["POST"])
@login_required("worker")
def decline_shift(shift_id):
    shift = Shift.query.filter_by(id=shift_id, worker_id=session["user_id"]).first()
    if not shift:
        flash("This shift is not assigned to you.")
        return redirect(url_for("dashboard"))

    reason = request.form.get("reason", "").strip()
    if not reason:
        flash("Please provide a reason for declining this shift.")
        return redirect(url_for("dashboard"))

    shift.decision = "Declined"
    shift.decline_reason = reason
    db.session.commit()
    worker = db.session.get(User, session["user_id"])
    manager = db.session.get(User, shift.manager_id)
    if worker and manager:
        notify_manager_response(shift, manager, worker)
    flash("Shift declined. Your reason has been shared with the manager.")
    return redirect(url_for("dashboard"))

@app.route("/attendance")
@login_required("worker")
def attendance_page():
    records = Attendance.query.filter_by(worker_id=session["user_id"]).order_by(Attendance.id.desc()).all()
    return render_template("attendance.html", records=records)

@app.route("/attendance/clock-in", methods=["POST"])
@login_required("worker")
def clock_in():
    existing = Attendance.query.filter_by(worker_id=session["user_id"], clock_out=None).first()
    if existing:
        flash("You are already clocked in.")
        return redirect(url_for("dashboard"))

    shift = Shift.query.filter_by(worker_id=session["user_id"], decision="Accepted").order_by(Shift.date, Shift.start).first()
    record = Attendance(worker_id=session["user_id"], shift_id=shift.id if shift else None, clock_in=datetime.now())
    db.session.add(record)
    db.session.commit()
    flash("Clocked in successfully.")
    return redirect(url_for("dashboard"))

@app.route("/attendance/clock-out", methods=["POST"])
@login_required("worker")
def clock_out():
    record = Attendance.query.filter_by(worker_id=session["user_id"], clock_out=None).order_by(Attendance.id.desc()).first()
    if not record:
        flash("You are not currently clocked in.")
        return redirect(url_for("dashboard"))
    record.clock_out = datetime.now()
    db.session.commit()
    flash("Clocked out successfully.")
    return redirect(url_for("dashboard"))

@app.route("/manager/attendance")
@login_required("manager")
def manager_attendance():
    records = Attendance.query.order_by(Attendance.id.desc()).all()
    workers = {u.id: u for u in User.query.filter_by(role="worker").all()}
    return render_template("manager_attendance.html", records=records, workers=workers)

@app.route("/profile", methods=["GET", "POST"])
@login_required()
def profile():
    user = User.query.get_or_404(session["user_id"])
    if request.method == "POST":
        user.name = request.form["name"].strip()
        user.position = request.form.get("position", user.position).strip()
        db.session.commit()
        session["name"] = user.name
        flash("Profile updated.")
        return redirect(url_for("profile"))
    return render_template("profile.html", user=user)

@app.route("/api/stats")
@login_required()
def stats():
    if session["role"] == "manager":
        sid = session["user_id"]
        return jsonify({
            "staff": User.query.filter_by(role="worker").count(),
            "shifts": Shift.query.filter_by(manager_id=sid).count(),
            "accepted": Shift.query.filter_by(manager_id=sid, decision="Accepted").count(),
            "pending": Shift.query.filter_by(manager_id=sid, decision="Pending").count()
        })
    wid = session["user_id"]
    return jsonify({
        "upcoming": Shift.query.filter_by(worker_id=wid, decision="Accepted").count(),
        "available": Shift.query.filter_by(worker_id=None).count()
    })

def seed_demo():
    # Always make sure the two test accounts exist and have the known password.
    manager = User.query.filter_by(email="manager@shiftflow.test").first()
    if not manager:
        manager = User(
            name="Demo Manager",
            email="manager@shiftflow.test",
            password_hash=generate_password_hash("password123"),
            role="manager",
            position="Team Manager"
        )
        db.session.add(manager)
        db.session.commit()
    else:
        manager.password_hash = generate_password_hash("password123")
        manager.role = "manager"
        manager.position = "Team Manager"
        db.session.commit()

    worker = User.query.filter_by(email="worker@shiftflow.test").first()
    if not worker:
        worker = User(
            name="Demo Worker",
            email="worker@shiftflow.test",
            password_hash=generate_password_hash("password123"),
            role="worker",
            position="Crew Member"
        )
        db.session.add(worker)
        db.session.commit()
    else:
        worker.password_hash = generate_password_hash("password123")
        worker.role = "worker"
        worker.position = "Crew Member"
        db.session.commit()

    # Add demo shifts only if the manager currently has none.
    if Shift.query.filter_by(manager_id=manager.id).count() == 0:
        today = datetime.now().strftime("%Y-%m-%d")
        demo = Shift(
            date=today, start="10:00", end="16:00",
            position="Crew Member",
            manager_id=manager.id, worker_id=worker.id,
            decision="Accepted"
        )
        available = Shift(
            date=today, start="17:00", end="22:00",
            position="Front of House",
            manager_id=manager.id,
            decision="Pending"
        )
        db.session.add_all([demo, available])
        db.session.commit()


def seed_initial_manager():
    email = os.environ.get("SHIFT_FLOW_ADMIN_EMAIL", "").strip().lower()
    password = os.environ.get("SHIFT_FLOW_ADMIN_PASSWORD", "")
    if not email or not password or User.query.filter_by(email=email).first():
        return

    manager = User(
        name=os.environ.get("SHIFT_FLOW_ADMIN_NAME", "ShiftFlow Manager").strip(),
        email=email,
        password_hash=generate_password_hash(password),
        role="manager",
        position="Team Manager"
    )
    db.session.add(manager)
    db.session.commit()


def ensure_database_schema():
    with db.engine.begin() as connection:
        columns = inspect(connection).get_columns("shift")
        if not any(column["name"] == "decline_reason" for column in columns):
            connection.execute(text("ALTER TABLE shift ADD COLUMN decline_reason VARCHAR(255)"))

with app.app_context():
    db.create_all()
    ensure_database_schema()
    if os.environ.get("SHIFT_FLOW_SEED_DEMO", "true").lower() == "true":
        seed_demo()
    seed_initial_manager()

if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "5000")),
        debug=os.environ.get("FLASK_DEBUG", "false").lower() == "true"
    )
