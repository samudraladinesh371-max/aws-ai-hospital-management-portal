import json
import pymysql
import os
from datetime import datetime
import traceback


# ================================
# DATABASE CONNECTION
# ================================
def get_db():
    return pymysql.connect(
        host=os.environ["DB_HOST"],
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
        database=os.environ["DB_NAME"],
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=True,
        connect_timeout=5
    )


# ================================
# STANDARD RESPONSE (CORS)
# ================================
def response(status_code, body=None):
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "POST,OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type"
        },
        "body": json.dumps(body) if body is not None else ""
    }


# ================================
# LAMBDA HANDLER
# ================================
def lambda_handler(event, context):
    
    print(f"Received event: {json.dumps(event)}")
    
    try:
        # Handle different event structures
        method = None
        if "requestContext" in event:
            method = event.get("requestContext", {}).get("http", {}).get("method")
        
        # ================================
        # CORS PREFLIGHT
        # ================================
        if method == "OPTIONS":
            return response(200)

        # ================================
        # SAFE BODY PARSING
        # ================================
        body = event.get("body") or {}

        if isinstance(body, str):
            try:
                body = json.loads(body)
            except json.JSONDecodeError:
                print("Failed to parse body as JSON")
                body = {}
        
        print(f"Parsed body: {json.dumps(body)}")
        
        role = body.get("role")
        print(f"Role: {role}")

        # ================================
        # DB CONNECTION
        # ================================
        try:
            conn = get_db()
            cur = conn.cursor()
            print("Database connection successful")
        except Exception as e:
            print(f"Database connection error: {str(e)}")
            print(traceback.format_exc())
            return response(500, {
                "error": "Database connection failed",
                "details": str(e)
            })

        # ================================
        # GET AVAILABLE DOCTORS (for patient registration)
        # ================================
        if role == "get_doctors":
            try:
                cur.execute("""
                    SELECT doctor_id, name, specialization
                    FROM doctors
                    WHERE availability_status = 'AVAILABLE'
                """)
                doctors = cur.fetchall()
                print(f"Found {len(doctors)} available doctors")
                return response(200, {"doctors": doctors})
            except Exception as e:
                print(f"Error in get_doctors: {str(e)}")
                print(traceback.format_exc())
                return response(500, {"error": str(e)})

        # ================================
        # EMERGENCY DASHBOARD - GET AVAILABLE DOCTORS BY DAY
        # ================================
        if role == "get_emergency_doctors":
            try:
                day = body.get("day", datetime.now().strftime("%A"))
                specialization = body.get("specialization")
                
                print(f"Searching doctors for day: {day}, specialization: {specialization}")
                
                # Query doctors available on the specified day (without start_time/end_time)
                query = """
                    SELECT DISTINCT
                        d.doctor_id,
                        d.name,
                        d.specialization,
                        d.phone,
                        d.email,
                        d.availability_status
                    FROM doctors d
                    JOIN doctor_schedules ds ON d.doctor_id = ds.doctor_id
                    WHERE ds.day_of_week = %s
                      AND d.availability_status = 'AVAILABLE'
                """
                
                params = [day]
                
                # Add specialization filter if provided
                if specialization:
                    query += " AND d.specialization = %s"
                    params.append(specialization)
                
                query += " ORDER BY d.specialization, d.name"
                
                print(f"Executing query with params: {params}")
                cur.execute(query, params)
                doctors = cur.fetchall()
                
                print(f"Found {len(doctors)} doctors")
                
                return response(200, {
                    "message": f"Available doctors for {day}",
                    "day": day,
                    "available_doctors": doctors,
                    "total_count": len(doctors)
                })
                
            except Exception as e:
                print(f"Error in get_emergency_doctors: {str(e)}")
                print(traceback.format_exc())
                return response(500, {
                    "error": "Failed to fetch emergency doctors",
                    "details": str(e),
                    "traceback": traceback.format_exc()
                })

        # ================================
        # BOOK EMERGENCY APPOINTMENT
        # ================================
        if role == "book_emergency":
            try:
                # Extract data from request
                doctor_id = body.get("doctor_id")
                patient_name = body.get("patient_name")
                patient_phone = body.get("patient_phone")
                appointment_date = body.get("appointment_date")
                appointment_time = body.get("appointment_time")
                emergency_reason = body.get("emergency_reason")
                status = body.get("status", "SCHEDULED")
                
                print(f"Booking emergency appointment: doctor={doctor_id}, patient={patient_name}")
                
                # Validate required fields
                if not all([doctor_id, patient_name, patient_phone, appointment_date, appointment_time, emergency_reason]):
                    return response(400, {
                        "error": "Missing required fields",
                        "required": ["doctor_id", "patient_name", "patient_phone", "appointment_date", "appointment_time", "emergency_reason"]
                    })
                
                # Get doctor details
                cur.execute("SELECT name, specialization FROM doctors WHERE doctor_id = %s", (doctor_id,))
                doctor = cur.fetchone()
                
                if not doctor:
                    return response(404, {"error": "Doctor not found"})
                
                # Insert into emergency_appointments table
                cur.execute("""
                    INSERT INTO emergency_appointments 
                    (doctor_id, doctor_name, patient_name, patient_phone, 
                     appointment_date, appointment_time, emergency_reason, 
                     specialization, booking_timestamp, status)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW(), %s)
                """, (
                    doctor_id,
                    doctor['name'],
                    patient_name,
                    patient_phone,
                    appointment_date,
                    appointment_time,
                    emergency_reason,
                    doctor['specialization'],
                    status
                ))
                
                emergency_id = cur.lastrowid
                
                print(f"Emergency appointment booked successfully with ID: {emergency_id}")
                
                return response(200, {
                    "message": "Emergency appointment booked successfully",
                    "emergency_id": emergency_id,
                    "patient_name": patient_name,
                    "doctor_name": doctor['name'],
                    "appointment_date": appointment_date,
                    "appointment_time": appointment_time
                })
                
            except Exception as e:
                print(f"Error in book_emergency: {str(e)}")
                print(traceback.format_exc())
                return response(500, {
                    "error": "Failed to book emergency appointment",
                    "details": str(e)
                })

        # ================================
        # GET ALL EMERGENCY APPOINTMENTS
        # ================================
        if role == "get_emergency_appointments":
            try:
                # Optional filters
                doctor_id = body.get("doctor_id")
                date = body.get("date")
                status_filter = body.get("status")
                
                query = """
                    SELECT 
                        emergency_id,
                        doctor_id,
                        doctor_name,
                        patient_name,
                        patient_phone,
                        appointment_date,
                        appointment_time,
                        emergency_reason,
                        specialization,
                        booking_timestamp,
                        status
                    FROM emergency_appointments
                    WHERE 1=1
                """
                
                params = []
                
                if doctor_id:
                    query += " AND doctor_id = %s"
                    params.append(doctor_id)
                
                if date:
                    query += " AND appointment_date = %s"
                    params.append(date)
                
                if status_filter:
                    query += " AND status = %s"
                    params.append(status_filter)
                
                query += " ORDER BY appointment_date DESC, appointment_time DESC"
                
                cur.execute(query, params)
                appointments = cur.fetchall()
                
                return response(200, {
                    "appointments": appointments,
                    "total_count": len(appointments)
                })
                
            except Exception as e:
                print(f"Error in get_emergency_appointments: {str(e)}")
                print(traceback.format_exc())
                return response(500, {
                    "error": "Failed to fetch appointments",
                    "details": str(e)
                })

        # ================================
        # PATIENT REGISTRATION & APPOINTMENT BOOKING
        # ================================
        if role == "patient":
            try:
                pid = "P" + datetime.now().strftime("%Y%m%d%H%M%S")
                
                print(f"Registering patient with ID: {pid}")

                cur.execute("""
                    INSERT INTO patients (patient_id, first_name, last_name, phone, age, gender, email)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                """, (
                    pid,
                    body.get("first_name"),
                    body.get("last_name"),
                    body.get("phone"),
                    body.get("age"),
                    body.get("gender"),
                    body.get("email")
                ))

                cur.execute("""
                    INSERT INTO appointments_registered
                    (patient_id, doctor_id, appointment_date, appointment_time, appointment_reason)
                    VALUES (%s, %s, %s, %s, %s)
                """, (
                    pid,
                    body.get("doctor_id"),
                    body.get("appointment_date"),
                    body.get("appointment_time"),
                    body.get("appointment_reason")
                ))
                
                print(f"Patient registered successfully")

                return response(200, {
                    "message": "Appointment booked successfully",
                    "patient_id": pid
                })

            except KeyError as e:
                print(f"Missing field in patient registration: {str(e)}")
                return response(400, {"error": f"Missing field: {str(e)}"})
            except Exception as e:
                print(f"Error in patient registration: {str(e)}")
                print(traceback.format_exc())
                return response(500, {
                    "error": "Patient registration failed",
                    "details": str(e)
                })

        # ================================
        # DOCTOR DASHBOARD
        # ================================
        if role == "doctor":
            try:
                cur.execute("""
                    SELECT 
                        ar.appointment_time,
                        ar.appointment_reason,
                        p.first_name,
                        p.last_name,
                        p.phone
                    FROM appointments_registered ar
                    JOIN patients p ON ar.patient_id = p.patient_id
                    WHERE ar.doctor_id = %s
                      AND ar.appointment_date = %s
                    ORDER BY ar.appointment_time
                """, (
                    body.get("doctor_id"),
                    body.get("date")
                ))

                rows = cur.fetchall()

                appointments = [{
                    "time": r["appointment_time"],
                    "patient_name": f"{r['first_name']} {r['last_name']}",
                    "phone": r["phone"],
                    "reason": r["appointment_reason"]
                } for r in rows]

                return response(200, {"appointments": appointments})

            except KeyError as e:
                return response(400, {"error": f"Missing field: {str(e)}"})
            except Exception as e:
                print(f"Error in doctor dashboard: {str(e)}")
                print(traceback.format_exc())
                return response(500, {
                    "error": "Failed to load appointments",
                    "details": str(e)
                })

        # ================================
        # INVALID ROLE
        # ================================
        print(f"Invalid role received: {role}")
        return response(400, {"error": "Invalid role", "received_role": role})
        
    except Exception as e:
        print(f"Unexpected error in lambda_handler: {str(e)}")
        print(traceback.format_exc())
        return response(500, {
            "error": "Internal server error",
            "details": str(e),
            "traceback": traceback.format_exc()
        })