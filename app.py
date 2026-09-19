import streamlit as st, sqlite3, uuid, hashlib, base64, requests
from datetime import datetime, date
import pandas as pd, random
from urllib.parse import quote_plus
from geopy.distance import geodesic
import math

st.set_page_config(page_title="Beacon of Hope - TeleCare", layout="wide", page_icon="🏥")

st.markdown("""
<style>
.stApp {background: linear-gradient(180deg,#f7fbff 0%,#ffffff 100%);}
h1,h2,h3 {color:#0a4a8a!important;}
.stButton>button {background:#0a4a8a; color:white; border-radius:8px; font-weight:600;}
.card {background:white; padding:18px; border-radius:14px; box-shadow:0 4px 14px rgba(10,74,138,0.08); border:1px solid #e6f0ff; margin-bottom:12px;}
</style>
""", unsafe_allow_html=True)

# --- HOSPITAL LOCATION (Beacon of Hope, Ongata Rongai) ---
HOSPITAL_LAT = -1.3927
HOSPITAL_LNG = 36.7578
HOSPITAL_ADDRESS = "Beacon of Hope Hospital, Ongata Rongai, Kenya"

DB="beacon_v2.db"
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
    if not c.execute("SELECT * FROM api_config").fetchone():
        c.execute("INSERT INTO api_config VALUES (?,?,?,?,?)", ("174379","your_consumer_key","your_consumer_secret","your_passkey","your_google_maps_api_key"))
    conn.commit(); conn.close()
init_db()

# --- AUTO DISTANCE CALCULATION ---
def geocode_address(address, google_key):
    """Try Google Geocoding, fallback to Nominatim"""
    try:
        if google_key and "your_google" not in google_key:
            url = f"https://maps.googleapis.com/maps/api/geocode/json?address={quote_plus(address)}&key={google_key}"
            r = requests.get(url, timeout=10).json()
            if r.get("status")=="OK":
                loc=r["results"][0]["geometry"]["location"]
                return loc["lat"], loc["lng"]
        # Fallback: Nominatim (free, no key)
        url = f"https://nominatim.openstreetmap.org/search?format=json&q={quote_plus(address + ', Kenya')}"
        r = requests.get(url, headers={"User-Agent":"BeaconApp"}, timeout=10).json()
        if r:
            return float(r[0]["lat"]), float(r[0]["lon"])
    except: pass
    return None, None

def get_distance_km_auto(patient_address, google_key):
    lat, lng = geocode_address(patient_address, google_key)
    if lat is None:
        return None, None, None
    # 1. Try Google Distance Matrix if key exists
    dist_km = None
    if google_key and "your_google" not in google_key:
        try:
            url = f"https://maps.googleapis.com/maps/api/distancematrix/json?origins={HOSPITAL_LAT},{HOSPITAL_LNG}&destinations={lat},{lng}&key={google_key}"
            r = requests.get(url, timeout=10).json()
            if r.get("status")=="OK" and r["rows"][0]["elements"][0]["status"]=="OK":
                meters = r["rows"][0]["elements"][0]["distance"]["value"]
                dist_km = round(meters/1000, 2)
        except: pass
    # 2. Fallback: straight line + road factor (1.4x)
    if dist_km is None:
        straight = geodesic((HOSPITAL_LAT, HOSPITAL_LNG), (lat, lng)).km
        dist_km = round(straight * 1.4, 2) # road is longer than straight
    return dist_km, lat, lng

def google_maps_link(address): return f"https://www.google.com/maps/search/?api=1&query={quote_plus(address + ', Rongai, Kenya')}"
def google_maps_embed(address): return f"https://www.google.com/maps?q={quote_plus(address)}&z=15&output=embed"
def google_directions_link(dest_address): return f"https://www.google.com/maps/dir/?api=1&origin={HOSPITAL_LAT},{HOSPITAL_LNG}&destination={quote_plus(dest_address)}"

# M-Pesa
def get_mpesa_token(key, secret):
    try:
        r = requests.get("https://sandbox.safaricom.co.ke/oauth/v1/generate?grant_type=client_credentials", auth=(key, secret), timeout=10)
        return r.json().get("access_token")
    except: return None
def stk_push(phone, amount, shortcode, passkey, token):
    phone = phone.strip().replace(" ","")
    if phone.startswith("0"): phone = "254"+phone[1:]
    if phone.startswith("+"): phone = phone[1:]
    ts = datetime.now().strftime("%Y%m%d%H%M%S")
    pwd = base64.b64encode((shortcode+passkey+ts).encode()).decode()
    payload = {"BusinessShortCode": shortcode, "Password": pwd, "Timestamp": ts, "TransactionType": "CustomerPayBillOnline", "Amount": int(amount), "PartyA": phone, "PartyB": shortcode, "PhoneNumber": phone, "CallBackURL": "https://mydomain.com/callback", "AccountReference": "BEACON", "TransactionDesc": "Drug Delivery"}
    headers={"Authorization": f"Bearer {token}"}
    return requests.post("https://sandbox.safaricom.co.ke/mpesa/stkpush/v1/processrequest", json=payload, headers=headers, timeout=15).json()

# --- AUTH ---
if "user" not in st.session_state: st.session_state.user=None
def login_box():
    c1,c2=st.columns(2)
    with c1:
        st.markdown('<div class="card"><h3>🔐 Login</h3></div>', unsafe_allow_html=True)
        phone=st.text_input("Phone / ID")
        pw=st.text_input("Password", type="password")
        if st.button("Login", use_container_width=True):
            conn=sqlite3.connect(DB)
            u=conn.execute("SELECT * FROM users WHERE (phone=? OR id_no=?) AND password=?", (phone, phone, hash_pw(pw))).fetchone()
            conn.close()
            if u: st.session_state.user={"id":u[0],"name":u[1],"phone":u[2],"id_no":u[3],"role":u[4]}; st.rerun()
            else: st.error("Invalid")
    with c2:
        st.markdown("### New Patient?")
        name=st.text_input("Full Name", key="rname"); rphone=st.text_input("Phone", key="rphone")
        id_no=st.text_input("Hospital ID (blank if new)", key="rid"); rpw=st.text_input("Password", type="password", key="rpw")
        if st.button("Create Account", use_container_width=True):
            conn=sqlite3.connect(DB); conn.execute("INSERT INTO users VALUES (?,?,?,?,?,?)", (str(uuid.uuid4()), name, rphone, id_no or f"BOH-{random.randint(10000,99999)}", "patient", hash_pw(rpw))); conn.commit(); conn.close(); st.success("Created! Login now.")

if not st.session_state.user: login_box(); st.stop()
user=st.session_state.user
st.sidebar.write(f"**{user['name']}** `{user['role']}`")
if st.sidebar.button("Logout"): st.session_state.user=None; st.rerun()
st.markdown(f"<h1>Beacon of Hope - TeleCare</h1><p>Auto Distance @ 50 KES/KM</p>", unsafe_allow_html=True)

conn=sqlite3.connect(DB); cfg=conn.execute("SELECT * FROM api_config").fetchone(); conn.close()
google_key=cfg[4]

# ROLES
if user["role"]=="patient":
    t1,t2,t3,t4=st.tabs(["📅 Book","🎥 Video","💊 Tracker","💰 M-Pesa"])
    with t1:
        disease=st.selectbox("Condition", ["Hypertension","Diabetes","HIV","Asthma"]); d=st.date_input("Date"); t=st.selectbox("Time", ["09:00","11:00","14:00"])
        notes=st.text_area("Symptoms")
        if st.button("Book"):
            rid=str(uuid.uuid4()); room=f"BOH-{uuid.uuid4().hex[:6].upper()}"
            conn=sqlite3.connect(DB); conn.execute("INSERT INTO appointments VALUES (?,?,?,?,?,?,?,?,?)", (rid, user["id"], user["name"], disease, str(d), t, "Pending", room, notes)); conn.commit(); conn.close(); st.success(f"Booked Room {room}")
    with t2:
        conn=sqlite3.connect(DB); appts=conn.execute("SELECT * FROM appointments WHERE patient_id=?", (user["id"],)).fetchall(); conn.close()
        for a in appts:
            with st.expander(f"{a[4]} {a[5]} {a[3]} {a[6]}"):
                if a[6]=="Approved": st.components.v1.iframe(f"https://meet.jit.si/{a[7]}", height=450)
    with t3:
        conn=sqlite3.connect(DB); orders=conn.execute("SELECT * FROM pharmacy_orders WHERE patient_id=? ORDER BY rowid DESC", (user["id"],)).fetchall(); conn.close()
        for o in orders:
            st.markdown('<div class="card">', unsafe_allow_html=True)
            st.progress({"Preparing":33,"Dispatched":66,"Delivered":100}.get(o[11],10))
            st.write(f"Order {o[0][:8]} | {o[11]} | Pay {o[13]} | {o[6]} KM = KES {o[8]}")
            st.write(f"📍 {o[5]}"); st.markdown(f"[Open Maps]({google_maps_link(o[5])})")
            st.components.v1.iframe(google_maps_embed(o[5]), height=220)
            st.markdown('</div>', unsafe_allow_html=True)
    with t4:
        conn=sqlite3.connect(DB); orders=conn.execute("SELECT * FROM pharmacy_orders WHERE patient_id=? AND payment_status!='PAID'", (user["id"],)).fetchall(); conn.close()
        for o in orders:
            with st.expander(f"Pay KES {o[9]} - Order {o[0][:8]}"):
                ph=st.text_input("M-Pesa No", value=user["phone"], key=f"ph{o[0]}")
                if st.button(f"Lipa KES {o[9]}", key=f"pay{o[0]}"):
                    token=get_mpesa_token(cfg[1], cfg[2])
                    if not token:
                        conn=sqlite3.connect(DB); conn.execute("UPDATE pharmacy_orders SET payment_status='PAID' WHERE id=?", (o[0],)); conn.commit(); conn.close()
                        st.success("Mock PAID ✅ (add Daraja keys for real STK)")
                    else:
                        resp=stk_push(ph, o[9], cfg[0], cfg[3], token); st.json(resp)

elif user["role"]=="pharmacist":
    conn=sqlite3.connect(DB); df=pd.read_sql("SELECT p.id as pres_id, p.drugs, p.dosage, ap.patient_name, ap.patient_id, ap.phone FROM prescriptions p JOIN appointments ap ON p.appointment_id=ap.id WHERE p.status='Sent to Pharmacy'", conn); conn.close()
    for _, r in df.iterrows():
        with st.expander(f"Rx {r['pres_id'][:8]} - {r['patient_name']} - {r['drugs']}"):
            avail=st.selectbox("Availability", ["Available","Out of Stock"], key=r['pres_id'])
            med_cost=st.number_input("Medicine Cost", value=500.0, key=f"mc{r['pres_id']}")
            address=st.text_input("Patient Address (e.g. Rongai Tuskys, Kware, Maasai Lodge)", key=f"ad{r['pres_id']}")
            if st.button("📍 Calculate Distance Auto", key=f"calc{r['pres_id']}"):
                if not address: st.warning("Enter address first")
                else:
                    with st.spinner("Calculating distance from Beacon Hospital..."):
                        dist, lat, lng = get_distance_km_auto(address, google_key)
                        if dist:
                            st.session_state[f"dist{r['pres_id']}"]=dist
                            st.session_state[f"lat{r['pres_id']}"]=lat
                            st.session_state[f"lng{r['pres_id']}"]=lng
                            st.success(f"Distance: {dist} KM (auto)")
                        else: st.error("Could not geocode address. Try more specific like 'Rongai, Kware'")
            dist=st.session_state.get(f"dist{r['pres_id']}", 5.0)
            lat=st.session_state.get(f"lat{r['pres_id']}", 0.0)
            lng=st.session_state.get(f"lng{r['pres_id']}", 0.0)
            delivery_fee=round(dist*50,2); total=med_cost+delivery_fee
            st.metric("Auto Calculated", f"{dist} KM | Delivery KES {delivery_fee} | Total KES {total}")
            if address: st.markdown(f"[Preview Direction]({google_directions_link(address)})")
            if st.button("Bill & Dispatch", key=f"bill{r['pres_id']}"):
                oid=str(uuid.uuid4())
                conn=sqlite3.connect(DB)
                conn.execute("INSERT INTO pharmacy_orders VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (oid, r['pres_id'], r['patient_id'], r['patient_name'], r['phone'], address, dist, med_cost, delivery_fee, total, avail, "Preparing", None, "UNPAID", lat, lng))
                conn.execute("UPDATE prescriptions SET status='Billed' WHERE id=?", (r['pres_id'],))
                conn.commit(); conn.close()
                st.success(f"Billed KES {total} - Rider will see maps")

elif user["role"]=="rider":
    st.subheader("Rider - Auto Distance Deliveries")
    conn=sqlite3.connect(DB); orders=conn.execute("SELECT * FROM pharmacy_orders WHERE status IN ('Preparing','Dispatched')").fetchall(); conn.close()
    for o in orders:
        with st.expander(f"Order {o[0][:8]} -> {o[3]} | {o[6]} KM | {o[11]} | KES {o[9]}"):
            st.write(f"📍 {o[5]} | Phone {o[4]}")
            st.metric("Fee", f"{o[6]} KM x 50 = KES {o[8]}")
            st.markdown(f"### 🧭 [NAVIGATE - Google Maps Directions]({google_directions_link(o[5])})")
            st.components.v1.iframe(google_maps_embed(o[5]), height=400)
            c1,c2=st.columns(2)
            if c1.button("Dispatched", key=f"di{o[0]}"): conn=sqlite3.connect(DB); conn.execute("UPDATE pharmacy_orders SET status='Dispatched', rider_id=? WHERE id=?", (user["name"], o[0])); conn.commit(); conn.close(); st.rerun()
            if c2.button("Delivered", key=f"de{o[0]}"): conn=sqlite3.connect(DB); conn.execute("UPDATE pharmacy_orders SET status='Delivered', rider_id=? WHERE id=?", (user["name"], o[0])); conn.commit(); conn.close(); st.rerun()

elif user["role"]=="clinician":
    conn=sqlite3.connect(DB); appts=conn.execute("SELECT * FROM appointments WHERE status IN ('Pending','Approved')").fetchall(); conn.close()
    for a in appts:
        with st.expander(f"{a[2]} | {a[3]}"):
            st.components.v1.iframe(f"https://meet.jit.si/{a[7]}", height=380)
            drugs=st.text_input("Drugs", key=f"d{a[0]}"); dosage=st.text_input("Dosage", key=f"do{a[0]}")
            if st.button("Send to Pharmacy", key=f"p{a[0]}"):
                conn=sqlite3.connect(DB); conn.execute("INSERT INTO prescriptions VALUES (?,?,?,?,?,?,?)", (str(uuid.uuid4()), a[0], a[1], drugs, dosage, "Sent to Pharmacy", datetime.now().isoformat())); conn.execute("UPDATE appointments SET status='Approved' WHERE id=?", (a[0],)); conn.commit(); conn.close(); st.success("Sent!")

else: # admin
    conn=sqlite3.connect(DB)
    df_o=pd.read_sql("SELECT * FROM pharmacy_orders", conn)
    cfg=conn.execute("SELECT * FROM api_config").fetchone()
    conn.close()
    st.metric("Total Revenue", f"KES {df_o['total'].sum() if not df_o.empty else 0}")
    st.dataframe(df_o, use_container_width=True)
    st.divider()
    st.subheader("API Keys Config")
    sc=st.text_input("M-Pesa Shortcode", value=cfg[0])
    k=st.text_input("M-Pesa Key", value=cfg[1], type="password")
    sec=st.text_input("M-Pesa Secret", value=cfg[2], type="password")
    pk=st.text_input("M-Pesa Passkey", value=cfg[3], type="password")
    gk=st.text_input("Google Maps API Key (for auto distance)", value=cfg[4], type="password")
    if st.button("Save Keys"):
        conn=sqlite3.connect(DB); conn.execute("UPDATE api_config SET mpesa_shortcode=?, mpesa_key=?, mpesa_secret=?, mpesa_passkey=?, google_key=?", (sc,k,sec,pk,gk)); conn.commit(); conn.close()
        st.success("Saved! If no Google key, app uses free OpenStreetMap + road factor 1.4x - still works")