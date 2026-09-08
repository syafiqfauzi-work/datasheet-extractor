import streamlit as st
import google.generativeai as genai
import PyPDF2
import json
import time   
import random 
import csv 
import io
import os
from datetime import datetime

# --- 1. SETTING TAJUK WEB ---
st.set_page_config(page_title="RG Datasheet Analyzer", page_icon="📄")
st.title("📄 RG Datasheet Analyzer")
st.write("Upload a datasheet (PDF) and the AI will extract the key specifications.")

# Baca metadata tarikh fail app.py ini terakhir disunting
file_path = __file__
modified_timestamp = os.path.getmtime(file_path)
last_update_date = datetime.fromtimestamp(modified_timestamp).strftime("%d/%m/%Y")

st.write(f"Analyzer last update on: {last_update_date}.")

# --- 2. INISIALISASI MEMORI (SESSION STATE) ---
if "reset_key" not in st.session_state:
    st.session_state.reset_key = 0
if "history" not in st.session_state:
    st.session_state.history = []

# --- PAPARAN HISTORY DI SIDEBAR ---
with st.sidebar:
    st.header("🕰️ Extraction History")
    if st.session_state.history:
        for idx, item in enumerate(reversed(st.session_state.history)):
            st.write(f"• {item}")
        
        if st.button("🗑️ Clear History"):
            st.session_state.history = []
            st.rerun() 
    else:
        st.info("No search record yet.")
  
# --- 3 & 4. BUTANG RESET, INPUT MPN & UPLOAD ---
if st.button("🔄 Reset"):
    st.session_state.reset_key += 1
    st.rerun() 

target_mpn = st.text_input("Enter specific MPN (Optional but recommended for catalogs):", key=f"mpn_{st.session_state.reset_key}")
uploaded_file = st.file_uploader("Upload Datasheet PDF here", type=["pdf"], key=f"pdf_{st.session_state.reset_key}")

if uploaded_file is not None:
    if st.button("Extract Data", type="primary"):
        progress_text = "Starting extraction process..."
        progress_bar = st.progress(0, text=progress_text)
        
        try:
            reader = PyPDF2.PdfReader(uploaded_file)
            
            # --- PENAPIS KESELAMATAN (SECURITY BYPASS) ---
            if reader.is_encrypted:
                try:
                    reader.decrypt("") # Buka kunci AES dengan kata laluan kosong
                except Exception:
                    st.error("Fail PDF ini dikunci dengan kata laluan penuh. Sila cari versi datasheet yang tidak di-encrypt.")
                    st.stop()
            # ---------------------------------------------
            
            pdf_text = ""
            total_pages = len(reader.pages)
            
            # Fasa 1: Membaca PDF (0% - 30%)
            for i, page in enumerate(reader.pages):
                text = page.extract_text()
                if text:
                    pdf_text += f"\n\n--- PAGE {i + 1} ---\n{text}"
                
                prog_val = int(((i + 1) / total_pages) * 30)
                progress_bar.progress(prog_val, text=f"Reading PDF... (Page {i+1}/{total_pages})")
            
            mpn_instruction = f"Focus ONLY on the specifications for this specific MPN: {target_mpn}." if target_mpn else "Extract the general specifications from the datasheet."
            
            full_prompt = f"""
            Act as an expert electronics engineer. {mpn_instruction}
            Review the provided datasheet text and accurately extract the requested information. 
            
            Extract these exact keys:
            "Operating Temperature (Max) (°C)", "Operating Temperature (Min) (°C)", 
            "Storage Temperature (Max) (°C)", "Storage Temperature (Min) (°C)", 
            "Length (mm)", "Width (mm)", "Height (Max)", "Height (mm)", 
            "Package Type", "Package Type (EIA)", "Pitch (Footprint) (mm)", "Number of Pins", "Resistance_Calculation_Logic", 
            "Resistance (Ohm)", "Tolerance (%)", "Voltage (V)", "Function", 
            "Power Consumption (W)", "TCR_Calculation_Logic", "Temperature Coefficient",
            "Kind of Mounting", "Washability", "Varnishability", "St. Solder (Standard Solder)", 
            "Alt. Solder (Alternate Solder)", "Rep. Solder (Repair Solder)", "ESS Suitable", 
            "Max Reflow Cycle (cycles)", "Max Reflow Time (s)", "Max Reflow Temp (°C)",
            "Designation"

            Important Instructions:
            - Return strictly a valid JSON object with the keys above.
            - FOR ALL OTHER KEYS: Return a nested JSON object with three fields: "value" (the string value, or "N/A"), "evidence" (a short exact quote from the text), and "page" (the exact Page number where it was found, e.g., "1", or "N/A").
              * Example format -> "Voltage (V)": {{"value": "50", "evidence": "Operating voltage, Umax AC/DC, STANDARD 50 V", "page": "2"}}
            
            [PROCESSABILITY RULES]
            - FOR "Kind of Mounting": Select ONLY ONE: "SMT (surface-mounting technology)", "THR, PiP (through-hole technology)", "press-fit", "THW (through-hole technology)", "ceramic substrate technology (Chip microwave)", "none", or "fine press-fit".
              * CRITICAL LOGIC: If the datasheet mentions traditional leaded components or soldering via "wave or dipping", select "THW (through-hole technology)". If it explicitly mentions "Through-Hole Reflow", "THR", or "Pin-in-Paste (PiP)", select "THR, PiP (through-hole technology)". If it is a standard surface mount chip/SMD, select "SMT (surface-mounting technology)".
            - FOR "St. Solder (Standard Solder)": Select ONLY ONE: "reflow soldering top / bottom", "reflow soldering top - only", "wave soldering bottom", "manually soldering / bonding", or "no soldering".
            - FOR "Alt. Solder (Alternate Solder)": Select ONLY ONE: "selective hot air soldering", "wave soldering bottom", "selective wave soldering", "manually soldering", or "no soldering".
            - FOR "Rep. Solder (Repair Solder)": Select ONLY ONE: "selective hot air soldering", "manually soldering", or "no soldering".
            - FOR "ESS Suitable": Evaluate the extracted Storage Temperatures. If the Storage Temperature (Min) and Storage Temperature (Max) fall in the range of -20°C to 75°C, select "ESS released". Otherwise, select "not ESS released". If there is no information available for the Storage Temperature, strictly return "N/A".
            - FOR "Washability" and "Varnishability": Select "Yes" or "No" if explicitly stated in the datasheet. If there is no information available regarding washability or varnishability, strictly return "N/A".
            - FOR REFLOW ("Max Reflow Cycle (cycles)", "Max Reflow Time (s)", "Max Reflow Temp (°C)"): Extract ONLY the raw nominal numerical value. Discard any text, units (e.g., seconds, s, °C, cycles), and tolerances (e.g., for "10 ± 1 seconds immersion time", return "10"; for "260 °C ± 5 °C", return "260").
            
            [GENERAL RULES]
            - FOR "Resistance_Calculation_Logic": If a target MPN is provided, you MUST "think out loud" using pure STRING MANIPULATION, not math. 1) Find the 4-digit resistance code (e.g., 1828). 2) Let the first 3 digits be XYZ and the 4th digit be M (e.g., for 1828, XYZ=182, M=8). 3) Apply this STRICT STRING RULE based on M: If M='7' output "0RXYZ"; If M='8' output "XRYZ" (e.g., 1828 -> 1R82); If M='9' output "XYRZ" (e.g., 1829 -> 18R2); If M='0' output "XYZR"; If M='1' output "XKYZ" (e.g., 1821 -> 1K82); If M='2' output "XYKZ" (e.g., 1822 -> 18K2); If M='3' output "XYZK" (e.g., 1823 -> 182K); If M='4' output "XMYZ"; If M='5' output "XYMZ"; If M='6' output "XYZM". Write out the step-by-step substitution.
            - FOR "Resistance (Ohm)": Extract ONLY the final string generated from the XYZ rule in "Resistance_Calculation_Logic". ABSOLUTELY NO DECIMALS.
            - FOR "TCR_Calculation_Logic": You MUST "think out loud". 1) State the decimal resistance. 2) State the Tolerance. 3) Find the EXACT row for the Part No. (e.g., ERJP06) in the Ratings table. 4) Within that specific row, match the Tolerance sub-block. 5) Mathematically evaluate the resistance against the ranges provided (e.g., 1000 Ohms is >= 33 Ohms, so it matches "33Ω ≤ R", NOT R < 33Ω). 6) State the exact T.C.R assigned to that specific range.
            - FOR "Temperature Coefficient": Look STRICTLY at the mathematical range you just determined in "TCR_Calculation_Logic". Extract ONLY the specific T.C.R. value assigned to that exact range. Extract the numerical value TOGETHER WITH its exact unit (e.g., "200 ppm/°C"). Discard "±".
            - FOR DIMENSIONS (Length, Width, Height (mm)): If a value includes a tolerance (e.g., 0.60 ± 0.03), extract ONLY the nominal base value (e.g., 0.60) and discard the tolerance completely.
            - FOR THE "Function" KEY: Select ONLY ONE: "Thin Film", "Thick Film", "Metal Foil", "Wire-wound", or "Carbon Film".
            - FOR HEIGHT DIMENSIONS: Strictly extract values associated with the label "H" or "Height". Do NOT extract values from "T" (Thickness/Terminal).
              * Note 1: FOR "Height (Max)": If the datasheet provides a nominal value with a tolerance (e.g., X ± Y), you MUST calculate the maximum value by adding the positive tolerance to the nominal value (X + Y).
            - FOR "Package Type": Return the value EXACTLY in this format: EIA[Package EIA Size]*. For example, if the size is 0201, return "EIA0201*". Do NOT extract shipping or delivery packaging methods (e.g., Tape and Reel, Paper Taping Reel, Bulk, Tube).
            - FOR "Voltage (V)": CRITICAL - PDF tables are flattened. You MUST scan the "Ratings" table, locate the exact identifier for the target package size (e.g., "ERJP06"), and trace its specific row to find the "Limiting element voltage". Do NOT grab values belonging to other part numbers like ERJPA3 or ERJP03.
            - FOR VOLTAGE AND POWER: If the datasheet lists multiple operation modes (e.g., "Standard" vs "Extended"), strictly extract the values for the "Standard" operation mode. Do not extract the Extended or maximum rating if a Standard mode is available.
              * Note 1: If Power is provided as a fraction (e.g., 1/20, 1/4, 1/8), you MUST calculate and return it strictly as a DECIMAL (e.g., 0.05, 0.25, 0.125) for both the "Power Consumption (W)" key and the "Designation" string.
            - FOR PITCH: "Pitch (Footprint) (mm)" refers STRICTLY to the physical center-to-center distance between the component's terminals/leads. Do NOT extract packaging, tape, or reel pitch dimensions. If terminal pitch is not specified, use "N/A".
            - FOR THE "Designation" KEY: Construct a string following EXACTLY this format: 
              [Resistance] [Tolerance] [Temperature coefficient] [Power] [RAW Package EIA] [Additional Info]
              * Note 1: For [Resistance], strictly use the R/K/M formatted value (e.g., use "5R11", do NOT use "5.11" or "5.11R"). If Resistance is 0 Ohm, use the maximal applicable current instead of Power.
              * Note 2: For [RAW Package EIA], use ONLY the bare numeric code (e.g., 0201, 0402). Do NOT include the "EIA" prefix or the "*" asterisk in this designation string.
              * Note 3: For [Additional Info], scan the datasheet and append the following exact tags if their corresponding features are found (separate multiple tags with '/'): HF, PP, HP, HV, AS, FT, SM, AIN, AU, AG, CU, AQ. If no additional tags apply, leave this section COMPLETELY EMPTY (do NOT write "N/A" at the end of the designation). Evaluate these specific mappings:
                - "HF": High Frequency
                - "PP": High Pulse, Pulse Proof, or Anti Surge
                - "HP": High Power (power higher than standard)
                - "HV": High Voltage
                - "AS": Anti Sulfurated or Anti-Sulfur
                - "FT": Flexiterm, Flexible Termination, or Soft Termination
                - "SM": Special Mounting (Flange, Chassis, Stacked)
                - "AIN": Aluminium Nitride material
                - "AU": Gold (Au) contact surface
                - "AG": Silver (Ag) contact surface
                - "CU": Copper (Cu) contact surface
                - "AQ": Automotive Grade or AEC-Q200 qualified
              * * Note 4: For [Temperature coefficient], use ONLY the numeric value followed by "PPM". You MUST drop the "/K" or "/°C" completely. Example: use "50PPM", NEVER "50PPM/K" or "50PPM/°C".
              * Example output: 5R11 1% 200PPM 0.1W 0603 PP/AQ/AS
            
            Datasheet Text:
            -----------------
            {pdf_text}
            """
            
            # Fasa 2: Menghantar ke AI (30% - 80%)
            progress_bar.progress(40, text="Analyzing datasheet using AI... This may take a minute.")
            
            max_retries = 3
            retry_delay = 15 
            extracted_data = None
            
            for attempt in range(max_retries):
                try:
                    api_keys = st.secrets["GEMINI_API_KEY"].split(",")
                    selected_key = random.choice(api_keys).strip()
                    genai.configure(api_key=selected_key)
                    model = genai.GenerativeModel('gemini-3.5-flash-lite')
                    
                    response = model.generate_content(
                        full_prompt,
                        generation_config={
                            "temperature": 0.0,
                            "response_mime_type": "application/json"
                        }
                    )
                    extracted_data = json.loads(response.text)
                    progress_bar.progress(80, text="AI extraction complete. Parsing data...")
                    break 
                    
                except KeyError:
                    progress_bar.empty()
                    st.error("⚠️ Sila masukkan GEMINI_API_KEY di dalam Streamlit Secrets.")
                    st.stop()
                    
                except Exception as e:
                    if "429" in str(e) or "Quota" in str(e):
                        if attempt < max_retries - 1:
                            progress_bar.progress(40, text=f"API limit reached. Auto-retrying in {retry_delay}s... (Trial {attempt+1}/{max_retries})")
                            time.sleep(retry_delay)
                        else:
                            progress_bar.empty()
                            st.error("Failed after 3 trials. Rilex & wait for a minute, then try again.")
                            st.stop() 
                    else:
                        progress_bar.empty()
                        st.error(f"API Error: {e}")
                        st.stop()
            
            if not extracted_data:
                st.stop()
            
            # Fasa 3: Menyusun UI & CSV (80% - 100%)
            progress_bar.progress(90, text="Building UI tables and CSV report...")
            
            # Asingkan Designation
            designation_text = extracted_data.pop("Designation", "N/A")
            if isinstance(designation_text, dict): 
                designation_text = designation_text.get("value", "N/A")
            designation_text = str(designation_text).upper()
            
            # PENAPIS KETAT: Buang unit /K atau /°C pada PPM
            designation_text = designation_text.replace("PPM/K", "PPM").replace("PPM/°C", "PPM").replace("PPM/C", "PPM")
            
            # Buang kertas conteng AI dari paparan jadual
            extracted_data.pop("TCR_Calculation_Logic", None)
            extracted_data.pop("Resistance_Calculation_Logic", None)
            
            st.success("Extraction Complete!")
            progress_bar.progress(100, text="Done!")
            time.sleep(0.5)
            progress_bar.empty() # Hilangkan bar selepas selesai
            
            # Simpan History
            rekod_mpn = target_mpn.upper() if target_mpn else "General (No MPN)"
            if rekod_mpn not in st.session_state.history:
                st.session_state.history.append(rekod_mpn)
            
            st.info(f"**Standardized Designation:** {designation_text}")
            
            # --- DEFINISI KATEGORI ---
            keys_top = ["Operating Temperature (Max) (°C)", "Operating Temperature (Min) (°C)", "Storage Temperature (Max) (°C)", "Storage Temperature (Min) (°C)"]
            keys_library = ["Length (mm)", "Width (mm)", "Height (Max)", "Package Type (EIA)", "Pitch (Footprint) (mm)", "Number of Pins"]
            keys_processability = ["Kind of Mounting", "Washability", "Varnishability", "St. Solder (Standard Solder)", "Alt. Solder (Alternate Solder)", "Rep. Solder (Repair Solder)", "ESS Suitable", "Max Reflow Cycle (cycles)", "Max Reflow Time (s)", "Max Reflow Temp (°C)"]
            keys_techn = ["Resistance (Ohm)", "Tolerance (%)", "Voltage (V)", "Function", "Package Type", "Power Consumption (W)", "Temperature Coefficient", "Height (mm)"]

            def build_table(keys_list, data_dict):
                specs, values, units, evidences, pages = [], [], [], [], []
                for key in keys_list:
                    item = data_dict.get(key, {"value": "N/A", "evidence": "N/A", "page": "N/A"})
                    if isinstance(item, str):
                        val, ev, pg = item, "N/A", "N/A"
                    else:
                        val = item.get("value", "N/A")
                        ev = item.get("evidence", "N/A")
                        pg = item.get("page", "N/A")
                        
                    # Asingkan Unit
                    unit_str = "-"
                    if key == "Temperature Coefficient" and val != "N/A":
                        if "ppm/°C" in val:
                            val, unit_str = val.replace("ppm/°C", "").strip(), "ppm/°C"
                        elif "ppm/K" in val:
                            val, unit_str = val.replace("ppm/K", "").strip(), "ppm/K"
                        elif "ppm/C" in val: 
                            val, unit_str = val.replace("ppm/C", "").strip(), "ppm/°C"
                            
                    elif "(°C)" in key: key, unit_str = key.replace(" (°C)", ""), "°C"
                    elif "(mm)" in key: key, unit_str = key.replace(" (mm)", ""), "mm"
                    elif "(Ohm)" in key: key, unit_str = key.replace(" (Ohm)", ""), "Ohm"
                    elif "(%)" in key: key, unit_str = key.replace(" (%)", ""), "%"
                    elif "(V)" in key: key, unit_str = key.replace(" (V)", ""), "V"
                    elif "(W)" in key: key, unit_str = key.replace(" (W)", ""), "W"
                    elif "(ppm/K)" in key: key, unit_str = key.replace(" (ppm/K)", ""), "ppm/K"
                    elif "(s)" in key: key, unit_str = key.replace(" (s)", ""), "s"
                    elif "(cycles)" in key: key, unit_str = key.replace(" (cycles)", ""), "cycles"
                    
                    specs.append(key)
                    values.append(val)
                    units.append(unit_str)
                    evidences.append(ev)
                    pages.append(pg)
                    
                return {"Specification": specs, "Extracted Value": values, "Unit": units, "Page": pages, "Source Evidence": evidences}

            # --- 4 TABS UI ---
            tab1, tab2, tab3, tab4 = st.tabs(["Top", "Library", "Processability", "Techn.Parameter"])
            with tab1: st.table(build_table(keys_top, extracted_data))
            with tab2: st.table(build_table(keys_library, extracted_data))
            with tab3: st.table(build_table(keys_processability, extracted_data))
            with tab4: st.table(build_table(keys_techn, extracted_data))
            
            # --- JANA FAIL EXCEL (CSV) ---
            all_keys = keys_top + keys_library + keys_processability + keys_techn
            all_data = build_table(all_keys, extracted_data)
            
            csv_buffer = io.StringIO()
            csv_buffer.write('\ufeff') 
            
            writer = csv.writer(csv_buffer)
            writer.writerow(["Specification", "Extracted Value", "Unit", "Page", "Source Evidence"]) 
            
            for i in range(len(all_data["Specification"])):
                writer.writerow([all_data["Specification"][i], all_data["Extracted Value"][i], all_data["Unit"][i], all_data["Page"][i], all_data["Source Evidence"][i]])
            
            st.divider()
            st.download_button(
                label="📥 Download Report (CSV)",
                data=csv_buffer.getvalue(),
                file_name=f"{rekod_mpn}_Report.csv",
                mime="text/csv"
            )
            
        except Exception as e:
            st.error(f"Error Happened!: {e}")
