-- MySQL starter schema (the application creates its mapped tables automatically)
CREATE TABLE users (id INT AUTO_INCREMENT PRIMARY KEY, email VARCHAR(120) NOT NULL UNIQUE,
 password_hash VARCHAR(255) NOT NULL, role VARCHAR(20) NOT NULL, active BOOLEAN NOT NULL DEFAULT TRUE,
 created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL);
CREATE TABLE students (id INT AUTO_INCREMENT PRIMARY KEY, student_code VARCHAR(30) NOT NULL UNIQUE,
 full_name VARCHAR(120) NOT NULL, email VARCHAR(120) NOT NULL UNIQUE, course VARCHAR(100) NOT NULL,
 department VARCHAR(100) NOT NULL, semester INT NOT NULL, division VARCHAR(10) NOT NULL,
 user_id INT NOT NULL UNIQUE, FOREIGN KEY (user_id) REFERENCES users(id));
CREATE TABLE staff (id INT AUTO_INCREMENT PRIMARY KEY, employee_code VARCHAR(30) NOT NULL UNIQUE,
 full_name VARCHAR(120) NOT NULL, email VARCHAR(120) NOT NULL UNIQUE, department VARCHAR(100) NOT NULL,
 user_id INT NOT NULL UNIQUE, FOREIGN KEY (user_id) REFERENCES users(id));
CREATE TABLE attendance (id INT AUTO_INCREMENT PRIMARY KEY, student_id INT NOT NULL, subject VARCHAR(120) NOT NULL,
 attendance_date DATE NOT NULL, period INT NOT NULL, status VARCHAR(10) NOT NULL,
 FOREIGN KEY (student_id) REFERENCES students(id), UNIQUE(student_id, subject, attendance_date, period));
CREATE TABLE marks (id INT AUTO_INCREMENT PRIMARY KEY, student_id INT NOT NULL, subject VARCHAR(120) NOT NULL,
 test1 FLOAT DEFAULT 0, test2 FLOAT DEFAULT 0, assignment FLOAT DEFAULT 0, practical FLOAT DEFAULT 0,
 project FLOAT DEFAULT 0, FOREIGN KEY (student_id) REFERENCES students(id), UNIQUE(student_id, subject));
CREATE TABLE fees (id INT AUTO_INCREMENT PRIMARY KEY, student_id INT NOT NULL UNIQUE, total DECIMAL(10,2) NOT NULL,
 paid DECIMAL(10,2) NOT NULL DEFAULT 0, FOREIGN KEY (student_id) REFERENCES students(id));
