# app.py
from flask import Flask, render_template, request, redirect, url_for, flash, send_file, session
from werkzeug.security import generate_password_hash, check_password_hash
import mysql.connector
from mysql.connector import Error
import os
from datetime import datetime
from functools import wraps

app = Flask(__name__)
app.config['SECRET_KEY'] = 'ZT0R4G3'
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024 * 1024  # 5GB max-size

# Database configuration
DB_CONFIG = {
    'host': 'localhost',
    'user': 'root',
    'password': '',
    'database': 'storage1',
    'port' : 3307
}

# Database connection function
def get_db_connection():
    try:
        connection = mysql.connector.connect(**DB_CONFIG)
        return connection
    except Error as e:
        print(f"Error connecting to MySQL: {e}")
        return None

# conn = get_db_connection()
# cursor = conn.cursor()
# Login required decorator
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please login first.')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# Initialize database tables
def init_db():

    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()

            # Create users table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    username VARCHAR(80) UNIQUE NOT NULL,
                    password VARCHAR(255) NOT NULL,
                    role VARCHAR(20) NOT NULL,
                    storage_limit BIGINT NOT NULL,
                    storage_used BIGINT DEFAULT 0
                )
            """)

            # Create files table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS files (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    filename VARCHAR(255) NOT NULL,
                    original_filename VARCHAR(255) NOT NULL,
                    file_size BIGINT NOT NULL,
                    upload_date DATETIME NOT NULL,
                    user_id INT NOT NULL,
                    FOREIGN KEY (user_id) REFERENCES users(id)
                )
            """)

            conn.commit()
        except Error as e:
            print(f"Error creating tables: {e}")
        finally:
            cursor.close()
            conn.close()

@app.route('/')
def index():
    return render_template('index.html')

# Route untuk register
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        admin_code = request.form.get('admin_code', '')

        conn = get_db_connection()
        if conn:
            try:
                cursor = conn.cursor(dictionary=True)

                # Check if username exists
                cursor.execute("SELECT id FROM users WHERE username = %s", (username,))
                if cursor.fetchone():
                    flash('Username already exists!')
                    return redirect(url_for('register'))

                # Set role and storage limit
                if admin_code == 'ZTORAG3':
                    role = 'admin'
                    storage_limit = 5 * 1024 * 1024 * 1024  # 5GB
                else:
                    role = 'user'
                    storage_limit = 1 * 1024 * 1024 * 1024  # 1GB

                # Create new user
                hashed_password = generate_password_hash(password, method='sha256')
                cursor.execute("""
                    INSERT INTO users (username, password, role, storage_limit)
                    VALUES (%s, %s, %s, %s)
                """, (username, hashed_password, role, storage_limit))

                conn.commit()
                flash('Registration successful!')
                return redirect(url_for('login'))

            except Error as e:
                print(f"Error: {e}")
                flash('Registration failed!')
            finally:
                cursor.close()
                conn.close()

    return render_template('register.html')

# Route untuk login
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        conn = get_db_connection()
        if conn:
            try:
                cursor = conn.cursor(dictionary=True)
                cursor.execute("SELECT * FROM users WHERE username = %s", (username,))
                user = cursor.fetchone()

                if user and check_password_hash(user['password'], password):
                    session['user_id'] = user['id']
                    session['username'] = user['username']
                    session['role'] = user['role']
                    return redirect(url_for('dashboard'))
                else:
                    flash('Invalid username or password!')
            finally:
                cursor.close()
                conn.close()

    return render_template('login.html')

# Route untuk dashboard
@app.route('/dashboard')
@login_required
def dashboard():
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor(dictionary=True)

            # Get user info
            cursor.execute("SELECT * FROM users WHERE id = %s", (session['user_id'],))
            user = cursor.fetchone()

            # Get user's files
            cursor.execute("SELECT * FROM files WHERE user_id = %s ORDER BY upload_date DESC",
                           (session['user_id'],))
            files = cursor.fetchall()

            storage_used_mb = user['storage_used'] / (1024 * 1024)
            storage_limit_mb = user['storage_limit'] / (1024 * 1024)

            return render_template('dashboard.html',
                                   files=files,
                                   storage_used=storage_used_mb,
                                   storage_limit=storage_limit_mb)
        finally:
            cursor.close()
            conn.close()

    return redirect(url_for('login'))

# Route untuk upload file
@app.route('/upload', methods=['POST'])
@login_required
def upload_file():
    if 'file' not in request.files:
        flash('No file selected!')
        return redirect(url_for('dashboard'))

    file = request.files['file']
    if file.filename == '':
        flash('No file selected!')
        return redirect(url_for('dashboard'))

    # Check file size
    file_content = file.read()
    file_size = len(file_content)
    file.seek(0)

    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor(dictionary=True)

            # Check storage limit
            cursor.execute("SELECT storage_used, storage_limit FROM users WHERE id = %s",
                           (session['user_id'],))
            user = cursor.fetchone()

            if user['storage_used'] + file_size > user['storage_limit']:
                flash('Not enough storage space!')
                return redirect(url_for('dashboard'))

            # Save file
            filename = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{file.filename}"
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(file_path)

            # Update database
            cursor.execute("""
                INSERT INTO files (filename, original_filename, file_size, upload_date, user_id)
                VALUES (%s, %s, %s, %s, %s)
            """, (filename, file.filename, file_size, datetime.now(), session['user_id']))

            # Update storage used
            cursor.execute("""
                UPDATE users SET storage_used = storage_used + %s
                WHERE id = %s
            """, (file_size, session['user_id']))

            conn.commit()
            flash('File uploaded successfully!')

        except Error as e:
            print(f"Error: {e}")
            flash('Upload failed!')
        finally:
            cursor.close()
            conn.close()

    return redirect(url_for('dashboard'))

# Route untuk download file
@app.route('/download/<int:file_id>')
@login_required
def download_file(file_id):
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor(dictionary=True)
            cursor.execute("""
                SELECT * FROM files 
                WHERE id = %s AND user_id = %s
            """, (file_id, session['user_id']))
            file = cursor.fetchone()

            if file:
                file_path = os.path.join(app.config['UPLOAD_FOLDER'], file['filename'])
                return send_file(file_path,
                                 as_attachment=True,
                                 download_name=file['original_filename'])
            else:
                flash('File not found or access denied!')
        finally:
            cursor.close()
            conn.close()

    return redirect(url_for('dashboard'))

# Route untuk delete file
@app.route('/delete/<int:file_id>')
@login_required
def delete_file(file_id):
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor(dictionary=True)

            # Get file info
            cursor.execute("""
                SELECT * FROM files 
                WHERE id = %s AND user_id = %s
            """, (file_id, session['user_id']))
            file = cursor.fetchone()

            if file:
                # Delete physical file
                file_path = os.path.join(app.config['UPLOAD_FOLDER'], file['filename'])
                if os.path.exists(file_path):
                    os.remove(file_path)

                # Update storage used
                cursor.execute("""
                    UPDATE users SET storage_used = storage_used - %s
                    WHERE id = %s
                """, (file['file_size'], session['user_id']))

                # Delete file record
                cursor.execute("DELETE FROM files WHERE id = %s", (file_id,))

                conn.commit()
                flash('File deleted successfully!')
            else:
                flash('File not found or access denied!')

        except Error as e:
            print(f"Error: {e}")
            flash('Delete failed!')
        finally:
            cursor.close()
            conn.close()

    return redirect(url_for('dashboard'))

# Route untuk logout
@app.route('/logout')
@login_required
def logout():
    session.clear()
    return redirect(url_for('login'))

if __name__ == '__main__':
    # Create upload folder if it doesn't exist
    if not os.path.exists(app.config['UPLOAD_FOLDER']):
        os.makedirs(app.config['UPLOAD_FOLDER'])

    # Initialize database
    init_db()

    app.run(host='0.0.0.0', port=5000, debug=True)
