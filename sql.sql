-- ============================================================
-- KPRCAS HOSTEL OUTPASS SYSTEM — COMPLETE DATABASE SETUP
-- Drop and recreate for clean setup. Run top to bottom.
-- ============================================================

DROP DATABASE IF EXISTS hosteloutpass;
CREATE DATABASE hosteloutpass CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE hosteloutpass;

-- ── Warden (must exist before outpass FK) ───────────────────
CREATE TABLE warden (
    id       BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    username VARCHAR(100) NOT NULL UNIQUE,
    password VARCHAR(255) NOT NULL,
    email    VARCHAR(100) NOT NULL UNIQUE,
    name     VARCHAR(100) NOT NULL
);

INSERT INTO warden (username, password, email, name) VALUES
('warden1', 'Hostel$2024', 'hostel@kprcas.ac.in',    'Warden One'),
('warden2', 'Hostel$2025', 'warden2@example.com',     'Warden Two');

-- ── Department ───────────────────────────────────────────────
CREATE TABLE department (
    id   INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(100) UNIQUE NOT NULL
);

-- ── Hostel ───────────────────────────────────────────────────
CREATE TABLE hostel (
    id   INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(100) UNIQUE NOT NULL
);

-- ── Tutor ────────────────────────────────────────────────────
CREATE TABLE tutor (
    id            BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    username      TEXT         NOT NULL,
    password      TEXT         NOT NULL,
    email         TEXT         NOT NULL,
    name          TEXT         NOT NULL,
    department    TEXT         NOT NULL,
    leave_status  BOOLEAN      DEFAULT FALSE,
    department_id INT          NULL,
    CONSTRAINT fk_tutor_department FOREIGN KEY (department_id) REFERENCES department(id)
);

INSERT INTO tutor (email, password, username, name, department, leave_status) VALUES
('test1@gmail.com',  'test1',           'test1',  'Vasuki R',           'II_BBA_A',              FALSE),
('test2@gmail.com',  'test2',           'test2',  'Aravind Kumar N',    'II_BBA_LOGISTICS_A',     FALSE),
('test3@gmail.com',  'test3',           'test3',  'Pouline Juliet A',   'II_BBA_WITH_CA_A',       FALSE),
('test4@gmail.com',  'test4',           'test4',  'Soundarya S',        'II_BCOM_A',              FALSE),
('test5@gmail.com',  'test5',           'test5',  'Abinaya K',          'II_BCOM_WITH_CA_A',      FALSE),
('test6@gmail.com',  'test6',           'test6',  'Monica S',           'II_BCOM_WITH_CA_B',      FALSE),
('test7@gmail.com',  'test7',           'test7',  'AMRITHA S',          'II_BCOM_IT_A',           FALSE),
('test8@gmail.com',  'IEuwXs2ttw',      'test8',  'Sivathivya R',       'II_BCOM_PA_A',           FALSE),
('test9@gmail.com',  'malar10205',      'test9',  'Malarvizhi G',       'II_BSC_CDF_A',           FALSE),
('test10@gmail.com', 'kaveA1990*',      'test10', 'Kaveri A',           'II_BSC_CS_A',            FALSE),
('test11@gmail.com', 'mahalingam2020',  'test11', 'Kiruthiga Mahalingam','III_BBA_WITH_CA_A',     FALSE),
('test12@gmail.com', 'haripriyas',      'test12', 'Hari Priya',         'III_BCOM_BA_A',          FALSE),
('test13@gmail.com', 'Ntkxt9EaAf',      'test13', 'SARANYA N',          'III_BCOM_ECOMMERCE_A',   FALSE),
('test14@gmail.com', 'sk2693',          'test14', 'Kowsalya S',         'III_BCOM_IT_A',          FALSE),
('test15@gmail.com', 'vgy3amslLE',      'test15', 'Kavipriya P',        'II_BCA_A',               FALSE),
('test16@gmail.com', 'uV18Ddf2Z3',      'test16', 'Maheshwari D',       'II_BSC_CT_A',            FALSE),
('test17@gmail.com', 'Shakthi@0305',    'test17', 'Shakthikrishna A',   'III_BCOM_WITH_CA_A',     FALSE),
('test18@gmail.com', 'santhikrishna',   'test18', 'Santhi Krishna V',   'III_BCOM_WITH_CA_B',     FALSE),
('test19@gmail.com', 'Gana@9800',       'test19', 'N Ganapathi Ram',    'III_BSC_AIML_A',         FALSE),
('test20@gmail.com', 'cdf@2023',        'test20', 'Iyyappan S',         'III_BSC_CDF_A',          FALSE);

-- ── Student (only hostel / dayscholar categories) ────────────
-- student_category: 'hostel' OR 'dayscholar'  (no sports/international)
CREATE TABLE student (
    id               BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    username         VARCHAR(50),
    password         VARCHAR(50),
    name             VARCHAR(100),
    parent_phone     VARCHAR(15),
    photo            VARCHAR(100),
    roll_number      VARCHAR(20) UNIQUE,
    gender           VARCHAR(10),
    department       VARCHAR(50),
    hostel_name      VARCHAR(50),
    tutor_id         BIGINT UNSIGNED NULL,
    student_category VARCHAR(20)  NOT NULL DEFAULT 'hostel'
                     CHECK (student_category IN ('hostel','dayscholar')),
    room_number      VARCHAR(20)
);

-- 16 hostellers
INSERT INTO student (username, password, name, parent_phone, photo, roll_number, gender, department, hostel_name, tutor_id, student_category, room_number) VALUES
('test1',      'test1@kprcas',      'SIBI V',              '9360590863', 'sibi_v.jpg',              '23PA115',   'Male', 'III_BCOM_PA_B',          'CHERAN',        NULL, 'hostel',     'CH-103'),
('test2',      'test2@kprcas',      'SUDHAKAR A',          '9360590863', 'SUDHAKAR A.jpg',           '23COBA60',  'Male', 'III_BCOM_BA_A',          'CHERAN',        NULL, 'hostel',     'CH-103'),
('test3',      'test3@kprcas',      'DHESIGAN V',          '9360590863', 'DHESIGAN V.jpg',           '23PA032',   'Male', 'III_BCOM_PA_A',          'CHERAN',        NULL, 'hostel',     'CH-202'),
('test4',      'test4@kprcas',      'ELAVARASAN K',        '9360590863', 'ELAVARASAN K.jpg',         '23COBA21',  'Male', 'III_BCOM_BA_A',          'CHERAN',        NULL, 'hostel',     'CH-202'),
('23CA115',    '23CA115@kprcas',    'SRINIVASH V',         '9080534903', 'SRINIVASH V.jpg',          '23CA115',   'Male', 'III_BCOM_WITH_CA_B',     'CHERAN',        NULL, 'hostel',     'CH-202'),
('23BLOG12',   '23BLOG12@kprcas',   'GIRIE PRASANTH A',    '9080534903', 'GIRIE PRASANTH A.jpg',     '23BLOG12',  'Male', 'III_BBA_LOGISTICS_A',   'CHERAN',        NULL, 'hostel',     'CH-203'),
('23BACA18',   '23BACA18@kprcas',   'GOWTHAM KUMAR V',     '9080534903', 'GOWTHAM KUMAR V.jpg',      '23BACA18',  'Male', 'III_BBA_WITH_CA_A',     'CHERAN',        NULL, 'hostel',     'CH-203'),
('23BLOG34',   '23BLOG34@kprcas',   'NIVAS B',             '9080534903', 'NIVAS B.jpg',              '23BLOG34',  'Male', 'III_BBA_LOGISTICS_A',   'CHERAN',        NULL, 'hostel',     'CH-203'),
('23COIT02',   '23COIT02@kprcas',   'ABISHEK R',           '9080534903', 'ABISHEK R.jpg',            '23COIT02',  'Male', 'III_BCOM_IT_A',          'CHERAN',        NULL, 'hostel',     'CH-206'),
('23COIT57',   '23COIT57@kprcas',   'SURYA PRAKASH R',     '9080534903', 'SURYA PRAKASH R.jpg',      '23COIT57',  'Male', 'III_BCOM_IT_A',          'CHERAN',        NULL, 'hostel',     'CH-206'),
('23BACA61',   '23BACA61@kprcas',   'VELLAI DURAI G',      '9080534903', 'VELLAI DURAI G.jpg',       '23BACA61',  'Male', 'III_BBA_WITH_CA_A',     'CHERAN',        NULL, 'hostel',     'CH-206'),
('23COEC07',   '23COEC07@kprcas',   'ARUNBALA K',          '9080534903', 'ARUNBALA K.jpg',           '23COEC07',  'Male', 'III_BCOM_ECOMMERCE_A',  'CHERAN',        NULL, 'hostel',     'CH-207'),
('23AIML08',   '23AIML08@kprcas',   'BARATH A',            '9080534903', 'BARATH A.jpg',             '23AIML08',  'Male', 'III_BSC_AIML_A',         'CHERAN',        NULL, 'hostel',     'CH-207'),
('23COEC48',   '23COEC48@kprcas',   'SHEIK UMAR MOQTHAR J','9080534903', 'SHEIK UMAR MOQTHAR J.jpg', '23COEC48',  'Male', 'III_BCOM_ECOMMERCE_A',  'CHERAN',        NULL, 'hostel',     'CH-208'),
('23BI16',     '23BI16@kprcas',     'HARI R G',            '9080534903', 'HARI R G.jpg',             '23BI16',    'Male', 'III_BCOM_B_AND_I_A',    'CHERAN',        NULL, 'hostel',     'CH-208'),
('24CEC052',   '24CEC052@kprcas',   'SIVASAKTHI K',        '9080534903', 'SIVASAKTHI K.jpg',         '24CEC052',  'Male', 'II_BCOM_ECOMMERCE_A',   'THIRUVALLUVAR', NULL, 'hostel',     'TV-133'),
-- 5 day scholars (no room/hostel needed but kept for schema consistency)
('23BI14',     '23BI14@kprcas',     'DEENA DAYALAN V',     '9080534903', 'DEENA DAYALAN V.jpg',      '23BI14',    'Male', 'III_BCOM_B_AND_I_A',    '',              NULL, 'dayscholar', ''),
('23CA075',    '23CA075@kprcas',    'PRAVEEN KUMAR E',     '9080534903', 'PRAVEEN KUMAR E.jpg',      '23CA075',   'Male', 'III_BCOM_WITH_CA_B',     '',              NULL, 'dayscholar', ''),
('23COIT43',   '23COIT43@kprcas',   'SABHAREESWARAN M',    '9080534903', 'SABHAREESWARAN M.jpg',     '23COIT43',  'Male', 'III_BCOM_IT_A',          '',              NULL, 'dayscholar', ''),
('23COEC43',   '23COEC43@kprcas',   'SANJITH KUMAR P',     '9080534903', 'SANJITH KUMAR P.jpg',      '23COEC43',  'Male', 'III_BCOM_ECOMMERCE_A',  '',              NULL, 'dayscholar', ''),
('23COEC4',    '23COEC4@kprcas',    'KUMAR P',             '9080534903', 'SANJITH KUMAR P.jpg',      '23COEC3',   'Male', 'I_BCOM_ECOMMERCE_A',    '',              NULL, 'dayscholar', '');

-- ── Outpass ──────────────────────────────────────────────────
CREATE TABLE outpass (
    id               BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    student_id       BIGINT UNSIGNED NULL,
    tutor_id         BIGINT UNSIGNED NULL,
    warden_id        BIGINT UNSIGNED NULL,
    name             VARCHAR(100)  NOT NULL,
    gender           VARCHAR(10)   NOT NULL CHECK (gender IN ('Male','Female','Other')),
    student_category VARCHAR(255),
    department       VARCHAR(255),
    room_number      VARCHAR(100)  NOT NULL,
    roll_number      VARCHAR(100)  NOT NULL,
    out_date         DATE          NOT NULL,
    in_date          DATE          NOT NULL,
    out_time         TIME          NOT NULL,
    in_time          TIME          NOT NULL,
    reason           VARCHAR(200)  NOT NULL,
    destination      VARCHAR(200)  NOT NULL,
    tutor_status     VARCHAR(10)   CHECK (tutor_status IN ('Pending','Approved','Rejected','Skipped','Accepted')),
    warden_status    VARCHAR(10)   DEFAULT 'Pending' CHECK (warden_status IN ('Pending','Accepted','Rejected')),
    watchman_status  VARCHAR(3)    DEFAULT 'In'      CHECK (watchman_status IN ('In','Out')),
    rejected_time    TIMESTAMP     NULL,
    outted_time      TIMESTAMP     NULL,
    arrived_time     TIMESTAMP     NULL,
    created_at       TIMESTAMP     DEFAULT CURRENT_TIMESTAMP,
    hostel_name      VARCHAR(255)  NOT NULL,
    photo            VARCHAR(255)  NOT NULL,
    department_id    INT           NULL,
    CONSTRAINT fk_op_student    FOREIGN KEY (student_id)    REFERENCES student(id)    ON DELETE SET NULL,
    CONSTRAINT fk_op_tutor      FOREIGN KEY (tutor_id)      REFERENCES tutor(id)      ON DELETE SET NULL,
    CONSTRAINT fk_op_warden     FOREIGN KEY (warden_id)     REFERENCES warden(id)     ON DELETE SET NULL,
    CONSTRAINT fk_op_department FOREIGN KEY (department_id) REFERENCES department(id) ON DELETE SET NULL
);

CREATE INDEX idx_outpass_student_id  ON outpass(student_id);
CREATE INDEX idx_outpass_tutor_id    ON outpass(tutor_id);
CREATE INDEX idx_outpass_warden_id   ON outpass(warden_id);
CREATE INDEX idx_outpass_roll_number ON outpass(roll_number);
CREATE INDEX idx_outpass_dates       ON outpass(out_date, in_date);
CREATE INDEX idx_outpass_statuses    ON outpass(tutor_status, warden_status, watchman_status);

-- ── Legacy hostel-night attendance (kept for warden dashboard) ─
CREATE TABLE attendance (
    id                  BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    student_id          BIGINT UNSIGNED NOT NULL,
    date                DATE     NOT NULL,
    time                TIME     NOT NULL,
    status              VARCHAR(20) NOT NULL DEFAULT 'Present',
    ip_address          VARCHAR(50),
    latitude            FLOAT,
    longitude           FLOAT,
    user_agent          VARCHAR(200),
    device_id           VARCHAR(64),
    verification_method VARCHAR(20),
    CONSTRAINT fk_attendance_student FOREIGN KEY (student_id) REFERENCES student(id) ON DELETE CASCADE
);

-- ── Watchman ─────────────────────────────────────────────────
CREATE TABLE watchman (
    id       BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    username VARCHAR(100) NOT NULL UNIQUE,
    password VARCHAR(255) NOT NULL,
    name     VARCHAR(100) NOT NULL
);

INSERT INTO watchman (username, password, name) VALUES
('maingate',  'maingate123', 'Watchman One'),
('watchman2', 'password456', 'Watchman Two');

-- ── Period Attendance (new) ───────────────────────────────────
-- student_category here is 'dayscholar' or 'hosteller' (the attendance flow type)
CREATE TABLE period_attendance (
    id               BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    student_id       BIGINT UNSIGNED NOT NULL,
    date             DATE        NOT NULL,
    period_number    TINYINT     NOT NULL COMMENT '1 to 8',
    status           VARCHAR(10) NOT NULL DEFAULT 'Absent' COMMENT 'Present or Absent',
    attendance_type  VARCHAR(20) NOT NULL DEFAULT 'dayscholar' COMMENT 'dayscholar or hosteller',
    marked_at        DATETIME    NULL     COMMENT 'NULL = auto-marked absent',
    latitude         FLOAT       NULL,
    longitude        FLOAT       NULL,
    CONSTRAINT fk_period_att_student
        FOREIGN KEY (student_id) REFERENCES student(id) ON DELETE CASCADE,
    UNIQUE KEY uq_period_entry (student_id, date, period_number, attendance_type)
);

CREATE INDEX idx_pa_student_date ON period_attendance (student_id, date);
CREATE INDEX idx_pa_date_period  ON period_attendance (date, period_number);
CREATE INDEX idx_pa_att_type     ON period_attendance (attendance_type);

-- ── Verify ───────────────────────────────────────────────────
SHOW TABLES;
SELECT id, name, student_category FROM student ORDER BY student_category, id;