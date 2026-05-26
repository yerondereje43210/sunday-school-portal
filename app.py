from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
import sqlite3
import os
from datetime import datetime, date
from functools import wraps

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', '56467239')

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'


# Database setup
def init_db():
    conn = sqlite3.connect('sunday_school.db')
    c = conn.cursor()

    # Users table
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        full_name TEXT NOT NULL,
        class_name TEXT NOT NULL,
        is_admin INTEGER DEFAULT 0
    )''')

    # Lessons table
    c.execute('''CREATE TABLE IF NOT EXISTS lessons (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        class_name TEXT NOT NULL,
        title_en TEXT NOT NULL,
        title_am TEXT NOT NULL,
        content_en TEXT NOT NULL,
        content_am TEXT NOT NULL,
        created_date TEXT NOT NULL
    )''')

    # Quizzes table
    c.execute('''CREATE TABLE IF NOT EXISTS quizzes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        class_name TEXT NOT NULL,
        title_en TEXT NOT NULL,
        title_am TEXT NOT NULL,
        questions TEXT NOT NULL,
        created_date TEXT NOT NULL
    )''')

    # Quiz scores table
    c.execute('''CREATE TABLE IF NOT EXISTS quiz_scores (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        quiz_id INTEGER NOT NULL,
        score INTEGER NOT NULL,
        total INTEGER NOT NULL,
        date TEXT NOT NULL,
        FOREIGN KEY (user_id) REFERENCES users(id),
        FOREIGN KEY (quiz_id) REFERENCES quizzes(id)
    )''')

    # Assignments table
    c.execute('''CREATE TABLE IF NOT EXISTS assignments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        class_name TEXT NOT NULL,
        title_en TEXT NOT NULL,
        title_am TEXT NOT NULL,
        description_en TEXT NOT NULL,
        description_am TEXT NOT NULL,
        due_date TEXT NOT NULL,
        created_date TEXT NOT NULL
    )''')

    # Assignment submissions table
    c.execute('''CREATE TABLE IF NOT EXISTS submissions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        assignment_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        content TEXT NOT NULL,
        grade INTEGER,
        feedback TEXT,
        submitted_date TEXT NOT NULL,
        FOREIGN KEY (assignment_id) REFERENCES assignments(id),
        FOREIGN KEY (user_id) REFERENCES users(id)
    )''')

    # Attendance table
    c.execute('''CREATE TABLE IF NOT EXISTS attendance (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        date TEXT NOT NULL,
        status TEXT NOT NULL,
        FOREIGN KEY (user_id) REFERENCES users(id),
        UNIQUE(user_id, date)
    )''')

    # ── Afaan Oromo column migrations (safe: ignored if already exist) ──
    migrations = [
        'ALTER TABLE lessons ADD COLUMN title_or TEXT DEFAULT ""',
        'ALTER TABLE lessons ADD COLUMN content_or TEXT DEFAULT ""',
        'ALTER TABLE quizzes ADD COLUMN title_or TEXT DEFAULT ""',
        'ALTER TABLE assignments ADD COLUMN title_or TEXT DEFAULT ""',
        'ALTER TABLE assignments ADD COLUMN description_or TEXT DEFAULT ""',
    ]
    for sql in migrations:
        try:
            c.execute(sql)
        except Exception:
            pass

    # Create admin user if not exists
    admin_username = os.getenv('ADMIN_USERNAME', 'admin')
    admin_password = os.getenv('ADMIN_PASSWORD', 'yerondereje432')

    c.execute('SELECT * FROM users WHERE username = ?', (admin_username,))
    if not c.fetchone():
        hashed_pw = generate_password_hash(admin_password)
        c.execute('INSERT INTO users (username, password, full_name, class_name, is_admin) VALUES (?, ?, ?, ?, ?)',
                  (admin_username, hashed_pw, 'Administrator', 'Admin', 1))

    conn.commit()
    conn.close()


# ── Classes ── (Membership Affairs Class added)
CLASSES = [
    'Doctrine Class',
    'Prosperity Class',
    'Philanthropy Class',
    'Hymn Class',
    'Literature Class',
    'Membership Affairs Class',
    'Board of Directors'
]


class User(UserMixin):
    def __init__(self, id, username, full_name, class_name, is_admin):
        self.id = id
        self.username = username
        self.full_name = full_name
        self.class_name = class_name
        self.is_admin = is_admin


@login_manager.user_loader
def load_user(user_id):
    conn = sqlite3.connect('sunday_school.db')
    c = conn.cursor()
    c.execute('SELECT * FROM users WHERE id = ?', (user_id,))
    user = c.fetchone()
    conn.close()
    if user:
        return User(user[0], user[1], user[3], user[4], user[5])
    return None


def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            flash('Access denied. Admin privileges required.', 'danger')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function


# ── Language switcher route ──
@app.route('/set_language/<lang>')
def set_language(lang):
    if lang in ['en', 'am', 'or']:
        session['language'] = lang
    return redirect(request.referrer or url_for('index'))


@app.route('/')
def index():
    if current_user.is_authenticated:
        if current_user.is_admin:
            return redirect(url_for('admin_dashboard'))
        else:
            return redirect(url_for('student_dashboard'))
    return redirect(url_for('login'))


@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))

    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')

        conn = sqlite3.connect('sunday_school.db')
        c = conn.cursor()
        c.execute('SELECT * FROM users WHERE username = ?', (username,))
        user = c.fetchone()
        conn.close()

        if user and check_password_hash(user[2], password):
            user_obj = User(user[0], user[1], user[3], user[4], user[5])
            login_user(user_obj)
            if user_obj.is_admin:
                return redirect(url_for('admin_dashboard'))
            else:
                return redirect(url_for('student_dashboard'))
        else:
            flash('Invalid username or password', 'danger')

    return render_template('login.html')


@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))


# ============ ADMIN ROUTES ============
@app.route('/admin')
@login_required
@admin_required
def admin_dashboard():
    conn = sqlite3.connect('sunday_school.db')
    c = conn.cursor()
    c.execute('SELECT * FROM users WHERE is_admin = 0')
    students = c.fetchall()
    stats = {}
    for class_name in CLASSES:
        c.execute('SELECT COUNT(*) FROM users WHERE class_name = ?', (class_name,))
        stats[class_name] = c.fetchone()[0]
    conn.close()
    return render_template('admin.html', students=students, classes=CLASSES, stats=stats)


@app.route('/admin/add_student', methods=['POST'])
@login_required
@admin_required
def add_student():
    username = request.form.get('username')
    password = request.form.get('password')
    full_name = request.form.get('full_name')
    class_name = request.form.get('class_name')

    conn = sqlite3.connect('sunday_school.db')
    c = conn.cursor()
    try:
        hashed_pw = generate_password_hash(password)
        c.execute('INSERT INTO users (username, password, full_name, class_name, is_admin) VALUES (?, ?, ?, ?, ?)',
                  (username, hashed_pw, full_name, class_name, 0))
        conn.commit()
        flash(f'Student {full_name} added successfully!', 'success')
    except sqlite3.IntegrityError:
        flash('Username already exists!', 'danger')
    conn.close()
    return redirect(url_for('admin_dashboard'))


@app.route('/admin/delete_student/<int:student_id>')
@login_required
@admin_required
def delete_student(student_id):
    conn = sqlite3.connect('sunday_school.db')
    c = conn.cursor()
    c.execute('DELETE FROM users WHERE id = ?', (student_id,))
    conn.commit()
    conn.close()
    flash('Student deleted successfully!', 'success')
    return redirect(url_for('admin_dashboard'))


@app.route('/admin/attendance', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_attendance():
    if request.method == 'POST':
        attendance_date = request.form.get('date')
        conn = sqlite3.connect('sunday_school.db')
        c = conn.cursor()
        c.execute('SELECT id FROM users WHERE is_admin = 0')
        students = c.fetchall()
        for student in students:
            student_id = student[0]
            status = request.form.get(f'status_{student_id}', 'absent')
            c.execute('INSERT OR REPLACE INTO attendance (user_id, date, status) VALUES (?, ?, ?)',
                      (student_id, attendance_date, status))
        conn.commit()
        conn.close()
        flash('Attendance marked successfully!', 'success')
        return redirect(url_for('admin_attendance'))

    conn = sqlite3.connect('sunday_school.db')
    c = conn.cursor()
    c.execute('SELECT * FROM users WHERE is_admin = 0 ORDER BY class_name, full_name')
    students = c.fetchall()
    conn.close()
    today = date.today().isoformat()
    return render_template('admin_attendance.html', students=students, today=today)


@app.route('/admin/lessons', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_lessons():
    if request.method == 'POST':
        class_name = request.form.get('class_name')
        title_en = request.form.get('title_en')
        title_am = request.form.get('title_am')
        content_en = request.form.get('content_en')
        content_am = request.form.get('content_am')
        conn = sqlite3.connect('sunday_school.db')
        c = conn.cursor()
        c.execute(
            'INSERT INTO lessons (class_name, title_en, title_am, content_en, content_am, created_date) VALUES (?, ?, ?, ?, ?, ?)',
            (class_name, title_en, title_am, content_en, content_am, datetime.now().isoformat()))
        conn.commit()
        conn.close()
        flash('Lesson added successfully!', 'success')
        return redirect(url_for('admin_lessons'))

    conn = sqlite3.connect('sunday_school.db')
    c = conn.cursor()
    c.execute('SELECT * FROM lessons ORDER BY created_date DESC')
    lessons = c.fetchall()
    conn.close()
    return render_template('admin_lessons.html', lessons=lessons, classes=CLASSES)


@app.route('/admin/assignments', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_assignments():
    if request.method == 'POST':
        class_name = request.form.get('class_name')
        title_en = request.form.get('title_en')
        title_am = request.form.get('title_am')
        description_en = request.form.get('description_en')
        description_am = request.form.get('description_am')
        due_date = request.form.get('due_date')
        conn = sqlite3.connect('sunday_school.db')
        c = conn.cursor()
        c.execute(
            'INSERT INTO assignments (class_name, title_en, title_am, description_en, description_am, due_date, created_date) VALUES (?, ?, ?, ?, ?, ?, ?)',
            (class_name, title_en, title_am, description_en, description_am, due_date, datetime.now().isoformat()))
        conn.commit()
        conn.close()
        flash('Assignment added successfully!', 'success')
        return redirect(url_for('admin_assignments'))

    conn = sqlite3.connect('sunday_school.db')
    c = conn.cursor()
    c.execute('SELECT * FROM assignments ORDER BY due_date DESC')
    assignments = c.fetchall()
    conn.close()
    return render_template('admin_assignments.html', assignments=assignments, classes=CLASSES)


@app.route('/admin/grade_submissions/<int:assignment_id>')
@login_required
@admin_required
def grade_submissions(assignment_id):
    conn = sqlite3.connect('sunday_school.db')
    c = conn.cursor()
    c.execute('SELECT * FROM assignments WHERE id = ?', (assignment_id,))
    assignment = c.fetchone()
    if not assignment:
        conn.close()
        return render_template('grade_submissions.html', assignment=None, submissions=[])
    c.execute('''SELECT s.*, u.full_name, u.username 
                 FROM submissions s 
                 JOIN users u ON s.user_id = u.id 
                 WHERE s.assignment_id = ?''', (assignment_id,))
    submissions = c.fetchall()
    conn.close()
    return render_template('grade_submissions.html', assignment=assignment, submissions=submissions)


@app.route('/admin/save_grade/<int:submission_id>', methods=['POST'])
@login_required
@admin_required
def save_grade(submission_id):
    grade = request.form.get('grade')
    feedback = request.form.get('feedback')
    conn = sqlite3.connect('sunday_school.db')
    c = conn.cursor()
    c.execute('UPDATE submissions SET grade = ?, feedback = ? WHERE id = ?', (grade, feedback, submission_id))
    conn.commit()
    conn.close()
    flash('Grade saved successfully!', 'success')
    return redirect(request.referrer)


# ============ STUDENT ROUTES ============
@app.route('/student')
@login_required
def student_dashboard():
    if current_user.is_admin:
        return redirect(url_for('admin_dashboard'))

    conn = sqlite3.connect('sunday_school.db')
    c = conn.cursor()
    c.execute('SELECT * FROM lessons WHERE class_name = ? ORDER BY created_date DESC LIMIT 5',
              (current_user.class_name,))
    lessons = c.fetchall()
    c.execute('SELECT * FROM assignments WHERE class_name = ? ORDER BY due_date DESC LIMIT 5',
              (current_user.class_name,))
    assignments = c.fetchall()
    c.execute('''SELECT AVG(score * 100.0 / total) as avg_score 
                 FROM quiz_scores WHERE user_id = ?''', (current_user.id,))
    avg_score = c.fetchone()[0] or 0
    c.execute('SELECT COUNT(*) FROM attendance WHERE user_id = ? AND status = "present"', (current_user.id,))
    present_count = c.fetchone()[0]
    c.execute('SELECT COUNT(*) FROM attendance WHERE user_id = ?', (current_user.id,))
    total_days = c.fetchone()[0]
    attendance_pct = (present_count / total_days * 100) if total_days > 0 else 0
    conn.close()

    return render_template('student.html',
                           lessons=lessons,
                           assignments=assignments,
                           avg_score=avg_score,
                           attendance_pct=attendance_pct)


@app.route('/student/lessons')
@login_required
def student_lessons():
    if current_user.is_admin:
        return redirect(url_for('admin_dashboard'))
    conn = sqlite3.connect('sunday_school.db')
    c = conn.cursor()
    c.execute('SELECT * FROM lessons WHERE class_name = ? ORDER BY created_date DESC',
              (current_user.class_name,))
    lessons = c.fetchall()
    conn.close()
    return render_template('student_lessons.html', lessons=lessons)


@app.route('/student/assignments')
@login_required
def student_assignments():
    if current_user.is_admin:
        return redirect(url_for('admin_dashboard'))
    conn = sqlite3.connect('sunday_school.db')
    c = conn.cursor()
    c.execute('SELECT * FROM assignments WHERE class_name = ? ORDER BY due_date DESC',
              (current_user.class_name,))
    assignments = c.fetchall()
    c.execute('SELECT assignment_id FROM submissions WHERE user_id = ?', (current_user.id,))
    submitted = [row[0] for row in c.fetchall()]
    conn.close()
    return render_template('student_assignments.html', assignments=assignments, submitted=submitted)


@app.route('/student/submit_assignment/<int:assignment_id>', methods=['POST'])
@login_required
def submit_assignment(assignment_id):
    content = request.form.get('content')
    conn = sqlite3.connect('sunday_school.db')
    c = conn.cursor()
    c.execute('INSERT INTO submissions (assignment_id, user_id, content, submitted_date) VALUES (?, ?, ?, ?)',
              (assignment_id, current_user.id, content, datetime.now().isoformat()))
    conn.commit()
    conn.close()
    flash('Assignment submitted successfully!', 'success')
    return redirect(url_for('student_assignments'))


@app.route('/student/progress')
@login_required
def student_progress():
    if current_user.is_admin:
        return redirect(url_for('admin_dashboard'))
    conn = sqlite3.connect('sunday_school.db')
    c = conn.cursor()
    c.execute('''SELECT q.title_en, qs.score, qs.total, qs.date 
                 FROM quiz_scores qs 
                 JOIN quizzes q ON qs.quiz_id = q.id 
                 WHERE qs.user_id = ? 
                 ORDER BY qs.date DESC''', (current_user.id,))
    quiz_scores = c.fetchall()
    c.execute('''SELECT a.title_en, s.grade, s.feedback, s.submitted_date 
                 FROM submissions s 
                 JOIN assignments a ON s.assignment_id = a.id 
                 WHERE s.user_id = ? AND s.grade IS NOT NULL 
                 ORDER BY s.submitted_date DESC''', (current_user.id,))
    assignment_grades = c.fetchall()
    c.execute('SELECT date, status FROM attendance WHERE user_id = ? ORDER BY date DESC LIMIT 30',
              (current_user.id,))
    attendance = c.fetchall()
    conn.close()
    return render_template('student_progress.html',
                           quiz_scores=quiz_scores,
                           assignment_grades=assignment_grades,
                           attendance=attendance)


init_db()

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)