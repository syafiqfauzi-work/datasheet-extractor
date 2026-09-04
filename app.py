import streamlit as st
import google.generativeai as genai
import PyPDF2
import json
import time   # Tambah ini untuk fungsi rehat/tunggu
import random # Tambah ini untuk pilih API key rawak

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
        st.info("No MPN record yet.")

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
                - The values must be strings. If data is missing, use "N/A".
                - FOR THE "Function" KEY: Select ONLY ONE: "Thin Film", "Thick Film", "Metal Foil", "Wire-wound", or "Carbon Film".
                - FOR HEIGHT DIMENSIONS: Strictly extract values associated with the label "H" or "Height". Do NOT extract values from "T" (Thickness/Terminal).
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
                
                # Tukar JSON dari AI kepada jadual Streamlit
                extracted_data = json.loads(response.text)
                
               # Asingkan Designation dan paparkan di atas (huruf besar)
                designation_text = extracted_data.pop("Designation", "N/A").upper()
                
                st.success("Extraction Complete!")
                
                # --- SIMPAN KE HISTORY ---
                rekod_mpn = target_mpn.upper() if target_mpn else "General (No MPN)"
                if rekod_mpn not in st.session_state.history:
                    st.session_state.history.append(rekod_mpn)
                
                st.info(f"**Standardized Designation:** {designation_text}")
                                
                # --- DEFINISI KATEGORI TAB ---
                keys_top = [
                    "Operating Temperature (Max) (°C)", "Operating Temperature (Min) (°C)", 
                    "Storage Temperature (Max) (°C)", "Storage Temperature (Min) (°C)"
                ]
                
                keys_library = [
                    "Length (mm)", "Width (mm)", "Height (Max)", 
                    "Package Type (EIA)", "Pitch (Footprint) (mm)", "Number of Pins"
                ]
                
                keys_techn = [
                    "Resistance (Ohm)", "Tolerance (%)", "Voltage (V)", "Function", 
                    "Package Type", "Power Consumption (W)", "Temperature Coefficient (ppm/K)", "Height (mm)"
                ]

                # Fungsi untuk susun data ke dalam jadual berserta lajur Unit
                def build_table(keys_list, data_dict):
                    specs, values, units = [], [], []
                    for key in keys_list:
                        val = data_dict.get(key, "N/A") # Ambil nilai dari JSON
                        
                        # Asingkan Unit
                        if "(°C)" in key:
                            specs.append(key.replace(" (°C)", ""))
                            units.append("°C")
                        elif "(mm)" in key:
                            specs.append(key.replace(" (mm)", ""))
                            units.append("mm")
                        elif "(Ohm)" in key:
                            specs.append(key.replace(" (Ohm)", ""))
                            units.append("Ohm")
                        elif "(%)" in key:
                            specs.append(key.replace(" (%)", ""))
                            units.append("%")
                        elif "(V)" in key:
                            specs.append(key.replace(" (V)", ""))
                            units.append("V")
                        elif "(W)" in key:
                            specs.append(key.replace(" (W)", ""))
                            units.append("W")
                        elif "(ppm/K)" in key:
                            specs.append(key.replace(" (ppm/K)", ""))
                            units.append("ppm/K")
                        else:
                            specs.append(key)
                            units.append("-")
                            
                        values.append(val)
                        
                    return {"Specification": specs, "Extracted Value": values, "Unit": units}

                # --- BINA TAB DI STREAMLIT ---
                tab1, tab2, tab3 = st.tabs(["Top", "Library", "Techn.Parameter"])
                
                with tab1:
                    st.table(build_table(keys_top, extracted_data))
                
                with tab2:
                    st.table(build_table(keys_library, extracted_data))
                    
                with tab3:
                    st.table(build_table(keys_techn, extracted_data))
                
            except Exception as e:
                # Paparkan ralat jika ada (termasuk sistem retry)
                st.error(f"Error Happened!: {e}")
                
                # Susun data untuk paparan cantik
                table_data = {
                    "Specification": list(extracted_data.keys()),
                    "Extracted Value": list(extracted_data.values())
                }
                
                st.success("Extraction Complete!")
                st.table(table_data) # Ini menjamin jadual sentiasa sama
                
            except Exception as e:
                st.error(f"Error Happened!: {e}")
