import streamlit as st
import google.generativeai as genai
import PyPDF2
import json
import time   # Tambah ini untuk fungsi rehat/tunggu
import random # Tambah ini untuk pilih API key rawak
import csv # Tambah ini
import io  # Tambah ini

# --- 1. SETTING TAJUK WEB ---
st.set_page_config(page_title="RG Datasheet Extractor", page_icon="📄")
st.title("📄 RG Datasheet Extractor")
st.write("Upload a datasheet (PDF) and the AI will extract the key specifications.")

# --- 1.5 INISIALISASI MEMORI (SESSION STATE) ---
if "reset_key" not in st.session_state:
    st.session_state.reset_key = 0
if "history" not in st.session_state:
    st.session_state.history = []

# --- PAPARAN HISTORY DI SIDEBAR ---
with st.sidebar:
    st.header("🕰️ Extraction History")
    if st.session_state.history:
        # Paparkan senarai dari yang paling baru (terbalikkan senarai)
        for idx, item in enumerate(reversed(st.session_state.history)):
            st.write(f"• {item}")
        
        if st.button("🗑️ Clear History"):
            st.session_state.history = []
            st.rerun() # Refresh page
    else:
        st.info("No search record yet.")

# --- 2. SETTING API KEY (ROTATION) ---
try:
    # Ambil senarai API key dan pilih secara rawak untuk jimat kuota
    api_keys = st.secrets["GEMINI_API_KEY"].split(",")
    selected_key = random.choice(api_keys).strip()
    genai.configure(api_key=selected_key)
    
    model = genai.GenerativeModel('gemini-3.6-flash')
except KeyError:
    st.error("⚠️ Sila masukkan GEMINI_API_KEY di dalam Streamlit Secrets.")
    st.stop()
    
# --- 3 & 4. BUTANG RESET, INPUT MPN & UPLOAD ---
if st.button("🔄 Reset"):
    st.session_state.reset_key += 1
    st.rerun() # Refresh page untuk kosongkan form

# Perhatikan kita tambah parameter `key` menggunakan reset_key
target_mpn = st.text_input("Enter specific MPN (Optional but recommended for catalogs):", key=f"mpn_{st.session_state.reset_key}")
uploaded_file = st.file_uploader("Upload Datasheet PDF here", type=["pdf"], key=f"pdf_{st.session_state.reset_key}")

if uploaded_file is not None:
    if st.button("Extract Data", type="primary"):
        with st.spinner("Reading PDF and extracting data... Please wait."):
            try:
                reader = PyPDF2.PdfReader(uploaded_file)
                pdf_text = "".join([page.extract_text() + "\n" for page in reader.pages if page.extract_text()])
                
                mpn_instruction = f"Focus ONLY on the specifications for this specific MPN: {target_mpn}." if target_mpn else "Extract the general specifications from the datasheet."
                
                full_prompt = f"""
                Act as an expert electronics engineer. {mpn_instruction}
                Review the provided datasheet text and accurately extract the requested information. 
                
                Extract these exact keys:
                "Designation",
                "Operating Temperature (Max) (°C)", "Operating Temperature (Min) (°C)", 
                "Storage Temperature (Max) (°C)", "Storage Temperature (Min) (°C)", 
                "Length (mm)", "Width (mm)", "Height (Max)", "Height (mm)", 
                "Package Type", "Package Type (EIA)", "Pitch (Footprint) (mm)", "Number of Pins", 
                "Resistance (Ohm)", "Tolerance (%)", "Voltage (V)", "Function", 
                "Power Consumption (W)", "Temperature Coefficient (ppm/K)"

                Important Instructions:
                - Return strictly a valid JSON object with the keys above.
                - FOR ALL OTHER KEYS: Return a nested JSON object with two fields: "value" (the string value, or "N/A") and "evidence" (a short exact quote from the text to prove the value).
                  * Example format -> "Voltage (V)": {{"value": "50", "evidence": "Operating voltage, Umax AC/DC, STANDARD 50 V"}}
                - FOR THE "Function" KEY: Select ONLY ONE: "Thin Film", "Thick Film", "Metal Foil", "Wire-wound", or "Carbon Film".
                - FOR HEIGHT DIMENSIONS: Strictly extract values associated with the label "H" or "Height". Do NOT extract values from "T" (Thickness/Terminal).
                - FOR VOLTAGE AND POWER: If the datasheet lists multiple operation modes (e.g., "Standard" vs "Extended"), strictly extract the values for the "Standard" operation mode. Do not extract the Extended or maximum rating if a Standard mode is available.
                - FOR THE "Designation" KEY: Construct a string following EXACTLY this format: 
                  [Resistance] [Tolerance] [Temperature coefficient] [Power] [Package EIA] [Additional Info]
                  * Note 1: If Resistance is 0 Ohm, use the maximal applicable current instead of Power.
                  * Note 2: For [Additional Info], scan the datasheet and append these tags if applicable (separate multiple tags with '/'): HF, PP, HP, HV, AS, FT, SM, AIN, AU, AG, CU, AQ.
                  * Example output: 3R6 1% 100ppm 0.250W 1206 PP/HP
                
                Datasheet Text:
                -----------------
                {pdf_text}
                """
                
              # --- SISTEM AUTO-RETRY UNTUK ELAK LIMIT ---
                max_retries = 3
                retry_delay = 15 # saat
                
                extracted_data = None
                
                for attempt in range(max_retries):
                    try:
                        response = model.generate_content(
                            full_prompt,
                            generation_config={
                                "temperature": 0.0,
                                "response_mime_type": "application/json"
                            }
                        )
                        extracted_data = json.loads(response.text)
                        break # Berjaya! Keluar dari loop
                        
                    except Exception as e:
                        if "429" in str(e) or "Quota" in str(e):
                            if attempt < max_retries - 1:
                                st.warning(f"Exceed API limit. System will auto try in {retry_delay} seconds... (Trial {attempt+1}/{max_retries})")
                                time.sleep(retry_delay)
                            else:
                                st.error("Failed after 3 trials. Rilex & wait for a minute, then try again.")
                                st.stop() # Hentikan proses supaya tak keluar NameError
                        else:
                            st.error(f"API Error: {e}")
                            st.stop()
                
                # Jika sistem gagal sepenuhnya selepas 3 kali, pastikan kod berhenti
                if not extracted_data:
                    st.stop()
                
              # Tukar JSON dari AI
                extracted_data = json.loads(response.text)
                
                # Asingkan Designation
                designation_text = extracted_data.pop("Designation", "N/A")
                if isinstance(designation_text, dict): # Jika AI terbuat nested JSON
                    designation_text = designation_text.get("value", "N/A")
                designation_text = str(designation_text).upper()
                
                st.success("Extraction Complete!")
                
                # Simpan History
                rekod_mpn = target_mpn.upper() if target_mpn else "General (No MPN)"
                if rekod_mpn not in st.session_state.history:
                    st.session_state.history.append(rekod_mpn)
                
                st.info(f"**Standardized Designation:** {designation_text}")
                
                keys_top = ["Operating Temperature (Max) (°C)", "Operating Temperature (Min) (°C)", "Storage Temperature (Max) (°C)", "Storage Temperature (Min) (°C)"]
                keys_library = ["Length (mm)", "Width (mm)", "Height (Max)", "Package Type (EIA)", "Pitch (Footprint) (mm)", "Number of Pins"]
                keys_techn = ["Resistance (Ohm)", "Tolerance (%)", "Voltage (V)", "Function", "Package Type", "Power Consumption (W)", "Temperature Coefficient (ppm/K)", "Height (mm)"]

                # Fungsi bina jadual baru (termasuk Evidence)
                def build_table(keys_list, data_dict):
                    specs, values, units, evidences = [], [], [], []
                    for key in keys_list:
                        # Dapatkan Value dan Evidence
                        item = data_dict.get(key, {"value": "N/A", "evidence": "N/A"})
                        if isinstance(item, str):
                            val, ev = item, "N/A"
                        else:
                            val = item.get("value", "N/A")
                            ev = item.get("evidence", "N/A")
                            
                        # Asingkan Unit
                        unit_str = "-"
                        if "(°C)" in key: key, unit_str = key.replace(" (°C)", ""), "°C"
                        elif "(mm)" in key: key, unit_str = key.replace(" (mm)", ""), "mm"
                        elif "(Ohm)" in key: key, unit_str = key.replace(" (Ohm)", ""), "Ohm"
                        elif "(%)" in key: key, unit_str = key.replace(" (%)", ""), "%"
                        elif "(V)" in key: key, unit_str = key.replace(" (V)", ""), "V"
                        elif "(W)" in key: key, unit_str = key.replace(" (W)", ""), "W"
                        elif "(ppm/K)" in key: key, unit_str = key.replace(" (ppm/K)", ""), "ppm/K"
                        
                        specs.append(key)
                        values.append(val)
                        units.append(unit_str)
                        evidences.append(ev)
                        
                    return {"Specification": specs, "Extracted Value": values, "Unit": units, "Source Evidence": evidences}

                tab1, tab2, tab3 = st.tabs(["Top", "Library", "Techn.Parameter"])
                with tab1: st.table(build_table(keys_top, extracted_data))
                with tab2: st.table(build_table(keys_library, extracted_data))
                with tab3: st.table(build_table(keys_techn, extracted_data))
                
                # --- JANA FAIL EXCEL (CSV) ---
                all_keys = keys_top + keys_library + keys_techn
                all_data = build_table(all_keys, extracted_data)
                
                csv_buffer = io.StringIO()
                writer = csv.writer(csv_buffer)
                writer.writerow(["Specification", "Extracted Value", "Unit", "Source Evidence"]) # Header
                
                for i in range(len(all_data["Specification"])):
                    writer.writerow([all_data["Specification"][i], all_data["Extracted Value"][i], all_data["Unit"][i], all_data["Source Evidence"][i]])
                
                st.divider()
                st.download_button(
                    label="📥 Download Report (CSV / Excel)",
                    data=csv_buffer.getvalue(),
                    file_name=f"{rekod_mpn}_Report.csv",
                    mime="text/csv"
                )
                
            except Exception as e:
                st.error(f"Error Happened!: {e}")
