from app import app, db, Equipment, ComplianceTest, Personnel
import re

def extract_email_from_info(info_text):
    """Extract email from contact info text"""
    if not info_text:
        return None
    
    # Look for email pattern
    email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
    match = re.search(email_pattern, info_text)
    return match.group() if match else None

def extract_phone_from_info(info_text):
    """Extract phone number from contact info text"""
    if not info_text:
        return None
    
    # Look for phone patterns
    phone_patterns = [
        r'\b\d{3}-\d{3}-\d{4}\b',  # 123-456-7890
        r'\b\(\d{3}\)\s*\d{3}-\d{4}\b',  # (123) 456-7890
        r'\b\d{3}\.\d{3}\.\d{4}\b',  # 123.456.7890
        r'\b\d{10}\b'  # 1234567890
    ]
    
    for pattern in phone_patterns:
        match = re.search(pattern, info_text)
        if match:
            return match.group()
    
    return None

def populate_personnel_from_equipment():
    """Extract personnel data from equipment records and populate Personnel table"""
    
    with app.app_context():
        print("Extracting personnel data from equipment records...")
        
        # Get all equipment records
        equipment_list = Equipment.query.all()
        
        personnel_data = {}  # Use dict to avoid duplicates by email
        
        # Extract contacts
        for eq in equipment_list:
            # Process contact person
            if eq.eq_contact and eq.eq_contact.strip():
                email = extract_email_from_info(eq.eq_contactinfo) if eq.eq_contactinfo else None
                phone = extract_phone_from_info(eq.eq_contactinfo) if eq.eq_contactinfo else None
                
                if email:
                    key = email.lower()
                    if key not in personnel_data:
                        personnel_data[key] = {
                            'name': eq.eq_contact.strip(),
                            'email': email,
                            'phone': phone,
                            'roles': set(['contact'])
                        }
                    else:
                        personnel_data[key]['roles'].add('contact')
            
            # Process supervisor
            if eq.eq_sup and eq.eq_sup.strip():
                email = extract_email_from_info(eq.eq_supinfo) if eq.eq_supinfo else None
                phone = extract_phone_from_info(eq.eq_supinfo) if eq.eq_supinfo else None
                
                if email:
                    key = email.lower()
                    if key not in personnel_data:
                        personnel_data[key] = {
                            'name': eq.eq_sup.strip(),
                            'email': email,
                            'phone': phone,
                            'roles': set(['supervisor'])
                        }
                    else:
                        personnel_data[key]['roles'].add('supervisor')
            
            # Process physician
            if eq.eq_physician and eq.eq_physician.strip():
                email = extract_email_from_info(eq.eq_physicianinfo) if eq.eq_physicianinfo else None
                phone = extract_phone_from_info(eq.eq_physicianinfo) if eq.eq_physicianinfo else None
                
                if email:
                    key = email.lower()
                    if key not in personnel_data:
                        personnel_data[key] = {
                            'name': eq.eq_physician.strip(),
                            'email': email,
                            'phone': phone,
                            'roles': set(['physician'])
                        }
                    else:
                        personnel_data[key]['roles'].add('physician')
        
        # Extract from compliance tests
        compliance_tests = ComplianceTest.query.all()
        for test in compliance_tests:
            if test.performed_by and test.performed_by.strip():
                # Try to extract email from performed_by field
                email = extract_email_from_info(test.performed_by)
                if email:
                    key = email.lower()
                    if key not in personnel_data:
                        personnel_data[key] = {
                            'name': test.performed_by.strip(),
                            'email': email,
                            'phone': None,
                            'roles': set(['qa_technologist'])
                        }
                    else:
                        personnel_data[key]['roles'].add('qa_technologist')
        
        print(f"Found {len(personnel_data)} unique personnel records with emails")
        
        # Add personnel to database
        added_count = 0
        skipped_count = 0
        
        for data in personnel_data.values():
            # Check if personnel already exists
            existing = Personnel.query.filter_by(email=data['email']).first()
            
            if existing:
                # Update roles if new ones found
                existing_roles = set(existing.get_roles_list())
                combined_roles = existing_roles.union(data['roles'])
                existing.set_roles_list(list(combined_roles))
                print(f"Updated roles for {existing.name}: {', '.join(combined_roles)}")
                skipped_count += 1
            else:
                # Create new personnel record
                personnel = Personnel(
                    name=data['name'],
                    email=data['email'],
                    phone=data['phone'],
                )
                personnel.set_roles_list(list(data['roles']))
                
                db.session.add(personnel)
                print(f"Added {personnel.name} ({personnel.email}) with roles: {', '.join(data['roles'])}")
                added_count += 1
        
        try:
            db.session.commit()
            print(f"\nSuccessfully added {added_count} new personnel records")
            print(f"Updated {skipped_count} existing personnel records")
        except Exception as e:
            db.session.rollback()
            print(f"Error committing to database: {e}")
        
        # Show some personnel without emails that were skipped
        print("\nPersonnel found without email addresses (not added):")
        equipment_list = Equipment.query.all()
        no_email_count = 0
        for eq in equipment_list:
            contacts = [
                (eq.eq_contact, eq.eq_contactinfo, 'contact'),
                (eq.eq_sup, eq.eq_supinfo, 'supervisor'),
                (eq.eq_physician, eq.eq_physicianinfo, 'physician')
            ]
            
            for name, info, role in contacts:
                if name and name.strip():
                    email = extract_email_from_info(info) if info else None
                    if not email:
                        print(f"  - {name} ({role}) - No email found")
                        no_email_count += 1
                        if no_email_count >= 10:  # Limit output
                            print("  ... (and more)")
                            break
            if no_email_count >= 10:
                break

if __name__ == '__main__':
    populate_personnel_from_equipment()