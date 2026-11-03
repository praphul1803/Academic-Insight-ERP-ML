import csv
import io
import math
import os
import re
from collections import Counter
from datetime import date, datetime, timedelta
from functools import wraps

from dotenv import load_dotenv
from flask import (
    Flask,
    abort,
    flash,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)
from flask_sqlalchemy import SQLAlchemy
from flask_wtf import CSRFProtect
from sqlalchemy import func, inspect
from sqlalchemy.exc import IntegrityError
from werkzeug.security import check_password_hash, generate_password_hash

load_dotenv()

app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "development-only-change-me")
instance_dir = os.path.join(os.path.dirname(__file__), "instance")
os.makedirs(instance_dir, exist_ok=True)
app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv(
    "DATABASE_URL",
    "sqlite:///"
    + os.path.abspath(os.path.join(instance_dir, "college_erp.db")).replace("\\", "/"),
)
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)
csrf = CSRFProtect(app)


def ensure_prediction_schema():
    with app.app_context():
        with db.engine.begin() as conn:
            inspector = inspect(conn)
            table_names = set(inspector.get_table_names())
            batch_columns = (
                {column["name"] for column in inspector.get_columns("prediction_batch")}
                if "prediction_batch" in table_names
                else set()
            )
            if batch_columns and "average_class_performance" not in batch_columns:
                conn.exec_driver_sql(
                    "ALTER TABLE prediction_batch ADD COLUMN average_class_performance FLOAT NOT NULL DEFAULT 0.0"
                )

            staff_columns = (
                {column["name"] for column in inspector.get_columns("staff")}
                if "staff" in table_names
                else set()
            )
            if staff_columns and "phone" not in staff_columns:
                conn.exec_driver_sql("ALTER TABLE staff ADD COLUMN phone VARCHAR(20)")

            assessment_columns = (
                {column["name"] for column in inspector.get_columns("assessment_record")}
                if "assessment_record" in table_names
                else set()
            )
            if assessment_columns and "staff_id" not in assessment_columns:
                conn.exec_driver_sql("ALTER TABLE assessment_record ADD COLUMN staff_id INTEGER")

            notice_columns = (
                {column["name"] for column in inspector.get_columns("notice")}
                if "notice" in table_names
                else set()
            )
            if notice_columns and "is_published" not in notice_columns:
                conn.exec_driver_sql(
                    "ALTER TABLE notice ADD COLUMN is_published BOOLEAN NOT NULL DEFAULT 1"
                )

            result_columns = (
                {column["name"] for column in inspector.get_columns("prediction_result")}
                if "prediction_result" in table_names
                else set()
            )
            for column_name, column_sql in {
                "unit_test_marks": "FLOAT NOT NULL DEFAULT 0.0",
                "quiz_marks": "FLOAT NOT NULL DEFAULT 0.0",
                "total_marks": "FLOAT NOT NULL DEFAULT 0.0",
                "overall_percentage": "FLOAT NOT NULL DEFAULT 0.0",
            }.items():
                if result_columns and column_name not in result_columns:
                    conn.exec_driver_sql(
                        f"ALTER TABLE prediction_result ADD COLUMN {column_name} {column_sql}"
                    )


class Timestamp:
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )


class User(Timestamp, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(12), nullable=False)
    active = db.Column(db.Boolean, default=True, nullable=False)
    student = db.relationship(
        "Student",
        backref="user",
        uselist=False,
        cascade="all, delete-orphan",
    )
    staff = db.relationship(
        "Staff",
        backref="user",
        uselist=False,
        cascade="all, delete-orphan",
    )


class Student(Timestamp, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_code = db.Column(db.String(30), unique=True, nullable=False)
    full_name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    course = db.Column(db.String(100), nullable=False)
    department = db.Column(db.String(100), nullable=False)
    semester = db.Column(db.Integer, nullable=False)
    division = db.Column(db.String(10), nullable=False)
    phone = db.Column(db.String(20))
    user_id = db.Column(
        db.Integer, db.ForeignKey("user.id"), unique=True, nullable=False
    )
    attendance = db.relationship(
        "Attendance",
        backref="student",
        cascade="all, delete-orphan",
    )
    marks = db.relationship(
        "Mark",
        backref="student",
        cascade="all, delete-orphan",
    )
    fee = db.relationship(
        "Fee",
        backref="student",
        uselist=False,
        cascade="all, delete-orphan",
    )


class Course(Timestamp, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    code = db.Column(db.String(20), unique=True, nullable=False)
    department = db.Column(db.String(100), nullable=False)
    duration_years = db.Column(db.Integer, nullable=False, default=3)
    description = db.Column(db.Text, default="")
    subjects = db.relationship("Subject", backref="course", lazy=True)


class Subject(Timestamp, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    code = db.Column(db.String(30), unique=True, nullable=False)
    course_id = db.Column(db.Integer, db.ForeignKey("course.id"))
    semester = db.Column(db.Integer, nullable=False, default=1)
    staff_id = db.Column(db.Integer, db.ForeignKey("staff.id"))
    staff = db.relationship("Staff", backref=db.backref("subjects", lazy=True))


class Staff(Timestamp, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    employee_code = db.Column(db.String(30), unique=True, nullable=False)
    full_name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    department = db.Column(db.String(100), nullable=False)
    phone = db.Column(db.String(20))
    assigned_subjects = db.Column(db.String(300), default="")
    user_id = db.Column(
        db.Integer, db.ForeignKey("user.id"), unique=True, nullable=False
    )


class Attendance(Timestamp, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(
        db.Integer,
        db.ForeignKey("student.id"),
        nullable=False,
        index=True,
    )
    subject = db.Column(db.String(120), nullable=False)
    attendance_date = db.Column(db.Date, nullable=False)
    period = db.Column(db.Integer, nullable=False, default=1)
    status = db.Column(db.String(10), nullable=False)

    __table_args__ = (
        db.UniqueConstraint("student_id", "subject", "attendance_date", "period"),
    )


class Mark(Timestamp, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("student.id"), nullable=False)
    subject = db.Column(db.String(120), nullable=False)
    test1 = db.Column(db.Float, default=0)
    test2 = db.Column(db.Float, default=0)
    assignment = db.Column(db.Float, default=0)
    practical = db.Column(db.Float, default=0)
    project = db.Column(db.Float, default=0)

    __table_args__ = (db.UniqueConstraint("student_id", "subject"),)

    @property
    def total(self):
        return sum(
            [
                self.test1 or 0,
                self.test2 or 0,
                self.assignment or 0,
                self.practical or 0,
                self.project or 0,
            ]
        )


class Fee(Timestamp, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(
        db.Integer,
        db.ForeignKey("student.id"),
        unique=True,
        nullable=False,
    )
    total = db.Column(db.Float, nullable=False)
    paid = db.Column(db.Float, default=0, nullable=False)
    payments = db.relationship(
        "FeePayment",
        backref="fee",
        cascade="all, delete-orphan",
        order_by="FeePayment.payment_date.desc()",
    )

    @property
    def pending(self):
        return max(0, self.total - self.paid)


class FeePayment(Timestamp, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    fee_id = db.Column(db.Integer, db.ForeignKey("fee.id"), nullable=False, index=True)
    amount = db.Column(db.Float, nullable=False)
    payment_date = db.Column(db.Date, nullable=False, default=date.today)
    reference = db.Column(db.String(100), default="")


class AssessmentRecord(Timestamp, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("student.id"), nullable=False, index=True)
    subject_id = db.Column(db.Integer, db.ForeignKey("subject.id"), nullable=False, index=True)
    unit_test_marks = db.Column(db.Float, nullable=False, default=0)
    assignment_marks = db.Column(db.Float, nullable=False, default=0)
    quiz_marks = db.Column(db.Float, nullable=False, default=0)
    staff_id = db.Column(db.Integer)
    student = db.relationship("Student", backref=db.backref("assessment_records", lazy=True))
    subject = db.relationship("Subject", backref=db.backref("assessment_records", lazy=True))

    __table_args__ = (db.UniqueConstraint("student_id", "subject_id"),)

    @property
    def total(self):
        return self.unit_test_marks + self.assignment_marks + self.quiz_marks


class Notice(Timestamp, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(160), nullable=False)
    body = db.Column(db.Text, nullable=False)
    audience = db.Column(db.String(30), default="All")
    category = db.Column(db.String(50), default="General")
    published_on = db.Column(db.Date, default=date.today)
    is_published = db.Column(db.Boolean, nullable=False, default=True)
    author_id = db.Column(db.Integer, db.ForeignKey("user.id"))


class PredictionBatch(Timestamp, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(200), nullable=False)
    report_name = db.Column(db.String(200), nullable=False)
    total_students = db.Column(db.Integer, default=0, nullable=False)
    good_students = db.Column(db.Integer, default=0, nullable=False)
    average_students = db.Column(db.Integer, default=0, nullable=False)
    poor_students = db.Column(db.Integer, default=0, nullable=False)
    high_risk_students = db.Column(db.Integer, default=0, nullable=False)
    slow_learners = db.Column(db.Integer, default=0, nullable=False)
    average_class_performance = db.Column(db.Float, default=0.0, nullable=False)
    status = db.Column(db.String(30), default="processed", nullable=False)
    results = db.relationship(
        "PredictionResult",
        backref="batch",
        cascade="all, delete-orphan",
    )


class PredictionResult(Timestamp, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    batch_id = db.Column(db.Integer, db.ForeignKey("prediction_batch.id"), nullable=False)
    student_id = db.Column(db.String(60), nullable=False)
    student_name = db.Column(db.String(200), nullable=False)
    attendance_percentage = db.Column(db.Float, nullable=False, default=0.0)
    internal_marks = db.Column(db.Float, nullable=False, default=0.0)
    mid_term_marks = db.Column(db.Float, nullable=False, default=0.0)
    assignment_marks = db.Column(db.Float, nullable=False, default=0.0)
    study_hours = db.Column(db.Float, default=0.0)
    unit_test_marks = db.Column(db.Float, nullable=False, default=0.0)
    quiz_marks = db.Column(db.Float, nullable=False, default=0.0)
    total_marks = db.Column(db.Float, nullable=False, default=0.0)
    overall_percentage = db.Column(db.Float, nullable=False, default=0.0)
    predicted_score = db.Column(db.Float, nullable=False)
    predicted_result = db.Column(db.String(20), nullable=False)
    performance_status = db.Column(db.String(20), nullable=False)
    risk_level = db.Column(db.String(20), nullable=False)
    slow_learner = db.Column(db.String(10), nullable=False, default="No")


class IndividualPrediction(Timestamp, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("student.id"), nullable=False, index=True)
    created_by_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    unit_test_marks = db.Column(db.Float, nullable=False)
    assignment_marks = db.Column(db.Float, nullable=False)
    quiz_marks = db.Column(db.Float, nullable=False)
    total_marks = db.Column(db.Float, nullable=False)
    overall_percentage = db.Column(db.Float, nullable=False)
    predicted_performance = db.Column(db.String(20), nullable=False)
    performance_status = db.Column(db.String(20), nullable=False)
    slow_learner = db.Column(db.String(10), nullable=False)
    student = db.relationship(
        "Student",
        backref=db.backref("individual_predictions", lazy=True),
    )


def sync_academic_catalog():
    existing_courses = {
        course.name.casefold(): course
        for course in Course.query.all()
    }
    for course_name, department in db.session.query(
        Student.course, Student.department
    ).distinct():
        if course_name and course_name.casefold() not in existing_courses:
            code = re.sub(r"[^A-Za-z0-9]+", "", course_name).upper()[:20] or "COURSE"
            suffix = 1
            unique_code = code
            while Course.query.filter_by(code=unique_code).first():
                suffix += 1
                unique_code = f"{code[:17]}{suffix}"
            course = Course(
                name=course_name,
                code=unique_code,
                department=department or "General",
                duration_years=3,
            )
            db.session.add(course)
            existing_courses[course_name.casefold()] = course
    db.session.flush()

    legacy_subjects = {
        subject.strip()
        for (subject,) in db.session.query(Mark.subject).distinct()
        if subject and subject.strip()
    }
    legacy_subjects.update(
        subject.strip()
        for (subject,) in db.session.query(Attendance.subject).distinct()
        if subject and subject.strip()
    )
    for staff_member in Staff.query.all():
        legacy_subjects.update(
            subject.strip()
            for subject in (staff_member.assigned_subjects or "").split(",")
            if subject.strip()
        )
    existing_subject_names = {
        subject.name.casefold() for subject in Subject.query.all()
    }
    used_codes = {subject.code.casefold() for subject in Subject.query.all()}
    for subject_name in sorted(legacy_subjects):
        if subject_name.casefold() in existing_subject_names:
            continue
        base_code = re.sub(r"[^A-Za-z0-9]+", "", subject_name).upper()[:25] or "SUBJECT"
        subject_code = base_code
        suffix = 1
        while subject_code.casefold() in used_codes:
            suffix += 1
            subject_code = f"{base_code[:22]}{suffix}"
        used_codes.add(subject_code.casefold())
        subject_staff = next(
            (
                staff_member
                for staff_member in Staff.query.all()
                if subject_name.casefold()
                in {
                    item.strip().casefold()
                    for item in (staff_member.assigned_subjects or "").split(",")
                }
            ),
            None,
        )
        db.session.add(
            Subject(
                name=subject_name,
                code=subject_code,
                semester=1,
                staff_id=subject_staff.id if subject_staff else None,
            )
        )
    db.session.commit()


with app.app_context():
    db.create_all()
    ensure_prediction_schema()
    sync_academic_catalog()


def current_user():
    uid = session.get("erp_uid")
    return db.session.get(User, uid) if isinstance(uid, int) else None


@app.context_processor
def inject_user():
    return {
        "me": current_user(),
        "today": date.today(),
        "attendance_pct": attendance_pct,
    }


@app.template_filter("course_student_count")
def course_student_count(course_name):
    return Student.query.filter_by(course=course_name).count()


def roles(*allowed):
    def wrap(fn):
        @wraps(fn)
        def inner(*args, **kwargs):
            user = current_user()
            if not user or not user.active:
                return redirect(url_for("login"))
            if user.role not in allowed:
                abort(403)
            return fn(*args, **kwargs)

        return inner

    return wrap


def attendance_pct(student_id):
    rows = Attendance.query.filter_by(student_id=student_id).all()
    if not rows:
        return 0
    return round(100 * sum(row.status == "Present" for row in rows) / len(rows), 1)


def students_assigned_to_staff(staff):
    subjects = [
        subject.strip().casefold()
        for subject in (staff.assigned_subjects or "").split(",")
        if subject.strip()
    ]
    assigned_subjects = staff_subjects(staff)
    if not assigned_subjects:
        return []

    students_with_marks = db.session.query(Mark.student_id).filter(
        func.lower(Mark.subject).in_(subjects)
    )
    students_with_attendance = db.session.query(Attendance.student_id).filter(
        func.lower(Attendance.subject).in_(subjects)
    )
    assigned_subject_ids = [subject.id for subject in assigned_subjects]
    students_with_assessments = (
        db.session.query(AssessmentRecord.student_id).filter(
            AssessmentRecord.subject_id.in_(assigned_subject_ids)
        )
        if assigned_subject_ids
        else db.session.query(AssessmentRecord.student_id).filter(db.false())
    )
    assigned_course_terms = [
        db.and_(
            Student.course == subject.course.name,
            Student.semester == subject.semester,
        )
        for subject in assigned_subjects
        if subject.course
    ]
    legacy_record_filter = db.or_(
        Student.id.in_(students_with_marks),
        Student.id.in_(students_with_attendance),
        Student.id.in_(students_with_assessments),
    )
    assignment_filter = [db.or_(*assigned_course_terms)] if assigned_course_terms else []
    candidates = (
        Student.query.filter(db.or_(legacy_record_filter, *assignment_filter))
        .order_by(Student.full_name, Student.student_code)
        .all()
    )
    return [
        student
        for student in candidates
        if any(
            staff_can_access_subject_student(staff, subject, student)
            for subject in assigned_subjects
        )
    ]


def staff_subjects(staff):
    assigned_names = [
        item.strip().casefold()
        for item in (staff.assigned_subjects or "").split(",")
        if item.strip()
    ]
    filters = [Subject.staff_id == staff.id]
    if assigned_names:
        filters.append(
            db.and_(
                Subject.staff_id.is_(None),
                func.lower(Subject.name).in_(assigned_names),
            )
        )
    return Subject.query.filter(db.or_(*filters)).order_by(Subject.name).all()


def staff_can_access_subject_student(staff, subject, student):
    assigned_names = {
        item.strip().casefold()
        for item in (staff.assigned_subjects or "").split(",")
        if item.strip()
    }
    if subject.staff_id != staff.id and (
        subject.staff_id is not None
        or subject.name.casefold() not in assigned_names
    ):
        return False
    if subject.course:
        return (
            student.course.casefold() == subject.course.name.casefold()
            and student.semester == subject.semester
        )
    return bool(
        Mark.query.filter_by(student_id=student.id, subject=subject.name).first()
        or Attendance.query.filter_by(student_id=student.id, subject=subject.name).first()
        or AssessmentRecord.query.filter_by(
            student_id=student.id, subject_id=subject.id
        ).first()
    )


def sync_staff_subject_names(staff_ids):
    for staff_id in {value for value in staff_ids if value}:
        staff_member = db.session.get(Staff, staff_id)
        if staff_member:
            staff_member.assigned_subjects = ", ".join(
                subject.name
                for subject in Subject.query.filter_by(staff_id=staff_id).order_by(Subject.name).all()
            )


def assigned_subjects_for_staff(staff):
    return {
        subject.name
        for subject in Subject.query.filter_by(staff_id=staff.id).all()
    }


TOTAL_ASSESSMENT_MARKS = 50
SLOW_LEARNER_MARK_THRESHOLD = 20
SLOW_LEARNER_PERCENT_THRESHOLD = 40.0
MAX_ASSESSMENT_SCORES = {"unit_test_marks": 20, "assignment_marks": 20, "quiz_marks": 10}


class AssessmentKNNModel:
    def __init__(self):
        self.training_data = [
            {"features": [20, 20, 10], "label": "Good"},
            {"features": [18, 18, 9], "label": "Good"},
            {"features": [17, 16, 8], "label": "Good"},
            {"features": [16, 15, 8], "label": "Good"},
            {"features": [15, 14, 7], "label": "Average"},
            {"features": [14, 12, 7], "label": "Average"},
            {"features": [12, 11, 6], "label": "Average"},
            {"features": [10, 10, 5], "label": "Average"},
            {"features": [8, 8, 4], "label": "Poor"},
            {"features": [7, 6, 4], "label": "Poor"},
            {"features": [5, 5, 2], "label": "Poor"},
            {"features": [3, 4, 1], "label": "Poor"},
        ]

    def _distance(self, features_a, features_b):
        return sum((a - b) ** 2 for a, b in zip(features_a, features_b)) ** 0.5

    def predict(self, unit_test_marks, assignment_marks, quiz_marks):
        candidate = [unit_test_marks, assignment_marks, quiz_marks]
        distances = [
            (self._distance(candidate, item["features"]), item["label"])
            for item in self.training_data
        ]
        distances.sort(key=lambda item: item[0])
        nearest = distances[:5]
        votes = Counter(label for _, label in nearest)
        predicted_label = votes.most_common(1)[0][0]
        total_marks = unit_test_marks + assignment_marks + quiz_marks
        overall_percentage = (total_marks / TOTAL_ASSESSMENT_MARKS) * 100
        slow_learner = slow_learner_flag(total_marks)
        return {
            "total_marks": round(total_marks, 2),
            "overall_percentage": round(overall_percentage, 2),
            "ml_predicted_performance": predicted_label,
            "slow_learner": slow_learner,
        }


assessment_knn_model = AssessmentKNNModel()


def predict_performance(unit_test_marks, assignment_marks, quiz_marks):
    unit_test_marks = max(0.0, float(unit_test_marks))
    assignment_marks = max(0.0, float(assignment_marks))
    quiz_marks = max(0.0, float(quiz_marks))
    result = assessment_knn_model.predict(unit_test_marks, assignment_marks, quiz_marks)
    status = performance_status_for(result["overall_percentage"])
    summary = {
        "Good": "Strong academic outlook with consistent assessment performance.",
        "Average": "Solid progress with scope for improvement in upcoming assessments.",
        "Poor": "This student needs focused support and regular assessment practice.",
    }[status]
    return {
        "label": result["ml_predicted_performance"],
        "score": result["overall_percentage"],
        "summary": summary,
        "total_marks": result["total_marks"],
        "overall_percentage": result["overall_percentage"],
        "slow_learner": result["slow_learner"],
    }


def student_prediction(student):
    return predict_performance(0, 0, 0)


def performance_status_for(score):
    if score >= 70:
        return "Good"
    if score >= 40:
        return "Average"
    return "Poor"


def risk_level_for(score, attendance=0):
    if score < 40 or attendance < 50:
        return "High"
    if score < 70 or attendance < 75:
        return "Medium"
    return "Low"


def slow_learner_flag(total_marks, threshold_marks=SLOW_LEARNER_MARK_THRESHOLD):
    return "Yes" if float(total_marks) < float(threshold_marks) else "No"


def dashboard_for(user):
    return {
        "admin": "admin_dashboard",
        "staff": "staff_dashboard",
        "student": "student_dashboard",
    }[user.role]


@app.route("/", methods=["GET", "POST"])
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        user = User.query.filter(func.lower(User.email) == email).first()
        password = request.form.get("password", "")
        if user and user.active and check_password_hash(user.password_hash, password):
            session.clear()
            session["erp_uid"] = user.id
            session.permanent = True
            return redirect(url_for(dashboard_for(user)))
        flash("Invalid email or password.", "danger")
    current = current_user()
    return (
        redirect(url_for(dashboard_for(current)))
        if current
        else render_template("login.html")
    )


@app.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.get("/admin")
@roles("admin")
def admin_dashboard():
    students = Student.query.count()
    fees = Fee.query.all()
    marks = Mark.query.all()
    assessments = AssessmentRecord.query.all()
    attends = Attendance.query.all()
    latest_prediction = (
        IndividualPrediction.query.order_by(IndividualPrediction.created_at.desc()).first()
    )
    academic_average = (
        round(
            sum(record.total for record in assessments)
            / (len(assessments) * TOTAL_ASSESSMENT_MARKS)
            * 100,
            1,
        )
        if assessments
        else (
            round(sum(mark.total for mark in marks) / (len(marks) * 80) * 100, 1)
            if marks
            else 0
        )
    )
    metrics = {
        "Total Students": students,
        "Total Staff": Staff.query.count(),
        "Total Courses": Course.query.count(),
        "Total Subjects": Subject.query.count(),
        "Total Fees Collected": sum(fee.paid for fee in fees),
        "Pending Fees": sum(fee.pending for fee in fees),
        "Average Attendance": (
            round(
                100
                * sum(attendance.status == "Present" for attendance in attends)
                / len(attends),
                1,
            )
            if attends
            else 0
        ),
        "Academic Performance Average": academic_average,
    }
    prediction = (
        {
            "label": latest_prediction.predicted_performance,
            "score": latest_prediction.overall_percentage,
            "summary": (
                f"Latest prediction for {latest_prediction.student.full_name} "
                f"({latest_prediction.student.student_code})."
            ),
        }
        if latest_prediction
        else None
    )
    course_distribution = [
        {
            "name": course.name,
            "count": Student.query.filter_by(course=course.name).count(),
        }
        for course in Course.query.order_by(Course.name).all()
    ]
    return render_template(
        "dashboard.html",
        title="Admin dashboard",
        metrics=metrics,
        notices=Notice.query.filter_by(is_published=True).order_by(Notice.published_on.desc()).limit(5).all(),
        chart={
            "labels": [course["name"] for course in course_distribution],
            "values": [course["count"] for course in course_distribution],
        },
        prediction=prediction,
    )


@app.get("/staff")
@roles("staff")
def staff_dashboard():
    staff_user = current_user().staff
    subjects = staff_subjects(staff_user)
    assigned_students = students_assigned_to_staff(staff_user)
    assigned_student_ids = [student.id for student in assigned_students]
    student_lookup = {student.id: student for student in assigned_students}
    subjects_by_name = {}
    for subject in subjects:
        subjects_by_name.setdefault(subject.name.casefold(), []).append(subject)
    today_attendance = (
        Attendance.query.filter(
            Attendance.attendance_date == date.today(),
            Attendance.student_id.in_(assigned_student_ids),
            func.lower(Attendance.subject).in_(
                list(subjects_by_name)
            ),
        ).all()
        if assigned_student_ids and subjects_by_name
        else []
    )
    today_entry_count = sum(
        row.student_id in student_lookup
        and row.subject.casefold() in subjects_by_name
        and any(
            staff_can_access_subject_student(staff_user, subject, student_lookup[row.student_id])
            for subject in subjects_by_name[row.subject.casefold()]
        )
        for row in today_attendance
    )
    metrics = {
        "Assigned Students": len(assigned_students),
        "Assigned Subjects": len(subjects),
        "Today's Attendance Entries": today_entry_count,
        "Total Assessment Marks Entered": AssessmentRecord.query.filter_by(
            staff_id=staff_user.id
        ).count(),
    }
    return render_template(
        "staff_dashboard.html",
        title="Staff dashboard",
        metrics=metrics,
        notices=visible_notices("Staff")[:5],
        subjects=subjects,
        students=assigned_students[:8],
    )


@app.get("/student")
@roles("student")
def student_dashboard():
    student = current_user().student
    marks = Mark.query.filter_by(student_id=student.id).all()
    fee = student.fee
    metrics = {
        "Attendance": f"{attendance_pct(student.id)}%",
        "Internal average": (
            round(sum(mark.total for mark in marks) / len(marks), 1) if marks else 0
        ),
        "Pending fees": f"?{fee.pending:,.0f}" if fee else "?0",
        "Current semester": student.semester,
    }
    return render_template(
        "dashboard.html",
        title=f"Welcome, {student.full_name}",
        metrics=metrics,
        notices=visible_notices("Student"),
        marks=marks,
        student=student,
        prediction=student_prediction(student),
    )


def visible_notices(audience):
    query = Notice.query.filter(
        Notice.is_published.is_(True),
        Notice.audience.in_(["All", audience]),
    )
    if audience == "Staff":
        admin_ids = db.session.query(User.id).filter(User.role == "admin")
        query = query.filter(Notice.author_id.in_(admin_ids))
    return (
        query
        .order_by(Notice.published_on.desc())
        .all()
    )


@app.route("/predict", methods=["GET", "POST"])
@roles("admin", "staff", "student")
def predict():
    user = current_user()
    if user.role == "student":
        if not user.student:
            abort(403)
        student_options = [user.student]
        student = user.student
    elif user.role == "staff":
        student_options = (
            students_assigned_to_staff(user.staff) if user.staff else []
        )
        student = None
    else:
        student_options = Student.query.order_by(
            Student.full_name, Student.student_code
        ).all()
        student = None

    selected_student_id = request.values.get("student_id", type=int)
    if user.role != "student" and selected_student_id:
        student = next(
            (option for option in student_options if option.id == selected_student_id),
            None,
        )
        if student is None:
            abort(403)

    form = {
        "unit_test_marks": 0,
        "assignment_marks": 0,
        "quiz_marks": 0,
    }
    prediction = None
    assessment_chart = None
    if request.method == "POST":
        if student is None:
            flash("Please select a student before generating a prediction.", "warning")
        else:
            try:
                unit_test_marks = float(request.form.get("unit_test_marks", ""))
                assignment_marks = float(request.form.get("assignment_marks", ""))
                quiz_marks = float(request.form.get("quiz_marks", ""))
            except ValueError:
                flash("Enter valid numeric marks for all three assessments.", "danger")
            else:
                form.update(
                    {
                        "unit_test_marks": unit_test_marks,
                        "assignment_marks": assignment_marks,
                        "quiz_marks": quiz_marks,
                    }
                )
                if not 0 <= unit_test_marks <= MAX_ASSESSMENT_SCORES["unit_test_marks"]:
                    flash("Unit test marks must be between 0 and 20.", "danger")
                elif not 0 <= assignment_marks <= MAX_ASSESSMENT_SCORES["assignment_marks"]:
                    flash("Assignment marks must be between 0 and 20.", "danger")
                elif not 0 <= quiz_marks <= MAX_ASSESSMENT_SCORES["quiz_marks"]:
                    flash("Quiz marks must be between 0 and 10.", "danger")
                else:
                    prediction = predict_performance(
                        unit_test_marks, assignment_marks, quiz_marks
                    )
                    prediction["performance_status"] = performance_status_for(
                        prediction["overall_percentage"]
                    )
                    total_marks = unit_test_marks + assignment_marks + quiz_marks
                    assessment_chart = {
                        "labels": ["Unit Test", "Assignment", "Quiz"],
                        "values": [
                            unit_test_marks,
                            assignment_marks,
                            quiz_marks,
                        ],
                        "maximums": [20, 20, 10],
                        "percentages": [
                            round((marks / total_marks) * 100, 1)
                            if total_marks
                            else 0
                            for marks in (
                                unit_test_marks,
                                assignment_marks,
                                quiz_marks,
                            )
                        ],
                    }
                    db.session.add(
                        IndividualPrediction(
                            student_id=student.id,
                            created_by_id=user.id,
                            unit_test_marks=unit_test_marks,
                            assignment_marks=assignment_marks,
                            quiz_marks=quiz_marks,
                            total_marks=prediction["total_marks"],
                            overall_percentage=prediction["overall_percentage"],
                            predicted_performance=prediction["label"],
                            performance_status=performance_status_for(
                                prediction["overall_percentage"]
                            ),
                            slow_learner=prediction["slow_learner"],
                        )
                    )
                    db.session.commit()
                    flash(
                        f"Prediction saved for {student.full_name} ({student.student_code}).",
                        "success",
                    )
    elif selected_student_id is None and user.role != "student":
        student = None

    return render_template(
        "predict.html",
        prediction=prediction,
        student=student,
        students=student_options,
        form=form,
        assessment_chart=assessment_chart,
    )


@app.route("/students", methods=["GET", "POST"])
@roles("admin", "staff")
def students():
    if request.method == "POST":
        if current_user().role != "admin":
            abort(403)
        data = request.form
        email = data["email"].strip().lower()
        if (
            User.query.filter_by(email=email).first()
            or Student.query.filter_by(student_code=data["student_code"]).first()
        ):
            flash("Email or student ID already exists.", "danger")
        else:
            user = User(
                email=email,
                password_hash=generate_password_hash("Demo@12345"),
                role="student",
            )
            db.session.add(user)
            db.session.flush()
            student = Student(
                student_code=data["student_code"],
                full_name=data["full_name"],
                email=email,
                course=data["course"],
                department=data["department"],
                semester=int(data["semester"]),
                division=data["division"],
                phone=data.get("phone"),
                user_id=user.id,
            )
            db.session.add(student)
            db.session.add(Fee(student_id=student.id, total=80000))
            db.session.commit()
            flash("Student created with demo password.", "success")
        return redirect(url_for("students"))

    if current_user().role == "staff":
        staff_member = current_user().staff
        assigned_subjects = staff_subjects(staff_member)
        assigned_subject_ids = [subject.id for subject in assigned_subjects]
        assigned_subject_names = [
            subject.name.casefold() for subject in assigned_subjects
        ]
        assigned_students = students_assigned_to_staff(staff_member)
        student_ids = [student.id for student in assigned_students]
        query = Student.query.filter(Student.id.in_(student_ids))
        search = request.args.get("q", "").strip()
        course = request.args.get("course", "")
        semester = request.args.get("semester", type=int)
        division = request.args.get("division", "")
        if search:
            query = query.filter(
                db.or_(
                    Student.full_name.ilike(f"%{search}%"),
                    Student.student_code.ilike(f"%{search}%"),
                )
            )
        if course:
            query = query.filter(Student.course == course)
        if semester:
            query = query.filter(Student.semester == semester)
        if division:
            query = query.filter(Student.division == division)
        visible_students = query.order_by(Student.full_name).all()
        detail_id = request.args.get("details", type=int)
        detail_student = None
        if detail_id:
            detail_student = next(
                (student for student in assigned_students if student.id == detail_id),
                None,
            )
            if detail_student is None:
                abort(404)
        performance = {}
        attendance_performance = {}
        for student in visible_students:
            student_subjects = [
                subject
                for subject in assigned_subjects
                if staff_can_access_subject_student(
                    staff_member, subject, student
                )
            ]
            student_subject_ids = [subject.id for subject in student_subjects]
            student_subject_names = [
                subject.name.casefold() for subject in student_subjects
            ]
            assessments = AssessmentRecord.query.filter(
                AssessmentRecord.student_id == student.id,
                AssessmentRecord.subject_id.in_(student_subject_ids),
            ).all() if student_subject_ids else []
            performance[student.id] = (
                round(
                    sum(item.total for item in assessments) / len(assessments),
                    1,
                )
                if assessments
                else None
            )
            attendance_rows = Attendance.query.filter(
                Attendance.student_id == student.id,
                func.lower(Attendance.subject).in_(student_subject_names),
            ).all() if student_subject_names else []
            attendance_performance[student.id] = (
                round(
                    100
                    * sum(row.status == "Present" for row in attendance_rows)
                    / len(attendance_rows),
                    1,
                )
                if attendance_rows
                else 0
            )
        detail_assessment_records = []
        detail_attendance_records = []
        if detail_student:
            subject_by_id = {subject.id: subject for subject in assigned_subjects}
            detail_subjects = [
                subject
                for subject in assigned_subjects
                if staff_can_access_subject_student(
                    staff_member, subject, detail_student
                )
            ]
            detail_subject_ids = [subject.id for subject in detail_subjects]
            detail_assessment_records = [
                row
                for row in AssessmentRecord.query.filter(
                    AssessmentRecord.student_id == detail_student.id,
                    AssessmentRecord.subject_id.in_(detail_subject_ids),
                ).order_by(AssessmentRecord.updated_at.desc()).all()
                if staff_can_access_subject_student(
                    staff_member, subject_by_id[row.subject_id], detail_student
                )
            ] if detail_subject_ids else []
            performance[detail_student.id] = (
                round(
                    sum(item.total for item in detail_assessment_records)
                    / len(detail_assessment_records),
                    1,
                )
                if detail_assessment_records
                else None
            )
            detail_subject_names = [
                subject.name.casefold() for subject in detail_subjects
            ]
            detail_attendance_records = (
                Attendance.query.filter(
                    Attendance.student_id == detail_student.id,
                    func.lower(Attendance.subject).in_(
                        detail_subject_names
                    ),
                ).order_by(Attendance.attendance_date.desc()).all()
                if detail_subjects
                else []
            )
            attendance_performance[detail_student.id] = (
                round(
                    100
                    * sum(row.status == "Present" for row in detail_attendance_records)
                    / len(detail_attendance_records),
                    1,
                )
                if detail_attendance_records
                else 0
            )
        return render_template(
            "staff_students.html",
            students=visible_students,
            courses=sorted({student.course for student in assigned_students}),
            semesters=sorted({student.semester for student in assigned_students}),
            divisions=sorted({student.division for student in assigned_students}),
            filters={
                "q": search,
                "course": course,
                "semester": semester,
                "division": division,
            },
            detail_student=detail_student,
            performance=performance,
            attendance_performance=attendance_performance,
            assessment_records=detail_assessment_records,
            attendance_records=detail_attendance_records,
        )

    query = Student.query
    search = request.args.get("q", "").strip()
    course = request.args.get("course", "")
    if search:
        query = query.filter(
            db.or_(
                Student.full_name.ilike(f"%{search}%"),
                Student.student_code.ilike(f"%{search}%"),
                Student.email.ilike(f"%{search}%"),
            )
        )
    if course:
        query = query.filter_by(course=course)
    return render_template(
        "students.html",
        students=query.order_by(Student.full_name).all(),
        courses=["BCA", "BBA", "B.Tech"],
    )


@app.post("/students/<int:id>/toggle")
@roles("admin")
def toggle_student(id):
    student = Student.query.get_or_404(id)
    student.user.active = not student.user.active
    db.session.commit()
    flash("Student status updated.", "success")
    return redirect(url_for("students"))


@app.route("/admin/manage/<section>", methods=["GET", "POST"])
@roles("admin")
def admin_management(section):
    models = {
        "students": Student,
        "staff": Staff,
        "courses": Course,
        "subjects": Subject,
        "attendance": Attendance,
        "assessments": AssessmentRecord,
        "fees": Fee,
        "notices": Notice,
    }
    if section not in models:
        abort(404)

    model = models[section]
    query = model.query
    edit_id = request.args.get("edit", type=int)
    record = db.session.get(model, edit_id) if edit_id else None
    if edit_id and record is None:
        abort(404)

    students_list = Student.query.order_by(Student.full_name).all()
    staff_list = Staff.query.order_by(Staff.full_name).all()
    courses_list = Course.query.order_by(Course.name).all()
    subjects_list = Subject.query.order_by(Subject.name).all()
    field_specs = []

    if section == "students":
        title = "Student Management"
        field_specs = [
            ("student_code", "Student ID / Roll Number", "text", True),
            ("full_name", "Full Name", "text", True),
            ("email", "Email", "email", True),
            ("password", "Initial / New Password", "password", False),
            ("phone", "Phone Number", "text", False),
            ("course", "Course", "course", True),
            ("department", "Department", "text", True),
            ("semester", "Semester", "number", True),
            ("division", "Division", "text", True),
        ]
    elif section == "staff":
        title = "Staff Management"
        field_specs = [
            ("employee_code", "Employee Code", "text", True),
            ("full_name", "Full Name", "text", True),
            ("email", "Email / Login", "email", True),
            ("department", "Department", "text", True),
            ("phone", "Phone Number", "text", False),
            ("assigned_subjects", "Assigned Subjects (comma-separated)", "text", False),
            ("password", "Initial / New Password", "password", False),
        ]
    elif section == "courses":
        title = "Courses Management"
        field_specs = [
            ("name", "Course Name", "text", True),
            ("code", "Course Code", "text", True),
            ("department", "Department", "text", True),
            ("duration_years", "Duration (years)", "number", True),
            ("description", "Description", "textarea", False),
        ]
    elif section == "subjects":
        title = "Subjects Management"
        field_specs = [
            ("name", "Subject Name", "text", True),
            ("code", "Subject Code", "text", True),
            ("course_id", "Course", "course_select", False),
            ("semester", "Semester", "number", True),
            ("staff_id", "Assigned Staff", "staff_select", False),
        ]
    elif section == "attendance":
        title = "Attendance Management"
        field_specs = [
            ("student_id", "Student", "student_select", True),
            ("subject", "Subject", "subject_text", True),
            ("attendance_date", "Date", "date", True),
            ("period", "Period", "number", True),
            ("status", "Status", "attendance_status", True),
        ]
    elif section == "assessments":
        title = "Assessments Management"
        field_specs = [
            ("student_id", "Student", "student_select", True),
            ("subject_id", "Subject", "subject_select", True),
            ("unit_test_marks", "Unit Test (20)", "unit_test", True),
            ("assignment_marks", "Assignment (20)", "assignment", True),
            ("quiz_marks", "Quiz (10)", "quiz", True),
        ]
    elif section == "fees":
        title = "Fees Management"
        field_specs = [
            ("student_id", "Student", "student_select", True),
            ("total", "Total Fees", "money", True),
        ]
    else:
        title = "Notices Management"
        field_specs = [
            ("title", "Title", "text", True),
            ("body", "Notice Body", "textarea", True),
            ("audience", "Audience", "audience", True),
            ("category", "Category", "text", True),
            ("published_on", "Notice Date", "date", True),
            ("is_published", "Published", "checkbox", False),
        ]

    if request.method == "POST":
        action = request.form.get("action", "save")
        try:
            if action == "delete":
                target = db.session.get(model, int(request.form.get("record_id", 0)))
                if target is None:
                    abort(404)
                if section == "students":
                    IndividualPrediction.query.filter_by(student_id=target.id).delete()
                    AssessmentRecord.query.filter_by(student_id=target.id).delete()
                    db.session.delete(target.user)
                elif section == "staff":
                    if IndividualPrediction.query.filter_by(
                        created_by_id=target.user_id
                    ).first():
                        raise ValueError(
                            "This staff member has saved prediction history. Deactivate the account instead to preserve its records."
                        )
                    for subject in target.subjects:
                        subject.staff_id = None
                    AssessmentRecord.query.filter_by(staff_id=target.id).update(
                        {"staff_id": None}
                    )
                    db.session.delete(target.user)
                elif section == "courses":
                    if Student.query.filter_by(course=target.name).first() or target.subjects:
                        raise ValueError("Move enrolled students and subjects before deleting this course.")
                    db.session.delete(target)
                elif section == "subjects":
                    if target.assessment_records:
                        raise ValueError("Delete or reassign this subject's assessment records first.")
                    db.session.delete(target)
                elif section == "fees":
                    db.session.delete(target)
                else:
                    db.session.delete(target)
                db.session.commit()
                flash(f"{title[:-10] if title.endswith('Management') else title} record deleted.", "success")
                return redirect(url_for("admin_management", section=section))
            if action == "toggle":
                target = db.session.get(model, int(request.form.get("record_id", 0)))
                if target is None:
                    abort(404)
                if section == "students" or section == "staff":
                    target.user.active = not target.user.active
                elif section == "notices":
                    target.is_published = not target.is_published
                else:
                    abort(400)
                db.session.commit()
                flash("Record status updated.", "success")
                return redirect(url_for("admin_management", section=section))

            data = request.form
            if section == "students":
                student_id = data.get("record_id", type=int)
                student = db.session.get(Student, student_id) if student_id else None
                code = data.get("student_code", "").strip()
                email = data.get("email", "").strip().lower()
                duplicate = Student.query.filter(
                    db.or_(Student.student_code == code, func.lower(Student.email) == email)
                )
                if student:
                    duplicate = duplicate.filter(Student.id != student.id)
                if duplicate.first() or (
                    User.query.filter(func.lower(User.email) == email).first()
                    and (not student or student.user.email.lower() != email)
                ):
                    raise ValueError("Student ID or email is already in use.")
                password = data.get("password", "")
                if password and len(password) < 8:
                    raise ValueError("Password must be at least 8 characters.")
                if student is None and not password:
                    raise ValueError("An initial password is required for a new student account.")
                if not code or not email or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
                    raise ValueError("Enter a valid student ID and email address.")
                values = {
                    "student_code": code,
                    "full_name": data.get("full_name", "").strip(),
                    "email": email,
                    "phone": data.get("phone", "").strip(),
                    "course": data.get("course", "").strip(),
                    "department": data.get("department", "").strip(),
                    "semester": int(data.get("semester", "")),
                    "division": data.get("division", "").strip(),
                }
                if not all([values["full_name"], values["course"], values["department"], values["division"]]) or not 1 <= values["semester"] <= 12:
                    raise ValueError("Complete all student fields and enter a semester from 1 to 12.")
                if Course.query.filter_by(name=values["course"]).first() is None:
                    raise ValueError("Select a course from the course catalog.")
                if student:
                    for key, value in values.items():
                        setattr(student, key, value)
                    student.user.email = email
                    if password:
                        student.user.password_hash = generate_password_hash(password)
                else:
                    user = User(
                        email=email,
                        password_hash=generate_password_hash(password),
                        role="student",
                    )
                    db.session.add(user)
                    db.session.flush()
                    student = Student(**values, user_id=user.id)
                    db.session.add(student)
                    db.session.flush()
            elif section == "staff":
                staff_id = data.get("record_id", type=int)
                staff_member = db.session.get(Staff, staff_id) if staff_id else None
                email = data.get("email", "").strip().lower()
                duplicate = User.query.filter(func.lower(User.email) == email)
                duplicate_code = Staff.query.filter_by(
                    employee_code=data.get("employee_code", "").strip()
                )
                if staff_member:
                    duplicate = duplicate.filter(User.id != staff_member.user_id)
                    duplicate_code = duplicate_code.filter(Staff.id != staff_member.id)
                if duplicate.first() or duplicate_code.first():
                    raise ValueError("Staff employee code or login email is already in use.")
                if not email or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
                    raise ValueError("Enter a valid staff email address.")
                if not data.get("employee_code", "").strip() or not data.get("full_name", "").strip() or not data.get("department", "").strip():
                    raise ValueError("Employee code, full name, and department are required.")
                if staff_member is None:
                    password = data.get("password", "")
                    if len(password) < 8:
                        raise ValueError("Initial password must be at least 8 characters.")
                    account = User(
                        email=email,
                        password_hash=generate_password_hash(password),
                        role="staff",
                    )
                    db.session.add(account)
                    db.session.flush()
                    staff_member = Staff(user_id=account.id, email=email)
                    db.session.add(staff_member)
                else:
                    staff_member.user.email = email
                    staff_member.email = email
                    if data.get("password"):
                        if len(data["password"]) < 8:
                            raise ValueError("Password must be at least 8 characters.")
                        staff_member.user.password_hash = generate_password_hash(data["password"])
                staff_member.employee_code = data.get("employee_code", "").strip()
                staff_member.full_name = data.get("full_name", "").strip()
                staff_member.department = data.get("department", "").strip()
                staff_member.phone = data.get("phone", "").strip() or None
                db.session.flush()
                staff_member.assigned_subjects = data.get("assigned_subjects", "").strip()
                assigned = {
                    value.casefold()
                    for value in staff_member.assigned_subjects.split(",")
                    if value.strip()
                }
                affected_staff_ids = {staff_member.id}
                for subject in staff_member.subjects:
                    if subject.name.casefold() not in assigned:
                        if subject.staff_id:
                            affected_staff_ids.add(subject.staff_id)
                        subject.staff_id = None
                for subject_name in assigned:
                    subject = Subject.query.filter(func.lower(Subject.name) == subject_name).first()
                    if subject:
                        if subject.staff_id:
                            affected_staff_ids.add(subject.staff_id)
                        subject.staff_id = staff_member.id
                db.session.flush()
                sync_staff_subject_names(affected_staff_ids)
                staff_member.assigned_subjects = ", ".join(
                    sorted(assigned_subjects_for_staff(staff_member), key=str.casefold)
                ) or staff_member.assigned_subjects
            elif section == "courses":
                target = db.session.get(Course, data.get("record_id", type=int)) if data.get("record_id") else None
                course_name = data.get("name", "").strip()
                code = data.get("code", "").strip().upper()
                duplicate = Course.query.filter(
                    db.or_(func.lower(Course.name) == course_name.lower(), func.lower(Course.code) == code.lower())
                )
                if target:
                    duplicate = duplicate.filter(Course.id != target.id)
                if duplicate.first():
                    raise ValueError("Course name or code already exists.")
                values = {
                    "name": course_name,
                    "code": code,
                    "department": data.get("department", "").strip(),
                    "duration_years": int(data.get("duration_years", "")),
                    "description": data.get("description", "").strip(),
                }
                if not values["name"] or not values["code"] or not values["department"] or not 1 <= values["duration_years"] <= 10:
                    raise ValueError("Enter course name, department, and a duration from 1 to 10 years.")
                if target:
                    previous_name = target.name
                    for key, value in values.items():
                        setattr(target, key, value)
                    if previous_name != target.name:
                        Student.query.filter_by(course=previous_name).update({"course": target.name})
                else:
                    db.session.add(Course(**values))
            elif section == "subjects":
                target = db.session.get(Subject, data.get("record_id", type=int)) if data.get("record_id") else None
                name = data.get("name", "").strip()
                code = data.get("code", "").strip().upper()
                duplicate = Subject.query.filter(
                    db.or_(func.lower(Subject.name) == name.lower(), func.lower(Subject.code) == code.lower())
                )
                if target:
                    duplicate = duplicate.filter(Subject.id != target.id)
                if duplicate.first():
                    raise ValueError("Subject name or code already exists.")
                staff_id = data.get("staff_id", type=int) or None
                if staff_id and db.session.get(Staff, staff_id) is None:
                    raise ValueError("Select a valid staff member.")
                values = {
                    "name": name,
                    "code": code,
                    "course_id": data.get("course_id", type=int) or None,
                    "semester": int(data.get("semester", "")),
                    "staff_id": staff_id,
                }
                if not values["name"] or not values["code"] or not 1 <= values["semester"] <= 12:
                    raise ValueError("Enter a subject name and semester from 1 to 12.")
                if values["course_id"] and db.session.get(Course, values["course_id"]) is None:
                    raise ValueError("Select a valid course.")
                if target:
                    old_name = target.name
                    old_staff_id = target.staff_id
                    for key, value in values.items():
                        setattr(target, key, value)
                    if old_name.casefold() != target.name.casefold():
                        for staff_member in Staff.query.all():
                            names = [
                                item.strip()
                                for item in (staff_member.assigned_subjects or "").split(",")
                            ]
                            staff_member.assigned_subjects = ", ".join(
                                target.name if item.casefold() == old_name.casefold() else item
                                for item in names
                                if item
                            )
                else:
                    old_staff_id = None
                    target = Subject(**values)
                    db.session.add(target)
                db.session.flush()
                sync_staff_subject_names({old_staff_id, target.staff_id})
            elif section == "attendance":
                target = db.session.get(Attendance, data.get("record_id", type=int)) if data.get("record_id") else None
                student_id = data.get("student_id", type=int)
                student = db.session.get(Student, student_id) if student_id else None
                attendance_date = datetime.strptime(data.get("attendance_date", ""), "%Y-%m-%d").date()
                period = int(data.get("period", ""))
                status = data.get("status", "")
                subject_name = data.get("subject", "").strip()
                if not student or not subject_name or period < 1 or status not in {"Present", "Absent"}:
                    raise ValueError("Enter a valid student, subject, period, and attendance status.")
                duplicate = Attendance.query.filter_by(
                    student_id=student.id,
                    subject=subject_name,
                    attendance_date=attendance_date,
                    period=period,
                )
                if target:
                    duplicate = duplicate.filter(Attendance.id != target.id)
                if duplicate.first():
                    raise ValueError("Attendance already exists for that student, subject, date, and period.")
                if target:
                    target.student_id = student.id
                    target.subject = subject_name
                    target.attendance_date = attendance_date
                    target.period = period
                    target.status = status
                else:
                    db.session.add(Attendance(
                        student_id=student.id, subject=subject_name,
                        attendance_date=attendance_date, period=period, status=status,
                    ))
            elif section == "assessments":
                target = db.session.get(AssessmentRecord, data.get("record_id", type=int)) if data.get("record_id") else None
                student_id = data.get("student_id", type=int)
                subject_id = data.get("subject_id", type=int)
                scores = {
                    "unit_test_marks": float(data.get("unit_test_marks", "")),
                    "assignment_marks": float(data.get("assignment_marks", "")),
                    "quiz_marks": float(data.get("quiz_marks", "")),
                }
                limits = {"unit_test_marks": 20, "assignment_marks": 20, "quiz_marks": 10}
                if not db.session.get(Student, student_id) or not db.session.get(Subject, subject_id):
                    raise ValueError("Select a valid student and subject.")
                if any(
                    not math.isfinite(scores[key])
                    or not 0 <= scores[key] <= maximum
                    for key, maximum in limits.items()
                ):
                    raise ValueError("Assessment marks must be within Unit Test 0–20, Assignment 0–20, and Quiz 0–10.")
                duplicate = AssessmentRecord.query.filter_by(student_id=student_id, subject_id=subject_id)
                if target:
                    duplicate = duplicate.filter(AssessmentRecord.id != target.id)
                if duplicate.first():
                    raise ValueError("An assessment record already exists for this student and subject.")
                if target:
                    target.student_id = student_id
                    target.subject_id = subject_id
                    for key, value in scores.items():
                        setattr(target, key, value)
                else:
                    db.session.add(AssessmentRecord(student_id=student_id, subject_id=subject_id, **scores))
            elif section == "fees":
                target = db.session.get(Fee, data.get("record_id", type=int)) if data.get("record_id") else None
                student_id = data.get("student_id", type=int)
                total = float(data.get("total", ""))
                student = db.session.get(Student, student_id) if student_id else None
                if not student or not math.isfinite(total) or total < 0:
                    raise ValueError("Select a student and enter a non-negative fee amount.")
                duplicate = Fee.query.filter_by(student_id=student_id)
                if target:
                    duplicate = duplicate.filter(Fee.id != target.id)
                if duplicate.first():
                    raise ValueError("A fee account already exists for this student.")
                if target:
                    if total < target.paid:
                        raise ValueError("Total fees cannot be less than the amount already paid.")
                    target.total = total
                else:
                    db.session.add(Fee(student_id=student_id, total=total, paid=0))
            else:
                target = db.session.get(Notice, data.get("record_id", type=int)) if data.get("record_id") else None
                title_text = data.get("title", "").strip()
                body_text = data.get("body", "").strip()
                if not title_text or not body_text:
                    raise ValueError("Notice title and body are required.")
                values = {
                    "title": title_text,
                    "body": body_text,
                    "audience": data.get("audience", "All"),
                    "category": data.get("category", "General").strip(),
                    "published_on": datetime.strptime(data.get("published_on", ""), "%Y-%m-%d").date(),
                    "is_published": data.get("is_published") == "on",
                }
                if values["audience"] not in {"All", "Student", "Staff"}:
                    raise ValueError("Select a valid notice audience.")
                if target:
                    for key, value in values.items():
                        setattr(target, key, value)
                else:
                    db.session.add(Notice(author_id=current_user().id, **values))

            db.session.commit()
            flash(f"{title} saved successfully.", "success")
            return redirect(url_for("admin_management", section=section))
        except ValueError as error:
            db.session.rollback()
            flash(str(error), "danger")
        except (TypeError, KeyError) as error:
            db.session.rollback()
            flash(f"Invalid or missing form value: {error}.", "danger")
        except IntegrityError:
            db.session.rollback()
            flash("This change conflicts with an existing record and was not saved.", "danger")

    q = request.args.get("q", "").strip()
    course_filter = request.args.get("course", "")
    department_filter = request.args.get("department", "")
    semester_filter = request.args.get("semester", type=int)
    division_filter = request.args.get("division", "")
    status_filter = request.args.get("status", "")
    assessment_type_filter = request.args.get("assessment_type", "")
    if assessment_type_filter not in {"", "unit_test", "assignment", "quiz"}:
        abort(400, description="Unknown assessment type.")
    date_filter = request.args.get("date", "")
    parsed_date = None
    if section == "attendance" and date_filter:
        try:
            parsed_date = datetime.strptime(date_filter, "%Y-%m-%d").date()
        except ValueError:
            abort(400, description="Date filter must use YYYY-MM-DD.")
    if section == "students":
        if q:
            query = query.filter(db.or_(
                Student.full_name.ilike(f"%{q}%"),
                Student.student_code.ilike(f"%{q}%"),
                Student.email.ilike(f"%{q}%"),
            ))
        if course_filter:
            query = query.filter(Student.course == course_filter)
        if department_filter:
            query = query.filter(Student.department == department_filter)
        if semester_filter:
            query = query.filter(Student.semester == semester_filter)
        if division_filter:
            query = query.filter(Student.division == division_filter)
        records = query.order_by(Student.full_name).all()
    elif section == "staff":
        if q:
            query = query.filter(db.or_(Staff.full_name.ilike(f"%{q}%"), Staff.email.ilike(f"%{q}%")))
        records = query.order_by(Staff.full_name).all()
    elif section == "courses":
        if q:
            query = query.filter(db.or_(Course.name.ilike(f"%{q}%"), Course.code.ilike(f"%{q}%")))
        records = query.order_by(Course.name).all()
    elif section == "subjects":
        if q:
            query = query.filter(db.or_(Subject.name.ilike(f"%{q}%"), Subject.code.ilike(f"%{q}%")))
        records = query.order_by(Subject.name).all()
    elif section == "attendance":
        query = query.join(Student)
        if q:
            query = query.filter(db.or_(Student.full_name.ilike(f"%{q}%"), Student.student_code.ilike(f"%{q}%")))
        if course_filter:
            query = query.filter(Student.course == course_filter)
        if semester_filter:
            query = query.filter(Student.semester == semester_filter)
        if division_filter:
            query = query.filter(Student.division == division_filter)
        if parsed_date:
            query = query.filter(Attendance.attendance_date == parsed_date)
        records = query.order_by(Attendance.attendance_date.desc()).limit(500).all()
    elif section == "assessments":
        query = query.join(Student).join(Subject)
        if q:
            query = query.filter(db.or_(Student.full_name.ilike(f"%{q}%"), Student.student_code.ilike(f"%{q}%"), Subject.name.ilike(f"%{q}%")))
        if course_filter:
            query = query.filter(Student.course == course_filter)
        if semester_filter:
            query = query.filter(Student.semester == semester_filter)
        records = query.order_by(AssessmentRecord.updated_at.desc()).limit(500).all()
    elif section == "fees":
        query = query.join(Student)
        if q:
            query = query.filter(db.or_(Student.full_name.ilike(f"%{q}%"), Student.student_code.ilike(f"%{q}%")))
        if status_filter == "paid":
            query = query.filter(Fee.paid >= Fee.total)
        elif status_filter == "pending":
            query = query.filter(Fee.paid < Fee.total)
        records = query.order_by(Student.full_name).all()
    elif section == "notices":
        if q:
            query = query.filter(db.or_(Notice.title.ilike(f"%{q}%"), Notice.category.ilike(f"%{q}%")))
        if status_filter == "published":
            query = query.filter(Notice.is_published.is_(True))
        elif status_filter == "draft":
            query = query.filter(Notice.is_published.is_(False))
        records = query.order_by(Notice.published_on.desc()).all()

    total_records = len(records)
    page_number = max(request.args.get("page", 1, type=int), 1)
    per_page = 20
    records = records[(page_number - 1) * per_page : page_number * per_page]
    detail_id = request.args.get("details", type=int)
    detail_record = db.session.get(model, detail_id) if detail_id else None
    attendance_summary = []
    if detail_record is not None and section == "students":
        detail_record = Student.query.filter_by(id=detail_record.id).first()
        grouped_attendance = {}
        for attendance in detail_record.attendance:
            subject_summary = grouped_attendance.setdefault(
                attendance.subject, {"present": 0, "total": 0}
            )
            subject_summary["total"] += 1
            subject_summary["present"] += attendance.status == "Present"
        attendance_summary = [
            {
                "subject": subject,
                "present": values["present"],
                "total": values["total"],
                "percentage": round(100 * values["present"] / values["total"], 1),
            }
            for subject, values in sorted(grouped_attendance.items())
        ]
    return render_template(
        "admin_management.html",
        section=section,
        title=title,
        fields=field_specs,
        record=record,
        records=records,
        detail_record=detail_record,
        attendance_summary=attendance_summary,
        page=page_number,
        pages=max((total_records + per_page - 1) // per_page, 1),
        students=students_list,
        staff=staff_list,
        courses=courses_list,
        subjects=subjects_list,
        filters={
            "q": q,
            "course": course_filter,
            "department": department_filter,
            "semester": semester_filter,
            "division": division_filter,
            "status": status_filter,
            "assessment_type": assessment_type_filter,
            "date": date_filter,
        },
        departments=sorted({item.department for item in Student.query.all()}),
        courses_used=sorted({item.course for item in Student.query.all()}),
        semesters=sorted({item.semester for item in Student.query.all()}),
        divisions=sorted({item.division for item in Student.query.all()}),
    )


@app.post("/admin/manage/fees/<int:fee_id>/payments")
@roles("admin")
def admin_record_fee_payment(fee_id):
    fee = Fee.query.get_or_404(fee_id)
    try:
        amount = float(request.form.get("amount", ""))
        payment_date = datetime.strptime(
            request.form.get("payment_date", ""), "%Y-%m-%d"
        ).date()
        if not math.isfinite(amount) or amount <= 0 or amount > fee.pending:
            raise ValueError("Payment must be greater than zero and no more than the pending balance.")
        payment = FeePayment(
            fee_id=fee.id,
            amount=amount,
            payment_date=payment_date,
            reference=request.form.get("reference", "").strip(),
        )
        fee.paid += amount
        db.session.add(payment)
        db.session.commit()
        flash("Fee payment recorded.", "success")
    except ValueError as error:
        db.session.rollback()
        flash(str(error), "danger")
    return redirect(url_for("admin_management", section="fees"))


@app.route("/profile", methods=["GET", "POST"])
@roles("student", "staff")
def profile():
    user = current_user()
    if user.role == "staff":
        staff_member = user.staff
        if request.method == "POST":
            action = request.form.get("action")
            try:
                if action == "profile":
                    full_name = request.form.get("full_name", "").strip()
                    email = request.form.get("email", "").strip().lower()
                    phone = request.form.get("phone", "").strip()
                    if not full_name or not re.fullmatch(
                        r"[^@\s]+@[^@\s]+\.[^@\s]+", email
                    ):
                        raise ValueError("Enter a valid name and email address.")
                    if len(full_name) > 120 or len(email) > 120 or len(phone) > 20:
                        raise ValueError("Name, email, or phone exceeds its maximum length.")
                    duplicate = User.query.filter(
                        func.lower(User.email) == email,
                        User.id != user.id,
                    ).first()
                    if duplicate:
                        raise ValueError("That email address is already in use.")
                    staff_member.full_name = full_name
                    staff_member.email = email
                    staff_member.phone = phone or None
                    user.email = email
                    db.session.commit()
                    flash("Profile updated.", "success")
                    return redirect(url_for("profile"))
                if action == "password":
                    current_password = request.form.get("current_password", "")
                    new_password = request.form.get("new_password", "")
                    if not check_password_hash(user.password_hash, current_password):
                        raise ValueError("Current password is incorrect.")
                    if len(new_password) < 8:
                        raise ValueError("New password must be at least 8 characters.")
                    user.password_hash = generate_password_hash(new_password)
                    db.session.commit()
                    flash("Password changed successfully.", "success")
                    return redirect(url_for("profile"))
                abort(400)
            except ValueError as error:
                db.session.rollback()
                flash(str(error), "danger")
            except IntegrityError:
                db.session.rollback()
                flash("Profile update conflicts with an existing account.", "danger")
        return render_template(
            "profile.html",
            staff_subjects=staff_subjects(staff_member),
        )
    student = user.student
    edit_mode = request.method == "POST" or request.args.get("edit") == "1"
    form_values = None
    if request.method == "POST":
        if request.form.get("action") != "student_profile":
            abort(400)
        full_name = request.form.get("full_name", "").strip()
        email = request.form.get("email", "").strip().lower()
        phone = request.form.get("phone", "").strip()
        try:
            if not full_name or len(full_name) > 120:
                raise ValueError("Enter your name using no more than 120 characters.")
            if not email or len(email) > 120 or not re.fullmatch(
                r"[^@\s]+@[^@\s]+\.[^@\s]+", email
            ):
                raise ValueError("Enter a valid email address.")
            if len(phone) > 20 or (
                phone
                and (
                    not re.fullmatch(r"\+?[0-9][0-9\s().-]*", phone)
                    or not 7 <= sum(character.isdigit() for character in phone) <= 15
                )
            ):
                raise ValueError("Enter a valid mobile number with 7 to 15 digits.")
            duplicate_student = Student.query.filter(
                func.lower(Student.email) == email,
                Student.id != student.id,
            ).first()
            duplicate_user = User.query.filter(
                func.lower(User.email) == email,
                User.id != user.id,
            ).first()
            if duplicate_student or duplicate_user:
                raise ValueError("That email address is already in use.")

            student.full_name = full_name
            student.email = email
            student.phone = phone or None
            user.email = email
            db.session.commit()
            flash("Your profile has been updated successfully!", "success")
            return redirect(url_for("profile"))
        except ValueError as error:
            db.session.rollback()
            flash(str(error), "danger")
            form_values = {"full_name": full_name, "email": email, "phone": phone}
        except IntegrityError:
            db.session.rollback()
            flash("Profile update conflicts with an existing account.", "danger")
            form_values = {"full_name": full_name, "email": email, "phone": phone}
    return render_template(
        "profile.html",
        edit_mode=edit_mode,
        form_values=form_values,
    )


def manage_staff_attendance(staff):
    subjects = staff_subjects(staff)
    subject_id = request.values.get("subject_id", type=int)
    selected_subject = next(
        (subject for subject in subjects if subject.id == subject_id), None
    )
    if subject_id and selected_subject is None:
        abort(403)
    edit_id = request.args.get("edit", type=int)
    editing_record = db.session.get(Attendance, edit_id) if edit_id else None
    if edit_id and editing_record is None:
        abort(404)
    if editing_record:
        editing_subject = next(
            (
                subject for subject in subjects
                if subject.name.casefold() == editing_record.subject.casefold()
            ),
            None,
        )
        editing_student = db.session.get(Student, editing_record.student_id)
        if (
            not editing_subject
            or not editing_student
            or not staff_can_access_subject_student(staff, editing_subject, editing_student)
            or (selected_subject and selected_subject.id != editing_subject.id)
        ):
            abort(403)
        selected_subject = editing_subject

    if request.method == "POST":
        if not selected_subject:
            abort(400, description="Select an assigned subject.")
        try:
            attendance_date = datetime.strptime(
                request.form.get("attendance_date", ""), "%Y-%m-%d"
            ).date()
            period = int(request.form.get("period", ""))
            if period < 1:
                raise ValueError("Period must be a positive number.")
            submitted_ids = request.form.getlist("student_id")
            if not submitted_ids:
                raise ValueError("Select at least one assigned student.")
            students_by_id = {
                student.id: student
                for student in students_assigned_to_staff(staff)
            }
            for raw_id in submitted_ids:
                student_id = int(raw_id)
                student = students_by_id.get(student_id)
                if not student or not staff_can_access_subject_student(
                    staff, selected_subject, student
                ):
                    abort(403)
                status = request.form.get(f"status_{student_id}")
                if status not in {"Present", "Absent"}:
                    raise ValueError("Choose Present or Absent for each student.")
                row = Attendance.query.filter_by(
                    student_id=student.id,
                    subject=selected_subject.name,
                    attendance_date=attendance_date,
                    period=period,
                ).first()
                if row:
                    row.status = status
                else:
                    db.session.add(
                        Attendance(
                            student_id=student.id,
                            subject=selected_subject.name,
                            attendance_date=attendance_date,
                            period=period,
                            status=status,
                        )
                    )
            db.session.commit()
            flash("Attendance saved successfully.", "success")
            return redirect(
                url_for(
                    "attendance",
                    subject_id=selected_subject.id,
                    course=request.form.get("course", ""),
                    semester=request.form.get("semester", ""),
                    division=request.form.get("division", ""),
                    q=request.form.get("q", ""),
                    date=attendance_date.isoformat(),
                )
            )
        except ValueError as error:
            db.session.rollback()
            flash(str(error), "danger")
        except IntegrityError:
            db.session.rollback()
            flash("Attendance conflicts with an existing register entry.", "danger")

    assigned_students = students_assigned_to_staff(staff)
    eligible_students = (
        [
            student for student in assigned_students
            if staff_can_access_subject_student(staff, selected_subject, student)
        ]
        if selected_subject
        else assigned_students
    )
    attendance_date_value = (
        editing_record.attendance_date.isoformat()
        if editing_record
        else request.values.get("attendance_date", request.args.get("date", date.today().isoformat()))
    )
    period_value = (
        editing_record.period
        if editing_record
        else request.values.get("period", "1")
    )
    search = request.args.get("q", "").strip()
    course = request.args.get("course", "")
    semester = request.args.get("semester", type=int)
    division = request.args.get("division", "")
    if search:
        eligible_students = [
            student for student in eligible_students
            if search.casefold() in student.full_name.casefold()
            or search.casefold() in student.student_code.casefold()
        ]
    if course:
        eligible_students = [student for student in eligible_students if student.course == course]
    if semester:
        eligible_students = [student for student in eligible_students if student.semester == semester]
    if division:
        eligible_students = [student for student in eligible_students if student.division == division]

    history_query = Attendance.query.join(Student)
    allowed_student_ids = [student.id for student in assigned_students]
    allowed_subject_names = [subject.name for subject in subjects]
    if allowed_student_ids and allowed_subject_names:
        history_query = history_query.filter(
            Attendance.student_id.in_(allowed_student_ids),
            func.lower(Attendance.subject).in_(
                [name.casefold() for name in allowed_subject_names]
            ),
        )
    else:
        history_query = history_query.filter(db.false())
    if selected_subject:
        history_query = history_query.filter(
            func.lower(Attendance.subject) == selected_subject.name.casefold()
        )
    date_filter = request.args.get("date", "")
    if date_filter:
        try:
            parsed_date = datetime.strptime(date_filter, "%Y-%m-%d").date()
        except ValueError:
            abort(400, description="Date filter must use YYYY-MM-DD.")
        history_query = history_query.filter(Attendance.attendance_date == parsed_date)
    status_filter = request.args.get("status", "")
    if status_filter:
        if status_filter not in {"Present", "Absent"}:
            abort(400, description="Unknown attendance status.")
        history_query = history_query.filter(Attendance.status == status_filter)
    history = history_query.order_by(Attendance.attendance_date.desc()).limit(1000).all()
    students_by_id = {student.id: student for student in assigned_students}
    subjects_by_name = {}
    for subject in subjects:
        subjects_by_name.setdefault(subject.name.casefold(), []).append(subject)
    history = [
        row
        for row in history
        if row.student_id in students_by_id
        and row.subject.casefold() in subjects_by_name
        and any(
            staff_can_access_subject_student(staff, subject, students_by_id[row.student_id])
            for subject in subjects_by_name[row.subject.casefold()]
        )
        and (
            not search
            or search.casefold() in row.student.full_name.casefold()
            or search.casefold() in row.student.student_code.casefold()
        )
        and (not course or row.student.course == course)
        and (not semester or row.student.semester == semester)
        and (not division or row.student.division == division)
    ]

    register_status = {}
    if selected_subject and eligible_students:
        try:
            register_date = datetime.strptime(
                attendance_date_value, "%Y-%m-%d"
            ).date()
            register_period = int(period_value)
            if register_period < 1:
                raise ValueError
        except ValueError:
            abort(400, description="Register date or period is invalid.")
        register_rows = Attendance.query.filter(
            Attendance.student_id.in_([student.id for student in eligible_students]),
            func.lower(Attendance.subject) == selected_subject.name.casefold(),
            Attendance.attendance_date == register_date,
            Attendance.period == register_period,
        ).all()
        register_status = {row.student_id: row.status for row in register_rows}

    percentages = {}
    for student in eligible_students:
        student_subject_names = [
            subject.name.casefold()
            for subject in subjects
            if (not selected_subject or subject.id == selected_subject.id)
            and staff_can_access_subject_student(staff, subject, student)
        ]
        rows = Attendance.query.filter(
            Attendance.student_id == student.id,
            func.lower(Attendance.subject).in_(
                student_subject_names
            ),
        ).all() if student_subject_names else []
        percentages[student.id] = (
            round(100 * sum(row.status == "Present" for row in rows) / len(rows), 1)
            if rows
            else 0
        )
    return render_template(
        "staff_attendance.html",
        subjects=subjects,
        selected_subject=selected_subject,
        students=eligible_students,
        history=history,
        percentages=percentages,
        editing_record=editing_record,
        attendance_date_value=attendance_date_value,
        period_value=period_value,
        register_status=register_status,
        courses=sorted({student.course for student in assigned_students}),
        semesters=sorted({student.semester for student in assigned_students}),
        divisions=sorted({student.division for student in assigned_students}),
        filters={
            "q": search,
            "course": course,
            "semester": semester,
            "division": division,
            "date": date_filter,
            "status": status_filter,
        },
    )


@app.route("/attendance", methods=["GET", "POST"])
@roles("admin", "staff", "student")
def attendance():
    user = current_user()
    if user.role == "staff":
        return manage_staff_attendance(user.staff)
    if request.method == "POST":
        if user.role not in ("admin", "staff"):
            abort(403)
        subject = request.form["subject"]
        when = datetime.strptime(request.form["attendance_date"], "%Y-%m-%d").date()
        period = int(request.form.get("period", 1))
        for student in Student.query.all():
            status = (
                "Present"
                if request.form.get(f"student_{student.id}") == "on"
                else "Absent"
            )
            row = Attendance.query.filter_by(
                student_id=student.id,
                subject=subject,
                attendance_date=when,
                period=period,
            ).first()
            if row:
                row.status = status
            else:
                db.session.add(
                    Attendance(
                        student_id=student.id,
                        subject=subject,
                        attendance_date=when,
                        period=period,
                        status=status,
                    )
                )
        db.session.commit()
        flash("Attendance saved.", "success")
        return redirect(url_for("attendance"))

    query = Attendance.query
    if user.role == "student":
        query = query.filter_by(student_id=user.student.id)
    return render_template(
        "attendance.html",
        rows=query.order_by(Attendance.attendance_date.desc()).limit(100).all(),
        students=Student.query.order_by(Student.full_name).all(),
        percent=attendance_pct(user.student.id) if user.role == "student" else None,
    )


def manage_staff_assessments(staff):
    subjects = staff_subjects(staff)
    subject_id = request.values.get("subject_id", type=int)
    selected_subject = next(
        (subject for subject in subjects if subject.id == subject_id), None
    )
    if subject_id and selected_subject is None:
        abort(403)

    assigned_students = students_assigned_to_staff(staff)
    eligible_students = (
        [
            student for student in assigned_students
            if staff_can_access_subject_student(staff, selected_subject, student)
        ]
        if selected_subject
        else []
    )

    if request.method == "POST":
        if not selected_subject:
            abort(400, description="Select an assigned subject.")
        student_id = request.form.get("student_id", type=int)
        student = next(
            (item for item in eligible_students if item.id == student_id), None
        )
        if not student:
            abort(403)
        try:
            scores = {
                "unit_test_marks": float(request.form.get("unit_test_marks", "")),
                "assignment_marks": float(request.form.get("assignment_marks", "")),
                "quiz_marks": float(request.form.get("quiz_marks", "")),
            }
            limits = {
                "unit_test_marks": 20,
                "assignment_marks": 20,
                "quiz_marks": 10,
            }
            if any(
                not math.isfinite(value) or value < 0 or value > limits[key]
                for key, value in scores.items()
            ):
                raise ValueError(
                    "Marks must be within Unit Test 0–20, Assignment 0–20, and Quiz 0–10."
                )
            record_id = request.form.get("record_id", type=int)
            record = (
                db.session.get(AssessmentRecord, record_id)
                if record_id
                else AssessmentRecord.query.filter_by(
                    student_id=student.id,
                    subject_id=selected_subject.id,
                ).first()
            )
            if record_id and record is None:
                abort(404)
            if record and (
                record.student_id != student.id
                or record.subject_id != selected_subject.id
            ):
                abort(403)
            if record is None:
                record = AssessmentRecord(
                    student_id=student.id,
                    subject_id=selected_subject.id,
                    staff_id=staff.id,
                )
                db.session.add(record)
            else:
                record.staff_id = staff.id
            for key, value in scores.items():
                setattr(record, key, value)
            db.session.commit()
            flash(
                f"Assessment saved for {student.full_name}: "
                f"{sum(scores.values()):g}/50 "
                f"({sum(scores.values()) * 2:g}%).",
                "success",
            )
            return redirect(
                url_for(
                    "marks",
                    subject_id=selected_subject.id,
                    course=request.form.get("course", ""),
                    semester=request.form.get("semester", ""),
                    division=request.form.get("division", ""),
                    q=request.form.get("q", ""),
                    date=request.form.get("date", ""),
                )
            )
        except ValueError as error:
            db.session.rollback()
            flash(str(error), "danger")
        except IntegrityError:
            db.session.rollback()
            flash("Assessment conflicts with an existing student-subject record.", "danger")

    search = request.values.get("q", "").strip()
    course = request.values.get("course", "")
    semester = request.values.get("semester", type=int)
    division = request.values.get("division", "")
    date_filter = request.values.get("date", "")
    if search:
        eligible_students = [
            student for student in eligible_students
            if search.casefold() in student.full_name.casefold()
            or search.casefold() in student.student_code.casefold()
        ]
    if course:
        eligible_students = [student for student in eligible_students if student.course == course]
    if semester:
        eligible_students = [student for student in eligible_students if student.semester == semester]
    if division:
        eligible_students = [student for student in eligible_students if student.division == division]

    records = []
    assessment_by_student = {}
    if selected_subject:
        all_subject_records = AssessmentRecord.query.filter(
            AssessmentRecord.subject_id == selected_subject.id,
            AssessmentRecord.student_id.in_(
                [student.id for student in eligible_students]
            ) if eligible_students else db.false(),
        ).all()
        assessment_by_student = {
            record.student_id: record for record in all_subject_records
        }
        records_query = (
            AssessmentRecord.query.join(Student)
            .filter(AssessmentRecord.subject_id == selected_subject.id)
            .order_by(AssessmentRecord.updated_at.desc())
        )
        if date_filter:
            try:
                datetime.strptime(date_filter, "%Y-%m-%d")
            except ValueError:
                abort(400, description="Date filter must use YYYY-MM-DD.")
            records_query = records_query.filter(
                func.date(AssessmentRecord.updated_at) == date_filter
            )
        allowed_ids = {
            student.id
            for student in assigned_students
            if staff_can_access_subject_student(staff, selected_subject, student)
        }
        records = [
            record
            for record in records_query.limit(500).all()
            if record.student_id in allowed_ids
            and (
                not search
                or search.casefold() in record.student.full_name.casefold()
                or search.casefold() in record.student.student_code.casefold()
            )
            and (not course or record.student.course == course)
            and (not semester or record.student.semester == semester)
            and (not division or record.student.division == division)
        ]
    return render_template(
        "staff_assessments.html",
        subjects=subjects,
        selected_subject=selected_subject,
        students=eligible_students,
        records=records,
        assessment_by_student=assessment_by_student,
        courses=sorted({student.course for student in assigned_students}),
        semesters=sorted({student.semester for student in assigned_students}),
        divisions=sorted({student.division for student in assigned_students}),
        filters={
            "q": search,
            "course": course,
            "semester": semester,
            "division": division,
            "date": date_filter,
        },
    )


@app.route("/marks", methods=["GET", "POST"])
@roles("admin", "staff", "student")
def marks():
    user = current_user()
    if user.role == "staff":
        return manage_staff_assessments(user.staff)
    if request.method == "POST":
        if user.role not in ("admin", "staff"):
            abort(403)
        student_id = int(request.form["student_id"])
        subject = request.form["subject"]
        row = Mark.query.filter_by(student_id=student_id, subject=subject).first()
        if row is None:
            row = Mark(student_id=student_id, subject=subject)
        for key in ["test1", "test2", "assignment", "practical", "project"]:
            setattr(row, key, max(0.0, float(request.form.get(key, 0))))
        db.session.add(row)
        db.session.commit()
        flash("Assessment saved.", "success")
        return redirect(url_for("marks"))

    query = (
        Mark.query
        if user.role != "student"
        else Mark.query.filter_by(student_id=user.student.id)
    )
    return render_template(
        "marks.html",
        rows=query.order_by(Mark.subject).all(),
        students=Student.query.order_by(Student.full_name).all(),
    )


@app.route("/fees", methods=["GET", "POST"])
@roles("admin", "student")
def fees():
    user = current_user()
    if request.method == "POST":
        fee = Fee.query.get_or_404(int(request.form["fee_id"]))
        amount = float(request.form["amount"])
        if amount <= 0:
            flash("Payment must be greater than zero.", "danger")
        else:
            applied_amount = min(amount, fee.pending)
            fee.paid += applied_amount
            db.session.add(
                FeePayment(
                    fee_id=fee.id,
                    amount=applied_amount,
                    payment_date=date.today(),
                )
            )
            db.session.commit()
            flash("Payment recorded.", "success")
        return redirect(url_for("fees"))

    rows = Fee.query.all() if user.role == "admin" else [user.student.fee]
    return render_template("fees.html", rows=rows)


@app.route("/notices", methods=["GET", "POST"])
@roles("admin", "staff", "student")
def notices():
    user = current_user()
    if request.method == "POST":
        if user.role != "admin":
            abort(403)
        db.session.add(
            Notice(
                title=request.form["title"],
                body=request.form["body"],
                audience=request.form["audience"],
                category=request.form.get("category", "General"),
                author_id=user.id,
            )
        )
        db.session.commit()
        flash("Notice published.", "success")
        return redirect(url_for("notices"))

    audience = (
        "Student"
        if user.role == "student"
        else "Staff" if user.role == "staff" else "All"
    )
    notice_rows = (
        Notice.query.order_by(Notice.published_on.desc())
        if user.role == "admin"
        else visible_notices(audience)
    )
    search = request.args.get("q", "").strip()
    category = request.args.get("category", "").strip()
    if search:
        notice_rows = [
            row for row in notice_rows
            if search.casefold() in row.title.casefold()
            or search.casefold() in row.body.casefold()
        ]
    if category:
        notice_rows = [
            row for row in notice_rows
            if (row.category or "General").casefold() == category.casefold()
        ]
    categories = sorted(
        {
            row.category or "General"
            for row in (
                visible_notices(audience)
                if user.role != "admin"
                else Notice.query.all()
            )
        }
    )
    detail_id = request.args.get("detail", type=int)
    detail_notice = next(
        (row for row in notice_rows if row.id == detail_id), None
    ) if detail_id else None
    if detail_id and detail_notice is None:
        abort(404)
    return render_template(
        "notices.html",
        rows=notice_rows,
        categories=categories,
        filters={"q": search, "category": category},
        detail_notice=detail_notice,
    )


@app.route("/staff/bulk-prediction", methods=["GET", "POST"])
@csrf.exempt
@roles("staff")
def bulk_prediction():
    selected_batch = None
    result_rows = []
    avg_class_performance = 0.0
    bulk_chart_data = None
    batch_id = request.args.get("batch_id", type=int)
    slow_only = request.args.get("slow_only") == "1"
    status_filter = request.args.get("status", "all")
    search_query = request.args.get("q", "").strip()
    sort_by = request.args.get("sort", "total_marks")
    detail_id = request.args.get("detail_id", type=int)
    detail_row = None

    if batch_id:
        selected_batch = PredictionBatch.query.get_or_404(batch_id)
        batch_results = PredictionResult.query.filter_by(
            batch_id=selected_batch.id
        ).all()
        category_counts = {
            category: sum(
                row.performance_status == category for row in batch_results
            )
            for category in ("Good", "Average", "Poor")
        }
        total_students = len(batch_results)
        bulk_chart_data = {
            "labels": ["Good Performance", "Average Performance", "Poor Performance"],
            "values": [
                category_counts["Good"],
                category_counts["Average"],
                category_counts["Poor"],
            ],
            "percentages": [
                round(count * 100 / total_students, 1) if total_students else 0
                for count in category_counts.values()
            ],
            "total_students": total_students,
            "slow_learners": sum(
                row.slow_learner == "Yes" for row in batch_results
            ),
        }
        query = PredictionResult.query.filter_by(batch_id=selected_batch.id)
        if slow_only:
            query = query.filter(PredictionResult.slow_learner == "Yes")
        if status_filter and status_filter != "all":
            query = query.filter(PredictionResult.performance_status == status_filter)
        if search_query:
            query = query.filter(
                db.or_(
                    PredictionResult.student_name.ilike(f"%{search_query}%"),
                    PredictionResult.student_id.ilike(f"%{search_query}%"),
                )
            )
        if sort_by == "predicted_score":
            query = query.order_by(PredictionResult.predicted_score.desc())
        else:
            query = query.order_by(PredictionResult.total_marks.desc())
        result_rows = query.all()
        if result_rows:
            avg_class_performance = round(
                sum(row.overall_percentage for row in result_rows) / len(result_rows), 1
            )
        if detail_id:
            detail_row = PredictionResult.query.filter_by(
                id=detail_id, batch_id=selected_batch.id
            ).first()

    if request.method == "POST":
        uploaded = request.files.get("csv_file")
        if not uploaded or not uploaded.filename:
            flash("Please upload a CSV file.", "danger")
            return redirect(url_for("bulk_prediction"))
        if not uploaded.filename.lower().endswith(".csv"):
            flash("Only CSV files are allowed.", "danger")
            return redirect(url_for("bulk_prediction"))

        data = uploaded.read()
        if not data.strip():
            flash("The uploaded CSV file is empty.", "danger")
            return redirect(url_for("bulk_prediction"))

        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            flash("The CSV file is not valid UTF-8 text.", "danger")
            return redirect(url_for("bulk_prediction"))

        reader = csv.DictReader(io.StringIO(text))
        if not reader.fieldnames:
            flash("The CSV file does not contain any header columns.", "danger")
            return redirect(url_for("bulk_prediction"))

        aliases = {
            "student_id": "student_id",
            "student_id_roll_number": "student_id",
            "roll_number": "student_id",
            "roll_no": "student_id",
            "student_code": "student_id",
            "student_name": "student_name",
            "name": "student_name",
            "unit_test_marks": "unit_test_marks",
            "unit_test": "unit_test_marks",
            "assignment_marks": "assignment_marks",
            "assignment": "assignment_marks",
            "quiz_marks": "quiz_marks",
            "quiz": "quiz_marks",
        }

        normalized_headers = {}
        for key in reader.fieldnames:
            normalized = re.sub(r"[^a-z0-9]+", "_", (key or "").strip().lower())
            normalized = normalized.strip("_")
            normalized_headers[key] = aliases.get(normalized, normalized)

        required = [
            "student_id",
            "student_name",
            "unit_test_marks",
            "assignment_marks",
            "quiz_marks",
        ]
        missing = [
            column
            for column in required
            if all(normalized_headers.get(header) != column for header in reader.fieldnames)
        ]
        if missing:
            flash("Missing required columns: " + ", ".join(missing) + ".", "danger")
            return redirect(url_for("bulk_prediction"))

        valid_rows = []
        errors = []
        seen_ids = set()

        for row_number, row in enumerate(reader, start=2):
            student_id_key = next(
                (key for key in row.keys() if normalized_headers.get(key) == "student_id"),
                None,
            )
            student_name_key = next(
                (key for key in row.keys() if normalized_headers.get(key) == "student_name"),
                None,
            )
            unit_test_key = next(
                (key for key in row.keys() if normalized_headers.get(key) == "unit_test_marks"),
                None,
            )
            assignment_key = next(
                (key for key in row.keys() if normalized_headers.get(key) == "assignment_marks"),
                None,
            )
            quiz_key = next(
                (key for key in row.keys() if normalized_headers.get(key) == "quiz_marks"),
                None,
            )

            raw_student_id = row.get(student_id_key, "") if student_id_key else ""
            raw_name = row.get(student_name_key, "") if student_name_key else ""
            raw_unit_test = row.get(unit_test_key, "") if unit_test_key else ""
            raw_assignment = row.get(assignment_key, "") if assignment_key else ""
            raw_quiz = row.get(quiz_key, "") if quiz_key else ""

            if not raw_student_id or not raw_name:
                errors.append(f"Row {row_number}: Student ID or name is missing.")
                continue
            if str(raw_student_id).strip() in seen_ids:
                errors.append(f"Row {row_number}: Duplicate student ID '{raw_student_id}'.")
                continue

            try:
                unit_test_marks = float(str(raw_unit_test).strip())
                assignment_marks = float(str(raw_assignment).strip())
                quiz_marks = float(str(raw_quiz).strip())
            except (TypeError, ValueError):
                errors.append(f"Row {row_number}: Assessment marks are invalid or missing.")
                continue

            if not 0 <= unit_test_marks <= MAX_ASSESSMENT_SCORES["unit_test_marks"]:
                errors.append(f"Row {row_number}: Unit test marks must be between 0 and 20.")
                continue
            if not 0 <= assignment_marks <= MAX_ASSESSMENT_SCORES["assignment_marks"]:
                errors.append(f"Row {row_number}: Assignment marks must be between 0 and 20.")
                continue
            if not 0 <= quiz_marks <= MAX_ASSESSMENT_SCORES["quiz_marks"]:
                errors.append(f"Row {row_number}: Quiz marks must be between 0 and 10.")
                continue

            seen_ids.add(str(raw_student_id).strip())
            valid_rows.append(
                {
                    "student_id": str(raw_student_id).strip(),
                    "student_name": str(raw_name).strip(),
                    "unit_test_marks": unit_test_marks,
                    "assignment_marks": assignment_marks,
                    "quiz_marks": quiz_marks,
                }
            )

        if errors:
            flash(
                "Some records are invalid: "
                + "; ".join(errors[:5])
                + (" ..." if len(errors) > 5 else ""),
                "danger",
            )
            return redirect(url_for("bulk_prediction"))

        if not valid_rows:
            flash("No valid student records were found in the uploaded CSV.", "danger")
            return redirect(url_for("bulk_prediction"))

        report_dir = os.path.join(app.root_path, "instance", "bulk_reports")
        os.makedirs(report_dir, exist_ok=True)
        report_name = f"Academic_Insight_Assessment_Report_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}.csv"
        report_path = os.path.join(report_dir, report_name)

        batch = PredictionBatch(
            filename=uploaded.filename,
            report_name=report_name,
            total_students=len(valid_rows),
            status="processed",
        )
        db.session.add(batch)
        db.session.flush()

        for row in valid_rows:
            prediction = predict_performance(
                row["unit_test_marks"], row["assignment_marks"], row["quiz_marks"]
            )
            total_marks = row["unit_test_marks"] + row["assignment_marks"] + row["quiz_marks"]
            overall_percentage = (total_marks / TOTAL_ASSESSMENT_MARKS) * 100
            status = performance_status_for(overall_percentage)
            slow = slow_learner_flag(total_marks)

            db.session.add(
                PredictionResult(
                    batch_id=batch.id,
                    student_id=row["student_id"],
                    student_name=row["student_name"],
                    unit_test_marks=row["unit_test_marks"],
                    assignment_marks=row["assignment_marks"],
                    quiz_marks=row["quiz_marks"],
                    total_marks=total_marks,
                    overall_percentage=overall_percentage,
                    attendance_percentage=0,
                    internal_marks=0,
                    mid_term_marks=0,
                    study_hours=0,
                    predicted_score=prediction["score"],
                    predicted_result=prediction["label"],
                    performance_status=status,
                    risk_level=risk_level_for(prediction["score"]),
                    slow_learner=slow,
                )
            )

        batch.good_students = sum(
            1
            for result in PredictionResult.query.filter_by(batch_id=batch.id).all()
            if result.performance_status == "Good"
        )
        batch.average_students = sum(
            1
            for result in PredictionResult.query.filter_by(batch_id=batch.id).all()
            if result.performance_status == "Average"
        )
        batch.poor_students = sum(
            1
            for result in PredictionResult.query.filter_by(batch_id=batch.id).all()
            if result.performance_status == "Poor"
        )
        batch.slow_learners = sum(
            1
            for result in PredictionResult.query.filter_by(batch_id=batch.id).all()
            if result.slow_learner == "Yes"
        )
        batch.average_class_performance = round(
            sum(result.overall_percentage for result in PredictionResult.query.filter_by(batch_id=batch.id).all())
            / max(len(PredictionResult.query.filter_by(batch_id=batch.id).all()), 1),
            1,
        )

        with open(report_path, "w", newline="", encoding="utf-8") as report_file:
            writer = csv.writer(report_file)
            writer.writerow([
                "Student ID / Roll Number",
                "Student Name",
                "Unit Test Marks",
                "Assignment Marks",
                "Quiz Marks",
                "Total Marks (Out of 50)",
                "Overall Performance Percentage",
                "ML Predicted Performance",
                "Performance Status",
                "Slow Learner Status",
            ])
            for row in valid_rows:
                prediction = predict_performance(
                    row["unit_test_marks"], row["assignment_marks"], row["quiz_marks"]
                )
                total_marks = row["unit_test_marks"] + row["assignment_marks"] + row["quiz_marks"]
                overall_percentage = (total_marks / TOTAL_ASSESSMENT_MARKS) * 100
                writer.writerow([
                    row["student_id"],
                    row["student_name"],
                    row["unit_test_marks"],
                    row["assignment_marks"],
                    row["quiz_marks"],
                    total_marks,
                    overall_percentage,
                    prediction["label"],
                    performance_status_for(overall_percentage),
                    slow_learner_flag(total_marks),
                ])

        db.session.commit()
        flash("Bulk prediction processed successfully.", "success")
        return redirect(url_for("bulk_prediction", batch_id=batch.id))

    batches = PredictionBatch.query.order_by(PredictionBatch.created_at.desc()).all()
    return render_template(
        "bulk_prediction.html",
        batches=batches,
        selected_batch=selected_batch,
        results=result_rows,
        slow_only=slow_only,
        search_query=search_query,
        status_filter=status_filter,
        sort_by=sort_by,
        average_class_performance=avg_class_performance,
        detail_row=detail_row,
        bulk_chart_data=bulk_chart_data,
    )


@app.get("/staff/bulk-prediction/template.csv")
@roles("staff")
def bulk_prediction_template():
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Student ID / Roll Number",
        "Student Name",
        "Unit Test Marks",
        "Assignment Marks",
        "Quiz Marks",
    ])
    writer.writerow(["COL2026001", "Aarav Mehta", 18, 16, 9])
    writer.writerow(["COL2026002", "Ananya Rao", 14, 12, 7])
    return send_file(
        io.BytesIO(output.getvalue().encode("utf-8")),
        mimetype="text/csv",
        as_attachment=True,
        download_name="bulk_student_assessment_template.csv",
    )


@app.get("/staff/bulk-prediction/<int:batch_id>/download")
@roles("staff")
def bulk_prediction_download(batch_id):
    batch = PredictionBatch.query.get_or_404(batch_id)
    report_path = os.path.join(app.root_path, "instance", "bulk_reports", batch.report_name)
    if not os.path.exists(report_path):
        abort(404)
    return send_file(
        report_path,
        mimetype="text/csv",
        as_attachment=True,
        download_name=batch.report_name,
    )


@app.get("/staff/bulk-prediction/<int:batch_id>/slow-learners/download")
@roles("staff")
def bulk_prediction_slow_learner_download(batch_id):
    batch = PredictionBatch.query.get_or_404(batch_id)
    slow_rows = PredictionResult.query.filter_by(batch_id=batch.id, slow_learner="Yes").all()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Student ID / Roll Number",
        "Student Name",
        "Unit Test Marks",
        "Assignment Marks",
        "Quiz Marks",
        "Total Marks (Out of 50)",
        "Overall Percentage",
        "Slow Learner Status",
    ])
    for row in slow_rows:
        writer.writerow([
            row.student_id,
            row.student_name,
            row.unit_test_marks,
            row.assignment_marks,
            row.quiz_marks,
            row.total_marks,
            row.overall_percentage,
            row.slow_learner,
        ])
    return send_file(
        io.BytesIO(output.getvalue().encode("utf-8")),
        mimetype="text/csv",
        as_attachment=True,
        download_name=f"{batch.id}_slow_learner_report.csv",
    )


@app.get("/reports/<name>.csv")
@roles("admin", "staff")
def report(name):
    output = io.StringIO()
    writer = csv.writer(output)
    staff_member = current_user().staff if current_user().role == "staff" else None
    staff_students = (
        students_assigned_to_staff(staff_member) if staff_member else None
    )
    staff_student_ids = (
        {student.id for student in staff_students} if staff_students is not None else set()
    )
    staff_subjects_list = staff_subjects(staff_member) if staff_member else None
    if name == "students":
        writer.writerow(
            ["Student ID", "Name", "Course", "Semester", "Division", "Email"]
        )
        rows = Student.query.filter(Student.id.in_(staff_student_ids)).all() if staff_member else Student.query.all()
        for student in rows:
            writer.writerow(
                [
                    student.student_code,
                    student.full_name,
                    student.course,
                    student.semester,
                    student.division,
                    student.email,
                ]
            )
    elif name == "attendance":
        writer.writerow(["Student", "Subject", "Date", "Period", "Status"])
        rows = Attendance.query.all()
        if staff_member:
            student_lookup = {student.id: student for student in staff_students}
            subjects_by_name = {}
            for subject in staff_subjects_list:
                subjects_by_name.setdefault(subject.name.casefold(), []).append(subject)
            rows = [
                row for row in rows
                if row.student_id in student_lookup
                and row.subject.casefold() in subjects_by_name
                and any(
                    staff_can_access_subject_student(
                        staff_member, subject, student_lookup[row.student_id]
                    )
                    for subject in subjects_by_name[row.subject.casefold()]
                )
            ]
        for row in rows:
            writer.writerow(
                [
                    row.student.full_name,
                    row.subject,
                    row.attendance_date,
                    row.period,
                    row.status,
                ]
            )
    elif name == "marks":
        writer.writerow(
            [
                "Student",
                "Subject",
                "Test 1",
                "Test 2",
                "Assignment",
                "Practical",
                "Project",
                "Total",
            ]
        )
        rows = Mark.query.all()
        if staff_member:
            student_lookup = {student.id: student for student in staff_students}
            rows = [
                row for row in rows
                if row.student_id in staff_student_ids
                and any(
                    subject.name.casefold() == row.subject.casefold()
                    and staff_can_access_subject_student(
                        staff_member, subject, student_lookup[row.student_id]
                    )
                    for subject in staff_subjects_list
                )
            ]
        for row in rows:
            writer.writerow(
                [
                    row.student.full_name,
                    row.subject,
                    row.test1,
                    row.test2,
                    row.assignment,
                    row.practical,
                    row.project,
                    row.total,
                ]
            )
    elif name == "fees":
        if staff_member:
            abort(403)
        writer.writerow([
            "Student Name",
            "Roll Number",
            "Total Fees",
            "Paid Amount",
            "Pending Amount",
            "Payment Status",
            "Latest Payment Date",
        ])
        for row in Fee.query.all():
            writer.writerow([
                row.student.full_name,
                row.student.student_code,
                row.total,
                row.paid,
                row.pending,
                "Paid" if row.pending == 0 else "Pending",
                row.payments[0].payment_date if row.payments else "",
            ])
    elif name == "assessments":
        writer.writerow([
            "Student ID / Roll Number",
            "Student Name",
            "Course",
            "Semester",
            "Subject",
            "Unit Test Marks (20)",
            "Assignment Marks (20)",
            "Quiz Marks (10)",
            "Total Marks (50)",
        ])
        rows = AssessmentRecord.query.order_by(AssessmentRecord.id).all()
        if staff_member:
            subject_lookup = {subject.id: subject for subject in staff_subjects_list}
            student_lookup = {student.id: student for student in staff_students}
            rows = [
                row for row in rows
                if row.subject_id in subject_lookup
                and row.student_id in student_lookup
                and staff_can_access_subject_student(
                    staff_member,
                    subject_lookup[row.subject_id],
                    student_lookup[row.student_id],
                )
            ]
        for row in rows:
            writer.writerow([
                row.student.student_code,
                row.student.full_name,
                row.student.course,
                row.student.semester,
                row.subject.name,
                row.unit_test_marks,
                row.assignment_marks,
                row.quiz_marks,
                row.total,
            ])
    else:
        abort(404)
    return send_file(
        io.BytesIO(output.getvalue().encode()),
        mimetype="text/csv",
        as_attachment=True,
        download_name=f"{name}-report.csv",
    )


def seed():
    if User.query.first():
        return

    pwd = generate_password_hash("Demo@12345")
    admin = User(email="admin@example.com", password_hash=pwd, role="admin")
    staff_user = User(
        email="staff@example.com",
        password_hash=pwd,
        role="staff",
    )
    db.session.add_all([admin, staff_user])
    db.session.flush()
    db.session.add(
        Staff(
            employee_code="STF001",
            full_name="Dr. Priya Sharma",
            email="staff@example.com",
            department="Computer Science",
            assigned_subjects="Python Programming, Database Systems",
            user_id=staff_user.id,
        )
    )

    names = [
        "Aarav Mehta",
        "Ananya Rao",
        "Vivaan Kapoor",
        "Diya Nair",
        "Arjun Singh",
        "Ishita Das",
        "Kabir Shah",
        "Meera Iyer",
        "Rohan Gupta",
        "Sana Khan",
        "Aditya Joshi",
        "Kavya Patel",
        "Neil Kumar",
        "Riya Bose",
        "Dev Malhotra",
        "Tara Jain",
        "Aryan Roy",
        "Nisha Verma",
        "Yash Sethi",
        "Pooja Menon",
    ]
    courses = ["BCA", "BBA", "B.Tech"]

    for index, name in enumerate(names, start=1):
        email = "student@example.com" if index == 1 else f"student{index}@example.com"
        user = User(email=email, password_hash=pwd, role="student")
        db.session.add(user)
        db.session.flush()
        course = courses[(index - 1) % 3]
        student = Student(
            student_code=f"COL2026{index:03}",
            full_name=name,
            email=email,
            course=course,
            department="Computer Science" if course != "BBA" else "Management",
            semester=(index % 6) + 1,
            division=chr(65 + index % 3),
            phone="9876501234",
            user_id=user.id,
        )
        db.session.add(student)
        db.session.flush()
        db.session.add(
            Fee(
                student_id=student.id,
                total=80000,
                paid=60000 if index % 3 else 40000,
            )
        )
        for day in range(8):
            db.session.add(
                Attendance(
                    student_id=student.id,
                    subject="Python Programming",
                    attendance_date=date.today() - timedelta(days=day),
                    period=1,
                    status="Present" if (index + day) % 5 else "Absent",
                )
            )
        db.session.add(
            Mark(
                student_id=student.id,
                subject="Python Programming",
                test1=14 + index % 6,
                test2=13 + index % 7,
                assignment=8 + index % 3,
                practical=17,
                project=16,
            )
        )

    db.session.add_all(
        [
            Notice(
                title="Mid-semester assessments",
                body="Internal assessments begin on 20 October. Please check your course schedule.",
                audience="All",
                category="Examination",
                author_id=admin.id,
            ),
            Notice(
                title="Library orientation",
                body="First-year students are invited to the library orientation this Friday.",
                audience="Student",
                category="Academic",
                author_id=admin.id,
            ),
        ]
    )
    db.session.commit()
    sync_academic_catalog()


if __name__ == "__main__":
    with app.app_context():
        db.create_all()
        seed()
    app.run(debug=True)
