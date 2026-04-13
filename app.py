
from flask import Flask, render_template, request, redirect, url_for, session, flash, send_file, Response
from flask_sqlalchemy import SQLAlchemy
from flask_mail import Mail, Message
import pymysql
from datetime import datetime, timedelta
from enum import Enum
from sqlalchemy import Enum as SQLAlchemyEnum
from twilio.rest import Client 
from werkzeug.utils import secure_filename
import os
import uuid
from flask import current_app
from itsdangerous import URLSafeTimedSerializer as Serializer
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import requests
import threading
from twilio.http.http_client import TwilioHttpClient
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Ensure PyMySQL is installed as MySQLdb
pymysql.install_as_MySQLdb()


# Initialize Flask app
app = Flask(__name__)
MAX_CONCURRENT_SUBMISSIONS = 150  # Set the maximum number of students who can submit at a time
active_submissions = 0
lock = threading.Lock()


# Configure database
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv("DATABASE_URL")
app.config['SECRET_KEY'] = os.getenv("SECRET_KEY")
db = SQLAlchemy(app)

# Flask-Mail Configuration
app.config['MAIL_SERVER'] = os.getenv("MAIL_SERVER")
app.config['MAIL_PORT'] = int(os.getenv("MAIL_PORT"))
app.config['MAIL_USE_TLS'] = os.getenv("MAIL_USE_TLS") == 'True'  # Convert string to boolean
app.config['MAIL_USERNAME'] = os.getenv("MAIL_USERNAME")
app.config['MAIL_PASSWORD'] = os.getenv("MAIL_PASSWORD")
app.config['MAIL_DEFAULT_SENDER'] = os.getenv("MAIL_DEFAULT_SENDER")
from flask_mail import Mail

mail = Mail(app)

# Twilio Credentials
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_PHONE_NUMBER = os.getenv("TWILIO_PHONE_NUMBER")

class CustomHttpClient(TwilioHttpClient):
    def request(self, *args, **kwargs):
        kwargs['timeout'] = 5  # Set timeout to 5 seconds
        return super().request(*args, **kwargs)

http_client = CustomHttpClient()
client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, http_client=http_client)

# Ensure the phone number is in the correct format (E.164)
def format_phone_number(phone):
    """Ensure the phone number is in E.164 format."""
    phone = phone.strip()  
    if not phone.startswith("+"): 
        phone = "+91" + phone
    return phone

def send_sms_background(to_number, message):
    """Background task to send an SMS to the provided number."""
    try:
        formatted_number = format_phone_number(to_number)

        # Twilio API credentials (load from environment variables)
        account_sid = os.getenv("TWILIO_ACCOUNT_SID")
        auth_token = os.getenv("TWILIO_AUTH_TOKEN")
        twilio_client = Client(account_sid, auth_token)
        
        # Send the SMS
        message_sent = twilio_client.messages.create(
            body=message,
            from_=TWILIO_PHONE_NUMBER,  # Your Twilio phone number
            to=formatted_number
        )
        print("SMS sent successfully! SID:", message_sent.sid)
        return message_sent.sid  # Return the SID of the sent message
    except Exception as e:
        print("Error sending SMS:", str(e))
        return None  # Return None if SMS failed


def send_sms(to_number, message):
    """Wrapper function to send SMS in background thread for instant response."""
    thread = threading.Thread(target=send_sms_background, args=(to_number, message))
    thread.daemon = True
    thread.start()
    return True



def get_outpass_counts(gender=None, include_pending=False):
    """Returns counts of students who have actually gone out (marked by watchman)"""
    now = datetime.now(IST)
    current_date = now.date()
    
    # Only count students who have been marked as "outted" by watchman
    query = Outpass.query.filter(
        Outpass.warden_status == 'Accepted',
        Outpass.outted_time.isnot(None),  # Only count those marked as out by watchman
        Outpass.arrived_time.is_(None),   # And haven't returned yet
        Outpass.out_date <= current_date,
        Outpass.in_date >= current_date
    )
    
    if gender:
        # Handle both Enum and string gender values
        if isinstance(gender, Gender):
            gender_value = gender.value
        else:
            gender_value = gender
            
        query = query.filter(Outpass.gender == gender_value)
        
    if not include_pending:
        query = query.filter(Outpass.tutor_status != 'Pending')
        
    return query


# Enum for Gender
class Gender(Enum):
    Male = "Male"
    Female = "Female"
    Other = "Other"


class Department(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)

class Hostel(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)


class Student_Category(Enum):
    sports = "sports"
    hostel = "hostel"
    international = "international"
    emergency = "Emergency" 

# Student Model
class Student(db.Model):
    __tablename__ = 'student'
    __table_args__ = {'extend_existing': True}

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False, index=True)
    password = db.Column(db.String(255), nullable=False)  # 🔹 Changed from password_hash to password
    name = db.Column(db.String(100), nullable=True)
    parent_phone = db.Column(db.String(15), nullable=True)  
    photo = db.Column(db.String(200), nullable=True)  
    roll_number = db.Column(db.String(20), unique=True, nullable=False)
    gender = db.Column(db.Enum(Gender), nullable=False)
    department = db.Column(db.String(50), nullable=False)
    student_category = db.Column(db.String(20), nullable=False, default="hostel")


    
    # Newly added columns
    room_number = db.Column(db.String(10), nullable=False)  # Room number of the student
    hostel_name = db.Column(db.String(50), nullable=False)  # Hostel name of the student

    # Relationships
    outpasses = db.relationship('Outpass', back_populates='student')
    tutor_id = db.Column(db.Integer, db.ForeignKey('tutor.id'), nullable=True)
    tutor = db.relationship('Tutor', backref=db.backref('students', lazy=True))

    def set_password(self, password):
        self.password = password  # Store plain text password

    def check_password(self, password):
        return self.password == password  # Compare plain text passwords


# Tutor Model
class Tutor(db.Model):
    __tablename__ = 'tutor'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False)
    email = db.Column(db.String(100), unique=True, nullable=False)
    name = db.Column(db.String(100), nullable=False)
    department = db.Column(db.String(100), nullable=True)
    department_id = db.Column(db.Integer, db.ForeignKey('department.id'), nullable=True)
    leave_status = db.Column(db.Boolean, default=False)

    assigned_outpasses = db.relationship('Outpass', back_populates='tutor')

    def set_password(self, password):
        self.password = password  # Store plain text password

    def check_password(self, password):
        return self.password == password  # Compare plain text passwords

    def get_reset_password_token(self, expires_sec=1800):
        secret_key = current_app.config['SECRET_KEY']
        print(f"Secret key type: {type(secret_key)}, value: {secret_key}")  # Debugging

        # Ensure secret_key is in bytes
        if isinstance(secret_key, str):
            secret_key = secret_key.encode('utf-8')
        elif isinstance(secret_key, int):
            secret_key = str(secret_key).encode('utf-8')

        # Ensure salt is a string or bytes
        salt = 'password-reset'  # Example salt, ensure it's a string or bytes
        if isinstance(salt, str):
            salt = salt.encode('utf-8')

        # Initialize Serializer with correct arguments
        s = Serializer(secret_key, salt=salt)
        return s.dumps({'tutor_id': self.id, 'exp': expires_sec})  # No need for .decode()
    

    @staticmethod
    def verify_reset_password_token(token):
        secret_key = current_app.config['SECRET_KEY']
        
        # Ensure secret_key is in bytes
        if isinstance(secret_key, str):
            secret_key = secret_key.encode('utf-8')
        
        # Ensure salt is a string or bytes
        salt = 'password-reset'  # Example salt, ensure it's a string or bytes
        if isinstance(salt, str):
            salt = salt.encode('utf-8')
        
        # Initialize Serializer with correct arguments
        s = Serializer(secret_key, salt=salt)
        
        try:
            # Load the token and verify expiration
            data = s.loads(token)
            tutor_id = data['tutor_id']
        except:
            return None
        return Tutor.query.get(tutor_id)
    


# Warden Model
class Warden(db.Model):
    __tablename__ = 'warden'
    __table_args__ = {'extend_existing': True}

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False, index=True)
    password = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(100), unique=True, nullable=False)
    name = db.Column(db.String(100), nullable=False)

    # Correct relationship to Outpass
    outpasses_by_warden = db.relationship('Outpass', back_populates='warden', lazy=True)

    def set_password(self, password):
        self.password = password  # Store plain text password

    def check_password(self, password):
        return self.password == password  # Compare plain text passwords

# Watchman Model
class Watchman(db.Model):
    __tablename__ = 'watchman'
    __table_args__ = {'extend_existing': True}

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False, index=True)
    password = db.Column(db.String(255), nullable=False)
    name = db.Column(db.String(100), nullable=False)

    def set_password(self, password):
        self.password = password  # Store plain text password

    def check_password(self, password):
        return self.password == password  # Compare plain text passwords


# Attendance Model
class Attendance(db.Model):
    __tablename__ = 'attendance'
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('student.id'), nullable=False)
    date = db.Column(db.Date, nullable=False)
    time = db.Column(db.Time, nullable=False)
    status = db.Column(db.String(20), nullable=False, default='Present')
    ip_address = db.Column(db.String(50))
    user_agent = db.Column(db.String(200))
    device_id = db.Column(db.String(64))
    latitude = db.Column(db.Float)
    longitude = db.Column(db.Float)
    verification_method = db.Column(db.String(20))
    
    student = db.relationship('Student', backref=db.backref('attendance_records', lazy=True))
    

# Outpass Model
class Outpass(db.Model):
    __tablename__ = 'outpass'
    __table_args__ = {'extend_existing': True}

    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('student.id', ondelete="SET NULL"), nullable=True)
    tutor_id = db.Column(db.Integer, db.ForeignKey('tutor.id'), nullable=True)
    warden_id = db.Column(db.Integer, db.ForeignKey('warden.id'), nullable=True)
    out_date = db.Column(db.Date, nullable=False)
    in_date = db.Column(db.Date, nullable=False)
    reason = db.Column(db.String(200), nullable=False)
    destination = db.Column(db.String(200), nullable=False)
    photo = db.Column(db.String(255), nullable=False)
    rejected_time = db.Column(db.DateTime, nullable=True)
    roll_number = db.Column(db.String(50), nullable=False)
    hostel_name = db.Column(db.String(255), nullable=False, default="Default Hostel")
    gender = db.Column(db.Enum(Gender), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    student_category = db.Column(db.String(50), nullable=True)
    department_id = db.Column(db.Integer, db.ForeignKey('department.id'), nullable=True)  # <-- FIXED
    # instead of relationship
    department = db.Column(db.String(100), nullable=False)
    room_number = db.Column(db.String(100), nullable=False)
    tutor_status = db.Column(db.String(50), default='Pending')
    warden_status = db.Column(db.String(50), default='Pending')
    watchman_status = db.Column(db.String(10), nullable=False, default="In")
    out_time = db.Column(db.Time, nullable=False)
    in_time = db.Column(db.Time, nullable=False)
    outted_time = db.Column(db.DateTime(timezone=True), nullable=True)
    arrived_time = db.Column(db.DateTime(timezone=True), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    student = db.relationship('Student', back_populates='outpasses')
    tutor = db.relationship('Tutor', back_populates='assigned_outpasses')
    warden = db.relationship('Warden', back_populates='outpasses_by_warden', lazy=True)

    def __init__(self, **kwargs):
        # Handle gender conversion if it's a string
        if 'gender' in kwargs and isinstance(kwargs['gender'], str):
            try:
                kwargs['gender'] = Gender[kwargs['gender']]
            except KeyError:
                kwargs['gender'] = Gender.Other
        super().__init__(**kwargs)

    def __repr__(self):
        return f"<Outpass {self.id} for {self.name}>"

    def is_active(self):
        """Check if the outpass is currently valid and active"""
        now = datetime.now(IST)
        current_date = now.date()

        return (
            self.warden_status == 'Accepted' and
            self.out_date <= current_date and
            self.in_date >= current_date and
            self.outted_time is not None and
            self.arrived_time is None
        )


from alembic import op
import sqlalchemy as sa

def upgrade():
    with op.batch_alter_table('outpass', schema=None) as batch_op:
        batch_op.alter_column('roll_number',
               existing_type=sa.VARCHAR(length=50),
               nullable=False)
        batch_op.drop_constraint('uk_roll_number_date', type_='unique')  # This line removes the unique constraint

def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('outpass', schema=None) as batch_op:
        batch_op.alter_column('roll_number',
               existing_type=sa.VARCHAR(length=50),
               nullable=False)
        batch_op.create_unique_constraint('uk_roll_number_date', ['roll_number', 'out_date'])  # Add this line
    # ### end Alembic commands ###









# Landing page route (login selection)
@app.route('/')
def login():
    return render_template('login.html')

# Role selection and redirection route
@app.route('/role_redirect', methods=['POST'])
def role_redirect():
    role = request.form.get('role')  # Get the role from the form
    if role == 'student':
        return redirect(url_for('student_login'))  # Redirect to student login page
    elif role == 'tutor':
        return redirect(url_for('tutor_login'))  # Redirect to tutor login page
    elif role == 'warden':
        return redirect(url_for('warden_login'))  # Redirect to warden login page
    elif role == 'watchman':
        return redirect(url_for('watchman_login'))  # Redirect to watchman login page
    else:
        # Handle invalid or missing role
        flash("Invalid role selected. Please try again.", "danger")
        return redirect(url_for('login'))  # Redirect back to the login selection page

# Student Login and Dashboard
@app.route('/student_login', methods=['GET', 'POST'])
def student_login():
    if request.method == 'POST':
        login_input = request.form['username'].strip().lower()
        password = request.form['password'].strip()
        
        print(f"🔍 Student Login attempt - Input: '{login_input}', Password: '{password}'")
        
        # Try multiple login identifiers: roll_number, username
        student = Student.query.filter_by(roll_number=login_input).first()
        if not student:
            student = Student.query.filter_by(username=login_input).first()
        
        if student:
            print(f"✅ Student found: {student.name}")
            print(f"   DB Roll Number: '{student.roll_number}'")
            print(f"   DB Username: '{student.username}'")
            print(f"   DB Password: '{student.password}'")
            print(f"   Input Password: '{password}'")
            print(f"   Password match: {student.password == password}")
        else:
            print(f"❌ Student not found with roll number/username: '{login_input}'")

        if student and student.password == password:  # Compare plain text passwords
            session['user_id'] = student.id
            session['role'] = 'student'
            print(f"✅ Login successful for student: {student.name} (ID: {student.id})")
            flash("Login successful!", "success")
            return redirect(url_for('student_category'))
        else:
            flash("Invalid roll number/username or password", "danger")
            return redirect(url_for('student_login'))

    return render_template('student_login.html')


# Define the upload folder as an absolute path
UPLOAD_FOLDER = os.path.join(app.root_path, "static", "students", "student_photos")
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "xlsx", "xls"}

app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

# Ensure the upload folder exists
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

# Function to check file extension
def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


# Route to udent
@app.route('/add_student', methods=['GET', 'POST'])
def add_student():
    if 'user_id' not in session or session.get('role') != 'warden':
        return redirect(url_for('warden_login'))

    if request.method == 'POST':
        name = request.form['name']
        roll_number = request.form['roll_number']
        username = request.form['username']
        gender = request.form['gender']
        password = request.form['password']
        confirm_password = request.form['confirm_password']
        parent_phone = request.form['parent_phone']
        department = request.form['department']
        student_category = request.form['student_category']
        room_number = request.form['room_number']
        hostel_name = request.form['hostel_name']
        photo = request.files['photo']

        # Validate phone number length
        if len(parent_phone) > 15:
            flash("Parent phone number is too long. Maximum 15 characters allowed.", "danger")
            return redirect(url_for('add_student'))

        # Trim the phone number to 15 characters
        parent_phone = parent_phone[:15]

        # Check if roll number or username already exists
        if Student.query.filter_by(roll_number=roll_number).first():
            flash("A student with this roll number already exists.", "danger")
            return redirect(url_for('add_student'))
        if Student.query.filter_by(username=username).first():
            flash("Username already exists. Choose a different username.", "danger")
            return redirect(url_for('add_student'))
        if password != confirm_password:
            flash("Passwords do not match.", "danger")
            return redirect(url_for('add_student'))

        # Save the photo
        photo_filename = None
        if photo and allowed_file(photo.filename):
            ext = photo.filename.rsplit(".", 1)[1].lower()
            photo_filename = f"{secure_filename(name.replace(' ', '_'))}.{ext}"
            photo_path = os.path.join(app.config['UPLOAD_FOLDER'], photo_filename)
            photo.save(photo_path)
        else:
            flash("Invalid photo format. Allowed formats: png, jpg, jpeg.", "danger")
            return redirect(url_for('add_student'))

        # Create a new student
        new_student = Student(
            name=name,
            roll_number=roll_number,
            username=username,
            gender=gender,
            password=password,
            parent_phone=parent_phone,
            department=department,
            student_category=student_category,
            room_number=room_number,
            hostel_name=hostel_name,
            photo=photo_filename
        )
        new_student.set_password(password)

        try:
            db.session.add(new_student)
            db.session.commit()
            flash("Student added successfully!", "success")
        except Exception as e:
            db.session.rollback()
            flash(f"An error occurred: {str(e)}", "danger")

        return redirect(url_for('add_student'))

    # Fetch all students to display in the template
    students = Student.query.all()
    departments = Department.query.all()  # ✅ Fetch all departments from DB
    hostels = Hostel.query.all()  # ✅ Fetch hostels if needed

    return render_template('add_student.html', students=students ,departments=departments,
        hostels=hostels)
    


@app.route('/verify_roll_number', methods=['POST'])
def verify_roll_number():
    """ Check if roll number exists and return student name """
    roll_number = request.json.get('roll_number')
    student = Student.query.filter_by(roll_number=roll_number).first()
    
    if student:
        expected_photo_name = student.name.lower().replace(" ", "_") + '.jpg'
        return jsonify({'exists': True, 'name': student.name, 'photo_name': expected_photo_name}), 200
    else:
        return jsonify({'exists': False}), 404



@app.route('/upload_photo', methods=['GET', 'POST'])
def upload_photo():
    if request.method == 'POST':
        roll_number = request.form['roll_number']
        photo = request.files['photo']
        
        student = Student.query.filter_by(roll_number=roll_number).first()
        
        if student:
            expected_photo_name = student.name.lower().replace(" ", "_") + '.jpg'
            upload_folder = os.path.join(os.getcwd(), "static", "students", "student_photos")
            
            # Ensure the upload directory exists
            if not os.path.exists(upload_folder):
                os.makedirs(upload_folder)

            if photo and allowed_file(photo.filename):
                photo_path = os.path.join(upload_folder, expected_photo_name)
                photo.save(photo_path)

                # Update the database with the correct filename
                student.photo = expected_photo_name
                db.session.commit()

                flash('Photo uploaded successfully!', 'success')
            else:
                flash('Invalid file type! Please upload a valid image file.', 'danger')
        else:
            flash('Student not found!', 'danger')

        return redirect(url_for('upload_photo'))

    return render_template('upload_photo.html')


    
@app.route('/delete_all_students', methods=['POST'])
def delete_all_students():
    try:
        # Step 1: Set student_id to NULL in outpass table
        db.session.query(Outpass).update({Outpass.student_id: None})
        db.session.commit()

        # Step 2: Fetch all student records
        students = Student.query.all()

        # Step 3: Delete student photos
        for student in students:
            if student.photo:
                photo_path = os.path.join('static/students/student_photos', student.photo)
                if os.path.exists(photo_path):
                    os.remove(photo_path)

        # Step 4: Delete all students
        db.session.query(Student).delete()
        db.session.commit()

        return jsonify({'message': 'All students deleted successfully', 'category': 'success'})

    except Exception as e:
        db.session.rollback()
        return jsonify({'message': f'Error deleting students: {str(e)}', 'category': 'danger'})


import pandas as pd
import io
import xlsxwriter
# Route to Download Student Data as Excel
@app.route('/download_students_excel', methods=['GET'])
def download_students_excel():
    if 'user_id' not in session or session.get('role') != 'warden':
        return redirect(url_for('warden_login'))

    # Create a DataFrame from the Student table
    students = Student.query.all()
    data = {
        "Name": [student.name for student in students],
        "Roll Number": [student.roll_number for student in students],
        "Username": [student.username for student in students],
        "Password": [student.password for student in students],  # Add password field
        "Gender": [student.gender.value for student in students],
        "Department": [student.department for student in students],
        "Hostel Name": [student.hostel_name for student in students],
        "Room Number": [student.room_number for student in students],
        "Student Category": [student.student_category for student in students],
    }
    df = pd.DataFrame(data)

    # Create an Excel file in memory
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df.to_excel(writer, sheet_name='Students', index=False)

    output.seek(0)
    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name="students_data.xlsx"
    )


from pytz import timezone

IST = timezone('Asia/Kolkata')

@app.route('/download_outpass_excel', methods=['GET'])
def download_outpass_excel():
    if 'user_id' not in session or session.get('role') != 'warden':
        return redirect(url_for('warden_login'))

    output = io.BytesIO()
    workbook = xlsxwriter.Workbook(output)
    worksheet = workbook.add_worksheet()

    # Define column headers
    headers = [
        'Student Name', 'Roll Number', 'Room Number', 'Department', 
        'Out Date', 'In Date', 'Out Time', 'In Time', 'Reason', 
        'Tutor Status', 'Warden Status', 'Mark as Outted Time', 'Mark as Arrived Time'
    ]
    
    for col, header in enumerate(headers):
        worksheet.write(0, col, header)

    # Fetch outpass requests and write to the worksheet
    outpasses = Outpass.query.all()
    for row, outpass in enumerate(outpasses, start=1):
        student = outpass.student  # Get the student object

        student_name = student.name if student else outpass.name
        student_roll = student.roll_number if student else outpass.roll_number

        worksheet.write(row, 0, student_name if student_name else "N/A")
        worksheet.write(row, 1, student_roll if student_roll else "N/A")
        worksheet.write(row, 2, outpass.room_number if outpass.room_number else "N/A")
        worksheet.write(row, 3, outpass.department.name if isinstance(outpass.department, Enum) else str(outpass.department))
        worksheet.write(row, 4, outpass.out_date.strftime('%Y-%m-%d') if outpass.out_date else "N/A")
        worksheet.write(row, 5, outpass.in_date.strftime('%Y-%m-%d') if outpass.in_date else "N/A")
        
        # Handle time objects (don't try to convert timezone)
        worksheet.write(row, 6, outpass.out_time.strftime('%I:%M %p') if outpass.out_time else "N/A")
        worksheet.write(row, 7, outpass.in_time.strftime('%I:%M %p') if outpass.in_time else "N/A")
        
        worksheet.write(row, 8, outpass.reason if outpass.reason else "N/A")
        worksheet.write(row, 9, outpass.tutor_status if outpass.tutor_status else "N/A")
        worksheet.write(row, 10, outpass.warden_status if outpass.warden_status else "N/A")
        
        # Handle datetime objects with timezone conversion
        if outpass.outted_time:
            outted_time_ist = outpass.outted_time.astimezone(pytz.timezone('Asia/Kolkata'))
            worksheet.write(row, 11, outted_time_ist.strftime('%Y-%m-%d %I:%M:%S %p'))
        else:
            worksheet.write(row, 11, "N/A")
            
        if outpass.arrived_time:
            arrived_time_ist = outpass.arrived_time.astimezone(pytz.timezone('Asia/Kolkata'))
            worksheet.write(row, 12, arrived_time_ist.strftime('%Y-%m-%d %I:%M:%S %p'))
        else:
            worksheet.write(row, 12, "N/A")

    workbook.close()
    output.seek(0)

    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name="outpass_data.xlsx"
    )
    

# Route to Delete Student
from flask import jsonify
import os
@app.route('/delete_student/<int:student_id>', methods=['POST'])
def delete_student(student_id):
    if 'user_id' not in session or session.get('role') != 'warden':
        return redirect(url_for('warden_login'))

    student = Student.query.get_or_404(student_id)

    try:
        # First, delete all attendance records for this student
        Attendance.query.filter_by(student_id=student.id).delete()
        
        # Then set student_id to NULL in related outpasses
        Outpass.query.filter_by(student_id=student.id).update({Outpass.student_id: None})
        db.session.commit()

        # Then delete the student
        db.session.delete(student)
        db.session.commit()

        # Delete the photo file if it exists
        if student.photo:
            photo_path = os.path.join(app.config['UPLOAD_FOLDER'], student.photo)
            if os.path.exists(photo_path):
                os.remove(photo_path)

        flash(f"Student {student.name} deleted successfully!", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Error deleting student: {str(e)}", "danger")

    return redirect(url_for('add_student'))




from flask_mail import Message

from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from datetime import datetime, timedelta
import queue
import json

@app.route('/student_dashboard', methods=['GET', 'POST'])
def student_dashboard():
    if 'user_id' not in session or session.get('role') != 'student':
        return redirect(url_for('student_login'))

    student = Student.query.get(session['user_id'])
    if not student:
        flash("Student not found!", "danger")
        return redirect(url_for('student_login'))
    
    student_photo = url_for('static', filename=f'students/student_photos/{student.photo}') if student and student.photo else None

    # Restrict multiple submissions within 1 hour
    one_hour_ago = datetime.now() - timedelta(hours=1)
    recent_submission = Outpass.query.filter(
        Outpass.student_id == student.id,
        Outpass.created_at >= one_hour_ago
    ).first()

    # Get all non-rejected outpasses for the student
    pending_outpasses = Outpass.query.filter(
        Outpass.student_id == student.id,
        Outpass.warden_status != 'Rejected',
        Outpass.tutor_status != 'Rejected'
    ).order_by(Outpass.created_at.desc()).all()

    if request.method == 'POST':
        # Check if it's an AJAX request
        is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
        
        if recent_submission:
            message = "You can only submit one outpass request per hour. Please wait before submitting another."
            if is_ajax:
                return jsonify({'success': False, 'message': message})
            flash(message, "warning")
            return redirect(url_for('student_dashboard'))

        try:
            # Collect all necessary data for background processing
            form_data = {
                'out_date': request.form.get('out_date'),
                'in_date': request.form.get('in_date'),
                'out-hour': request.form.get('out-hour'),
                'out-minute': request.form.get('out-minute'),
                'out-am-pm': request.form.get('out-am-pm'),
                'in-hour': request.form.get('in-hour'),
                'in-minute': request.form.get('in-minute'),
                'in-am-pm': request.form.get('in-am-pm'),
                'destination': request.form.get('destination'),
                'reason': request.form.get('reason')
            }
            
            # Validate required fields first
            if not all([form_data['out_date'], form_data['in_date'], 
                       form_data['out-hour'], form_data['out-minute'], form_data['out-am-pm'],
                       form_data['in-hour'], form_data['in-minute'], form_data['in-am-pm'],
                       form_data['destination'], form_data['reason']]):
                message = "All fields are required!"
                if is_ajax:
                    return jsonify({'success': False, 'message': message})
                flash(message, "danger")
                return redirect(url_for('student_dashboard'))
            
            # Prepare student info for background task
            student_info = {
                'name': student.name,
                'department': str(student.department) if student.department else "",
                'student_category': str(student.student_category) if student.student_category else "",
                'gender': student.gender.value if isinstance(student.gender, Gender) else str(student.gender),
                'roll_number': student.roll_number,
                'room_number': student.room_number,
                'parent_phone': student.parent_phone,
                'photo': student.photo,
                'hostel_name': student.hostel_name
            }
            
            # Start background task IMMEDIATELY - don't wait for it
            from flask import current_app
            thread = threading.Thread(
                target=create_outpass_async,
                args=(current_app._get_current_object(), student.id, form_data, student_info)
            )
            thread.daemon = True
            thread.start()
            
            print("✅ Background task started, returning instant response")
            
            # Return INSTANT success response (within milliseconds)
            if is_ajax:
                return jsonify({
                    'success': True, 
                    'message': 'Outpass request submitted successfully! Processing in background.',
                    'processing': True
                })
            
            # For non-AJAX, still redirect but instantly
            flash("Outpass request submitted successfully! Processing in background.", "success")
            return redirect(url_for('student_dashboard'))

        except Exception as e:
            import traceback
            print(f"Error: {e}\nTraceback: {traceback.format_exc()}")
            message = f"Error occurred: {str(e)}"
            if is_ajax:
                return jsonify({'success': False, 'message': message})
            flash(message, "danger")
            return redirect(url_for('student_dashboard'))

    # For rendering form
    departments = Department.query.all()
    hostels = Hostel.query.all()
    return render_template(
        'student_dashboard.html',
        student=student,
        student_photo=student_photo,
        pending_outpasses=pending_outpasses,
        departments=departments,
        hostels=hostels
    )


        
                         

@app.route('/process_outpass/<int:request_id>/<string:action>', methods=['GET'])
def process_outpass(request_id, action):
    outpass = Outpass.query.get(request_id)
    if not outpass:
        flash("Outpass request not found.", "danger")
        return redirect(url_for('tutor_dashboard'))
    
    # ✅ Prevent double-processing
    if outpass.tutor_status != 'Pending' and action in ['accept', 'reject']:
        flash("This outpass request has already been processed.", "info")
        return redirect(url_for('tutor_dashboard'))

    if action == 'accept':
        outpass.tutor_status = 'Accepted'
        
        # Ensure gender is valid before processing
        gender = (
            outpass.gender.name.lower() if isinstance(outpass.gender, Enum) 
            else (outpass.gender.lower() if outpass.gender else 'unknown')
        )

        if gender == 'male':
            warden = Warden.query.filter_by(username='warden1').first()
        elif gender == 'female':
            warden = Warden.query.filter_by(username='warden2').first()
        else:
            flash("Invalid gender for outpass request.", "warning")
            return redirect(url_for('tutor_dashboard'))

        if warden:
            outpass.warden_status = 'Pending'
            
            try:
                warden_email = warden.email
                accept_url = url_for('warden_approve_outpass', request_id=outpass.id, _external=True)
                reject_url = url_for('warden_reject_outpass', request_id=outpass.id, _external=True)

                # Create action buttons based on status
                action_buttons = ""
                if outpass.warden_status == 'Pending':
                    action_buttons = f"""
                    <a href="{accept_url}" style="text-decoration: none; padding: 10px; background-color: green; color: white; border-radius: 5px;">✅ Accept</a>
                    <a href="{reject_url}" style="text-decoration: none; padding: 10px; background-color: red; color: white; border-radius: 5px; margin-left: 10px;">❌ Reject</a>
                    """
                elif outpass.warden_status == 'Accepted':
                    action_buttons = """
                    <button disabled style="padding: 10px; background-color: gray; color: white; border-radius: 5px;">
                        ✅ Already Accepted
                    </button>
                    """
                elif outpass.warden_status == 'Rejected':
                    action_buttons = """
                    <button disabled style="padding: 10px; background-color: gray; color: white; border-radius: 5px;">
                        ❌ Already Rejected
                    </button>
                    """

                msg = Message("New Outpass Request for Approval", recipients=[warden_email])
                msg.html = f"""
                <html>
                <body>
                    <p>Dear {warden.name},</p>
                    <p>A new outpass request has been approved by the tutor and is pending your review.</p>
                    <ul>
                        <li><strong>Name:</strong> {outpass.name}</li>
                        <li><strong>Roll Number:</strong> {outpass.roll_number}</li>
                        <li><strong>Department:</strong> {outpass.department.value if hasattr(outpass.department, 'value') else outpass.department}</li>
                        <li><strong>Gender:</strong> {outpass.gender.value if hasattr(outpass.gender, 'value') else outpass.gender}</li>
                        <li><strong>Hostel Name:</strong> {outpass.hostel_name}</li>
                        <li><strong>Room Number:</strong> {outpass.room_number}</li>
                        <li><strong>Out Date:</strong> {outpass.out_date}</li>
                        <li><strong>Out Time:</strong> {outpass.out_time.strftime('%I:%M %p') if outpass.out_time else 'N/A'}</li>
                        <li><strong>In Date:</strong> {outpass.in_date}</li>
                        <li><strong>In Time:</strong> {outpass.in_time.strftime('%I:%M %p') if outpass.in_time else 'N/A'}</li>
                        <li><strong>Reason:</strong> {outpass.reason}</li>
                        <li><strong>Destination:</strong> {outpass.destination}</li>
                    </ul>
                    <p><strong>Take Action:</strong></p>
                    {action_buttons}
                </body>
                </html>
                """

                print(f"📧 Sending email to Warden: {warden_email}")  # DEBUGGING
                send_email(msg)

                db.session.commit()
                flash("Outpass request approved and forwarded to the warden.", "success")
            except Exception as e:
                db.session.rollback()
                print(f"⚠️ Email sending failed: {str(e)}")
                flash("Failed to notify warden via email.", "warning")

    elif action == 'reject':
        outpass.tutor_status = 'Rejected'
        outpass.warden_status = 'Rejected'
        db.session.commit()
        flash("Outpass request rejected.", "danger")

    else:
        flash("Invalid action.", "danger")

    # ✅ Session check
    user_id = session.get('user_id')
    if not user_id:
        flash("Session expired or user not logged in. Please log in again.", "warning")
        return redirect(url_for('login'))

    tutor = Tutor.query.get(user_id)
    if tutor and tutor.username in ['sports1', 'international']:
        return redirect(url_for('tutor_dashboard'))

    return redirect(url_for('tutor_dashboard'))





@app.route('/warden_approve_outpass/<int:request_id>')
def warden_approve_outpass(request_id):
    outpass = Outpass.query.get(request_id)
    if outpass:
        outpass.warden_status = 'Accepted'
        db.session.commit()
        flash("Outpass approved successfully.", "success")
    else:
        flash("Outpass request not found.", "danger")
    return redirect(url_for('warden_dashboard'))  # or any other dashboard route

@app.route('/warden_reject_outpass/<int:request_id>')
def warden_reject_outpass(request_id):
    outpass = Outpass.query.get(request_id)
    if outpass:
        outpass.warden_status = 'Rejected'
        db.session.commit()
        flash("Outpass rejected successfully.", "danger")
    else:
        flash("Outpass request not found.", "danger")
    return redirect(url_for('warden_dashboard'))




# Tutor Login and Dashboard
@app.route('/tutor_login', methods=['GET', 'POST'])
def tutor_login():
    if request.method == 'POST':
        login_input = request.form['username'].strip().lower()
        password = request.form['password'].strip()
        
        print(f"🔍 Tutor Login attempt - Input: '{login_input}', Password: '{password}'")
        
        # Try to find by email first (more unique), then by username
        tutor = Tutor.query.filter_by(email=login_input).first()
        if not tutor:
            tutor = Tutor.query.filter_by(username=login_input).first()
        
        if tutor:
            print(f"✅ Tutor found: {tutor.name}")
            print(f"   DB Email: '{tutor.email}'")
            print(f"   DB Username: '{tutor.username}'")
            print(f"   DB Password: '{tutor.password}'")
            print(f"   Input Password: '{password}'")
            print(f"   Password match: {tutor.password == password}")
        else:
            print(f"❌ Tutor not found with email/username: '{login_input}'")

        if tutor and tutor.password == password:  # Compare plain text passwords
            session['user_id'] = tutor.id
            session['role'] = 'tutor'
            print(f"✅ Tutor login successful: {tutor.name} (ID: {tutor.id})")
            flash("Login successful!", "success")
            return redirect(url_for('tutor_outpass'))
        else:
            flash("Invalid username/email or password", "danger")
            return redirect(url_for('tutor_login'))
    return render_template('tutor_login.html')

import socket

def check_internet():
    """Check if the internet connection is available."""
    dns_servers = ["8.8.8.8", "1.1.1.1"]  # Google and Cloudflare DNS servers
    timeout = 10  # Increase timeout to 10 seconds for a more reliable check

    for dns in dns_servers:
        try:
            print(f"Checking internet connectivity via {dns}...")
            socket.create_connection((dns, 53), timeout=timeout)
            print("Internet connection is available.")
            return True
        except OSError as e:
            print(f"Internet check failed for {dns}: {e}")
    
    print("No internet connection available.")
    return False


@app.route('/tutor_dashboard', methods=['GET', 'POST'])
def tutor_dashboard():
    if 'user_id' not in session or session.get('role') != 'tutor':
        return redirect(url_for('tutor_login'))

    tutor = db.session.get(Tutor, session['user_id'])  
    if not tutor:
        flash("Tutor not found. Please log in again.", "danger")
        return redirect(url_for('tutor_login'))

    # Handle leave status toggle
    if request.method == 'POST' and 'toggle_leave' in request.form:
        tutor.leave_status = not tutor.leave_status
        db.session.commit()
        flash(f"You are now {'on leave' if tutor.leave_status else 'available'}.", "success")
        return redirect(url_for('tutor_dashboard'))

    # Fetch requests
    if tutor.leave_status:
        requests = []
    else:
        if tutor.username == 'sports1':
            # Sports Tutor only sees sports requests
            requests = Outpass.query.filter_by(
                student_category='sports',
                tutor_status='Pending'
            ).all()
        elif tutor.username == 'international':
            # International Tutor only sees international requests
            requests = Outpass.query.filter_by(
                student_category='international',
                tutor_status='Pending'
            ).all()
        else:
            # Regular Tutors: match department as string, exclude sports/international
            if not tutor.department:
                flash("Your department is not assigned. Contact the admin.", "danger")
                return redirect(url_for('logout'))

            requests = Outpass.query.filter(
                Outpass.department == tutor.department,
                Outpass.student_category.notin_(['sports', 'international']),
                Outpass.tutor_status == 'Pending'
            ).all()

    # Accept/Reject actions
    if request.method == 'POST' and 'request_id' in request.form and 'action' in request.form:
        try:
            request_id = request.form['request_id']
            action = request.form['action']
            tutor_status = 'Accepted' if action == 'Accept' else 'Rejected'

            outpass = db.session.get(Outpass, request_id)

            # Authorization check
            is_authorized = False
            if tutor.username == 'sports1' and outpass.student_category == 'sports':
                is_authorized = True
            elif tutor.username == 'international' and outpass.student_category == 'international':
                is_authorized = True
            elif (tutor.department == outpass.department and
                  outpass.student_category not in ['sports', 'international']):
                is_authorized = True

            if outpass and is_authorized:
                outpass.tutor_status = tutor_status
                db.session.commit()

                flash(f"Request {tutor_status.lower()} successfully!", "success")
            else:
                flash("Unauthorized action. The request does not belong to your department or category.", "danger")

        except Exception as e:
            flash(f"Error occurred: {e}", "danger")

        return redirect(url_for('tutor_dashboard'))

    return render_template('tutor_dashboard.html', tutor=tutor, requests=requests)



@app.route('/warden_login', methods=['GET', 'POST'])
def warden_login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        warden = Warden.query.filter_by(username=username).first()
        
        if warden and warden.password == password:  # Compare plain text passwords
            session['user_id'] = warden.id
            session['role'] = 'warden'
            session['username'] = warden.username  # Add this line to store the username in the session
            flash("Login successful!", "success")
            return redirect(url_for('warden_dashboard'))
        else:
            flash("Invalid username or password", "danger")
            return redirect(url_for('warden_login'))
    return render_template('warden_login.html')




@app.route('/warden_dashboard', methods=['GET', 'POST'])
def warden_dashboard():
    if 'username' not in session or session.get('role') != 'warden':
        return redirect(url_for('warden_login'))

    warden_username = session.get('username')

    if warden_username == "warden1":
        warden_type = "Boys Warden Dashboard"
        gender_filter = "Male"
    elif warden_username == "warden2":
        warden_type = "Girls Warden Dashboard"
        gender_filter = "Female"
    else:
        flash("Unauthorized access.", "danger")
        return redirect(url_for('warden_login'))

    if request.method == 'POST':
        request_id = request.form.get('request_id')
        action = request.form.get('action')

        if not request_id or not action:
            flash("Missing request data.", "danger")
            return redirect(url_for('warden_dashboard'))

        outpass = Outpass.query.get(request_id)
        if not outpass:
            flash("Request not found.", "danger")
            return redirect(url_for('warden_dashboard'))

        student = Student.query.get(outpass.student_id)
        if not student:
            flash("Student not found for this request.", "danger")
            return redirect(url_for('warden_dashboard'))

        print(f"DEBUG: Warden '{warden_username}' (Gender: {gender_filter}) checking student {student.name} ({student.gender})")

        if gender_filter == "Male" and student.gender.name != "Male":
            flash("Unauthorized action. This request does not belong to your category.", "danger")
            return redirect(url_for('warden_dashboard'))
        elif gender_filter == "Female" and student.gender.name != "Female":
            flash("Unauthorized action. This request does not belong to your category.", "danger")
            return redirect(url_for('warden_dashboard'))

        warden_status = 'Accepted' if action == 'Accept' else 'Rejected'
        outpass.warden_status = warden_status

        try:
            if request.form.get('out_date'):
                outpass.out_date = datetime.strptime(request.form['out_date'], '%Y-%m-%d').date()
            if request.form.get('in_date'):
                outpass.in_date = datetime.strptime(request.form['in_date'], '%Y-%m-%d').date()

            # Unified AM/PM or 24-hour format handling for out_time
            if request.form.get('out_time'):
                out_time_str = request.form['out_time'].strip().upper()
                try:
                    if 'AM' in out_time_str or 'PM' in out_time_str:
                        out_time = datetime.strptime(out_time_str, "%I:%M %p").time()
                    else:
                        out_time = datetime.strptime(out_time_str, "%H:%M").time()
                    outpass.out_time = out_time
                except ValueError as e:
                    raise ValueError(f"Invalid out_time format: {out_time_str}")

            # Unified AM/PM or 24-hour format handling for in_time
            if request.form.get('in_time'):
                in_time_str = request.form['in_time'].strip().upper()
                try:
                    if 'AM' in in_time_str or 'PM' in in_time_str:
                        in_time = datetime.strptime(in_time_str, "%I:%M %p").time()
                    else:
                        in_time = datetime.strptime(in_time_str, "%H:%M").time()
                    outpass.in_time = in_time
                except ValueError as e:
                    raise ValueError(f"Invalid in_time format: {in_time_str}")

            db.session.commit()
            flash(f"Request {warden_status.lower()} successfully!", "success")

        except ValueError as ve:
            db.session.rollback()
            flash(str(ve) + ". Please use time format like '02:30 PM' or '14:30'", "danger")
        except Exception as e:
            db.session.rollback()
            flash(f"Database update failed: {str(e)}", "danger")

        return redirect(url_for('warden_dashboard'))

    # Get requests using standardized query
    normal_requests = Outpass.query.join(Student).filter(
        Outpass.tutor_status == 'Accepted',
        Outpass.warden_status == 'Pending',
        Student.gender == gender_filter
    ).all()

    skipped_requests = Outpass.query.join(Student).filter(
        Outpass.tutor_status == 'Skipped',
        Outpass.warden_status == 'Pending',
        Student.gender == gender_filter
    ).all()

    # Get counts using standardized function
    total_boys = Student.query.filter_by(gender='Male').count()
    total_girls = Student.query.filter_by(gender='Female').count()
    
    students_out = get_outpass_counts(gender_filter).count()

    boys_total = total_boys if gender_filter == 'Female' else total_boys - students_out
    girls_total = total_girls if gender_filter == 'Male' else total_girls - students_out

    pending_requests = len(normal_requests) + len(skipped_requests)

    return render_template('warden_dashboard.html',
                         normal_requests=normal_requests,
                         skipped_requests=skipped_requests,
                         warden_type=warden_type,
                         boys_total=boys_total,
                         girls_total=girls_total,
                         students_out=students_out,
                         pending_requests=pending_requests)
                         
                           


from sqlalchemy.exc import OperationalError
import time
from sqlalchemy.orm.attributes import flag_modified

from sqlalchemy.exc import OperationalError

@app.route('/edit_student/<int:student_id>', methods=['GET', 'POST'])
def edit_student(student_id):
    if 'user_id' not in session or session.get('role') != 'warden':
        return redirect(url_for('warden_login'))

    student = Student.query.get_or_404(student_id)
    departments = Department.query.all()  # ✅ Fetch all departments from DB
    hostels = Hostel.query.all()  # ✅ Fetch hostels if needed

    if request.method == 'POST':
        try:
            student.name = request.form['name']
            student.roll_number = request.form['roll_number']
            student.username = request.form['username']
            student.gender = request.form['gender']
            student.parent_phone = request.form['parent_phone']
            student.department = request.form['department']
            student.student_category = request.form['student_category']
            student.room_number = request.form['room_number']
            student.hostel_name = request.form['hostel_name']

            # Handle password update if provided
            new_password = request.form.get('password')
            if new_password and new_password.strip():  # Check if password field is not empty
                student.set_password(new_password)
                flash("Password updated successfully!", "success")

            # Handle photo update if provided
            if 'photo' in request.files and request.files['photo'].filename != '':
                photo = request.files['photo']
                if photo and allowed_file(photo.filename):
                    ext = photo.filename.rsplit(".", 1)[1].lower()
                    photo_filename = f"{secure_filename(student.name.replace(' ', '_'))}.{ext}"
                    photo_path = os.path.join(app.config['UPLOAD_FOLDER'], photo_filename)
                    photo.save(photo_path)
                    student.photo = photo_filename

            db.session.commit()
            flash("Student details updated successfully!", "success")
            return redirect(url_for('warden_dashboard'))
        except Exception as e:
            db.session.rollback()
            flash(f"Error updating student: {str(e)}", "danger")

    return render_template('edit_student.html', student=student, departments=departments,
        hostels=hostels)

    
@app.route('/warden_students/<category>')
def warden_students(category):
    if 'username' not in session or session.get('role') != 'warden':
        return redirect(url_for('warden_login'))

    # Get warden's gender filter
    warden_username = session.get('username')
    gender_filter = 'Male' if warden_username == "warden1" else 'Female' if warden_username == "warden2" else None

    if not gender_filter:
        flash("Unauthorized access.", "danger")
        return redirect(url_for('warden_login'))

    students = []
    title = ""
    now = datetime.now(IST)
    current_date = now.date()

    # Handle boys/girls categories (show all students of that gender)
    if category == 'boys':
        title = "All Boys Students"
        students = Student.query.filter_by(gender='Male').all()
    elif category == 'girls':
        title = "All Girls Students"
        students = Student.query.filter_by(gender='Female').all()
    # ✅ Total Students
    elif category == 'total':
        title = "Total Students"
        students = Student.query.filter_by(gender=gender_filter).all()
    # ✅ Present Students
    elif category == 'present':
        title = "Present Today"
        students = db.session.query(Student).join(Attendance, Attendance.student_id == Student.id).filter(
            Attendance.date == current_date,
            Attendance.status == 'Present',
            Student.gender == gender_filter
        ).all()
    # ✅ Absent (On Outpass)
    elif category == 'absent':
        title = "On Outpass"
        students = db.session.query(Student).join(Outpass, Outpass.student_id == Student.id).filter(
            Outpass.warden_status == 'Accepted',
            Outpass.outted_time.isnot(None),
            Outpass.arrived_time.is_(None),
            Outpass.out_date <= current_date,
            Outpass.in_date >= current_date,
            Student.gender == gender_filter
        ).all()
    # ✅ Missing Students
    elif category == 'missing':
        title = "Missing in Hostel"
        students = Student.query.filter_by(gender=gender_filter).all()

        present_ids = db.session.query(Attendance.student_id).filter(
            Attendance.date == current_date,
            Attendance.status == 'Present'
        ).subquery()

        outpass_ids = db.session.query(Outpass.student_id).filter(
            Outpass.warden_status == 'Accepted',
            Outpass.outted_time.isnot(None),
            Outpass.arrived_time.is_(None),
            Outpass.out_date <= current_date,
            Outpass.in_date >= current_date
        ).subquery()

        students = Student.query.filter(
            Student.gender == gender_filter,
            ~Student.id.in_(present_ids),
            ~Student.id.in_(outpass_ids)
        ).all()
    # ✅ Pending Requests
    elif category == 'pending':
        title = "Pending Requests"
        students = db.session.query(Student).join(Outpass, Outpass.student_id == Student.id).filter(
            Outpass.tutor_status == 'Accepted',
            Outpass.warden_status == 'Pending',
            Student.gender == gender_filter
        ).all()
    else:
        flash("Invalid category.", "danger")
        return redirect(url_for('warden_dashboard'))

    return render_template('warden_students.html', title=title, students=students, category=category)

    


# Watchman Login and Dashboard
@app.route('/watchman_login', methods=['GET', 'POST'])
def watchman_login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        watchman = Watchman.query.filter_by(username=username).first()
        
        if watchman and watchman.password == password:  # Compare plain text passwords
            session['user_id'] = watchman.id
            session['role'] = 'watchman'
            flash("Login successful!", "success")
            return redirect(url_for('watchman_dashboard'))
        else:
            flash("Invalid username or password", "danger")
            return redirect(url_for('watchman_login'))
    return render_template('watchman_login.html')




from datetime import datetime, time as dt_time, timedelta

from datetime import datetime, time as dt_time
import pytz

tz = pytz.timezone('Asia/Kolkata')

@app.route('/watchman_dashboard', methods=['GET', 'POST'])
def watchman_dashboard():
    if 'user_id' not in session or session.get('role') != 'watchman':
        return redirect(url_for('watchman_login'))

    now_dt = datetime.now(IST)
    current_time = now_dt.time()
    current_date = now_dt.date()

    roll_number = None
    view_outted = session.get('view_outted', False)

    if request.method == 'POST':
        # Searching roll number
        if 'roll_number' in request.form:
            roll_number = request.form['roll_number'].strip()
            session['search_roll_number'] = roll_number
            view_outted = False
            session['view_outted'] = False

        elif 'outpass_id' in request.form and 'action' in request.form:
            outpass_id = request.form['outpass_id']
            action = request.form['action']
            outpass = Outpass.query.get(outpass_id)

            if outpass:
                # Ensure proper time formats
                if isinstance(outpass.out_time, str):
                    try:
                        outpass.out_time = datetime.strptime(outpass.out_time, "%H:%M:%S").time()
                    except ValueError:
                        outpass.out_time = datetime.strptime(outpass.out_time, "%I:%M %p").time()

                if isinstance(outpass.in_time, str):
                    try:
                        outpass.in_time = datetime.strptime(outpass.in_time, "%H:%M:%S").time()
                    except ValueError:
                        outpass.in_time = datetime.strptime(outpass.in_time, "%I:%M %p").time()

                # ✅ Mark as Outted
                if action == 'outted' and outpass.outted_time is None:
                    outpass.outted_time = now_dt
                    db.session.commit()
                    flash(f"Student {outpass.name} marked as 'Outted' at {now_dt.strftime('%I:%M %p')}.", "success")

                # ✅ Mark as Arrived
                elif action == 'arrived' and outpass.outted_time is not None and outpass.arrived_time is None:
                    outpass.arrived_time = now_dt
                    db.session.commit()
                    flash(f"Student {outpass.name} marked as 'Arrived' at {now_dt.strftime('%I:%M %p')}.", "success")

                # 🆕 ✅ Delete Outpass (NEW)
                elif action == 'delete':
                    db.session.delete(outpass)
                    db.session.commit()
                    flash(f"Outpass for {outpass.name} has been deleted successfully!", "danger")

            return redirect(url_for('watchman_dashboard'))

        elif 'view_outted' in request.form:
            view_outted = not session.get('view_outted', False)
            session['view_outted'] = view_outted
            if view_outted:
                flash("Showing all outted students", "info")
            else:
                flash("Showing search results only", "info")

    # Load from session
    roll_number = session.get('search_roll_number', '').strip()
    view_outted = session.get('view_outted', False)

    if view_outted:
        outpasses = Outpass.query.filter(
            Outpass.warden_status == 'Accepted',
            Outpass.outted_time.isnot(None),
            Outpass.arrived_time.is_(None)
        ).order_by(Outpass.outted_time.desc()).all()

    elif roll_number:
        outpasses = Outpass.query.filter(
            Outpass.roll_number == roll_number,
            Outpass.warden_status == 'Accepted',
            Outpass.arrived_time.is_(None),
            db.or_(
                db.and_(
                    Outpass.out_date <= current_date,
                    Outpass.in_date >= current_date
                ),
                db.and_(
                    Outpass.outted_time.isnot(None),
                    Outpass.in_date < current_date
                )
            )
        ).order_by(Outpass.out_date, Outpass.out_time).all()
    else:
        outpasses = []

    # Format outpasses
    filtered_outpasses = []
    for outpass in outpasses:
        if isinstance(outpass.out_time, str):
            try:
                outpass.out_time = datetime.strptime(outpass.out_time, "%H:%M:%S").time()
            except ValueError:
                outpass.out_time = datetime.strptime(outpass.out_time, "%I:%M %p").time()

        is_expired = outpass.in_date < current_date if outpass.in_date else False
        filtered_outpasses.append((outpass, True, is_expired))

    return render_template(
        'watchman_dashboard.html',
        outpasses=filtered_outpasses,
        current_time=current_time,
        current_date=current_date,
        roll_number=roll_number,
        view_outted=view_outted
    )

    


@app.template_filter('strptime')
def strptime_filter(value, format='%I:%M %p'):
    if isinstance(value, str) and value.strip():
        try:
            return datetime.strptime(value, format)
        except ValueError:
            return value
    return value


import pytz

@app.template_filter('to_ist')
def to_ist(value):
    if value is None:
        return ""
    import pytz
    ist = pytz.timezone('Asia/Kolkata')
    # If value is naive (no tzinfo), assume UTC
    if value.tzinfo is None:
        value = pytz.utc.localize(value)
    return value.astimezone(ist)

    

@app.route('/submit_outpass', methods=['POST'])
def submit_outpass():
    global active_submissions

    if 'user_id' not in session:
        return redirect(url_for('student_login'))

    with lock:  # Ensure thread-safe access to active_submissions
        if active_submissions >= MAX_CONCURRENT_SUBMISSIONS:
            flash("Too many submissions. Please try again in a few moments.", "danger")
            return redirect(url_for('student_dashboard'))
        active_submissions += 1

    try:
        out_date = request.form['out_date']
        in_date = request.form['in_date']
        reason = request.form['reason']
        student_id = session['user_id']

        # Fetch Student Details
        student = Student.query.get(student_id)
        if not student:
            flash("Student not found.", "danger")
            return redirect(url_for('student_dashboard'))

        parent_phone = student.parent_phone
        student_category = student.student_category  # Fetch category

        # Assign tutor based on category
        tutor_details = {
            "sports": ("sports1", "sports123", "sports_tutor@example.com", "Sports Tutor", "Sports"),
            "international": ("international", "international123", "international@gmail.com", "International Tutor", "International")
        }

        tutor_id = None
        if student_category in tutor_details:
            username, password, email, tutor_name, tutor_department = tutor_details[student_category]

            # Use row-level locking to prevent race conditions
            tutor = db.session.query(Tutor).with_for_update().filter_by(username=username).first()

            if not tutor:
                tutor = Tutor(username=username, password=password, email=email, name=tutor_name, department=tutor_department)
                db.session.add(tutor)
                db.session.commit()

            tutor_id = tutor.id

            # Send email to assigned tutor
            email_subject = f"New Outpass Request - {student.name}"
            email_body = f"A new outpass request has been submitted by {student.name} ({student_category} category).\n\nDetails:\n- Roll Number: {student.roll_number}\n- Department: {student.department}\n- Out Date: {out_date}\n- In Date: {in_date}\n- Reason: {reason}\n- Destination: Not provided"
            send_email(email, email_subject, email_body)

        # Create new outpass request with a database transaction
        new_outpass = Outpass(
            student_id=student_id,
            out_date=out_date,
            in_date=in_date,
            reason=reason,
            tutor_id=tutor_id,  # Assign tutor if applicable
            status="Pending"
        )

        db.session.add(new_outpass)
        db.session.commit()

        # Send SMS Notification to Parent
        if parent_phone:
            message = f"Your child {student.name} has applied for an outpass from {out_date} to {in_date}. Reason: {reason}"
            sms_sid = send_sms(parent_phone, message)

            if sms_sid:
                flash("Outpass submitted. Notification sent to parent.", "success")
            else:
                flash("Outpass submitted, but failed to send SMS.", "warning")
        else:
            flash("Outpass submitted. No parent phone number found.", "warning")

    except Exception as e:
        db.session.rollback()  # Ensure atomic transactions
        flash(f"An error occurred: {str(e)}", "danger")

    finally:
        with lock:
            active_submissions -= 1  # Decrement active submissions after processing

    return redirect(url_for('student_dashboard'))



# Approve or Reject Outpass (Tutor)
@app.route('/approve_outpass', methods=['POST'])
def approve_outpass():
    if 'user_id' not in session:
        return redirect(url_for('tutor_login'))
    
    outpass_id = request.form['outpass_id']
    action = request.form['action']
    
    # Update the outpass request status
    outpass = Outpass.query.get(outpass_id)
    if action == 'approve':
        outpass.tutor_approval = True
    else:
        outpass.tutor_approval = False
    db.session.commit()

    return redirect(url_for('tutor_dashboard'))


@app.route('/accept_outpass', methods=['POST'])
def accept_outpass():
    if 'user_id' not in session or session.get('role') != 'tutor':
        return redirect(url_for('tutor_login'))
    
    outpass_id = request.form['outpass_id']
    action = request.form['action']
    
    # Update the tutor's decision on the request
    outpass = Outpass.query.get(outpass_id)
    if action == 'Accept':
        outpass.tutor_status = 'Accepted'
    else:
        outpass.tutor_status = 'Rejected'
    
    db.session.commit()

    flash("Request accepted! Warden notified.", "success")
    return redirect(url_for('tutor_dashboard'))




@app.route('/reject_outpass', methods=['GET'])
def reject_outpass():
    outpass_id = request.args.get('outpass_id')
    outpass = Outpass.query.get(outpass_id)
    outpass.tutor_status = 'Rejected'
    db.session.commit()

    flash("Request rejected.", "danger")
    return redirect(url_for('tutor_dashboard'))



# Final Approval or Rejection (Warden)
@app.route('/final_approval', methods=['GET'])
def final_approval():
    if 'user_id' not in session or session.get('role') != 'warden':
        return redirect(url_for('warden_login'))

    outpass_id = request.args.get('outpass_id')
    action = request.args.get('action')

    outpass = Outpass.query.get(outpass_id)

    if action == 'accept':
        outpass.warden_status = 'Accepted'
    else:
        outpass.warden_status = 'Rejected'

    db.session.commit()

    flash(f"Request {outpass.warden_status} by Warden.", "success")
    return redirect(url_for('warden_dashboard'))



@app.route('/history', methods=['GET', 'POST'])
def history():
    if 'user_id' not in session:
        flash("You need to log in first!", "error")
        return redirect(url_for('login'))

    requests = []
    rejection_message = None
    current_date = datetime.now(IST).date()  # ✅ today's date in IST

    if request.method == 'POST':
        roll_number = request.form.get('roll_number')

        # ✅ Fetch only valid active outpasses (not returned yet & not expired)
        requests = Outpass.query.filter(
            Outpass.roll_number == roll_number,
            Outpass.arrived_time.is_(None),      # not yet marked as returned
            Outpass.in_date >= current_date,     # still valid (not expired)
            Outpass.tutor_status != 'Rejected',  # not rejected by tutor
            Outpass.warden_status != 'Rejected'  # not rejected by warden
        ).order_by(Outpass.created_at.desc()).all()

        # ✅ If no active requests, check for the most recent rejection
        if not requests:
            rejected_outpass = Outpass.query.filter(
                Outpass.roll_number == roll_number,
                (Outpass.tutor_status == 'Rejected') | (Outpass.warden_status == 'Rejected')
            ).order_by(Outpass.created_at.desc()).first()

            if rejected_outpass:
                if rejected_outpass.tutor_status == 'Rejected':
                    rejection_message = "Tutor Rejected Your Outpass."
                elif rejected_outpass.warden_status == 'Rejected':
                    rejection_message = "Warden Rejected Your Outpass."
            else:
                flash("No outpass history found for this Roll Number.", "info")

    return render_template('history.html', requests=requests, rejection_message=rejection_message)
    


@app.route('/tutor/forgot_password', methods=['GET', 'POST'])
def tutor_forgot_password():
    if request.method == 'POST':
        username = request.form['username']
        tutor = Tutor.query.filter_by(username=username).first()

        if tutor:
            # Generate a password reset token
            token = tutor.get_reset_password_token()
            reset_url = url_for('tutor_reset_password', token=token, _external=True)

            msg = Message('Password Reset Request', sender='your-email@example.com', recipients=[tutor.email])
            msg.body = f"To reset your password, click the following link: {reset_url}"

            try:
                mail.send(msg)
                flash("A password reset link has been sent to your email address.", "success")
            except Exception as e:
                flash("Error: Email could not be sent.", "danger")

            return redirect(url_for('tutor_login'))  # Redirect after processing

    return render_template('tutor_forgot_password.html')  # Ensure a response for GET requests
    
@app.route('/tutor/reset_password/<token>', methods=['GET', 'POST'])
def tutor_reset_password(token):
    tutor = Tutor.verify_reset_password_token(token)  # Verify the token

    if not tutor:
        flash('Invalid or expired token', 'danger')
        return redirect(url_for('tutor_login'))

    if request.method == 'POST':
        new_password = request.form['new_password']
        confirm_password = request.form['confirm_password']

        if new_password != confirm_password:
            flash("Passwords don't match", 'danger')
            return redirect(url_for('tutor_reset_password', token=token))

        tutor.set_password(new_password)  # Set the new password
        db.session.commit()
        flash('Your password has been updated!', 'success')
        return redirect(url_for('tutor_login'))

    return render_template('tutor_reset_password.html', token=token)

import time
import traceback
from flask_mail import Message

import time
import traceback

import logging



def send_email_background(msg):
    """Background task to send email with retries and error handling."""
    max_retries = 3  # Number of retry attempts
    for attempt in range(max_retries):
        try:
            mail.send(msg)
            print(f"📧 Email sent successfully to {msg.recipients}")  # Debugging
            return True  # Success
        except Exception as e:
            error_message = str(e).lower()
            logging.error(f"Email sending failed (Attempt {attempt + 1}): {e}")  # Log the error

            # Specific error handling
            if "authentication failed" in error_message:
                print("❌ Authentication failed. Check your email credentials.")
                break
            elif "network" in error_message or "connection" in error_message:
                print("❌ Network error. Check your internet connection.")
                break
            elif "smtplib" in error_message:
                print("❌ SMTP error. Check your SMTP server configuration.")
                break

            if attempt < max_retries - 1:
                time.sleep(2)  # Wait before retrying

    print("❌ Email could not be sent after multiple attempts.")
    return False  # Failure after all retries


def send_email(msg):
    """Wrapper function to send email in background thread for instant response."""
    thread = threading.Thread(target=send_email_background, args=(msg,))
    thread.daemon = True
    thread.start()
    return True


def create_outpass_async(app_instance, student_id, form_data, student_info):
    """Background task to create outpass record and send notifications."""
    with app_instance.app_context():
        try:
            # Rebuild all data from serialized info
            name = student_info['name']
            department_value = student_info['department']
            student_category_value = student_info['student_category']
            gender_str = student_info['gender']
            gender_value = Gender(gender_str)
            roll_number = student_info['roll_number']
            room_number = student_info['room_number']
            parent_phone = student_info['parent_phone']
            
            # Parse form data
            out_date = form_data.get('out_date')
            in_date = form_data.get('in_date')
            out_hour = form_data.get('out-hour')
            out_minute = form_data.get('out-minute')
            out_am_pm = form_data.get('out-am-pm')
            in_hour = form_data.get('in-hour')
            in_minute = form_data.get('in-minute')
            in_am_pm = form_data.get('in-am-pm')
            destination = form_data.get('destination')
            reason = form_data.get('reason')
            
            # Parse time
            out_time_str = f"{out_hour}:{out_minute} {out_am_pm}".strip()
            in_time_str = f"{in_hour}:{in_minute} {in_am_pm}".strip()
            out_time_str = out_time_str.replace(": ", ":")
            in_time_str = in_time_str.replace(": ", ":")
            out_time_str = " ".join(out_time_str.split())
            in_time_str = " ".join(in_time_str.split())
            
            out_time_24hr = datetime.strptime(out_time_str, "%I:%M %p").time()
            in_time_24hr = datetime.strptime(in_time_str, "%I:%M %p").time()
            
            # Parse dates
            out_date_obj = datetime.strptime(out_date, "%Y-%m-%d").date()
            in_date_obj = datetime.strptime(in_date, "%Y-%m-%d").date()
            
            # Find tutor/warden
            tutor = None
            warden = None
            tutor_status = 'Pending'
            
            if student_category_value == 'sports':
                tutor = Tutor.query.filter_by(username='sports1').first()
                if not tutor or tutor.leave_status:
                    warden = Warden.query.filter_by(username='warden1').first() if gender_str.lower() == 'male' else Warden.query.filter_by(username='warden2').first()
                    tutor_status = 'Skipped'
            elif student_category_value == 'international':
                tutor = Tutor.query.filter_by(username='international').first()
                if not tutor or tutor.leave_status:
                    warden = Warden.query.filter_by(username='warden1').first() if gender_str.lower() == 'male' else Warden.query.filter_by(username='warden2').first()
                    tutor_status = 'Skipped'
            else:
                tutor = Tutor.query.filter_by(department=department_value).first()
                if not tutor or tutor.leave_status:
                    warden = Warden.query.filter_by(username='warden1').first() if gender_str.lower() == 'male' else Warden.query.filter_by(username='warden2').first()
                    tutor_status = 'Skipped'
            
            # Get email recipient
            email_recipient = None
            recipient_role = None
            if tutor and not tutor.leave_status:
                email_recipient = tutor.email
                recipient_role = "Tutor"
            elif warden:
                email_recipient = warden.email
                recipient_role = "Warden"
            
            if not email_recipient:
                print("ERROR: No email recipient found")
                return False
            
            # Create outpass record in database
            new_outpass = Outpass(
                student_id=student_id,
                name=name,
                department=department_value,
                student_category=student_category_value,
                gender=gender_value,
                room_number=room_number,
                roll_number=roll_number,
                photo=student_info['photo'],
                out_date=out_date_obj,
                in_date=in_date_obj,
                out_time=out_time_24hr,
                in_time=in_time_24hr,
                destination=destination,
                reason=reason,
                tutor_status=tutor_status,
                warden_status='Pending',
                hostel_name=student_info['hostel_name'],
                created_at=datetime.now()
            )
            
            db.session.add(new_outpass)
            db.session.commit()
            
            print(f"✅ Outpass created successfully with ID: {new_outpass.id}")
            
            # Send email notification
            if email_recipient:
                accept_url = url_for('process_outpass', request_id=new_outpass.id, action='accept', _external=True)
                reject_url = url_for('process_outpass', request_id=new_outpass.id, action='reject', _external=True)
                
                action_buttons = ""
                if tutor_status == 'Pending':
                    action_buttons = f"""
                    <a href="{accept_url}" style="padding: 10px; background-color: green; color: white; border-radius: 5px;">✅ Accept</a>
                    <a href="{reject_url}" style="padding: 10px; background-color: red; color: white; border-radius: 5px; margin-left: 10px;">❌ Reject</a>
                    """
                elif tutor_status == 'Accepted':
                    action_buttons = """<button disabled style="padding: 10px; background-color: gray; color: white; border-radius: 5px;">✅ Already Accepted</button>"""
                elif tutor_status == 'Rejected':
                    action_buttons = """<button disabled style="padding: 10px; background-color: gray; color: white; border-radius: 5px;">❌ Already Rejected</button>"""
                
                msg = Message("New Outpass Request", recipients=[email_recipient])
                msg.html = f"""
                <html>
                <body>
                    <p>Dear {recipient_role},</p>
                    <p>A student has submitted an outpass request. Please review and take action.</p>
                    <ul>
                        <li><strong>Name:</strong> {name}</li>
                        <li><strong>Roll Number:</strong> {roll_number}</li>
                        <li><strong>Department:</strong> {department_value}</li>
                        <li><strong>Gender:</strong> {gender_str}</li>
                        <li><strong>Hostel Name:</strong> {student_info['hostel_name']}</li>
                        <li><strong>Room Number:</strong> {room_number}</li>
                        <li><strong>Out Date:</strong> {out_date_obj}</li>
                        <li><strong>Out Time:</strong> {out_time_24hr.strftime('%I:%M %p')}</li>
                        <li><strong>In Date:</strong> {in_date_obj}</li>
                        <li><strong>In Time:</strong> {in_time_24hr.strftime('%I:%M %p')}</li>
                        <li><strong>Reason:</strong> {reason}</li>
                        <li><strong>Destination:</strong> {destination}</li>
                        <li><strong>Tutor Name:</strong> {tutor.name if tutor else "Assigned to Warden"}</li>
                    </ul>
                    <p><strong>Take Action:</strong></p>
                    {action_buttons}
                </body>
                </html>
                """
                send_email(msg)
                print(f"📧 Email sent to {email_recipient}")
            
            # Send SMS to parent
            if parent_phone:
                sms_message = f"Dear Parent, your child {name} (Roll No: {roll_number}) has applied for an outpass from {out_date_obj} at {out_time_24hr.strftime('%I:%M %p')} to {in_date_obj} at {in_time_24hr.strftime('%I:%M %p')}. Reason: {reason}. Approval Pending."
                send_sms(parent_phone, sms_message)
                print(f"📱 SMS sent to {parent_phone}")
            
            return True
            
        except Exception as e:
            db.session.rollback()
            print(f"❌ Error in async outpass creation: {e}")
            import traceback
            traceback.print_exc()
            return False



from sqlalchemy.exc import OperationalError
from time import sleep

def execute_query(session, query, params):
    retries = 3
    for _ in range(retries):
        try:
            return session.execute(query, params)
        except OperationalError:
            session.rollback()
            sleep(2)  # Wait before retrying
    raise Exception("Database connection failed after retries.")



from datetime import datetime
@app.route('/emergency_pass', methods=['GET', 'POST'])
def emergency_pass():
    if request.method == 'POST':
        try:
            roll_number = request.form.get('roll_number')
            student = Student.query.filter_by(roll_number=roll_number).first()
            
            if not student:
                flash("Student not found!", "danger")
                return redirect(url_for('emergency_pass'))

            # Get form data
            out_date = datetime.strptime(request.form['out_date'], "%Y-%m-%d").date()
            in_date = datetime.strptime(request.form['in_date'], "%Y-%m-%d").date()
            
            # Convert time to 24-hour format
            out_time_str = f"{request.form['out-hour']}:{request.form['out-minute']} {request.form['out-am-pm']}"
            in_time_str = f"{request.form['in-hour']}:{request.form['in-minute']} {request.form['in-am-pm']}"
            out_time = datetime.strptime(out_time_str, "%I:%M %p").time()
            in_time = datetime.strptime(in_time_str, "%I:%M %p").time()

            # Create emergency outpass
            new_pass = Outpass(
                student_id=student.id,
                name=student.name,
                roll_number=student.roll_number,
                department=student.department,  # String department name
                room_number=student.room_number,
                hostel_name=student.hostel_name,
                gender=student.gender,
                photo=student.photo,
                out_date=out_date,
                in_date=in_date,
                out_time=out_time,
                in_time=in_time,
                reason=request.form['reason'],
                destination="Emergency",
                tutor_status='Accepted',
                warden_status='Accepted',
                student_category='Emergency',
                created_at=datetime.now()
            )

            db.session.add(new_pass)
            db.session.commit()
            
            flash("Emergency pass created successfully!", "success")
            return redirect(url_for('emergency_pass'))
            
        except Exception as e:
            db.session.rollback()
            flash(f"Error creating emergency pass: {str(e)}", "danger")
            return redirect(url_for('emergency_pass'))

    return render_template('emergency_pass.html')
    

    
# Add these routes to your existing app.py

@app.route('/warden_tutors')
def warden_tutors():
    if 'user_id' not in session or session.get('role') != 'warden':
        return redirect(url_for('warden_login'))
    
    tutors = Tutor.query.all()
    return render_template('wardentutor.html', tutors=tutors)

@app.route('/add_tutor', methods=['GET', 'POST'])
def add_tutor():
    if 'user_id' not in session or session.get('role') != 'warden':
        return redirect(url_for('warden_login'))
    
    departments = Department.query.all()
    if request.method == 'POST':
        name = request.form['name']
        username = request.form['username']
        email = request.form['email']
        department_name = request.form['department']  # Get department name
        password = request.form['password']
        
        # Check if username or email already exists
        if Tutor.query.filter_by(username=username).first():
            flash("Username already exists.", "danger")
            return redirect(url_for('add_tutor'))
        if Tutor.query.filter_by(email=email).first():
            flash("Email already exists.", "danger")
            return redirect(url_for('add_tutor'))
        
        # Create new tutor with department name
        new_tutor = Tutor(
            name=name,
            username=username,
            email=email,
            department=department_name,  # Store department name as string
        )
        new_tutor.set_password(password)
        
        try:
            db.session.add(new_tutor)
            db.session.commit()
            flash("Tutor added successfully!", "success")
            return redirect(url_for('warden_tutors'))
        except Exception as e:
            db.session.rollback()
            flash(f"An error occurred: {str(e)}", "danger")
    
    return render_template('add_tutor.html', departments=departments)



@app.route('/edit_tutor/<int:tutor_id>', methods=['GET', 'POST'])
def edit_tutor(tutor_id):
    if 'user_id' not in session or session.get('role') != 'warden':
        return redirect(url_for('warden_login'))
    tutor = Tutor.query.get_or_404(tutor_id)
    departments = Department.query.all()
    if request.method == 'POST':
        tutor.name = request.form['name']
        tutor.username = request.form['username']
        tutor.email = request.form['email']
        tutor.department_id = request.form['department_id']
        tutor.leave_status = request.form.get('leave_status', 'False') == 'True'
        try:
            db.session.commit()
            flash("Tutor updated successfully!", "success")
            return redirect(url_for('warden_tutors'))
        except Exception as e:
            db.session.rollback()
            flash(f"Error updating tutor: {str(e)}", "danger")
    return render_template('edit_tutor.html', tutor=tutor, departments=departments)




@app.route('/delete_tutor/<int:tutor_id>', methods=['POST'])
def delete_tutor(tutor_id):
    if 'user_id' not in session or session.get('role') != 'warden':
        return redirect(url_for('warden_login'))
    
    tutor = Tutor.query.get_or_404(tutor_id)

    try:
        # Check if tutor has assigned students
        if tutor.students:
            flash("Cannot delete tutor with assigned students. Reassign students first.", "danger")
            return redirect(url_for('warden_tutors'))

        db.session.delete(tutor)
        db.session.commit()
        flash("Tutor deleted successfully!", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Error deleting tutor: {str(e)}", "danger")

    return redirect(url_for('warden_tutors'))


import logging
from math import radians, cos, sin, asin, sqrt


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


BOYS_HOSTEL_LOC = (11.0789, 77.1423)    
GIRLS_HOSTEL_LOC = (11.0750, 77.1428)   
RADIUS_KM = 0.5  # 500 meters

def is_within_allowed_range(lat, lon, gender):
    """More flexible location checking with radius buffer"""
    if lat is None or lon is None:
        return False
    
    # Get gender value (handles both enum and string)
    gender_value = gender.value if isinstance(gender, Gender) else gender
    
    # Choose hostel location based on gender
    target_lat, target_lon = BOYS_HOSTEL_LOC if gender_value.lower() == 'male' else GIRLS_HOSTEL_LOC
    
    # Convert decimal degrees to radians
    lat1, lon1, lat2, lon2 = map(radians, [lat, lon, target_lat, target_lon])
    
    # Haversine formula with larger radius (1km)
    dlon = lon2 - lon1 
    dlat = lat2 - lat1 
    a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
    c = 2 * asin(sqrt(a)) 
    distance_km = 6371 * c  # Radius of Earth in km
    
    return distance_km <= 1.0  # 1 kilometer radius



# Attendance System Routes
@app.route('/attendance_dashboard')
def attendance_dashboard():
    if 'user_id' not in session or session.get('role') != 'warden':
        return redirect(url_for('warden_login'))

    try:
        today = datetime.now(IST).date()

        # ✅ Get today's attendance records
        today_attendance_ids = [r.student_id for r in 
                                db.session.query(Attendance.student_id)
                                .filter(Attendance.date == today)
                                .all()]

        # ✅ Get outpass students
        outpass_student_ids = [s.id for s in 
                                db.session.query(Student.id)
                                .join(Outpass)
                                .filter(
                                    Outpass.warden_status == 'Accepted',
                                    Outpass.out_date <= today,
                                    Outpass.in_date >= today,
                                    Outpass.outted_time.isnot(None),
                                    Outpass.arrived_time.is_(None)
                                ).all()]

        # ✅ Get all students
        all_students = Student.query.options(
            db.load_only(
                Student.id,
                Student.roll_number,
                Student.name,
                Student.gender,
                Student.hostel_name,
                Student.room_number
            )
        ).all()

        # ✅ Initialize combined attendance data
        attendance_data = {
            'Present': 0,
            'Absent': 0,
            'Missing': 0,
            'Total': 0,
            'PresentStudents': [],
            'AbsentStudents': [],
            'MissingStudents': []
        }

        # ✅ Gender stats (if needed)
        gender_stats = {
            'total': {'male': 0, 'female': 0, 'other': 0},
            'present': {'male': 0, 'female': 0, 'other': 0},
            'absent': {'male': 0, 'female': 0, 'other': 0},
            'missing': {'male': 0, 'female': 0, 'other': 0}
        }

        # ✅ Calculate attendance
        for student in all_students:
            attendance_data['Total'] += 1

            gender = student.gender.value.lower() if isinstance(student.gender, Gender) else (student.gender.lower() if student.gender else 'other')
            gender_stats['total'][gender] += 1

            has_attendance = student.id in today_attendance_ids
            is_on_outpass = student.id in outpass_student_ids

            if has_attendance:
                attendance_data['Present'] += 1
                attendance_data['PresentStudents'].append(student)
                gender_stats['present'][gender] += 1
            elif is_on_outpass:
                attendance_data['Absent'] += 1
                attendance_data['AbsentStudents'].append(student)
                gender_stats['absent'][gender] += 1
            else:
                attendance_data['Missing'] += 1
                attendance_data['MissingStudents'].append(student)
                gender_stats['missing'][gender] += 1

        return render_template(
            'attendance_dashboard.html',
            attendance_data=attendance_data,
            gender_stats=gender_stats,
            today=today.strftime('%Y-%m-%d')
        )

    except Exception as e:
        app.logger.error(f"Error in attendance_dashboard: {str(e)}", exc_info=True)
        flash("An error occurred while generating the attendance report", "danger")
        return redirect(url_for('warden_dashboard'))

        
        

import pytz  # Import pytz for timezone handling


from sqlalchemy import func  # Add this import at the top of your file with other imports

@app.route('/mark_attendance', methods=['GET', 'POST'])
def mark_attendance():
    # Authentication check
    if 'user_id' not in session or session.get('role') != 'student':
        logger.warning("Unauthorized access attempt to mark_attendance")
        flash("Please login as a student to mark attendance", "warning")
        return redirect(url_for('student_login'))
    
    student = Student.query.get(session['user_id'])
    if not student:
        logger.error(f"Student not found for user_id: {session['user_id']}")
        flash("Student not found in our records", "danger")
        return redirect(url_for('student_dashboard'))

    # Current date & time
    ist = pytz.timezone('Asia/Kolkata')
    now = datetime.now(ist)
    current_date = now.date()

    # Modified check for active outpass
    active_outpass = Outpass.query.filter(
        Outpass.student_id == student.id,
        Outpass.warden_status == 'Accepted',
        Outpass.out_date <= current_date,
        Outpass.in_date >= current_date,
        Outpass.outted_time.isnot(None),
        Outpass.arrived_time.is_(None)
    ).first()
    
    if active_outpass:
        logger.info(f"Student {student.id} attempted to mark attendance with active outpass")
        flash("You cannot mark attendance while on an active outpass", "danger")
        return redirect(url_for('student_dashboard'))

    if request.method == 'POST':
        # Get the real client IP (works behind proxies)
        if request.headers.getlist("X-Forwarded-For"):
            ip_address = request.headers.getlist("X-Forwarded-For")[0]
        else:
            ip_address = request.remote_addr
            
        device_id = request.form.get('device_id')
        user_agent = request.headers.get('User-Agent', 'unknown')
        
        logger.info(f"Attendance attempt - Student: {student.id}, IP: {ip_address}, Device: {device_id}")

        # Check existing attendance for today
        existing = Attendance.query.filter(
            Attendance.student_id == student.id,
            Attendance.date == current_date
        ).first()
        
        if existing:
            flash("You've already marked attendance today", "info")
            return redirect(url_for('student_dashboard'))

        # Device/IP double-use detection
        recent_marks = Attendance.query.filter(
            db.or_(
                db.and_(
                    Attendance.ip_address == ip_address,
                    Attendance.student_id != student.id
                ),
                db.and_(
                    Attendance.device_id == device_id,
                    Attendance.device_id != None,
                    Attendance.student_id != student.id
                )
            ),
            Attendance.date == current_date,
            Attendance.time >= (now - timedelta(hours=1)).time()
        ).count()

        if recent_marks > 0:
            flash("This device/network was recently used by another student. Please use your own device.", "warning")
            return redirect(url_for('mark_attendance'))

        # Location validation
        verification_method = 'gps'
        try:
            lat = float(request.form.get('latitude', 0))
            lon = float(request.form.get('longitude', 0))
            
            if not is_within_allowed_range(lat, lon, student.gender):
                verification_method = 'manual'
                logger.warning(f"Student {student.id} outside allowed location")
                flash("Location verification failed. Please see warden for manual attendance.", "warning")
                return redirect(url_for('mark_attendance'))
        except (TypeError, ValueError):
            verification_method = 'wifi'
            lat = lon = None

        # Time window with grace period
        current_hour = now.hour
        if not (19 <= current_hour < 21):  # 7 PM to 9 PM
            flash("Attendance can be marked between 7:00 PM and 9:00 PM IST", "info")
            return redirect(url_for('mark_attendance'))

        # Create attendance record
        new_attendance = Attendance(
            student_id=student.id,
            date=current_date,
            time=now.time(),
            status='Present',
            ip_address=ip_address,
            device_id=device_id,
            user_agent=user_agent,
            latitude=lat,
            longitude=lon,
            verification_method=verification_method
        )

        try:
            db.session.add(new_attendance)
            db.session.commit()
            logger.info(f"Attendance marked for {student.id} via {verification_method}")
            flash("Attendance marked successfully!", "success")
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error saving attendance: {str(e)}")
            flash("Technical error marking attendance. Please try again.", "danger")

        return redirect(url_for('student_dashboard'))
    
    # Generate device ID for first-time GET request
    device_id = str(uuid.uuid4()) if not request.form.get('device_id') else None
    
    return render_template('mark_attendance.html', 
                         student=student,
                         device_id=device_id,
                         current_time=datetime.now(pytz.timezone('Asia/Kolkata')).strftime('%I:%M %p'))

                         
    
    
    
def generate_report_text():
    try:
        today = datetime.now(pytz.timezone('Asia/Kolkata')).date()
        current_time = datetime.now().strftime("%d-%m-%Y %H:%M:%S")

        # Get attendance records with student details
        attendance_records = db.session.query(
            Attendance, Student
        ).join(Student, Attendance.student_id == Student.id).filter(
            Attendance.date == today
        ).all()

        outpass_students = db.session.query(Student).join(Outpass).filter(
            Outpass.warden_status == 'Accepted',
            Outpass.outted_time.isnot(None),
            Outpass.arrived_time.is_(None),
            Outpass.out_date <= today,
            Outpass.in_date >= today
        ).all()

        all_students = Student.query.all()

        # Get all departments and hostels from database
        all_departments = Department.query.all()
        all_hostels = Hostel.query.all()

        hostel_data = {}
        department_data = {}
        year_data = {}

        # Get present students lists by gender
        present_male = []
        present_female = []
        
        for student in all_students:
            hostel = student.hostel_name
            department = student.department
            year = student.roll_number[:2] if student.roll_number and len(student.roll_number) >= 2 else 'Unknown'
            gender = student.gender.value if isinstance(student.gender, Enum) else student.gender

            # Initialize hostel data
            if hostel not in hostel_data:
                hostel_data[hostel] = {'present': 0, 'absent': 0, 'missing': 0, 'total': 0}

            # Initialize department data
            if department not in department_data:
                department_data[department] = {'present': 0, 'absent': 0, 'missing': 0, 'total': 0}

            # Initialize year data
            if year not in year_data:
                year_data[year] = {'present': 0, 'absent': 0, 'missing': 0, 'total': 0}

            # Update counts
            hostel_data[hostel]['total'] += 1
            department_data[department]['total'] += 1
            year_data[year]['total'] += 1

            has_attendance = any(record.Student.id == student.id for record in attendance_records)
            is_on_outpass = student in outpass_students

            if has_attendance:
                hostel_data[hostel]['present'] += 1
                department_data[department]['present'] += 1
                year_data[year]['present'] += 1
                # Add to present students list
                if gender.lower() == 'male':
                    present_male.append(student)
                elif gender.lower() == 'female':
                    present_female.append(student)
            elif is_on_outpass:
                hostel_data[hostel]['absent'] += 1
                department_data[department]['absent'] += 1
                year_data[year]['absent'] += 1
            else:
                hostel_data[hostel]['missing'] += 1
                department_data[department]['missing'] += 1
                year_data[year]['missing'] += 1

        total_present = sum(h['present'] for h in hostel_data.values())
        total_absent = sum(h['absent'] for h in hostel_data.values())
        total_missing = sum(h['missing'] for h in hostel_data.values())
        total_students = sum(h['total'] for h in hostel_data.values())

        # Get absent and missing students lists
        absent_male = [s for s in outpass_students if s.gender.value.lower() == 'male']
        absent_female = [s for s in outpass_students if s.gender.value.lower() == 'female']
        missing_male = [s for s in all_students 
                       if s not in outpass_students and 
                       not any(record.Student.id == s.id for record in attendance_records) and 
                       s.gender.value.lower() == 'male']
        missing_female = [s for s in all_students 
                         if s not in outpass_students and 
                         not any(record.Student.id == s.id for record in attendance_records) and 
                         s.gender.value.lower() == 'female']

        # HTML with improved styling and container alignment
        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Hostel Attendance Report - {today.strftime('%d-%m-%Y')}</title>
            <style>
                body {{
                    font-family: Arial, sans-serif;
                    margin: 0;
                    padding: 20px;
                    color: #333;
                }}
                .container {{
                    max-width: 1200px;
                    margin: 0 auto;
                    padding: 20px;
                    background-color: #fff;
                    box-shadow: 0 0 10px rgba(0,0,0,0.1);
                }}
                .header {{
                    text-align: center;
                    margin-bottom: 30px;
                    padding-bottom: 20px;
                    border-bottom: 1px solid #eee;
                }}
                .header h1 {{
                    color: #2c3e50;
                    margin-bottom: 5px;
                }}
                .header p {{
                    color: #7f8c8d;
                    margin-top: 0;
                }}
                .report-info {{
                    background-color: #f8f9fa;
                    padding: 15px;
                    border-radius: 5px;
                    margin-bottom: 20px;
                }}
                table {{
                    width: 100%;
                    border-collapse: collapse;
                    margin-bottom: 30px;
                    box-shadow: 0 0 20px rgba(0,0,0,0.1);
                }}
                th, td {{
                    padding: 12px 15px;
                    text-align: center;
                    border: 1px solid #ddd;
                }}
                th {{
                    background-color: #3498db;
                    color: white;
                    font-weight: bold;
                }}
                tr:nth-child(even) {{
                    background-color: #f2f2f2;
                }}
                tr:hover {{
                    background-color: #e3f2fd;
                }}
                .total-row {{
                    font-weight: bold;
                    background-color: #e1f5fe;
                }}
                .student-list {{
                    margin-top: 40px;
                    page-break-before: always;
                }}
                .student-list h3 {{
                    color: #2c3e50;
                    border-bottom: 2px solid #3498db;
                    padding-bottom: 10px;
                    margin-top: 30px;
                }}
                .student-table {{
                    width: 100%;
                    border-collapse: collapse;
                    margin-bottom: 20px;
                }}
                .student-table th {{
                    background-color: #3498db;
                    color: white;
                    text-align: left;
                    padding: 10px 15px;
                }}
                .student-table td {{
                    padding: 8px 15px;
                    border-bottom: 1px solid #ddd;
                    text-align: left;
                }}
                .student-table tr:nth-child(even) {{
                    background-color: #f9f9f9;
                }}
                .footer {{
                    text-align: center;
                    margin-top: 30px;
                    padding-top: 20px;
                    border-top: 1px solid #eee;
                    color: #7f8c8d;
                    font-size: 0.9em;
                }}
                .section-header {{
                    background-color: #2c3e50;
                    color: white;
                    padding: 10px;
                    margin-top: 30px;
                    border-radius: 5px;
                }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>Hostel Management System - Attendance Report</h1>
                    <p>Generated on: {today.strftime('%B %d, %Y')} at {current_time}</p>
                </div>

                <div class="report-info">
                    <strong>Total Students:</strong> {total_students} | 
                    <strong>Present:</strong> {total_present} | 
                    <strong>On Outpass:</strong> {total_absent} | 
                    <strong>Missing:</strong> {total_missing}
                </div>

                <div class="section-header">
                    <h2>Hostel Wise Attendance</h2>
                </div>
                <table>
                    <tr>
                        <th>S.No</th>
                        <th>Hostel Name</th>
                        <th>Total</th>
                        <th>Present</th>
                        <th>On Outpass</th>
                        <th>Missing</th>
                        <th>Attendance %</th>
                    </tr>
        """

        for i, (hostel, stats) in enumerate(hostel_data.items(), start=1):
            attendance_percentage = (stats['present'] / stats['total'] * 100) if stats['total'] > 0 else 0
            html += f"""
                    <tr>
                        <td>{i}</td>
                        <td>{hostel}</td>
                        <td>{stats['total']}</td>
                        <td>{stats['present']}</td>
                        <td>{stats['absent']}</td>
                        <td>{stats['missing']}</td>
                        <td>{attendance_percentage:.1f}%</td>
                    </tr>
            """

        html += f"""
                    <tr class="total-row">
                        <td colspan="2">Total</td>
                        <td>{total_students}</td>
                        <td>{total_present}</td>
                        <td>{total_absent}</td>
                        <td>{total_missing}</td>
                        <td>{(total_present/total_students*100) if total_students > 0 else 0:.1f}%</td>
                    </tr>
                </table>

                <div class="section-header">
                    <h2>Department Wise Attendance</h2>
                </div>
                <table>
                    <tr>
                        <th>S.No</th>
                        <th>Department</th>
                        <th>Total</th>
                        <th>Present</th>
                        <th>On Outpass</th>
                        <th>Missing</th>
                        <th>Attendance %</th>
                    </tr>
        """

        for i, (department, stats) in enumerate(department_data.items(), start=1):
            attendance_percentage = (stats['present'] / stats['total'] * 100) if stats['total'] > 0 else 0
            html += f"""
                    <tr>
                        <td>{i}</td>
                        <td>{department}</td>
                        <td>{stats['total']}</td>
                        <td>{stats['present']}</td>
                        <td>{stats['absent']}</td>
                        <td>{stats['missing']}</td>
                        <td>{attendance_percentage:.1f}%</td>
                    </tr>
            """

 

        for i, (year, stats) in enumerate(year_data.items(), start=1):
            attendance_percentage = (stats['present'] / stats['total'] * 100) if stats['total'] > 0 else 0
            html += f"""
                    <tr>
                        <td>{i}</td>
                        <td>{year}</td>
                        <td>{stats['total']}</td>
                        <td>{stats['present']}</td>
                        <td>{stats['absent']}</td>
                        <td>{stats['missing']}</td>
                        <td>{attendance_percentage:.1f}%</td>
                    </tr>
            """

        html += f"""
                    <tr class="total-row">
                        <td colspan="2">Total</td>
                        <td>{total_students}</td>
                        <td>{total_present}</td>
                        <td>{total_absent}</td>
                        <td>{total_missing}</td>
                        <td>{(total_present/total_students*100) if total_students > 0 else 0:.1f}%</td>
                    </tr>
                </table>

                <div class="student-list">
                    <h3>Present Students (Male)</h3>
                    <table class="student-table">
                        <tr>
                            <th>S.No</th>
                            <th>Roll Number</th>
                            <th>Name</th>
                            <th>Department</th>
                            <th>Hostel</th>
                            <th>Room No</th>
                        </tr>
        """

        for i, student in enumerate(present_male, start=1):
            html += f"""
                        <tr>
                            <td>{i}</td>
                            <td>{student.roll_number}</td>
                            <td>{student.name}</td>
                            <td>{student.department}</td>
                            <td>{student.hostel_name}</td>
                            <td>{student.room_number}</td>
                        </tr>
            """

        html += """
                    </table>

                    <h3>Present Students (Female)</h3>
                    <table class="student-table">
                        <tr>
                            <th>S.No</th>
                            <th>Roll Number</th>
                            <th>Name</th>
                            <th>Department</th>
                            <th>Hostel</th>
                            <th>Room No</th>
                        </tr>
        """

        for i, student in enumerate(present_female, start=1):
            html += f"""
                        <tr>
                            <td>{i}</td>
                            <td>{student.roll_number}</td>
                            <td>{student.name}</td>
                            <td>{student.department}</td>
                            <td>{student.hostel_name}</td>
                            <td>{student.room_number}</td>
                        </tr>
            """

        html += """
                    </table>

                    <h3>Students on Outpass (Male)</h3>
                    <table class="student-table">
                        <tr>
                            <th>S.No</th>
                            <th>Roll Number</th>
                            <th>Name</th>
                            <th>Department</th>
                            <th>Hostel</th>
                            <th>Room No</th>
                        </tr>
        """

        for i, student in enumerate(absent_male, start=1):
            html += f"""
                        <tr>
                            <td>{i}</td>
                            <td>{student.roll_number}</td>
                            <td>{student.name}</td>
                            <td>{student.department}</td>
                            <td>{student.hostel_name}</td>
                            <td>{student.room_number}</td>
                        </tr>
            """

        html += """
                    </table>

                    <h3>Students on Outpass (Female)</h3>
                    <table class="student-table">
                        <tr>
                            <th>S.No</th>
                            <th>Roll Number</th>
                            <th>Name</th>
                            <th>Department</th>
                            <th>Hostel</th>
                            <th>Room No</th>
                        </tr>
        """

        for i, student in enumerate(absent_female, start=1):
            html += f"""
                        <tr>
                            <td>{i}</td>
                            <td>{student.roll_number}</td>
                            <td>{student.name}</td>
                            <td>{student.department}</td>
                            <td>{student.hostel_name}</td>
                            <td>{student.room_number}</td>
                        </tr>
            """

        html += """
                    </table>

                    <h3>Missing Students (Male)</h3>
                    <table class="student-table">
                        <tr>
                            <th>S.No</th>
                            <th>Roll Number</th>
                            <th>Name</th>
                            <th>Department</th>
                            <th>Hostel</th>
                            <th>Room No</th>
                        </tr>
        """

        for i, student in enumerate(missing_male, start=1):
            html += f"""
                        <tr>
                            <td>{i}</td>
                            <td>{student.roll_number}</td>
                            <td>{student.name}</td>
                            <td>{student.department}</td>
                            <td>{student.hostel_name}</td>
                            <td>{student.room_number}</td>
                        </tr>
            """

        html += """
                    </table>

                    <h3>Missing Students (Female)</h3>
                    <table class="student-table">
                        <tr>
                            <th>S.No</th>
                            <th>Roll Number</th>
                            <th>Name</th>
                            <th>Department</th>
                            <th>Hostel</th>
                            <th>Room No</th>
                        </tr>
        """

        for i, student in enumerate(missing_female, start=1):
            html += f"""
                        <tr>
                            <td>{i}</td>
                            <td>{student.roll_number}</td>
                            <td>{student.name}</td>
                            <td>{student.department}</td>
                            <td>{student.hostel_name}</td>
                            <td>{student.room_number}</td>
                        </tr>
            """

        html += """
                    </table>
                </div>
                
                <div class="footer">
                    <p>This report was automatically generated by the Hostel Management System</p>
                    <p>Report includes data from {len(all_departments)} departments and {len(all_hostels)} hostels</p>
                </div>
            </div>
        </body>
        </html>
        """

        return html
        
    except Exception as e:
        app.logger.error(f"Error generating report: {str(e)}", exc_info=True)
        return "<h1>Error generating report</h1>"
        

        
        


from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz
from datetime import datetime
import atexit
import logging
from flask import Flask
from functools import wraps

# Configure logging for the scheduler
logging.basicConfig()
logging.getLogger('apscheduler').setLevel(logging.DEBUG)

# Initialize scheduler as None initially
scheduler = None

def with_app_context(func):
    """Decorator to ensure function runs with app context"""
    @wraps(func)
    def wrapper(*args, **kwargs):
        with app.app_context():
            return func(*args, **kwargs)
    return wrapper

def init_scheduler():
    """Initialize the scheduler with proper configuration"""
    global scheduler
    if scheduler is None or not scheduler.running:
        scheduler = BackgroundScheduler(
            timezone=pytz.timezone('Asia/Kolkata'),
            job_defaults={
                'misfire_grace_time': 60*60,  # 1 hour grace period for missed jobs
                'coalesce': True,            # Combine multiple missed runs into one
                'max_instances': 1           # Only one instance of each job
            }
        )
    return scheduler

@with_app_context
def send_daily_attendance_report_email():
    """Send the daily attendance report to wardens with error handling"""
    try:
        current_time = datetime.now(pytz.timezone('Asia/Kolkata'))
        print(f"⏰ Attempting to send daily attendance report at {current_time}")
        
        # Generate the report (use HTML format)
        report_html = generate_report_text()
        
        # Get all warden emails
        wardens = Warden.query.all()
        if not wardens:
            print("⚠️ No wardens found in database")
            return
        
        warden_emails = [warden.email for warden in wardens]
        
        # Create and send email
        msg = Message(
            subject=f"Daily Hostel Attendance Report - {current_time.strftime('%d-%m-%Y')}",
            recipients=warden_emails,
            html=report_html
        )
        
        # Send email with error handling
        mail.send(msg)
        print(f"✅ Successfully sent attendance report to {len(warden_emails)} wardens")
        
    except Exception as e:
        print(f"❌ Failed to send attendance report: {str(e)}")
        import traceback
        traceback.print_exc()

def schedule_daily_tasks():
    """Schedule all recurring tasks"""
    try:
        scheduler = init_scheduler()
        
        # Schedule the daily report at 10:00 PM IST
        scheduler.add_job(
            func=send_daily_attendance_report_email,
            trigger=CronTrigger(
                hour=22,  # 10 PM
                minute=0,
                timezone='Asia/Kolkata'
            ),
            id='daily_attendance_report',
            replace_existing=True,
            name='Daily Attendance Report'
        )
        print("📅 Scheduled daily attendance report at 22:00 IST")
        
    except Exception as e:
        print(f"Failed to schedule tasks: {str(e)}")
        raise

def start_scheduler():
    """Start the scheduler with proper initialization"""
    try:
        scheduler = init_scheduler()
        
        if not scheduler.running:
            scheduler.start()
            schedule_daily_tasks()
            print("🚀 Scheduler started successfully")
            
            # Register shutdown handler that checks if running
            atexit.register(shutdown_scheduler)
            
    except Exception as e:
        print(f"Failed to start scheduler: {str(e)}")
        raise

def shutdown_scheduler():
    """Shutdown the scheduler safely"""
    global scheduler
    if scheduler is not None and scheduler.running:
        try:
            print("🛑 Shutting down scheduler...")
            scheduler.shutdown(wait=False)
        except Exception as e:
            print(f"Error during scheduler shutdown: {str(e)}")
    scheduler = None

@app.teardown_appcontext
def teardown_scheduler(exception=None):
    """Ensure scheduler shuts down properly on app teardown"""
    shutdown_scheduler()

# Start the scheduler when app starts
start_scheduler()


        
@app.route('/generate_attendance_report')
def generate_attendance_report():
    if 'user_id' not in session or session.get('role') != 'warden':
        return redirect(url_for('warden_login'))
    
    try:
        report_html = generate_report_text()
        return Response(report_html, mimetype='text/html')
    except Exception as e:
        app.logger.error(f"Error in generate_attendance_report: {str(e)}", exc_info=True)
        flash("An error occurred while generating the attendance report", "danger")
        return redirect(url_for('warden_dashboard'))

        
    
@app.route('/send_attendance_report')
def send_attendance_report():
    with app.app_context():
        try:
            # Generate the report
            report_html = generate_report_text()
            
            # Get warden emails
            warden_emails = [warden.email for warden in Warden.query.all()]
            
            if not warden_emails:
                print("No warden emails found to send the report")
                return "No warden emails found."   # <-- Return something here
            
            # Create and send email with HTML content
            msg = Message(
                subject=f"Daily Hostel Attendance Report - {datetime.now().strftime('%d-%m-%Y')}",
                recipients=warden_emails
            )
            msg.html = report_html
            
            mail.send(msg)
            print("Daily attendance report sent successfully")
            return "Daily attendance report sent successfully."  # <-- Return a message
        
        except Exception as e:
            print(f"Error sending daily attendance report: {str(e)}")
            return f"Failed to send report: {str(e)}"   # <-- Return error as response

    


# ...existing code...

@app.route('/manage_departments', methods=['GET', 'POST'])
def manage_departments():
    if 'user_id' not in session or session.get('role') != 'warden':
        return redirect(url_for('warden_login'))
    if request.method == 'POST':
        dept_name = request.form.get('department_name')
        if dept_name and not Department.query.filter_by(name=dept_name).first():
            db.session.add(Department(name=dept_name))
            db.session.commit()
            flash("Department added!", "success")
        else:
            flash("Department already exists or invalid.", "danger")
    departments = Department.query.all()
    return render_template('manage_departments.html', departments=departments)

@app.route('/manage_hostels', methods=['GET', 'POST'])
def manage_hostels():
    if 'user_id' not in session or session.get('role') != 'warden':
        return redirect(url_for('warden_login'))
    if request.method == 'POST':
        hostel_name = request.form.get('hostel_name')
        if hostel_name and not Hostel.query.filter_by(name=hostel_name).first():
            db.session.add(Hostel(name=hostel_name))
            db.session.commit()
            flash("Hostel added!", "success")
        else:
            flash("Hostel already exists or invalid.", "danger")
    hostels = Hostel.query.all()
    return render_template('manage_hostels.html', hostels=hostels)



@app.route('/delete_department/<int:department_id>')
def delete_department(department_id):
    if 'user_id' not in session or session.get('role') != 'warden':
        return redirect(url_for('warden_login'))
    department = Department.query.get_or_404(department_id)
    db.session.delete(department)
    db.session.commit()
    flash("Department deleted!", "success")
    return redirect(url_for('manage_departments'))



@app.route('/delete_hostel/<int:hostel_id>')
def delete_hostel(hostel_id):
    if 'user_id' not in session or session.get('role') != 'warden':
        return redirect(url_for('warden_login'))
    hostel = Hostel.query.get_or_404(hostel_id)
    db.session.delete(hostel)
    db.session.commit()
    flash("Hostel deleted!", "success")
    return redirect(url_for('manage_hostels'))

# ...existing code...

@app.route('/change_password_warden', methods=['GET', 'POST'])
def change_password_warden():
    if 'user_id' not in session or session.get('role') != 'warden':
        return redirect(url_for('warden_login'))
    warden = Warden.query.get(session['user_id'])
    if request.method == 'POST':
        username = request.form['username']
        new_password = request.form['new_password']
        confirm_password = request.form['confirm_password']
        if username != warden.username:
            flash("Username incorrect.", "danger")
       
        elif new_password != confirm_password:
            flash("New passwords do not match.", "danger")
        else:
            warden.set_password(new_password)
            db.session.commit()
            flash("Password changed successfully!", "success")
            return redirect(url_for('warden_dashboard'))
    return render_template('change_password_warden.html')



@app.route('/change_password_watchman', methods=['GET', 'POST'])
def change_password_watchman():
    watchman = None

    # If watchman is logged in, get details
    if 'watchman_id' in session:
        watchman = Watchman.query.get(session['watchman_id'])

    if request.method == 'POST':
        username = request.form.get('username')  # username instead of current password
        new_password = request.form.get('new_password')
        confirm_password = request.form.get('confirm_password')

        if not watchman:
            flash("No active session. Please enter valid username.", "danger")
        elif username != watchman.username:
            flash("Entered username is incorrect.", "danger")
        elif new_password != confirm_password:
            flash("New passwords do not match.", "danger")
        else:
            watchman.set_password(new_password)
            db.session.commit()
            flash("Password changed successfully!", "success")
            return redirect(url_for('watchman_dashboard'))

    # Render page regardless (even if not logged in)
    return render_template('change_password_watchman.html')


@app.route('/add_watchman', methods=['GET', 'POST'])
def add_watchman():
    if 'user_id' not in session or session.get('role') != 'warden':
        return redirect(url_for('warden_login'))
    if request.method == 'POST':
        name = request.form['name']
        username = request.form['username']
        password = request.form['password']
        if Watchman.query.filter_by(username=username).first():
            flash("Username already exists.", "danger")
            return redirect(url_for('add_watchman'))
        new_watchman = Watchman(name=name, username=username)
        new_watchman.set_password(password)
        db.session.add(new_watchman)
        db.session.commit()
        flash("Watchman added successfully!", "success")
        return redirect(url_for('warden_dashboard'))
    return render_template('add_watchman.html')

# Logout Route
@app.route('/logout', methods=['GET'])
def logout():
    session.pop('role', None)  # Ensure session is cleared
    return redirect(url_for('login'))  # Redirect back to login

# ============================================================
# NEW ROUTES — paste these into app.py BEFORE the if __name__ == "__main__" line
# ============================================================

# ── Period Schedule ──────────────────────────────────────────
# Standard 8-period schedule (IST, 24-hour).
# Adjust start/end times to match your actual timetable.
PERIOD_SCHEDULE = [
    {"number": 1, "start": "08:40", "end": "09:30"},
    {"number": 2, "start": "09:30", "end": "10:20"},
    {"number": 3, "start": "10:30", "end": "11:20"},
    {"number": 4, "start": "11:20", "end": "12:10"},
    {"number": 5, "start": "13:00", "end": "13:50"},
    {"number": 6, "start": "13:50", "end": "14:40"},
    {"number": 7, "start": "14:40", "end": "15:30"},
    {"number": 8, "start": "15:30", "end": "16:20"},
]

# ── College GPS Coordinates ──────────────────────────────────
# ⚠️  Replace with real college lat/lon before going live
COLLEGE_LAT = 11.0789   # PLACEHOLDER – fill in actual latitude
COLLEGE_LON = 77.1423   # PLACEHOLDER – fill in actual longitude
COLLEGE_RADIUS_KM = 0.5  # 500-metre allowed radius


# ── PeriodAttendance SQLAlchemy Model ────────────────────────
class PeriodAttendance(db.Model):
    """Stores per-period attendance for each student."""
    __tablename__ = 'period_attendance'
    __table_args__ = {'extend_existing': True}

    # Use BigInteger (unsigned via MySQL BIGINT UNSIGNED) to match student.id SERIAL type
    id           = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    student_id   = db.Column(db.BigInteger, db.ForeignKey('student.id'), nullable=False)
    date         = db.Column(db.Date, nullable=False)
    period_number= db.Column(db.SmallInteger, nullable=False)   # 1–8
    status       = db.Column(db.String(10), nullable=False, default='Absent')  # Present / Absent
    attendance_type = db.Column(db.String(20), nullable=False, default='regular')  # dayscholar / hosteller
    marked_at    = db.Column(db.DateTime, nullable=True)
    latitude     = db.Column(db.Float, nullable=True)
    longitude    = db.Column(db.Float, nullable=True)

    student = db.relationship('Student', backref=db.backref('period_records', lazy=True))


# ── Helper: get period info for today ───────────────────────
def get_period_info(student_id, date, attendance_type):
    """
    Returns a list of period dicts for the given student & date.
    Each dict includes: number, start, end, is_active, is_past,
    already_marked, marked_status.
    """
    ist = pytz.timezone('Asia/Kolkata')
    now = datetime.now(ist)
    current_time_str = now.strftime('%H:%M')

    # Fetch all already-marked records for this student on this date
    existing = {
        r.period_number: r.status
        for r in PeriodAttendance.query.filter_by(
            student_id=student_id, date=date, attendance_type=attendance_type
        ).all()
    }

    periods = []
    for p in PERIOD_SCHEDULE:
        is_active = p['start'] <= current_time_str <= p['end']
        is_past   = current_time_str > p['end']
        already_marked = p['number'] in existing

        periods.append({
            'number':        p['number'],
            'start':         p['start'],
            'end':           p['end'],
            'is_active':     is_active,
            'is_past':       is_past,
            'already_marked':already_marked,
            'marked_status': existing.get(p['number'], 'Absent'),
        })

    return periods


# ── Helper: auto-absent past periods ────────────────────────
def auto_absent_past_periods(student_id, date, attendance_type):
    """
    For every period that has ended today and has NO record,
    insert an Absent record automatically.
    Called on page load so tutors always see a complete picture.
    """
    ist = pytz.timezone('Asia/Kolkata')
    now = datetime.now(ist)
    current_time_str = now.strftime('%H:%M')

    existing_periods = {
        r.period_number
        for r in PeriodAttendance.query.filter_by(
            student_id=student_id, date=date, attendance_type=attendance_type
        ).all()
    }

    for p in PERIOD_SCHEDULE:
        if current_time_str > p['end'] and p['number'] not in existing_periods:
            absent = PeriodAttendance(
                student_id=student_id,
                date=date,
                period_number=p['number'],
                status='Absent',
                attendance_type=attendance_type,
                marked_at=None
            )
            db.session.add(absent)

    try:
        db.session.commit()
    except Exception:
        db.session.rollback()


# ════════════════════════════════════════════════════════════
# STUDENT ROUTES
# ════════════════════════════════════════════════════════════

@app.route('/student_category')
def student_category():
    """
    Entry point after student login.
    Day Scholar → auto-redirects to dayscholar attendance page.
    Hosteller   → auto-redirects to hosteller choice page (Regular / Hostel).
    No selection screen is shown to the student.
    """
    if 'user_id' not in session or session.get('role') != 'student':
        return redirect(url_for('student_login'))

    student = Student.query.get(session['user_id'])
    if not student:
        flash("Student not found!", "danger")
        return redirect(url_for('student_login'))

    if student.student_category == 'dayscholar':
        return redirect(url_for('student_attendance_page', attendance_type='dayscholar'))
    else:
        # hosteller → go directly to outpass request page
        return redirect(url_for('student_dashboard'))


@app.route('/student_hosteller_choice')
def student_hosteller_choice():
    """
    For hostellers: Regular Page  |  Hostel Page
    """
    if 'user_id' not in session or session.get('role') != 'student':
        return redirect(url_for('student_login'))

    student = Student.query.get(session['user_id'])
    if not student:
        return redirect(url_for('student_login'))

    return render_template('student_hosteller_choice.html', student=student)


@app.route('/student_attendance_page/<attendance_type>')
def student_attendance_page(attendance_type):
    """
    Attendance page for Day Scholars and Hostellers (Regular).
    attendance_type: 'dayscholar' or 'hosteller'
    """
    if 'user_id' not in session or session.get('role') != 'student':
        return redirect(url_for('student_login'))

    if attendance_type not in ('dayscholar', 'hosteller'):
        flash("Invalid attendance type.", "danger")
        return redirect(url_for('student_category'))

    student = Student.query.get(session['user_id'])
    if not student:
        return redirect(url_for('student_login'))

    ist = pytz.timezone('Asia/Kolkata')
    today = datetime.now(ist).date()

    # Auto-fill Absent for any past period not yet recorded
    auto_absent_past_periods(student.id, today, attendance_type)

    # Build period list
    periods = get_period_info(student.id, today, attendance_type)

    device_id = str(uuid.uuid4())

    return render_template(
        'period_attendance.html',
        student=student,
        periods=periods,
        attendance_type=attendance_type,
        today=today.strftime('%d %B %Y'),
        device_id=device_id,
        college_lat=COLLEGE_LAT,
        college_lon=COLLEGE_LON,
    )


@app.route('/submit_period_attendance', methods=['POST'])
def submit_period_attendance():
    """
    Handles period attendance form submission.
    Validates GPS, prevents re-submission within same period,
    saves Present/Absent for each active period.
    """
    if 'user_id' not in session or session.get('role') != 'student':
        return redirect(url_for('student_login'))

    student = Student.query.get(session['user_id'])
    if not student:
        return redirect(url_for('student_login'))

    attendance_type = request.form.get('attendance_type', 'dayscholar')

    # ── GPS Validation ───────────────────────────────────────
    try:
        lat = float(request.form.get('lat', 0))
        lon = float(request.form.get('lon', 0))
    except (TypeError, ValueError):
        lat = lon = 0.0

    if lat == 0.0 and lon == 0.0:
        flash("Location data missing. Please enable GPS and try again.", "danger")
        return redirect(url_for('student_attendance_page', attendance_type=attendance_type))

    if not is_within_allowed_range(lat, lon, student.gender):
        flash("You must be within the college campus to mark attendance.", "danger")
        return redirect(url_for('student_attendance_page', attendance_type=attendance_type))

    ist = pytz.timezone('Asia/Kolkata')
    now = datetime.now(ist)
    today = now.date()
    current_time_str = now.strftime('%H:%M')

    saved = 0

    for p in PERIOD_SCHEDULE:
        field_name = f'period_{p["number"]}'
        status_value = request.form.get(field_name, 'Absent')

        # Only process periods that are currently active or just ended
        is_active = p['start'] <= current_time_str <= p['end']
        if not is_active:
            continue

        # Check if already marked for this period today
        existing = PeriodAttendance.query.filter_by(
            student_id=student.id,
            date=today,
            period_number=p['number'],
            attendance_type=attendance_type
        ).first()

        if existing:
            # Already marked — do not overwrite
            continue

        new_record = PeriodAttendance(
            student_id=student.id,
            date=today,
            period_number=p['number'],
            status=status_value,
            attendance_type=attendance_type,
            marked_at=now,
            latitude=lat,
            longitude=lon
        )
        db.session.add(new_record)
        saved += 1

    try:
        db.session.commit()
        if saved > 0:
            flash(f"Attendance submitted successfully for {saved} period(s)!", "success")
        else:
            flash("No new periods were submitted (already marked or no active period).", "info")
    except Exception as e:
        db.session.rollback()
        flash(f"Error saving attendance: {str(e)}", "danger")

    return redirect(url_for('student_attendance_page', attendance_type=attendance_type))


# ════════════════════════════════════════════════════════════
# TUTOR ROUTES  (new)
# ════════════════════════════════════════════════════════════

@app.route('/tutor_choice', methods=['GET', 'POST'])
def tutor_choice():
    """
    New entry point after tutor login.
    Shows: Regular Attendance Check  |  Outpass Request Check
    Also handles leave toggle (same as original tutor_dashboard).
    """
    if 'user_id' not in session or session.get('role') != 'tutor':
        return redirect(url_for('tutor_login'))

    tutor = db.session.get(Tutor, session['user_id'])
    if not tutor:
        flash("Tutor not found. Please log in again.", "danger")
        return redirect(url_for('tutor_login'))

    # Handle leave toggle
    if request.method == 'POST' and 'toggle_leave' in request.form:
        tutor.leave_status = not tutor.leave_status
        db.session.commit()
        flash(f"You are now {'on leave' if tutor.leave_status else 'available'}.", "success")
        return redirect(url_for('tutor_choice'))

    return render_template('tutor_choice.html', tutor=tutor)


@app.route('/tutor_outpass', methods=['GET', 'POST'])
def tutor_outpass():
    """
    Wraps the existing tutor_dashboard outpass logic.
    Tutor sees outpass requests; can accept/reject.
    """
    if 'user_id' not in session or session.get('role') != 'tutor':
        return redirect(url_for('tutor_login'))

    tutor = db.session.get(Tutor, session['user_id'])
    if not tutor:
        flash("Tutor not found.", "danger")
        return redirect(url_for('tutor_login'))

    # Handle leave status toggle
    if request.method == 'POST' and 'toggle_leave' in request.form:
        tutor.leave_status = not tutor.leave_status
        db.session.commit()
        flash(f"You are now {'on leave' if tutor.leave_status else 'available'}.", "success")
        return redirect(url_for('tutor_outpass'))

    # Fetch requests
    if tutor.leave_status:
        requests_list = []
    else:
        if tutor.username == 'sports1':
            requests_list = Outpass.query.filter_by(
                student_category='sports', tutor_status='Pending'
            ).all()
        elif tutor.username == 'international':
            requests_list = Outpass.query.filter_by(
                student_category='international', tutor_status='Pending'
            ).all()
        else:
            if not tutor.department:
                flash("Your department is not assigned. Contact the admin.", "danger")
                return redirect(url_for('logout'))
            requests_list = Outpass.query.filter(
                Outpass.department == tutor.department,
                Outpass.student_category.notin_(['sports', 'international']),
                Outpass.tutor_status == 'Pending'
            ).all()

    # Accept/Reject actions
    if request.method == 'POST' and 'request_id' in request.form and 'action' in request.form:
        try:
            request_id = request.form['request_id']
            action = request.form['action']
            tutor_status = 'Accepted' if action == 'Accept' else 'Rejected'

            outpass = db.session.get(Outpass, request_id)

            is_authorized = False
            if tutor.username == 'sports1' and outpass.student_category == 'sports':
                is_authorized = True
            elif tutor.username == 'international' and outpass.student_category == 'international':
                is_authorized = True
            elif (tutor.department == outpass.department and
                  outpass.student_category not in ['sports', 'international']):
                is_authorized = True

            if outpass and is_authorized:
                outpass.tutor_status = tutor_status
                db.session.commit()
                flash(f"Request {tutor_status.lower()} successfully!", "success")
            else:
                flash("Unauthorized action.", "danger")
        except Exception as e:
            flash(f"Error occurred: {e}", "danger")

        return redirect(url_for('tutor_outpass'))

    # Reuse tutor_dashboard.html (existing template — no changes needed)
    return render_template('tutor_dashboard.html', tutor=tutor, requests=requests_list)


@app.route('/tutor_attendance_view')
def tutor_attendance_view():
    """
    Tutor views regular class attendance of their department's students.
    Supports filtering by date, category, and period.
    """
    if 'user_id' not in session or session.get('role') != 'tutor':
        return redirect(url_for('tutor_login'))

    tutor = db.session.get(Tutor, session['user_id'])
    if not tutor:
        flash("Tutor not found.", "danger")
        return redirect(url_for('tutor_login'))

    ist = pytz.timezone('Asia/Kolkata')
    today_str = datetime.now(ist).date().strftime('%Y-%m-%d')

    # Filters from query params
    selected_date_str = request.args.get('date', today_str)
    selected_category = request.args.get('category', 'all')
    selected_period   = request.args.get('period', 'all')

    try:
        from datetime import date as date_type
        selected_date = datetime.strptime(selected_date_str, '%Y-%m-%d').date()
    except ValueError:
        selected_date = datetime.now(ist).date()
        selected_date_str = today_str

    # ── Fetch students in this tutor's department ────────────
    student_query = Student.query.filter_by(department=tutor.department)

    if selected_category != 'all':
        student_query = student_query.filter_by(student_category=selected_category)

    students = student_query.all()

    # ── Fetch period records for the selected date ───────────
    student_ids = [s.id for s in students]

    pa_records = PeriodAttendance.query.filter(
        PeriodAttendance.student_id.in_(student_ids),
        PeriodAttendance.date == selected_date
    ).all()

    # Build a quick lookup: {student_id: {period_number: status}}
    record_map = {}
    for r in pa_records:
        record_map.setdefault(r.student_id, {})[r.period_number] = r.status

    # Build result rows
    result = []
    for s in students:
        periods_dict = record_map.get(s.id, {})
        present_count = sum(1 for v in periods_dict.values() if v == 'Present')

        if selected_period != 'all':
            # Only include students who have a record for that period
            # (show all students regardless — mark N/A if missing)
            pass

        result.append({
            'student': s,
            'periods': periods_dict,   # {1: 'Present', 2: 'Absent', ...}
            'present_count': present_count,
        })

    # Sort: students with some attendance first
    result.sort(key=lambda x: -x['present_count'])

    stats = {
        'total':   len(result),
        'present': sum(1 for r in result if r['present_count'] > 0),
        'absent':  sum(1 for r in result if r['present_count'] == 0),
    }

    return render_template(
        'tutor_attendance_view.html',
        tutor=tutor,
        students=result,
        selected_date=selected_date_str,
        selected_category=selected_category,
        selected_period=selected_period,
        today=today_str,
        stats=stats,
    )


# ════════════════════════════════════════════════════════════
# Tutor Attendance — Filtered Results Page
# ════════════════════════════════════════════════════════════
@app.route('/tutor_attendance_results')
def tutor_attendance_results():
    """Shows filtered attendance results on a separate page."""
    if 'user_id' not in session or session.get('role') != 'tutor':
        return redirect(url_for('tutor_login'))

    tutor = db.session.get(Tutor, session['user_id'])
    if not tutor:
        flash("Tutor not found.", "danger")
        return redirect(url_for('tutor_login'))

    ist = pytz.timezone('Asia/Kolkata')
    today_str = datetime.now(ist).date().strftime('%Y-%m-%d')

    selected_date_str = request.args.get('date', today_str)
    selected_category = request.args.get('category', 'all')
    selected_period   = request.args.get('period', 'all')

    try:
        selected_date = datetime.strptime(selected_date_str, '%Y-%m-%d').date()
    except ValueError:
        selected_date = datetime.now(ist).date()
        selected_date_str = today_str

    student_query = Student.query.filter_by(department=tutor.department)
    if selected_category != 'all':
        student_query = student_query.filter_by(student_category=selected_category)

    students = student_query.all()
    student_ids = [s.id for s in students]

    pa_records = PeriodAttendance.query.filter(
        PeriodAttendance.student_id.in_(student_ids),
        PeriodAttendance.date == selected_date
    ).all()

    record_map = {}
    for r in pa_records:
        record_map.setdefault(r.student_id, {})[r.period_number] = r.status

    result = []
    for s in students:
        periods_dict = record_map.get(s.id, {})
        present_count = sum(1 for v in periods_dict.values() if v == 'Present')
        result.append({
            'student': s,
            'periods': periods_dict,
            'present_count': present_count,
        })

    result.sort(key=lambda x: -x['present_count'])

    return render_template(
        'tutor_attendance_results.html',
        tutor=tutor,
        students=result,
        selected_date=selected_date_str,
        selected_category=selected_category,
        selected_period=selected_period,
        today=today_str,
    )


# ════════════════════════════════════════════════════════════
# Tutor Attendance — Full Table Page
# ════════════════════════════════════════════════════════════
@app.route('/tutor_attendance_full')
def tutor_attendance_full():
    """Shows the complete attendance table for today (all students, all periods)."""
    if 'user_id' not in session or session.get('role') != 'tutor':
        return redirect(url_for('tutor_login'))

    tutor = db.session.get(Tutor, session['user_id'])
    if not tutor:
        flash("Tutor not found.", "danger")
        return redirect(url_for('tutor_login'))

    ist = pytz.timezone('Asia/Kolkata')
    today = datetime.now(ist).date()
    today_str = today.strftime('%Y-%m-%d')

    students = Student.query.filter_by(department=tutor.department).all()
    student_ids = [s.id for s in students]

    pa_records = PeriodAttendance.query.filter(
        PeriodAttendance.student_id.in_(student_ids),
        PeriodAttendance.date == today
    ).all()

    record_map = {}
    for r in pa_records:
        record_map.setdefault(r.student_id, {})[r.period_number] = r.status

    result = []
    for s in students:
        periods_dict = record_map.get(s.id, {})
        present_count = sum(1 for v in periods_dict.values() if v == 'Present')
        result.append({
            'student': s,
            'periods': periods_dict,
            'present_count': present_count,
        })

    result.sort(key=lambda x: -x['present_count'])

    stats = {
        'total':   len(result),
        'present': sum(1 for r in result if r['present_count'] > 0),
        'absent':  sum(1 for r in result if r['present_count'] == 0),
    }

    return render_template(
        'tutor_attendance_full.html',
        tutor=tutor,
        students=result,
        selected_date=today_str,
        today=today_str,
        stats=stats,
    )


# ════════════════════════════════════════════════════════════
# Tutor Attendance — Download Excel
# ════════════════════════════════════════════════════════════
@app.route('/tutor_attendance_excel')
def tutor_attendance_excel():
    """Downloads attendance data as an Excel file."""
    if 'user_id' not in session or session.get('role') != 'tutor':
        return redirect(url_for('tutor_login'))

    tutor = db.session.get(Tutor, session['user_id'])
    if not tutor:
        flash("Tutor not found.", "danger")
        return redirect(url_for('tutor_login'))

    import pandas as pd
    from io import BytesIO

    ist = pytz.timezone('Asia/Kolkata')
    today_str = datetime.now(ist).date().strftime('%Y-%m-%d')
    selected_date_str = request.args.get('date', today_str)

    try:
        selected_date = datetime.strptime(selected_date_str, '%Y-%m-%d').date()
    except ValueError:
        selected_date = datetime.now(ist).date()
        selected_date_str = today_str

    students = Student.query.filter_by(department=tutor.department).all()
    student_ids = [s.id for s in students]

    pa_records = PeriodAttendance.query.filter(
        PeriodAttendance.student_id.in_(student_ids),
        PeriodAttendance.date == selected_date
    ).all()

    record_map = {}
    for r in pa_records:
        record_map.setdefault(r.student_id, {})[r.period_number] = r.status

    rows = []
    for s in students:
        periods_dict = record_map.get(s.id, {})
        row = {
            'Name': s.name,
            'Roll Number': s.roll_number,
            'Department': s.department,
            'Category': s.student_category,
        }
        for p in range(1, 9):
            row[f'Period {p}'] = periods_dict.get(p, '-')
        row['Total Present'] = sum(1 for v in periods_dict.values() if v == 'Present')
        rows.append(row)

    df = pd.DataFrame(rows)
    output = BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df.to_excel(writer, index=False, sheet_name='Attendance')
    output.seek(0)

    filename = f"attendance_{tutor.department}_{selected_date_str}.xlsx"
    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name=filename
    )


if __name__ == "__main__":
    app.run(debug=True)

