import streamlit as st, sqlite3, uuid, hashlib, base64, requests
from datetime import datetime, date
import pandas as pd, random
from urllib.parse import quote_plus
from geopy.distance import geodesic

st.set_page_config(page_title="Beacon of Hope - TeleCare", layout="wide", page_icon="🏥")

st.markdown("""
<style>
.stApp {background: linear-gradient(180deg,#f7fbff 0%,#ffffff 100%);}
h1,h2,h3 {color:#0a4a8a!important;}
.stButton>button {background:#0a4a8a; color:white; border-radius:10px; font-weight:700; padding:8px 16px;}
.stButton>button:hover {background:#08396b;}
.card {background:white; padding:18px; border-radius:14px; box-shadow:0 4px 14px rgba(10,74,138,0.08); border:1px solid #e6f0ff; margin-bottom:12px;}
.badge {padding:6px 12px; border-radius:20px; font-size:12px; font-weight:800; background:#e6f0ff; color:#0a4a8a;}
</style>
""", unsafe_allow_html=True)

HOSPITAL_LAT = -1.3927
HOSPITAL_LNG = 36.7578
HOSPITAL_ADDRESS = "Beacon of Hope Hospital, Ongata Rongai"
DB="beacon_final.db"

def hash_pw(p): return hashlib.sha256(p.encode()).hexdigest()

def init_db():
    conn=sqlite3.connect(DB)
    c=conn.cursor()
    c.execute("CREATE TABLE IF NOT EXISTS users (id TEXT PRIMARY KEY, name TEXT, phone TEXT, id_no TEXT, role TEXT, password TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS appointments (id TEXT PRIMARY KEY, patient_id TEXT, patient_name TEXT, disease TEXT, date TEXT, time TEXT, status TEXT, room TEXT, notes TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS prescriptions (id TEXT PRIMARY KEY, appointment_id TEXT, patient_id TEXT, drugs TEXT, dosage TEXT, status TEXT, created_at TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS pharmacy_orders (id TEXT PRIMARY KEY, prescription_id TEXT, patient_id TEXT, patient_name TEXT, phone TEXT, address TEXT, km REAL, med_cost REAL, delivery_fee REAL, total REAL, availability TEXT, status TEXT, rider_id TEXT, payment_status TEXT, lat REAL, lng REAL)")
    c.execute("CREATE TABLE IF NOT EXISTS lab_requests (id TEXT PRIMARY KEY, appointment_id TEXT, patient_name TEXT, test TEXT, status TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS api_config (mpesa_shortcode TEXT, mpesa_key TEXT, mpesa_secret TEXT, mpesa_passkey TEXT, google_key TEXT)")
    if not c.execute("SELECT * FROM users WHERE role='admin'").fetchone():
        c.execute("INSERT INTO users VALUES (?,?,?,?,?,?)", (str(uuid.uuid4()), "Admin", "0700000000", "ADMIN001", "admin", hash_pw("admin123")))
        c.execute("INSERT INTO users VALUES (?,?,?,?,?,?)", (str(uuid.uuid4()), "Dr. Wafula", "0711000000", "DOC001", "clinician", hash_pw("doc123")))
        c.execute("INSERT INTO users VALUES (?,?,?,?,?,?)", (str(uuid.uuid4()), "Pharmacy", "0712000000", "PHARM001", "pharmacist", hash_pw("pharm123")))
        c.execute("INSERT INTO users VALUES (?,?,?,?,?,?)", (str(uuid.uuid4()), "Rider James", "0713000000", "RIDER001", "rider", hash_pw("rider123")))
        c.execute("INSERT INTO users VALUES (?,?,?,?,?,?)", (str(uuid.uuid4()), "Lab Tech", "0714000000", "LAB001", "lab_technician", hash_pw("lab123")))
        c.execute("INSERT INTO users VALUES (?,?,?,?,?,?)", (str(uuid.uuid4()), "Test Patient", "0715000000", "BOH-12345", "patient", hash_pw("patient123")))
    if not c.execute("SELECT * FROM api_config").fetchone():
        c.execute("INSERT INTO api_config VALUES (?,?,?,?,?)", ("174379","your_key","your_secret","your_passkey",""))
    conn.commit(); conn.close()
init_db()

def geocode_address(address, google_key):
    try:
        if google_key and len(google_key)>10:
            url=f"https://maps.googleapis.com/maps/api/geocode/json?address={quote_plus(address)}&key={google_key}"
            r=requests.get(url,timeout=10).json()
            if r.get("status")=="OK":
                loc=r["results"][0]["geometry"]["location"]
                return loc["lat"], loc["lng"]
        url=f"https://nominatim.openstreetmap.org/search?format=json&q={quote_plus(address + ', Kenya')}"
        r=requests.get(url, headers={"User-Agent":"BeaconApp"}, timeout=10).json()
        if r: return float(r[0]["lat"]), float(r[0]["lon"])
    except: pass
    return None, None

def get_distance_km_auto(addr, google_key):
    lat,lng=geocode_address(addr, google_key)
    if lat is None: return None,None,None
    dist=None
    if google_key and len(google_key)>10:
        try:
            url=f"https://maps.googleapis.com/maps/api/distancematrix/json?origins={HOSPITAL_LAT},{HOSPITAL_LNG}&destinations={lat},{lng}&key={google_key}"
            r=requests.get(url,timeout=10).json()
            if r["rows"][0]["elements"][0]["status"]=="OK":
                dist=round(r["rows"][0]["elements"][0]["distance"]["value"]/1000,2)
        except: pass
    if dist is None:
        straight=geodesic((HOSPITAL_LAT,HOSPITAL_LNG),(lat,lng)).km
        dist=round(straight*1.4,2)
    return dist,lat,lng

def google_directions_link(addr): return f"https://www.google.com/maps/dir/?api=1&origin={HOSPITAL_LAT},{HOSPITAL_LNG}&destination={quote_plus(addr)}"
def google_maps_embed(addr): return f"https://www.google.com/maps?q={quote_plus(addr)}&z=15&output=embed"
def get_mpesa_token(k,s):
    try:
        r=requests.get("https://sandbox.safaricom.co.ke/oauth/v1/generate?grant_type=client_credentials", auth=(k,s), timeout=10)
        return r.json().get("access_token")
    except: return None

# AUTH - FIXED TO ACCEPT WORDS LIKE "admin"
if "user" not in st.session_state: st.session_state.user=None
def login_box():
    c1,c2=st.columns([1,1])
    with c1:
        st.markdown('<div class="card"><h3>🔐 Login</h3><p>Try: admin / admin123</p></div>', unsafe_allow_html=True)
        phone=st.text_input("Phone / ID / Username")
        pw=st.text_input("Password", type="password")
        if st.button("Login", use_container_width=True):
            conn=sqlite3.connect(DB)
            # FIXED QUERY - now accepts role, name, phone, id
            u=conn.execute("SELECT * FROM users WHERE (phone=? OR id_no=? OR LOWER(role)=LOWER(?) OR LOWER(name)=LOWER(?) OR LOWER(name) LIKE LOWER(?)) AND password=?",
                           (phone, phone, phone, phone, f"%{phone}%", hash_pw(pw))).fetchone()
            conn.close()
            if u:
                st.session_state.user={"id":u[0],"name":u[1],"phone":u[2],"id_no":u[3],"role":u[4]}; st.rerun()
            else: st.error("Invalid. Use admin/admin123 or 0700000000/admin123")
    with c2:
        st.markdown("### New Patient? Create Account (if no Hospital ID)")
        name=st.text_input("Full Name", key="rname"); rphone=st.text_input("Phone 07..", key="rphone")
        id_no=st.text_input("Hospital ID (blank if new)", key="rid"); rpw=st.text_input("Password", type="password", key="rpw")
        if st.button("Create Patient Account", use_container_width=True):
            if not name or not rphone or not rpw: st.warning("Fill all")
            else:
                conn=sqlite3.connect(DB); conn.execute("INSERT INTO users VALUES (?,?,?,?,?,?)", (str(uuid.uuid4()), name, rphone, id_no or f"BOH-{random.randint(10000,99999)}", "patient", hash_pw(rpw))); conn.commit(); conn.close(); st.success("Created! Now login on left.")

if not st.session_state.user: login_box(); st.stop()

user=st.session_state.user
st.sidebar.markdown(f"### 🏥 Beacon of Hope\n**{user['name']}**\n`{user['role'].upper()}`\nID: {user['id_no']}")
if st.sidebar.button("Logout"): st.session_state.user=None; st.rerun()

st.markdown(f"<h1>Beacon of Hope - TeleCare</h1><p><span class='badge'>CHRONIC CARE</span> <span class='badge'>DELIVERY 50 KES/KM AUTO</span> <span class='badge'>BLUE & WHITE</span></p>", unsafe_allow_html=True)

conn=sqlite3.connect(DB); cfg=conn.execute("SELECT * FROM api_config").fetchone(); conn.close()
google_key=cfg[4] if cfg else ""

# PATIENT
if user["role"]=="patient":
    t1,t2,t3,t4=st.tabs(["📅 Book","🎥 Video Room","💊 Tracker + Maps","💰 Pay M-Pesa"])
    with t1:
        st.markdown('<div class="card">', unsafe_allow_html=True)
        disease=st.selectbox("Chronic Disease", ["Hypertension","Diabetes","HIV","Asthma","HIV+Hypertension","TB","Diabetes+Hypertension"]); d=st.date_input("Date", value=date.today()); t=st.selectbox("Time", ["09:00","11:00","14:00","15:00"]); notes=st.text_area("Symptoms")
        if st.button("Book Consultation", use_container_width=True):
            rid=str(uuid.uuid4()); room=f"BOH-{uuid.uuid4().hex[:6].upper()}"
            conn=sqlite3.connect(DB); conn.execute("INSERT INTO appointments VALUES (?,?,?,?,?,?,?,?,?)", (rid, user["id"], user["name"], disease, str(d), t, "Pending", room, notes)); conn.commit(); conn.close(); st.success(f"Booked! Room: {room}"); st.balloons()
        st.markdown('</div>', unsafe_allow_html=True)
    with t2:
        conn=sqlite3.connect(DB); appts=conn.execute("SELECT * FROM appointments WHERE patient_id=? ORDER BY date DESC", (user["id"],)).fetchall(); conn.close()
        if not appts: st.info("No bookings yet - book in first tab")
        for a in appts:
            with st.expander(f"{a[4]} {a[5]} | {a[3]} | {a[6]}", expanded=(a[6]=="Approved")):
                if a[6]=="Approved": st.components.v1.iframe(f"https://meet.jit.si/{a[7]}", height=500); st.success(f"Room: {a[7]}")
                else: st.warning(f"Waiting for clinician approval - Room {a[7]} will activate soon")
    with t3:
        conn=sqlite3.connect(DB); orders=conn.execute("SELECT * FROM pharmacy_orders WHERE patient_id=? ORDER BY rowid DESC", (user["id"],)).fetchall(); conn.close()
        if not orders: st.info("No drug deliveries yet - doctor will prescribe after video")
        for o in orders:
            st.markdown('<div class="card">', unsafe_allow_html=True)
            prog={"Preparing":33,"Dispatched":66,"Delivered":100}.get(o[11],10)
            st.progress(prog); st.write(f"**Order {o[0][:8]}** | {o[10]} | Status: **{o[11]}** | Payment: {o[13]}")
            c1,c2,c3=st.columns(3); c1.metric("Distance", f"{o[6]} KM"); c2.metric("Delivery Fee", f"KES {o[8]}"); c3.metric("Total", f"KES {o[9]}")
            st.write(f"📍 {o[5]}"); st.markdown(f"[📍 Open Google Maps]({google_directions_link(o[5])})")
            st.components.v1.iframe(google_maps_embed(o[5]), height=260)
            st.markdown('</div>', unsafe_allow_html=True)
    with t4:
        conn=sqlite3.connect(DB); orders=conn.execute("SELECT * FROM pharmacy_orders WHERE patient_id=? AND payment_status!='PAID' ORDER BY rowid DESC", (user["id"],)).fetchall(); conn.close()
        if not orders: st.success("All bills PAID ✅")
        for o in orders:
            with st.expander(f"Pay KES {o[9]} - Order {o[0][:8]}"):
                ph=st.text_input("M-Pesa Number", value=user["phone"], key=f"ph{o[0]}")
                if st.button(f"Lipa na M-Pesa KES {o[9]}", key=f"pay{o[0]}", use_container_width=True):
                    token=get_mpesa_token(cfg[1], cfg[2]) if cfg else None
                    if not token:
                        conn=sqlite3.connect(DB); conn.execute("UPDATE pharmacy_orders SET payment_status='PAID' WHERE id=?", (o[0],)); conn.commit(); conn.close()
                        st.success("Mock PAID ✅ - Add real Daraja keys in Admin for real STK Push"); st.balloons()
                    else:
                        st.info("STK Push sent - check phone")

# CLINICIAN - FIXED BLANK SCREEN
elif user["role"]=="clinician":
    st.markdown('<div class="card"><h3>👨‍⚕️ Clinician - Video + Prescription → Pharmacy</h3></div>', unsafe_allow_html=True)
    conn=sqlite3.connect(DB); appts=conn.execute("SELECT * FROM appointments ORDER BY rowid DESC").fetchall(); conn.close()
    if not appts: st.info("No patients yet. Create a test patient to see how it works.")
    for a in appts:
        with st.expander(f"Patient: {a[2]} | {a[3]} | {a[4]} {a[5]} | {a[6]}", expanded=True):
            col1,col2=st.columns([2,1])
            with col1:
                st.components.v1.iframe(f"https://meet.jit.si/{a[7]}", height=400)
                drugs=st.text_input("Prescription (Drugs)", key=f"d{a[0]}", placeholder="Metformin 500mg x30, Amlodipine 5mg x30")
                dosage=st.text_input("Dosage Instructions", key=f"do{a[0]}", placeholder="1 tab twice daily after food")
                lab=st.text_input("Lab Test (optional)", key=f"l{a[0]}")
                if st.button("💊 Add Prescription & SEND TO PHARMACY", key=f"p{a[0]}", use_container_width=True):
                    if not drugs: st.warning("Enter drugs")
                    else:
                        conn=sqlite3.connect(DB); conn.execute("INSERT INTO prescriptions VALUES (?,?,?,?,?,?,?)", (str(uuid.uuid4()), a[0], a[1], drugs, dosage, "Sent to Pharmacy", datetime.now().isoformat())); conn.execute("UPDATE appointments SET status='Approved' WHERE id=?", (a[0],))
                        if lab: conn.execute("INSERT INTO lab_requests VALUES (?,?,?,?,?)", (str(uuid.uuid4()), a[0], a[2], lab, "Pending"))
                        conn.commit(); conn.close(); st.success("Sent to pharmacy!"); st.rerun()
            with col2:
                if st.button("✅ Approve Consultation", key=f"ap{a[0]}", use_container_width=True):
                    conn=sqlite3.connect(DB); conn.execute("UPDATE appointments SET status='Approved' WHERE id=?", (a[0],)); conn.commit(); conn.close(); st.rerun()
                st.write(f"Notes: {a[8]}")

# PHARMACIST
elif user["role"]=="pharmacist":
    st.markdown('<div class="card"><h3>💊 Pharmacy - Auto Distance Calculation @ 50 KES/KM</h3></div>', unsafe_allow_html=True)
    conn=sqlite3.connect(DB); df=pd.read_sql("SELECT p.id as pres_id, p.drugs, p.dosage, ap.patient_name, ap.patient_id, ap.phone FROM prescriptions p JOIN appointments ap ON p.appointment_id=ap.id WHERE p.status='Sent to Pharmacy'", conn); conn.close()
    if df.empty: st.info("No prescriptions - waiting for clinician")
    for _, r in df.iterrows():
        with st.expander(f"Rx {r['pres_id'][:8]} - {r['patient_name']} - {r['drugs']}", expanded=True):
            avail=st.selectbox("Availability", ["Available","Out of Stock"], key=r['pres_id'])
            med_cost=st.number_input("Medicine Cost KES", value=600.0, key=f"mc{r['pres_id']}")
            address=st.text_input("Patient Address (e.g. Rongai, Tuskys, Kware)", key=f"ad{r['pres_id']}", placeholder="Type exact area in Rongai")
            if st.button("📍 Calculate Distance AUTO", key=f"calc{r['pres_id']}", use_container_width=True):
                if not address: st.warning("Enter address")
                else:
                    with st.spinner("Calculating distance from Beacon Hospital..."):
                        dist,lat,lng=get_distance_km_auto(address, google_key)
                        if dist: st.session_state[f"dist{r['pres_id']}"]=dist; st.session_state[f"lat{r['pres_id']}"]=lat; st.session_state[f"lng{r['pres_id']}"]=lng; st.success(f"Distance: {dist} KM auto-calculated")
                        else: st.error("Can't find address. Try 'Ongata Rongai Kware' or 'Rongai Maasai Lodge'")
            dist=st.session_state.get(f"dist{r['pres_id']}", 0.0)
            lat=st.session_state.get(f"lat{r['pres_id']}", 0.0)
            lng=st.session_state.get(f"lng{r['pres_id']}", 0.0)
            if dist>0:
                fee=round(dist*50,2); total=med_cost+fee
                st.metric("Auto Bill", f"{dist} KM | Delivery KES {fee} | Total KES {total}")
                st.markdown(f"[Preview Directions]({google_directions_link(address)})")
                if st.button(f"Bill KES {total} & Dispatch to Rider", key=f"bill{r['pres_id']}", use_container_width=True):
                    oid=str(uuid.uuid4())
                    conn=sqlite3.connect(DB); conn.execute("INSERT INTO pharmacy_orders VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (oid, r['pres_id'], r['patient_id'], r['patient_name'], r['phone'], address, dist, med_cost, fee, total, avail, "Preparing", None, "UNPAID", lat, lng)); conn.execute("UPDATE prescriptions SET status='Billed' WHERE id=?", (r['pres_id'],)); conn.commit(); conn.close(); st.success(f"Billed KES {total} - sent to rider"); st.rerun()

# RIDER
elif user["role"]=="rider":
    st.markdown('<div class="card"><h3>🛵 Rider - Live Google Maps Navigation</h3></div>', unsafe_allow_html=True)
    conn=sqlite3.connect(DB); orders=conn.execute("SELECT * FROM pharmacy_orders WHERE status IN ('Preparing','Dispatched')").fetchall(); conn.close()
    if not orders: st.info("No deliveries - waiting for pharmacy")
    for o in orders:
        with st.expander(f"Order {o[0][:8]} -> {o[3]} | {o[6]} KM | KES {o[9]} | {o[11]}", expanded=True):
            st.write(f"Patient: {o[3]} | Phone: {o[4]} | Pay: {o[13]} | Address: {o[5]}")
            st.metric("Delivery Fee", f"{o[6]} KM x 50 = KES {o[8]}")
            st.markdown(f"### 🧭 [CLICK TO NAVIGATE - Google Maps]({google_directions_link(o[5])})")
            st.components.v1.iframe(google_maps_embed(o[5]), height=380)
            c1,c2=st.columns(2)
            if c1.button("Mark Dispatched", key=f"di{o[0]}", use_container_width=True): conn=sqlite3.connect(DB); conn.execute("UPDATE pharmacy_orders SET status='Dispatched', rider_id=? WHERE id=?", (user["name"], o[0])); conn.commit(); conn.close(); st.rerun()
            if c2.button("Mark Delivered ✅", key=f"de{o[0]}", use_container_width=True): conn=sqlite3.connect(DB); conn.execute("UPDATE pharmacy_orders SET status='Delivered', rider_id=? WHERE id=?", (user["name"], o[0])); conn.commit(); conn.close(); st.balloons(); st.rerun()

elif user["role"]=="lab_technician":
    st.subheader("Lab Tech"); conn=sqlite3.connect(DB); df=pd.read_sql("SELECT * FROM lab_requests", conn); conn.close(); st.dataframe(df, use_container_width=True)
else:
    conn=sqlite3.connect(DB); df_o=pd.read_sql("SELECT * FROM pharmacy_orders", conn); cfg=conn.execute("SELECT * FROM api_config").fetchone(); conn.close()
    st.metric("Revenue", f"KES {df_o['total'].sum() if not df_o.empty else 0}"); st.dataframe(df_o, use_container_width=True)
    st.divider(); st.subheader("API Keys")
    sc=st.text_input("M-Pesa Shortcode", value=cfg[0]); k=st.text_input("M-Pesa Key", value=cfg[1], type="password"); s=st.text_input("Secret", value=cfg[2], type="password"); pk=st.text_input("Passkey", value=cfg[3], type="password"); gk=st.text_input("Google Maps Key (optional - for accurate road distance)", value=cfg[4], type="password")
    if st.button("Save Keys"): conn=sqlite3.connect(DB); conn.execute("UPDATE api_config SET mpesa_shortcode=?, mpesa_key=?, mpesa_secret=?, mpesa_passkey=?, google_key=?", (sc,k,s,pk,gk)); conn.commit(); conn.close(); st.success("Saved! Google key not needed - app uses free map if blank")
