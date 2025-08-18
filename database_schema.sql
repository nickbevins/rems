-- Physics Database Schema for Radiology Equipment Management
-- This schema supports equipment tracking, compliance testing, and reporting

-- Equipment Classes (Lookup Table)
CREATE TABLE equipment_classes (
    id INT PRIMARY KEY AUTO_INCREMENT,
    class_name VARCHAR(100) NOT NULL,
    subclass_name VARCHAR(100),
    description TEXT,
    INDEX idx_class_name (class_name)
);

-- Manufacturers (Lookup Table)
CREATE TABLE manufacturers (
    id INT PRIMARY KEY AUTO_INCREMENT,
    manufacturer_name VARCHAR(100) NOT NULL UNIQUE,
    contact_info TEXT,
    INDEX idx_manufacturer_name (manufacturer_name)
);

-- Facilities (Lookup Table)
CREATE TABLE facilities (
    id INT PRIMARY KEY AUTO_INCREMENT,
    facility_name VARCHAR(200) NOT NULL,
    facility_code VARCHAR(50),
    address TEXT,
    PRIMARY KEY (id),
    INDEX idx_facility_name (facility_name)
);

-- Departments (Lookup Table)
CREATE TABLE departments (
    id INT PRIMARY KEY AUTO_INCREMENT,
    department_name VARCHAR(100) NOT NULL,
    facility_id INT,
    description TEXT,
    FOREIGN KEY (facility_id) REFERENCES facilities(id),
    INDEX idx_department_name (department_name)
);

-- Main Equipment Table
CREATE TABLE equipment (
    eq_id INT PRIMARY KEY AUTO_INCREMENT,
    eq_class VARCHAR(100) NOT NULL,
    eq_subclass VARCHAR(100),
    eq_manu VARCHAR(100),
    eq_mod VARCHAR(200),
    eq_dept VARCHAR(100),
    eq_rm VARCHAR(100),
    eq_fac VARCHAR(200),
    eq_address TEXT,
    
    -- Contact Information
    eq_contact VARCHAR(200),
    eq_contactinfo TEXT,
    eq_sup VARCHAR(200),
    eq_supinfo TEXT,
    eq_physician VARCHAR(200),
    eq_physicianinfo TEXT,
    
    -- Asset Information
    eq_assetid VARCHAR(100),
    eq_sn VARCHAR(200),
    eq_mefac VARCHAR(100),
    eq_mereg VARCHAR(100),
    eq_mefacreg VARCHAR(100),
    eq_manid VARCHAR(100),
    
    -- Important Dates
    eq_mandt DATE,
    eq_instdt DATE,
    eq_eoldate DATE,
    eq_eeoldate DATE,
    eq_retdate DATE,
    eq_retired BOOLEAN DEFAULT FALSE,
    
    -- Compliance Information
    eq_auditfreq INT DEFAULT 12, -- months
    eq_acrsite VARCHAR(100),
    eq_acrunit VARCHAR(100),
    eq_servlogin VARCHAR(100),
    eq_servpwd VARCHAR(100),
    
    -- Technical Specifications
    eq_radcap INT,
    eq_capcat INT,
    eq_capcst INT,
    
    -- Notes
    eq_notes TEXT,
    
    -- Foreign Keys (for normalized data)
    eq_cls_id INT,
    eq_cls_subid INT,
    eq_manu_id INT,
    eq_fac_id INT,
    eq_dept_id INT,
    
    -- Metadata
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    
    -- Indexes for performance
    INDEX idx_eq_class (eq_class),
    INDEX idx_eq_manu (eq_manu),
    INDEX idx_eq_dept (eq_dept),
    INDEX idx_eq_fac (eq_fac),
    INDEX idx_eq_retired (eq_retired),
    INDEX idx_eq_instdt (eq_instdt),
    INDEX idx_eq_eoldate (eq_eoldate),
    INDEX idx_eq_auditfreq (eq_auditfreq),
    
    -- Foreign Key Constraints
    FOREIGN KEY (eq_cls_id) REFERENCES equipment_classes(id),
    FOREIGN KEY (eq_manu_id) REFERENCES manufacturers(id),
    FOREIGN KEY (eq_fac_id) REFERENCES facilities(id),
    FOREIGN KEY (eq_dept_id) REFERENCES departments(id)
);

-- Compliance Testing Records
CREATE TABLE compliance_tests (
    test_id INT PRIMARY KEY AUTO_INCREMENT,
    eq_id INT NOT NULL,
    test_type VARCHAR(100) NOT NULL,
    test_date DATE NOT NULL,
    next_due_date DATE,
    test_status ENUM('Scheduled', 'In Progress', 'Completed', 'Failed', 'Overdue') DEFAULT 'Scheduled',
    test_results TEXT,
    performed_by VARCHAR(200),
    notes TEXT,
    
    -- Metadata
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    
    FOREIGN KEY (eq_id) REFERENCES equipment(eq_id) ON DELETE CASCADE,
    INDEX idx_eq_id (eq_id),
    INDEX idx_test_date (test_date),
    INDEX idx_next_due_date (next_due_date),
    INDEX idx_test_status (test_status)
);

-- Testing Schedule/Templates
CREATE TABLE test_schedules (
    schedule_id INT PRIMARY KEY AUTO_INCREMENT,
    eq_class VARCHAR(100) NOT NULL,
    test_type VARCHAR(100) NOT NULL,
    frequency_months INT NOT NULL,
    description TEXT,
    is_mandatory BOOLEAN DEFAULT TRUE,
    
    INDEX idx_eq_class (eq_class),
    INDEX idx_test_type (test_type)
);

-- Users/Staff (for access control and tracking)
CREATE TABLE users (
    user_id INT PRIMARY KEY AUTO_INCREMENT,
    username VARCHAR(100) NOT NULL UNIQUE,
    email VARCHAR(200) NOT NULL UNIQUE,
    full_name VARCHAR(200),
    role ENUM('Admin', 'Physics Staff', 'Technician', 'Viewer') DEFAULT 'Viewer',
    department VARCHAR(100),
    is_active BOOLEAN DEFAULT TRUE,
    
    -- Metadata
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    
    INDEX idx_username (username),
    INDEX idx_email (email),
    INDEX idx_role (role)
);

-- Audit Log for changes
CREATE TABLE audit_log (
    log_id INT PRIMARY KEY AUTO_INCREMENT,
    table_name VARCHAR(100) NOT NULL,
    record_id INT NOT NULL,
    action ENUM('INSERT', 'UPDATE', 'DELETE') NOT NULL,
    changed_by INT,
    changed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    old_values JSON,
    new_values JSON,
    
    FOREIGN KEY (changed_by) REFERENCES users(user_id),
    INDEX idx_table_record (table_name, record_id),
    INDEX idx_changed_at (changed_at)
);

-- Views for common queries
CREATE VIEW equipment_with_next_test AS
SELECT 
    e.*,
    MIN(ct.next_due_date) as next_test_due,
    COUNT(ct.test_id) as total_tests
FROM equipment e
LEFT JOIN compliance_tests ct ON e.eq_id = ct.eq_id
WHERE e.eq_retired = FALSE
GROUP BY e.eq_id;

CREATE VIEW overdue_equipment AS
SELECT 
    e.*,
    ct.test_type,
    ct.next_due_date,
    DATEDIFF(CURDATE(), ct.next_due_date) as days_overdue
FROM equipment e
JOIN compliance_tests ct ON e.eq_id = ct.eq_id
WHERE ct.next_due_date < CURDATE() 
  AND ct.test_status != 'Completed'
  AND e.eq_retired = FALSE;

CREATE VIEW upcoming_tests AS
SELECT 
    e.*,
    ct.test_type,
    ct.next_due_date,
    DATEDIFF(ct.next_due_date, CURDATE()) as days_until_due
FROM equipment e
JOIN compliance_tests ct ON e.eq_id = ct.eq_id
WHERE ct.next_due_date BETWEEN CURDATE() AND DATE_ADD(CURDATE(), INTERVAL 30 DAY)
  AND ct.test_status != 'Completed'
  AND e.eq_retired = FALSE
ORDER BY ct.next_due_date;