from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy import create_engine, text
from sqlalchemy.orm import scoped_session, sessionmaker
import os
from datetime import datetime, date
from functools import wraps

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', '56467239')

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# ── SQLAlchemy engine: WAL + connection pool for concurrent writes ──
engine = create_engine(
    'sqlite:///sunday_school.db',
    connect_args={
        'timeout': 30,
        'check_same_thread': False,
    },
    pool_size=10,          # up to 10 simultaneous connections
    max_overflow=20,       # burst to 30 if needed
    pool_pre_ping=True,
)

# Enable WAL mode on every new connection
from sqlalchemy import event
@event.listens_for(engine, "connect")
def set_wal_mode(dbapi_conn, connection_record):
    dbapi_conn.execute("PRAGMA journal_mode=WAL")
    dbapi_conn.execute("PRAGMA synchronous=NORMAL")
    dbapi_conn.execute("PRAGMA busy_timeout=30000")

db_session = scoped_session(sessionmaker(bind=engine))


@app.teardown_appcontext
def shutdown_session(exception=None):
    db_session.remove()


def query(sql, params=None):
    return db_session.execute(text(sql), params or {})


def execute(sql, params=None):
    db_session.execute(text(sql), params or {})
    db_session.commit()


# Database setup
def init_db():
    with engine.connect() as conn:
        conn.execute(text("PRAGMA journal_mode=WAL"))
        conn.execute(text('''CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            full_name TEXT NOT NULL,
            class_name TEXT NOT NULL,
            is_admin INTEGER DEFAULT 0
        )'''))
        conn.execute(text('''CREATE TABLE IF NOT EXISTS lessons (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            class_name TEXT NOT NULL,
            title_en TEXT NOT NULL,
            title_am TEXT NOT NULL,
            content_en TEXT NOT NULL,
            content_am TEXT NOT NULL,
            created_date TEXT NOT NULL
        )'''))
        conn.execute(text('''CREATE TABLE IF NOT EXISTS quizzes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            class_name TEXT NOT NULL,
            title_en TEXT NOT NULL,
            title_am TEXT NOT NULL,
            questions TEXT NOT NULL,
            created_date TEXT NOT NULL
        )'''))
        conn.execute(text('''CREATE TABLE IF NOT EXISTS quiz_scores (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            quiz_id INTEGER NOT NULL,
            score INTEGER NOT NULL,
            total INTEGER NOT NULL,
            date TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (quiz_id) REFERENCES quizzes(id)
        )'''))
        conn.execute(text('''CREATE TABLE IF NOT EXISTS assignments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            class_name TEXT NOT NULL,
            title_en TEXT NOT NULL,
            title_am TEXT NOT NULL,
            description_en TEXT NOT NULL,
            description_am TEXT NOT NULL,
            due_date TEXT NOT NULL,
            created_date TEXT NOT NULL
        )'''))
        conn.execute(text('''CREATE TABLE IF NOT EXISTS submissions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            assignment_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            content TEXT NOT NULL,
            grade INTEGER,
            feedback TEXT,
            submitted_date TEXT NOT NULL,
            FOREIGN KEY (assignment_id) REFERENCES assignments(id),
            FOREIGN KEY (user_id) REFERENCES users(id)
        )'''))
        conn.execute(text('''CREATE TABLE IF NOT EXISTS attendance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            status TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id),
            UNIQUE(user_id, date)
        )'''))

        # Afaan Oromo migrations
        for sql in [
            'ALTER TABLE lessons ADD COLUMN title_or TEXT DEFAULT ""',
            'ALTER TABLE lessons ADD COLUMN content_or TEXT DEFAULT ""',
            'ALTER TABLE quizzes ADD COLUMN title_or TEXT DEFAULT ""',
            'ALTER TABLE assignments ADD COLUMN title_or TEXT DEFAULT ""',
            'ALTER TABLE assignments ADD COLUMN description_or TEXT DEFAULT ""',
        ]:
            try:
                conn.execute(text(sql))
            except Exception:
                pass

        # Admin user
        admin_username = os.getenv('ADMIN_USERNAME', 'admin')
        admin_password = os.getenv('ADMIN_PASSWORD', 'yerondereje432')
        row = conn.execute(text('SELECT id FROM users WHERE username = :u'), {'u': admin_username}).fetchone()
        if not row:
            conn.execute(text(
                'INSERT INTO users (username, password, full_name, class_name, is_admin) VALUES (:u,:p,:f,:c,1)'
            ), {'u': admin_username, 'p': generate_password_hash(admin_password), 'f': 'Administrator', 'c': 'Admin'})
        conn.commit()


CLASSES = [
    'የትምህርት ክፍል / Doctrine Class',
    'የልማት ክፍል / Development Class',
    'የበጎ አድራጎት ክፍል / Charity Class',
    'የመዝሙር ክፍል / Hymn Class',
    'የኪነ ጥበብ / Art Class',
    'የአባልነት ጉዳዮች ክፍል / Membership Affairs Class',
    'የሥራ አስፈፃሚዎች ክፍል / Executive Class'
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
    row = query('SELECT * FROM users WHERE id = :id', {'id': user_id}).fetchone()
    if row:
        return User(row[0], row[1], row[3], row[4], row[5])
    return None


def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            flash('Access denied. Admin privileges required.', 'danger')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function


@app.route('/set_language/<lang>')
def set_language(lang):
    if lang in ['en', 'am', 'or']:
        session['language'] = lang
    return redirect(request.referrer or url_for('index'))


@app.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('admin_dashboard') if current_user.is_admin else url_for('student_dashboard'))
    return redirect(url_for('login'))


@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = query('SELECT * FROM users WHERE username = :u', {'u': username}).fetchone()
        if user and check_password_hash(user[2], password):
            user_obj = User(user[0], user[1], user[3], user[4], user[5])
            login_user(user_obj)
            return redirect(url_for('admin_dashboard') if user_obj.is_admin else url_for('student_dashboard'))
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
    students = query('SELECT * FROM users WHERE is_admin = 0').fetchall()
    stats = {c: query('SELECT COUNT(*) FROM users WHERE class_name = :c', {'c': c}).fetchone()[0] for c in CLASSES}
    return render_template('admin.html', students=students, classes=CLASSES, stats=stats)


@app.route('/admin/add_student', methods=['POST'])
@login_required
@admin_required
def add_student():
    username  = request.form.get('username')
    password  = request.form.get('password')
    full_name = request.form.get('full_name')
    class_name= request.form.get('class_name')
    try:
        execute(
            'INSERT INTO users (username, password, full_name, class_name, is_admin) VALUES (:u,:p,:f,:c,0)',
            {'u': username, 'p': generate_password_hash(password), 'f': full_name, 'c': class_name}
        )
        flash(f'Student {full_name} added successfully!', 'success')
    except Exception:
        flash('Username already exists!', 'danger')
    return redirect(url_for('admin_dashboard'))


@app.route('/admin/delete_student/<int:student_id>')
@login_required
@admin_required
def delete_student(student_id):
    execute('DELETE FROM users WHERE id = :id', {'id': student_id})
    flash('Student deleted successfully!', 'success')
    return redirect(url_for('admin_dashboard'))


@app.route('/admin/attendance', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_attendance():
    if request.method == 'POST':
        attendance_date = request.form.get('date')
        students = query('SELECT id FROM users WHERE is_admin = 0').fetchall()
        for student in students:
            sid    = student[0]
            status = request.form.get(f'status_{sid}', 'absent')
            execute(
                'INSERT OR REPLACE INTO attendance (user_id, date, status) VALUES (:u,:d,:s)',
                {'u': sid, 'd': attendance_date, 's': status}
            )
        flash('Attendance marked successfully!', 'success')
        return redirect(url_for('admin_attendance'))
    students = query('SELECT * FROM users WHERE is_admin = 0 ORDER BY class_name, full_name').fetchall()
    return render_template('admin_attendance.html', students=students, today=date.today().isoformat())


@app.route('/admin/lessons', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_lessons():
    if request.method == 'POST':
        execute(
            'INSERT INTO lessons (class_name,title_en,title_am,content_en,content_am,created_date) VALUES (:c,:te,:ta,:ce,:ca,:d)',
            {'c': request.form.get('class_name'), 'te': request.form.get('title_en'),
             'ta': request.form.get('title_am'), 'ce': request.form.get('content_en'),
             'ca': request.form.get('content_am'), 'd': datetime.now().isoformat()}
        )
        flash('Lesson added successfully!', 'success')
        return redirect(url_for('admin_lessons'))
    lessons = query('SELECT * FROM lessons ORDER BY created_date DESC').fetchall()
    return render_template('admin_lessons.html', lessons=lessons, classes=CLASSES)


@app.route('/admin/assignments', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_assignments():
    if request.method == 'POST':
        execute(
            'INSERT INTO assignments (class_name,title_en,title_am,description_en,description_am,due_date,created_date) VALUES (:c,:te,:ta,:de,:da,:dd,:cd)',
            {'c': request.form.get('class_name'), 'te': request.form.get('title_en'),
             'ta': request.form.get('title_am'), 'de': request.form.get('description_en'),
             'da': request.form.get('description_am'), 'dd': request.form.get('due_date'),
             'cd': datetime.now().isoformat()}
        )
        flash('Assignment added successfully!', 'success')
        return redirect(url_for('admin_assignments'))
    assignments = query('SELECT * FROM assignments ORDER BY due_date DESC').fetchall()
    return render_template('admin_assignments.html', assignments=assignments, classes=CLASSES)


@app.route('/admin/grade_submissions/<int:assignment_id>')
@login_required
@admin_required
def grade_submissions(assignment_id):
    assignment = query('SELECT * FROM assignments WHERE id = :id', {'id': assignment_id}).fetchone()
    if not assignment:
        return render_template('grade_submissions.html', assignment=None, submissions=[])
    submissions = query(
        'SELECT s.*, u.full_name, u.username FROM submissions s JOIN users u ON s.user_id = u.id WHERE s.assignment_id = :id',
        {'id': assignment_id}
    ).fetchall()
    return render_template('grade_submissions.html', assignment=assignment, submissions=submissions)


@app.route('/admin/save_grade/<int:submission_id>', methods=['POST'])
@login_required
@admin_required
def save_grade(submission_id):
    execute(
        'UPDATE submissions SET grade = :g, feedback = :f WHERE id = :id',
        {'g': request.form.get('grade'), 'f': request.form.get('feedback'), 'id': submission_id}
    )
    flash('Grade saved successfully!', 'success')
    return redirect(request.referrer)


# ============ STUDENT ROUTES ============
@app.route('/student')
@login_required
def student_dashboard():
    if current_user.is_admin:
        return redirect(url_for('admin_dashboard'))
    lessons     = query('SELECT * FROM lessons WHERE class_name = :c ORDER BY created_date DESC LIMIT 5',
                        {'c': current_user.class_name}).fetchall()
    assignments = query('SELECT * FROM assignments WHERE class_name = :c ORDER BY due_date DESC LIMIT 5',
                        {'c': current_user.class_name}).fetchall()
    avg_score   = query('SELECT AVG(score * 100.0 / total) FROM quiz_scores WHERE user_id = :id',
                        {'id': current_user.id}).fetchone()[0] or 0
    present     = query('SELECT COUNT(*) FROM attendance WHERE user_id = :id AND status = "present"',
                        {'id': current_user.id}).fetchone()[0]
    total_days  = query('SELECT COUNT(*) FROM attendance WHERE user_id = :id',
                        {'id': current_user.id}).fetchone()[0]
    att_pct     = (present / total_days * 100) if total_days > 0 else 0
    return render_template('student.html', lessons=lessons, assignments=assignments,
                           avg_score=avg_score, attendance_pct=att_pct)


@app.route('/student/lessons')
@login_required
def student_lessons():
    if current_user.is_admin:
        return redirect(url_for('admin_dashboard'))
    lessons = query('SELECT * FROM lessons WHERE class_name = :c ORDER BY created_date DESC',
                    {'c': current_user.class_name}).fetchall()
    return render_template('student_lessons.html', lessons=lessons)


@app.route('/student/assignments')
@login_required
def student_assignments():
    if current_user.is_admin:
        return redirect(url_for('admin_dashboard'))
    assignments = query('SELECT * FROM assignments WHERE class_name = :c ORDER BY due_date DESC',
                        {'c': current_user.class_name}).fetchall()
    submitted   = [r[0] for r in query('SELECT assignment_id FROM submissions WHERE user_id = :id',
                                       {'id': current_user.id}).fetchall()]
    return render_template('student_assignments.html', assignments=assignments, submitted=submitted)


@app.route('/student/submit_assignment/<int:assignment_id>', methods=['POST'])
@login_required
def submit_assignment(assignment_id):
    execute(
        'INSERT INTO submissions (assignment_id, user_id, content, submitted_date) VALUES (:a,:u,:c,:d)',
        {'a': assignment_id, 'u': current_user.id,
         'c': request.form.get('content'), 'd': datetime.now().isoformat()}
    )
    flash('Assignment submitted successfully!', 'success')
    return redirect(url_for('student_assignments'))


@app.route('/student/progress')
@login_required
def student_progress():
    if current_user.is_admin:
        return redirect(url_for('admin_dashboard'))
    quiz_scores = query(
        'SELECT q.title_en, qs.score, qs.total, qs.date FROM quiz_scores qs JOIN quizzes q ON qs.quiz_id = q.id WHERE qs.user_id = :id ORDER BY qs.date DESC',
        {'id': current_user.id}).fetchall()
    assignment_grades = query(
        'SELECT a.title_en, s.grade, s.feedback, s.submitted_date FROM submissions s JOIN assignments a ON s.assignment_id = a.id WHERE s.user_id = :id AND s.grade IS NOT NULL ORDER BY s.submitted_date DESC',
        {'id': current_user.id}).fetchall()
    attendance = query(
        'SELECT date, status FROM attendance WHERE user_id = :id ORDER BY date DESC LIMIT 30',
        {'id': current_user.id}).fetchall()
    return render_template('student_progress.html', quiz_scores=quiz_scores,
                           assignment_grades=assignment_grades, attendance=attendance)


init_db()

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)